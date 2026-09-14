import cv2 
import numpy as np

KERNEL_FRAC = 0.04
MIN_BOX_H = 8
MIN_BOX_W = 30
MAX_HEIGHT_MULT = 3.0
EDGE_MARGIN = 4
FRAME_SPAN = 0.8     # a border artifact runs most of a side...
FRAME_THIN = 10      # ...and is thin. Content that merely touches the edge stays.
ROW_OVERLAP = 0.5
MIN_INK_FRAC = 0.03   # real pen handwriting is ~0.08-0.11; sparse shadow speckle
                      # is ~0.02-0.03. Keep this BELOW real handwriting — dropping a
                      # real working line is worse than letting some noise through.
                      # (0.12 was over-tuned to synthetic putText text at 0.25+.)
                      # Lowered 0.05 -> 0.03 when this filter moved AFTER the row
                      # merge: a merged line box includes the gaps between terms,
                      # so "x = 6." in large sparse handwriting measures well under
                      # 0.05 and was being dropped as noise.
MIN_ASPECT = 1.5
MIN_SPECK = 3        # pre-merge: only discard dust, never a line fragment
def _smear(ink, kw):
    
    sm = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((1, kw), np.uint8))
    return cv2.dilate(sm, np.ones((3, max(3, kw // 2)), np.uint8), iterations=1)

def _merge_rows(boxes, overlap=ROW_OVERLAP):
    """Group blobs sitting on the same written line into one box per line.

    The bar for "same line" is a fraction of the MEDIAN blob height, not of
    the smaller of the two boxes. That distinction is the whole fix: with
    `overlap * min(h, H)` a 4px speck sets the bar at 2px, so one merge grew
    a box, the bigger box then reached the next row, and the page cascaded
    into a single box. A bar fixed to the median cannot be dragged down by
    the smallest thing in the set.

    Tuned on the 9 real photos in evals/vision_samples: 0.4-0.6 here against
    MIN_INK_FRAC 0.02-0.04 all score 8/9, so this sits in the middle of a
    plateau rather than on a knife edge.
    """
    if not boxes:
        return []
    bar = overlap * float(np.median([b[3] for b in boxes]))
    boxes = sorted(boxes, key=lambda b: b[1])
    changed = True
    while changed:
        changed = False
        out = []
        for x, y, w, h in boxes:
            merged = False
            for i, (X, Y, W, H) in enumerate(out):
                if min(y + h, Y + H) - max(y, Y) >= bar:
                    nx, ny = min(x, X), min(y, Y)
                    out[i] = (nx, ny, max(x + w, X + W) - nx, max(y + h, Y + H) - ny)
                    changed = merged = True
                    break
            if not merged:
                out.append((x, y, w, h))
        boxes = sorted(out, key=lambda b: b[1])
    return boxes

def segment(binary, kernel_frac=KERNEL_FRAC):
    """Cleaned page in, list of (x, y, w, h) in reading order out."""
    ink = 255 - binary                      # findContours wants white on black
    H, W = ink.shape
    kw = max(9, int(W * kernel_frac))

    contours, _ = cv2.findContours(_smear(ink, kw), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in contours]

    # Order matters here, and getting it wrong silently truncates every line.
    # The smear only closes gaps up to kw px, so one written line usually
    # arrives as SEVERAL blobs ("4x" and "=20" separately). MIN_BOX_W,
    # MIN_ASPECT and MIN_INK_FRAC describe a whole line of working, not a
    # fragment of one — applied before the merge they deleted the narrow
    # fragment, and the surviving piece became the "line". "4x = 20" was
    # cropped to "=20" and duly transcribed as "-20".
    # So: drop only page-border junk and specks first, merge into rows, and
    # judge line-shaped thresholds against line-shaped boxes.
    # Drop page-border artifacts, not content. The old test deleted ANY blob
    # touching the frame, which silently removed real working whenever a
    # stroke reached the edge: v6's "= 5" went because the 5's descender hit
    # the bottom row, leaving that line as a bare "x", which the vision model
    # duly read as rac{x}{x}. A real border artifact is a long THIN line
    # running most of a side -- require that shape before discarding.
    def _is_frame(x, y, w, h):
        touches = (x <= EDGE_MARGIN or y <= EDGE_MARGIN
                   or x + w >= W - EDGE_MARGIN or y + h >= H - EDGE_MARGIN)
        spans = w >= FRAME_SPAN * W or h >= FRAME_SPAN * H
        thin = max(w, h) >= FRAME_THIN * max(1, min(w, h))
        return touches and spans and thin

    boxes = [b for b in boxes if not _is_frame(*b)]
    boxes = [b for b in boxes if b[3] >= MIN_SPECK and b[2] >= MIN_SPECK]
    if not boxes:
        return []

    # Drop rules, brackets and margin lines BEFORE merging. A blob several
    # times taller than a typical line is not a fragment of one, and if it
    # survives into the merge it overlaps every row at once and collapses the
    # whole page into a single box (v4's left margin rule did exactly that).
    # The same filter runs again after the merge, on line-shaped boxes.
    med_h = float(np.median([b[3] for b in boxes]))
    boxes = [b for b in boxes if b[3] <= MAX_HEIGHT_MULT * med_h]
    if not boxes:
        return []

    boxes = _merge_rows(boxes)

    kept = []
    for (x, y, w, h) in boxes:
        patch = ink[y:y + h, x:x + w]
        density = float(np.count_nonzero(patch)) / float(w * h)
        if density >= MIN_INK_FRAC and (w / h) >= MIN_ASPECT                 and h >= MIN_BOX_H and w >= MIN_BOX_W:
            kept.append((x, y, w, h))
    boxes = kept
    if not boxes:
        return []

    med = float(np.median([b[3] for b in boxes]))
    boxes = [b for b in boxes if b[3] <= MAX_HEIGHT_MULT * med]

    return sorted(boxes, key=lambda b: b[1])

def crops(binary, boxes=None, pad=3):
    if boxes is None:
        boxes = segment(binary)
    H, W = binary.shape
    out = []
    for x, y, w, h in boxes:
        
        y0, y1 = max(0, y - pad), min(H, y + h + pad)
        x0, x1 = max(0, x - pad), min(W, x + w + pad)
        out.append(binary[y0:y1, x0:x1])
    return out

def draw(binary, boxes=None):
    if boxes is None: # Fixed indentation
        boxes = segment(binary)
    vis = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    for i, (x, y, w, h) in enumerate(boxes):
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cv2.putText(vis, str(i), (max(0, x - 16), y + h),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
    return vis
