import cv2
import numpy as np
KERNEL_FRAC = 0.04
MIN_BOX_H = 8
MIN_BOX_W = 30
MAX_HEIGHT_MULT = 3.0
EDGE_MARGIN = 4
FRAME_SPAN = 0.8
FRAME_THIN = 10
ROW_OVERLAP = 0.5
MIN_INK_FRAC = 0.03
MIN_ASPECT = 1.5
MIN_SPECK = 3

def _smear(ink, kw):
    sm = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((1, kw), np.uint8))
    return cv2.dilate(sm, np.ones((3, max(3, kw // 2)), np.uint8), iterations=1)

def _merge_rows(boxes, overlap=ROW_OVERLAP):
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
                cy, CY = (y + h / 2, Y + H / 2)
                centred = Y <= cy <= Y + H or y <= CY <= y + h
                if min(y + h, Y + H) - max(y, Y) >= bar and centred:
                    nx, ny = (min(x, X), min(y, Y))
                    out[i] = (nx, ny, max(x + w, X + W) - nx, max(y + h, Y + H) - ny)
                    changed = merged = True
                    break
            if not merged:
                out.append((x, y, w, h))
        boxes = sorted(out, key=lambda b: b[1])
    return boxes

def segment(binary, kernel_frac=KERNEL_FRAC):
    ink = 255 - binary
    H, W = ink.shape
    kw = max(9, int(W * kernel_frac))
    contours, _ = cv2.findContours(_smear(ink, kw), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in contours]

    def _is_frame(x, y, w, h):
        touches = x <= EDGE_MARGIN or y <= EDGE_MARGIN or x + w >= W - EDGE_MARGIN or (y + h >= H - EDGE_MARGIN)
        spans = w >= FRAME_SPAN * W or h >= FRAME_SPAN * H
        thin = max(w, h) >= FRAME_THIN * max(1, min(w, h))
        return touches and spans and thin
    boxes = [b for b in boxes if not _is_frame(*b)]
    boxes = [b for b in boxes if b[3] >= MIN_SPECK and b[2] >= MIN_SPECK]
    if not boxes:
        return []
    med_h = float(np.median([b[3] for b in boxes]))
    boxes = [b for b in boxes if b[3] <= MAX_HEIGHT_MULT * med_h]
    if not boxes:
        return []
    boxes = _merge_rows(boxes)
    kept = []
    for x, y, w, h in boxes:
        patch = ink[y:y + h, x:x + w]
        density = float(np.count_nonzero(patch)) / float(w * h)
        if density >= MIN_INK_FRAC and w / h >= MIN_ASPECT and (h >= MIN_BOX_H) and (w >= MIN_BOX_W):
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
        y0, y1 = (max(0, y - pad), min(H, y + h + pad))
        x0, x1 = (max(0, x - pad), min(W, x + w + pad))
        out.append(binary[y0:y1, x0:x1])
    return out

def draw(binary, boxes=None):
    if boxes is None:
        boxes = segment(binary)
    vis = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    for i, (x, y, w, h) in enumerate(boxes):
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cv2.putText(vis, str(i), (max(0, x - 16), y + h), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
    return vis