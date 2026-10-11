#!/usr/bin/env bash
# Lab launcher — gunicorn (multi-worker) for ~20 concurrent students over the LAN.
# Unlike start.sh, which runs Flask's single-threaded dev server for solo work,
# this handles real concurrency. No Ollama / no browser: the lab uses Groq and
# students connect from their own PCs.
set -euo pipefail
cd "$(dirname "$0")"

PORT=5000
WORKERS=4
THREADS=4

# Prefer the venv's interpreter + gunicorn if a .venv exists.
if [[ -x .venv/bin/gunicorn ]]; then
    GUNICORN=.venv/bin/gunicorn
    PYTHON=.venv/bin/python
else
    PYTHON=$(command -v python3 || command -v python)
    GUNICORN=$(command -v gunicorn || true)
fi

if [[ -z "${GUNICORN:-}" ]]; then
    echo "gunicorn not found. Install it:  pip install gunicorn" >&2
    exit 1
fi

# Verify required keys (Groq etc.) before students show up.
echo
"$PYTHON" keycheck.py
echo

# Bail if something already holds the port.
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
    exec 3<&-; exec 3>&-
    echo "Port $PORT is already in use — is the server already running?" >&2
    exit 1
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "──────────────────────────────────────────────────────────"
echo " EdKernel LAB server — gunicorn ${WORKERS}w × ${THREADS}t"
echo " Students connect to:  http://${IP:-<this-machine-ip>}:$PORT"
echo " Tips: wire this machine in by Ethernet; turn auth ON in settings.json;"
echo "       keep this window open; Ctrl+C to stop."
echo "──────────────────────────────────────────────────────────"
echo

exec "$GUNICORN" -w "$WORKERS" --threads "$THREADS" --timeout 120 \
    --bind "0.0.0.0:$PORT" app:app
