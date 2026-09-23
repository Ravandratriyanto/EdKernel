import argparse
import json
import platform
import sys
import time
from pathlib import Path
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.vision.preprocess import ink_mask, find_page, binarise, deskew, preprocess
from core.vision.segment import segment

def _make_page(h=1200, w=900):
    img = np.full((h, w, 3), 240, dtype=np.uint8)
    rng = np.random.default_rng(42)
    for y in range(80, h - 40, 60):
        cv2.line(img, (30, y), (w - 30, y), (180, 180, 180), 1)
    for _ in range(120):
        x = int(rng.integers(40, w - 80))
        y = int(rng.integers(40, h - 40))
        bw = int(rng.integers(30, 180))
        bh = int(rng.integers(4, 18))
        cv2.ellipse(img, (x, y), (bw, bh), float(rng.integers(-15, 15)), 0, 360, (20, 20, 20), -1)
    return img

def _make_binary(h=1200, w=900):
    return binarise(_make_page(h, w))

def _timeit(fn, n=50):
    for _ in range(3):
        fn()
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    arr = np.array(times) * 1000
    mean = float(np.mean(arr))
    std = float(np.std(arr))
    tput = float(1000 / mean)
    return (mean, std, tput)

def bench_resize(img, n=50):
    return _timeit(lambda: cv2.resize(img, (450, 600)), n)

def bench_cvtcolor(img, n=50):
    return _timeit(lambda: cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), n)

def bench_bilateral(img, n=50):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return _timeit(lambda: cv2.bilateralFilter(gray, 9, 75, 75), n)

def bench_adaptive_threshold(img, n=50):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return _timeit(lambda: cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 15), n)

def bench_canny(img, n=50):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return _timeit(lambda: cv2.Canny(gray, 50, 150), n)

def bench_morphology(img, n=50):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    kernel = np.ones((1, 25), np.uint8)
    return _timeit(lambda: cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel), n)

def bench_find_contours(img, n=50):
    binary = _make_binary()
    ink = 255 - binary
    return _timeit(lambda: cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE), n)

def bench_hough(img, n=50):
    mask = ink_mask(img)
    W = mask.shape[1]
    return _timeit(lambda: cv2.HoughLinesP(mask, 1, np.pi / 720, threshold=80, minLineLength=int(W * 0.25), maxLineGap=20), n)

def bench_warp_perspective(img, n=50):
    corners = find_page(img)
    if corners is None:
        h, w = img.shape[:2]
        src = np.float32([[10, 10], [w - 10, 10], [w - 10, h - 10], [10, h - 10]])
        dst = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        M = cv2.getPerspectiveTransform(src, dst)
        return _timeit(lambda: cv2.warpPerspective(img, M, (w, h)), n)
    from core.vision.preprocess import _order_corners, rectify
    return _timeit(lambda: rectify(img, corners), n)

def bench_ink_mask(img, n=50):
    return _timeit(lambda: ink_mask(img), n)

def bench_segment_pipeline(n=30):
    binary = _make_binary()
    return _timeit(lambda: segment(binary), n)

def bench_full_preprocess(img, n=20):
    return _timeit(lambda: binarise(deskew(img)[0]), n)
SUITES = [('resize (900→450)', bench_resize, {}), ('cvtColor BGR→Gray', bench_cvtcolor, {}), ('bilateralFilter', bench_bilateral, {}), ('adaptiveThreshold', bench_adaptive_threshold, {}), ('Canny edge detect', bench_canny, {}), ('morphologyEx CLOSE', bench_morphology, {}), ('findContours', bench_find_contours, {}), ('HoughLinesP', bench_hough, {}), ('warpPerspective', bench_warp_perspective, {}), ('ink_mask (full)', bench_ink_mask, {}), ('segment pipeline', bench_segment_pipeline, {'img': None}), ('preprocess (full page)', bench_full_preprocess, {})]

def run_all(n_ops=50, n_pipeline=20):
    img = _make_page()
    results = []
    print(f"\n{'Operation':<30} {'Mean (ms)':>10} {'Std (ms)':>9} {'Img/s':>8}")
    print('-' * 62)
    for label, fn, kwargs in SUITES:
        if 'img' in kwargs and kwargs['img'] is None:
            n = n_pipeline
            mean, std, tput = fn(n=n)
        else:
            n = n_ops
            mean, std, tput = fn(img, n=n)
        print(f'  {label:<28} {mean:>10.2f} {std:>9.2f} {tput:>8.1f}')
        results.append({'operation': label, 'mean_ms': round(mean, 3), 'std_ms': round(std, 3), 'img_per_s': round(tput, 2), 'n_iters': n})
    return results

def system_info():
    return {'python': sys.version.split()[0], 'opencv': cv2.__version__, 'platform': platform.platform(), 'machine': platform.machine(), 'cpu': platform.processor() or platform.machine(), 'numpy': np.__version__}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None, help='Save JSON results to this path')
    ap.add_argument('--n-ops', type=int, default=50, help='Iterations per isolated op')
    ap.add_argument('--n-pipeline', type=int, default=20, help='Iterations for pipeline ops')
    args = ap.parse_args()
    info = system_info()
    print('\nEdKernel OpenCV Benchmark')
    print('=' * 62)
    for k, v in info.items():
        print(f'  {k:<12}: {v}')
    results = run_all(n_ops=args.n_ops, n_pipeline=args.n_pipeline)
    payload = {'system': info, 'results': results}
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2))
        print(f'\nResults saved → {out}')
    else:
        print('\n(use --out results/x86.json to save for comparison)')
    return payload
if __name__ == '__main__':
    main()