import argparse
from llm.client import generate, chat
from rag.retrieve import retrieve

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SAT/A-level LLM tutor")
    parser.add_argument("mode", choices=["learn", "check"])
    parser.add_argument("--text", required=True, help="Question as typed text")
    parser.add_argument("--answer", help="Student's answer (check mode only)")
    parser.add_argument("--ollama-host", default="http://localhost:11434")
    parser.add_argument("--model", default="gemma4")
    return parser

TUTOR_SYSTEM_PROMPT = (
    "You are a patient, encouraging SAT/A-level tutor. "
    "Teach one concept at a time. After each explanation, ask the student exactly ONE question to check understanding. "
    "When the student answers, give brief feedback and either move to the next concept or re-explain if they struggled. "
    "When the entire topic has been covered and the student understands, end your response with the exact phrase 'Topic complete.'"
)

def learn_mode(topic: str, model: str, host: str):
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
        response = chat(messages, model=model, host=host)
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

    if args.mode == "check":
        if not args.answer:
            print("Error: --answer is required in check mode")
            return

        context_chunks = retrieve(args.text)
        context = "\n\n".join(context_chunks) if context_chunks else ""

        context_prefix = f"Reference material:\n{context}\n\n" if context else ""
        prompt = (
            f"{context_prefix}"
            f"Question: {args.text}\n"
            f"Student's answer: {args.answer}\n\n"
            "Is the student's answer correct? Explain briefly."
        )
        print(generate(prompt, model=args.model, host=args.ollama_host))

    elif args.mode == "learn":
        learn_mode(args.text, model=args.model, host=args.ollama_host)

if __name__ == "__main__":
    main()
