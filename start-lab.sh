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

# Packages the server needs. Fail now, not when the first student logs in.
if ! "$PYTHON" -c "import flask, authlib, dotenv" 2>/dev/null; then
    echo "Some Python packages are missing. Install them:" >&2
    echo "    $PYTHON -m pip install -r requirements.txt" >&2
    exit 1
fi

# Keys, lab settings (login ON, guests ON, demo class OFF) and the admin
# password — shared with start-lab.bat so the two can't drift apart.
echo
"$PYTHON" lab_setup.py
echo

# Bail if something already holds the port.
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
    exec 3<&-; exec 3>&-
    echo "Port $PORT is already in use — is the server already running?" >&2
    exit 1
fi

# Print the real resolved IP, not the 0.0.0.0 bind address — a browser can't
# connect to 0.0.0.0 (ERR_ADDRESS_INVALID). start-lab.bat hit this twice: once
# by only logging the waitress bind address, and once because its placeholder
# used literal <> characters, which cmd.exe parses as redirection and silently
# ate the whole line ("The system cannot find the file specified").
# `hostname` isn't installed on every distro (Arch ships without it), so fall
# back to asking the kernel which address it would use to reach the internet.
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
if [[ -z "$IP" ]]; then
    IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}' || true)
fi
echo "──────────────────────────────────────────────────────────"
echo " EdKernel LAB server — gunicorn ${WORKERS}w × ${THREADS}t"
echo " Students connect to:  http://${IP:-<this-machine-ip>}:$PORT"
echo "   (they pick the guest option and type their name)"
echo
echo " Watch the chats (on this machine):"
echo "   1. open http://localhost:$PORT and log in as 4dmin"
echo "   2. then open http://localhost:$PORT/chats"
echo "   Use localhost, not the IP, so a student login in another tab"
echo "   doesn't replace yours."
echo
echo " The IP changes when you switch networks — read it off this box"
echo " each time. Wire in by Ethernet; keep this window open; Ctrl+C to stop."
echo "──────────────────────────────────────────────────────────"
echo

exec "$GUNICORN" -w "$WORKERS" --threads "$THREADS" --timeout 120 \
    --bind "0.0.0.0:$PORT" app:app
