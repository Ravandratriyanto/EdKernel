import collections
import re
_DOTS = re.compile('\\.{4,}')
_LIG = re.compile('\\b(\\w*(?:ffi|ffl|fi|fl|ff))\\s{2,}([a-z]\\w*)')
_URL = re.compile('\\b(www|https?://\\S*?)\\s+\\.')

def page_text(page) -> str:
    runs = []

    def visit(text, cm, tm, font_dict, font_size):
        if text:
            runs.append([text, tm[5] * cm[3], abs(font_size * tm[0] * cm[0])])
    page.extract_text(visitor_text=visit)
    out, prev_y, prev_sz = ([], None, None)
    for text, y, size in runs:
        stripped = text.strip()
        if not stripped:
            out.append(text)
            continue
        raised = prev_y is not None and size < prev_sz * 0.85 and (0 < y - prev_y <= prev_sz * 0.7)
        if raised:
            out.append('^' + stripped)
        else:
            out.append(text)
            prev_y, prev_sz = (y, size)
    return ''.join(out)

def clean(s: str) -> str:
    s = _LIG.sub('\\1\\2', s)
    s = _DOTS.sub(' ___ ', s)
    s = _URL.sub('\\1.', s)
    s = re.sub('[ \\t]{2,}', ' ', s)
    return re.sub('\\n{3,}', '\n\n', s)

def strip_repeats(pages: list[str], min_share: float=0.6) -> list[str]:
    if len(pages) < 4:
        return pages
    seen = collections.Counter()
    for p in pages:
        for line in set((l.strip() for l in p.splitlines() if len(l.strip()) > 12)):
            seen[line] += 1
    cut = {line for line, n in seen.items() if n >= len(pages) * min_share}
    return ['\n'.join((l for l in p.splitlines() if l.strip() not in cut)) for p in pages]

def doc_pages(reader) -> list[str]:
    pages = []
    for i in range(len(reader.pages)):
        try:
            pages.append(clean(page_text(reader.pages[i])))
        except Exception:
            break
    return strip_repeats(pages)