GROQ_VISION_MODEL = 'qwen/qwen3.8-27b'
DETECT_PROMPT = 'Look at this image. If it contains a printed or handwritten mathematical question, problem, or exercise, transcribe it as plain text — use LaTeX notation for any maths (e.g. \\(x^2\\), \\(\\frac{a}{b}\\)). Include every part of the question: the stem, all sub-parts (a), (b)…, and describe any diagram in one sentence. If the image does NOT contain a clear question or problem (e.g. it is handwritten calculation steps, a blank page, or an unrelated photo), respond with exactly: NO_QUESTION\nOutput only the transcription or NO_QUESTION. No preamble, no explanation.'
TRANSCRIBE_PROMPT = "Transcribe the handwritten mathematics in this image as a single line of plain text, using LaTeX for any mathematics. This is a student's working and it may contain mistakes. Copy it verbatim: do NOT correct errors, do NOT solve, simplify, or 'fix' anything. If a step is wrong, transcribe the wrong version exactly as it is written. Write the expression exactly once — do NOT repeat it, and do NOT break it into separate fragments or pieces. Output only the transcription — no preamble, no explanation, no answer. Students cross out working they have abandoned, either by striking through a line or by drawing one large X over a whole block of lines. A large X crosses out EVERY line it spans, not just the first. Wrap all crossed-out working in [CROSSED OUT] ... [/CROSSED OUT], transcribing it as written inside the tags."
FRAME_PROMPT = 'This is a still frame from an educational video. Transcribe any text, equations, or diagram labels shown on screen (slides, whiteboard, on-screen captions), using LaTeX for any mathematics. Describe any diagram or graph in one sentence. If the frame has no readable educational content (e.g. just a person talking, a blank screen, or a logo), respond with exactly: NO_TEXT\nOutput only the transcription or NO_TEXT. No preamble, no explanation.'
_MIME = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp', 'gif': 'image/gif'}

def _mime_for(name: str) -> str:
    ext = name.lower().rsplit('.', 1)[-1] if '.' in name else ''
    return _MIME.get(ext, 'image/png')

def drop_reasoning(text: str) -> str:
    if '</think>' in text:
        return text.rsplit('</think>', 1)[1].strip()
    if '<think>' in text:
        return ''
    return text.strip()

def detect_question(b64: str, name: str='image.png', provider: str='ollama', model: str='gemma4', host: str='http://localhost:11434', api_key: str='', vision_model: str='') -> dict:
    if provider == 'groq':
        raw = _groq_vision(DETECT_PROMPT, b64, name, vision_model or GROQ_VISION_MODEL, api_key)
    else:
        from ollama import Client as OllamaClient
        client = OllamaClient(host=host)
        messages = [{'role': 'user', 'content': DETECT_PROMPT, 'images': [b64]}]
        raw = drop_reasoning(client.chat(model=model, messages=messages).message.content)
    raw = (raw or '').strip()
    if not raw or raw.upper().startswith('NO_QUESTION') or len(raw) < 8:
        return {'found': False, 'question': ''}
    return {'found': True, 'question': raw}

def transcribe(b64: str, name: str='image.png', provider: str='ollama', model: str='gemma4', host: str='http://localhost:11434', api_key: str='', vision_model: str='') -> str:
    if provider == 'groq':
        return _groq_vision(TRANSCRIBE_PROMPT, b64, name, vision_model or GROQ_VISION_MODEL, api_key)
    from ollama import Client as OllamaClient
    client = OllamaClient(host=host)
    messages = [{'role': 'user', 'content': TRANSCRIBE_PROMPT, 'images': [b64]}]
    return drop_reasoning(client.chat(model=model, messages=messages).message.content)

def read_frame(b64: str, name: str='frame.jpg', provider: str='ollama', model: str='gemma4', host: str='http://localhost:11434', api_key: str='', vision_model: str='') -> str:
    if provider == 'groq':
        raw = _groq_vision(FRAME_PROMPT, b64, name, vision_model or GROQ_VISION_MODEL, api_key)
    else:
        from ollama import Client as OllamaClient
        client = OllamaClient(host=host)
        messages = [{'role': 'user', 'content': FRAME_PROMPT, 'images': [b64]}]
        raw = drop_reasoning(client.chat(model=model, messages=messages).message.content)
    raw = (raw or '').strip()
    if raw.upper().startswith('NO_TEXT'):
        return ''
    return raw

def _groq_vision(prompt: str, b64: str, name: str, vision_model: str, api_key: str) -> str:
    from groq import Groq
    client = Groq(api_key=api_key, timeout=60.0, max_retries=0)
    response = client.chat.completions.create(model=vision_model, reasoning_effort='none', max_tokens=512, temperature=0, messages=[{'role': 'user', 'content': [{'type': 'text', 'text': prompt}, {'type': 'image_url', 'image_url': {'url': f'data:{_mime_for(name)};base64,{b64}'}}]}])
    return drop_reasoning(response.choices[0].message.content)