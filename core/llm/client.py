import sys

from ollama import Client as OllamaClient



_warned_no_usage = False


class LLMText(str):
    """A model reply that also carries its token usage.

    Subclasses str, so every existing caller keeps working untouched — this
    *is* the text, and .strip(), f-strings, `in` and slicing all behave
    normally. The counts just ride along on .usage for the session log.

    Any transform returns a plain str, so "reply".strip() drops .usage. Read
    usage off the raw reply before stripping it.
    """

    def __new__(cls, text: str, usage: dict | None = None):
        obj = super().__new__(cls, text or "")
        obj.usage = usage or {}
        return obj


def _ollama_usage(r) -> dict:
    """Token counts off an Ollama response.

    Ollama names these differently from every hosted API, which is the easy
    thing to get silently wrong — a wrong name here reads as zero, not as an
    error. So say so: the warning prints the field names the response actually
    has, which is the one thing you need to fix a rename.
    """
    global _warned_no_usage
    u = {"prompt": getattr(r, "prompt_eval_count", 0) or 0,
         "completion": getattr(r, "eval_count", 0) or 0}
    if not u["completion"] and not _warned_no_usage:
        _warned_no_usage = True
        fields = sorted(vars(r)) if hasattr(r, "__dict__") else type(r).__name__
        print(f"warning: ollama returned no token counts. fields seen: {fields}",
              file=sys.stderr)
    return u


def generate(prompt: str, model: str = "gemma4", host: str = "http://localhost:11434",
             provider: str = "ollama", api_key: str = "") -> LLMText:
    if provider == "groq":
        return _groq_chat([{"role": "user", "content": prompt}], model, api_key)
    if provider == "bedrock":
        return _bedrock_chat([{"role": "user", "content": prompt}], model,
                             region=host if not host.startswith("http") else "us-east-1")
    client = OllamaClient(host=host)
    r = client.generate(model=model, prompt=prompt)
    return LLMText(r.response, _ollama_usage(r))


def chat(messages: list[dict], model: str = "gemma4", host: str = "http://localhost:11434",
         provider: str = "ollama", api_key: str = "") -> LLMText:
    if provider == "groq":
        return _groq_chat(messages, model, api_key)
    if provider == "bedrock":
        return _bedrock_chat(messages, model,
                             region=host if not host.startswith("http") else "us-east-1")
    client = OllamaClient(host=host)
    r = client.chat(model=model, messages=messages)
    return LLMText(r.message.content, _ollama_usage(r))


def _groq_chat(messages: list[dict], model: str, api_key: str) -> LLMText:
    from groq import Groq
    clean = [{"role": m["role"], "content": m["content"]} for m in messages]
    client = Groq(api_key=api_key)
    r = client.chat.completions.create(model=model, messages=clean)
    u = getattr(r, "usage", None)
    return LLMText(r.choices[0].message.content,
                   {"prompt": getattr(u, "prompt_tokens", 0) or 0,
                    "completion": getattr(u, "completion_tokens", 0) or 0})


def _bedrock_chat(messages: list[dict], model: str,
                  region: str = "us-east-1") -> LLMText:
    """Call Amazon Bedrock via the Converse API.

    Credentials come from the environment (AWS_ACCESS_KEY_ID /
    AWS_SECRET_ACCESS_KEY) or, on ECS Fargate, from the task IAM role
    automatically — no api_key field is used.

    The Converse API separates system prompts from the turn list, so we
    pull any role="system" messages out before building the request.
    Image bytes in Ollama-format messages are stripped — Bedrock vision
    would need a separate content-block path.
    """
    import boto3
    client = boto3.client("bedrock-runtime", region_name=region)

    system_blocks = []
    turn_messages = []
    for m in messages:
        text = m.get("content") or ""
        if isinstance(text, list):
            # Flatten multi-part content (shouldn't reach here, but be safe)
            text = " ".join(p.get("text", "") for p in text if isinstance(p, dict))
        if m["role"] == "system":
            if text:
                system_blocks.append({"text": text})
        else:
            turn_messages.append({
                "role": m["role"],
                "content": [{"text": text or " "}],  # Bedrock rejects empty strings
            })

    kwargs: dict = {"modelId": model, "messages": turn_messages}
    if system_blocks:
        kwargs["system"] = system_blocks

    r = client.converse(**kwargs)
    text = r["output"]["message"]["content"][0]["text"]
    u = r.get("usage", {})
    return LLMText(text, {
        "prompt":     u.get("inputTokens", 0),
        "completion": u.get("outputTokens", 0),
    })
