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

echo "==> Ollama models (primary + lighter fallback)"
if command -v ollama >/dev/null 2>&1; then
  for var in OLLAMA_MODEL OLLAMA_FALLBACK_MODEL; do
    M="$(grep -E "^${var}=" backend/.env | head -1 | cut -d= -f2 | cut -d'#' -f1 | tr -d ' ')"
    if [ -n "$M" ]; then
      echo "    Pulling '$M' (this can take a few minutes the first time)"
      ollama pull "$M" || echo "    (could not pull $M — skipping)"
    fi
  done
else
  echo "    Ollama not found. Install it from https://ollama.com/download then run: ollama pull mistral"
  echo "    (No local Ollama is fine — the app falls back to Ollama Cloud if OLLAMA_API_KEY is set.)"
fi

cat <<'EOF'

==> Setup complete.

Start the backend:
    source .venv/bin/activate
    cd backend
    uvicorn main:app --reload --port 8000

Then open frontend/index.html in your browser.
EOF
