"""Pull still frames out of a video question.

A filmed question is nearly always a static page, so most frames are the same
picture. ffmpeg's mpdecimate filter drops the near-duplicates, which is what
stops this spending one vision call per second of footage.
"""

import glob
import shutil
import subprocess
import tempfile
from pathlib import Path

SAMPLE_EVERY = 2.0      
MAX_FRAMES = 8          
_TIMEOUT = 120


class ExtractError(Exception):
    """No frames could be read."""


def extract_frames(path: str, every: float = SAMPLE_EVERY,
                   max_frames: int = MAX_FRAMES) -> list[bytes]:
    """Return JPEG bytes for the distinct frames of a video, in order."""
    if not Path(path).is_file():
        raise ExtractError(f"No such video: {path}")
    if shutil.which("ffmpeg") is None:
        raise ExtractError("ffmpeg is not installed")

    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            "ffmpeg", "-loglevel", "error", "-nostdin",
            "-i", str(path),
            "-vf", f"fps=1/{every},mpdecimate=hi=64*12:lo=64*5:frac=0.33",
            "-fps_mode", "vfr",
            "-frames:v", str(max_frames),
            "-q:v", "3",
            f"{tmp}/f%03d.jpg",
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ExtractError(f"ffmpeg took longer than {_TIMEOUT}s on {path}")

        files = sorted(glob.glob(f"{tmp}/f*.jpg"))
        if not files:
            tail = (r.stderr or "").strip().splitlines()
            raise ExtractError(f"No frames from {path}"
                               + (f": {tail[-1]}" if tail else ""))
        return [Path(f).read_bytes() for f in files]
