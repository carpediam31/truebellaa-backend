#!/usr/bin/env bash
# Convenience script to run the API locally.
set -e
python -m venv venv 2>/dev/null || true
source venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Starting TrueBellaa API on http://localhost:8000 (docs at /docs)"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
