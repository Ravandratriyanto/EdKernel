"""Text extraction for past-paper PDFs.

pypdf's extract_text() throws away superscripts, so x² comes out as "x2" — a
different equation, and the tutor cannot tell. This recovers them from glyph
positions and cleans up the rest of the exam-paper noise.
"""

import collections
import re

_DOTS = re.compile(r"\.{4,}")
_LIG  = re.compile(r"\b(\w*(?:ffi|ffl|fi|fl|ff))\s{2,}([a-z]\w*)")
_URL  = re.compile(r"\b(www|https?://\S*?)\s+\.")


def page_text(page) -> str:
    """One page, with superscripts written as ^n."""
    runs = []

    def visit(text, cm, tm, font_dict, font_size):
        # pypdf reports font_size as 1.0 on most runs and hides the real scale
        # in the matrices, so the size has to be multiplied out.
        if text:
            runs.append([text, tm[5] * cm[3], abs(font_size * tm[0] * cm[0])])

    page.extract_text(visitor_text=visit)

    out, prev_y, prev_sz = [], None, None
    for text, y, size in runs:
        stripped = text.strip()
        if not stripped:
            out.append(text)
            continue
        # A superscript sits higher than the run before it and is set smaller.
        # Compare against the previous run, not the last normal one — a stale
        # baseline is what turns the subscript in NH3 into NH^3.
        raised = (prev_y is not None
                  and size < prev_sz * 0.85
                  and 0 < y - prev_y <= prev_sz * 0.7)
        if raised:
            out.append("^" + stripped)
        else:
            out.append(text)
            prev_y, prev_sz = y, size
    return "".join(out)


def clean(s: str) -> str:
    """Repair the noise that survives extraction."""
    s = _LIG.sub(r"\1\2", s)        # "simplifi  es" -> "simplifies"
    s = _DOTS.sub(" ___ ", s)       # answer rules -> one short blank
    s = _URL.sub(r"\1.", s)         # "www .site" -> "www.site"
    s = re.sub(r"[ \t]{2,}", " ", s)
    return re.sub(r"\n{3,}", "\n\n", s)


def strip_repeats(pages: list[str], min_share: float = 0.6) -> list[str]:
    """Drop lines that appear on most pages — running heads and footers."""
    if len(pages) < 4:
        return pages                # too few to tell a footer from content
    seen = collections.Counter()
    for p in pages:
        # set() first: a line repeated twice on one page still counts once.
        for line in set(l.strip() for l in p.splitlines() if len(l.strip()) > 12):
            seen[line] += 1
    cut = {line for line, n in seen.items() if n >= len(pages) * min_share}
    return ["\n".join(l for l in p.splitlines() if l.strip() not in cut)
            for p in pages]


def doc_pages(reader) -> list[str]:
    """Every page of an open PdfReader, cleaned. Survives a mid-file failure."""
    pages = []
    for i in range(len(reader.pages)):
        try:
            pages.append(clean(page_text(reader.pages[i])))
        except Exception:
            break                   # keep what was readable before the fault
    return strip_repeats(pages)
