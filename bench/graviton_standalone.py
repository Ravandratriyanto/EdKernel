import cv2, numpy as np, time, json, platform, sys, argparse
from pathlib import Path

def make_img(h=1200, w=900):
    img = np.full((h, w, 3), 240, dtype=np.uint8)
    rng = np.random.default_rng(42)
    for y in range(80, h - 40, 60):
        cv2.line(img, (30, y), (w - 30, y), (180, 180, 180), 1)
    for _ in range(120):
        x = int(rng.integers(40, w - 80))
        y = int(rng.integers(40, h - 40))
        bw = int(rng.integers(30, 180))
        bh = int(rng.integers(4, 18))
        angle = float(rng.integers(-15, 15))
        cv2.ellipse(img, (x, y), (bw, bh), angle, 0, 360, (20, 20, 20), -1)
    return img

def binarise(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    blur = cv2.bilateralFilter(gray, 9, 75, 75)
    return cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 15)

def ink_mask(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return mask

def segment(binary):
    kernel = np.ones((1, 25), np.uint8)
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rows = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w > 40 and h > 4:
            rows.append((y, y + h))
    return sorted(rows)

def timeit(fn, n=50):
    for _ in range(3):
        fn()
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    arr = np.array(times) * 1000
    return (round(float(np.mean(arr)), 3), round(float(np.std(arr)), 3), round(1000.0 / float(np.mean(arr)), 2))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    ap.add_argument('--n-ops', type=int, default=50)
    args = ap.parse_args()
    img = make_img()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    binary = binarise(img)
    mask = ink_mask(img)
    kernel = np.ones((1, 25), np.uint8)
    h, w = img.shape[:2]
    src = np.float32([[10, 10], [w - 10, 10], [w - 10, h - 10], [10, h - 10]])
    dst = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    M = cv2.getPerspectiveTransform(src, dst)
    n = args.n_ops
    ops = [('resize', lambda: cv2.resize(img, (450, 600)), n), ('cvtColor', lambda: cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), n), ('bilateralFilter', lambda: cv2.bilateralFilter(gray, 9, 75, 75), n), ('adaptiveThreshold', lambda: cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 15), n), ('Canny', lambda: cv2.Canny(gray, 50, 150), n), ('morphologyEx', lambda: cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel), n), ('findContours', lambda: cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE), n), ('HoughLinesP', lambda: cv2.HoughLinesP(mask, 1, np.pi / 720, threshold=80, minLineLength=int(w * 0.25), maxLineGap=20), n), ('warpPerspective', lambda: cv2.warpPerspective(img, M, (w, h)), n), ('ink_mask', lambda: ink_mask(img), n), ('segment', lambda: segment(binary), 30), ('binarise (full)', lambda: binarise(img), 20)]
    info = {'python': sys.version.split()[0], 'opencv': cv2.__version__, 'platform': platform.platform(), 'machine': platform.machine(), 'cpu': platform.processor() or platform.machine(), 'numpy': np.__version__}
    print('\nEdKernel OpenCV Benchmark — Graviton')
    print('=' * 55)
    for k, v in info.items():
        print(f'  {k:<12}: {v}')
    results = []
    print(f"\n{'Operation':<22} {'Mean(ms)':>10} {'Std':>8} {'Img/s':>8}")
    print('-' * 52)
    for label, fn, iters in ops:
        mean, std, tput = timeit(fn, iters)
        print(f'  {label:<20} {mean:>10.2f} {std:>8.2f} {tput:>8.1f}')
        results.append({'operation': label, 'mean_ms': mean, 'std_ms': std, 'img_per_s': tput, 'n_iters': iters})
    payload = {'system': info, 'results': results}
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2))
        print(f'\nSaved -> {out}')
if __name__ == '__main__':
    main()