import time
import uuid
import httpx
from fastapi import FastAPI, HTTPException, Header, Depends, status, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from config import NESTJS_BASE_URL
from rules import (
    MAX_HISTORY_TURNS,
    RATE_LIMIT_PER_MINUTE,
    RATE_LIMIT_PER_HOUR,
    RATE_LIMIT_PER_DAY,
    MIN_GIAY_GIUA_2_CAU_HOI,
    ZALO_NHAN_VIEN_URL,
)
from rag import tim_tour_lien_quan, hoi_tim_tour_thieu_thong_tin, hoi_muon_gap_nhan_vien
from moderation import co_noi_dung_nhay_cam
from llm_gemini import hoi_gemini, tom_tat_hoi_thoai
from database import (
    khoi_tao_database,
    luu_tin_nhan,
    lay_lich_su,
    kiem_tra_rate_limit,
    don_tin_nhan_cu_3_ngay,
    xoa_lich_su_cuoc_tro_chuyen,
)

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


# [GEMINI] T-003: Cache token trong bộ nhớ 5 phút (dict tối đa 1000 items)
# Không ghi token vào log/print/traceback
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_MAX_SIZE = 1000


async def lay_nguoi_dung(authorization: str | None = Header(None)) -> str:
    """Xác thực token NestJS: gọi GET {NESTJS_BASE_URL}/api/v1/users/me (timeout 5s).
    Cache kết quả 5 phút theo token. Không log token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập đã hết hạn hoặc thiếu token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = time.time()
    if token in _TOKEN_CACHE:
        user_id, expire_at = _TOKEN_CACHE[token]
        if now < expire_at:
            return user_id
        else:
            _TOKEN_CACHE.pop(token, None)

    if not NESTJS_BASE_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chưa cấu hình NESTJS_BASE_URL trên máy chủ",
        )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{NESTJS_BASE_URL.rstrip('/')}/api/v1/users/me",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Phiên đăng nhập đã hết hạn",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            payload = resp.json()
            user_data = payload.get("data", payload) if isinstance(payload, dict) else {}
            user_id = str(user_data.get("id") or user_data.get("_id") or user_data.get("userId") or user_data.get("email") or "")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Không xác định được ID người dùng",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Quản lý dung lượng cache
            if len(_TOKEN_CACHE) >= _CACHE_MAX_SIZE:
                expired_keys = [k for k, v in _TOKEN_CACHE.items() if v[1] <= now]
                for k in expired_keys:
                    _TOKEN_CACHE.pop(k, None)
                if len(_TOKEN_CACHE) >= _CACHE_MAX_SIZE:
                    for k in list(_TOKEN_CACHE.keys())[:100]:
                        _TOKEN_CACHE.pop(k, None)

            _TOKEN_CACHE[token] = (user_id, now + 300)
            return user_id

    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Không thể kết nối đến máy chủ xác thực người dùng",
            headers={"WWW-Authenticate": "Bearer"},
        )


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
khoi_tao_database()

TRA_LOI_KHI_BI_CHAN = "Mình xin phép không trả lời câu này ạ. Câu này của bạn chứa từ ngữ nhạy cảm, thô tục. Bạn có câu hỏi nào khác về tour không? 😊"


# [GEMINI] T-003: ChatRequest theo Hợp đồng API {message, conversation_id}
class ChatRequest(BaseModel):
    message: str
    conversation_id: str

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, v: str) -> str:
        if not v or len(v) > 64:
            raise ValueError("conversation_id không hợp lệ (tối đa 64 ký tự)")
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("conversation_id phải là chuỗi UUID hợp lệ")
        return v


# [GEMINI] T-003: Healthcheck endpoint (không cần token)
@app.get("/health")
def health():
    return {"ok": True}


# [GEMINI] T-003: DELETE /chat/{conversation_id} -> 204 xoá lịch sử đúng user
@app.delete("/chat/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, user_id: str = Depends(lay_nguoi_dung)):
    if not conversation_id or len(conversation_id) > 64:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="conversation_id không hợp lệ",
        )
    xoa_lich_su_cuoc_tro_chuyen(user_id, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/chat")
def chat(req: ChatRequest, user_id: str = Depends(lay_nguoi_dung)):
    don_tin_nhan_cu_3_ngay()

    # [GEMINI] T-003: Khoá session nội bộ f"{user_id}:{conversation_id}"
    session_key = f"{user_id}:{req.conversation_id}"

    # Rate limit tính theo user_id (không theo từng cuộc trò chuyện)
    ly_do_bi_chan = kiem_tra_rate_limit(
        user_id, RATE_LIMIT_PER_MINUTE, RATE_LIMIT_PER_HOUR, RATE_LIMIT_PER_DAY, MIN_GIAY_GIUA_2_CAU_HOI
    )
    if ly_do_bi_chan:
        return {"reply": ly_do_bi_chan, "tours": [], "goi_y": []}

    if co_noi_dung_nhay_cam(req.message):
        return {"reply": TRA_LOI_KHI_BI_CHAN, "tours": [], "goi_y": []}

    lich_su = lay_lich_su(session_key, MAX_HISTORY_TURNS)

    if hoi_muon_gap_nhan_vien(req.message):
        tom_tat = tom_tat_hoi_thoai(req.message, lich_su)
        reply = (
            "Mình xin phép chuyển bạn sang trao đổi trực tiếp với nhân viên "
            "CSKH để được hỗ trợ nhanh và chính xác nhất nhé. Bạn bấm vào link "
            f"Zalo bên dưới, nhân viên đã có sẵn tóm tắt nội dung bạn vừa hỏi.\n{ZALO_NHAN_VIEN_URL}"
        )
        luu_tin_nhan(session_key, "user", req.message, user_id=user_id)
        luu_tin_nhan(session_key, "assistant", reply, user_id=user_id)
        return {
            "reply": reply,
            "tours": [],
            "goi_y": [],
            "handoff": {"zalo_url": ZALO_NHAN_VIEN_URL, "tom_tat": tom_tat},
        }

    tours_raw = tim_tour_lien_quan(req.message, lich_su=lich_su)
    tours = [chuan_hoa_the_tour(t) for t in tours_raw]
    goi_y_lam_ro = (
        ["Trong nước", "Nước ngoài", "Dưới 10 triệu", "Từ 10-20 triệu", "Có tour nào độc lạ không?"]
        if hoi_tim_tour_thieu_thong_tin(req.message)
        else []
    )

    reply = hoi_gemini(req.message, tours, lich_su)

    luu_tin_nhan(session_key, "user", req.message, user_id=user_id)
    luu_tin_nhan(session_key, "assistant", reply, user_id=user_id)
    return {"reply": reply, "tours": tours, "goi_y": goi_y_lam_ro}
