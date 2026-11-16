"""Xuất toàn bộ kết quả Ragas mới nhất thành một báo cáo Markdown duy nhất."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "ragas_reports"


def latest(prefix: str) -> Path:
    files = sorted(REPORTS.glob(f"{prefix}_*.json"), key=lambda file: file.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"Không có báo cáo {prefix}.")
    return files[-1]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def escape(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def tours_markdown(tours: list[dict[str, Any]]) -> str:
    if not tours:
        return "Không có thẻ tour."
    lines = []
    for tour in tours:
        fields = [
            tour.get("ten", "Không rõ tên"),
            f"điểm đến: {tour.get('diem_den', '—')}",
            f"giá: {tour.get('gia', '—'):,}đ" if isinstance(tour.get("gia"), int) else "giá: —",
            f"{tour.get('so_ngay', '—')} ngày",
            f"khởi hành: {tour.get('ngay_khoi_hanh', '—')}",
        ]
        lines.append("- " + " · ".join(fields))
    return "\n".join(lines)


def suite_markdown(title: str, report: dict[str, Any], metric_names: tuple[str, str]) -> list[str]:
    rows = report["scenarios_and_results"]
    summary = report["summary"]
    precision_name, recall_name = metric_names
    lines = [f"## {title}", "", f"- Tổng ca: **{summary['total']}**", f"- Đạt: **{summary['passed']}**", f"- Không đạt: **{summary['failed']}**", ""]
    if precision_name in summary:
        lines.append(f"- Precision trung bình: **{summary[precision_name]:.3f}**")
    if recall_name in summary:
        lines.append(f"- Recall trung bình: **{summary[recall_name]:.3f}**")
    lines += ["", "| # | Nhóm | Câu hỏi | Số thẻ | Handoff | Precision | Recall | Kết quả |", "| ---: | --- | --- | ---: | --- | ---: | ---: | --- |"]
    for index, row in enumerate(rows, start=1):
        precision = row.get("retrieval_precision", row.get("precision", 0.0))
        recall = row.get("retrieval_recall", row.get("recall", 0.0))
        result = "Đạt" if row.get("passed") else "Không đạt"
        lines.append(f"| {index} | {escape(row.get('category', '—'))} | {escape(row['question'])} | {row['retrieved_count']} | {'Có' if row.get('handoff') else 'Không'} | {precision:.2f} | {recall:.2f} | {result} |")
    lines += ["", "### Chi tiết từng kịch bản", ""]
    for index, row in enumerate(rows, start=1):
        result = "Đạt" if row.get("passed") else "Không đạt"
        lines += [f"<details><summary>{index:03d}. {escape(row['question'])} — {result}</summary>", "", f"- Nhóm: {row.get('category', '—')}", f"- Kỳ vọng: `{json.dumps(row['expect'], ensure_ascii=False)}`", f"- Handoff: {'Có' if row.get('handoff') else 'Không'}", f"- Tour trả về ({row['retrieved_count']}):", tours_markdown(row.get("retrieved", [])), "", "</details>", ""]
    return lines


def main() -> None:
    technical_path = latest("tour_extended_retrieval")
    passenger_path = latest("passenger_scenarios")
    technical = load(technical_path)
    passenger = load(passenger_path)
    lines = ["# Báo cáo Ragas đầy đủ", "", f"Tạo lúc: {datetime.now().astimezone().isoformat()}", "", "Gemini API không được gọi trong hai bộ kiểm thử này.", ""]
    lines += suite_markdown("100 kịch bản kỹ thuật", technical, ("mean_retrieval_precision", "mean_retrieval_recall"))
    lines += suite_markdown("100 tình huống hành khách du lịch", passenger, ("mean_precision", "mean_recall"))
    output = REPORTS / f"ragas_full_markdown_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
