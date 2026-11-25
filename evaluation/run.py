"""Deterministic retrieval smoke evaluation. Never calls Gemini."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from app.config import ROOT
from app.ingest import extract
from app.store import Store


def main():
    cases = json.loads((ROOT / "evaluation/cases.json").read_text(encoding="utf-8"))
    # Isolated corpus: uploaded/private documents never enter the evaluation.
    with tempfile.TemporaryDirectory(prefix="docuguia-eval-") as directory:
        store = Store(Path(directory) / "eval.sqlite3")
        manifest = json.loads((ROOT / "demo/manifest.json").read_text(encoding="utf-8"))
        for doc in manifest:
            raw = (ROOT / "demo" / doc["file"]).read_bytes()
            chunks, warnings = extract(doc["file"], raw)
            store.add(doc["file"], raw, doc, chunks, warnings)
        rows = []
        for case in cases:
            if not any(key in case for key in ("expected_file", "expect_empty", "forbidden_file")):
                rows.append({"id": case["id"], "passed": None, "status": "pending_live_evaluation"})
                continue
            sources = store.retrieve(case["question"], case["block"], case["status"])
            success = True
            if case.get("expected_file"):
                success &= any(s["filename"] == case["expected_file"] and case["expected_text"] in s["text"] for s in sources)
            if case.get("expect_empty"):
                success &= not sources
            if case.get("forbidden_file"):
                success &= all(s["filename"] != case["forbidden_file"] for s in sources)
            rows.append({"id": case["id"], "passed": bool(success), "retrieved_files": [s["filename"] for s in sources]})
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "kind": "synthetic_retrieval_smoke",
              "api_calls": 0, "passed": sum(r["passed"] is True for r in rows),
              "total": sum(r["passed"] is not None for r in rows),
              "pending_live": sum(r["passed"] is None for r in rows), "cases": rows,
              "limitations": "Development examples, not a held-out benchmark; does not measure Gemini answer correctness or semantic citation support."}
    path = ROOT / "evaluation/baseline.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "total": report["total"], "pending_live": report["pending_live"], "api_calls": 0}))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
