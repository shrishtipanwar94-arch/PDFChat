"""Run the hand-labelled question set against a running server.

    python eval/make_sample_pdf.py
    python eval/run_eval.py [--base-url http://localhost:8000]

Reports retrieval and answer accuracy separately:
  - Retrieval: did the top 5 chunks include the page that holds the answer?
  - Answer: was the answer correct, and did the model say "not in the document"
    for questions with no answer?
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
REFUSAL_MARKERS = ["not in the document", "not mentioned", "does not contain", "doesn't contain", "no information"]


def is_refusal(answer: str) -> bool:
    a = answer.lower()
    return any(m in a for m in REFUSAL_MARKERS)


def is_correct(answer: str, expect: list[list[str]]) -> bool:
    a = answer.lower()
    return all(any(alt.lower() in a for alt in group) for group in expect)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--questions", default=str(HERE / "questions.json"))
    parser.add_argument("--delay", type=float, default=0.0, help="seconds between questions (free-tier rate limits)")
    args = parser.parse_args()

    spec = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    pdf_path = HERE / spec["pdf"]
    if not pdf_path.exists():
        print(f"{pdf_path} not found. Run: python eval/make_sample_pdf.py", file=sys.stderr)
        return 1

    session = str(uuid.uuid4())
    headers = {"X-Chat-Session-Id": session}
    client = httpx.Client(base_url=args.base_url, headers=headers, timeout=180)

    with pdf_path.open("rb") as f:
        doc = client.post("/api/documents", files={"file": (pdf_path.name, f, "application/pdf")}).json()
    if doc.get("status") != "ready":
        print(f"Upload failed: {doc}", file=sys.stderr)
        return 1

    answerable = [q for q in spec["questions"] if q["page"] is not None]
    unanswerable = [q for q in spec["questions"] if q["page"] is None]
    hits = correct = refused = 0
    results = []

    try:
        for item in spec["questions"]:
            r = client.post("/api/chat", json={"documentId": doc["id"], "question": item["q"]})
            if r.status_code != 200:
                print(f"  ! {item['q']}: HTTP {r.status_code} {r.text[:200]}")
                results.append({**item, "error": r.text})
                continue
            res = r.json()
            pages = [s["page"] for s in res["sources"]]
            answer = res["answer"]
            if item["page"] is None:
                ok = is_refusal(answer)
                refused += ok
                hit = None
            else:
                hit = item["page"] in pages
                ok = is_correct(answer, item["expect"])
                hits += hit
                correct += ok
            mark = "✓" if ok else "✗"
            print(f"  {mark} [{res['provider']}] {item['q']}\n      → {answer[:160].replace(chr(10), ' ')}")
            results.append({**item, "answer": answer, "provider": res["provider"], "pages": pages, "retrieval_hit": hit, "ok": ok})
            if args.delay:
                time.sleep(args.delay)
    finally:
        client.delete(f"/api/documents/{doc['id']}")

    print()
    print("| Measure | Result |")
    print("| --- | --- |")
    print(f"| Retrieval hit rate (top 5) | {hits} / {len(answerable)} |")
    print(f"| Correct answers | {correct} / {len(answerable)} |")
    print(f"| Correctly refused (answer not in PDF) | {refused} / {len(unanswerable)} |")

    (HERE / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
