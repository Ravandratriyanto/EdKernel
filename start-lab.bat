@echo off
REM Lab launcher (Windows) — waitress, multi-threaded, for ~20 concurrent students.
REM gunicorn does NOT run on Windows (it needs fork), so the lab server here is
REM waitress. If it's missing:  pip install waitress
cd /d "%~dp0"

python "%~dp0keycheck.py"
echo.

set "LAN_IP="
for /f "delims=" %%a in ('powershell -NoProfile -Command "(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1).IPv4Address.IPAddress" 2^>nul') do set "LAN_IP=%%a"

echo ------------------------------------------------------------
echo  EdKernel LAB server (Windows) - waitress, 8 threads
if defined LAN_IP (
    echo  Students connect to:  http://%LAN_IP%:5000
) else (
    echo  Students connect to:  http://^<this machine's IP - run ipconfig^>:5000
)
echo  This machine only:    http://127.0.0.1:5000
echo  Tips: wire in by Ethernet; turn auth ON in settings.json;
echo        keep this window open; Ctrl+C to stop.
echo ------------------------------------------------------------
echo.

waitress-serve --listen=0.0.0.0:5000 --threads=8 app:app
