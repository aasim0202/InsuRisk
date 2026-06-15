# InsuRisk — Business Risk Classifier

> AI-powered commercial insurance underwriting intelligence. Enriches a business name + address with real-time public web data, grounds it via RAG, and uses a local LLM to generate a **structured, validated, and source-cited** risk classification.

![CI](https://github.com/aasim0202/InsuRisk/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi)
![Ollama](https://img.shields.io/badge/Ollama-Mistral%207B-black?style=flat-square)
![ChromaDB](https://img.shields.io/badge/ChromaDB-RAG-orange?style=flat-square)
![AWS S3](https://img.shields.io/badge/AWS-S3-FF9900?style=flat-square&logo=amazon-aws)

> Full feature walkthrough: see **[FEATURES.md](FEATURES.md)**.

---

## Architecture

```
Frontend (HTML)  ──tabs──▶  Classify · Batch · History
    │  POST /classify/stream  (Server-Sent Events)
    ▼
FastAPI Backend
    ├── Step 1 → Tavily API        3 web searches (risk / OSHA / industry)
    ├── Step 2 → ChromaDB          embed chunks, top-5 RAG retrieval
    ├── Step 3 → Ollama Mistral    chain-of-thought prompt, streamed token-by-token
    ├── Step 4 → Post-processing   JSON extraction · confidence clamp · NAICS validation
    └── Step 5 → Output            local JSON + AWS S3 upload + metrics
```

---

## Features

| Feature | What it does |
|---|---|
| **Live streaming classification** | Stage-by-stage progress + the LLM's reasoning streamed token-by-token over SSE |
| **Evidence & source citations** | Every classification lists the exact Tavily URLs + snippets it was grounded in |
| **NAICS validation layer** | The LLM's NAICS code is checked against a reference table; flags unverified codes, industry mismatches, and reconciles LLM risk vs. the rule-based baseline |
| **Pipeline metrics** | Per-stage latency (Tavily / RAG / LLM), model name, chunks indexed, context size |
| **Batch mode** | Upload a CSV of businesses → classify all → download results as JSON |
| **History** | Browse and re-open every past classification saved locally |
| **Eval harness** | `evaluate.py` scores the classifier against a labeled set — industry + risk accuracy, mean confidence, mean latency |

---

## Output Schema

```json
{
  "industry": "Automotive Repair",
  "naics_code": "811111",
  "risk_level": "MEDIUM",
  "confidence_score": 0.82,
  "risk_flags": ["Chemical waste handling", "Lift equipment hazards"],
  "chain_of_thought": "Step 1: This is an auto repair shop...",
  "summary": "Joe's Auto Repair operates in a moderate-risk segment...",
  "naics_validation": {
    "known": true,
    "official_description": "General Automotive Repair",
    "industry_match": true,
    "expected_risk": "MEDIUM",
    "status": "verified",
    "risk_reconciliation": { "aligned": true, "note": "LLM risk (MEDIUM) matches rule baseline." }
  },
  "sources": [ { "title": "...", "url": "https://...", "snippet": "..." } ],
  "metrics": { "tavily_ms": 1240, "rag_ms": 410, "llm_ms": 8100, "total_ms": 9750, "model": "mistral" }
}
```

---

## Tech Stack

| Component | Tool | Why |
|---|---|---|
| Backend API | FastAPI | Async, fast, SSE streaming, auto-docs |
| LLM inference | Ollama + Mistral 7B (Q4_K_M) | Free, local, ~4.1GB RAM |
| Web enrichment | Tavily API | LLM-optimized search results |
| Vector store | ChromaDB (in-memory) | RAG retrieval, no infra needed |
| Output storage | Local JSON + AWS S3 | Mirrors production insurtech pipelines |
| Frontend | Vanilla HTML/CSS/JS | Zero dependencies, dark theme |

---

## Setup

### Prerequisites
- Python 3.10+
- [Ollama](https://ollama.com/download) installed and running
- Tavily API key (free tier at [tavily.com](https://tavily.com))
- (Optional) AWS S3 bucket named `insurisk-outputs` — skipped gracefully if not configured

### 1. Pull the model

```bash
ollama pull mistral
```

~4GB once. Runs in **Q4_K_M quantization** — safe on 8GB RAM.

> **Lighter machine?** The model is read from `.env` at runtime, so switching needs no code change. Use the helper script:
> ```bash
> ./scripts/switch-model.sh llama3.2:3b        # Linux / macOS
> .\scripts\switch-model.ps1 -Model llama3.2:3b # Windows
> ```
> | Model | RAM | Notes |
> |---|---|---|
> | `mistral` | ~4.1 GB | Default; best quality on 8GB |
> | `llama3.2:3b` | ~2.0 GB | Lighter, strong JSON adherence |
> | `phi3:mini` | ~2.3 GB | Strong step-by-step reasoning |
> | `gemma2:2b` | ~1.6 GB | Lightest, very constrained machines |

---

### Fast path — setup scripts

```bash
# Linux / macOS
git clone https://github.com/aasim0202/InsuRisk.git
cd InsuRisk
./scripts/setup.sh        # venv + deps + .env + pulls the Ollama model
```

```powershell
# Windows
git clone https://github.com/aasim0202/InsuRisk.git
cd InsuRisk
.\scripts\setup.ps1
```

Then edit `backend/.env` with your `TAVILY_API_KEY` and start the backend (below).

### Manual — Windows

```bash
git clone https://github.com/aasim0202/InsuRisk.git
cd InsuRisk/backend
pip install -r requirements.txt
copy .env.example .env        # then edit .env with your keys
uvicorn main:app --reload --port 8000
# open frontend/index.html in your browser
```

### Manual — Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull mistral

git clone https://github.com/aasim0202/InsuRisk.git
cd InsuRisk/backend
pip install -r requirements.txt
cp .env.example .env          # then: nano .env
uvicorn main:app --reload --port 8000
xdg-open ../frontend/index.html
```

---

## Environment Variables

```env
TAVILY_API_KEY=tvly-your-key-here
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral
AWS_ACCESS_KEY_ID=your-access-key-id
AWS_SECRET_ACCESS_KEY=your-secret-access-key
AWS_S3_BUCKET=insurisk-outputs
```

> **Never commit `.env`** — it is in `.gitignore`.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health check |
| `POST` | `/classify` | Run pipeline, return full result (blocking) |
| `POST` | `/classify/stream` | Same pipeline as Server-Sent Events (progress + live tokens) |
| `POST` | `/classify/batch` | Upload a CSV, classify every row |
| `GET` | `/history` | List past classifications (newest first) |
| `GET` | `/history/{filename}` | Fetch one saved classification |

```bash
curl -X POST http://localhost:8000/classify \
  -H "Content-Type: application/json" \
  -d '{"business_name": "Joe Auto Repair", "address": "4521 Oak St, Chicago IL"}'
```

---

## Running the Eval Harness

```bash
cd backend
python evaluate.py                      # uses model from .env
python evaluate.py --model llama3.2:3b  # compare a lighter model
```

Reports industry accuracy, risk accuracy, mean confidence, and mean latency against
`data/eval/eval_set.json`. The eval set is illustrative — edit it with your own labels.

---

## ML Concepts Demonstrated

| Concept | Implementation |
|---|---|
| **RAG grounding** | ChromaDB embeds Tavily results; top-5 chunks retrieved as LLM context; sources cited in output |
| **Top-k retrieval** | `n_results=5` in ChromaDB query |
| **Chain-of-thought** | Prompt instructs the model to reason step-by-step before emitting JSON |
| **LLM quantization** | Mistral runs as Q4_K_M GGUF — 4-bit weights, ~4.1GB footprint |
| **KV cache** | Ollama caches the prompt prefix's key/value tensors across the streamed generation |
| **Post-processing validation** | JSON extraction, field defaults, confidence clamping, NAICS cross-check |
| **Model evaluation** | `evaluate.py` measures accuracy/latency and enables model A/B comparison |
| **VRAM-aware selection** | Q4_K_M chosen for 8GB RAM; `llama3.2:3b` documented as the lighter fallback |

---

## Project Structure

```
InsuRisk/
├── .github/workflows/ci.yml  # CI: compile, validate, secret-guard
├── backend/
│   ├── main.py           # FastAPI app, CORS, all endpoints (stream/batch/history)
│   ├── pipeline.py       # Pipeline stages, streaming generator, metrics, S3
│   ├── naics.py          # NAICS lookup table + validation/reconciliation rules
│   ├── evaluate.py       # Eval harness
│   ├── requirements.txt
│   ├── .env.example
│   └── .env              # Your secrets (git-ignored)
├── frontend/
│   └── index.html        # Tabbed dark UI: Classify / Batch / History
├── scripts/
│   ├── setup.sh / setup.ps1            # One-shot setup
│   └── switch-model.sh / switch-model.ps1  # Swap the Ollama model
├── data/
│   ├── eval/eval_set.json    # Labeled eval cases
│   ├── sample_businesses.csv # Sample CSV for batch mode
│   └── outputs/              # Saved JSON results (git-ignored)
├── .gitignore
├── FEATURES.md           # Detailed feature guide
└── README.md
```

---

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and PR to `main`: it byte-compiles the
backend, validates the eval JSON, checks required files exist, and **fails the build
if a `.env` is ever committed** — so secrets can't slip into the repo.

---

## Built During

Personal project built alongside an internship at **NeuralMetrics** (insurtech, AI/ML on AWS) to explore the underlying ML engineering concepts — RAG pipelines, local LLM inference, quantization tradeoffs, post-processing validation, and model evaluation — that power commercial insurance risk classification systems.
