#!/usr/bin/env bash
# Linux equivalent of start.bat — launches Ollama and Flask, then opens the browser.
set -euo pipefail

cd "$(dirname "$0")"

OLLAMA_PORT=11434
FLASK_PORT=5000
LOG_DIR=".logs"
PIDS=()

mkdir -p "$LOG_DIR"

cleanup() {
    trap - EXIT INT TERM   # don't re-enter on the EXIT that follows a signal
    echo
    echo "Shutting down..."
    for pid in "${PIDS[@]:-}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3<&- && exec 3>&-
}

wait_for_port() {
    local port=$1 name=$2 tries=${3:-40}
    for ((i = 0; i < tries; i++)); do
        if port_open "$port"; then
            echo "$name is up on port $port"
            return 0
        fi
        sleep 0.5
    done
    echo "Timed out waiting for $name on port $port" >&2
    return 1
}

echo "Starting OLLM Tutor..."

# --- Ollama ---------------------------------------------------------------
# Skipped if already running, or if ollama isn't installed (the Groq provider
# can be selected in the UI instead).
if port_open "$OLLAMA_PORT"; then
    echo "Ollama already running on port $OLLAMA_PORT"
elif command -v ollama >/dev/null 2>&1; then
    echo "Starting Ollama (logging to $LOG_DIR/ollama.log)..."
    ollama serve >"$LOG_DIR/ollama.log" 2>&1 &
    PIDS+=($!)
    wait_for_port "$OLLAMA_PORT" "Ollama" || true
else
    echo "ollama not found on PATH — skipping. Use the Groq provider in the UI,"
    echo "or point the host field at a remote Ollama instance."
fi

# --- Flask ----------------------------------------------------------------
if [[ -x .venv/bin/python ]]; then
    PYTHON=.venv/bin/python
else
    PYTHON=$(command -v python3 || command -v python)
    echo "No .venv found — using $PYTHON"
fi

echo
"$PYTHON" keycheck.py
echo

if port_open "$FLASK_PORT"; then
    echo "Port $FLASK_PORT is already in use — is the app already running?" >&2
    exit 1
fi

echo "Starting Flask (logging to $LOG_DIR/flask.log)..."
"$PYTHON" app.py >"$LOG_DIR/flask.log" 2>&1 &
FLASK_PID=$!
PIDS+=("$FLASK_PID")

if ! wait_for_port "$FLASK_PORT" "Flask"; then
    echo "--- flask.log ---" >&2
    cat "$LOG_DIR/flask.log" >&2
    exit 1
fi

# --- Browser --------------------------------------------------------------
URL="http://localhost:$FLASK_PORT"
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
else
    echo "xdg-open not found — open $URL manually."
fi

echo
echo "OLLM Tutor running at $URL"
echo "Press Ctrl+C to stop."
echo

# Stream Flask output until it exits or we're interrupted.
tail -f "$LOG_DIR/flask.log" &
PIDS+=($!)
wait "$FLASK_PID"
