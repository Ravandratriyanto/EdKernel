import io
import base64
from flask import Flask, request, jsonify, send_from_directory
from pypdf import PdfReader
from llm.client import generate, chat
from rag.retrieve import retrieve

app = Flask(__name__, static_folder="static")

TUTOR_SYSTEM_PROMPT = (
    "You are a patient, encouraging SAT/A-level tutor. "
    "Teach one concept at a time. After each explanation, ask the student exactly ONE question to check understanding. "
    "When the student answers, give brief feedback and either move to the next concept or re-explain if they struggled. "
    "When the entire topic has been covered and the student understands, end your response with the exact phrase 'Topic complete.'"
)

ALLOWED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PDF_TEXT_LIMIT = 8000

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/upload", methods=["POST"])
def api_upload():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400

    name = file.filename.lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""

    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(file.read()))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return jsonify({"type": "pdf", "text": text[:PDF_TEXT_LIMIT], "name": file.filename})

    if ext in ALLOWED_IMAGES:
        b64 = base64.b64encode(file.read()).decode("utf-8")
        return jsonify({"type": "image", "b64": b64, "name": file.filename})

    return jsonify({"error": f"Unsupported file type: {ext}"}), 400

@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.json
    topic = data.get("topic", "")
    model = data.get("model", "gemma4")
    host = data.get("host", "http://localhost:11434")
    attachment = data.get("attachment")  # {type, text?, b64?, name}

    context_chunks = retrieve(topic)
    context = "\n\n".join(context_chunks) if context_chunks else ""
    context_prefix = f"Reference material:\n{context}\n\n" if context else ""

    user_msg = {"role": "user", "content": f"{context_prefix}Teach me about: {topic}"}
    if attachment:
        _apply_attachment(user_msg, attachment)

    messages = [{"role": "system", "content": TUTOR_SYSTEM_PROMPT}, user_msg]

    response = chat(messages, model=model, host=host)
    messages.append({"role": "assistant", "content": response})

    return jsonify({"response": response, "messages": _strip_images(messages), "done": "Topic complete." in response})

@app.route("/api/reply", methods=["POST"])
def api_reply():
    data = request.json
    messages = data.get("messages", [])
    user_input = data.get("input", "")
    model = data.get("model", "gemma4")
    host = data.get("host", "http://localhost:11434")
    attachment = data.get("attachment")

    user_msg = {"role": "user", "content": user_input}
    if attachment:
        _apply_attachment(user_msg, attachment)

    messages.append(user_msg)
    response = chat(messages, model=model, host=host)
    messages.append({"role": "assistant", "content": response})

    return jsonify({"response": response, "messages": _strip_images(messages), "done": "Topic complete." in response})

@app.route("/api/check", methods=["POST"])
def api_check():
    data = request.json
    question = data.get("question", "")
    answer = data.get("answer", "")
    model = data.get("model", "gemma4")
    host = data.get("host", "http://localhost:11434")
    attachment = data.get("attachment")

    context_chunks = retrieve(question)
    context = "\n\n".join(context_chunks) if context_chunks else ""
    context_prefix = f"Reference material:\n{context}\n\n" if context else ""

    if attachment and attachment.get("type") == "image":
        messages = [
            {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{context_prefix}"
                    f"Question: {question}\n"
                    f"Student's answer: {answer}\n\n"
                    "The student also attached an image for context. "
                    "Is the student's answer correct? Explain briefly."
                ),
                "images": [attachment["b64"]],
            },
        ]
        return jsonify({"response": chat(messages, model=model, host=host)})

    pdf_context = ""
    if attachment and attachment.get("type") == "pdf":
        pdf_context = f"Attached document:\n{attachment['text']}\n\n"

    prompt = (
        f"{context_prefix}{pdf_context}"
        f"Question: {question}\n"
        f"Student's answer: {answer}\n\n"
        "Is the student's answer correct? Explain briefly."
    )
    return jsonify({"response": generate(prompt, model=model, host=host)})

def _apply_attachment(msg: dict, attachment: dict):
    if attachment.get("type") == "image":
        msg["images"] = [attachment["b64"]]
        msg["content"] += f"\n\n(Student attached image: {attachment.get('name', 'image')})"
    elif attachment.get("type") == "pdf":
        msg["content"] += f"\n\nAttached document ({attachment.get('name', 'file')}):\n{attachment['text']}"

def _strip_images(messages: list) -> list:
    """Remove image data from messages before sending back to client to keep payload small."""
    cleaned = []
    for m in messages:
        entry = {"role": m["role"], "content": m["content"]}
        cleaned.append(entry)
    return cleaned

if __name__ == "__main__":
    app.run(debug=True, port=5000)
