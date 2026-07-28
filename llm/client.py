from ollama import Client as OllamaClient

def generate(prompt: str, model: str = "gemma4", host: str = "http://localhost:11434",
             provider: str = "ollama", api_key: str = "") -> str:
    if provider == "groq":
        return _groq_chat([{"role": "user", "content": prompt}], model, api_key)
    client = OllamaClient(host=host)
    return client.generate(model=model, prompt=prompt).response

def chat(messages: list[dict], model: str = "gemma4", host: str = "http://localhost:11434",
         provider: str = "ollama", api_key: str = "") -> str:
    if provider == "groq":
        return _groq_chat(messages, model, api_key)
    client = OllamaClient(host=host)
    return client.chat(model=model, messages=messages).message.content

def _groq_chat(messages: list[dict], model: str, api_key: str) -> str:
    from groq import Groq
    # Strip image data — Groq text models don't support multimodal
    clean = [{"role": m["role"], "content": m["content"]} for m in messages]
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(model=model, messages=clean)
    return response.choices[0].message.content
