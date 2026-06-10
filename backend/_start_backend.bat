@echo off
cd /d "d:\DraftMind\backend"
set PYTHONPATH=.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info > "d:\DraftMind\backend\_uvicorn.log" 2>&1
