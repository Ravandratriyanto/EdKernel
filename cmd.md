# cmd.md — running EdKernel (local / LAN / testing)

Quick command reference. Run everything from the repo root
(`/home/ravan/Desktop/EdKernel`).

## Start the server (LAN — students connect over the network)

```bash
# start it (keep this terminal open; Ctrl+C to stop)
gunicorn -w 4 --bind 0.0.0.0:5000 app:app

# more concurrency for a lab (threads help the I/O-bound tutor path)
gunicorn -w 4 --threads 4 --timeout 120 --bind 0.0.0.0:5000 app:app
```

`0.0.0.0` = listen on all interfaces (required for other PCs to reach it).
Wait for the `Listening at: http://0.0.0.0:5000` line.

> Do **not** use `python app.py` — this app has no `app.run()`, so it just
> imports and exits, leaving nothing listening. Always use gunicorn.

## Find this machine's LAN IP

```bash
hostname -I            # first address is usually the LAN one
ip -4 addr show scope global | grep -oP 'inet \K[\d.]+'
```

This host is currently **192.168.100.30** (ignore `172.17.0.1` — that's Docker).

## Connect from another PC (same network)

Browser: `http://<HOST_IP>:5000`  →  e.g. `http://192.168.100.30:5000`

Windows PowerShell checks:
```powershell
ping <HOST_IP>                                  # network reachable?
Test-NetConnection <HOST_IP> -Port 5000         # port open? want TcpTestSucceeded : True
```

Troubleshoot in this order:
1. `ping` fails → network/subnet issue or router client-isolation (not the app).
2. ping OK, port test False → gunicorn not running, or bound to `127.0.0.1`.
3. Check the server is up:  `ss -tlnp | grep :5000`

## Auth (lab vs open)

`settings.json` → `auth_required`. Currently `false` (open — anyone on the LAN
walks straight in). Flip to `true` for a lab so quiz results attribute per
student. First account created becomes **admin** regardless of role — make your
teacher/admin login first, then students.

## Ingest curriculum materials → ChromaDB

```bash
# build the vector collection for a curriculum (reads its reference/ + papers/)
python -m core.rag.ingest --curriculum gcse-maths
python -m core.rag.ingest --curriculum gcse-maths-test   # the small test set
```

Materials just need to land in `curricula/<id>/reference/` (the source is
swappable — local copy, git, or the Drive sync below). Then re-ingest.

## Sync materials from Google Drive (optional adapter)

```bash
# needs GOOGLE_API_KEY in .env and the folder shared "Anyone with link — Viewer"
python drive_sync.py <FOLDER_ID> curricula/<id>/reference
python -m core.rag.ingest --curriculum <id>
```

## Stress / load test

```bash
# page-serve capacity (no DB writes) — run from the host against localhost
python stress_test.py --url http://localhost:5000/ -c 10 -n 400
python stress_test.py --url http://localhost:5000/ -c 40 -n 800
python stress_test.py --url http://localhost:5000/ -c 60 -n 1200

# watch RAM while it runs (separate terminal)
watch -n1 free -h
```

Pass = <1% errors, zero `db-locked`, sane p95. If it OOMs, that caps the real
concurrency — this box has ~1.4GB free.

> After changing SQLite to WAL in `users.py`, **restart gunicorn** so workers
> pick up new connections.

## LLM backend (tutor/check need this; quiz marking does not)

- Groq key lives in `.env` as `API_KEY` — one shared server key, no per-student
  keys. Shared key = shared rate limit (~7k tokens/min), so 20+ concurrent tutor
  users will `429`. Use the **quiz flow** for big concurrent tests.
- Default provider is `ollama` (local, no rate limit) if you run Ollama instead.
```
