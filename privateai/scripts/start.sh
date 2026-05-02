#!/usr/bin/env bash
# PrivateAI — one-command startup
# Usage: ./scripts/start.sh

set -e

BACKEND_DIR="$(cd "$(dirname "$0")/../backend" && pwd)"
FRONTEND_DIR="$(cd "$(dirname "$0")/../frontend" && pwd)"

echo ""
echo "╔══════════════════════════════╗"
echo "║        PrivateAI v0.1        ║"
echo "║   Local · Offline · Private  ║"
echo "╚══════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "❌ Python 3 required. Install from https://python.org"
  exit 1
fi

# Check Ollama (soft warning, not hard fail)
if ! command -v ollama &>/dev/null; then
  echo "⚠️  Ollama not found. Install: https://ollama.com"
  echo "   Then run: ollama pull gemma2:2b"
  echo "   (Backend will start, but LLM calls will fail until Ollama is running)"
  echo ""
fi

# Install Python deps if needed
if ! python3 -c "import fastapi" 2>/dev/null; then
  echo "📦 Installing backend dependencies..."
  pip3 install -r "$BACKEND_DIR/requirements.txt" -q
fi

# Check Node (for frontend dev server)
if command -v node &>/dev/null; then
  cd "$FRONTEND_DIR"
  if [ ! -d "node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    npm install -q
  fi

  echo "🚀 Starting frontend dev server..."
  npm run dev &
  FRONTEND_PID=$!
else
  echo "⚠️  Node.js not found — frontend dev server won't start."
  echo "   Install: https://nodejs.org"
fi

# Start backend
echo "🚀 Starting backend on http://127.0.0.1:8000"
echo ""
cd "$BACKEND_DIR"
python3 main.py &
BACKEND_PID=$!

echo "✅ PrivateAI running"
if command -v node &>/dev/null; then
  echo "   Frontend: http://localhost:5173"
fi
echo "   Backend:  http://localhost:8000"
echo "   API docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services."
echo ""

# Cleanup on exit
trap "kill $BACKEND_PID ${FRONTEND_PID:-} 2>/dev/null; echo 'Stopped.'" EXIT INT TERM
wait $BACKEND_PID
