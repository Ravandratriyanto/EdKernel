import cv2
import numpy as np

WORK_WIDTH    = 900   
MIN_PAGE_FRAC = 0.25   
MAX_TILT      = 30.0   # ignore lines steeper than this; they are page edges, not text
SEARCH_SPAN   = 3.0    
SEARCH_STEP   = 0.1


def _order_corners(pts):
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    return rect


def _small(img):
    h, w = img.shape[:2]
    if w <= WORK_WIDTH:
        return img, 1.0
    s = WORK_WIDTH / w
    return cv2.resize(img, (WORK_WIDTH, int(h * s))), s


def ink_mask(img):
    """White ink on black, with each line of writing closed into a streak."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    m = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                              cv2.THRESH_BINARY_INV, 25, 15)
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((1, 25), np.uint8))


def find_page(img, min_area_frac=MIN_PAGE_FRAC):
    """Four page corners at full-image scale, or None."""
    small, scale = _small(img)
    sh, sw = small.shape[:2]

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    edges = cv2.Canny(gray, 50, 150)
    # Shadow and low contrast break a page edge into arcs. Closing rejoins them
    # so findContours sees one loop instead of four pieces.
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        if cv2.contourArea(c) < min_area_frac * sh * sw:
            break
        peri = cv2.arcLength(c, True)
        for eps in (0.02, 0.04, 0.06):
            approx = cv2.approxPolyDP(c, eps * peri, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                return (approx.reshape(4, 2) / scale).astype("float32")
    return None


def rectify(img, corners):
    rect = _order_corners(corners)
    tl, tr, br, bl = rect
    w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(rect, dst), (w, h))


def _rotate(img, deg):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def _contour_estimate(small):
    """Median tilt of the text-line blobs, or None.

    Reuses the same contour machinery as segmentation instead of a second
    HoughLinesP pass — Hough was the COOL-benchmark bottleneck (240 ms x86 /
    1587 ms Graviton). ink_mask() already closes each written line into a
    horizontal streak, so its external contours ARE the lines; the min-area
    rectangle of each gives that line's tilt. The angle is read from the
    longest edge of the box (via boxPoints) so it is independent of OpenCV's
    version-dependent minAreaRect angle convention.
    """
    m = ink_mask(small)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    min_len = m.shape[1] * 0.15          # ignore specks; a line spans the page
    angs = []
    for c in contours:
        rect = cv2.minAreaRect(c)
        box = cv2.boxPoints(rect)
        # angle of the longest edge, measured from horizontal
        p1, p2 = max(((box[i], box[(i + 1) % 4]) for i in range(4)),
                     key=lambda e: np.hypot(*(e[1] - e[0])))
        if np.hypot(*(p2 - p1)) < min_len:
            continue
        a = np.degrees(np.arctan2(float(p2[1] - p1[1]), float(p2[0] - p1[0])))
        if a > 90:  a -= 180
        if a < -90: a += 180
        if abs(a) <= MAX_TILT:
            angs.append(a)
    return float(np.median(angs)) if angs else None


def skew_angle(img):
    small, _ = _small(img)
    mask = ink_mask(small)
    h, w = mask.shape

    def score(deg):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
        r = cv2.warpAffine(mask, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        return float(np.var(r.sum(axis=1).astype(float)))

    start = _contour_estimate(small) or 0.0
    coarse = max(np.arange(start - SEARCH_SPAN, start + SEARCH_SPAN + 1e-9, 0.5), key=score)
    return float(max(np.arange(coarse - 0.5, coarse + 0.5 + 1e-9, SEARCH_STEP), key=score))


def deskew(img):
    a = skew_angle(img)
    return (img if abs(a) < 0.1 else _rotate(img, a)), a


def binarise(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, 25, 15)


def preprocess(path, debug=False):
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)

    corners = find_page(img)
    if corners is not None:
        page, how = rectify(img, corners), "perspective"
    else:
        page, a = deskew(img)
        how = f"deskew {a:+.2f} deg"

    out = binarise(page)
    return (out, how) if debug else out