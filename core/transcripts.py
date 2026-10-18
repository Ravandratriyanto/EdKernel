import re
from youtube_transcript_api import YouTubeTranscriptApi

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