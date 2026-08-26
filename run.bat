@echo off
REM Sentinel console. Build the queue first if data\queue is empty:
REM   python scripts\build_queue.py
python -m uvicorn sentinel.api.app:app --host 127.0.0.1 --port 8000
