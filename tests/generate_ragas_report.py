"""Gộp lần chạy Ragas mới nhất thành một báo cáo JSON dễ chia sẻ.

Chạy sau hai benchmark:
    python -m tests.generate_ragas_report
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "ragas_results" / "experiments"
REPORTS = ROOT / "ragas_reports"


def _latest(prefix: str) -> Path:
    files = sorted(RESULTS.glob(f"{prefix}_*.jsonl"), key=lambda path: path.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"Chưa có kết quả cho {prefix}.")
    return files[-1]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _summary(rows: list[dict[str, Any]], score_fields: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total": len(rows),
        "passed": sum(bool(row.get("passed")) for row in rows),
        "failed": sum(not bool(row.get("passed")) for row in rows),
    }
    for field in score_fields:
        values = [row[field] for row in rows if isinstance(row.get(field), (int, float))]
        if values:
            summary[f"mean_{field}"] = round(sum(values) / len(values), 4)
    return summary


def main() -> None:
    retrieval_source = _latest("tour_retrieval")
    answer_source = _latest("tour_answer")
    retrieval = _read_jsonl(retrieval_source)
    answer = _read_jsonl(answer_source)
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "scope": "Đánh giá RAG chatbot tour: retrieval và câu trả lời Gemini được Ragas chấm.",
        "suites": {
            "retrieval": {
                "source": str(retrieval_source),
                "summary": _summary(retrieval, ["retrieval_precision", "retrieval_recall"]),
                "scenarios_and_results": retrieval,
            },
            "answer_quality": {
                "source": str(answer_source),
                "summary": _summary(answer, []),
                "scenarios_and_results": answer,
            },
        },
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    destination = REPORTS / f"ragas_evaluation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
