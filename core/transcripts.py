import re
import os 
import base64
import yt_dlp 
import tempfile 
from core.llm.client import transcribe_audio 
from core.vision.image_handler import transcribe as transcribe_frame
from core.keyframes import extract_keyframes
from youtube_transcript_api import YouTubeTranscriptApi

VIDEO_MAX_SECONDS = 1200 # This is 20 minutes long video worth 

_ID_RE = re.compile(r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})")

def video_id(url: str) -> str:
    m = _ID_RE.search(url or "")
    if not m:
        raise ValueError("Could not find a YouTube video id in that URL")
    return m.group(1)

def fetch_transcript(url: str) -> str:
    fetched = YouTubeTranscriptApi().fetch(video_id(url), languages=["en", "id"])
    text = " ".join(s.text for s in fetched).strip()
    if not text:
        raise ValueError("That video has no usable captions")
    return text 
def _probe_duration(url: str) -> float:
    with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'noplaylist': True}) as ydl:
        info = ydl.extract_info(url, download=False)
    return float(info.get('duration') or 0)
def _download(url: str, out_path: str) -> None:
    opts = {'format': 'worst[ext=mp4]/worst', 'outtmpl': out_path, 'quiet': True, 'noplaylist': True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

def transcribe_video(url: str, model: str='gemma4', host: str='http://localhost:11434',
                      provider: str='ollama', api_key: str='', vision_model: str='') -> str:
    duration = _probe_duration(url)
    if duration > VIDEO_MAX_SECONDS:
        raise ValueError(f'That video is too long for the no-captions fallback (limit {VIDEO_MAX_SECONDS // 60} min)')
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'video.mp4')
        _download(url, path)
        audio_text = ''
        try:
            audio_text = transcribe_audio(path, api_key=api_key)
        except Exception:
            pass
        frame_texts = []
        for i, jpg in enumerate(extract_keyframes(path), 1):
            b64 = base64.b64encode(jpg).decode()
            try:
                t = transcribe_frame(b64, name=f'frame{i}.jpg', provider=provider, model=model,
                                      host=host, api_key=api_key, vision_model=vision_model).strip()
            except Exception:
                continue
            if t:
                frame_texts.append(t)
        if not audio_text and not frame_texts:
            raise ValueError('Could not get any audio or readable frames from that video')
        parts = []
        if audio_text:
            parts.append('## Spoken content (audio transcript)\n' + audio_text)
        if frame_texts:
            parts.append('## On-screen content (from video frames)\n' + '\n\n'.join(frame_texts))
        return '\n\n'.join(parts)