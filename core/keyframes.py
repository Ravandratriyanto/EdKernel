import cv2

SAMPLE_EVERY_SEC = 4.0 
DIFF_THRESHOLD = 12.0 
MAX_FRAMES = 10 
RESIZE_FOR_DIFF = (160, 90)

def extract_keyframes(path: str, every: float=SAMPLE_EVERY_SEC, max_frames: int=MAX_FRAMES) -> list[bytes]:
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(int(fps*every), 1)
    prev_gray = None
    kept = []
    idx = 0
    while len(kept) < max_frames:
        ok, frame = cap.read()
        if not ok:
            break 
        if idx % step == 0:
            small = cv2.resize(frame, RESIZE_FOR_DIFF)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if prev_gray is None or cv2.absdiff(gray, prev_gray).mean() > DIFF_THRESHOLD:
                ok2, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok2:
                    kept.append(buf.tobytes())
                prev_gray = gray 
        idx += 1
    cap.release()
    return kept 
