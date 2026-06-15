"""
Eval harness — measures classifier quality against a labeled set.

Runs the full pipeline over data/eval/eval_set.json and reports:
  - Industry match accuracy (keyword-based)
  - Risk-level exact accuracy
  - Mean confidence and mean per-stage latency

Usage:
    python evaluate.py                 # uses OLLAMA_MODEL from .env
    python evaluate.py --model llama3.2:3b
    python evaluate.py --model mistral

NOTE: requires Ollama running and a TAVILY_API_KEY in .env.
The eval set is illustrative — edit data/eval/eval_set.json with your own labels.
"""
import os
import sys
import json
import argparse

EVAL_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "eval", "eval_set.json")


def industry_matches(predicted: str, keywords) -> bool:
    p = (predicted or "").lower()
    return any(kw.lower() in p for kw in keywords)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="Override OLLAMA_MODEL for this run (e.g. mistral, llama3.2:3b)")
    args = parser.parse_args()

    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model

    # Import after env override so pipeline reads the right model
    from pipeline import run_pipeline

    model = os.getenv("OLLAMA_MODEL", "mistral")

    with open(EVAL_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print(f"\n{'='*72}")
    print(f"  InsuRisk Eval  |  model={model}  |  {len(cases)} cases")
    print(f"{'='*72}\n")

    industry_hits = 0
    risk_hits = 0
    confidences = []
    latencies = []

    for i, case in enumerate(cases, 1):
        name = case["business_name"]
        addr = case["address"]
        exp_risk = case["expected_risk"]
        exp_kw = case["expected_industry_keywords"]

        try:
            r = run_pipeline(name, addr)
        except Exception as e:
            print(f"[{i:02d}] {name:<32} ERROR: {e}")
            continue

        ind_ok = industry_matches(r["industry"], exp_kw)
        risk_ok = r["risk_level"] == exp_risk
        industry_hits += ind_ok
        risk_hits += risk_ok
        confidences.append(r["confidence_score"])
        latencies.append(r.get("metrics", {}).get("total_ms", 0))

        ind_mark = "OK " if ind_ok else "MISS"
        risk_mark = "OK " if risk_ok else "MISS"
        print(f"[{i:02d}] {name:<32} industry[{ind_mark}] {r['industry']:<24} "
              f"risk[{risk_mark}] {r['risk_level']:<6} (exp {exp_risk})  conf={r['confidence_score']:.2f}")

    n = len(confidences) or 1
    print(f"\n{'-'*72}")
    print(f"  Industry accuracy : {industry_hits}/{len(cases)}  ({100*industry_hits/len(cases):.0f}%)")
    print(f"  Risk accuracy     : {risk_hits}/{len(cases)}  ({100*risk_hits/len(cases):.0f}%)")
    print(f"  Mean confidence   : {sum(confidences)/n:.2f}")
    print(f"  Mean latency      : {sum(latencies)/n/1000:.1f}s")
    print(f"{'-'*72}\n")


if __name__ == "__main__":
    main()
