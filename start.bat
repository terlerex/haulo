@echo off
cd /d "%~dp0"
if not exist .venv python -m venv .venv
.venv\Scripts\pip install -q -r requirements.txt
echo Acces local: http://localhost:8000
ipconfig | findstr /C:"IPv4"
.venv\Scripts\uvicorn app:app --host 0.0.0.0 --port 8000
