"""100 tình huống hỏi đáp thực tế của khách du lịch, đánh giá bằng Ragas.

Không gọi Gemini: mô phỏng phần lựa chọn tour/handoff khách nhìn thấy từ
main.py. Chạy: python -m tests.ragas_passenger_scenarios_eval
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


def _matches(tour: dict[str, Any], expect: dict[str, Any]) -> bool:
    destination = expect.get("destination")
    if destination:
        name_has_destination = bo_dau(str(destination)).lower() in bo_dau(str(tour.get("ten", ""))).lower()
        if tour.get("diem_den") != destination and not name_has_destination:
            return False
    if expect.get("not_destination") and tour.get("diem_den") == expect["not_destination"]:
        return False
    if expect.get("loai_hinh") and tour.get("loai_hinh") != expect["loai_hinh"]:
        return False
    if expect.get("so_ngay") and tour.get("so_ngay") != expect["so_ngay"]:
        return False
    if expect.get("gia_toi_da") and tour.get("gia", float("inf")) > expect["gia_toi_da"]:
        return False
    if expect.get("gia_toi_thieu") and tour.get("gia", float("-inf")) < expect["gia_toi_thieu"]:
        return False
    if expect.get("thang_khoi_hanh") and int(str(tour.get("ngay_khoi_hanh"))[5:7]) != expect["thang_khoi_hanh"]:
        return False
    return True


@numeric_metric(name="passenger_retrieval_precision", allowed_values=(0.0, 1.0))
def precision(retrieved: list[dict[str, Any]], expect: dict[str, Any]) -> float:
    if expect.get("empty"):
        return 1.0 if not retrieved else 0.0
    if not retrieved:
        return 0.0
    return sum(_matches(tour, expect) for tour in retrieved) / len(retrieved)


@numeric_metric(name="passenger_retrieval_recall", allowed_values=(0.0, 1.0))
def recall(retrieved: list[dict[str, Any]], expect: dict[str, Any]) -> float:
    if expect.get("empty"):
        return 1.0 if not retrieved else 0.0
    return 1.0 if any(_matches(tour, expect) for tour in retrieved) else 0.0


def add(cases: list[dict[str, Any]], category: str, question: str, expect: dict[str, Any]) -> None:
    cases.append({"id": f"passenger_{len(cases) + 1:03d}", "category": category, "question": question, "expect": expect})


def build_cases() -> list[dict[str, Any]]:
    rows = tat_ca_luot_con_han()
    destinations = Counter(row["diem_den"] for row in rows)
    if len(destinations) < 25:
        raise RuntimeError("Cần tối thiểu 25 điểm đến đang còn hiệu lực.")
    cases: list[dict[str, Any]] = []

    destination_templates = (
        "Gia đình tôi muốn đi {destination}, còn tour nào không?",
        "Tư vấn giúp mình chuyến {destination} vào dịp tới nhé",
        "Tôi đang quan tâm tour {destination}, gửi tôi vài lựa chọn",
        "Đi {destination} có tour nào phù hợp không bạn?",
        "Mình muốn xem lịch tour {destination}",
    )
    for index, (destination, _) in enumerate(destinations.most_common(25)):
        add(cases, "khách hỏi điểm đến", destination_templates[index % len(destination_templates)].format(destination=destination), {"destination": destination, "require_results": True})

    aliases = [(alias, destination) for alias, destination in ALIAS_DIEM_DEN.items() if destination in destinations and bo_dau(alias).lower() != bo_dau(destination).lower()]
    aliases.sort(key=lambda item: (len(item[0]), item[0]))
    for index, (alias, destination) in enumerate(aliases[:15]):
        add(cases, "khách dùng tên gọi khác", ("ad ơi có tour {alias} không ạ?", "mình muốn đi {alias}, tư vấn giúp")[index % 2].format(alias=alias), {"destination": destination, "require_results": True})

    budget_prompts = (
        (3, "Hai vợ chồng có khoảng 3 triệu/người, có tour nào không?"),
        (5, "Mình đi với bạn, ngân sách dưới 5 triệu thì đi đâu được?"),
        (7, "Có tour nào tầm 7 triệu cho gia đình không?"),
        (10, "Mình muốn tour dưới 10 triệu, gợi ý giúp nhé"),
        (15, "Ngân sách tối đa 15 triệu, có lựa chọn nào hay?"),
        (20, "Mình có 20 triệu, muốn xem các tour phù hợp"),
        (50, "Tôi muốn trải nghiệm tour cao cấp từ 50 triệu trở lên"),
        (100, "Tìm giúp tour hạng sang trên 100 triệu"),
        (5, "Sinh viên muốn đi chơi, chỉ có 5 triệu thôi"),
        (10, "Tour nào giá không quá 10 triệu vậy bạn?"),
    )
    for budget, question in budget_prompts:
        expect = {"gia_toi_thieu": budget * 1_000_000, "require_results": True} if budget in (50, 100) else {"gia_toi_da": 7_490_000 if budget == 7 else budget * 1_050_000, "require_results": True}
        add(cases, "khách hỏi ngân sách", question, expect)

    for duration in sorted({row["so_ngay"] for row in rows})[:10]:
        add(cases, "khách hỏi thời lượng", f"Tôi chỉ sắp xếp được {duration} ngày, có tour nào phù hợp không?", {"so_ngay": duration, "require_results": True})

    for question, category in (
        ("Nhà mình có trẻ nhỏ, muốn đi tour trong nước", "gia đình chọn loại hình"),
        ("Mình muốn đi nước ngoài lần đầu, xem giúp tour nhé", "khách chọn loại hình"),
        ("Cuối tuần này gia đình đi trong nước được không?", "gia đình chọn loại hình"),
        ("Đi cùng bạn bè, muốn thử tour nước ngoài", "khách chọn loại hình"),
    ):
        expected_type = "Trong Nước" if "trong nước" in question else "Nước Ngoài"
        add(cases, category, question, {"loai_hinh": expected_type, "require_results": True})

    for destination in ("Thái Lan", "Nhật Bản", "Hàn Quốc", "Singapore", "Trung Quốc", "Malaysia"):
        add(cases, "khách loại trừ điểm đến", f"Mình muốn đi nước ngoài nhưng không đi {destination}, tư vấn giúp nhé", {"loai_hinh": "Nước Ngoài", "not_destination": destination, "require_results": True})

    handoff_prompts = (
        "Tôi đã đặt tour rồi, cần hỗ trợ",
        "Tour tôi đã đặt bị đổi lịch, giúp tôi với",
        "Tôi muốn hủy tour đã đặt tuần trước",
        "Tôi đã thanh toán rồi mà chưa thấy xác nhận",
        "Hành lý của tôi bị mất trong chuyến đi",
        "Tôi muốn gặp nhân viên để khiếu nại",
        "Tôi cần nói chuyện trực tiếp với người hỗ trợ",
        "Tôi đã cọc tour rồi, muốn đổi ngày",
        "Tôi muốn hoàn tiền cho tour đã mua",
        "Đoàn của tôi bị trễ chuyến bay, cần hỗ trợ gấp",
    )
    for question in handoff_prompts:
        add(cases, "khách cần CSKH", question, {"empty": True, "handoff": True})

    info_prompts = (
        "Xin chào, bạn là ai?",
        "Hotline của công ty là gì?",
        "Địa chỉ văn phòng ở đâu?",
        "Chính sách hoàn tiền tour như thế nào?",
        "Công ty có làm visa không?",
        "Có thể thanh toán tour bằng cách nào?",
        "Tôi cần hóa đơn VAT cho chuyến đi",
        "Tour có mua bảo hiểm không?",
        "Có cần hộ chiếu khi đi nước ngoài không?",
        "Cảm ơn bạn, để tôi xem thêm nhé",
    )
    for question in info_prompts:
        add(cases, "khách hỏi thông tin dịch vụ", question, {"empty": True})

    months = sorted({int(str(row["ngay_khoi_hanh"])[5:7]) for row in rows})
    for index in range(10):
        month = months[index % len(months)]
        add(cases, "khách hỏi tháng khởi hành", f"Tháng {month} mình mới đi được, có tour nào không?", {"thang_khoi_hanh": month, "require_results": True})

    if len(cases) != 100:
        raise RuntimeError(f"Cần đúng 100 kịch bản, hiện có {len(cases)}.")
    return cases


@experiment()
def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    handoff = hoi_muon_gap_nhan_vien(case["question"])
    retrieved = [] if handoff else tim_tour_lien_quan(case["question"])
    p = precision(retrieved=retrieved, expect=case["expect"])
    r = recall(retrieved=retrieved, expect=case["expect"])
    return {
        **case,
        "handoff": handoff,
        "retrieved_count": len(retrieved),
        "retrieved": [{key: tour.get(key) for key in ("ten", "diem_den", "gia", "so_ngay", "ngay_khoi_hanh", "loai_hinh")} for tour in retrieved],
        "precision": p,
        "recall": r,
        "passed": p == 1.0 and r == 1.0 and (not case["expect"].get("handoff") or handoff),
    }


async def run(cases: list[dict[str, Any]], output: Path) -> tuple[str, list[dict[str, Any]]]:
    dataset = Dataset(name="passenger_scenarios", backend="local/jsonl", root_dir=str(output), data=cases)
    dataset.save()
    name = "passenger_scenarios_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    results = await evaluate_case.arun(dataset, name=name)
    return name, list(results)


def main() -> int:
    parser = argparse.ArgumentParser(description="Chạy 100 tình huống hành khách bằng Ragas, không gọi Gemini.")
    parser.add_argument("--output", type=Path, default=ROOT / "ragas_results")
    parser.add_argument("--reports", type=Path, default=ROOT / "ragas_reports")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    name, rows = asyncio.run(run(build_cases(), args.output))
    summary = {"run": name, "total": len(rows), "passed": sum(row["passed"] for row in rows), "failed": sum(not row["passed"] for row in rows), "mean_precision": round(sum(row["precision"] for row in rows) / len(rows), 4), "mean_recall": round(sum(row["recall"] for row in rows) / len(rows), 4), "gemini_api_called": False}
    args.reports.mkdir(parents=True, exist_ok=True)
    report_path = args.reports / f"{name}.json"
    report_path.write_text(json.dumps({"generated_at": datetime.now().astimezone().isoformat(), "summary": summary, "scenarios_and_results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    print(f"Details: {report_path}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
