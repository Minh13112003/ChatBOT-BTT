import json
import re
import threading
import time
import openai
from openai import OpenAI
from config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_BASE_URL
from rules import LUAT_CO_DINH

# Model dự phòng khi model chính quá tải (503/429) hoặc treo. Đã gọi thử endpoint OpenAI-compatible: nhận được.
GEMINI_MODEL_DU_PHONG = "gemini-3-flash-preview"
# App chỉ chờ 30s mỗi câu (services/chatbot.ts). Tệ nhất: 12s model chính + 10s model dự phòng = 22s < 28s.
TIMEOUT_MODEL_CHINH_GIAY = 12.0
TIMEOUT_MODEL_DU_PHONG_GIAY = 10.0
TIMEOUT_TOM_TAT_GIAY = 12.0
TONG_THOI_GIAN_TOI_DA_GIAY = 28.0
THOI_GIAN_TOI_THIEU_DE_HOI_LAI_GIAY = 3.0
# Token suy luận ẩn tính chung vào max_tokens. Mặc định, model dự phòng tiêu khoảng 1.440/1.500 token cho suy luận và câu
# trả lời bị cắt sau khoảng 200 ký tự (finish_reason="length"), một câu còn tốn tới 12s. Đo thật: "low" còn 0 token ẩn, 2-3s.
MUC_SUY_LUAN = "low"

# max_retries=0: SDK tự thử lại ngầm (kèm chờ) từng làm 1 câu treo tới 253s; việc thử lại do hoi_gemini điều khiển.
client = OpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_BASE_URL, timeout=TIMEOUT_MODEL_CHINH_GIAY, max_retries=0)

_LOI_NEN_THU_LAI = (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)

# Token của câu đang trả lời, để trang quản trị tính chi phí. Mỗi request /chat chạy trên 1 luồng nên dùng thread-local.
_token_cau_hoi = threading.local()


def _ghi_token(response, model: str) -> None:
    usage = getattr(response, "usage", None)
    vao, ra = getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)
    if not isinstance(vao, int) or not isinstance(ra, int):
        return
    cu = getattr(_token_cau_hoi, "gia_tri", None) or {"inputTokens": 0, "outputTokens": 0}
    # Một câu có thể gọi 2 lần (hỏi lại khi bị cắt): cộng dồn vì cả 2 lần đều tốn tiền.
    _token_cau_hoi.gia_tri = {"model": model, "inputTokens": cu["inputTokens"] + vao, "outputTokens": cu["outputTokens"] + ra}


def lay_token_cau_vua_hoi() -> dict | None:
    """Trả {model, inputTokens, outputTokens} của lần hoi_gemini vừa rồi (đọc xong thì xoá), None nếu không gọi Gemini."""
    gia_tri = getattr(_token_cau_hoi, "gia_tri", None)
    _token_cau_hoi.gia_tri = None
    return gia_tri


def loc_dau_ra(text: str | None) -> str:
    """App chỉ hiển thị văn bản thuần: bỏ chú thích HTML (từng lộ "<!-- Thẻ tour sẽ hiển thị ở đây -->"), thẻ HTML,
    **in đậm**, dấu `, và dấu # đầu dòng. Chuỗi toàn khoảng trắng/rỗng -> ""."""
    if not text:
        return ""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # Chỗ giữ chỗ AI tự chèn cho thẻ tour (bug thật: "[Chèn thẻ tour tại đây]" hiện nguyên trong khung chat)
    text = re.sub(r"\[[^\[\]\n]{0,60}(?:thẻ tour|the tour|chèn|tour card)[^\[\]\n]{0,60}\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?[A-Za-z][^<>]*>", "", text)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _bi_cat_giua_chung(noi_dung: str, finish_reason: str | None) -> bool:
    """Hết token, hoặc kết thúc dở dang dù báo "stop" (đã gặp thật ở tom_tat_hoi_thoai). Dòng gạch đầu dòng và câu kết bằng
    dấu ":" (dẫn vào thẻ tour) hay emoji được coi là trọn vẹn."""
    if finish_reason == "length":
        return True
    if not noi_dung or noi_dung.rsplit("\n", 1)[-1].lstrip().startswith("-"):
        return False
    ky_tu_cuoi = noi_dung[-1]
    return ky_tu_cuoi.isalnum() or ky_tu_cuoi in ",;-–—(/"


def _cat_ve_cau_tron_ven(noi_dung: str) -> str:
    """Bỏ phần dở dang cuối, giữ tới hết câu hoặc hết dòng gần nhất. Dấu chấm trong "10.000.000" không phải hết câu."""
    moc_cat = [m.end() for m in re.finditer(r"[.!?…](?=\s|$)|\n", noi_dung)]
    return noi_dung[: moc_cat[-1]].strip() if moc_cat else ""


def hoi_gemini(cau_hoi: str, tours: list[dict], lich_su: list[dict], tin_nhan_vien: str | None = None, ghi_chu_kenh: str | None = None,
               chinh_sach: str | None = None) -> str:
    """Bản thay thế tạm cho hoi_luna() ở llm_luna.py — dùng Gemini (free tier)
    qua endpoint OpenAI-compatible của Google, để test không tốn credit OpenAI.
    Cùng cấu trúc prompt/messages với Luna, chỉ khác client/model.
    """
    danh_sach_tour = f"DANH SÁCH TOUR PHÙ HỢP:\n{json.dumps(tours, ensure_ascii=False, indent=2)}"

    # Tin nhân viên thật đã nhắn khách (chỉ có khi nối trang quản trị): khách hay trả lời đúng thứ nhân viên vừa gửi.
    khoi_nhan_vien = (f"\n\nNHÂN VIÊN BENTHANH ĐÃ NHẮN KHÁCH GẦN ĐÂY (cũ trước, mới sau):\n{tin_nhan_vien}" if tin_nhan_vien else "")
    # Kênh Zalo/Facebook: tên khách trên kênh và việc không đặt tour được trong khung chat (main.ghi_chu_kenh).
    khoi_kenh = f"\n\nKÊNH NHẮN TIN:\n{ghi_chu_kenh}" if ghi_chu_kenh else ""
    # Chính sách theo tour (cọc, huỷ, thanh toán, bao gồm...) lấy từ API chi tiết tour: chinh_sach_tour.khoi_chinh_sach.
    khoi_chinh_sach = f"\n\n{chinh_sach}" if chinh_sach else ""
    messages = [{"role": "system", "content": LUAT_CO_DINH + khoi_kenh + "\n\n" + danh_sach_tour + khoi_chinh_sach + khoi_nhan_vien}]
    messages += lich_su
    messages.append({"role": "user", "content": cau_hoi})

    def goi(model: str, timeout: float):
        response = client.chat.completions.create(
            model=model, max_tokens=1500, messages=messages, timeout=timeout, reasoning_effort=MUC_SUY_LUAN,
        )
        _ghi_token(response, model)
        lua_chon = response.choices[0]
        return loc_dau_ra(lua_chon.message.content), lua_chon.finish_reason

    _token_cau_hoi.gia_tri = None
    bat_dau = time.monotonic()
    try:
        noi_dung, ly_do_dung = goi(GEMINI_MODEL, TIMEOUT_MODEL_CHINH_GIAY)
    except _LOI_NEN_THU_LAI:
        # Quá tải / treo: thử nhanh đúng 1 lần với model dự phòng; lỗi tiếp thì ném ra (main.py có câu dự phòng).
        noi_dung, ly_do_dung = goi(GEMINI_MODEL_DU_PHONG, TIMEOUT_MODEL_DU_PHONG_GIAY)

    if _bi_cat_giua_chung(noi_dung, ly_do_dung):
        # Hỏi lại 1 lần nếu còn kịp (app chỉ chờ 30s). Lần này lỗi hoặc vẫn dở thì cắt về câu trọn vẹn, không để lộ câu dở.
        con_lai = TONG_THOI_GIAN_TOI_DA_GIAY - (time.monotonic() - bat_dau)
        if con_lai >= THOI_GIAN_TOI_THIEU_DE_HOI_LAI_GIAY:
            try:
                noi_dung_moi, ly_do_moi = goi(GEMINI_MODEL_DU_PHONG, min(con_lai, TIMEOUT_MODEL_DU_PHONG_GIAY))
                if noi_dung_moi:
                    noi_dung, ly_do_dung = noi_dung_moi, ly_do_moi
            except _LOI_NEN_THU_LAI:
                pass
        if _bi_cat_giua_chung(noi_dung, ly_do_dung):
            noi_dung = _cat_ve_cau_tron_ven(noi_dung) or ("" if ly_do_dung == "length" else noi_dung)

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
            timeout=TIMEOUT_TOM_TAT_GIAY,
            reasoning_effort=MUC_SUY_LUAN,
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
