@echo off
echo Starting OLLM Tutor...

start "Ollama" cmd /k ollama serve
timeout /t 3 /nobreak >nul

start "Flask" cmd /k python app.py
timeout /t 2 /nobreak >nul

start http://localhost:5000
