#!/usr/bin/env bash
# Sentinel console. Build the queue first if data/queue is empty:
#   python scripts/build_queue.py
set -e
python -m uvicorn sentinel.api.app:app --host 127.0.0.1 --port 8000 --reload
