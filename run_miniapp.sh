#!/usr/bin/env bash
# Serves the Mini App API + static files (webapp.py). Put this behind a
# reverse proxy (nginx/caddy) with a real TLS cert, then point MINI_APP_URL
# in .env at that https address.
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
uvicorn webapp:app --host 127.0.0.1 --port 8088
