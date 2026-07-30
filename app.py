import io
import os
import re
import base64
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from pypdf import PdfReader
from llm.client import generate, chat
from rag.retrieve import retrieve
from vision.image_handler import transcribe

load_dotenv()

_SIGNAL_RE = re.compile(r'\s*\[(CORRECT|WRONG)\]\s*$', re.IGNORECASE)

# Models mimic the bracket convention they see — the [CORRECT]/[WRONG] signal and
# the [Tutor note: ...] lines we inject — and invent markers of their own, e.g.
# [WAITING FOR RESPONSE]. Anchored to a whole line so it can't eat interval
# notation like [0, 5] or a citation mid-sentence.
_STRAY_MARKER_RE = re.compile(r'^[ \t]*\[[A-Z][A-Z0-9 _:-]{2,40}\][ \t]*$\n?', re.MULTILINE)

app = Flask(__name__, static_folder="static")


def _key(data: dict, field: str, env_var: str) -> str:
    """A key typed into the UI wins; otherwise fall back to the one in .env."""
    return (data.get(field) or "").strip() or os.environ.get(env_var, "").strip()

TUTOR_SYSTEM_PROMPT = (
    "You are a Socratic SAT/A-level tutor. Your job is to guide the student to discover answers themselves — never lecture or dump information. "
    "Write in the simplest English you can. Short sentences. Everyday words a 12-year-old would understand. "
    "Never use a long or academic word where a short one works: say 'use' not 'utilise', 'so' not 'therefore', 'find' not 'determine'. "
    "One idea per sentence. No filler, no throat-clearing, no phrases like 'let us consider' or 'it is important to note'. "
    "You may use a subject term (like 'mitochondria' or 'derivative') when it is the thing being taught — but the first time it appears, "
    "immediately explain what it means in plain words. Assume English may be the student's second language. "
    "Every response is one short hint or question (1-2 sentences max) that nudges the student toward the next idea. "
    "End there — do not answer your own question, and do not announce that you are waiting.\n"
    "The ONLY bracketed markers you may ever write are [CORRECT] and [WRONG]. Never invent others such as "
    "[WAITING FOR RESPONSE] or [PAUSE] — they are shown to the student as raw text and look broken.\n"
    "If the student asks for something that is not the lesson — a file, a download, a past paper, or a question about "
    "what this app can do — answer plainly in one or two sentences and say honestly if you cannot do it. Never reply to "
    "that kind of request with a Socratic question, and never attach options to it. Specifically: you cannot fetch, "
    "attach, or produce PDF files. Past papers are a separate feature the student starts from the past-papers control, "
    "and it generates practice questions rather than handing over the original paper. If they ask again after you have "
    "said you cannot, say so once more in plain words — do not steer them back into the lesson as if they had not asked.\n"
    "Multiple-choice options are OPTIONAL. Most turns should not have them. Offer them only when the answer really is "
    "a pick-one-of-a-few, or when the student is stuck and needs the field narrowed:\n"
    "- Offer options when: the answer is one of a few named things (which term, which rule applies, which step comes next, "
    "which line of the working is wrong); or the student has just been wrong twice in a row on the same idea; "
    "or they are brand new to the topic and do not yet have the words to answer freely.\n"
    "- Do NOT offer options when: you are asking them to explain something in their own words; asking what they notice; "
    "asking them to calculate a number or derive an expression (options let them work backwards from the answers instead of "
    "doing the maths); asking for a method with several steps; or you are just affirming a correct answer and moving on.\n"
    "When you do offer options, give 2 to 4 of them, each on its own line, at the end of your response but BEFORE any "
    "[CORRECT] or [WRONG] marker, in this exact format:\n"
    "A) option text\n"
    "B) option text\n"
    "Make one correct and the rest plausible but wrong. Do not label or hint which is correct. "
    "Never use this 'A)' line format for anything else — not for listing points, steps, or examples. Those lines render as "
    "clickable buttons, so a line starting with 'A)' that is not an answer choice will break the interface.\n"
    "Never explain more than one idea per turn. Never give the full answer unprompted. "
    "When the student answers incorrectly, escalate your hints based on how many times they have been wrong in a row:\n"
    "- Wrong once: subtle nudge only, stay indirect.\n"
    "- Wrong twice: name the key concept without fully explaining it.\n"
    "- Wrong three or more times: directly explain the concept they are missing, then ask them to apply it.\n"
    "If they are right, affirm briefly and move to the next idea with another question. "
    "When evaluating a student's answer, end your response with exactly [CORRECT] or [WRONG] on its own line. "
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
    api_key     = _key(data, "api_key", "API_KEY")

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
    api_key      = _key(data, "api_key", "API_KEY")
    attachment   = data.get("attachment")
    vision_model = data.get("vision_model", "")

    context_chunks = retrieve(topic)
    context        = "\n\n".join(context_chunks) if context_chunks else ""
    context_prefix = f"Reference material:\n{context}\n\n" if context else ""

    user_msg = {"role": "user", "content": f"{context_prefix}Teach me about: {topic}"}
    if attachment:
        _apply_attachment(user_msg, attachment, provider, model, host, api_key, vision_model)

    messages = [{"role": "system", "content": TUTOR_SYSTEM_PROMPT}, user_msg]
    response = chat(messages, model=model, host=host, provider=provider, api_key=api_key)
    response, _ = _strip_signal(response)
    messages.append({"role": "assistant", "content": response})

    return jsonify({"response": response, "messages": _strip_images(messages), "done": "Topic complete." in response})

@app.route("/api/reply", methods=["POST"])
def api_reply():
    data         = request.json
    messages     = data.get("messages", [])
    user_input   = data.get("input", "")
    provider     = data.get("provider", "ollama")
    model        = data.get("model", "gemma4")
    host         = data.get("host", "http://localhost:11434")
    api_key      = _key(data, "api_key", "API_KEY")
    attachment   = data.get("attachment")
    vision_model = data.get("vision_model", "")
    wrong_streak = int(data.get("wrong_streak", 0))

    hint_note = ""
    if wrong_streak == 1:
        hint_note = "\n\n[Tutor note: student answered this wrong once — give a slightly more specific clue than your first hint.]"
    elif wrong_streak == 2:
        hint_note = "\n\n[Tutor note: student answered this wrong twice — give a direct clue that names the key concept.]"
    elif wrong_streak >= 3:
        hint_note = "\n\n[Tutor note: student answered this wrong 3+ times — directly explain the concept they are missing, then ask them to apply it.]"

    user_msg = {"role": "user", "content": user_input + hint_note}
    if attachment:
        _apply_attachment(user_msg, attachment, provider, model, host, api_key, vision_model)

    messages.append(user_msg)
    response = chat(messages, model=model, host=host, provider=provider, api_key=api_key)
    response, correct = _strip_signal(response)
    messages.append({"role": "assistant", "content": response})

    return jsonify({
        "response": response,
        "messages": _strip_images(messages),
        "done": "Topic complete." in response,
        "correct": correct,
    })

# ── check endpoint ───────────────────────────────────────────────────────────

@app.route("/api/check", methods=["POST"])
def api_check():
    data       = request.json
    question   = data.get("question", "")
    answer     = data.get("answer", "")
    provider   = data.get("provider", "ollama")
    model      = data.get("model", "gemma4")
    host       = data.get("host", "http://localhost:11434")
    api_key      = _key(data, "api_key", "API_KEY")
    attachment   = data.get("attachment")
    vision_model = data.get("vision_model", "")

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

    # Providers without image input get the question transcribed to text instead.
    image_context = ""
    if attachment and attachment.get("type") == "image":
        image_context = _transcription_note(attachment, provider, model, host, api_key, vision_model).strip() + "\n\n"

    prompt = (
        f"{context_prefix}{pdf_context}{image_context}"
        f"Question: {question}\n"
        f"Student's answer: {answer}\n\n"
        "Is the student's answer correct? Explain briefly."
    )
    return jsonify({"response": generate(prompt, model=model, host=host, provider=provider, api_key=api_key)})

# ── helpers ──────────────────────────────────────────────────────────────────

def _apply_attachment(msg: dict, attachment: dict, provider: str, model: str = "",
                      host: str = "", api_key: str = "", vision_model: str = ""):
    if attachment.get("type") == "image":
        name = attachment.get("name", "image")
        if provider == "ollama":
            msg["images"] = [attachment["b64"]]
            msg["content"] += f"\n\n(Student attached image: {name})"
        else:
            msg["content"] += _transcription_note(attachment, provider, model, host, api_key, vision_model)
    elif attachment.get("type") == "pdf":
        msg["content"] += f"\n\nAttached document ({attachment.get('name', 'file')}):\n{attachment['text']}"

def _transcription_note(attachment: dict, provider: str, model: str, host: str,
                        api_key: str, vision_model: str) -> str:
    """Transcribe an image to text for providers that can't take image input."""
    name = attachment.get("name", "image")
    try:
        text = transcribe(attachment["b64"], name=name, provider=provider,
                          model=model, host=host, api_key=api_key, vision_model=vision_model)
    except Exception as e:
        app.logger.warning("Image transcription failed for %s: %s", name, e)
        return f"\n\n(Student attached image: {name} — could not be read: {e})"
    return f"\n\nThe student attached an image ({name}). Transcription:\n{text}"

def _strip_images(messages: list) -> list:
    return [{"role": m["role"], "content": m["content"]} for m in messages]

def _strip_signal(text: str) -> tuple:
    m = _SIGNAL_RE.search(text)
    if m:
        clean, correct = text[:m.start()], m.group(1).upper() == "CORRECT"
    else:
        clean, correct = text, None
    clean = _STRAY_MARKER_RE.sub('', clean)
    return re.sub(r'\n{3,}', '\n\n', clean).strip(), correct

# ── past papers ─────────────────────────────────────────────────────────────

PAPER_DOMAINS = [
    "physicsandmathstutor.com",
    "savemyexams.co.uk",
    "aqa.org.uk",
    "cambridgeinternational.org",
    "ocr.org.uk",
    "qualifications.pearson.com",
    "collegeboard.org",
    "pastpapers.co",
    "revisely.co.uk",
    "znotes.org",
]

PAPER_GEN_PROMPT = (
    "You are an SAT/A-level exam question writer.\n"
    "Read the content below from past papers and generate {n} multiple-choice questions "
    "that test understanding of key concepts.\n\n"
    "Use this EXACT format — no deviations:\n\n"
    "Q1. Question text here\n"
    "A) First option\n"
    "B) Second option\n"
    "C) Third option\n"
    "D) Fourth option\n"
    "[ANSWER: B]\n\n"
    "Rules:\n"
    "- Number questions Q1, Q2, Q3 etc.\n"
    "- Always exactly 4 options: A B C D\n"
    "- Always end each question with [ANSWER: X] on its own line\n"
    "- One correct answer, three plausible distractors\n"
    "- Match SAT/A-level difficulty\n"
    "- Blank line between questions\n\n"
    "Past paper content:\n{content}"
)

@app.route("/api/papers", methods=["POST"])
def api_papers():
    data        = request.json
    topic       = data.get("topic", "")
    tavily_key  = _key(data, "tavily_key", "TAVILY_KEY")
    n_questions = int(data.get("n_questions", 5))
    provider    = data.get("provider", "ollama")
    model_name  = data.get("model", "gemma4")
    host        = data.get("host", "http://localhost:11434")
    api_key     = _key(data, "api_key", "API_KEY")

    if not topic:
        return jsonify({"error": "No topic provided"}), 400
    if not tavily_key:
        return jsonify({"error": "Tavily API key required"}), 400

    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": tavily_key,
                "query": f"{topic} past paper exam questions SAT A-level",
                "search_depth": "advanced",
                "include_domains": PAPER_DOMAINS,
                "max_results": 6,
            },
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as e:
        return jsonify({"error": f"Search failed: {e}"}), 500

    if not results:
        return jsonify({"error": "No past paper content found for that topic. Try a more specific query."}), 404

    content_parts = [r["content"] for r in results[:5] if r.get("content")]
    sources = [{"title": r.get("title", ""), "url": r.get("url", "")} for r in results[:5]]
    combined = "\n\n---\n\n".join(content_parts)[:7000]

    prompt = PAPER_GEN_PROMPT.format(n=n_questions, content=combined)
    try:
        raw = chat(
            [{"role": "user", "content": prompt}],
            model=model_name, host=host, provider=provider, api_key=api_key,
        )
    except Exception as e:
        return jsonify({"error": f"Question generation failed: {e}"}), 500

    return jsonify({"questions": raw, "sources": sources})


@app.route("/api/papers/hint", methods=["POST"])
def api_papers_hint():
    data         = request.json
    question     = data.get("question", "")
    options      = data.get("options", [])
    chosen       = data.get("chosen", "")
    correct      = data.get("correct", "")
    wrong_streak = int(data.get("wrong_streak", 1))
    provider     = data.get("provider", "ollama")
    model_name   = data.get("model", "gemma4")
    host         = data.get("host", "http://localhost:11434")
    api_key      = _key(data, "api_key", "API_KEY")

    opts_text = "\n".join(f"{o['letter']}) {o['text']}" for o in options)
    if wrong_streak == 1:
        instruction = "Give a subtle hint that nudges the student toward the right thinking. Stay indirect — do not name the concept yet."
    elif wrong_streak == 2:
        instruction = "Name the key concept the student needs but do not give away the answer."
    else:
        instruction = "Directly explain why the chosen option is wrong and explain the correct concept clearly. Then ask the student to confirm they understand."

    messages = [
        {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Past paper question:\n{question}\n\n{opts_text}\n\n"
            f"The student chose: {chosen}\n"
            f"The correct answer is: {correct}\n\n"
            f"{instruction} Write in plain, simple English. Do not end with [CORRECT] or [WRONG]."
        )},
    ]
    response = chat(messages, model=model_name, host=host, provider=provider, api_key=api_key)
    response, _ = _strip_signal(response)
    return jsonify({"response": response})


if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
