#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

docker compose up -d mongo

source venv/bin/activate
exec uvicorn app.main:app --reload --app-dir src --host 0.0.0.0 --port 8000
