# InsuRisk — Feature Guide

A walkthrough of every feature, what it does, why it matters for underwriting, and where it lives in the code.

---

## The Pipeline (end to end)

When you classify a business, the request flows through five stages:

```
business name + address
        │
   1. Tavily          3 targeted web searches (general risk · OSHA · industry/license)
        │             → raw text split into ~500-char chunks + a list of cited sources
        │
   2. ChromaDB        chunks embedded with DefaultEmbeddingFunction, stored in an
        │             ephemeral per-business collection
        │
   3. RAG retrieval   top-5 most relevant chunks pulled back as grounded context
        │
   4. Ollama (LLM)    chain-of-thought prompt → identify industry → scan risk signals
        │             → decide risk level → emit structured JSON (streamed token by token)
        │
   5. Post-process    extract JSON · clamp confidence · validate fields · NAICS check
        │             → save to data/outputs/*.json + best-effort S3 upload
        ▼
   structured result  industry · NAICS · risk level · confidence · flags · CoT · sources · metrics
```

Code: `backend/pipeline.py` (`run_pipeline` for blocking, `stream_pipeline` for streaming).

---

## 1. Live Streaming Classification

**What:** Instead of a spinner that hangs for 10–60s, the UI shows each stage completing in real time, and the LLM's reasoning fills in token by token as the model generates it.

**How:** The backend exposes `POST /classify/stream` as **Server-Sent Events**. `stream_pipeline()` is a Python generator that `yield`s typed events:

| Event | Meaning |
|---|---|
| `stage` (`start`/`done`) | a pipeline stage began or finished (with elapsed ms) |
| `sources` | the list of Tavily sources, sent as soon as enrichment finishes |
| `token` | one chunk of the LLM's output as it streams |
| `result` | the final validated classification object |
| `error` | something failed mid-pipeline |

The frontend reads the response body with a `ReadableStream` reader, splits on `\n\n`, and updates the stage checklist + live-reasoning panel as events arrive.

**Why it matters:** Long local-LLM inference feels broken without feedback. Streaming makes latency legible and shows the chain-of-thought happening live.

Code: `backend/main.py` → `classify_stream`; `backend/pipeline.py` → `stream_pipeline`, `_stream_ollama`; frontend → `classify()`.

---

## 2. Evidence & Source Citations

**What:** Every classification lists the exact web sources it was grounded in — title, URL, and the snippet that was indexed.

**How:** During enrichment, `_tavily_enrich()` collects each result's title/URL/snippet (de-duplicated by URL) alongside the text chunks. Those sources travel through to the final result and render in a collapsible "Evidence & Sources" panel.

**Why it matters:** This is the heart of **RAG grounding** — it proves the output is traceable to retrieved data, not hallucinated. In an underwriting context, an adjuster can click through to verify any claim.

Code: `backend/pipeline.py` → `_tavily_enrich`; frontend → `renderSources()`.

---

## 3. NAICS Validation Layer

**What:** The LLM proposes a 6-digit NAICS code and an industry. We don't trust it blindly — we cross-check it.

**How:** `backend/naics.py` holds a reference table of ~40 common commercial NAICS codes, each with an official description, matching keywords, and a rule-based `base_risk` tier. `validate_naics()` returns:

- `valid_format` — is it a 6-digit code?
- `known` — is the code in the reference table?
- `industry_match` — does the code's official class align with the predicted industry (keyword overlap)?
- `status` — `verified` / `mismatch` / `unverified`

`reconcile_risk()` then compares the **LLM's risk level** against the **rule-based baseline** for that industry class and notes whether they agree (and which direction they differ).

The UI shows a badge next to the NAICS code: **Verified** (green), **Industry mismatch** (amber), or **Unverified code** (amber), plus the official class name and the reconciliation note.

**Why it matters:** This is textbook **post-processing validation** — a deterministic rule layer that catches model errors and surfaces disagreement instead of silently trusting the LLM.

Code: `backend/naics.py`; applied in `backend/pipeline.py` → `_postprocess`; frontend → `renderNaicsValidation()`.

---

## 4. Pipeline Metrics

**What:** Each result reports per-stage latency and run details.

**How:** `run_pipeline`/`stream_pipeline` time each stage with `time.perf_counter()` and attach a `metrics` block: `tavily_ms`, `rag_ms`, `llm_ms`, `total_ms`, `chunks_indexed`, `context_chunks`, and the `model` used. The UI renders this as a compact footer under the result.

**Why it matters:** Basic observability. It makes the LLM stage's dominance of total latency obvious, and lets you compare models quantitatively (see the eval harness).

Code: `backend/pipeline.py`; frontend → `renderMetrics()`.

---

## 5. Batch Mode

**What:** Upload a CSV of businesses and classify them all in one run.

**How:** `POST /classify/batch` accepts a multipart CSV upload. It maps the `business_name`/`address` columns case-insensitively (also accepts `name`/`business` and `addr`/`location`), runs the full pipeline per row, and returns an array of results (or a per-row error). The UI renders a results table and a "Download JSON" button. A sample file ships at `data/sample_businesses.csv`.

**Why it matters:** Underwriters work over portfolios, not single lookups. This mirrors a realistic batch-enrichment workflow.

Code: `backend/main.py` → `classify_batch`; frontend → `runBatch()`, `renderBatchTable()`.

---

## 6. History

**What:** Browse and re-open every past classification.

**How:** Every run is saved to `data/outputs/<slug>_<timestamp>.json`. `GET /history` lists them (newest first) with summary fields; `GET /history/{filename}` returns a full saved result (filename sanitized to its basename to prevent path traversal). Clicking an item in the History tab re-renders the full result card.

**Why it matters:** Persistence + auditability. Past assessments stay reviewable, which matters for any decision-support tool.

Code: `backend/main.py` → `history`, `history_item`; frontend → `loadHistory()`, `openHistory()`.

---

## 7. Eval Harness

**What:** A script that measures classifier quality against a labeled set.

**How:** `backend/evaluate.py` runs the pipeline over `data/eval/eval_set.json` (12 labeled businesses) and reports **industry accuracy**, **risk-level accuracy**, **mean confidence**, and **mean latency**. The `--model` flag overrides `OLLAMA_MODEL` for the run, so you can A/B compare:

```bash
python evaluate.py --model mistral
python evaluate.py --model llama3.2:3b
```

**Why it matters:** Signals engineering maturity — you don't just call an LLM, you *measure* it. The eval set is illustrative; edit it with your own ground-truth labels.

Code: `backend/evaluate.py`; data in `data/eval/eval_set.json`.

---

## 8. Model Switching

The model is read from `OLLAMA_MODEL` in `.env` at call time, so switching needs **no code change**.

**Quick way — helper scripts:**

```bash
# Linux / macOS
./scripts/switch-model.sh llama3.2:3b

# Windows
.\scripts\switch-model.ps1 -Model llama3.2:3b
```

They pull the model via Ollama and rewrite the `OLLAMA_MODEL` line in `.env`. Restart the backend to apply.

**Manual way:** `ollama pull <model>`, edit `OLLAMA_MODEL=<model>` in `.env`, restart `uvicorn`.

| Model | RAM | Notes |
|---|---|---|
| `mistral` | ~4.1 GB | Default; best quality on 8GB |
| `llama3.2:3b` | ~2.0 GB | Lighter, strong JSON adherence |
| `phi3:mini` | ~2.3 GB | Strong step-by-step reasoning |
| `gemma2:2b` | ~1.6 GB | Lightest, very constrained machines |

### Smart switch: local Ollama → Ollama Cloud

The inference layer is **provider-agnostic** and picks its provider automatically.
`_provider_chain()` builds an ordered list based on `LLM_MODE`:

- **`auto`** (default) — `_local_available()` probes `GET {local}/api/tags` (a ~2s check;
  connection-refused returns instantly). If local is up → `[local(mistral), local(llama3.2:3b), cloud]`.
  If local is down → `[cloud, local(mistral), local(llama3.2:3b)]`. The local tier tries the
  primary model then a lighter fallback, so a RAM-constrained machine that only has the small
  model still works; a machine where local Ollama is blocked (e.g. **CrowdStrike Falcon**)
  transparently uses the cloud.
- **`local`** — local only.
- **`cloud`** — Ollama Cloud only (needs `OLLAMA_API_KEY`).

Both `_call_ollama` (blocking) and `_open_stream` (streaming) then **try each provider in
order**, falling through to the next on any request error — so a momentary local failure
still completes via cloud. The chosen provider/model is reported in the result `metrics`
(`"provider": "local"|"cloud"`) and shown in the UI metrics line, and `GET /health` returns
`active_provider` / `active_model`.

Why this beats running cloud models through the terminal: `ollama run <model>-cloud` still
launches the local Ollama binary (blocked by Falcon). The backend's direct HTTPS call to
`https://ollama.com/api/chat` never starts a local process, so it sidesteps the block.

Config (`.env`):

```env
LLM_MODE=auto
OLLAMA_URL=http://localhost:11434      # local, tried first
OLLAMA_MODEL=mistral                   # primary local model
OLLAMA_FALLBACK_MODEL=llama3.2:3b      # lighter local model, tried next
OLLAMA_CLOUD_URL=https://ollama.com    # cloud fallback
OLLAMA_CLOUD_MODEL=gpt-oss:120b
OLLAMA_API_KEY=...                     # enables the cloud fallback
```

Code: `backend/pipeline.py` → `_local_available`, `_provider_chain`, `resolve_active_provider`,
`_call_ollama`, `_open_stream`, `_iter_stream`.

---

## 9. Continuous Integration

`.github/workflows/ci.yml` runs on every push/PR to `main`:

- byte-compiles all backend files (syntax check)
- validates `eval_set.json` parses
- confirms required files (`frontend/index.html`, `requirements.txt`, `.env.example`) exist
- **guards against a committed `.env`** — fails the build if secrets are ever tracked

---

## ML Concepts → Where They Live

| Concept | In this project |
|---|---|
| RAG grounding | ChromaDB retrieval + cited sources (`_embed_and_retrieve`, `_tavily_enrich`) |
| Top-k retrieval | `n_results=5` ChromaDB query |
| Chain-of-thought | step-by-step prompt in `_build_prompt` |
| Quantization | Mistral Q4_K_M; lighter Q4 models documented |
| KV cache | Ollama caches prompt-prefix K/V across the streamed generation |
| Post-processing validation | `_postprocess` + `naics.py` rule layer |
| Model evaluation | `evaluate.py` accuracy/latency, model A/B |
| VRAM-aware selection | model table sized to 8GB RAM |
