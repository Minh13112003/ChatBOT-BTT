"""Benchmark Ragas cho lớp truy xuất tour.

Không gọi Gemini: bài đánh giá này kiểm tra trực tiếp các tour mà RAG trả về
với các điều kiện có thể xác minh được (điểm đến, giá, loại hình, số ngày).
Chạy bằng: python -m tests.ragas_retrieval_eval
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ragas import Dataset, experiment
from ragas.metrics import numeric_metric

from rag import tim_tour_lien_quan


ROOT = Path(__file__).resolve().parent
DEFAULT_CASES = ROOT / "ragas_cases.json"
DEFAULT_OUTPUT = ROOT / "ragas_results"


def _is_match(tour: dict[str, Any], expect: dict[str, Any]) -> bool:
    """True khi một thẻ tour thỏa tất cả điều kiện vàng của ca kiểm thử."""
    checks = {
        "destination": lambda value: tour.get("diem_den") == value,
        "khong_phai_diem_den": lambda value: tour.get("diem_den") != value,
        "loai_hinh": lambda value: tour.get("loai_hinh") == value,
        "so_ngay": lambda value: tour.get("so_ngay") == value,
        "gia_toi_da": lambda value: tour.get("gia", float("inf")) <= value,
        "gia_toi_thieu": lambda value: tour.get("gia", float("-inf")) >= value,
    }
    return all(checks[key](value) for key, value in expect.items() if key in checks)


@numeric_metric(name="retrieval_precision", allowed_values=(0.0, 1.0))
def retrieval_precision(retrieved: list[dict[str, Any]], expect: dict[str, Any]) -> float:
    """Tỷ lệ thẻ trả về thỏa điều kiện vàng; ca cần rỗng chỉ đúng khi rỗng."""
    if expect.get("empty"):
        return 1.0 if not retrieved else 0.0
    if not retrieved:
        return 0.0
    return sum(_is_match(tour, expect) for tour in retrieved) / len(retrieved)


@numeric_metric(name="retrieval_recall", allowed_values=(0.0, 1.0))
def retrieval_recall(retrieved: list[dict[str, Any]], expect: dict[str, Any]) -> float:
    """Có ít nhất một thẻ đúng khi ca yêu cầu kết quả; ca cần rỗng chỉ đúng khi rỗng."""
    if expect.get("empty"):
        return 1.0 if not retrieved else 0.0
    return 1.0 if any(_is_match(tour, expect) for tour in retrieved) else 0.0


def _load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Tệp ca kiểm thử phải là một mảng JSON không rỗng.")
    for case in cases:
        if not {"id", "question", "expect"} <= case.keys():
            raise ValueError(f"Ca kiểm thử thiếu id, question hoặc expect: {case}")
    return cases


@experiment()
async def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    retrieved = tim_tour_lien_quan(case["question"])
    expect = case["expect"]
    # Gọi trực tiếp metric để tránh lồng event loop trên Python 3.14. Hai hàm
    # vẫn là Ragas NumericMetric (decorator @numeric_metric) và được Ragas
    # quản lý cùng dataset/experiment bên dưới.
    precision = retrieval_precision(retrieved=retrieved, expect=expect)
    recall = retrieval_recall(retrieved=retrieved, expect=expect)
    passed = precision == 1.0 and recall == 1.0
    return {
        "id": case["id"],
        "question": case["question"],
        "expect": expect,
        "retrieved_count": len(retrieved),
        "retrieved": [
            {
                "ten": tour.get("ten"),
                "diem_den": tour.get("diem_den"),
                "gia": tour.get("gia"),
                "so_ngay": tour.get("so_ngay"),
                "loai_hinh": tour.get("loai_hinh"),
            }
            for tour in retrieved
        ],
        "retrieval_precision": precision,
        "retrieval_recall": recall,
        "passed": passed,
    }


async def _run(cases: list[dict[str, Any]], output: Path) -> tuple[Path, dict[str, Any]]:
    dataset = Dataset(name="tour_retrieval_cases", backend="local/jsonl", root_dir=str(output), data=cases)
    dataset.save()
    name = "tour_retrieval_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    results = await evaluate_case.arun(dataset, name=name)
    rows = list(results)
    summary = {
        "run": name,
        "total": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "failed": sum(not row["passed"] for row in rows),
        "mean_precision": round(sum(row["retrieval_precision"] for row in rows) / len(rows), 4),
        "mean_recall": round(sum(row["retrieval_recall"] for row in rows) / len(rows), 4),
    }
    output_path = output / "experiments" / f"{name}.jsonl"
    return output_path, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Đánh giá retrieval tour bằng Ragas.")
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
