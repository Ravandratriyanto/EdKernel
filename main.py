import argparse
import base64
import os
from pathlib import Path

from dotenv import load_dotenv

from llm.client import generate, chat
from rag.retrieve import retrieve
from vision.image_handler import transcribe
# The module, not the function — the wrapper below shares its name.
from video import video_handler
from video.frame_extractor import ExtractError
# Shared with app.py so the two front ends cannot drift on the verdict signal.
from prompts import (
    build_check_prompt, strip_signal,
    PLAIN_ENGLISH_RULES, TOPIC_COMPLETE_RULE,
)

load_dotenv()

ALLOWED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
ALLOWED_VIDEOS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SAT/A-level LLM tutor")
    parser.add_argument("mode", choices=["learn", "check"])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="Question as typed text")
    source.add_argument("--image", help="Path to a photo of the question")
    source.add_argument("--video", help="Path to a video of the question")
    parser.add_argument("--answer", help="Student's answer (check mode only)")
    parser.add_argument("--ollama-host", default="http://localhost:11434")
    parser.add_argument("--model", default="gemma4")
    parser.add_argument("--provider", choices=["ollama", "groq"], default="ollama")
    parser.add_argument("--api-key", default="", help="Falls back to API_KEY in .env")
    parser.add_argument("--vision-model", default="",
                        help="Overrides the provider's default image model")
    return parser

TUTOR_SYSTEM_PROMPT = (
    "You are a patient, encouraging SAT/A-level tutor. "
    f"{PLAIN_ENGLISH_RULES} "
    "Teach one concept at a time. After each explanation, ask the student exactly ONE question to check understanding. "
    "When the student answers, give brief feedback and either move to the next concept or re-explain if they struggled. "
    f"{TOPIC_COMPLETE_RULE}"
)

def question_from_image(path: str, model: str, host: str,
                        provider: str, api_key: str, vision_model: str) -> str:
    """Read an image file and return the question inside it as plain text."""
    image_path = Path(path)
    if not image_path.is_file():
        raise SystemExit(f"No such image: {path}")

    # _mime_for() falls back to image/png for anything it doesn't know, so an
    # unsupported file would be sent with the wrong content type rather than
    # rejected. Cheaper to stop here than to burn a model call finding out.
    if image_path.suffix.lower() not in ALLOWED_IMAGES:
        allowed = ", ".join(sorted(ALLOWED_IMAGES))
        raise SystemExit(f"Unsupported image type '{image_path.suffix}'. Use one of: {allowed}")

    b64 = base64.b64encode(image_path.read_bytes()).decode()

    try:
        text = transcribe(b64, name=image_path.name, provider=provider, model=model,
                          host=host, api_key=api_key, vision_model=vision_model).strip()
    except Exception as e:
        raise SystemExit(f"Could not transcribe {path}: {e}")

    if not text:
        raise SystemExit(f"Nothing readable in {path} — is the question visible in the photo?")
    return text


def question_from_video(path: str, model: str, host: str,
                        provider: str, api_key: str, vision_model: str) -> str:
    """Read a video file and return the question inside it as plain text."""
    video_path = Path(path)
    if not video_path.is_file():
        raise SystemExit(f"No such video: {path}")

    if video_path.suffix.lower() not in ALLOWED_VIDEOS:
        allowed = ", ".join(sorted(ALLOWED_VIDEOS))
        raise SystemExit(f"Unsupported video type '{video_path.suffix}'. Use one of: {allowed}")

    def progress(n, total):
        # flush=True because Python buffers print when output is not a
        # terminal, and progress you see after the work finishes is not
        # progress. One vision call per frame, so this can be a slow wait.
        print(f"  reading frame {n} of {total}...", flush=True)

    try:
        return video_handler.question_from_video(
            path, model=model, host=host, provider=provider,
            api_key=api_key, vision_model=vision_model, on_progress=progress)
    except ExtractError as e:
        raise SystemExit(str(e))
    except Exception as e:
        raise SystemExit(f"Could not read {path}: {e}")


def learn_mode(topic: str, model: str, host: str,
               provider: str = "ollama", api_key: str = ""):
    context_chunks = retrieve(topic)
    context = "\n\n".join(context_chunks) if context_chunks else ""

    context_prefix = f"Reference material:\n{context}\n\n" if context else ""
    first_user_message = f"{context_prefix}Teach me about: {topic}"

    messages = [
        {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
        {"role": "user", "content": first_user_message},
    ]

    print(f"\n--- Learn mode: {topic} ---")
    print("(Type 'quit' at any time to exit)\n")

    while True:
        response = chat(messages, model=model, host=host,
                        provider=provider, api_key=api_key)
        print(f"\nTutor: {response}\n")

        if "Topic complete." in response:
            print("--- Session complete ---")
            break

        messages.append({"role": "assistant", "content": response})

        user_input = input("You: ").strip()
        if user_input.lower() in ("quit", "exit"):
            print("Session ended.")
            break

        messages.append({"role": "user", "content": user_input})


def main():
    args = build_arg_parser().parse_args()

    # A typed key wins, otherwise fall back to .env — same rule the web app uses.
    api_key = args.api_key.strip() or os.environ.get("API_KEY", "").strip()
    if args.provider == "groq" and not api_key:
        raise SystemExit("Groq needs a key: pass --api-key or set API_KEY in .env")

    if args.mode == "check" and not args.answer:
        raise SystemExit("Error: --answer is required in check mode")

    # From here down neither mode knows or cares where the question came from.
    if args.image:
        question = question_from_image(args.image, args.model, args.ollama_host,
                                       args.provider, api_key, args.vision_model)
        # Transcription is the one lossy step, so show it before it's used.
        print(f"\n--- Read from {args.image} ---\n{question}\n")
    elif args.video:
        question = question_from_video(args.video, args.model, args.ollama_host,
                                       args.provider, api_key, args.vision_model)
        print(f"\n--- Read from {args.video} ---\n{question}\n")
    else:
        question = args.text

    if args.mode == "check":
        context_chunks = retrieve(question)
        context = "\n\n".join(context_chunks) if context_chunks else ""

        context_prefix = f"Reference material:\n{context}\n\n" if context else ""
        prompt = build_check_prompt(question, args.answer,
                                    context_prefix=context_prefix)
        raw = generate(prompt, model=args.model, host=args.ollama_host,
                       provider=args.provider, api_key=api_key)
        # The marker is for machines, so strip it and say the verdict in words.
        response, correct = strip_signal(raw)
        print(response)
        verdict = {True: "Correct", False: "Not correct",
                   None: "No clear verdict"}[correct]
        print(f"\n--- {verdict} ---")

    elif args.mode == "learn":
        learn_mode(question, model=args.model, host=args.ollama_host,
                   provider=args.provider, api_key=api_key)

if __name__ == "__main__":
    main()
