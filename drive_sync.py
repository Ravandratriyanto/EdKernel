import os 
from pathlib import Path 
import requests 
from dotenv import load_dotenv 

load_dotenv()
_API = "https://www.googleapis.com/drive/v3/files"


def list_files(folder_id: str, key: str) -> list[dict]:
    """Every non-trashed file directly inside the folder: id, name, mimeType."""
    params = {
        "q": f"'{folder_id}' in parents and trashed = false",
        "fields": "files(id, name, mimeType)",
        "key": key,
    }
    r = requests.get(_API, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("files", [])

def download(file_id: str, dest: Path, key: str) -> None:
    r = requests.get(f"{_API}/{file_id}", params={"alt": "media", "key": key}, timeout=60)
    r.raise_for_status()
    dest.write_bytes(r.content)

def sync(folder_id: str, dest_dir: str, key: str | None = None) -> list[str]:
    key = key or os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        raise SystemExit("GOOGLE API KEY NOT SET, PLEASE SET IT IN .env")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    names = []
    for f in list_files(folder_id, key):
        if f["mimeType"].startswith("application/vnd.google-apps"):
            print(f"  skip (Google-native): {f['name']}")
            continue
        download(f["id"], dest / f["name"], key)
        names.append(f["name"])
        print(f"  pulled: {f['name']}")
    return names
if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        raise SystemExit("usage: python drive_sync.py <folder_id> <dest_dir>")
    pulled = sync(sys.argv[1], sys.argv[2])
    print(f"\n{len(pulled)} file(s) synced to {sys.argv[2]}")
