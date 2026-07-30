@echo off
echo Starting OLLM Tutor...

echo.
python "%~dp0keycheck.py"
echo.

start "Ollama" cmd /k ollama serve
timeout /t 3 /nobreak >nul

start "Flask" cmd /k python app.py
timeout /t 2 /nobreak >nul

start http://localhost:5000
