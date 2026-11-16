"""100 kịch bản Ragas cho lớp truy xuất tour, không gọi Gemini.

Kịch bản được tạo từ dữ liệu ChromaDB hiện tại để có thể chạy lại sau khi
``sync_tours.py`` cập nhật lịch khởi hành.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from ragas import Dataset, experiment
from ragas.metrics import numeric_metric

from rag import bo_dau, hoi_muon_gap_nhan_vien, tat_ca_luot_con_han, tim_tour_lien_quan
from rules import ALIAS_DIEM_DEN


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "ragas_results"
DEFAULT_REPORTS = ROOT / "ragas_reports"


def _matches(tour: dict[str, Any], expect: dict[str, Any]) -> bool:
    destination = expect.get("destination")
    if destination:
        actual_destination = tour.get("diem_den")
        # Tour liên tuyến có thể lưu điểm đến là thành phố dừng chân, trong khi
        # tên tour giữ vùng/đất nước khách hỏi (VD Malaysia - Singapore). Đây
        # là kết quả hợp lệ theo quy tắc RAG hiện hành.
        if expect.get("allow_destination_in_tour_name"):
            destination_in_name = bo_dau(str(destination)).lower() in bo_dau(str(tour.get("ten", ""))).lower()
            if actual_destination != destination and not destination_in_name:
                return False
        elif actual_destination != destination:
            return False
    checks = {
        "loai_hinh": lambda value: tour.get("loai_hinh") == value,
        "so_ngay": lambda value: tour.get("so_ngay") == value,
        "gia_toi_da": lambda value: tour.get("gia", float("inf")) <= value,
        "gia_toi_thieu": lambda value: tour.get("gia", float("-inf")) >= value,
    }
    return all(checks[key](value) for key, value in expect.items() if key in checks)


@numeric_metric(name="retrieval_precision", allowed_values=(0.0, 1.0))
def retrieval_precision(retrieved: list[dict[str, Any]], expect: dict[str, Any]) -> float:
    if expect.get("empty"):
        return 1.0 if not retrieved else 0.0
    if not retrieved:
        return 0.0
    return sum(_matches(tour, expect) for tour in retrieved) / len(retrieved)


@numeric_metric(name="retrieval_recall", allowed_values=(0.0, 1.0))
def retrieval_recall(retrieved: list[dict[str, Any]], expect: dict[str, Any]) -> float:
    if expect.get("empty"):
        return 1.0 if not retrieved else 0.0
    return 1.0 if any(_matches(tour, expect) for tour in retrieved) else 0.0


def _case(case_id: str, category: str, question: str, expect: dict[str, Any]) -> dict[str, Any]:
    return {"id": case_id, "category": category, "question": question, "expect": expect}


def build_cases() -> list[dict[str, Any]]:
    rows = tat_ca_luot_con_han()
    destinations = Counter(row["diem_den"] for row in rows)
    if len(destinations) < 35:
        raise RuntimeError("Cần tối thiểu 35 điểm đến còn hiệu lực để tạo đủ 100 kịch bản.")

    cases: list[dict[str, Any]] = []
    ordered_destinations = [name for name, _ in destinations.most_common()]

    # 35 điểm đến trực tiếp + 20 cách gõ không dấu.
    for index, destination in enumerate(ordered_destinations[:35], start=1):
        cases.append(_case(f"destination_{index:02d}", "điểm đến", f"Có tour {destination} không?", {"destination": destination, "allow_destination_in_tour_name": True, "require_results": True}))
    for index, destination in enumerate(ordered_destinations[:20], start=1):
        cases.append(_case(f"destination_unaccented_{index:02d}", "điểm đến không dấu", f"co tour {bo_dau(destination).lower()} khong", {"destination": destination, "allow_destination_in_tour_name": True, "require_results": True}))

    # 15 alias phổ biến, nhưng chỉ lấy alias dẫn đến điểm đến đang có dữ liệu.
    aliases = [
        (alias, destination)
        for alias, destination in ALIAS_DIEM_DEN.items()
        if destination in destinations and bo_dau(alias).lower() != bo_dau(destination).lower()
    ]
    aliases.sort(key=lambda item: (len(item[0]), item[0]))
    for index, (alias, destination) in enumerate(aliases[:15], start=1):
        cases.append(_case(f"alias_{index:02d}", "tên gọi khác", f"Tư vấn tour {alias}", {"destination": destination, "require_results": True}))

    # 2 loại hình, 11 thời lượng thực tế, 8 ngưỡng ngân sách.
    cases.extend([
        _case("domestic", "loại hình", "Cho mình xem tour trong nước", {"loai_hinh": "Trong Nước", "require_results": True}),
        _case("international", "loại hình", "Cho mình xem tour nước ngoài", {"loai_hinh": "Nước Ngoài", "require_results": True}),
    ])
    for duration in sorted({row["so_ngay"] for row in rows}):
        cases.append(_case(f"duration_{duration}_days", "thời lượng", f"Có tour {duration} ngày không?", {"so_ngay": duration, "require_results": True}))
    for budget_million in (3, 5, 7, 10, 15, 20):
        # Ngoại lệ nghiệp vụ đã xác nhận: với ngân sách 7 triệu, cho phép tour
        # 7,49 triệu xuất hiện như một lựa chọn gần ngân sách.
        maximum_price = 7_490_000 if budget_million == 7 else budget_million * 1_050_000
        cases.append(_case(f"under_{budget_million}m", "ngân sách tối đa", f"Tư vấn tour dưới {budget_million} triệu", {"gia_toi_da": maximum_price, "require_results": True}))
    for budget_million in (50, 100):
        cases.append(_case(f"over_{budget_million}m", "ngân sách tối thiểu", f"Tìm giúp tour trên {budget_million} triệu", {"gia_toi_thieu": budget_million * 1_000_000, "require_results": True}))

    # 4 câu xã giao và 5 câu thông tin: không được tự gắn thẻ tour.
    for index, question in enumerate(("Xin chào", "Bạn là ai?", "Cảm ơn bạn", "Hotline là gì?"), start=1):
        cases.append(_case(f"no_tour_social_{index:02d}", "không nên trả tour", question, {"empty": True}))
    for index, question in enumerate((
        "Chính sách hoàn tiền tour như thế nào?",
        "Địa chỉ văn phòng ở đâu?",
        "Hướng dẫn thanh toán tour giúp mình",
        "Tôi đã đặt tour rồi, cần hỗ trợ",
        "Tôi muốn gặp nhân viên tư vấn",
    ), start=1):
        expect = {"empty": True}
        if question == "Tôi đã đặt tour rồi, cần hỗ trợ":
            expect["handoff"] = True
        cases.append(_case(f"no_tour_information_{index:02d}", "không nên trả tour", question, expect))

    if len(cases) != 100:
        raise RuntimeError(f"Bộ kịch bản phải có đúng 100 ca, hiện có {len(cases)}.")
    return cases


@experiment()
def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    # Khách thấy luồng handoff của main.py, không thấy kết quả retrieval thô.
    # Đánh giá theo cùng thứ tự xử lý để không báo lỗi giả cho yêu cầu hỗ trợ
    # đơn đã đặt hoặc yêu cầu gặp nhân viên.
    handoff = hoi_muon_gap_nhan_vien(case["question"])
    retrieved = [] if handoff else tim_tour_lien_quan(case["question"])
    expect = case["expect"]
    precision = retrieval_precision(retrieved=retrieved, expect=expect)
    recall = retrieval_recall(retrieved=retrieved, expect=expect)
    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "expect": expect,
        "handoff": handoff,
        "retrieved_count": len(retrieved),
        "retrieved": [{key: tour.get(key) for key in ("ten", "diem_den", "gia", "so_ngay", "loai_hinh")} for tour in retrieved],
        "retrieval_precision": precision,
        "retrieval_recall": recall,
        "passed": precision == 1.0 and recall == 1.0 and (not expect.get("handoff") or handoff),
    }


async def _run(cases: list[dict[str, Any]], output: Path) -> tuple[list[dict[str, Any]], str]:
    dataset = Dataset(name="tour_extended_retrieval_cases", backend="local/jsonl", root_dir=str(output), data=cases)
    dataset.save()
    name = "tour_extended_retrieval_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    results = await evaluate_case.arun(dataset, name=name)
    return list(results), name


def main() -> int:
    parser = argparse.ArgumentParser(description="Chạy 100 kịch bản retrieval Ragas, không gọi Gemini.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = build_cases()
    rows, name = asyncio.run(_run(cases, args.output))
    summary = {
        "run": name,
        "total": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "failed": sum(not row["passed"] for row in rows),
        "mean_retrieval_precision": round(sum(row["retrieval_precision"] for row in rows) / len(rows), 4),
        "mean_retrieval_recall": round(sum(row["retrieval_recall"] for row in rows) / len(rows), 4),
        "gemini_api_called": False,
    }
    report = {"generated_at": datetime.now().astimezone().isoformat(), "summary": summary, "scenarios_and_results": rows}
    args.reports.mkdir(parents=True, exist_ok=True)
    report_path = args.reports / f"{name}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    print(f"Details: {report_path}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
