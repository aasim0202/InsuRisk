#!/usr/bin/env bash
# Switch the Ollama model InsuRisk uses (Linux / macOS)
# Usage: ./scripts/switch-model.sh <model>
#   e.g. ./scripts/switch-model.sh llama3.2:3b
set -e

MODEL="$1"
if [ -z "$MODEL" ]; then
  cat <<'EOF'
Usage: ./scripts/switch-model.sh <model>

Recommended models by RAM footprint:
  mistral        ~4.1 GB   default, best quality on 8GB
  llama3.2:3b    ~2.0 GB   lighter, strong JSON adherence
  phi3:mini      ~2.3 GB   strong step-by-step reasoning
  gemma2:2b      ~1.6 GB   lightest, for very constrained machines
EOF
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV="$ROOT/backend/.env"
[ -f "$ENV" ] || cp "$ROOT/backend/.env.example" "$ENV"

if command -v ollama >/dev/null 2>&1; then
  echo "==> Pulling $MODEL"
  ollama pull "$MODEL"
else
  echo "    Ollama not found — install from https://ollama.com/download (skipping pull)"
fi

if grep -qE '^OLLAMA_MODEL=' "$ENV"; then
  sed -i.bak "s|^OLLAMA_MODEL=.*|OLLAMA_MODEL=$MODEL|" "$ENV" && rm -f "$ENV.bak"
else
  echo "OLLAMA_MODEL=$MODEL" >> "$ENV"
fi

echo "==> OLLAMA_MODEL set to '$MODEL'. Restart the backend to apply."
