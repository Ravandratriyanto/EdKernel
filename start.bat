@echo off
echo Starting OLLM Tutor...

echo.
python "%~dp0keycheck.py"
echo.

start "Ollama" cmd /k ollama serve
call :wait_ready 11434 Ollama 20

start "Flask" cmd /k python app.py
call :wait_ready 5000 Flask 120

start http://localhost:5000
goto :eof

:wait_ready
setlocal
set "PORT=%~1"
set "NAME=%~2"
set "MAX_TRIES=%~3"
set "TRIES=0"
echo Waiting for %NAME% on port %PORT% (up to %MAX_TRIES%s)...
:wait_loop
set /a TRIES+=1
curl -s -o nul --max-time 2 http://localhost:%PORT%
if not errorlevel 1 (
    echo %NAME% is up ^(%TRIES%s^).
    endlocal
    goto :eof
)
if %TRIES% GEQ %MAX_TRIES% (
    echo Warning: %NAME% did not respond after %MAX_TRIES%s - continuing anyway.
    endlocal
    goto :eof
)
timeout /t 1 /nobreak >nul
goto wait_loop
