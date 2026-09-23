import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
import cv2
from dotenv import load_dotenv
from core.vision.preprocess import preprocess
from core.vision.segment import segment, crops
from core.vision.step_checker import _upscale, _with_retry
from core.vision.image_handler import _groq_vision, GROQ_VISION_MODEL, TRANSCRIBE_PROMPT
from evals.vision import _norm
load_dotenv()
CASES = Path(__file__).parent / 'vision_cases.jsonl'
FAITHFUL_PROMPT = TRANSCRIBE_PROMPT
NAIVE_PROMPT = 'Transcribe the handwritten mathematics in this image as a single line of plain text, using LaTeX for any mathematics. Output only the transcription.'
_THINK = re.compile('<think>.*?</think>', re.DOTALL | re.IGNORECASE)

def _crop_b64(binary, box):
    crop = _upscale(crops(binary, [box], pad=3)[0])
    ok, buf = cv2.imencode('.jpg', crop)
    return base64.b64encode(buf.tobytes()).decode() if ok else None

def _read(prompt, b64, key):
    try:
        raw = _with_retry(lambda: _groq_vision(prompt, b64, 'line.jpg', GROQ_VISION_MODEL, key))
    except Exception as e:
        return f'[vision unavailable: {type(e).__name__}]'
    return _THINK.sub('', raw or '').strip()

def load_cases(only):
    out = []
    for ln in CASES.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        c = json.loads(ln)
        if only and c.get('id') not in only:
            continue
        out.append(c)
    return out

def run(only, key):
    cases = load_cases(only)
    preserved = {'naive': 0, 'guarded': 0}
    err_total = 0
    rows = []
    for c in cases:
        img = Path(c['image'])
        if not img.exists():
            print(f"  {c['id']}: no image at {img}", file=sys.stderr)
            continue
        binary = preprocess(str(img))
        boxes = segment(binary)
        want = c.get('lines') or []
        err_i = c.get('error_index')
        for i, box in enumerate(boxes):
            if i >= len(want):
                break
            b64 = _crop_b64(binary, box)
            if not b64:
                continue
            truth = want[i]
            is_err = err_i is not None and i == err_i
            if is_err:
                err_total += 1
            reads = {}
            for name, prompt in (('naive', NAIVE_PROMPT), ('guarded', FAITHFUL_PROMPT)):
                got = _read(prompt, b64, key)
                ok = _norm(got) == _norm(truth)
                reads[name] = (got, ok)
                if is_err and ok:
                    preserved[name] += 1
            rows.append((c['id'], i, is_err, truth, reads))
    _report(rows, preserved, err_total)

def _report(rows, preserved, err_total):
    print('\n=== per-line reads (★ = labelled error line) ===')
    for cid, i, is_err, truth, reads in rows:
        star = '★' if is_err else ' '
        print(f'\n{star} {cid} line {i}  student wrote: {truth!r}')
        for name in ('naive', 'guarded'):
            got, ok = reads[name]
            mark = 'PRESERVED' if ok else 'changed  '
            print(f'    {name:8} {mark}  {got[:70]!r}')
    print(f'\n=== error-preservation (on {err_total} labelled error lines) ===')
    for name in ('naive', 'guarded'):
        print(f'  {name:8} {preserved[name]}/{err_total}')
    print("Did the student's wrong step survive the read? Same model, same pixels — only the faithfulness instruction differs.")
if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='', help='comma-separated case ids, e.g. v7,v8,v9')
    args = ap.parse_args()
    key = os.environ.get('API_KEY', '')
    if not key:
        sys.exit('API_KEY not set (need a Groq key in .env)')
    only = {s.strip() for s in args.only.split(',') if s.strip()}
    run(only, key)