"""Score multi-turn tutor conversations against a scripted dialogue.

    python -m evals.conversations
    python -m evals.conversations --case chem_chlorine
    python -m evals.conversations --show

Each case is a scripted student conversation. For every turn we send the
student line, receive the tutor reply, and judge it against per-turn rubric
(marker present, arithmetic shown, no leaked answer). This catches classes
of failure the single-turn check-mode eval cannot see:

  - a correct numeric answer confirmed without a [CORRECT] marker on the
    transition to the next question (the miss noted in Session 20)
  - a numeric confirmation reply that skips the arithmetic
  - the answer leaked at concept-intro before the student ever computes it

Runs jobs=1 by default. Each case sends N turns whose history grows each
turn — cheaper to serialise than to explain why the rate limit ate half the
cases.
"""

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
from core.prompts import TUTOR_SYSTEM_PROMPT, strip_signal
from core.vision.image_handler import drop_reasoning

load_dotenv()

CASES = Path(__file__).parent / "conversations.jsonl"

_MARKER_RE = re.compile(r"\[(CORRECT|WRONG|OPEN)\]\s*$", re.IGNORECASE)
_ARITH_RE = re.compile(r"\d+(?:\.\d+)?\s*[+\-×x*÷/]\s*\d+.*=\s*\d")


def _marker(raw_reply: str) -> str:
    """Return the trailing marker ('CORRECT'/'WRONG'/'OPEN'), or 'none'."""
    m = _MARKER_RE.search(raw_reply.rstrip())
    return m.group(1).upper() if m else "none"


def _shows_arithmetic(text: str) -> bool:
    """True if the reply contains a `a op b = c` line — evidence of working."""
    return _ARITH_RE.search(text) is not None


def _missing(text: str, needles) -> list:
    """Which of the needles are absent? Empty list = all present."""
    return [n for n in needles if not re.search(re.escape(n), text, re.I)]


def _leaked(text: str, needles) -> list:
    """Which of the needles appeared? Empty list = all withheld."""
    return [n for n in needles if re.search(re.escape(n), text, re.I)]


def run_case(case, provider, model, host, api_key, tries=4):
    """Walk one scripted dialogue turn by turn, keeping the full transcript."""
    chunks = retrieve(case["topic"])
    context = "\n\n".join(chunks) if chunks else ""
    prefix = f"Reference material:\n{context}\n\n" if context else ""

    messages = [{"role": "system", "content": TUTOR_SYSTEM_PROMPT}]
    first = True
    replies = []

    for turn in case["turns"]:
        content = turn["student"]
        if first:
            content = f"{prefix}{content}"
            first = False
        messages.append({"role": "user", "content": content})

        for attempt in range(tries):
            try:
                raw = chat(messages, model=model, host=host,
                           provider=provider, api_key=api_key)
                break
            except Exception as e:
                msg = str(e).lower()
                daily = "tpd" in msg or "per day" in msg
                if not (("429" in msg or "rate limit" in msg) and not daily) \
                        or attempt == tries - 1:
                    return {**case, "replies": replies,
                            "error": f"{type(e).__name__}: {e}"}
                time.sleep(5 * 2 ** attempt)

        raw_str = drop_reasoning(str(raw))
        marker = _marker(raw_str)
        reply, _ = strip_signal(raw_str)
        replies.append({"clean": reply, "marker": marker})
        messages.append({"role": "assistant", "content": raw_str})

    return {**case, "replies": replies, "error": None}


def judge_turn(reply, expect):
    """Return (name, ok, detail) tuples for one turn's rubric."""
    checks = []

    if "marker" in expect:
        want, got = expect["marker"].upper(), reply["marker"]
        checks.append(("marker", got == want,
                       f"wanted [{want}], got [{got}]"))

    if expect.get("shows_arithmetic"):
        ok = _shows_arithmetic(reply["clean"])
        checks.append(("shows arithmetic", ok,
                       "no `a op b = c` line found in the reply"))

    if "contains" in expect:
        missing = _missing(reply["clean"], expect["contains"])
        checks.append(("contains", not missing, f"missing: {missing}"))

    if "absent" in expect:
        leaked = _leaked(reply["clean"], expect["absent"])
        checks.append(("absent", not leaked, f"leaked: {leaked}"))

    return checks


def judge(result):
    """Judge every turn. Prefixes each check with its turn number."""
    if result["error"]:
        return [("ran", False, result["error"])]
    if len(result["replies"]) < len(result["turns"]):
        return [("ran", False,
                 f"only {len(result['replies'])}/{len(result['turns'])} turns ran")]

    all_checks = []
    for i, (turn, reply) in enumerate(
            zip(result["turns"], result["replies"]), 1):
        for name, ok, detail in judge_turn(reply, turn.get("expect", {})):
            all_checks.append((f"turn {i} — {name}", ok, detail))
    return all_checks


def run_cases(cases, provider, model, host, api_key, jobs):
    """Run every case, `jobs` at a time. Default 1 — see module docstring."""
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(
            lambda c: run_case(c, provider, model, host, api_key), cases))


def _trim(text, width=200):
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= width else flat[:width - 1] + "…"


def report(results, show=False):
    if not results:
        print("no cases ran")
        return 1

    judged = [(r, judge(r)) for r in results]
    passed = [r for r, checks in judged if all(ok for _, ok, _ in checks)]

    pct = 100 * len(passed) / len(judged)
    print(f"\nconversations     {len(passed)}/{len(judged)}  ({pct:.0f}%)")

    tally = {}
    for _, checks in judged:
        for name, ok, _ in checks:
            hit, total = tally.get(name, (0, 0))
            tally[name] = (hit + bool(ok), total + 1)
    for name in sorted(tally):
        hit, total = tally[name]
        print(f"  {name:32} {hit}/{total}")

    failed = [(r, checks) for r, checks in judged
              if not all(ok for _, ok, _ in checks)]
    if failed:
        print("\nfailures:")
        for r, checks in failed:
            print(f"\n  {r['id']}  {r['topic']}")
            for name, ok, detail in checks:
                if not ok:
                    print(f"    FAIL  {name} — {detail}")
            for i, rep in enumerate(r["replies"], 1):
                print(f"    turn {i}  [{rep['marker']}] {_trim(rep['clean'])}")

    if show:
        print("\nall transcripts:")
        for r, _ in judged:
            print(f"\n  {r['id']}  {r['topic']}")
            for i, (turn, rep) in enumerate(
                    zip(r["turns"], r["replies"]), 1):
                print(f"    S{i}  {_trim(turn['student'], 400)}")
                print(f"    T{i}  [{rep['marker']}] {_trim(rep['clean'], 400)}")

    return 0 if not failed else 1


def main():
    p = argparse.ArgumentParser(
        description="Eval harness for multi-turn tutor conversations")
    p.add_argument("--provider", choices=["ollama", "groq"], default="groq")
    p.add_argument("--model", default="openai/gpt-oss-120b")
    p.add_argument("--ollama-host", default="http://localhost:11434")
    p.add_argument("--api-key", default="",
                   help="Falls back to API_KEY in .env")
    p.add_argument("--jobs", type=int, default=1,
                   help="Cases at a time. Default 1: each case is many turns "
                        "and the free-tier TPM ceiling is 8000.")
    p.add_argument("--case", nargs="+", metavar="ID",
                   help="Run only these case IDs.")
    p.add_argument("--repeat", type=int, default=1, metavar="N")
    p.add_argument("--show", action="store_true",
                   help="Print every turn of every case, passing or not.")
    args = p.parse_args()

    api_key = args.api_key.strip() or os.environ.get("API_KEY", "").strip()
    if args.provider == "groq" and not api_key:
        raise SystemExit("Groq needs a key: pass --api-key or set API_KEY in .env")
    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")

    cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
    if args.case:
        wanted = set(args.case)
        missing = wanted - {c["id"] for c in cases}
        if missing:
            raise SystemExit(f"Unknown case id(s): {', '.join(sorted(missing))}")
        cases = [c for c in cases if c["id"] in wanted]
    cases = cases * args.repeat

    print(f"running {len(cases)} cases on {args.provider}/{args.model}, "
          f"{args.jobs} at a time...")
    results = run_cases(cases, args.provider, args.model,
                        args.ollama_host, api_key, args.jobs)
    raise SystemExit(report(results, show=args.show))


if __name__ == "__main__":
    main()
