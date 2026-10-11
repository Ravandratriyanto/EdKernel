@echo off
REM Lab launcher (Windows) — waitress, multi-threaded, for ~20 concurrent students.
REM gunicorn does NOT run on Windows (it needs fork), so the lab server here is
REM waitress. If it's missing:  pip install waitress
cd /d "%~dp0"

python "%~dp0keycheck.py"
echo.
echo ------------------------------------------------------------
echo  EdKernel LAB server (Windows) - waitress, 8 threads
echo  Students connect to:  http://<this-machine-ip>:5000
echo  Tips: wire in by Ethernet; turn auth ON in settings.json;
echo        keep this window open; Ctrl+C to stop.
echo ------------------------------------------------------------
echo.

waitress-serve --listen=0.0.0.0:5000 --threads=8 app:app
