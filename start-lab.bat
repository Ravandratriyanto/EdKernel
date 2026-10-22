@echo off
REM Lab launcher (Windows) - waitress, multi-threaded, for ~20 concurrent students.
REM gunicorn does NOT run on Windows (it needs fork), so the lab server here is
REM waitress.
REM
REM ======================= NOTES FOR CLAUDE CODE ON THE LAB LAPTOP =======================
REM (Written 2026-10-22 on the dev machine. Comments only - nothing here runs.)
REM
REM WHAT THIS SCRIPT DOES
REM   1. Checks flask, authlib, dotenv, waitress are installed (else: pip install -r requirements.txt)
REM   2. Runs lab_setup.py: shows API key status, WRITES settings.json to lab mode
REM      (auth_required=true, guest_login=true, stub_testing=false), checks ADPASS is set.
REM   3. Prints the LAN IP, then serves app.py with waitress on 0.0.0.0:5000.
REM
REM WHO OPENS WHAT (port 5000)
REM   Students, their own PCs:  http://<this laptop's LAN IP>:5000  -> guest button, type their name
REM   Teacher, THIS laptop:     http://localhost:5000  -> log in as 4dmin (password = ADPASS in .env)
REM                             then http://localhost:5000/chats  -> live chats, side by side
REM   Use localhost (not the IP) for the admin tab: different "site" to the browser, so a
REM   student login on this same laptop can't overwrite the admin cookie.
REM   The LAN IP changes when the network changes - read it off this window every time.
REM
REM THE DEV PANEL
REM   File: static\dev.html.  Served by app.py at /chats (needs an admin login) and at
REM   /dev/<DEV_PANEL_KEY> (key from .env). static\dev.html is in .gitignore - if this laptop
REM   got the code from GitHub, the file is MISSING and /chats 404s. Copy it over by hand.
REM
REM .env ON THIS LAPTOP NEEDS
REM   API_KEY=...        Groq key - the tutor does nothing without it
REM   ADPASS=...         password for the 4dmin account (no other way to reach /chats with auth on)
REM   DEV_PANEL_KEY=...  optional, for /dev/<key>
REM   Never put real keys in .env.example or any tracked file.
REM
REM IF STUDENTS CAN'T CONNECT
REM   - Windows Firewall: allow Python on Private AND Public networks (Windows asks once).
REM   - Same Wi-Fi? Guest Wi-Fi / "client isolation" blocks device-to-device traffic;
REM     use Ethernet or a phone hotspot instead.
REM   - Test from this laptop first: http://<LAN IP>:5000 must load here before anyone else's.
REM
REM KNOWN QUIRKS (see the last "## Session" entry in devlog.md for the full list)
REM   - Two students typing the SAME name share ONE guest account - ask for full names.
REM   - After this script runs, settings.json keeps login ON; plain "python app.py" will
REM     ask for a login until auth is switched off in the dev panel.
REM   - Only one class is live: "Math" (curricula\cambridge-as-p1). Lab quiz = 10 MCQs in
REM     curricula\cambridge-as-p1\quizzes.json. Pre/post scores show in the dev panel's Study box.
REM   - This script has NOT yet been run on Windows - if a line misbehaves, cmd.exe
REM     special characters ( ) < > ^ & inside echo are the usual cause.
REM ======================================================================================
cd /d "%~dp0"

REM Packages the server needs. Fail now, not when the first student logs in.
python -c "import flask, authlib, dotenv, waitress" 2>nul
if errorlevel 1 (
    echo Some Python packages are missing. Install them:
    echo     python -m pip install -r requirements.txt
    pause
    exit /b 1
)

REM Keys, lab settings (login ON, guests ON, demo class OFF) and the admin
REM password - shared with start-lab.sh so the two can't drift apart.
echo.
python "%~dp0lab_setup.py"
echo.

REM Bail if something already holds the port.
netstat -ano | findstr /r /c:":5000 .*LISTENING" >nul
if not errorlevel 1 (
    echo Port 5000 is already in use - is the server already running?
    pause
    exit /b 1
)

set "LAN_IP="
for /f "delims=" %%a in ('powershell -NoProfile -Command "(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1).IPv4Address.IPAddress" 2^>nul') do set "LAN_IP=%%a"

echo ------------------------------------------------------------
echo  EdKernel LAB server (Windows) - waitress, 8 threads
if defined LAN_IP (
    echo  Students connect to:  http://%LAN_IP%:5000
) else (
    echo  Students connect to:  http://^<this machine's IP - run ipconfig^>:5000
)
echo    they pick the guest option and type their name
echo.
echo  Watch the chats, on this machine:
echo    1. open http://localhost:5000 and log in as 4dmin
echo    2. then open http://localhost:5000/chats
echo    Use localhost, not the IP, so a student login in another tab
echo    doesn't replace yours.
echo.
echo  Students can't connect? Allow Python through Windows Firewall -
echo  Windows asks the first time; tick Private AND Public networks.
echo  The IP changes when you switch networks - read it off this box
echo  each time. Wire in by Ethernet; keep this window open; Ctrl+C to stop.
echo ------------------------------------------------------------
echo.

waitress-serve --listen=0.0.0.0:5000 --threads=8 app:app
pause
