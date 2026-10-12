import json
from openai import OpenAI
from config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_BASE_URL
from rules import LUAT_CO_DINH

client = OpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_BASE_URL)


def hoi_gemini(cau_hoi: str, tours: list[dict], lich_su: list[dict]) -> str:
    """Bản thay thế tạm cho hoi_luna() ở llm_luna.py — dùng Gemini (free tier)
    qua endpoint OpenAI-compatible của Google, để test không tốn credit OpenAI.
    Cùng cấu trúc prompt/messages với Luna, chỉ khác client/model.
    """
    danh_sach_tour = f"DANH SÁCH TOUR PHÙ HỢP:\n{json.dumps(tours, ensure_ascii=False, indent=2)}"

    messages = [{"role": "system", "content": LUAT_CO_DINH + "\n\n" + danh_sach_tour}]
    messages += lich_su
    messages.append({"role": "user", "content": cau_hoi})

    response = client.chat.completions.create(
        model=GEMINI_MODEL,
        max_tokens=1500,
        messages=messages,
    )
    noi_dung = response.choices[0].message.content
    if not noi_dung:
        noi_dung = "Mình tìm được vài tour phù hợp, bạn xem chi tiết bên dưới nhé:"
    return noi_dung


_PROMPT_TOM_TAT = """Nhiệm vụ của bạn là TÓM TẮT lại đoạn hội thoại dưới đây
cho một nhân viên CSKH đọc — bạn KHÔNG phải người trả lời khách, KHÔNG được
tư vấn/hướng dẫn/trả lời trực tiếp khách hàng trong output. Đoạn hội thoại là
giữa 1 khách hàng và chatbot AI tư vấn tour của BenThanh Tourist, nay khách
cần chuyển sang nhân viên THẬT xử lý tiếp qua Zalo. Nhân viên đó KHÔNG có sẵn
lịch sử chat này, nên bản tóm tắt của bạn là nguồn thông tin DUY NHẤT họ có
trước khi nhắn khách.

Viết ĐÚNG 1 đoạn văn xuôi ngắn (2-4 câu), BẮT BUỘC bằng tiếng Việt, không dùng
markdown/gạch đầu dòng, nêu rõ: (1) khách đang hỏi/quan tâm tour nào (tên tour/
điểm đến nếu có), (2) lý do cần chuyển nhân viên (khiếu nại/hoàn tiền/huỷ/đổi
lịch/câu hỏi ngoài khả năng AI...), (3) chi tiết cụ thể khách đã cung cấp
(ngày, số tiền, số người, mã tour nếu có). Chỉ viết nội dung tóm tắt, không
thêm lời chào, không thêm hướng dẫn xử lý, không thêm nhận xét."""


def tom_tat_hoi_thoai(cau_hoi_hien_tai: str, lich_su: list[dict]) -> str:
    """Dùng chính Gemini tóm tắt lịch sử hội thoại + câu hỏi hiện tại thành
    đoạn ngắn cho nhân viên CSKH đọc khi khách được chuyển sang Zalo — nhân
    viên không đọc được lịch sử chat của khách với bot (2 kênh tách biệt),
    nên nếu không tóm tắt, họ sẽ phải hỏi lại từ đầu, gây trải nghiệm xấu
    đúng lúc khách đang cần hỗ trợ nhất (khiếu nại/sự cố). max_tokens phải đủ
    RỘNG (không phải chỉ đủ cho câu trả lời ngắn) — model reasoning như Gemini
    3.6 Flash tiêu tốn 1 phần token ẩn cho suy luận trước khi sinh câu trả lời
    cuối, set quá sát (VD 300) khiến output bị CẮT CỤT giữa chừng (bug thật
    gặp phải: tóm tắt trả về "...)." dở dang). Lỗi gọi API (mất mạng, hết
    quota) không được làm sập luồng handoff — bắt buộc phải trả về MỘT giá
    trị chuỗi hợp lệ dù rỗng, để main.py vẫn chuyển khách sang Zalo kèm
    nguyên văn câu hỏi cuối làm phương án dự phòng."""
    hoi_thoai = "\n".join(f"{t['role']}: {t['content']}" for t in lich_su)
    hoi_thoai += f"\nuser: {cau_hoi_hien_tai}"

    du_phong = f"Khách hỏi: {cau_hoi_hien_tai}"
    try:
        response = client.chat.completions.create(
            model=GEMINI_MODEL,
            max_tokens=1000,
            messages=[
                {"role": "system", "content": _PROMPT_TOM_TAT},
                {"role": "user", "content": f"ĐOẠN HỘI THOẠI CẦN TÓM TẮT:\n{hoi_thoai}"},
            ],
        )
        tom_tat = response.choices[0].message.content
        if not tom_tat:
            return du_phong
        tom_tat = tom_tat.strip()
        # Phòng trường hợp model dừng sinh chữ giữa chừng (đã gặp thật dù
        # finish_reason vẫn báo "stop" — tính bất định của model, không phải
        # lỗi code) — câu tóm tắt dở dang (không kết thúc bằng dấu câu) gây
        # hiểu lầm/thiếu thông tin cho nhân viên hơn là không có gì. Cắt về
        # câu hoàn chỉnh gần nhất còn lại, hoặc dùng dự phòng nếu không còn
        # câu nào trọn vẹn.
        if tom_tat and tom_tat[-1] not in ".!?":
            cau_cuoi_hop_le = max(tom_tat.rfind(d) for d in ".!?")
            tom_tat = tom_tat[: cau_cuoi_hop_le + 1].strip() if cau_cuoi_hop_le > 0 else ""
        return tom_tat if tom_tat else du_phong
    except Exception:
        return du_phong
