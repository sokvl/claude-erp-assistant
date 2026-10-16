#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

docker compose up -d mongo1 mongo2 mongo3

source venv/bin/activate
exec uvicorn app.main:app --reload --app-dir src --host 0.0.0.0 --port 8000
