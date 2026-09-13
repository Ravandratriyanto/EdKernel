import cv2 
import numpy as np

KERNEL_FRAC = 0.04
MIN_BOX_H = 8
MIN_BOX_W = 30
MAX_HEIGHT_MULT = 3.0
EDGE_MARGIN = 4
ROW_OVERLAP = 0.5
MIN_INK_FRAC = 0.05   # real pen handwriting is ~0.08-0.11; sparse shadow speckle
                      # is ~0.02-0.03. Keep this BELOW real handwriting — dropping a
                      # real working line is worse than letting some noise through.
                      # (0.12 was over-tuned to synthetic putText text at 0.25+.)
MIN_ASPECT = 1.5
def _smear(ink, kw):
    
    sm = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((1, kw), np.uint8))
    return cv2.dilate(sm, np.ones((3, max(3, kw // 2)), np.uint8), iterations=1)

def _merge_rows(boxes, overlap=ROW_OVERLAP):

    boxes = sorted(boxes, key=lambda b: b[1])
    changed = True 
    while changed:
        changed = False 
        out = []
        for x, y, w, h in boxes:
            merged = False
            for i, (X, Y, W, H) in enumerate(out):
                # Calculate horizontal overlap metric if needed, or stick to vertical overlap
                if min(y + h, Y + H) - max(y, Y) > overlap * min(h, H):
                    nx, ny = min(x, X), min(y, Y)
                    out[i] = (nx, ny, max(x + w, X + W) - nx, max(y + h, Y + H) - ny)
                    changed = True 
                    merged = True
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
    kept = []
    for (x, y, w, h) in boxes:
        patch = ink[y:y + h, x:x + w]
        density = float(np.count_nonzero(patch)) / float(w * h)
        if density >= MIN_INK_FRAC and (w / h) >= MIN_ASPECT:
            kept.append((x, y, w, h))
    boxes = kept
    boxes = [(x, y, w, h) for (x, y, w, h) in boxes
             if x > EDGE_MARGIN and y > EDGE_MARGIN
             and x + w < W - EDGE_MARGIN and y + h < H - EDGE_MARGIN]
    boxes = [b for b in boxes if b[3] >= MIN_BOX_H and b[2] >= MIN_BOX_W]
    if not boxes:
        return []

    med = float(np.median([b[3] for b in boxes]))
    boxes = [b for b in boxes if b[3] <= MAX_HEIGHT_MULT * med]

    return _merge_rows(boxes)

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
