import cv2

SAMPLE_EVERY_SEC = 4.0
DIFF_THRESHOLD = 12.0
MAX_FRAMES = 10
RESIZE_FOR_DIFF = (160, 90)

def _jpg(frame) -> bytes | None:
    ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None

def extract_keyframes(path: str, every: float=SAMPLE_EVERY_SEC, max_frames: int=MAX_FRAMES) -> list[bytes]:
    # Keep the LAST frame of each scene, not the first: whiteboard videos build up
    # ink slowly, so the frame just before a wipe is the full board and the one
    # just after is nearly blank. A scene ends when a sample drifts past
    # DIFF_THRESHOLD from the scene's first sample (a wipe, a new slide, or
    # enough ink added).
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(int(fps*every), 1)
    scene_start = None
    last_frame = None
    kept = []
    idx = 0
    while len(kept) < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            small = cv2.resize(frame, RESIZE_FOR_DIFF)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if scene_start is None:
                scene_start = gray
            elif cv2.absdiff(gray, scene_start).mean() > DIFF_THRESHOLD:
                jpg = _jpg(last_frame)
                if jpg:
                    kept.append(jpg)
                scene_start = gray
            last_frame = frame
        idx += 1
    cap.release()
    if last_frame is not None and len(kept) < max_frames:
        jpg = _jpg(last_frame)
        if jpg:
            kept.append(jpg)
    return kept
