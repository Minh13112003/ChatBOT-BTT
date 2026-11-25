import re
import threading
import time
import unicodedata
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Header, Depends, Request, UploadFile, status, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import admin_chat
import lich_su_db
from config import NESTJS_BASE_URL, NHUNG_CHO_PHEP
from rules import (
    MAX_HISTORY_TURNS,
    RATE_LIMIT_PER_MINUTE,
    RATE_LIMIT_PER_HOUR,
    RATE_LIMIT_PER_DAY,
    MIN_GIAY_GIUA_2_CAU_HOI,
    ZALO_NHAN_VIEN_URL,
    TU_KHOA_HOI_HOTLINE,
    TRA_LOI_HOTLINE,
    TRA_LOI_CACH_DAT_TOUR,
)
from rag import (
    chia_trang_dip, hoi_dip_le_chung, hoi_xem_tiep_tour,
    tim_tour_lien_quan, hoi_tim_tour_thieu_thong_tin, hoi_muon_gap_nhan_vien, hoi_cach_dat_tour, _co_cum_tu,
    dia_danh_khong_co_tour, ten_goi_diem_den, trich_diem_den, can_nhan_vien_som,
    co_cau_hoi_ngoai_sdt, la_cau_hoi_cua_nhan_vien, nhieu_noi_hoac_nhieu_ngay, hoi_ngay_khoi_hanh_sat,
)
from moderation import co_noi_dung_nhay_cam
from llm_gemini import hoi_gemini, lay_token_cau_vua_hoi, tom_tat_hoi_thoai
import chinh_sach_tour
import ngoai_pham_vi
import dat_tour
from database import (
    khoi_tao_database,
    lay_khach_web,
    lay_moc_doc_web,
    luu_khach_web,
    luu_tin_nhan,
    lay_lich_su,
    moc_lich_su_cu_nhat,
    kiem_tra_rate_limit,
    don_tin_nhan_cu_3_ngay,
    xoa_lich_su_cuoc_tro_chuyen,
)

# Số CCCD (12 số) / hộ chiếu (1 chữ + 7 số): chatbot cam kết KHÔNG thu trong chat — nếu khách tự gõ
# thì che đi trước khi lưu lịch sử 3 ngày và trước khi gửi cho AI. Số điện thoại (10 số) không bị che.
_MAU_GIAY_TO = re.compile(r"(?<![\w])(?:\d{12}|[A-Za-z]\d{7})(?![\w])")


def che_giay_to(text: str) -> str:
    return _MAU_GIAY_TO.sub("[đã ẩn]", text)


def _tien_dong(v) -> str:
    return f"{int(round(float(v))):,}".replace(",", ".") + " đ"


def _muc_gia(v: int) -> str:
    """10_000_000 -> "10 triệu", 7_500_000 -> "7,5 triệu", 500_000 -> "500.000 đ"."""
    if v >= 1_000_000:
        so = f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{so} triệu"
    return _tien_dong(v)


def tra_loi_khong_co_trong_tam_gia(goi_y: dict, cau_hoi: str) -> str:
    """Câu trả lời VIẾT SẴN (không qua AI, số liệu luôn đúng): không có tour nào dưới mức giá khách nêu,
    giới thiệu tour gần mức giá nhất."""
    ten_noi = ten_goi_diem_den(cau_hoi, goi_y["diem_den"]) if goi_y.get("diem_den") else ""
    noi = f" {ten_noi}" if ten_noi else ""
    if ten_noi:
        # "Đà Lạt" nằm trong tỉnh Lâm Đồng (cùng tỉnh còn tour Đắk Nông): ưu tiên tour có đúng chữ khách gõ trong tên.
        goi_y["tours"].sort(key=lambda m: ten_noi.lower() not in str(m.get("ten", "")).lower())
    t = goi_y["tours"][0]
    cau = (
        f"Hiện BenThanh Tourist chưa có tour{noi} nào dưới {_muc_gia(goi_y['ngan_sach'])}. "
        f"Tour gần mức giá bạn đưa ra nhất là “{t['ten']}” giá {_tien_dong(t['gia'])}"
    )
    if len(goi_y["tours"]) > 1:
        cau += f", ngoài ra còn {len(goi_y['tours']) - 1} tour khác"
    return cau + ". Bạn tham khảo ở thẻ tour bên dưới nhé, hoặc cho mình biết mức giá khác để mình tìm thêm."


def tra_loi_gan_dung(goi_y: dict) -> str:
    """Câu VIẾT SẴN (không qua AI, số liệu luôn đúng): nói rõ không có tour đúng yêu cầu, giới thiệu tour tương tự."""
    noi = f" {goi_y['noi']}" if goi_y.get("noi") else ""
    # Đọc tự nhiên: "tour Trung Quốc nào vào dịp Tết kéo dài 6 ngày" (thời lượng đứng cuối).
    yeu_cau = " ".join(reversed(goi_y["yeu_cau"]))

    def mo_ta(t: dict) -> str:
        ngay = str(t["ngay_khoi_hanh"])[:10]
        phan = [f"khởi hành {ngay[8:10]}/{ngay[5:7]}/{ngay[:4]}", f"giá {_tien_dong(t['gia'])}"]
        if t.get("so_ngay"):
            phan.insert(0, f"{t['so_ngay']} ngày {max(t['so_ngay'] - 1, 0)} đêm")
        return ", ".join(phan)

    if goi_y.get("vuot_gia"):
        yeu_cau += f" dưới {_muc_gia(goi_y['vuot_gia'])}"
    cau = f"Hiện BenThanh Tourist chưa có tour{noi} nào {yeu_cau}. "
    tours = goi_y["tours"]
    if len(tours) == 1:
        cau += f"Bên mình có tour tương tự là “{tours[0]['ten']}” ({mo_ta(tours[0])})."
    else:
        cau += f"Bên mình có {len(tours)} tour tương tự:\n" + "\n".join(f"- “{t['ten']}” ({mo_ta(t)})" for t in tours)
    if goi_y.get("vuot_gia"):
        cau += f"\n\nLưu ý: {'các tour này có' if len(tours) > 1 else 'tour này có'} giá cao hơn mức {_muc_gia(goi_y['vuot_gia'])} bạn đưa ra."
    return cau + "\n\nBạn xem chi tiết ở thẻ tour bên dưới nhé."


def tra_loi_noi_khong_co_tour(noi: str) -> str:
    return (
        f"Hiện BenThanh Tourist chưa có tour đi {noi}. Bạn có thể tham khảo các điểm đến khác đang mở bán "
        "(ví dụ Nhật Bản, Hàn Quốc, Châu Âu, Đà Lạt, Phú Quốc), hoặc nhắn “gặp nhân viên” để được tư vấn tour theo yêu cầu nhé."
    )


def _so_nguyen(v) -> int:
    """so_ngay / so_cho_con có thể là None hoặc chữ trong dữ liệu tour -> 0 thay vì làm sập cả câu trả lời."""
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


# [GEMINI] T-002: Chuẩn hoá dữ liệu thẻ tour đúng Hợp đồng API
def chuan_hoa_the_tour(tour: dict | None) -> dict:
    tour = tour or {}
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

    the = {
        "tour_key": str(tour.get("tour_key") or ""),
        "id": str(tour.get("id") or ""),
        "ten": str(tour.get("ten") or ""),
        "gia": gia,
        "so_ngay": _so_nguyen(tour.get("so_ngay")),
        "ngay_khoi_hanh": str(tour.get("ngay_khoi_hanh") or ""),
        "so_cho_con": _so_nguyen(tour.get("so_cho_con")),
        "anh": anh,
        "url": str(tour.get("url") or ""),
        "diem_den": str(tour.get("diem_den") or ""),
        "loai_hinh": str(tour.get("loai_hinh") or ""),
    }
    # App vẽ thanh ngang + dòng "phan_cach_truoc" ngay trước thẻ; 2 field nhóm để AI giới thiệu tách đúng nhóm.
    for khoa in ("phan_cach_truoc", "ten_dip", "nhom_dip"):
        if tour.get(khoa):
            the[khoa] = str(tour[khoa])
    return the


def nhac_xem_tiep(con_lai: list[dict]) -> str:
    return f'Còn {len(con_lai)} tour nữa, bạn gõ "tiếp tục" hoặc "còn tour nào không" để xem tiếp nhé.'


# [GEMINI] T-003: Cache token trong bộ nhớ 5 phút (dict tối đa 1000 items)
# Không ghi token vào log/print/traceback
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_MAX_SIZE = 1000

# Tên + SĐT từ tài khoản, để gửi cho trang quản trị. /users/me còn trả CCCD, hộ chiếu...: cố ý KHÔNG giữ các trường đó.
_HO_SO_KHACH: dict[str, dict] = {}


def trich_ho_so_khach(user_data: dict) -> dict:
    """Chỉ lấy tên và SĐT. Backend mới (trang quản trị chat, /app/users/me) trả `fullName` đúng thứ tự họ tên;
    không có thì ghép firstName rồi lastName như bản cũ."""
    ten = str(user_data.get("fullName") or "").strip() or " ".join(str(user_data.get(k) or "").strip() for k in ("firstName", "lastName")).strip()
    sdt = str(user_data.get("phonenumber") or "").strip()
    return {**({"name": ten[:120]} if ten else {}), **({"phone": sdt[:30]} if sdt else {})}


async def lay_nguoi_dung(authorization: str | None = Header(None)) -> str:
    """Xác thực token app: gọi GET {NESTJS_BASE_URL}/api/v1/app/users/me của trang quản trị chat (timeout 5s).
    Từ 2026-11-16 tài khoản app nằm ở trang quản trị chat; `id` trả về là id tài khoản app, trùng mã khách kênh APP bên đó.
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
                f"{NESTJS_BASE_URL.rstrip('/')}/api/v1/app/users/me",
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
            if len(_HO_SO_KHACH) >= _CACHE_MAX_SIZE:
                _HO_SO_KHACH.clear()  # chỉ là bộ nhớ đệm: lần xác thực sau của mỗi khách sẽ ghi lại
            _HO_SO_KHACH[user_id] = trich_ho_so_khach(user_data)
            return user_id

    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Không thể kết nối đến máy chủ xác thực người dùng",
            headers={"WWW-Authenticate": "Bearer"},
        )


app = FastAPI()

# CORS cho Zalo Mini App (chạy như web app trong trình duyệt/webview Zalo — gọi chatbot từ origin khác).
# Xác thực bằng header Authorization (Bearer), KHÔNG dùng cookie nên không bật credentials.
# Chỉ mở cho: localhost/LAN (zmp start), Zalo (h5.zdn.vn, zbrowser://h5.zdn.vn) và tunnel preview *.mini.123c.vn.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?|https://([a-z0-9-]+\.)?(mini\.123c\.vn|zdn\.vn)|zbrowser://h5\.zdn\.vn)$",
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)
@app.middleware("http")
async def chi_cho_website_duoc_phep_nhung(request: Request, call_next):
    """Khung chat web chỉ được nhúng (iframe, qua static/widget.js) vào website trong NHUNG_CHO_PHEP, mặc định benthanhtourist.com.
    Website lạ nhúng thì trình duyệt không hiện, để không ai gắn chatbot của công ty lên trang của họ."""
    res = await call_next(request)
    if request.url.path == "/static/chat.html":
        res.headers["Content-Security-Policy"] = f"frame-ancestors 'self' {NHUNG_CHO_PHEP}"
    return res


app.mount("/static", StaticFiles(directory="static"), name="static")
khoi_tao_database()

# Khách chưa để SĐT (Zalo, Facebook) mà gõ số; đoàn công ty / đoàn đông; chỉ cần vé máy bay hoặc khách sạn lẻ: bot không phục vụ được,
# báo nhân viên ngay (cờ wantsHuman). Câu dưới đây chỉ dùng khi trang quản trị không trả lời (backend đã có câu báo riêng khi nối được).
TRA_LOI_NHAN_VIEN_SOM = {
    "SDT": "Mình đã ghi nhận số điện thoại của bạn và chuyển cho nhân viên. Nhân viên BenThanh sẽ liên hệ bạn sớm nhé.",
    "DOANH_NGHIEP": "Với đoàn công ty hoặc đoàn đông người, nhân viên cần trao đổi trực tiếp để báo giá phù hợp. Mình đã chuyển yêu cầu của bạn cho nhân viên, "
                    "bạn cũng có thể gọi bộ phận đoàn: trong nước 0971 963 676, quốc tế 0919 696 894.",
    "VE_RIENG": "Vé máy bay lẻ bạn liên hệ hotline 0823 260 110 nhé. Mình cũng đã chuyển yêu cầu của bạn cho nhân viên để hỗ trợ thêm về vé và khách sạn.",
    "DAT_TOUR": "Mình đã báo nhân viên BenThanh. Nhân viên sẽ nhắn bạn ngay tại đây để kiểm tra chỗ và chốt tour nhé.",
    # Khách nêu ngày đi còn dưới 3 ngày (chốt 2026-11-19): chatbot không gợi ý tour sát ngày, nhân viên kiểm tra chỗ thật.
    "NGAY_SAT": "Tour khởi hành sát ngày cần nhân viên kiểm tra chỗ còn hay không. Mình đã báo nhân viên BenThanh, nhân viên sẽ nhắn bạn sớm nhé.",
    # Mục chưa có dữ liệu (chủ dự án chốt 2026-11-25). Câu này cũng gửi cho trang quản trị (contactReply) để thay câu báo mặc định.
    "TU_VAN": "Trường hợp này mình sẽ liên hệ nhân viên tư vấn cho bạn nha. Trong lúc chờ nhân viên, bạn cứ hỏi mình vấn đề khác bạn đang thắc mắc nhé.",
}
# Lý do gửi câu riêng cho trang quản trị thay câu "Mình đã báo nhân viên..." mặc định.
CAU_BAO_RIENG = ("TU_VAN",)
# Zalo, Facebook (chốt 19/11/2026): bot vẫn tư vấn, gọi khách theo tên trên kênh đó, nhưng KHÔNG chạy luồng đặt tour (luồng đặt cần tài khoản
# app); khách muốn đặt / chốt thì báo nhân viên để sale chủ động nhắn. Bug thật: luồng đặt nuốt số điện thoại, chọn sai ngày.
KENH_MANG_XA_HOI = ("ZALO", "FACEBOOK")


def ghi_chu_kenh(kenh: str, khach: dict | None) -> str | None:
    if kenh not in KENH_MANG_XA_HOI:
        return None
    ten_kenh = "Zalo" if kenh == "ZALO" else "Facebook"
    dong = [
        f"Khách đang nhắn qua {ten_kenh}. Khách KHÔNG đặt tour được trong khung chat này: đừng hướng dẫn đặt trên app hay bấm nút đặt tour. "
        "Khi khách nói muốn đặt, hệ thống tự báo nhân viên; còn lại bạn ĐỪNG hứa nhân viên sẽ nhắn, gọi hay liên hệ, vì chưa ai được báo."
    ]
    ten = ((khach or {}).get("name") or "").strip()
    if ten:
        dong.append(f"Tên {ten_kenh} của khách: {ten[:60]}. Gọi khách bằng tên này cho thân thiện; chưa rõ là anh hay chị thì đừng tự đoán.")
    return chr(10).join(dong)


def _muon_dat_tour(cau: str) -> bool:
    return dat_tour.hoi_dat_tour(cau) or dat_tour.chi_noi_muon_dat(cau) or dat_tour.muon_dang_ky(cau) or hoi_cach_dat_tour(cau)
DO_DAI_TIN_NHAN_TOI_DA = 1000  # ký tự; dài hơn thì không gửi cho AI (tốn token, thường là dán nhầm/spam)
TRA_LOI_KHI_AI_LOI = "Trợ lý đang bận nên mình chưa trả lời chi tiết được, bạn thử lại sau ít phút nhé."
TRA_LOI_KHI_AI_LOI_CO_TOUR = "Mình tìm được vài tour phù hợp, bạn xem chi tiết ở các thẻ bên dưới nhé."
TRA_LOI_KHI_BI_CHAN = "Mình xin phép không trả lời câu này ạ. Câu này của bạn chứa từ ngữ nhạy cảm, thô tục. Bạn có câu hỏi nào khác về tour không? 😊"


# [GEMINI] T-003: ChatRequest theo Hợp đồng API {message, conversation_id}
class ChatAction(BaseModel):
    """Nút bấm trong khung chat (luồng đặt tour, xem dat_tour.py). `values` dùng cho nút chọn nhiều (người đi cùng)."""
    id: str
    values: list[str] | None = None
    label: str | None = Field(default=None, max_length=500)  # Chữ trên nút khách bấm, để nhân viên đọc được trong lịch sử.


class ChatRequest(BaseModel):
    message: str = ""
    conversation_id: str
    action: ChatAction | None = None

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
    dat_tour.xoa_trang_thai(f"{user_id}:{conversation_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/chat")
def chat(
    req: ChatRequest,
    nen: BackgroundTasks,
    user_id: str = Depends(lay_nguoi_dung),
    authorization: str | None = Header(None),
):
    token = (authorization or "")[7:].strip()
    return _xu_ly_chat(req, nen, user_id, token, "APP", user_id, _HO_SO_KHACH.get(user_id))


@app.get("/chat/updates")
def chat_updates(after: str | None = None, tep: int = 0, user_id: str = Depends(lay_nguoi_dung)):
    # `tep=1`: app biết hiện ảnh/PDF nên nhận `attachment` riêng. Bản app cũ (không gửi) nhận link ngay trong chữ để vẫn mở được.
    return _lay_tin_nhan_vien("APP", user_id, after, ho_tro_tep=bool(tep))


def _bay_gio_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _moc_muon_hon(after: str, moc_som_nhat: str) -> str:
    """Không cho đọc trước `moc_som_nhat`. `after` do client gửi nên có thể sai định dạng hoặc cố tình lùi về quá khứ."""
    try:
        return after if datetime.fromisoformat(after) > datetime.fromisoformat(moc_som_nhat) else moc_som_nhat
    except (ValueError, TypeError):
        return moc_som_nhat


def _lay_tin_nhan_vien(kenh: str, ma_ngoai: str, after: str | None, moc_som_nhat: str | None = None, ho_tro_tep: bool = True) -> dict:
    """Tin nhân viên gửi sau mốc `after`. Chưa có mốc (thiết bị mới) thì lấy mốc bây giờ để KHÔNG đọc tin cũ của khách.
    Client lưu `cursor` trả về rồi gửi lại ở lần sau, nhờ vậy không phụ thuộc đồng hồ của điện thoại."""
    moc = after or _bay_gio_iso()
    if moc_som_nhat:
        moc = _moc_muon_hon(moc, moc_som_nhat)
    kq = admin_chat.updates(kenh, ma_ngoai, moc)
    if not kq:
        return {"che_do": "BOT", "items": [], "cursor": moc}
    items = []
    for t in kq.get("items", []):
        muc = {"id": t["id"], "text": t["text"], "at": t["createdAt"]}
        tep = t.get("attachment")
        if tep:
            url = admin_chat.link_tep(tep["url"])
            if ho_tro_tep:
                muc["attachment"] = {"url": url, "type": tep["type"], "name": tep["name"], "size": tep["size"]}
            else:
                loai = "tệp PDF" if tep["type"] == "application/pdf" else "ảnh"
                dong_moi = "\n" if muc["text"] else ""
                muc["text"] = f"{muc['text']}{dong_moi}[Nhân viên gửi {loai}: {url}]"
        items.append(muc)
    return {"che_do": kq.get("mode", "BOT"), "items": items, "cursor": items[-1]["at"] if items else moc}


# ---------------------------------------------------------------- Khách gửi ảnh / PDF cho nhân viên
GIOI_HAN_BYTE_TEP = 20 * 1024 * 1024  # theo giới hạn lớn nhất của trang quản trị (PDF 20 MB); loại file và dung lượng từng loại do backend kiểm tra
GIOI_HAN_CHU_KEM_TEP = 500
TRA_LOI_KHI_NHAN_ANH = (
    "Mình đã nhận được file của bạn và chuyển cho nhân viên. Mình chưa xem được ảnh nên bạn nhắn thêm bằng chữ nội dung cần hỗ trợ, "
    "hoặc gõ \"gặp nhân viên\" để nhân viên trả lời bạn trực tiếp nhé. Bạn lưu ý không gửi ảnh giấy tờ tuỳ thân (CCCD, hộ chiếu) nếu chưa cần thiết."
)
KHONG_GUI_DUOC_TEP = "Hiện chưa gửi được ảnh hoặc file, bạn thử lại sau ít phút nhé."


_LUOT_TEP: dict[str, deque] = {}
_KHOA_LUOT_TEP = threading.Lock()


def _gioi_han_tep(khoa: str) -> str | None:
    """Tối đa 4 file mỗi phút, 30 mỗi giờ, 100 mỗi ngày cho mỗi khách. Đếm trong bộ nhớ: kiem_tra_rate_limit đếm theo bảng tin chữ nên không dùng được."""
    bay_gio = time.monotonic()
    with _KHOA_LUOT_TEP:
        if len(_LUOT_TEP) > 5000:
            _LUOT_TEP.clear()
        luot = _LUOT_TEP.setdefault(khoa, deque())
        while luot and bay_gio - luot[0] > 86400:
            luot.popleft()
        trong_phut = sum(1 for t in luot if bay_gio - t <= 60)
        trong_gio = sum(1 for t in luot if bay_gio - t <= 3600)
        if luot and bay_gio - luot[-1] < 3:
            return "Bạn gửi hơi nhanh, đợi vài giây rồi gửi tiếp nhé."
        if trong_phut >= 4:
            return "Bạn gửi file hơi nhiều trong 1 phút, đợi chút rồi gửi tiếp nhé."
        if trong_gio >= 30:
            return "Bạn đã đạt giới hạn số file trong 1 giờ, đợi chút rồi gửi tiếp nhé."
        if len(luot) >= 100:
            return "Bạn đã đạt giới hạn số file trong hôm nay, hẹn gặp lại bạn vào ngày mai nhé."
        luot.append(bay_gio)
    return None


async def _nhan_tep(file: UploadFile, message: str, nen: BackgroundTasks, kenh: str, ma_ngoai: str, khoa_gioi_han: str, khach: dict | None):
    """Khách gửi ảnh hoặc PDF: chuyển cho trang quản trị (kiểm tra loại file theo nội dung, thu nhỏ, lưu Storage).
    Bot không xem được ảnh: ở chế độ bot thì trả lời cố định; nhân viên đang xử lý thì im lặng như tin chữ."""
    # Giới hạn riêng cho file, chặt hơn tin chữ: mỗi file tốn dung lượng lưu trữ.
    ly_do = _gioi_han_tep(khoa_gioi_han)
    if ly_do:
        return JSONResponse({"code": "QUA_NHANH", "message": ly_do}, status_code=429)
    du_lieu = await file.read(GIOI_HAN_BYTE_TEP + 1)
    if len(du_lieu) > GIOI_HAN_BYTE_TEP:
        return JSONResponse({"code": "TEP_QUA_LON", "message": "File quá lớn, ảnh tối đa 10 MB và PDF tối đa 20 MB."}, status_code=413)
    if not du_lieu:
        return JSONResponse({"code": "TEP_TRONG", "message": "File trống, bạn chọn lại giúp mình nhé."}, status_code=400)

    chu_kem = che_giay_to(unicodedata.normalize("NFC", message or "")).strip()[:GIOI_HAN_CHU_KEM_TEP]
    if chu_kem and co_noi_dung_nhay_cam(chu_kem):
        chu_kem = ""  # Không chuyển chữ nhạy cảm; file vẫn tới nhân viên.
    doi_nguoi = bool(chu_kem) and hoi_muon_gap_nhan_vien(chu_kem)
    res = admin_chat.inbound_file(kenh, ma_ngoai, chu_kem, khach, du_lieu, (file.filename or "tep")[:200], file.content_type or "application/octet-stream", admin_chat.ma_tin_moi())
    if res is None or res.status_code >= 500:
        return JSONResponse({"code": "KHONG_GUI_DUOC", "message": KHONG_GUI_DUOC_TEP}, status_code=503)
    if res.status_code == 400:
        try:
            noi_dung = res.json().get("message")
        except ValueError:
            noi_dung = None
        return JSONResponse({"code": "TEP_KHONG_HOP_LE", "message": noi_dung if isinstance(noi_dung, str) else "File này chưa gửi được, bạn thử ảnh hoặc PDF khác nhé."}, status_code=400)
    if not res.is_success:
        return JSONResponse({"code": "KHONG_GUI_DUOC", "message": KHONG_GUI_DUOC_TEP}, status_code=503)

    ket_qua = res.json()
    hanh_dong = ket_qua.get("action")
    if hanh_dong == "STAFF":
        return {"reply": "", "tours": [], "goi_y": [], "che_do": "STAFF"}
    if hanh_dong in ("AUTO_REPLY", "CONTACT") and ket_qua.get("reply"):
        return {"reply": ket_qua["reply"], "tours": [], "goi_y": []}
    if doi_nguoi:
        return {"reply": TRA_LOI_KHI_NHAN_ANH, "tours": [], "goi_y": []}
    nen.add_task(admin_chat.bot_reply, kenh, ma_ngoai, TRA_LOI_KHI_NHAN_ANH, None, None, khach)
    return {"reply": TRA_LOI_KHI_NHAN_ANH, "tours": [], "goi_y": []}


@app.post("/chat/attachment")
async def chat_attachment(
    nen: BackgroundTasks,
    file: UploadFile = File(...),
    message: str = Form(""),
    user_id: str = Depends(lay_nguoi_dung),
):
    return await _nhan_tep(file, message, nen, "APP", user_id, user_id, _HO_SO_KHACH.get(user_id))


# ---------------------------------------------------------------- Khách web, không đăng nhập
# API công khai nên phải tự giới hạn theo IP: mã thiết bị do trình duyệt tự sinh, đổi mã là né được giới hạn theo khách.
GIOI_HAN_IP_MOI_PHUT = {"chat": 20, "identify": 10, "updates": 240}
_LUOT_THEO_IP: dict[str, deque] = {}
_KHOA_LUOT_IP = threading.Lock()
_MAY_NOI_BO = {"127.0.0.1", "::1", "localhost"}
CAN_THONG_TIN_KHACH = "Bạn cho mình xin họ tên và số điện thoại để thuận tiện cho việc tư vấn và liên hệ nhé."
_MAU_SDT_VN = re.compile(r"^(?:\+?84|0)\d{9}$")


def _ip_khach(request: Request) -> str:
    host = request.client.host if request.client else ""
    # Chỉ tin header của Cloudflare khi kết nối đến từ chính máy này (cloudflared chạy cùng máy); kết nối thẳng thì tự giả được.
    return (request.headers.get("cf-connecting-ip") or host) if host in _MAY_NOI_BO else host


def _kiem_tra_gioi_han_ip(request: Request, loai: str) -> None:
    khoa = f"{loai}:{_ip_khach(request)}"
    bay_gio = time.monotonic()
    with _KHOA_LUOT_IP:
        if len(_LUOT_THEO_IP) > 5000:
            _LUOT_THEO_IP.clear()
        luot = _LUOT_THEO_IP.setdefault(khoa, deque())
        while luot and bay_gio - luot[0] > 60:
            luot.popleft()
        if len(luot) >= GIOI_HAN_IP_MOI_PHUT[loai]:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Bạn thao tác hơi nhanh, thử lại sau ít phút nhé.")
        luot.append(bay_gio)


def _kiem_tra_ma_thiet_bi(v: str) -> str:
    try:
        uuid.UUID(v)
    except (ValueError, AttributeError, TypeError):
        raise ValueError("device_id phải là chuỗi UUID hợp lệ")
    return v


class WebIdentifyRequest(BaseModel):
    device_id: str
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=30)

    _kiem_tra_thiet_bi = field_validator("device_id")(_kiem_tra_ma_thiet_bi)


class WebChatRequest(ChatRequest):
    device_id: str

    _kiem_tra_thiet_bi = field_validator("device_id")(_kiem_tra_ma_thiet_bi)


@app.post("/web/identify")
def web_identify(req: WebIdentifyRequest, request: Request):
    _kiem_tra_gioi_han_ip(request, "identify")
    ten = " ".join(unicodedata.normalize("NFC", req.name).split())
    sdt = re.sub(r"[^\d+]", "", req.phone)
    if not ten:
        return JSONResponse({"code": "INVALID_NAME", "message": CAN_THONG_TIN_KHACH}, status_code=400)
    if not _MAU_SDT_VN.match(sdt):
        return JSONResponse({"code": "INVALID_PHONE", "message": "Số điện thoại chưa đúng, bạn kiểm tra lại giúp mình nhé."}, status_code=400)

    tra_ve = {"returning": False, "load_history": False}
    res = admin_chat.identify("WEB", req.device_id, ten, sdt)
    if res is not None and res.is_success:
        data = res.json()
    elif res is not None and res.status_code < 500:
        # Chỉ chuyển lỗi có mã nghiệp vụ (số sai, tên không khớp), không để lộ chi tiết kỹ thuật khác.
        data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
        if data.get("code") in ("INVALID_PHONE", "NAME_MISMATCH"):
            return JSONResponse({"code": data["code"], "message": data.get("message", "")}, status_code=res.status_code)
        return JSONResponse({"code": "UNAVAILABLE", "message": "Hệ thống đang bận, bạn thử lại sau ít phút nhé."}, status_code=503)
    elif admin_chat.da_cau_hinh() or lich_su_db.da_cau_hinh():
        # Backend trang quản trị không chạy: vẫn nhận khách, ghi thẳng vào database cùng quy tắc tên + SĐT.
        data = lich_su_db.dinh_danh("WEB", req.device_id, ten, sdt)
        if data is None:
            return JSONResponse({"code": "UNAVAILABLE", "message": "Hệ thống đang bận, bạn thử lại sau ít phút nhé."}, status_code=503)
        if data.get("code"):
            return JSONResponse({"code": data["code"], "message": data["message"]}, status_code=409)
    else:
        data = {}  # Chạy độc lập, không có trang quản trị.
    tra_ve = {"returning": bool(data.get("returning")), "load_history": bool(data.get("loadHistory"))}

    # Chỉ đúng thiết bị cũ mới giữ mốc đang có. Thiết bị mới, kể cả nhập trùng số của khách cũ, chỉ đọc từ bây giờ trở đi.
    luu_khach_web(req.device_id, ten, sdt, None if tra_ve["load_history"] else _bay_gio_iso())
    return tra_ve


@app.post("/web/chat")
def web_chat(req: WebChatRequest, nen: BackgroundTasks, request: Request):
    _kiem_tra_gioi_han_ip(request, "chat")
    khach = lay_khach_web(req.device_id)
    if not khach:
        # Khoá ở máy chủ, không chỉ ẩn ô nhập trên trang: chưa có tên + SĐT thì không giải đáp, không gọi AI.
        return JSONResponse({"code": "CAN_THONG_TIN", "message": CAN_THONG_TIN_KHACH}, status_code=403)
    # Không có dấu ":" trong mã: kiem_tra_rate_limit tách theo ":" nên "web:..." sẽ gộp mọi khách web làm một.
    return _xu_ly_chat(req, nen, f"web-{req.device_id}", "", "WEB", req.device_id, khach)


@app.post("/web/attachment")
async def web_attachment(
    request: Request,
    nen: BackgroundTasks,
    file: UploadFile = File(...),
    device_id: str = Form(...),
    message: str = Form(""),
):
    _kiem_tra_gioi_han_ip(request, "chat")
    try:
        _kiem_tra_ma_thiet_bi(device_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="device_id không hợp lệ")
    khach = lay_khach_web(device_id)
    if not khach:
        return JSONResponse({"code": "CAN_THONG_TIN", "message": CAN_THONG_TIN_KHACH}, status_code=403)
    return await _nhan_tep(file, message, nen, "WEB", device_id, f"web-{device_id}", khach)


@app.get("/web/updates")
def web_updates(device_id: str, request: Request, after: str | None = None):
    _kiem_tra_gioi_han_ip(request, "updates")
    try:
        _kiem_tra_ma_thiet_bi(device_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="device_id không hợp lệ")
    moc_som_nhat = lay_moc_doc_web(device_id)
    if not moc_som_nhat:
        # Thiết bị chưa để lại tên + SĐT thì không có gì để đọc, cũng không cần hỏi trang quản trị.
        return {"che_do": "BOT", "items": [], "cursor": after}
    return _lay_tin_nhan_vien("WEB", device_id, after, moc_som_nhat)


def _gio_vn(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=7))).strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return ""


def ghi_chu_nhan_vien(kenh: str, ma_ngoai: str, session_key: str) -> str | None:
    """Các tin nhân viên thật đã nhắn khách (tối đa 8, mỗi tin tối đa 500 ký tự) để đưa cho AI. Lỗi gì cũng bỏ qua: thiếu phần này AI vẫn trả lời được."""
    try:
        tin = admin_chat.tin_nhan_vien_gan_day(kenh, ma_ngoai, moc_lich_su_cu_nhat(session_key, MAX_HISTORY_TURNS))
        if not tin:
            return None
        dong = []
        for t in tin[-8:]:
            chu = (t.get("text") or "").strip()[:500]
            tep = f" [đính kèm {t.get('attachmentName') or 'tệp'}]" if t.get("attachmentType") else ""
            dong.append(f"- {_gio_vn(t.get('createdAt'))} Nhân viên: {chu}{tep}".replace("  ", " ").rstrip())
        return chr(10).join(dong)
    except Exception:
        return None


def _xu_ly_chat(
    req: ChatRequest,
    nen: BackgroundTasks,
    user_id: str,
    token: str,
    kenh: str,
    ma_ngoai: str,
    khach: dict | None,
):
    don_tin_nhan_cu_3_ngay()

    # [GEMINI] T-003: Khoá session nội bộ f"{user_id}:{conversation_id}"
    session_key = f"{user_id}:{req.conversation_id}"

    # Bàn phím tiếng Việt trên iPhone/macOS có thể gửi chữ dạng tổ hợp (NFD: chữ + dấu rời) -> đưa về dạng dựng sẵn (NFC)
    # để đếm độ dài, kiểm duyệt, so từ khoá đều thấy đúng chữ khách gõ.
    req.message = che_giay_to(unicodedata.normalize("NFC", req.message))

    # Tin rỗng / quá dài: trả lời ngay, không tính vào giới hạn, không gọi AI.
    if not req.action:
        if not req.message.strip():
            return {"reply": "Bạn muốn hỏi gì về tour ạ? Bạn gõ câu hỏi giúp mình nhé.", "tours": [], "goi_y": []}
        if len(req.message) > DO_DAI_TIN_NHAN_TOI_DA:
            return {"reply": f"Câu hỏi hơi dài (tối đa {DO_DAI_TIN_NHAN_TOI_DA} ký tự). Bạn tóm gọn lại giúp mình nhé.", "tours": [], "goi_y": []}

    # Rate limit tính theo user_id (không theo từng cuộc trò chuyện)
    # Bấm nút trong luồng đặt tour không tính vào giới hạn số câu hỏi (không gọi AI, không lưu tin nhắn).
    # Đang đặt tour dở: khách gõ chữ trả lời từng bước (không gọi AI) nên CHƯA áp giới hạn theo phút ở đây;
    # câu nào luồng đặt không nhận mà rơi sang chat thường (gọi AI) thì bị kiểm tra đủ ở bên dưới.
    mang_xa_hoi = kenh in KENH_MANG_XA_HOI
    dang_dat_do = not req.action and not mang_xa_hoi and dat_tour.dang_dat_do(session_key)
    ly_do_bi_chan = None if req.action else kiem_tra_rate_limit(
        user_id,
        float("inf") if dang_dat_do else RATE_LIMIT_PER_MINUTE,
        RATE_LIMIT_PER_HOUR, RATE_LIMIT_PER_DAY, MIN_GIAY_GIUA_2_CAU_HOI,
    )
    # Giới hạn để chặn spam và tiết kiệm AI. Nhân viên đang xử lý thì tin của khách phải tới được nhân viên, nên chỉ khi chạm giới hạn
    # mới hỏi trạng thái (không tốn thêm lời gọi cho tin bình thường). Khách web vẫn còn giới hạn theo IP ở /web/chat.
    vuot_gioi_han = ly_do_bi_chan
    if vuot_gioi_han and not admin_chat.nhan_vien_dang_xu_ly(kenh, ma_ngoai):
        return {"reply": ly_do_bi_chan, "tours": [], "goi_y": []}

    luc_khach_gui = lich_su_db.bay_gio()

    if not req.action and co_noi_dung_nhay_cam(req.message):
        # Vẫn lưu để nhân viên đọc lại được khi cần (khiếu nại...), nhưng không báo nhân viên và không đưa vào ngữ cảnh của AI.
        nen.add_task(admin_chat.ghi_lich_su, kenh, ma_ngoai, khach, [
            {"loai": "CUSTOMER", "text": req.message, "luc": luc_khach_gui, "ma_tin": admin_chat.ma_tin_moi()},
            {"loai": "BOT", "text": TRA_LOI_KHI_BI_CHAN, "luc": luc_khach_gui + timedelta(milliseconds=1), "ma_tin": admin_chat.ma_tin_moi()},
        ])
        return {"reply": TRA_LOI_KHI_BI_CHAN, "tours": [], "goi_y": []}

    # Khách web không có luồng nút bấm: không ghi, để API công khai không bị dùng để nhét dữ liệu vào database.
    if req.action and token:
        chu_tren_nut = (req.action.label or "").strip() or f"[Khách bấm nút {req.action.id[:100]}]"
        nen.add_task(admin_chat.ghi_lich_su, kenh, ma_ngoai, khach, [
            {"loai": "CUSTOMER", "text": chu_tren_nut, "luc": luc_khach_gui, "ma_tin": admin_chat.ma_tin_moi()},
        ])

    # Báo tin khách cho trang quản trị TRƯỚC khi trả lời: nhân viên đang xử lý thì bot im, khách đòi gặp người thì báo nhân viên.
    # Backend không trả lời thì None: bot vẫn trả lời khách như thường, còn câu của khách được ghi thẳng vào database ngay.
    # Tin có số điện thoại mà còn hỏi chuyện khác: vẫn báo nhân viên, nhưng AI trả lời câu hỏi rồi nối câu "đã báo nhân viên" ở cuối.
    cau_bao_nhan_vien = None  # câu "đã báo nhân viên" sẽ nối vào cuối câu AI trả lời
    da_ghi_cau_bao = False  # backend đã tự lưu câu đó vào hội thoại thì không ghi lại lần nữa
    if not req.action:
        doi_nguoi = hoi_muon_gap_nhan_vien(req.message)
        # Chưa tính khi đang đặt tour dở (khách gõ SĐT là trả lời bước của luồng đặt). Khách có sẵn SĐT (web, app) không bao giờ rơi vào ca "SDT".
        ly_do_som = None if (doi_nguoi or dang_dat_do) else can_nhan_vien_som(req.message, bool((khach or {}).get("phone")))
        if not doi_nguoi and not ly_do_som and mang_xa_hoi and _muon_dat_tour(req.message):
            ly_do_som = "DAT_TOUR"
        if not doi_nguoi and not ly_do_som and not dang_dat_do and hoi_ngay_khoi_hanh_sat(req.message):
            ly_do_som = "NGAY_SAT"
        ai_van_tra_loi = ly_do_som == "SDT" and co_cau_hoi_ngoai_sdt(req.message)
        bao_nhan_vien = doi_nguoi or bool(ly_do_som)
        ma_tin_khach = admin_chat.ma_tin_moi()
        tu_admin = admin_chat.inbound(kenh, ma_ngoai, req.message, khach, bao_nhan_vien, ma_tin=ma_tin_khach,
                                      cau_bao=TRA_LOI_NHAN_VIEN_SOM[ly_do_som] if ly_do_som in CAU_BAO_RIENG else None)
        if tu_admin is None:
            nen.add_task(admin_chat.ghi_tin_khach_truc_tiep, kenh, ma_ngoai, khach, req.message, luc_khach_gui, ma_tin_khach, bao_nhan_vien)
        hanh_dong = (tu_admin or {}).get("action")
        if hanh_dong == "STAFF":
            luu_tin_nhan(session_key, "user", req.message, user_id=user_id)
            return {"reply": "", "tours": [], "goi_y": [], "che_do": "STAFF"}
        if hanh_dong == "CONTACT" and ai_van_tra_loi and tu_admin.get("reply"):
            cau_bao_nhan_vien, da_ghi_cau_bao = tu_admin["reply"], True
        elif hanh_dong in ("AUTO_REPLY", "CONTACT") and tu_admin.get("reply"):
            luu_tin_nhan(session_key, "user", req.message, user_id=user_id)
            luu_tin_nhan(session_key, "assistant", tu_admin["reply"], user_id=user_id)
            return {"reply": tu_admin["reply"], "tours": [], "goi_y": []}
        if ly_do_som and tu_admin is None and ai_van_tra_loi:
            cau_bao_nhan_vien = TRA_LOI_NHAN_VIEN_SOM[ly_do_som]
        elif ly_do_som and tu_admin is None:
            # Trang quản trị không trả lời: tin đã ghi thẳng database kèm cờ báo nhân viên, trả câu viết sẵn thay vì để AI trả lời lạc đề.
            reply = TRA_LOI_NHAN_VIEN_SOM[ly_do_som]
            luu_tin_nhan(session_key, "user", req.message, user_id=user_id)
            luu_tin_nhan(session_key, "assistant", reply, user_id=user_id)
            nen.add_task(admin_chat.bot_reply, kenh, ma_ngoai, reply, None, None, khach)
            return {"reply": reply, "tours": [], "goi_y": []}
        if vuot_gioi_han:
            # Backend đang tắt, hoặc nhân viên vừa trả khách cho bot: tin đã được lưu ở trên nhưng không gọi AI cho tin vượt giới hạn.
            return {"reply": vuot_gioi_han, "tours": [], "goi_y": []}

    # Luồng ĐẶT TOUR (máy trạng thái, không qua Gemini): xem dat_tour.py. Khách web không có token nên chỉ ghi nhận yêu cầu
    # (nhân viên gọi lại), không tạo đơn thật trên NestJS.
    ket_qua_dat_tour = None if mang_xa_hoi else dat_tour.xu_ly(
        session_key, token, req.message, req.action.model_dump() if req.action else None
    )
    if ket_qua_dat_tour is not None:
        don = ket_qua_dat_tour.pop("_don", None)
        if ket_qua_dat_tour.pop("_khong_ghi", False):
            return ket_qua_dat_tour
        if not req.action:
            luu_tin_nhan(session_key, "user", req.message, user_id=user_id)
            luu_tin_nhan(session_key, "assistant", ket_qua_dat_tour["reply"], user_id=user_id)
        nen.add_task(admin_chat.bot_reply, kenh, ma_ngoai, ket_qua_dat_tour["reply"], ket_qua_dat_tour.get("tours"), None, khach)
        if don:
            nen.add_task(admin_chat.deal, kenh, ma_ngoai, don, khach)
        return ket_qua_dat_tour
    if req.action:
        return {"reply": "Mình chưa hiểu thao tác này. Bạn nhắn lại giúp mình nhé.", "tours": [], "goi_y": []}

    if dang_dat_do:
        # Câu này luồng đặt tour không nhận (khách hỏi câu khác giữa chừng) -> sẽ gọi AI nên áp đủ giới hạn như chat thường.
        ly_do_bi_chan = kiem_tra_rate_limit(
            user_id, RATE_LIMIT_PER_MINUTE, RATE_LIMIT_PER_HOUR, RATE_LIMIT_PER_DAY, MIN_GIAY_GIUA_2_CAU_HOI
        )
        if ly_do_bi_chan:
            return {"reply": ly_do_bi_chan, "tours": [], "goi_y": []}

    # Câu không liên quan du lịch (giải toán, code, tài chính, chính trị, phạm pháp...): trả câu viết sẵn, không gọi AI, không kèm thẻ tour.
    # Đặt sau luồng đặt tour và sau khi đã báo trang quản trị: nhân viên đang xử lý thì đã dừng ở trên, tin vẫn được lưu.
    loai_ngoai_le = None if hoi_muon_gap_nhan_vien(req.message) else ngoai_pham_vi.phan_loai(req.message)
    if loai_ngoai_le:
        reply = ngoai_pham_vi.cau_tra_loi(loai_ngoai_le)
        luu_tin_nhan(session_key, "user", req.message, user_id=user_id)
        luu_tin_nhan(session_key, "assistant", reply, user_id=user_id)
        nen.add_task(admin_chat.bot_reply, kenh, ma_ngoai, reply, None, None, khach)
        return {"reply": reply, "tours": [], "goi_y": []}

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
        nen.add_task(admin_chat.bot_reply, kenh, ma_ngoai, reply, None, None, khach)
        return {
            "reply": reply,
            "tours": [],
            "goi_y": [],
            "handoff": {"zalo_url": ZALO_NHAN_VIEN_URL, "tom_tat": tom_tat},
        }

    con_lai: list[dict] = []
    if _co_cum_tu(req.message.lower(), TU_KHOA_HOI_HOTLINE):
        # Hỏi số tổng đài / hotline: trả số THẬT có sẵn trong rules.py, không để AI tự nghĩ ra số.
        tours, goi_y_lam_ro, reply = [], [], TRA_LOI_HOTLINE
    elif hoi_xem_tiep_tour(req.message) and (con_lai_truoc := dat_tour.doc_tour_con_lai(session_key)) is not None:
        # Xem tiếp danh sách theo dịp lễ: trả từ danh sách đã lưu, không gọi AI nên không tốn quota.
        trang, con_lai = chia_trang_dip(con_lai_truoc)
        dat_tour.ghi_tour_con_lai(session_key, con_lai)
        tours, goi_y_lam_ro = [chuan_hoa_the_tour(t) for t in trang], []
        if trang:
            reply = f"Mình hiện tiếp {len(trang)} tour {trang[0]['ten_dip']} nhé:"
            reply += "\n\n" + (nhac_xem_tiep(con_lai) if con_lai else "Đây là các tour cuối cùng theo dịp bạn hỏi rồi ạ.")
        else:
            reply = "Mình đã hiện hết tour theo dịp bạn hỏi rồi ạ. Bạn muốn xem dịp lễ hay điểm đến nào khác không?"
    else:
        goi_y_gia: dict = {}
        goi_y_gan_dung: dict = {}
        tours_raw = tim_tour_lien_quan(req.message, lich_su=lich_su, goi_y_gia=goi_y_gia, goi_y_gan_dung=goi_y_gan_dung)
        tin_nhan_vien = ghi_chu_nhan_vien(kenh, ma_ngoai, session_key)
        # Câu viết sẵn "chưa có tour X vào ngày/tháng Y" chỉ hiểu một nơi một ngày và không đọc tin nhân viên: nhân viên vừa hỏi khách
        # (câu khách là câu trả lời) hoặc câu nêu nhiều nơi / nhiều ngày thì để AI trả lời với cùng danh sách tour.
        nhan_vien_vua_hoi = bool(tin_nhan_vien) and la_cau_hoi_cua_nhan_vien(tin_nhan_vien.rsplit(chr(10), 1)[-1].split("Nhân viên:", 1)[-1])
        viet_san_duoc = not (nhan_vien_vua_hoi or nhieu_noi_hoac_nhieu_ngay(req.message))
        noi_khong_co = None if tours_raw or goi_y_gia or goi_y_gan_dung or trich_diem_den(req.message) else dia_danh_khong_co_tour(req.message)
        if goi_y_gia:
            tours_raw = goi_y_gia["tours"]
        elif goi_y_gan_dung:
            tours_raw = goi_y_gan_dung["tours"]
        theo_dip = bool(tours_raw and tours_raw[0].get("nhom_dip"))
        tours_raw, con_lai = chia_trang_dip(tours_raw)
        dat_tour.ghi_tour_con_lai(session_key, con_lai if theo_dip else None)
        tours = [chuan_hoa_the_tour(t) for t in tours_raw]
        goi_y_lam_ro = (
            ["Trong nước", "Nước ngoài", "Dưới 10 triệu", "Từ 10-20 triệu", "Có tour nào độc lạ không?"]
            if hoi_tim_tour_thieu_thong_tin(req.message)
            else []
        )

        try:
            # Không có tour trong tầm giá / nơi không có tour: trả lời viết sẵn (không để AI hỏi vòng vo hay bịa giá).
            if goi_y_gia:
                reply = tra_loi_khong_co_trong_tam_gia(goi_y_gia, req.message)
                tours = [chuan_hoa_the_tour(t) for t in goi_y_gia["tours"]]  # thẻ theo đúng thứ tự câu trả lời nêu
            elif noi_khong_co and viet_san_duoc:
                reply = tra_loi_noi_khong_co_tour(noi_khong_co)
            elif goi_y_gan_dung and viet_san_duoc:
                reply = tra_loi_gan_dung(goi_y_gan_dung)
            elif hoi_cach_dat_tour(req.message) and not mang_xa_hoi:
                # Câu viết sẵn dẫn về app, không gọi AI (AI hay bảo khách nhắn "gặp nhân viên" để đặt).
                reply = TRA_LOI_CACH_DAT_TOUR
            else:
                # Dòng phân cách đã hiện sẵn trên thẻ; đưa cho AI thì nó chép lại nguyên văn vào câu trả lời.
                ghi_chu = ghi_chu_kenh(kenh, khach)
                if nhan_vien_vua_hoi:
                    # Bug thật: nhân viên hỏi "rớt visa bao lâu rồi", khách đáp "Đầu tháng 4 e", AI vẫn hiểu là tìm tour tháng 4.
                    ghi_chu = (ghi_chu + chr(10) if ghi_chu else "") + (
                        "Tin nhân viên gần nhất là một CÂU HỎI gửi khách. Câu khách vừa nhắn là câu TRẢ LỜI cho câu hỏi đó, không phải yêu cầu tìm "
                        "tour mới: ghi nhận câu trả lời, đừng nói có hay không có tour theo ngày tháng trong câu."
                    )
                if cau_bao_nhan_vien:
                    # Câu "đã ghi nhận số, đã báo nhân viên" được nối sẵn ở cuối: AI chỉ trả lời câu hỏi, không nhắc lại (bug thật: nói 2 lần).
                    ghi_chu = (ghi_chu + chr(10) if ghi_chu else "") + (
                        "Hệ thống ĐÃ ghi nhận số điện thoại khách và báo nhân viên; câu báo này sẽ được thêm ở cuối. Chỉ trả lời câu hỏi của khách, "
                        "không nhắc lại số điện thoại, không nói đã ghi nhận số hay nhân viên sẽ gọi."
                    )
                # Câu hỏi cọc / huỷ / bao gồm / tip...: đưa chính sách thật của tour khách đang hỏi (API chi tiết tour) cho Gemini.
                chinh_sach = chinh_sach_tour.khoi_chinh_sach(req.message, tours)
                reply = hoi_gemini(req.message, [{k: v for k, v in t.items() if k != "phan_cach_truoc"} for t in tours], lich_su, tin_nhan_vien,
                                   ghi_chu_kenh=ghi_chu, **({"chinh_sach": chinh_sach} if chinh_sach else {}))
        except Exception:
            # AI treo / hết quota / mất mạng: khách vẫn nhận được thẻ tour (đã tìm xong ở trên) thay vì lỗi 500.
            reply = None
        if not reply or not reply.strip():
            reply = TRA_LOI_KHI_AI_LOI_CO_TOUR if tours else TRA_LOI_KHI_AI_LOI
        if theo_dip and hoi_dip_le_chung(req.message):
            reply = f"Dịp lễ gần nhất là {tours_raw[0]['ten_dip'].removeprefix('dịp ')}.\n\n{reply}"
        if con_lai:
            reply += "\n\n" + nhac_xem_tiep(con_lai)
    dat_tour.ghi_tour_gan_nhat(session_key, tours)
    if tours and not goi_y_lam_ro and not mang_xa_hoi:
        goi_y_lam_ro = ["Tôi muốn đặt tour này"]
    if tours and con_lai:
        goi_y_lam_ro = ["Còn tour nào không", *goi_y_lam_ro]

    # Khách hỏi câu khác GIỮA luồng đặt tour: trả lời xong thì nhắc + hiện lại nút của bước đang dở để khách đặt tiếp.
    # Khách đang xem TOUR KHÁC (câu hỏi ra thẻ tour không có tour đang đặt): hỏi 3 hướng thay vì chỉ nhắc đặt tiếp.
    nhac = dat_tour.nhac_buoc_dang_do(session_key, tour_khac=dat_tour.hoi_tour_khac(session_key, tours)) if dang_dat_do else None
    if nhac:
        reply = reply + "\n\n" + nhac.pop("reply")
        goi_y_lam_ro = []

    tra_loi_ghi_lai = reply  # phần bot cần ghi vào trang quản trị
    if cau_bao_nhan_vien:
        reply = reply + "\n\n" + cau_bao_nhan_vien
        if not da_ghi_cau_bao:
            tra_loi_ghi_lai = reply
    luu_tin_nhan(session_key, "user", req.message, user_id=user_id)
    luu_tin_nhan(session_key, "assistant", reply, user_id=user_id)
    # Chạy sau khi đã trả lời khách để khách không phải chờ thêm.
    nen.add_task(admin_chat.bot_reply, kenh, ma_ngoai, tra_loi_ghi_lai, tours, lay_token_cau_vua_hoi(), khach)
    ket_qua = {"reply": reply, "tours": tours, "goi_y": goi_y_lam_ro}
    if nhac:
        ket_qua.update({k: v for k, v in nhac.items() if k in ("choices", "multi", "toi_da")})
    return ket_qua
