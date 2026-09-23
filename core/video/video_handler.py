import base64
import difflib
from core.llm.client import generate
from core.vision.image_handler import transcribe, drop_reasoning
from core.video.frame_extractor import extract_frames, ExtractError
SAME_ENOUGH = 0.85
MERGE_PROMPT = 'These are transcriptions of different frames of one video showing a single exam question. They overlap, and some are partly wrong.\nCombine them into one complete question. Keep every number, symbol and equation. Where two frames disagree, choose the reading that makes the mathematics valid. Do not answer the question. Do not add anything that is not in the transcriptions.\nOutput only the combined question.\n\n'

def _dedupe(texts: list[str]) -> list[str]:
    kept = []
    for t in texts:
        for i, k in enumerate(kept):
            if difflib.SequenceMatcher(None, t, k).ratio() > SAME_ENOUGH:
                if len(t) > len(k):
                    kept[i] = t
                break
        else:
            kept.append(t)
    return kept

def question_from_video(path: str, model: str='gemma4', host: str='http://localhost:11434', provider: str='ollama', api_key: str='', vision_model: str='', on_progress=None) -> str:
    frames = extract_frames(path)
    texts = []
    for n, jpg in enumerate(frames, 1):
        if on_progress:
            on_progress(n, len(frames))
        b64 = base64.b64encode(jpg).decode()
        try:
            t = transcribe(b64, name=f'frame{n}.jpg', provider=provider, model=model, host=host, api_key=api_key, vision_model=vision_model).strip()
        except Exception:
            continue
        if t:
            texts.append(t)
    if not texts:
        raise ExtractError(f'Nothing readable in any frame of {path}')
    texts = _dedupe(texts)
    if len(texts) == 1:
        return texts[0]
    numbered = '\n\n'.join((f'Frame {i}:\n{t}' for i, t in enumerate(texts, 1)))
    merged = generate(MERGE_PROMPT + numbered, model=model, host=host, provider=provider, api_key=api_key)
    return drop_reasoning(merged).strip() or texts[0]