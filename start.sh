#!/bin/bash
echo "Starting HR Agent..."

# Get the absolute path of this script's directory
DIR="/Users/aditya/Desktop/HR-Agent"

# Start Redis in background
docker compose -f "$DIR/docker/docker-compose.dev.yml" up -d
echo "✓ Redis started"

# Ollama already running — skip (address already in use is fine)
echo "✓ Ollama already running"

# Start frontend in background
lsof -ti:5500 | xargs kill -9 2>/dev/null
cd "$DIR/frontend" && python -m http.server 5500 &
echo "✓ Frontend started at http://localhost:5500/voice.html"

# Start FastAPI — must be run from backend/ with venv
cd "$DIR/backend"
source "$DIR/backend/venv/bin/activate"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
