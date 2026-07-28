import io
import re
import base64
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from flask import Flask, request, jsonify, send_from_directory
from pypdf import PdfReader
from llm.client import generate, chat
from rag.retrieve import retrieve

app = Flask(__name__, static_folder="static")

TUTOR_SYSTEM_PROMPT = (
    "You are a Socratic SAT/A-level tutor. Your job is to guide the student to discover answers themselves — never lecture or dump information. "
    "Each response must follow this exact structure:\n"
    "1. One short hint or question (1-2 sentences max) that nudges the student toward the next idea.\n"
    "2. Wait for their answer before revealing anything else.\n"
    "Never explain more than one idea per turn. Never give the full answer unprompted. "
    "If the student is wrong, give a small clue and ask again. If they are right, affirm briefly and move to the next idea with another question. "
    "When a process diagram or flowchart would help (cycles, cause-effect, steps), include it as a ```mermaid code block using 'graph TD'. "
    "Mermaid syntax rule: always wrap node labels in double quotes when they contain special characters. Example: A[\"Step one\"] --> B[\"Step two\"]. "
    "NEVER use Mermaid for mathematical function plots — Mermaid cannot draw axes or curves. "
    "For mathematical graphs (plotting functions, comparing curves, showing derivatives), use a ```graph code block containing a plain English description of what to plot. "
    "Example: ```graph\nPlot f(x) = x^2 and f'(x) = 2x on the same axes from x = -3 to x = 3, with a legend\n``` "
    "When the entire topic has been fully explored through dialogue, end your response with the exact phrase 'Topic complete.'"
)

GRAPH_SYSTEM_PROMPT = (
    "You are a Python matplotlib code generator. Output ONLY valid Python code with no explanation and no markdown fences. "
    "The following are already in scope — do NOT import or redefine them: plt, np. "
    "Write only the plotting logic. Rules:\n"
    "- Use LaTeX notation in all labels, titles, and legends: wrap math in $...$. "
    "Example: label=r'$f(x) = x^{2}$'. Always use r-strings for LaTeX.\n"
    "- Do NOT call plt.savefig(), plt.show(), plt.close(), or import anything.\n"
    "- End with plt.tight_layout()."
)

ALLOWED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PDF_TEXT_LIMIT  = 8000

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

# ── file upload ──────────────────────────────────────────────────────────────

@app.route("/api/upload", methods=["POST"])
def api_upload():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400

    name = file.filename.lower()
    ext  = "." + name.rsplit(".", 1)[-1] if "." in name else ""

    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(file.read()))
        text   = "\n".join(page.extract_text() or "" for page in reader.pages)
        return jsonify({"type": "pdf", "text": text[:PDF_TEXT_LIMIT], "name": file.filename})

    if ext in ALLOWED_IMAGES:
        b64 = base64.b64encode(file.read()).decode("utf-8")
        return jsonify({"type": "image", "b64": b64, "name": file.filename})

    return jsonify({"error": f"Unsupported file type: {ext}"}), 400

# ── graph generation ─────────────────────────────────────────────────────────

@app.route("/api/graph", methods=["POST"])
def api_graph():
    data        = request.json
    description = data.get("description", "")
    provider    = data.get("provider", "ollama")
    model       = data.get("model", "gemma4")
    host        = data.get("host", "http://localhost:11434")
    api_key     = data.get("api_key", "")

    if not description:
        return jsonify({"error": "No description provided"}), 400

    messages = [
        {"role": "system", "content": GRAPH_SYSTEM_PROMPT},
        {"role": "user",   "content": f"Generate a graph for: {description}"},
    ]
    raw_code = chat(messages, model=model, host=host, provider=provider, api_key=api_key)

    # Strip accidental markdown fences and any savefig/show/close calls
    code = re.sub(r"^```(?:python)?\n?", "", raw_code.strip())
    code = re.sub(r"\n?```$", "", code)
    code = re.sub(r"plt\.(savefig|show|close)\([^)]*\)\n?", "", code)
    code = re.sub(r"^import .*$", "", code, flags=re.MULTILINE)

    try:
        plt.close("all")
        exec(code, {"plt": plt, "np": np})  # noqa: S102
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        plt.close("all")
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode("utf-8")
        return jsonify({"image": img_b64})
    except Exception as e:
        plt.close("all")
        return jsonify({"error": str(e)}), 500

# ── learn endpoints ──────────────────────────────────────────────────────────

@app.route("/api/start", methods=["POST"])
def api_start():
    data       = request.json
    topic      = data.get("topic", "")
    provider   = data.get("provider", "ollama")
    model      = data.get("model", "gemma4")
    host       = data.get("host", "http://localhost:11434")
    api_key    = data.get("api_key", "")
    attachment = data.get("attachment")

    context_chunks = retrieve(topic)
    context        = "\n\n".join(context_chunks) if context_chunks else ""
    context_prefix = f"Reference material:\n{context}\n\n" if context else ""

    user_msg = {"role": "user", "content": f"{context_prefix}Teach me about: {topic}"}
    if attachment:
        _apply_attachment(user_msg, attachment, provider)

    messages = [{"role": "system", "content": TUTOR_SYSTEM_PROMPT}, user_msg]
    response = chat(messages, model=model, host=host, provider=provider, api_key=api_key)
    messages.append({"role": "assistant", "content": response})

    return jsonify({"response": response, "messages": _strip_images(messages), "done": "Topic complete." in response})

@app.route("/api/reply", methods=["POST"])
def api_reply():
    data       = request.json
    messages   = data.get("messages", [])
    user_input = data.get("input", "")
    provider   = data.get("provider", "ollama")
    model      = data.get("model", "gemma4")
    host       = data.get("host", "http://localhost:11434")
    api_key    = data.get("api_key", "")
    attachment = data.get("attachment")

    user_msg = {"role": "user", "content": user_input}
    if attachment:
        _apply_attachment(user_msg, attachment, provider)

    messages.append(user_msg)
    response = chat(messages, model=model, host=host, provider=provider, api_key=api_key)
    messages.append({"role": "assistant", "content": response})

    return jsonify({"response": response, "messages": _strip_images(messages), "done": "Topic complete." in response})

# ── check endpoint ───────────────────────────────────────────────────────────

@app.route("/api/check", methods=["POST"])
def api_check():
    data       = request.json
    question   = data.get("question", "")
    answer     = data.get("answer", "")
    provider   = data.get("provider", "ollama")
    model      = data.get("model", "gemma4")
    host       = data.get("host", "http://localhost:11434")
    api_key    = data.get("api_key", "")
    attachment = data.get("attachment")

    context_chunks = retrieve(question)
    context        = "\n\n".join(context_chunks) if context_chunks else ""
    context_prefix = f"Reference material:\n{context}\n\n" if context else ""

    if attachment and attachment.get("type") == "image" and provider == "ollama":
        messages = [
            {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{context_prefix}Question: {question}\n"
                    f"Student's answer: {answer}\n\n"
                    "The student also attached an image for context. "
                    "Is the student's answer correct? Explain briefly."
                ),
                "images": [attachment["b64"]],
            },
        ]
        return jsonify({"response": chat(messages, model=model, host=host, provider=provider, api_key=api_key)})

    pdf_context = f"Attached document:\n{attachment['text']}\n\n" if attachment and attachment.get("type") == "pdf" else ""

    prompt = (
        f"{context_prefix}{pdf_context}"
        f"Question: {question}\n"
        f"Student's answer: {answer}\n\n"
        "Is the student's answer correct? Explain briefly."
    )
    return jsonify({"response": generate(prompt, model=model, host=host, provider=provider, api_key=api_key)})

# ── helpers ──────────────────────────────────────────────────────────────────

def _apply_attachment(msg: dict, attachment: dict, provider: str):
    if attachment.get("type") == "image":
        if provider == "ollama":
            msg["images"] = [attachment["b64"]]
        msg["content"] += f"\n\n(Student attached image: {attachment.get('name', 'image')})"
    elif attachment.get("type") == "pdf":
        msg["content"] += f"\n\nAttached document ({attachment.get('name', 'file')}):\n{attachment['text']}"

def _strip_images(messages: list) -> list:
    return [{"role": m["role"], "content": m["content"]} for m in messages]

if __name__ == "__main__":
    app.run(debug=True, port=5000)
