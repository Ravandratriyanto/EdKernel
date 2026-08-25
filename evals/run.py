"""Score check mode against questions with known answers.

    python -m evals.run                          everything
    python -m evals.run --only regress           no model calls, no cost
    python -m evals.run --provider ollama --model gemma4
    python -m evals.run --case q12 --repeat 30   diagnose one flaky case

The point is one number you can compare across prompt changes. Two regressions
shipped in this project because a change was checked structurally and never
against real model output.
"""

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from llm.client import generate
from rag.retrieve import retrieve
from prompts import build_check_prompt, strip_signal
from evals import regress

load_dotenv()

CASES = Path(__file__).parent / "cases.jsonl"

# The same pattern app.py uses, anchored to end-of-string. Kept identical on
# purpose: if the product's signal moves, this must fail, not quietly adapt.
_SIGNAL_RE = re.compile(r"\s*\[(CORRECT|WRONG)\]\s*$", re.IGNORECASE)

# Fallback for prose, because check mode does not currently emit a signal.
# Fragile by nature — "a common mistake is..." inside a correct verdict will
# fool it. That fragility is the argument for adding the signal, so the report
# counts how often this had to be used.
_NEG_RE = re.compile(r"(is not correct|is incorrect|is wrong|not correct|"
                     r"does not match|is not right|therefore.{0,20}incorrect)", re.I)
_POS_RE = re.compile(r"(is correct|answer is right|is indeed correct|"
                     r"correctly (solved|found|applied))", re.I)


def build_prompt(question: str, answer: str) -> str:
    """The real /api/check prompt, minus attachments.

    Calls the product's own builder rather than a copy. An eval that invents
    its own prompt measures the eval, not the product.
    """
    chunks = retrieve(question)
    context = "\n\n".join(chunks) if chunks else ""
    prefix = f"Reference material:\n{context}\n\n" if context else ""
    return build_check_prompt(question, answer, context_prefix=prefix)


def verdict(text: str) -> tuple:
    """(True / False / None, how it was decided)."""
    m = _SIGNAL_RE.search(text)
    if m:
        return m.group(1).upper() == "CORRECT", "signal"

    # The conclusion is nearly always at the end, so only read the tail. The
    # working above it often discusses wrong approaches on the way past.
    tail = text[-400:]
    neg, pos = _NEG_RE.search(tail), _POS_RE.search(tail)
    if neg and not pos:
        return False, "prose"
    if pos and not neg:
        return True, "prose"
    if neg and pos:
        # Both present: whichever lands later is the verdict.
        return neg.start() < pos.start(), "prose"
    return None, "unparsed"


def score_one(case, provider, model, host, api_key, tries=4):
    """Run one case. Returns the case plus what happened.

    Retries on a rate limit. Groq's free tier is 12,000 tokens a minute and the
    RAG context makes each case ~1,500, so a straight run of 30 will hit the
    limit. A case lost to a 429 is not a wrong answer, but it silently drops
    out of the score, which makes the number a lie.
    """
    prompt = build_prompt(case["question"], case["answer"])
    for attempt in range(tries):
        try:
            raw = generate(prompt, model=model, host=host,
                           provider=provider, api_key=api_key)
            got, how = verdict(str(raw))
            # The body the student would actually see. strip_signal is imported
            # from the product on purpose, unlike _SIGNAL_RE above, which this
            # file copies so it breaks when the signal moves. The question here
            # is not "does our regex agree" but "what reaches the student", and
            # only the product's own stripper can answer that.
            body, _ = strip_signal(str(raw))
            return {**case, "got": got, "how": how, "body": body,
                    "detail": str(raw)[-160:].replace("\n", " ")}
        except Exception as e:
            msg = str(e).lower()
            # A per-minute limit clears in seconds. A per-day one does not, so
            # do not burn 35 seconds of backoff on each of 30 cases finding out.
            daily = "tpd" in msg or "per day" in msg
            retryable = ("429" in msg or "rate limit" in msg) and not daily
            if not retryable or attempt == tries - 1:
                return {**case, "got": None, "how": "error", "body": "",
                        "detail": f"{type(e).__name__}: {e}"}
            # Back off further each time: 5s, 10s, 20s.
            time.sleep(5 * 2 ** attempt)


def run_cases(cases, provider, model, host, api_key, jobs):
    """Run every case, `jobs` at a time.

    These are network calls, so they spend nearly all their time waiting.
    Threads overlap that waiting — 30 cases 4 at a time is about four times
    faster at no extra cost. map() keeps the results in input order.
    """
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(
            lambda c: score_one(c, provider, model, host, api_key), cases))


def report(results, regressions):
    """Print the scores, then every failure. Returns the shell exit code."""
    # Every case counts, including ones with no readable verdict. got is None
    # there, which never equals True or False, so they score as misses — which
    # is right: the web UI cannot show a tick for those either.
    hits   = [r for r in results if r["got"] == r["correct"]]
    trues  = [r for r in results if r["correct"]]
    falses = [r for r in results if not r["correct"]]

    if results:
        pct = 100 * len(hits) / len(results)
        print(f"\ncheck mode        {len(hits)}/{len(results)}  ({pct:.0f}%)")
        # `is True` / `is False`, not truthiness. got is None when there was no
        # verdict at all, and `not None` is True — which silently counted every
        # rate-limited case as a successful rejection. It read "rejects wrong
        # 15/15" on a run where 7 of those 15 never reached the model.
        print(f"  accepts correct   {sum(1 for r in trues if r['got'] is True)}/{len(trues)}")
        print(f"  rejects wrong     {sum(1 for r in falses if r['got'] is False)}/{len(falses)}")

        by = lambda h: sum(1 for r in results if r["how"] == h)
        print(f"  verdict source    signal {by('signal')}, prose {by('prose')}, "
              f"unparsed {by('unparsed')}, error {by('error')}")

        # An empty body means the model sent a verdict and nothing else, so the
        # student sees a canned _EMPTY_REPLY line and no teaching at all. This
        # was 16/16 blank on 2026-08-18 underneath a 50/50 score: every number
        # above reads the verdict only, so a tutor that judges perfectly and
        # explains nothing scores full marks here. `replied` because `ran` is
        # taken by the regressions block below.
        replied = [r for r in results if r["how"] != "error"]
        if replied:
            blank = sum(1 for r in replied if not r["body"].strip())
            short = sum(1 for r in replied if 0 < len(r["body"].strip()) < 80)
            print(f"  explanation       blank {blank}/{len(replied)}, "
                  f"under 80 chars {short}/{len(replied)}")

        # Per-case rollup when --repeat runs the same case more than once. The
        # aggregate above answers "how good is the tutor"; this answers "how
        # flaky is q12", which is what --case exists for.
        ids = [r["id"] for r in results]
        if len(set(ids)) < len(ids):
            print("\nper case:")
            for cid in sorted(set(ids), key=ids.index):
                runs = [r for r in results if r["id"] == cid]
                passed = sum(1 for r in runs if r["got"] == r["correct"])
                print(f"  {cid}  {passed}/{len(runs)}  ({100 * passed / len(runs):.0f}%)")

    # A skipped check (result None) counts as neither passed nor failed.
    ran    = [r for r in regressions if r[1] is not None]
    passed = sum(1 for _, ok, _ in ran if ok)
    if regressions:
        skipped = len(regressions) - len(ran)
        tail = f"  ({skipped} skipped)" if skipped else ""
        print(f"\nregressions       {passed}/{len(ran)}  "
              f"{'PASS' if passed == len(ran) else 'FAIL'}{tail}")

    bad = [r for r in results if r["got"] != r["correct"]]
    if bad:
        print("\nfailures:")
        for r in bad:
            want = "CORRECT" if r["correct"] else "WRONG"
            said = {True: "CORRECT", False: "WRONG", None: "no verdict"}[r["got"]]
            print(f"  {r['id']}  {r['topic']:22} wanted {want:7} got {said}")
            print(f"        {r['answer']}  ->  ...{r['detail']}")

    for name, ok, err in regressions:
        if ok is None:
            print(f"  SKIPPED     {name}")
        elif not ok:
            print(f"  REGRESSION  {name}" + (f"  ({err})" if err else ""))

    return 0 if not bad and passed == len(ran) else 1


def main():
    p = argparse.ArgumentParser(description="Eval harness for check mode")
    p.add_argument("--only", choices=["regress", "cases"],
                   help="Run just one half. 'regress' costs nothing.")
    p.add_argument("--provider", choices=["ollama", "groq"], default="ollama")
    p.add_argument("--model", default="gemma4")
    p.add_argument("--ollama-host", default="http://localhost:11434")
    p.add_argument("--api-key", default="", help="Falls back to API_KEY in .env")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--case", nargs="+", metavar="ID",
                   help="Run only these case IDs (e.g. --case q12 q21).")
    p.add_argument("--repeat", type=int, default=1, metavar="N",
                   help="Run each selected case N times. Model flakiness on a "
                        "single case cannot be told from an unlucky run without this.")
    args = p.parse_args()

    api_key = args.api_key.strip() or os.environ.get("API_KEY", "").strip()
    if args.provider == "groq" and not api_key and args.only != "regress":
        raise SystemExit("Groq needs a key: pass --api-key or set API_KEY in .env")

    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")

    results = []
    if args.only != "regress":
        cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
        if args.case:
            wanted = set(args.case)
            missing = wanted - {c["id"] for c in cases}
            if missing:
                # Fail early rather than silently running a smaller set — a typo
                # in --case would otherwise pass with a flattering score.
                raise SystemExit(f"Unknown case id(s): {', '.join(sorted(missing))}")
            cases = [c for c in cases if c["id"] in wanted]
        cases = cases * args.repeat
        print(f"running {len(cases)} cases on {args.provider}/{args.model}, "
              f"{args.jobs} at a time...")
        results = run_cases(cases, args.provider, args.model,
                            args.ollama_host, api_key, args.jobs)

    regressions = [] if args.only == "cases" else regress.run()
    raise SystemExit(report(results, regressions))


if __name__ == "__main__":
    main()
