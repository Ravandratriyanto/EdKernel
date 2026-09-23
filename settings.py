import json
from pathlib import Path
_PATH = Path(__file__).parent / 'settings.json'
DEFAULTS: dict = {'auth_required': True, 'stub_testing': True, 'rate_limiting': True}

def load() -> dict:
    if not _PATH.exists():
        return dict(DEFAULTS)
    try:
        return {**DEFAULTS, **json.loads(_PATH.read_text(encoding='utf-8'))}
    except Exception:
        return dict(DEFAULTS)

def save(data: dict) -> dict:
    merged = {k: bool(data.get(k, DEFAULTS[k])) for k in DEFAULTS}
    _PATH.write_text(json.dumps(merged, indent=2), encoding='utf-8')
    return merged