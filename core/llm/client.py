import os
import sys
from ollama import Client as OllamaClient
_warned_no_usage = False

class LLMText(str):

    def __new__(cls, text: str, usage: dict | None=None):
        obj = super().__new__(cls, text or '')
        obj.usage = usage or {}
        return obj

def _ollama_usage(r) -> dict:
    global _warned_no_usage
    u = {'prompt': getattr(r, 'prompt_eval_count', 0) or 0, 'completion': getattr(r, 'eval_count', 0) or 0}
    if not u['completion'] and (not _warned_no_usage):
        _warned_no_usage = True
        fields = sorted(vars(r)) if hasattr(r, '__dict__') else type(r).__name__
        print(f'warning: ollama returned no token counts. fields seen: {fields}', file=sys.stderr)
    return u

def generate(prompt: str, model: str='gemma4', host: str='http://localhost:11434', provider: str='ollama', api_key: str='', temperature: float=0.0) -> LLMText:
    if provider == 'groq':
        return _groq_chat([{'role': 'user', 'content': prompt}], model, api_key, temperature)
    if provider == 'bedrock':
        return _bedrock_chat([{'role': 'user', 'content': prompt}], model, region=host if not host.startswith('http') else 'us-east-1', temperature=temperature)
    client = OllamaClient(host=host)
    r = client.generate(model=model, prompt=prompt, options={'temperature': temperature})
    return LLMText(r.response, _ollama_usage(r))

def chat(messages: list[dict], model: str='gemma4', host: str='http://localhost:11434', provider: str='ollama', api_key: str='', temperature: float=0.0) -> LLMText:
    if provider == 'groq':
        return _groq_chat(messages, model, api_key, temperature)
    if provider == 'bedrock':
        return _bedrock_chat(messages, model, region=host if not host.startswith('http') else 'us-east-1', temperature=temperature)
    client = OllamaClient(host=host)
    r = client.chat(model=model, messages=messages, options={'temperature': temperature})
    return LLMText(r.message.content, _ollama_usage(r))

def _groq_chat(messages: list[dict], model: str, api_key: str, temperature: float=0.0) -> LLMText:
    from groq import Groq
    clean = [{'role': m['role'], 'content': m['content']} for m in messages]
    client = Groq(api_key=api_key, timeout=60.0, max_retries=0)
    r = client.chat.completions.create(model=model, messages=clean, temperature=temperature)
    u = getattr(r, 'usage', None)
    return LLMText(r.choices[0].message.content, {'prompt': getattr(u, 'prompt_tokens', 0) or 0, 'completion': getattr(u, 'completion_tokens', 0) or 0})

def _bedrock_chat(messages: list[dict], model: str, region: str='us-east-1', temperature: float=0.0) -> LLMText:
    import boto3
    client = boto3.client('bedrock-runtime', region_name=region)
    system_blocks = []
    turn_messages = []
    for m in messages:
        text = m.get('content') or ''
        if isinstance(text, list):
            text = ' '.join((p.get('text', '') for p in text if isinstance(p, dict)))
        if m['role'] == 'system':
            if text:
                system_blocks.append({'text': text})
        else:
            turn_messages.append({'role': m['role'], 'content': [{'text': text or ' '}]})
    kwargs: dict = {'modelId': model, 'messages': turn_messages, 'inferenceConfig': {'temperature': temperature}}
    if system_blocks:
        kwargs['system'] = system_blocks
    r = client.converse(**kwargs)
    text = r['output']['message']['content'][0]['text']
    u = r.get('usage', {})
    return LLMText(text, {'prompt': u.get('inputTokens', 0), 'completion': u.get('outputTokens', 0)})

MAX_AUDIO_BYTES = 25 * 1024 * 1024

def transcribe_audio(path: str, model: str='whisper-large-v3-turbo', api_key: str='') -> str:
    if os.path.getsize(path) > MAX_AUDIO_BYTES:
        raise ValueError('Video file is too large for Whisper (25MB limit)')
    from groq import Groq
    client = Groq(api_key=api_key, timeout=120.0, max_retries=0)
    with open(path, 'rb') as f:
        r = client.audio.transcriptions.create(model=model, file=(os.path.basename(path), f.read()))
    return r.text.strip()