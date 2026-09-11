import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from core.vision.step_checker import check_working

load_dotenv()

CASES = Path(__file__).parent / "vision_cases.jsonl"


def score_one(case, provider, model, host, api_key, vision_model):
    img = Path(case["image"])
    if not img.exists():
        return {**case, "got": None, "how": "missing", "detail": f"no image at {img}"}
    try:
        result = check_working(str(img), provider=provider, model=model,
                               host=host, api_key=api_key, vision_model=vision_model)
        return {**case, "got": result["error_index"], "how": "ok",
                "detail": (result["explanation"] or "")[:160].replace("\n", " ")}
    except Exception as e:
        return {**case, "got": None, "how": "error",
                "detail": f"{type(e).__name__}: {e}"}


def report(results):
    scored = [r for r in results if r["how"] != "missing"]
    hits = [r for r in scored if r["got"] == r["error_index"]]
    err_cases = [r for r in scored if r["error_index"] is not None]
    ok_cases = [r for r in scored if r["error_index"] is None]

    if scored:
        print(f"\nstep checker      {len(hits)}/{len(scored)}  "
              f"({100 * len(hits) / len(scored):.0f}%)")
    else:
        print("\nno cases scored — add photos to evals/vision_samples/")

    if err_cases:
        loc = sum(1 for r in err_cases if r["got"] == r["error_index"])
        print(f"  error located     {loc}/{len(err_cases)}  (exact line)")
    if ok_cases:
        clean = sum(1 for r in ok_cases if r["got"] is None)
        print(f"  clean pass        {clean}/{len(ok_cases)}  (no false error)")

    missing = [r for r in results if r["how"] == "missing"]
    errored = [r for r in scored if r["how"] == "error"]
    if missing:
        print(f"  MISSING IMAGES    {len(missing)}")
    if errored:
        print(f"  PIPELINE ERRORS   {len(errored)}")

    bad = [r for r in scored if r["got"] != r["error_index"]]
    if bad:
        print("\nfailures:")
        for r in bad:
            print(f"  {r['id']}  wanted {r['error_index']}  got {r['got']}  "
                  f"({r.get('note', '')})")
            if r["detail"]:
                print(f"        ...{r['detail']}")

    for r in missing:
        print(f"  MISSING  {r['id']}  {r['detail']}")

    return 0 if scored and not bad else 1


def main():
    p = argparse.ArgumentParser(description="Eval harness for the step checker")
    p.add_argument("--provider", choices=["ollama", "groq"], default="ollama")
    p.add_argument("--model", default="gemma4")
    p.add_argument("--vision-model", default="",
                   help="Vision model if separate from --model")
    p.add_argument("--ollama-host", default="http://localhost:11434")
    p.add_argument("--api-key", default="", help="Falls back to API_KEY in .env")
    args = p.parse_args()

    api_key = args.api_key.strip() or os.environ.get("API_KEY", "").strip()
    if args.provider == "groq" and not api_key:
        raise SystemExit("Groq needs a key: pass --api-key or set API_KEY in .env")

    if not CASES.exists():
        raise SystemExit(f"No cases file at {CASES}")
    cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
    print(f"running {len(cases)} vision cases on {args.provider}/{args.model}...")

    results = [score_one(c, args.provider, args.model, args.ollama_host,
                         api_key, args.vision_model) for c in cases]
    raise SystemExit(report(results))


if __name__ == "__main__":
    main()
