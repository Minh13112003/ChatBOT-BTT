import json
from openai import OpenAI
from config import OPENAI_API_KEY, LUNA_MODEL
from rules import LUAT_CO_DINH

client = OpenAI(api_key=OPENAI_API_KEY)


def hoi_luna(cau_hoi: str, tours: list[dict], lich_su: list[dict]) -> str:
    """Tương đương xay_system_prompt() + claude.messages.create() ở §10.7,
    nhưng dùng OpenAI Chat Completions API — cú pháp khác Anthropic:
    - Không có system riêng + cache_control, phải nhét vào messages[0] role=system.
    - Lịch sử hội thoại đi chung 1 mảng messages, không tách system/messages như Anthropic.
    """
    danh_sach_tour = f"DANH SÁCH TOUR PHÙ HỢP:\n{json.dumps(tours, ensure_ascii=False, indent=2)}"

    messages = [{"role": "system", "content": LUAT_CO_DINH + "\n\n" + danh_sach_tour}]
    messages += lich_su
    messages.append({"role": "user", "content": cau_hoi})

    response = client.chat.completions.create(
        model=LUNA_MODEL,
        # Luna là reasoning model — token "suy nghĩ" ẩn cũng trừ vào ngân sách
        # này trước khi sinh phần text hiển thị. 400 từng gây "reply": "" rỗng
        # hoàn toàn khi danh sách tour dài (7 tour) vì hết ngân sách giữa
        # chừng lúc suy luận, chưa kịp sinh chữ nào. Nâng lên hẳn để có dư.
        max_completion_tokens=1500,
        messages=messages,
    )
    noi_dung = response.choices[0].message.content
    if not noi_dung:
        # Phòng hờ vẫn bị cắt dù đã nâng ngân sách — không để giao diện
        # hiện bong bóng trống hoàn toàn.
        noi_dung = "Mình tìm được vài tour phù hợp, bạn xem chi tiết bên dưới nhé:"
    return noi_dung
