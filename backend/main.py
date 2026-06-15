import os
import io
import csv
import json
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from pipeline import run_pipeline, stream_pipeline, OUTPUTS_DIR

load_dotenv()

app = FastAPI(
    title="InsuRisk API",
    version="2.0.0",
    description="Business Risk Classifier for Commercial Insurance Underwriting",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ClassifyRequest(BaseModel):
    business_name: str
    address: str


def _validate(req: ClassifyRequest):
    if not req.business_name.strip():
        raise HTTPException(status_code=400, detail="business_name cannot be empty")
    if not req.address.strip():
        raise HTTPException(status_code=400, detail="address cannot be empty")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
        "model": os.getenv("OLLAMA_MODEL", "mistral"),
        "mode": "cloud" if os.getenv("OLLAMA_API_KEY") else "local",
        "s3_bucket": os.getenv("AWS_S3_BUCKET", "insurisk-outputs"),
    }


@app.post("/classify")
def classify(request: ClassifyRequest):
    _validate(request)
    try:
        return run_pipeline(request.business_name.strip(), request.address.strip())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/classify/stream")
def classify_stream(request: ClassifyRequest):
    """Server-Sent Events: streams stage progress + live LLM tokens + final result."""
    _validate(request)

    def event_source():
        for event in stream_pipeline(request.business_name.strip(), request.address.strip()):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/classify/batch")
async def classify_batch(file: UploadFile = File(...)):
    """Accept a CSV with business_name + address columns; classify each row."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV is empty or has no header row.")

    # Map columns case-insensitively
    cols = {c.lower().strip(): c for c in reader.fieldnames}
    name_col = cols.get("business_name") or cols.get("name") or cols.get("business")
    addr_col = cols.get("address") or cols.get("addr") or cols.get("location")
    if not name_col or not addr_col:
        raise HTTPException(
            status_code=400,
            detail="CSV must contain 'business_name' and 'address' columns.",
        )

    results = []
    for i, row in enumerate(reader):
        name = (row.get(name_col) or "").strip()
        address = (row.get(addr_col) or "").strip()
        if not name or not address:
            continue
        try:
            classification = run_pipeline(name, address)
            results.append({"business_name": name, "address": address, "classification": classification})
        except Exception as e:
            results.append({"business_name": name, "address": address, "error": str(e)})

    return {"count": len(results), "results": results}


@app.get("/history")
def history(limit: int = 50):
    """List past classifications saved locally, newest first."""
    if not os.path.isdir(OUTPUTS_DIR):
        return {"count": 0, "items": []}

    items = []
    for fname in os.listdir(OUTPUTS_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(OUTPUTS_DIR, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            c = data.get("classification", {})
            items.append({
                "filename": fname,
                "business_name": data.get("business_name", "Unknown"),
                "address": data.get("address", ""),
                "timestamp": data.get("timestamp", ""),
                "industry": c.get("industry", "UNKNOWN"),
                "risk_level": c.get("risk_level", "UNKNOWN"),
                "confidence_score": c.get("confidence_score", 0),
            })
        except (json.JSONDecodeError, OSError):
            continue

    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"count": len(items), "items": items[:limit]}


@app.get("/history/{filename}")
def history_item(filename: str):
    """Fetch a single saved classification. Filename is sanitized to its basename."""
    safe = os.path.basename(filename)
    if not safe.endswith(".json"):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    path = os.path.join(OUTPUTS_DIR, safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Classification not found.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
