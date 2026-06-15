import os
import json
import re
import time
import requests
import chromadb
import boto3
from datetime import datetime
from tavily import TavilyClient
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from dotenv import load_dotenv

from naics import validate_naics, reconcile_risk

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "outputs")

# Reuse one embedding function instance — loading the model is expensive.
_EMBED_FN = DefaultEmbeddingFunction()


def _cfg(key, default=None):
    """Read config at call time so tools like evaluate.py can override via env."""
    return os.getenv(key, default)


def sanitize_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "_", name.lower()).strip("_")
    return (slug or "business")[:40]


# ──────────────────────────────────────────────────────────────────────────
# Pipeline stages (shared by the blocking and streaming entry points)
# ──────────────────────────────────────────────────────────────────────────

def _tavily_enrich(business_name: str, address: str):
    """Run 3 targeted searches. Returns (chunks, sources)."""
    tavily = TavilyClient(api_key=TAVILY_API_KEY)
    queries = [
        f"{business_name} {address} business risk insurance",
        f"{business_name} OSHA violations safety record incidents",
        f"{business_name} industry license type NAICS classification",
    ]

    chunks, sources, seen_urls = [], [], set()
    for query in queries:
        try:
            results = tavily.search(query=query, max_results=3)
            for r in results.get("results", []):
                content = (r.get("content") or "").strip()
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    sources.append({
                        "title": r.get("title", "Untitled source"),
                        "url": url,
                        "snippet": content[:280],
                        "query": query,
                    })
                for i in range(0, len(content), 500):
                    chunk = content[i:i + 500].strip()
                    if chunk:
                        chunks.append(chunk)
        except Exception as e:
            print(f"[Tavily] Error on query '{query}': {e}")

    if not chunks:
        chunks = [f"Business: {business_name} located at {address}. No additional public data retrieved."]
    return chunks, sources


def _embed_and_retrieve(business_name: str, address: str, chunks):
    """Embed chunks in an ephemeral ChromaDB collection and return top-5 context."""
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection(
        name=f"biz_{sanitize_name(business_name)}",
        embedding_function=_EMBED_FN,
    )
    collection.add(documents=chunks, ids=[f"chunk_{i}" for i in range(len(chunks))])

    n_results = min(5, len(chunks))
    q = collection.query(
        query_texts=[f"{business_name} {address} risk classification"],
        n_results=n_results,
    )
    docs = q["documents"][0] if q["documents"] else chunks[:5]
    return docs


def _build_prompt(business_name: str, address: str, context: str) -> str:
    return f"""You are a senior commercial insurance underwriter. Analyze the business below and classify its risk.

Business Name: {business_name}
Address: {address}

Research Context (retrieved from public sources):
{context}

Think step by step before answering:
Step 1 — Identify the industry: What type of business is this? What sector does it operate in?
Step 2 — Scan for risk signals: Are there OSHA violations, safety incidents, lawsuits, regulatory issues, or inherently hazardous activities?
Step 3 — Decide risk level: Based on industry norms and specific signals found, what is the risk level?

Respond ONLY with a valid JSON object — no markdown, no extra text:
{{
  "industry": "<industry name>",
  "naics_code": "<6-digit NAICS code>",
  "risk_level": "<LOW|MEDIUM|HIGH>",
  "confidence_score": <0.0 to 1.0>,
  "risk_flags": ["<flag1>", "<flag2>"],
  "chain_of_thought": "<your step-by-step reasoning>",
  "summary": "<2-3 sentence underwriter summary>"
}}"""


# ── Provider selection (smart switch: local Ollama → Ollama Cloud) ──

def _local_available(url: str, timeout: float = 2.0) -> bool:
    """Is a local Ollama server reachable? (fast — connection refused returns immediately)"""
    try:
        return requests.get(f"{url}/api/tags", timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def _provider_chain() -> list:
    """
    Ordered list of LLM providers to try (each entry = one URL + model).
      LLM_MODE=local  -> local models only
      LLM_MODE=cloud  -> cloud only (if a key is set)
      LLM_MODE=auto   -> prefer local if its server is up, else cloud; the other is a fallback

    The local tier tries the primary model (mistral) first, then a lighter
    fallback (llama3.2:3b) — so a RAM-constrained machine that only has the
    small model still works.
    """
    mode = (_cfg("LLM_MODE", "auto") or "auto").lower()
    local_url = _cfg("OLLAMA_URL", "http://localhost:11434")

    local_models = []
    for m in (_cfg("OLLAMA_MODEL", "mistral"), _cfg("OLLAMA_FALLBACK_MODEL", "llama3.2:3b")):
        if m and m not in local_models:
            local_models.append(m)
    locals_ = [{"name": "local", "url": local_url, "model": m, "api_key": None} for m in local_models]

    cloud = {
        "name": "cloud",
        "url": _cfg("OLLAMA_CLOUD_URL", "https://ollama.com"),
        "model": _cfg("OLLAMA_CLOUD_MODEL", "gpt-oss:120b"),
        "api_key": _cfg("OLLAMA_API_KEY"),
    }
    has_cloud = bool(cloud["api_key"])

    if mode == "local":
        return locals_
    if mode == "cloud":
        return [cloud] if has_cloud else locals_

    # auto
    if _local_available(local_url):
        return locals_ + ([cloud] if has_cloud else [])
    return ([cloud] if has_cloud else []) + locals_


def resolve_active_provider() -> dict:
    """The provider that would currently be used (first in the chain). Used by /health."""
    return _provider_chain()[0]


def _headers(provider: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    return headers


def _chat_payload(prompt: str, stream: bool, provider: dict) -> dict:
    # /api/chat works for both local Ollama and Ollama Cloud.
    return {
        "model": provider["model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": stream,
        "options": {"temperature": 0.2, "top_k": 40, "top_p": 0.9},
    }


def _call_ollama(prompt: str):
    """Try each provider in order; return (content, provider). Raises if all fail."""
    errors = []
    for p in _provider_chain():
        try:
            resp = requests.post(
                f"{p['url']}/api/chat", json=_chat_payload(prompt, False, p),
                headers=_headers(p), timeout=240,
            )
            resp.raise_for_status()
            return (resp.json().get("message") or {}).get("content", ""), p
        except requests.RequestException as e:
            errors.append(f"{p['name']} ({p['model']}): {e}")
    raise RuntimeError("All LLM providers failed -> " + " | ".join(errors))


def _open_stream(prompt: str):
    """Open a streaming chat connection, trying providers in order. Returns (response, provider)."""
    errors = []
    for p in _provider_chain():
        try:
            resp = requests.post(
                f"{p['url']}/api/chat", json=_chat_payload(prompt, True, p),
                headers=_headers(p), stream=True, timeout=240,
            )
            resp.raise_for_status()
            return resp, p
        except requests.RequestException as e:
            errors.append(f"{p['name']} ({p['model']}): {e}")
    raise RuntimeError("All LLM providers failed -> " + " | ".join(errors))


def _iter_stream(resp):
    """Yield response tokens as they arrive."""
    for line in resp.iter_lines():
        if not line:
            continue
        try:
            obj = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            continue
        token = (obj.get("message") or {}).get("content", "")
        if token:
            yield token
        if obj.get("done"):
            break


def _postprocess(raw: str, business_name: str, address: str) -> dict:
    """Extract JSON, validate fields, clamp confidence, run NAICS validation."""
    defaults = {
        "industry": "UNKNOWN",
        "naics_code": "000000",
        "risk_level": "UNKNOWN",
        "confidence_score": 0.5,
        "risk_flags": [],
        "chain_of_thought": "",
        "summary": "",
    }

    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        parsed = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        parsed = {}

    result = {field: parsed.get(field, default) for field, default in defaults.items()}

    if result["risk_level"] not in ("LOW", "MEDIUM", "HIGH"):
        result["risk_level"] = "UNKNOWN"

    try:
        result["confidence_score"] = max(0.0, min(1.0, float(result["confidence_score"])))
    except (TypeError, ValueError):
        result["confidence_score"] = 0.5

    if not isinstance(result["risk_flags"], list):
        result["risk_flags"] = [str(result["risk_flags"])] if result["risk_flags"] else []

    # ── NAICS validation layer ──
    naics_validation = validate_naics(result["naics_code"], result["industry"])
    reconciliation = reconcile_risk(result["risk_level"], naics_validation.get("expected_risk"))
    naics_validation["risk_reconciliation"] = reconciliation
    result["naics_validation"] = naics_validation

    return result


def _save_output(business_name: str, address: str, result: dict) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{sanitize_name(business_name)}_{timestamp}.json"
    output = {
        "business_name": business_name,
        "address": address,
        "timestamp": timestamp,
        "classification": result,
    }

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    with open(os.path.join(OUTPUTS_DIR, filename), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    # Best-effort S3 upload
    bucket = _cfg("AWS_S3_BUCKET", "insurisk-outputs")
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=_cfg("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=_cfg("AWS_SECRET_ACCESS_KEY"),
            region_name="us-east-1",
        )
        s3.put_object(
            Bucket=bucket,
            Key=f"outputs/{filename}",
            Body=json.dumps(output, indent=2),
            ContentType="application/json",
        )
        result["s3_key"] = f"outputs/{filename}"
    except Exception as e:
        print(f"[S3] Upload skipped: {e}")

    result["output_file"] = filename
    return filename


# ──────────────────────────────────────────────────────────────────────────
# Entry points
# ──────────────────────────────────────────────────────────────────────────

def run_pipeline(business_name: str, address: str) -> dict:
    """Blocking pipeline — used by /classify, batch mode, and the eval harness."""
    t0 = time.perf_counter()

    t = time.perf_counter()
    chunks, sources = _tavily_enrich(business_name, address)
    tavily_ms = round((time.perf_counter() - t) * 1000)

    t = time.perf_counter()
    context_docs = _embed_and_retrieve(business_name, address, chunks)
    rag_ms = round((time.perf_counter() - t) * 1000)

    prompt = _build_prompt(business_name, address, "\n\n---\n\n".join(context_docs))

    t = time.perf_counter()
    raw, provider = _call_ollama(prompt)
    llm_ms = round((time.perf_counter() - t) * 1000)

    result = _postprocess(raw, business_name, address)
    result["sources"] = sources
    result["metrics"] = {
        "tavily_ms": tavily_ms,
        "rag_ms": rag_ms,
        "llm_ms": llm_ms,
        "total_ms": round((time.perf_counter() - t0) * 1000),
        "chunks_indexed": len(chunks),
        "context_chunks": len(context_docs),
        "model": provider["model"],
        "provider": provider["name"],
    }

    _save_output(business_name, address, result)
    return result


def _ev(event_type, **kw):
    kw["type"] = event_type
    return kw


def stream_pipeline(business_name: str, address: str):
    """Generator yielding progress events for SSE. Streams LLM tokens live."""
    try:
        t0 = time.perf_counter()

        yield _ev("stage", stage="tavily", status="start", label="Searching public web sources")
        t = time.perf_counter()
        chunks, sources = _tavily_enrich(business_name, address)
        tavily_ms = round((time.perf_counter() - t) * 1000)
        yield _ev("stage", stage="tavily", status="done", ms=tavily_ms, detail=f"{len(sources)} sources, {len(chunks)} chunks")
        yield _ev("sources", sources=sources)

        yield _ev("stage", stage="rag", status="start", label="Embedding & retrieving top-5 context (RAG)")
        t = time.perf_counter()
        context_docs = _embed_and_retrieve(business_name, address, chunks)
        rag_ms = round((time.perf_counter() - t) * 1000)
        yield _ev("stage", stage="rag", status="done", ms=rag_ms, detail=f"top-{len(context_docs)} chunks")

        prompt = _build_prompt(business_name, address, "\n\n---\n\n".join(context_docs))

        yield _ev("stage", stage="llm", status="start", label="Reasoning with LLM (selecting provider)")
        t = time.perf_counter()
        resp, provider = _open_stream(prompt)
        yield _ev("stage", stage="llm", status="start", label=f"Reasoning with {provider['model']} ({provider['name']})")
        raw = ""
        for token in _iter_stream(resp):
            raw += token
            yield _ev("token", text=token)
        llm_ms = round((time.perf_counter() - t) * 1000)
        yield _ev("stage", stage="llm", status="done", ms=llm_ms, detail=f"{provider['name']} · {provider['model']}")

        yield _ev("stage", stage="post", status="start", label="Validating output & NAICS code")
        result = _postprocess(raw, business_name, address)
        result["sources"] = sources
        result["metrics"] = {
            "tavily_ms": tavily_ms,
            "rag_ms": rag_ms,
            "llm_ms": llm_ms,
            "total_ms": round((time.perf_counter() - t0) * 1000),
            "chunks_indexed": len(chunks),
            "context_chunks": len(context_docs),
            "model": provider["model"],
            "provider": provider["name"],
        }
        _save_output(business_name, address, result)
        yield _ev("stage", stage="post", status="done")
        yield _ev("result", data=result)
    except Exception as e:
        yield _ev("error", detail=str(e))
