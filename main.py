from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rules import MAX_HISTORY_TURNS, RATE_LIMIT_PER_MINUTE, RATE_LIMIT_PER_HOUR, RATE_LIMIT_PER_DAY, MIN_GIAY_GIUA_2_CAU_HOI, ZALO_NHAN_VIEN_URL
from rag import tim_tour_lien_quan, hoi_tim_tour_thieu_thong_tin, hoi_muon_gap_nhan_vien
from moderation import co_noi_dung_nhay_cam
# [GEMINI] T-001: Chỉ dùng Gemini, bỏ Luna
from llm_gemini import hoi_gemini, tom_tat_hoi_thoai
from database import khoi_tao_database, luu_tin_nhan, lay_lich_su, kiem_tra_rate_limit

# [GEMINI] T-002: Chuẩn hoá dữ liệu thẻ tour đúng Hợp đồng API
def chuan_hoa_the_tour(tour: dict) -> dict:
    gia = tour.get("gia")
    if gia is not None:
        try:
            gia = int(gia)
        except (ValueError, TypeError):
            gia = None

    anh = tour.get("anh")
    if not anh or not str(anh).strip():
        anh = None
    else:
        anh = str(anh).strip()

    return {
        "tour_key": str(tour.get("tour_key", "")),
        "id": str(tour.get("id", "")),
        "ten": str(tour.get("ten", "")),
        "gia": gia,
        "so_ngay": int(tour.get("so_ngay", 0)),
        "ngay_khoi_hanh": str(tour.get("ngay_khoi_hanh", "")),
        "so_cho_con": int(tour.get("so_cho_con", 0)),
        "anh": anh,
        "url": str(tour.get("url", "")),
        "diem_den": str(tour.get("diem_den", "")),
        "loai_hinh": str(tour.get("loai_hinh", "")),
    }

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
khoi_tao_database()

TRA_LOI_KHI_BI_CHAN = "Mình xin phép không trả lời câu này ạ. Câu này của bạn chứa từ ngữ nhạy cảm, thô tục. Bạn có câu hỏi nào khác về tour không? 😊"


class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/chat")
def chat(req: ChatRequest):
    ly_do_bi_chan = kiem_tra_rate_limit(
        req.session_id, RATE_LIMIT_PER_MINUTE, RATE_LIMIT_PER_HOUR, RATE_LIMIT_PER_DAY, MIN_GIAY_GIUA_2_CAU_HOI
    )
    if ly_do_bi_chan:
        return {"reply": ly_do_bi_chan, "tours": []}

    if co_noi_dung_nhay_cam(req.message):
        return {"reply": TRA_LOI_KHI_BI_CHAN, "tours": []}

    lich_su = lay_lich_su(req.session_id, MAX_HISTORY_TURNS)

    if hoi_muon_gap_nhan_vien(req.message):
        # Khiếu nại/hoàn tiền/đổi lịch/khách chủ động đòi gặp người thật —
        # KHÔNG để AI tự trả lời (rủi ro nói sai chính sách hoàn tiền/huỷ tour
        # thật), chuyển thẳng sang Zalo nhân viên kèm bản tóm tắt hội thoại để
        # nhân viên không phải hỏi lại từ đầu (2 kênh tách biệt, nhân viên
        # không đọc được lịch sử chat với bot). Vẫn lưu lại tin nhắn khách để
        # không mất dấu vết hội thoại nếu khách quay lại chat tiếp với bot.
        tom_tat = tom_tat_hoi_thoai(req.message, lich_su)
        reply = (
            "Mình xin phép chuyển bạn sang trao đổi trực tiếp với nhân viên "
            "CSKH để được hỗ trợ nhanh và chính xác nhất nhé. Bạn bấm vào link "
            f"Zalo bên dưới, nhân viên đã có sẵn tóm tắt nội dung bạn vừa hỏi.\n{ZALO_NHAN_VIEN_URL}"
        )
        luu_tin_nhan(req.session_id, "user", req.message)
        luu_tin_nhan(req.session_id, "assistant", reply)
        return {
            "reply": reply,
            "tours": [],
            "goi_y": [],
            "handoff": {"zalo_url": ZALO_NHAN_VIEN_URL, "tom_tat": tom_tat},
        }

    tours_raw = tim_tour_lien_quan(req.message, lich_su=lich_su)
    # [GEMINI] T-002: Chuẩn hoá danh sách tour đúng Hợp đồng API
    tours = [chuan_hoa_the_tour(t) for t in tours_raw]
    # Khách rõ ràng muốn tìm tour nhưng chưa nêu điều kiện gì cụ thể (không
    # điểm đến/ngân sách/thời gian) -> gợi ý câu hỏi làm rõ NGAY trên giao
    # diện (chip bấm nhanh), thay vì chỉ trông chờ AI tự hỏi ngược trong văn
    # bản trả lời — khách lười gõ có thể bấm thẳng thay vì phải tự nghĩ trả lời.
    goi_y_lam_ro = (
        ["Trong nước", "Nước ngoài", "Dưới 10 triệu", "Từ 10-20 triệu", "Có tour nào độc lạ không?"]
        if hoi_tim_tour_thieu_thong_tin(req.message)
        else []
    )

    # [GEMINI] T-001: Luôn dùng Gemini cho bttAI
    reply = hoi_gemini(req.message, tours, lich_su)

    luu_tin_nhan(req.session_id, "user", req.message)
    luu_tin_nhan(req.session_id, "assistant", reply)
    return {"reply": reply, "tours": tours, "goi_y": goi_y_lam_ro}
