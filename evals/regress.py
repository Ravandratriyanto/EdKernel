"""Bugs this project has already fixed once, so they cannot come back.

Every case here is a real defect from the devlog, not a hypothetical. No model
calls, so this runs in seconds, costs nothing, and the answer never moves.

A check returns True to pass, False to fail, or None to skip — skip is for a
check whose input is missing, which is not the same as a pass.
"""

import glob
import re

import pdftext
from ratelimit import RateLimiter
from vision.image_handler import drop_reasoning
from video.video_handler import _dedupe

CHECKS = []


def check(name):
    """Register a function as a named regression check.

    A decorator that takes an argument is two layers deep: check("...") runs
    first and returns `wrap`, then Python applies `wrap` to the function
    underneath it. `wrap` stores the pair and hands the function straight back,
    so the registry builds itself as this file loads. Adding a check is one
    function with no list to keep in step.
    """
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


# --- transcription -------------------------------------------------------

@check("drop_reasoning strips a closed <think> block")
def _closed_think():
    return drop_reasoning("<think>hmm</think>\nSolve x = 2") == "Solve x = 2"


@check("drop_reasoning kills an UNCLOSED <think> block")
def _unclosed_think():
    # 6,146 characters of the model talking to itself once reached the merge
    # prompt as the student's question. Empty is the honest answer, and callers
    # already skip an empty frame.
    return drop_reasoning("<think>The user wants me to transcribe...") == ""


@check("drop_reasoning leaves ordinary text alone")
def _plain_text():
    return drop_reasoning("  Solve 2x^2 = 8  ") == "Solve 2x^2 = 8"


# --- PDF extraction ------------------------------------------------------

@check("clean() does not raise a subscript (NH3 stays NH3)")
def _no_false_superscript():
    # Weak on its own: clean() has no rule that can add a ^. It guards against
    # the ORPHAN rejoining regex coming back — that one fixed 65 split
    # exponents and created 120 false ones, every NH3 and CO2 among them.
    # The real subscript guard is _real_pdf_superscripts below.
    return "^" not in pdftext.clean("NH3 and H2SO4 and CO2")


@check("dotted answer rules collapse to one blank")
def _dotted_rules():
    return pdftext.clean("Answer x = ...................... [4]") == "Answer x = ___ [4]"


@check("a ligature gap is closed")
def _ligature():
    return pdftext.clean("simplifi  es") == "simplifies"


@check("a spaced URL is closed")
def _url():
    return pdftext.clean("visit www .savemyexams.co.uk") == "visit www.savemyexams.co.uk"


@check("strip_repeats leaves a short document alone")
def _short_doc():
    # Under 4 pages there is no way to tell a footer from content.
    pages = ["Footer line that is long\nreal one",
             "Footer line that is long\nreal two"]
    return pdftext.strip_repeats(pages) == pages


@check("strip_repeats drops a running footer")
def _footer():
    pages = [f"Save My Exams - The Home of Revision\nquestion {i}" for i in range(5)]
    out = pdftext.strip_repeats(pages)
    return all("Save My Exams" not in p for p in out) and "question 3" in out[3]


@check("real papers still yield ^ exponents and no raised subscripts")
def _real_pdf_superscripts():
    """The end-to-end version of the two checks above, on actual papers.

    Three files, not all 25: the full corpus takes 47 seconds and gives the
    same answer. Measured 2026-08-09 — 25 files, 1,492 superscripts, 0 raised
    subscripts; these 3 alone, 58 and 0.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return None                     # pypdf not installed — skip, not pass
    papers = sorted(glob.glob("data/papers/*.pdf"))[:3]
    if not papers:
        return None                     # fresh clone, no papers downloaded
    text = ""
    for path in papers:
        text += "\n".join(pdftext.doc_pages(PdfReader(path)))
    # A subscript wrongly raised looks like NH^3 or CO^2.
    return "^" in text and not re.search(r"(?:NH|CO|H2SO|CH)\^", text)


# --- video ---------------------------------------------------------------

@check("_dedupe collapses frames of one page, keeping the fullest")
def _dedupe_same():
    got = _dedupe(["Solve 2x^2 + 7x - 3 = 0",
                   "Solve 2x^2 + 7x - 3 = O",     # one frame misread 0 as O
                   "Solve 2x^2 + 7x - 3 = 0 now"])
    return got == ["Solve 2x^2 + 7x - 3 = 0 now"]


@check("_dedupe keeps genuinely different pages")
def _dedupe_diff():
    return len(_dedupe(["Solve 2x^2 + 7x - 3 = 0", "Show all your working"])) == 2


# --- auth ----------------------------------------------------------------

@check("rate limiter allows attempts up to the limit")
def _limiter_allows():
    rl = RateLimiter(max_failures=3, window_seconds=900)
    for _ in range(2):
        rl.record_failure("ip:1.2.3.4", now=1000.0)
    return rl.retry_after("ip:1.2.3.4", now=1000.0) == 0


@check("rate limiter blocks on the nth failure")
def _limiter_blocks():
    rl = RateLimiter(max_failures=3, window_seconds=900)
    for _ in range(3):
        rl.record_failure("ip:1.2.3.4", now=1000.0)
    return rl.retry_after("ip:1.2.3.4", now=1000.0) > 0


@check("rate limiter forgets failures once the window passes")
def _limiter_window():
    rl = RateLimiter(max_failures=3, window_seconds=900)
    for _ in range(3):
        rl.record_failure("ip:1.2.3.4", now=1000.0)
    # One second after the window, the oldest failure has aged out.
    return rl.retry_after("ip:1.2.3.4", now=1000.0 + 901) == 0


@check("rate limiter keeps keys apart")
def _limiter_isolated():
    rl = RateLimiter(max_failures=3, window_seconds=900)
    for _ in range(3):
        rl.record_failure("ip:1.2.3.4", now=1000.0)
    # A blocked address must not block everyone else.
    return rl.retry_after("ip:5.6.7.8", now=1000.0) == 0


@check("a correct password clears the failure count")
def _limiter_cleared():
    rl = RateLimiter(max_failures=3, window_seconds=900)
    for _ in range(3):
        rl.record_failure("ip:1.2.3.4", "user:ravan", now=1000.0)
    rl.clear("ip:1.2.3.4", "user:ravan")
    return rl.retry_after("ip:1.2.3.4", "user:ravan", now=1000.0) == 0


@check("rate limiter does not leak keys that aged out")
def _limiter_no_leak():
    rl = RateLimiter(max_failures=3, window_seconds=900)
    rl.record_failure("ip:1.2.3.4", now=1000.0)
    rl.retry_after("ip:1.2.3.4", now=1000.0 + 901)
    return rl._hits == {}


@check("the session cookie is not marked secure on plain http")
def _cookie_secure_default():
    # A secure cookie over http is dropped silently, so the default must stay
    # off for localhost. OLLM_HTTPS=1 turns it on.
    import os
    return os.environ.get("OLLM_HTTPS", "").strip().lower() not in {"1", "true", "yes"}


def run():
    """Return (name, result, note) for every check. result is True/False/None."""
    out = []
    for name, fn in CHECKS:
        try:
            result = fn()
            out.append((name, result if result is None else bool(result), ""))
        except Exception as e:
            # A check that throws is a failure, not a crash of the whole run.
            out.append((name, False, f"{type(e).__name__}: {e}"))
    return out
