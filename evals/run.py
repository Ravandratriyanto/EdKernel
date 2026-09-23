import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dotenv import load_dotenv
from core.llm.client import generate
from core.rag.retrieve import retrieve
from core.prompts import build_check_prompt, strip_signal
from evals import regress
load_dotenv()
CASES = Path(__file__).parent / 'cases.jsonl'
_SIGNAL_RE = re.compile('\\s*\\[(CORRECT|WRONG)\\]\\s*$', re.IGNORECASE)
_NEG_RE = re.compile('(is not correct|is incorrect|is wrong|not correct|does not match|is not right|therefore.{0,20}incorrect)', re.I)
_POS_RE = re.compile('(is correct|answer is right|is indeed correct|correctly (solved|found|applied))', re.I)

def build_prompt(question: str, answer: str) -> str:
    chunks = retrieve(question)
    context = '\n\n'.join(chunks) if chunks else ''
    prefix = f'Reference material:\n{context}\n\n' if context else ''
    return build_check_prompt(question, answer, context_prefix=prefix)

def verdict(text: str) -> tuple:
    m = _SIGNAL_RE.search(text)
    if m:
        return (m.group(1).upper() == 'CORRECT', 'signal')
    tail = text[-400:]
    neg, pos = (_NEG_RE.search(tail), _POS_RE.search(tail))
    if neg and (not pos):
        return (False, 'prose')
    if pos and (not neg):
        return (True, 'prose')
    if neg and pos:
        return (neg.start() < pos.start(), 'prose')
    return (None, 'unparsed')

def score_one(case, provider, model, host, api_key, tries=4):
    prompt = build_prompt(case['question'], case['answer'])
    for attempt in range(tries):
        try:
            raw = generate(prompt, model=model, host=host, provider=provider, api_key=api_key)
            got, how = verdict(str(raw))
            body, _ = strip_signal(str(raw))
            return {**case, 'got': got, 'how': how, 'body': body, 'detail': str(raw)[-160:].replace('\n', ' ')}
        except Exception as e:
            msg = str(e).lower()
            daily = 'tpd' in msg or 'per day' in msg
            retryable = ('429' in msg or 'rate limit' in msg) and (not daily)
            if not retryable or attempt == tries - 1:
                return {**case, 'got': None, 'how': 'error', 'body': '', 'detail': f'{type(e).__name__}: {e}'}
            time.sleep(5 * 2 ** attempt)

def run_cases(cases, provider, model, host, api_key, jobs):
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(lambda c: score_one(c, provider, model, host, api_key), cases))

def report(results, regressions):
    hits = [r for r in results if r['got'] == r['correct']]
    trues = [r for r in results if r['correct']]
    falses = [r for r in results if not r['correct']]
    if results:
        pct = 100 * len(hits) / len(results)
        print(f'\ncheck mode        {len(hits)}/{len(results)}  ({pct:.0f}%)')
        print(f"  accepts correct   {sum((1 for r in trues if r['got'] is True))}/{len(trues)}")
        print(f"  rejects wrong     {sum((1 for r in falses if r['got'] is False))}/{len(falses)}")
        by = lambda h: sum((1 for r in results if r['how'] == h))
        print(f"  verdict source    signal {by('signal')}, prose {by('prose')}, unparsed {by('unparsed')}, error {by('error')}")
        replied = [r for r in results if r['how'] != 'error']
        if replied:
            blank = sum((1 for r in replied if not r['body'].strip()))
            short = sum((1 for r in replied if 0 < len(r['body'].strip()) < 80))
            print(f'  explanation       blank {blank}/{len(replied)}, under 80 chars {short}/{len(replied)}')
        ids = [r['id'] for r in results]
        if len(set(ids)) < len(ids):
            print('\nper case:')
            for cid in sorted(set(ids), key=ids.index):
                runs = [r for r in results if r['id'] == cid]
                passed = sum((1 for r in runs if r['got'] == r['correct']))
                print(f'  {cid}  {passed}/{len(runs)}  ({100 * passed / len(runs):.0f}%)')
    ran = [r for r in regressions if r[1] is not None]
    passed = sum((1 for _, ok, _ in ran if ok))
    if regressions:
        skipped = len(regressions) - len(ran)
        tail = f'  ({skipped} skipped)' if skipped else ''
        print(f"\nregressions       {passed}/{len(ran)}  {('PASS' if passed == len(ran) else 'FAIL')}{tail}")
    bad = [r for r in results if r['got'] != r['correct']]
    if bad:
        print('\nfailures:')
        for r in bad:
            want = 'CORRECT' if r['correct'] else 'WRONG'
            said = {True: 'CORRECT', False: 'WRONG', None: 'no verdict'}[r['got']]
            print(f"  {r['id']}  {r['topic']:22} wanted {want:7} got {said}")
            print(f"        {r['answer']}  ->  ...{r['detail']}")
    for name, ok, err in regressions:
        if ok is None:
            print(f'  SKIPPED     {name}')
        elif not ok:
            print(f'  REGRESSION  {name}' + (f'  ({err})' if err else ''))
    return 0 if not bad and passed == len(ran) else 1

def main():
    p = argparse.ArgumentParser(description='Eval harness for check mode')
    p.add_argument('--only', choices=['regress', 'cases'], help="Run just one half. 'regress' costs nothing.")
    p.add_argument('--provider', choices=['ollama', 'groq'], default='ollama')
    p.add_argument('--model', default='gemma4')
    p.add_argument('--ollama-host', default='http://localhost:11434')
    p.add_argument('--api-key', default='', help='Falls back to API_KEY in .env')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--case', nargs='+', metavar='ID', help='Run only these case IDs (e.g. --case q12 q21).')
    p.add_argument('--repeat', type=int, default=1, metavar='N', help='Run each selected case N times. Model flakiness on a single case cannot be told from an unlucky run without this.')
    args = p.parse_args()
    api_key = args.api_key.strip() or os.environ.get('API_KEY', '').strip()
    if args.provider == 'groq' and (not api_key) and (args.only != 'regress'):
        raise SystemExit('Groq needs a key: pass --api-key or set API_KEY in .env')
    if args.repeat < 1:
        raise SystemExit('--repeat must be at least 1')
    results = []
    if args.only != 'regress':
        cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
        if args.case:
            wanted = set(args.case)
            missing = wanted - {c['id'] for c in cases}
            if missing:
                raise SystemExit(f"Unknown case id(s): {', '.join(sorted(missing))}")
            cases = [c for c in cases if c['id'] in wanted]
        cases = cases * args.repeat
        print(f'running {len(cases)} cases on {args.provider}/{args.model}, {args.jobs} at a time...')
        results = run_cases(cases, args.provider, args.model, args.ollama_host, api_key, args.jobs)
    regressions = [] if args.only == 'cases' else regress.run()
    raise SystemExit(report(results, regressions))
if __name__ == '__main__':
    main()