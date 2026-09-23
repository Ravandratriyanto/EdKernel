import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from core.vision.step_checker import check_working
load_dotenv()
CASES = Path(__file__).parent / 'vision_cases.jsonl'
_STRIP = re.compile('[\\s$\\\\,.;]|\\\\left|\\\\right|\\{|\\}|\\(\\)|\\\\!|\\\\ ')

def _norm(s: str) -> str:
    s = (s or '').lower()
    s = s.replace('\\times', '*').replace('\\cdot', '*')
    s = s.replace('^{2}', '^2').replace('^{3}', '^3')
    s = re.sub('\\\\[a-z]+', '', s)
    s = re.sub('\\\\[()\\[\\]]', '', s)
    s = _STRIP.sub('', s)
    s = re.sub('^\\d{1,2}\\)', '', s)
    return s

def _read_score(got_steps, want_lines):
    if not want_lines:
        return None
    matched = sum((1 for a, b in zip(got_steps, want_lines) if _norm(a) == _norm(b)))
    return (matched, len(want_lines))

def score_one(case, provider, model, host, api_key, vision_model):
    img = Path(case['image'])
    if not img.exists():
        return {**case, 'got': None, 'how': 'missing', 'steps': [], 'detail': f'no image at {img}'}
    t0 = time.time()
    try:
        result = check_working(str(img), provider=provider, model=model, host=host, api_key=api_key, vision_model=vision_model)
        return {**case, 'got': result['error_index'], 'how': 'ok', 'steps': result['steps'], 'secs': time.time() - t0, 'detail': (result['explanation'] or '')[:160].replace('\n', ' ')}
    except Exception as e:
        return {**case, 'got': None, 'how': 'error', 'steps': [], 'secs': time.time() - t0, 'detail': f'{type(e).__name__}: {e}'}

def report(results, show_steps=True):
    scored = [r for r in results if r['how'] == 'ok']
    errored = [r for r in results if r['how'] == 'error']
    missing = [r for r in results if r['how'] == 'missing']
    hits = [r for r in scored if r['got'] == r['error_index']]
    err_cases = [r for r in scored if r['error_index'] is not None]
    ok_cases = [r for r in scored if r['error_index'] is None]
    print()
    if scored:
        print(f'step checker      {len(hits)}/{len(scored)}  ({100 * len(hits) / len(scored):.0f}%)   [{len(errored)} case(s) died before scoring]')
    else:
        print('no cases scored — every case errored or is missing its photo')
    if err_cases:
        loc = sum((1 for r in err_cases if r['got'] == r['error_index']))
        print(f'  error located     {loc}/{len(err_cases)}  (exact line)')
    if ok_cases:
        clean = sum((1 for r in ok_cases if r['got'] is None))
        print(f'  clean pass        {clean}/{len(ok_cases)}  (no false error)')
    labelled = [r for r in scored if r.get('lines')]
    if labelled:
        tot_m = tot_n = 0
        perfect = 0
        for r in labelled:
            m, n = _read_score(r['steps'], r['lines'])
            tot_m += m
            tot_n += n
            if m == n and len(r['steps']) == n:
                perfect += 1
        print(f'\ntranscription     {tot_m}/{tot_n} lines read faithfully ({100 * tot_m / tot_n:.0f}%)')
        print(f'  clean reads       {perfect}/{len(labelled)}  (whole problem)')
        clean_cases = [r for r in labelled if _read_score(r['steps'], r['lines'])[0] == len(r['lines']) and len(r['steps']) == len(r['lines'])]
        if clean_cases:
            ch = sum((1 for r in clean_cases if r['got'] == r['error_index']))
            print(f'  verdict | clean    {ch}/{len(clean_cases)}  (step check, given a faithful read)')
    if missing:
        print(f'\n  MISSING IMAGES    {len(missing)}')
    if errored:
        print(f'  PIPELINE ERRORS   {len(errored)}')
    bad = [r for r in scored if r['got'] != r['error_index']]
    if bad or errored:
        print('\nfailures:')
        for r in bad + errored:
            print(f"  {r['id']}  wanted {r['error_index']}  got {r['got']}  ({r.get('note', '')})")
            if r['detail']:
                print(f"        {r['detail']}")
            if show_steps and r['steps']:
                want = r.get('lines') or []
                for i, s in enumerate(r['steps']):
                    flag = ' '
                    if want:
                        exp = want[i] if i < len(want) else '<no such line>'
                        flag = '.' if _norm(s) == _norm(exp) else 'X'
                    print(f'        [{i}]{flag} {s[:90]}')
                    if want and flag == 'X':
                        exp = want[i] if i < len(want) else '<no such line>'
                        print(f'           want: {exp}')
    for r in missing:
        print(f"  MISSING  {r['id']}  {r['detail']}")
    return 0 if scored and (not bad) and (not errored) else 1

def main():
    p = argparse.ArgumentParser(description='Eval harness for the step checker')
    p.add_argument('--provider', choices=['ollama', 'groq'], default='ollama')
    p.add_argument('--model', default='gemma4')
    p.add_argument('--vision-model', default='', help='Vision model if separate from --model')
    p.add_argument('--ollama-host', default='http://localhost:11434')
    p.add_argument('--api-key', default='', help='Falls back to API_KEY in .env')
    p.add_argument('--only', default='', help='Comma-separated case ids, e.g. v1,v7')
    p.add_argument('--pause', type=float, default=0.0, help="Seconds to wait between cases. Groq's free tier allows ~3 image calls/min (7000 input tokens/min), so a full run needs pacing: try --pause 20")
    p.add_argument('--no-steps', action='store_true', help='Hide transcribed lines in the failure dump')
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass
    api_key = args.api_key.strip() or os.environ.get('API_KEY', '').strip()
    if args.provider == 'groq' and (not api_key):
        raise SystemExit('Groq needs a key: pass --api-key or set API_KEY in .env')
    if not CASES.exists():
        raise SystemExit(f'No cases file at {CASES}')
    cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
    if args.only:
        want = {s.strip() for s in args.only.split(',') if s.strip()}
        cases = [c for c in cases if c['id'] in want]
        if not cases:
            raise SystemExit(f'No cases matched --only {args.only}')
    print(f'running {len(cases)} vision cases on {args.provider}/{args.model}...')
    results = []
    for n, c in enumerate(cases):
        print(f"  [{n + 1}/{len(cases)}] {c['id']} ...", end='', flush=True)
        r = score_one(c, args.provider, args.model, args.ollama_host, api_key, args.vision_model)
        results.append(r)
        mark = 'ok' if r['got'] == r['error_index'] and r['how'] == 'ok' else r['how'].upper()
        print(f" {mark}  (wanted {r['error_index']}, got {r['got']}, {r.get('secs', 0):.0f}s)", flush=True)
        if r['how'] == 'error':
            print(f"        {r['detail'][:200]}", flush=True)
        if args.pause and n < len(cases) - 1:
            time.sleep(args.pause)
    raise SystemExit(report(results, show_steps=not args.no_steps))
if __name__ == '__main__':
    main()