from ollama import Client

def generate(prompt: str, model: str = "gemma4", host: str = "http://localhost:11434") -> str:
    client = Client(host=host)
    response = client.generate(model=model, prompt=prompt)
    return response.response

def chat(messages: list[dict], model: str = "gemma4", host: str = "http://localhost:11434") -> str:
    client = Client(host=host)
    response = client.chat(model=model, messages=messages)
    return response.message.content
