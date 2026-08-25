import argparse
import json
import os
import re
import time 
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dotenv import load_dotenv 
from llm.client import chat 
from rag.retrieve import retrieve
from prompts import TUTOR_SYSTEM_PROMPT, hint_note, strip_signal
load_dotenv()
CASES = Path(__file__).parent / "learn_cases.jsonl"
ATTEMPTS = 3
def _norm(text: str ) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()
def _names(text: str, words) -> bool:
    r"""Does this hint name any of the concept words?
    A plain substring test fails here the way it failed in _leaks, but for the
    opposite reason. There the danger was being too strict; here it is being too
    loose. h3's concept word "light" matched inside "sunlight", so a rung-1 hint
    saying "sunlight, water and carbon dioxide" scored as naming a concept it had
    actually withheld, and the ladder was marked broken when it was not.

    So the boundary goes on the FRONT only. "light" no longer matches inside
    "sunlight", but "subtracting" still counts as naming "subtract" — an
    inflection is the same concept, and a \b on both ends would throw those away.

    The tail is a known ending rather than a character count. \w{0,3} was tried
    first and lost "splitting" (split + four), while widening it to four let
    "address" match "add". The optional \w is the doubled consonant in
    "splitting" and "adding"; without it those need a longer allowance than
    "address" can be kept out of.
    """
    return any(re.search(r'\b' + re.escape(w) + r'\w?(?:s|es|ed|ing)?\b',
                         text, re.I)
               for w in words)
def _leaks(text: str, answer: str) -> bool:
    r"""Is the final answer sitting in this text?

    A plain substring test fails here: the answer "5" matched the 5 inside
    "3x = 15", so a textbook rung-2 hint scored as a leak. The guards below stop
    a short answer matching inside a longer number.

    The guards are about DIGITS, not word characters, and are only added where
    the answer's own edge is a digit. Guarding on \w instead looks tidier and is
    wrong: it stops "chloroplast" matching "chloroplasts", so a hint that gives
    the answer in the plural reads as clean. Digits are the only thing that
    silently glues into a different value.

    The two sides differ on purpose: a "." to the LEFT means we are inside a
    decimal (0.5 is not 5), while a "." to the RIGHT is nearly always a full
    stop, and "the answer is 5." is a real leak.

    Known limit: a word answer is still a plain substring, so a short one would
    match inside a longer word. Subject terms are long enough that this has not
    come up.
    """
    left  = r"(?<![\d.])" if answer[:1].isdigit()  else ""
    right = r"(?!\d)"     if answer[-1:].isdigit() else ""
    return re.search(left + re.escape(answer) + right, text, re.I) is not None
def run_case(case, provider, model, host, api_key, tries=4):
    chunks = retrieve(case["topic"])
    context = "\n\n".join(chunks) if chunks else ""
    prefix = f"Reference material:\n{context}\n\n" if context else ""
    messages = [
        {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
        {"role": "user", "content": f"{prefix}Teach me about: {case['topic']}\n\n"
                                    f"Start with this question: {case['question']}"},
    ]
    hints = []
    for streak in range(1, ATTEMPTS + 1):
        note = hint_note(streak)
        messages.append({"role": "user", "content": case["wrong"] + note})

        for attempt in range(tries):
            try:
                raw = chat(messages, model=model, host=host,
                           provider=provider, api_key=api_key)
                break
            except Exception as e:
                msg = str(e).lower()
                daily = "tpd" in msg or "per day" in msg
                if not (("429" in msg or "rate limit" in msg) and not daily)                        or attempt == tries - 1:
                    return {**case, "hints": hints, "error": f"{type(e).__name__}: {e}"}
                time.sleep(5 * 2 ** attempt)

        reply, _ = strip_signal(str(raw))
        hints.append(reply)
    return {**case, "hints": hints, "error": None}
def judge(result):
    hints = result["hints"]
    if result["error"] or len(hints) < ATTEMPTS:
        return [("ran", False, result["error"] or f"only {len(hints)} hints")]
    first, second = hints[0], hints[1]
    concept, answer = result["concept"], result["answer"]
    seen = [_norm(h) for h in hints]
    return [
        ("hints differ", len(set(seen)) == ATTEMPTS,
         "two rungs produced the same text"),
        ("rung 1 withholds concept", not _names(first, concept),
         f"named {[w for w in concept if _names(first, [w])]} on the first hint"),
        ("rung 2 names concept", _names(second, concept),
         f"none of {concept} appeared by the second hint"),
        ("answer held back", not _leaks(first + " " + second, answer),
         f"leaked {answer!r} before the third hint"),
    ]
def run_cases(cases, provider, model, host, api_key, jobs):
    """Run every case, `jobs` at a time.

    Fewer jobs than run.py on purpose. Each case here is a three-turn
    conversation whose history grows every turn, so one case sends far more
    tokens than one check case does. A rate limit part way through does not
    just cost a retry — it returns a short `hints` list and the case scores as
    "ran: False", which reads like a broken ladder rather than a 429.
    """
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(
            lambda c: run_case(c, provider, model, host, api_key), cases))
def _trim(text: str, width: int = 200) -> str:
    """One line, short enough to read in a terminal."""
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= width else flat[:width - 1] + "…"
def report(results, show=False):
    """Print the score, then every failed check. Returns the shell exit code."""
    if not results:
        print("no cases ran")
        return 1

    judged = [(r, judge(r)) for r in results]
    passed = [r for r, checks in judged if all(ok for _, ok, _ in checks)]

    pct = 100 * len(passed) / len(judged)
    print(f"\nhint ladder       {len(passed)}/{len(judged)}  ({pct:.0f}%)")

    tally = {}
    for _, checks in judged:
        for name, ok, _ in checks:
            hit, total = tally.get(name, (0, 0))
            tally[name] = (hit + bool(ok), total + 1)
    for name in sorted(tally, key=lambda n: n == "ran"):
        hit, total = tally[name]
        print(f"  {name:26} {hit}/{total}")

    ids = [r["id"] for r, _ in judged]
    if len(set(ids)) < len(ids):
        print("\nper case:")
        for cid in sorted(set(ids), key=ids.index):
            runs = [c for r, c in judged if r["id"] == cid]
            ok = sum(1 for checks in runs if all(o for _, o, _ in checks))
            print(f"  {cid}  {ok}/{len(runs)}  ({100 * ok / len(runs):.0f}%)")

    failed = [(r, checks) for r, checks in judged
              if not all(ok for _, ok, _ in checks)]
    if failed:
        print("\nfailures:")
        for r, checks in failed:
            print(f"\n  {r['id']}  {r['topic']}")
            for name, ok, detail in checks:
                if not ok:
                    print(f"    FAIL  {name} — {detail}")
            for i, h in enumerate(r["hints"]):
                print(f"    rung {i + 1}  {_trim(h)}")

    if show:
        print("\nall hints:")
        for r, _ in judged:
            print(f"\n  {r['id']}  {r['topic']}")
            for i, h in enumerate(r["hints"]):
                print(f"    rung {i + 1}  {_trim(h, 400)}")

    return 0 if not failed else 1
def main():
    p = argparse.ArgumentParser(description="Eval harness for learn mode's hint ladder")
    p.add_argument("--provider", choices=["ollama", "groq"], default="ollama")
    p.add_argument("--model", default="gemma4")
    p.add_argument("--ollama-host", default="http://localhost:11434")
    p.add_argument("--api-key", default="", help="Falls back to API_KEY in .env")
    p.add_argument("--jobs", type=int, default=2,
                   help="Cases at a time. Lower than run.py's 4 because each "
                        "case is a three-turn conversation.")
    p.add_argument("--case", nargs="+", metavar="ID",
                   help="Run only these case IDs (e.g. --case h1 h4).")
    p.add_argument("--repeat", type=int, default=1, metavar="N",
                   help="Run each selected case N times, to tell a flaky "
                        "ladder from an unlucky run.")
    p.add_argument("--show", action="store_true",
                   help="Print all three hints for every case, passing or not.")
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

    print(f"running {len(cases)} cases x {ATTEMPTS} turns on "
          f"{args.provider}/{args.model}, {args.jobs} at a time...")
    results = run_cases(cases, args.provider, args.model,
                        args.ollama_host, api_key, args.jobs)
    raise SystemExit(report(results, show=args.show))
if __name__ == "__main__":
    main()