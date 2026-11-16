"""Đánh giá Ragas cho câu trả lời Gemini có dùng kết quả RAG.

Chạy: python -m tests.ragas_answer_eval
Lưu ý: script gọi Gemini để sinh câu trả lời và làm giám khảo, nên có dùng quota.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ragas import Dataset, experiment
from ragas.metrics import discrete_metric
from ragas.metrics.result import MetricResult

import llm_gemini
from rag import tim_tour_lien_quan


ROOT = Path(__file__).resolve().parent
DEFAULT_CASES = ROOT / "ragas_answer_cases.json"
DEFAULT_OUTPUT = ROOT / "ragas_results"

JUDGE_PROMPT = """Bạn là giám khảo QA nghiêm khắc cho chatbot tư vấn tour.
Chỉ dùng câu hỏi, tiêu chí, thẻ tour và câu trả lời bên dưới để chấm.

Chấm PASS khi câu trả lời đáp ứng tiêu chí, không mâu thuẫn thẻ tour, không bịa tour/giá/ngày khởi hành; nếu không có thẻ tour thì không được bịa tour.
Chấm FAIL khi thiếu yêu cầu chính, giới thiệu tour sai điều kiện, hoặc bịa thông tin quan trọng.

Chỉ trả về JSON hợp lệ có đúng dạng:
{"verdict":"pass" hoặc "fail", "reason":"lý do ngắn bằng tiếng Việt"}
"""


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    return json.loads(match.group(0)) if match else {}


@discrete_metric(name="grounded_and_helpful", allowed_values=["pass", "fail"])
def grounded_and_helpful(
    question: str, rubric: str, answer: str, retrieved: list[dict[str, Any]]
) -> MetricResult:
    """Ragas custom metric: Gemini chấm tính đúng đắn và bám dữ liệu."""
    payload = json.dumps(
        {"cau_hoi": question, "tieu_chi": rubric, "the_tour": retrieved, "cau_tra_loi": answer},
        ensure_ascii=False,
    )
    try:
        response = llm_gemini.client.chat.completions.create(
            model=llm_gemini.GEMINI_MODEL,
            max_tokens=400,
            timeout=30,
            reasoning_effort="low",
            messages=[
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": payload},
            ],
        )
        verdict = _extract_json(response.choices[0].message.content or "")
        value = verdict.get("verdict")
        if value not in {"pass", "fail"}:
            return MetricResult("fail", "Giám khảo không trả về verdict hợp lệ.")
        return MetricResult(value, str(verdict.get("reason") or "Không có lý do."))
    except Exception as exc:  # Không biến lỗi dịch vụ thành một kết quả tốt.
        return MetricResult("fail", f"Không gọi được giám khảo: {type(exc).__name__}.")


def _load_cases(path: Path) -> list[dict[str, str]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Tệp ca kiểm thử phải là một mảng JSON không rỗng.")
    for case in cases:
        if not {"id", "question", "rubric"} <= case.keys():
            raise ValueError(f"Ca kiểm thử thiếu id, question hoặc rubric: {case}")
    return cases


@experiment()
def evaluate_case(case: dict[str, str]) -> dict[str, Any]:
    tours = tim_tour_lien_quan(case["question"])
    answer = llm_gemini.hoi_gemini(case["question"], tours, [])
    judgement = grounded_and_helpful(
        question=case["question"], rubric=case["rubric"], answer=answer, retrieved=tours
    )
    return {
        "id": case["id"],
        "question": case["question"],
        "rubric": case["rubric"],
        "answer": answer,
        "retrieved_count": len(tours),
        "retrieved": [
            {key: tour.get(key) for key in ("ten", "diem_den", "gia", "so_ngay", "ngay_khoi_hanh")}
            for tour in tours
        ],
        "grounded_and_helpful": judgement.value,
        "judge_reason": judgement.reason,
        "passed": judgement.value == "pass",
    }


async def _run(cases: list[dict[str, str]], output: Path) -> tuple[Path, dict[str, Any]]:
    dataset = Dataset(name="tour_answer_cases", backend="local/jsonl", root_dir=str(output), data=cases)
    dataset.save()
    name = "tour_answer_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    results = await evaluate_case.arun(dataset, name=name)
    rows = list(results)
    summary = {
        "run": name,
        "total": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "failed": sum(not row["passed"] for row in rows),
    }
    return output / "experiments" / f"{name}.jsonl", summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Đánh giá câu trả lời RAG bằng Ragas và Gemini.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    cases = _load_cases(args.cases)
    args.output.mkdir(parents=True, exist_ok=True)
    result_path, summary = asyncio.run(_run(cases, args.output))
    # Giữ stdout ASCII để chạy được cả PowerShell Windows mặc định cp1252.
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    print(f"Details: {result_path}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
