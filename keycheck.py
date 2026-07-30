"""Print which API keys .env provides, with the values masked.

Called by start.sh and start.bat so you can see at launch whether a key will
come from .env or still has to be typed into the UI. Deliberately free of
heavy imports (no chromadb) so it stays instant, and ASCII-only so it prints
cleanly in a Windows console.
"""
from pathlib import Path

from dotenv import dotenv_values

KEYS = [
    ("API_KEY", "LLM provider (Groq)"),
    ("TAVILY_KEY", "Tavily search, for past papers"),
]


def mask(value: str) -> str:
    """Show only the last 4 characters, so the output is safe to screen-share."""
    return "****" + (value[-4:] if len(value) > 4 else "")


def main() -> None:
    env_path = Path(__file__).with_name(".env")
    print("API keys from .env:")

    if not env_path.is_file():
        print("  no .env file - copy .env.example to .env to store keys")
        return

    values = dotenv_values(env_path)
    for name, description in KEYS:
        value = (values.get(name) or "").strip()
        state = mask(value) if value else "not set"
        print(f"  {name:<11} {state:<10} - {description}")


if __name__ == "__main__":
    main()
