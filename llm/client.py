from ollama import Client as OllamaClient


class LLMText(str):
    """A model reply that also carries its token usage.

    Subclasses str, so every existing caller keeps working untouched — this
    *is* the text, and .strip(), f-strings, `in` and slicing all behave
    normally. The counts just ride along on .usage for the session log.

    Any transform returns a plain str, so "reply".strip() drops .usage. Read
    usage off the raw reply before stripping it.
    """

    def __new__(cls, text: str, usage: dict | None = None):
        # str is immutable, so the value is fixed in __new__, not __init__.
        obj = super().__new__(cls, text or "")
        obj.usage = usage or {}
        return obj


def _ollama_usage(r) -> dict:
    """Token counts off an Ollama response.

    Ollama names these differently from every hosted API, which is the easy
    thing to get silently wrong — a wrong name here reads as zero, not as an
    error.
    """
    return {"prompt": getattr(r, "prompt_eval_count", 0) or 0,
            "completion": getattr(r, "eval_count", 0) or 0}


def generate(prompt: str, model: str = "gemma4", host: str = "http://localhost:11434",
             provider: str = "ollama", api_key: str = "") -> LLMText:
    if provider == "groq":
        return _groq_chat([{"role": "user", "content": prompt}], model, api_key)
    client = OllamaClient(host=host)
    r = client.generate(model=model, prompt=prompt)
    return LLMText(r.response, _ollama_usage(r))


def chat(messages: list[dict], model: str = "gemma4", host: str = "http://localhost:11434",
         provider: str = "ollama", api_key: str = "") -> LLMText:
    if provider == "groq":
        return _groq_chat(messages, model, api_key)
    client = OllamaClient(host=host)
    r = client.chat(model=model, messages=messages)
    return LLMText(r.message.content, _ollama_usage(r))


def _groq_chat(messages: list[dict], model: str, api_key: str) -> LLMText:
    from groq import Groq
    # Strip image data — Groq text models don't support multimodal
    clean = [{"role": m["role"], "content": m["content"]} for m in messages]
    client = Groq(api_key=api_key)
    r = client.chat.completions.create(model=model, messages=clean)
    u = getattr(r, "usage", None)
    return LLMText(r.choices[0].message.content,
                   {"prompt": getattr(u, "prompt_tokens", 0) or 0,
                    "completion": getattr(u, "completion_tokens", 0) or 0})
