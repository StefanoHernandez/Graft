#!/usr/bin/env bash
set -e
uv run alembic upgrade head || echo "no migrations yet"
exec uv run uvicorn graft.main:app --host 0.0.0.0 --port 8000
