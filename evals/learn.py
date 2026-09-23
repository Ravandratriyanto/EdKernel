import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dotenv import load_dotenv
from core.llm.client import chat
from core.rag.retrieve import retrieve
from core.prompts import TUTOR_SYSTEM_PROMPT, hint_note, strip_signal
from core.vision.image_handler import drop_reasoning
load_dotenv()
CASES = Path(__file__).parent / 'learn_cases.jsonl'
ATTEMPTS = 3

def _norm(text: str) -> str:
    return re.sub('\\s+', ' ', text).strip().casefold()

def _names(text: str, words) -> bool:
    return any((re.search('\\b' + re.escape(w) + '\\w?(?:s|es|ed|ing|ion)?\\b', text, re.I) for w in words))

def _leaks(text: str, answer: str) -> bool:
    left = '(?<![\\d.])' if answer[:1].isdigit() else ''
    right = '(?!\\d)' if answer[-1:].isdigit() else ''
    return re.search(left + re.escape(answer) + right, text, re.I) is not None

def run_case(case, provider, model, host, api_key, tries=4):
    chunks = retrieve(case['topic'])
    context = '\n\n'.join(chunks) if chunks else ''
    prefix = f'Reference material:\n{context}\n\n' if context else ''
    messages = [{'role': 'system', 'content': TUTOR_SYSTEM_PROMPT}, {'role': 'user', 'content': f"{prefix}Teach me about: {case['topic']}\n\nStart with this question: {case['question']}"}]
    hints = []
    for streak in range(1, ATTEMPTS + 1):
        note = hint_note(streak)
        messages.append({'role': 'user', 'content': case['wrong'] + note})
        for attempt in range(tries):
            try:
                raw = chat(messages, model=model, host=host, provider=provider, api_key=api_key)
                break
            except Exception as e:
                msg = str(e).lower()
                daily = 'tpd' in msg or 'per day' in msg
                if not (('429' in msg or 'rate limit' in msg) and (not daily)) or attempt == tries - 1:
                    return {**case, 'hints': hints, 'error': f'{type(e).__name__}: {e}'}
                time.sleep(5 * 2 ** attempt)
        reply, _ = strip_signal(drop_reasoning(str(raw)))
        hints.append(reply)
    return {**case, 'hints': hints, 'error': None}

def judge(result):
    hints = result['hints']
    if result['error'] or len(hints) < ATTEMPTS:
        return [('ran', False, result['error'] or f'only {len(hints)} hints')]
    first, second = (hints[0], hints[1])
    concept, answer = (result['concept'], result['answer'])
    seen = [_norm(h) for h in hints]
    return [('hints differ', len(set(seen)) == ATTEMPTS, 'two rungs produced the same text'), ('rung 1 withholds concept', not _names(first, concept), f'named {[w for w in concept if _names(first, [w])]} on the first hint'), ('rung 2 names concept', _names(second, concept), f'none of {concept} appeared by the second hint'), ('answer held back', not _leaks(first + ' ' + second, answer), f'leaked {answer!r} before the third hint')]

def run_cases(cases, provider, model, host, api_key, jobs):
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(lambda c: run_case(c, provider, model, host, api_key), cases))

def _trim(text: str, width: int=200) -> str:
    flat = re.sub('\\s+', ' ', text).strip()
    return flat if len(flat) <= width else flat[:width - 1] + '…'

def report(results, show=False):
    if not results:
        print('no cases ran')
        return 1
    judged = [(r, judge(r)) for r in results]
    passed = [r for r, checks in judged if all((ok for _, ok, _ in checks))]
    pct = 100 * len(passed) / len(judged)
    print(f'\nhint ladder       {len(passed)}/{len(judged)}  ({pct:.0f}%)')
    tally = {}
    for _, checks in judged:
        for name, ok, _ in checks:
            hit, total = tally.get(name, (0, 0))
            tally[name] = (hit + bool(ok), total + 1)
    for name in sorted(tally, key=lambda n: n == 'ran'):
        hit, total = tally[name]
        print(f'  {name:26} {hit}/{total}')
    ids = [r['id'] for r, _ in judged]
    if len(set(ids)) < len(ids):
        print('\nper case:')
        for cid in sorted(set(ids), key=ids.index):
            runs = [c for r, c in judged if r['id'] == cid]
            ok = sum((1 for checks in runs if all((o for _, o, _ in checks))))
            print(f'  {cid}  {ok}/{len(runs)}  ({100 * ok / len(runs):.0f}%)')
    failed = [(r, checks) for r, checks in judged if not all((ok for _, ok, _ in checks))]
    if failed:
        print('\nfailures:')
        for r, checks in failed:
            print(f"\n  {r['id']}  {r['topic']}")
            for name, ok, detail in checks:
                if not ok:
                    print(f'    FAIL  {name} — {detail}')
            for i, h in enumerate(r['hints']):
                print(f'    rung {i + 1}  {_trim(h)}')
    if show:
        print('\nall hints:')
        for r, _ in judged:
            print(f"\n  {r['id']}  {r['topic']}")
            for i, h in enumerate(r['hints']):
                print(f'    rung {i + 1}  {_trim(h, 400)}')
    return 0 if not failed else 1

def main():
    p = argparse.ArgumentParser(description="Eval harness for learn mode's hint ladder")
    p.add_argument('--provider', choices=['ollama', 'groq'], default='ollama')
    p.add_argument('--model', default='gemma4')
    p.add_argument('--ollama-host', default='http://localhost:11434')
    p.add_argument('--api-key', default='', help='Falls back to API_KEY in .env')
    p.add_argument('--jobs', type=int, default=2, help="Cases at a time. Lower than run.py's 4 because each case is a three-turn conversation.")
    p.add_argument('--case', nargs='+', metavar='ID', help='Run only these case IDs (e.g. --case h1 h4).')
    p.add_argument('--repeat', type=int, default=1, metavar='N', help='Run each selected case N times, to tell a flaky ladder from an unlucky run.')
    p.add_argument('--show', action='store_true', help='Print all three hints for every case, passing or not.')
    args = p.parse_args()
    api_key = args.api_key.strip() or os.environ.get('API_KEY', '').strip()
    if args.provider == 'groq' and (not api_key):
        raise SystemExit('Groq needs a key: pass --api-key or set API_KEY in .env')
    if args.repeat < 1:
        raise SystemExit('--repeat must be at least 1')
    cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
    if args.case:
        wanted = set(args.case)
        missing = wanted - {c['id'] for c in cases}
        if missing:
            raise SystemExit(f"Unknown case id(s): {', '.join(sorted(missing))}")
        cases = [c for c in cases if c['id'] in wanted]
    cases = cases * args.repeat
    print(f'running {len(cases)} cases x {ATTEMPTS} turns on {args.provider}/{args.model}, {args.jobs} at a time...')
    results = run_cases(cases, args.provider, args.model, args.ollama_host, api_key, args.jobs)
    raise SystemExit(report(results, show=args.show))
if __name__ == '__main__':
    main()