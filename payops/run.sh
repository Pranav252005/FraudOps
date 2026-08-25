#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
[ -f .env ] && set -a && . ./.env && set +a
echo
echo "  Sentinel is starting on http://127.0.0.1:8000"
echo
cd backend
exec python -m uvicorn app:app --host 127.0.0.1 --port 8000
