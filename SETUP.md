# InsuRisk — Full Local Setup Guide

Everything you need to run InsuRisk on your machine, including Ollama models and the
local↔cloud smart switch. Covers Windows (PowerShell) and Linux/macOS.

---

## 0. What you're running

```
Frontend (HTML)  →  FastAPI backend  →  Tavily (web) → ChromaDB (RAG) → Ollama LLM → JSON + S3
```

- **Backend:** FastAPI (Python) on port 8000
- **LLM:** Ollama — **local** (`mistral` / `llama3.2:3b`) or **Ollama Cloud** (`gpt-oss:120b`)
- **Web enrichment:** Tavily API
- **Vector store:** ChromaDB (in-memory)
- **Storage:** local JSON in `data/outputs/` + AWS S3

---

## 1. Prerequisites

- **Python 3.10–3.12** (3.11 recommended) → check: `python --version`
- **Ollama** (only if you want to run the model locally) → https://ollama.com/download
- **Tavily API key** → https://tavily.com (free tier, 1,000 calls/month)
- (optional) **Ollama Cloud key** → https://ollama.com/settings/keys
- (optional) **AWS S3 bucket** named `insurisk-outputs`

---

## 2. Install Ollama + pull models (LOCAL path)

> Skip this whole section if you're using **Ollama Cloud** (see §3). On machines where
> endpoint security (e.g. **CrowdStrike Falcon**) blocks the local Ollama runtime, local
> won't work — use Cloud instead.

1. Install Ollama from https://ollama.com/download
2. Pull the models (the project's local tier is `mistral`, then `llama3.2:3b` as a lighter fallback):

```bash
ollama pull mistral        # ~4.1 GB — primary, best quality on 8GB RAM
ollama pull llama3.2:3b    # ~2.0 GB — lighter fallback
```

3. Ollama runs a background server at `http://localhost:11434`. Verify:

```bash
curl http://localhost:11434/api/tags
```

| Model | RAM | Notes |
|---|---|---|
| `mistral` | ~4.1 GB | Default; best quality on 8GB |
| `llama3.2:3b` | ~2.0 GB | Lighter fallback |
| `phi3:mini` | ~2.3 GB | Strong step-by-step reasoning |
| `gemma2:2b` | ~1.6 GB | Lightest, very constrained machines |

---

## 3. The LLM smart switch (local vs cloud)

Controlled by `LLM_MODE` in `.env`:

| `LLM_MODE` | Behaviour |
|---|---|
| `auto` *(default)* | Try local Ollama (`mistral` → `llama3.2:3b`); if local is unreachable, fall back to **Ollama Cloud** (`gpt-oss:120b`). |
| `local` | Local only. |
| `cloud` | Ollama Cloud only (needs `OLLAMA_API_KEY`). |

**If CrowdStrike Falcon blocks local Ollama:** set `LLM_MODE=cloud` (or leave `auto` — it
will detect local is down and fall back). Cloud calls are plain HTTPS to `ollama.com`, so the
local Ollama daemon never starts and Falcon has nothing to block.

To use Cloud, set in `.env`:
```env
LLM_MODE=cloud
OLLAMA_CLOUD_URL=https://ollama.com
OLLAMA_CLOUD_MODEL=gpt-oss:120b      # pick from https://ollama.com/search?c=cloud
OLLAMA_API_KEY=<your-ollama-cloud-key>
```

---

## 4. Get the project

It's already on your Desktop at `C:\Users\aasim.reh051\Desktop\insurisk`. To clone elsewhere:

```bash
git clone https://github.com/aasim0202/InsuRisk.git
cd InsuRisk
```

---

## 5. Backend setup (virtual environment + dependencies)

### Windows (PowerShell)
```powershell
cd C:\Users\aasim.reh051\Desktop\insurisk
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```
> If activation is blocked: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` then retry.

### Linux / macOS
```bash
cd insurisk
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

> **Or use the one-shot script:** `.\scripts\setup.ps1` (Windows) / `./scripts/setup.sh`
> (Linux) — creates the venv, installs deps, copies `.env`, and pulls the local models.

---

## 6. Configure `.env`

On **this machine** `backend/.env` is **already filled in** — you don't need to change anything
to run it. If you're starting fresh on another machine:

```bash
# from the backend/ folder
copy .env.example .env      # Windows
cp .env.example .env        # Linux/macOS
```

Then fill it in. The full file looks like this:

```env
# LLM smart switch — auto | local | cloud
LLM_MODE=auto

# Local Ollama (tried first in auto mode)
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral
OLLAMA_FALLBACK_MODEL=llama3.2:3b

# Ollama Cloud fallback
OLLAMA_CLOUD_URL=https://ollama.com
OLLAMA_CLOUD_MODEL=gpt-oss:120b
OLLAMA_API_KEY=<your-ollama-cloud-key>

# Web enrichment
TAVILY_API_KEY=<your-tavily-key>

# Output storage
AWS_ACCESS_KEY_ID=<your-aws-access-key>
AWS_SECRET_ACCESS_KEY=<your-aws-secret-key>
AWS_S3_BUCKET=insurisk-outputs
```

> Your actual key values were provided during setup and are already in your local `backend/.env`.
> **Never commit `.env`** — it's git-ignored. Don't paste real keys into any tracked file.

---

## 7. Run the backend

```bash
# venv active, from the backend/ folder:
cd backend
uvicorn main:app --reload --port 8000
```

Confirm it's up and which provider it picked:
```bash
curl http://localhost:8000/health
# → {"status":"ok","llm_mode":"auto","active_provider":"local"|"cloud","active_model":"..."}
```

---

## 8. Open the frontend

Just open `frontend/index.html` in your browser (double-click, or):
```bash
# Linux
xdg-open frontend/index.html
```
The page auto-detects the API: when opened as a file it calls `http://localhost:8000`.
(When the backend serves it in deployment, it uses the same origin.)

---

## 9. Test it

- Use the **Classify** tab: enter a business name + address and hit **Classify Risk**.
- Sample inputs are in [`data/test_companies.md`](data/test_companies.md) (100 companies,
  10 Indian ones at the top).
- Example: `Infosys` / `Electronics City, Hosur Road, Bangalore, Karnataka 560100`

What you'll see: live stage progress, streamed reasoning, a risk badge, confidence bar,
industry + NAICS (with a Verified/mismatch badge), risk flags, sources, and metrics.

---

## 10. Other features

- **Batch:** the **Batch** tab takes a CSV with `business_name,address` columns
  (sample: `data/sample_businesses.csv`). Classifies every row, downloadable as JSON.
- **History:** the **History** tab lists past runs (read from `data/outputs/`); click to reopen.
- **Eval harness:** measure accuracy/latency against a labeled set:
  ```bash
  cd backend
  python evaluate.py                      # uses the model from .env
  python evaluate.py --model llama3.2:3b  # A/B compare a lighter model
  ```

---

## 11. Switching models

The model is read from `.env` at runtime — no code change needed.

```bash
# helper scripts
.\scripts\switch-model.ps1 -Model llama3.2:3b   # Windows
./scripts/switch-model.sh llama3.2:3b           # Linux/macOS
```
Or edit `OLLAMA_MODEL` (local) / `OLLAMA_CLOUD_MODEL` (cloud) in `.env` and restart uvicorn.

---

## 12. Troubleshooting

| Symptom | Fix |
|---|---|
| `np.float_ was removed in NumPy 2.0` | Already pinned `numpy<2.0` in requirements; reinstall: `pip install -r backend/requirements.txt`. |
| Backend can't reach Ollama / `All LLM providers failed` | Local Ollama not running or blocked → set `LLM_MODE=cloud` and a valid `OLLAMA_API_KEY`. |
| CrowdStrike Falcon blocks local Ollama | Use Cloud (`LLM_MODE=cloud`). The backend's HTTPS call to `ollama.com` doesn't start the local daemon. |
| Cloud model name rejected | Pick a current one from https://ollama.com/search?c=cloud and set `OLLAMA_CLOUD_MODEL`. |
| Frontend can't reach backend | Make sure uvicorn is on port 8000; if you opened the HTML from a custom host, append `?api=http://localhost:8000` to the URL. |
| `port 8000 already in use` | Run on another port: `uvicorn main:app --reload --port 8001` (and use `?api=http://localhost:8001`). |
| First classify is very slow | ChromaDB downloads the embedding model on first use — one-time. |
| Tavily errors / empty results | Check `TAVILY_API_KEY`; free tier is 1,000 calls/month. |

---

## Quick start (TL;DR)

```bash
# 1. (local LLM only) install Ollama, then:
ollama pull mistral && ollama pull llama3.2:3b
#    — or skip and use Ollama Cloud (set LLM_MODE=cloud + OLLAMA_API_KEY in .env)

# 2. backend
cd insurisk
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows  (Linux: source .venv/bin/activate)
pip install -r backend\requirements.txt
cd backend
uvicorn main:app --reload --port 8000

# 3. open frontend/index.html in your browser
```
