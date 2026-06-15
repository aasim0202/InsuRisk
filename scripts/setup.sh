#!/usr/bin/env bash
# InsuRisk one-shot setup (Linux / macOS)
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Creating Python virtual environment (.venv)"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing backend dependencies"
pip install --upgrade pip >/dev/null
pip install -r backend/requirements.txt

echo "==> Preparing environment file"
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "    Created backend/.env — open it and fill in TAVILY_API_KEY (and AWS keys if using S3)."
else
  echo "    backend/.env already exists — leaving it untouched."
fi

echo "==> Ollama model"
if command -v ollama >/dev/null 2>&1; then
  MODEL="$(grep -E '^OLLAMA_MODEL=' backend/.env | head -1 | cut -d= -f2)"
  MODEL="${MODEL:-mistral}"
  echo "    Pulling '$MODEL' (this can take a few minutes the first time)"
  ollama pull "$MODEL"
else
  echo "    Ollama not found. Install it from https://ollama.com/download then run: ollama pull mistral"
fi

cat <<'EOF'

==> Setup complete.

Start the backend:
    source .venv/bin/activate
    cd backend
    uvicorn main:app --reload --port 8000

Then open frontend/index.html in your browser.
EOF
