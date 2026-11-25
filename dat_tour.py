"""Luồng ĐẶT TOUR qua chatbot (máy trạng thái, KHÔNG để Gemini tự do trả lời).

Chatbot ĐẶT TOUR LUÔN trong khung chat: dẫn khách qua các bước, hiện bảng
tóm tắt để khách soát lại, khách bấm "Đồng ý" thì gọi thẳng NestJS
`POST /api/v1/bookings` rồi trả về `booking` (mã đơn + đường dẫn tới trang
trạng thái đơn) để app mở. Không đưa khách sang trang booking nữa.

Các bước (state["step"]):
  chon_tour -> chon_ngay -> so_nguoi -> chon_nguoi -> xac_nhan -> (khong_dong_y -> quay lại bước tương ứng)

Dữ liệu ngày khởi hành / giá / số chỗ lấy TRỰC TIẾP từ benthanhtourist.com lúc đó
(dữ liệu Chroma của chatbot có thể cũ).
Thân nhân lấy từ NestJS GET /api/v1/relatives bằng chính token của khách.
Không bao giờ thu CCCD / hộ chiếu / visa trong chat: backend đã bỏ bắt buộc
thông tin hành khách, họ tên / email / SĐT lấy sẵn từ tài khoản theo token.
"""
import json
import re
from datetime import date, datetime

import httpx

from config import BENTHANH_API_BASE, BENTHANH_HEADERS, NESTJS_BASE_URL
from database import ket_noi
import rag
from rag import bo_dau, hoi_muon_gap_nhan_vien, tim_tour_lien_quan, trich_diem_den

TRANG_THAI_HET_HAN_PHUT = 120
GIA_TRE_EM = 0.8
GIA_EM_BE = 0.4
TOI_DA_KHACH = 20
# [TẠM TẮT 2026-10-14 — chủ dự án chưa cần nhân thân/CCCD/hộ chiếu] False = bỏ bước "người đi cùng" (không gọi
# NestJS /relatives, không hỏi chọn thân nhân, không nhắc hộ chiếu/visa); True = bật lại như cũ.
DUNG_THAN_NHAN = False


# ---------------------------------------------------------------- lưu trạng thái
def _khoi_tao():
    with ket_noi() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS booking_state (
                   session_id TEXT PRIMARY KEY,
                   state TEXT NOT NULL,
                   updated_at TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )


_khoi_tao()


def _doc(session_key: str) -> dict | None:
    with ket_noi() as conn:
        row = conn.execute(
            "SELECT state FROM booking_state WHERE session_id = ? AND updated_at >= datetime('now', ?)",
            (session_key, f"-{TRANG_THAI_HET_HAN_PHUT} minutes"),
        ).fetchone()
    if not row:
        return None
    # Trạng thái hỏng (JSON lỗi / không phải object) -> coi như không có phiên, không được làm sập chat.
    try:
        st = json.loads(row[0])
    except (ValueError, TypeError):
        return None
    return st if isinstance(st, dict) else None


def dang_dat_do(session_key: str) -> bool:
    """Khách đang ở giữa luồng đặt tour (main.py dùng để không áp giới hạn theo phút cho câu trả lời từng bước)."""
    return bool((_doc(session_key) or {}).get("step"))


def _ghi(session_key: str, st: dict):
    with ket_noi() as conn:
        conn.execute(
            "INSERT INTO booking_state (session_id, state, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(session_id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
            (session_key, json.dumps(st, ensure_ascii=False)),
        )


def xoa_trang_thai(session_key: str):
    with ket_noi() as conn:
        conn.execute("DELETE FROM booking_state WHERE session_id = ?", (session_key,))


def _ket_thuc_luong(session_key: str, st: dict):
    """Kết thúc luồng (đồng ý / huỷ / lỗi) nhưng vẫn nhớ các tour vừa gợi ý, để khách nói lại "đặt tour này" được."""
    last = st.get("last_tours") or []
    if last and isinstance(last, list):
        _ghi(session_key, {"step": None, "last_tours": last})
    else:
        xoa_trang_thai(session_key)


# Đủ để "tour thứ 7" vẫn hiểu được khi hỏi theo dịp lễ (danh sách không cắt ở 5 thẻ); nút bấm vẫn chỉ hiện 5 tour đầu.
_SO_TOUR_GAN_NHAT_TOI_DA = 30


def ghi_tour_gan_nhat(session_key: str, tours: list[dict]):
    """Nhớ các tour vừa gợi ý để câu "đặt tour này" hiểu được. Không đụng vào luồng đang chạy."""
    if not tours:
        return
    st = _doc(session_key) or {"step": None}
    st["last_tours"] = [{"key": str(t["tour_key"]), "ten": str(t.get("ten") or "")} for t in tours if t.get("tour_key")][:_SO_TOUR_GAN_NHAT_TOI_DA]
    _ghi(session_key, st)


def doc_tour_con_lai(session_key: str) -> list[dict] | None:
    """Danh sách tour dịp lễ chưa hiện. None = lượt tìm gần nhất không theo dịp lễ; [] = đã hiện hết."""
    return (_doc(session_key) or {}).get("tour_con_lai")


def ghi_tour_con_lai(session_key: str, tours: list[dict] | None):
    """Lượt tìm tour mới luôn ghi đè, để "còn tour nào không" chỉ tiếp nối đúng danh sách vừa hiện."""
    st = _doc(session_key)
    if tours is None:
        if st and "tour_con_lai" in st:
            del st["tour_con_lai"]
            _ghi(session_key, st)
        return
    st = st or {"step": None}
    st["tour_con_lai"] = tours
    _ghi(session_key, st)


def khach_web(session_key: str) -> bool:
    """Khách trang web chat: chỉ có tên + SĐT, KHÔNG có tài khoản NestJS nên không tạo được đơn thật và không có thân nhân.
    main.py đặt mã người dùng web là "web-<mã thiết bị>"; mã tài khoản app không bao giờ bắt đầu như vậy."""
    return session_key.startswith("web-")


# ---------------------------------------------------------------- nhận diện câu lệnh
_DONG_Y = re.compile(r"\b(dong y|ok|oke|okay|duoc|dung roi|chot|vang|u|yes|xac nhan|chuan)\b")
_KHONG = re.compile(r"\b(khong|sai|doi|chua|no|khong dong y)\b")
# "thôi" KHÔNG nằm trong _HUY: "2 người lớn thôi", "chỉ 2 người thôi" là câu trả lời, không phải huỷ.
# Chỉ coi là huỷ khi cả câu gần như chỉ có chữ "thôi" (xem _muon_huy).
_HUY = re.compile(r"\b(huy|bo qua dat|khong dat nua|khong dat tour nua|khong di nua|dung lai|cancel)\b")
_THOI_HUY = re.compile(r"^thoi( (khoi|nhe|nha|a|ban|vay|khong can|khong dat|de sau|de khi khac))*$")
_BO_QUA = re.compile(r"\b(khong|bo qua|mot minh|di mot minh|nhap sau|de sau|thoi)\b")
# Nói RÕ là bỏ qua (xét trước khi dò tên); "không"/"thôi" đứng chung với tên ("đi với Lan thôi") thì tên thắng.
_BO_QUA_RO = re.compile(r"\b(bo qua|mot minh|nhap sau|de sau)\b")
_HOI_CHINH_SACH = re.compile(r"\b(coc|huy tour|hoan|chinh sach|thanh toan|bao lau|the nao|lam sao|huong dan|cach|bao nhieu tien coc)\b")
_CHUA_MUON_DAT = re.compile(r"\b(chua|khong|dung|khoi|chang) (muon |can |dinh |co y dinh )?(dat|book|dang ky)\b")
_DAT = re.compile(r"\b(dat|book|booking|dang ky|dang ki|chot|giu cho)\b")
# Khách kể chuyện tour ĐÃ đặt (hỏi xác nhận, khiếu nại…) -> không phải muốn đặt mới.
_DA_DAT = re.compile(r"\b(da dat|dat roi|vua dat|dat hom|da book|book roi|da dang ky)\b")
# Từ chỉ "tour vừa được gợi ý" (đầu tiên / thứ 2 xử lý riêng ở _thu_tu)
_CHI_TOUR_VUA_GOI_Y = re.compile(r"\b(nay|do|vua roi|tren|kia|ay)\b")
# Đang đặt dở mà nói "đổi lịch khởi hành", "đổi ngày", "chọn lại ngày", "ngày khác" -> đổi ngày của ĐƠN ĐANG ĐẶT
# (khách đã đặt xong rồi muốn đổi lịch thì không còn phiên đặt -> vẫn chuyển nhân viên).
_DOI_NGAY = re.compile(r"\b(doi|chon|lay) (lai |sang |qua )?(ngay|lich)\b|\b(ngay|lich) (khoi hanh )?khac\b")
# Câu hỏi: có dấu "?" hoặc có từ để hỏi / kết thúc bằng từ để hỏi (không tính các từ đệm cuối câu).
_TU_HOI = re.compile(r"\b(bao nhieu|the nao|ra sao|tai sao|vi sao|la gi|khi nao|bao gio|bao lau|o dau|may gio)\b")
_DUOI_HOI = ("khong", "ko", "hong", "chua", "chu", "sao", "nhi", "ha")
_TU_DEM_CUOI = {"ban", "a", "vay", "the", "shop", "ad", "admin", "em", "anh", "chi", "oi", "nha", "nhe"}
# "thì không", "chắc là chưa"… là câu TRẢ LỜI, không phải câu hỏi
_TRUOC_DUOI_KHONG_HOI = {"la", "thi", "chac", "da", "vang", "thoi", "o", "u", "van", "cung"}


def _nd(text: str) -> str:
    return bo_dau(text.lower())


def _chuan(text: str) -> str:
    """Không dấu, chữ thường, bỏ mọi ký tự không phải chữ/số — để so tên tour với câu khách gõ."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _nd(text))).strip()


def _la_cau_hoi(message: str) -> bool:
    """Khách đang HỎI (vd "visa có khó không?", "giá này đã gồm vé máy bay chưa") chứ không trả lời bước đang dở."""
    if "?" in message:
        return True
    nd = _chuan(message)
    tu = nd.split()
    if len(tu) < 3:
        return False  # "không", "được chứ", "chưa đúng" là câu trả lời
    if _TU_HOI.search(nd):
        return True
    while len(tu) > 2 and tu[-1] in _TU_DEM_CUOI:
        tu.pop()
    if tu[-1] not in _DUOI_HOI:
        return False
    return not (tu[-1] in ("khong", "ko", "hong", "chua") and tu[-2] in _TRUOC_DUOI_KHONG_HOI)


# Muốn đặt mà KHÔNG nói chữ "tour": "đặt chỗ đi Nga", "đặt vé đi Đà Lạt", "giữ chỗ giúp tôi", "mình lấy tour này".
_DAT_KHONG_CHU_TOUR = re.compile(r"\b(dat cho|dat ve|giu cho|book ve)\b")
_LAY_TOUR = re.compile(r"\blay tour\b")
_VE_KHAC = re.compile(r"\b(may bay|ve xe|ve tau|khach san|phong|ve vao cong|ve xem|ve concert|ve cau)\b")
# Khách chỉ HỎI chứ chưa muốn đặt tour (đánh giá 160 câu 2026-11-23): "muốn hỏi thêm tour Nha Trang, hỏi được ko" hay "đặt giùm khách sạn,
# ko đi tour" bị mở nhầm luồng đặt tour.
_HOI_THEM = re.compile(r"\b(muon hoi|hoi them|hoi duoc (ko|khong|k)|hoi (dc|duoc) (ko|khong|k))\b")
_KHONG_DI_TOUR = re.compile(r"\b(khong|ko|k|chang)\s+(di|mua|dat|di theo)\s+tour\b")
# Câu hỏi thông tin / quyền lợi có nhắc "đăng ký/đặt tour" ("đăng ký tour thì cần lưu ý gì về visa?", "đặt tiếp có ưu đãi thân thiết không?").
_HOI_THONG_TIN = re.compile(
    r"\b(luu y|can gi|can nhung gi|giay to|ho so|visa|ho chieu|uu dai|giam gia|khuyen mai|ma giam|than thiet|bao hiem|phu thu|hoa don|vat)\b"
)


def _chi_hoi_khong_dat(message: str, nd: str) -> bool:
    if _HOI_THEM.search(nd) or _KHONG_DI_TOUR.search(nd):
        return True
    if _la_cau_hoi(message):
        # Câu hỏi có nhắc vé máy bay / khách sạn / giấy tờ / ưu đãi: là hỏi thông tin, bấm "Tôi muốn đặt tour này" sau khi được trả lời.
        return bool(_VE_KHAC.search(nd) or _HOI_THONG_TIN.search(nd))
    return False


def hoi_dat_tour(message: str) -> bool:
    nd = _nd(message)
    if "tour" in nd:
        if not (_DAT.search(nd) or _LAY_TOUR.search(nd)):
            return False
    elif not _DAT_KHONG_CHU_TOUR.search(nd) or _VE_KHAC.search(nd):
        return False
    if _DA_DAT.search(nd):
        return False
    if _CHUA_MUON_DAT.search(nd):
        return False  # "chưa muốn đặt tour đâu, chỉ hỏi giá" -> chỉ hỏi, không mở luồng đặt
    # "đặt cọc thế nào", "huỷ tour được không", "làm sao để đặt" -> câu hỏi chính sách, để Gemini trả lời
    # "các bước đặt tour", "đặt tour ở đâu" -> hỏi cách đặt, không phải muốn đặt ngay
    return not (_HOI_CHINH_SACH.search(nd) or rag.la_cau_hoi_cach_dat(message) or _chi_hoi_khong_dat(message, nd))


_DANG_KY_LUON = re.compile(r"\b(dang ky|dang ki|book|giu cho|chot)\b")
_QUEN_DANG_KY = re.compile(r"\bquen (dang|book|chot|giu)\b")


def muon_dang_ky(message: str) -> bool:
    """Khách nói muốn đăng ký / book / giữ chỗ / chốt dù không có chữ "tour" ("nếu phù hợp thì hôm nay chị đăng ký luôn"). Dùng cho
    Zalo/Facebook để báo nhân viên; không tính câu hỏi chính sách, chuyện đã đặt, chưa muốn đặt, hay "quên đăng ký"."""
    nd = _nd(message)
    if not _DANG_KY_LUON.search(nd):
        return False
    return not (_DA_DAT.search(nd) or _CHUA_MUON_DAT.search(nd) or _HOI_CHINH_SACH.search(nd) or _QUEN_DANG_KY.search(nd) or _VE_KHAC.search(nd))


# "chốt", "đặt luôn", "ok chốt đi", "giữ chỗ giúp mình" — muốn đặt mà không nói chữ "tour" lẫn tên tour.
_TU_DEM_KHI_CHI_NOI_DAT = {
    "ok", "oke", "vay", "the", "thi", "toi", "minh", "em", "anh", "chi", "ban", "muon", "xin", "can", "luon", "di", "nhe", "nha",
    "a", "giup", "nao", "thoi", "nhen", "ngay", "lien", "cho", "u", "oi", "cai", "nay", "do", "cu", "nhanh",
}


def chi_noi_muon_dat(message: str) -> bool:
    """Cả câu chỉ là lời muốn đặt ("chốt", "đặt luôn đi", "giữ chỗ giúp mình"). Chỉ dùng khi KHÔNG đang đặt dở:
    đang ở bước xác nhận thì "ok chốt" là Đồng ý, không phải bắt đầu lại."""
    nd = _chuan(message)
    if _DA_DAT.search(nd) or _CHUA_MUON_DAT.search(nd):
        return False
    con_lai = [t for t in nd.split() if t not in _TU_DEM_KHI_CHI_NOI_DAT]
    return con_lai in (["chot"], ["dat"], ["book"], ["giu"], ["dang", "ky"])


def _muon_huy(message: str, step: str | None) -> bool:
    nd = _chuan(message)
    if _THOI_HUY.match(nd):
        return step != "chon_nguoi"  # ở bước chọn người đi cùng, "thôi" nghĩa là không chọn ai
    if not _HUY.search(nd):
        return False
    # "huỷ", "huỷ tour", "huỷ đặt tour", "không đặt tour nữa" -> huỷ. Còn "huỷ … tour X" có tên tour khác thì thôi.
    con_lai = re.sub(r"\b(huy|viec|dat|khong|nua|tour|giup|minh|toi|em|di|nhe|nha|a|bo qua|dung lai|cancel|booking|lai)\b", " ", nd)
    return len(con_lai.split()) <= 2


_TU_THUA = (
    r"\b(toi|minh|em|anh|chi|ban|muon|can|xin|giup|cho|hay|vui long|dat|book|booking|dang ky|dang ki|chot|giu cho|tour|"
    r"di|nhe|nha|a|voi|oi|nay|do|vua roi|tren|kia|ay|thu|so|dau tien|cuoi cung|nguoi|lon|tre|be|khach|ngay|thang|"
    r"du lich|chuyen|luon|ngay|va|la|co|ve|lay|\d+)\b"
)


def _bo_cum_dat_tour(message: str) -> str:
    """Phần còn lại của câu sau khi bỏ các từ không phải tên tour/điểm đến. Rỗng = khách chưa nói tour nào."""
    return re.sub(r"\s+", " ", re.sub(_TU_THUA, " ", _chuan(message))).strip()


# ---------------------------------------------------------------- gọi dữ liệu ngoài
def lay_tour_live(tour_key: str) -> dict | None:
    try:
        r = httpx.get(f"{BENTHANH_API_BASE}/item", params={"tour_key": tour_key}, headers=BENTHANH_HEADERS, timeout=15)
        return r.json()["data"]
    except Exception:
        return None


PHUONG_THUC_THANH_TOAN = "AT_OFFICE"  # mặc định "thanh toán tại văn phòng" — chatbot không hỏi, khách đổi sau với nhân viên


def tao_booking(token: str, st: dict) -> tuple[dict | None, str | None]:
    """Tạo booking THẬT qua `POST /api/v1/app/bookings` của trang quản trị chat (từ 2026-11-16, thay NestJS):
    gửi tourKey/departureKey, backend tự lấy giá từ benthanhtourist.com, đơn hiện ngay trong hộp thư ở trạng thái chờ xác nhận.
    `id` đơn trả về cũng là `orderCode`, nên khi main.py báo `_don` lên trang quản trị thì không tạo đơn thứ hai.

    KHÔNG gửi `guests` — backend đã bỏ bắt buộc thông tin hành khách
    (CCCD/hộ chiếu/thân nhân); họ tên, email, SĐT lấy từ tài khoản khách theo
    token. Đây cũng là lý do chatbot không phải hỏi thêm thông tin cá nhân.

    Trả (booking, None) khi thành công, (None, thông_báo_lỗi) khi hỏng.
    """
    if not NESTJS_BASE_URL or not token:
        return None, "Mình chưa xác thực được tài khoản của bạn nên chưa đặt tour được. Bạn đăng nhập lại rồi thử lại giúp mình nhé."

    than = {
        "tourKey": st["tour"]["key"],
        "departureKey": st["dot"]["key"],
        "departureDate": st["dot"]["date"],
        "unitPrice": int(float(st["dot"]["price"] or 0)),
        "adults": st["adults"],
        "children": st["children"],
        "infants": st["infants"],
        "paymentMethod": PHUONG_THUC_THANH_TOAN,
    }
    try:
        r = httpx.post(
            f"{NESTJS_BASE_URL.rstrip('/')}/api/v1/app/bookings",
            json=than,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=20,
        )
    except httpx.RequestError:
        # Có thể request ĐÃ tới nơi và tạo đơn rồi (timeout/mất mạng giữa chừng) ->
        # tuyệt đối không tự đặt lại, bảo khách kiểm tra lịch sử để tránh đặt trùng 2 đơn.
        return None, "Mình chưa nhận được phản hồi từ hệ thống đặt tour. Bạn kiểm tra mục “Lịch sử đặt tour” giúp mình nhé — nếu chưa có đơn nào thì bạn bấm “Đồng ý” lại."

    if r.status_code in (200, 201):
        payload = r.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        return (data if isinstance(data, dict) else {}), None

    if r.status_code == 401:
        return None, "Phiên đăng nhập của bạn đã hết hạn. Bạn đăng nhập lại rồi đặt tour giúp mình nhé."

    # 400/404... backend trả lý do cụ thể (hết chỗ, voucher sai, đợt không hợp lệ) -> nói đúng lý do cho khách.
    ly_do = ""
    try:
        than_loi = r.json()
        if isinstance(than_loi, dict):
            m = than_loi.get("message") or than_loi.get("error")
            ly_do = "; ".join(m) if isinstance(m, list) else str(m or "")
    except Exception:
        pass
    return None, (f"Mình chưa đặt được tour: {ly_do}" if ly_do else "Mình chưa đặt được tour do hệ thống đang bận. Bạn thử lại sau ít phút nhé.")


def lay_than_nhan(token: str) -> list[dict] | None:
    """None = không gọi được (khác với [] = chưa có ai)."""
    if not NESTJS_BASE_URL or not token:
        return None
    try:
        r = httpx.get(
            f"{NESTJS_BASE_URL.rstrip('/')}/api/v1/app/relatives",  # đã bỏ thân nhân (DUNG_THAN_NHAN = False), backend mới không có
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=8,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception:
        return None


def cac_dot_khoi_hanh(data: dict) -> list[dict]:
    """Các đợt còn chỗ, khởi hành từ rag.SO_NGAY_BAO_TRUOC_GOI_Y ngày sau trở đi. Gộp cả đợt top-level nếu chưa có trong tour_days[] (dữ liệu Laravel hay lệch)."""
    dots = []
    for d in data.get("tour_days") or []:
        dots.append({"key": str(d.get("id")), "date": str(d.get("departure_date", ""))[:10], "price": d.get("price"), "seats": d.get("stock_qty"), "code": d.get("code")})
    top = str(data.get("departure_date", ""))[:10]
    if top and all(x["date"] != top for x in dots):
        dots.append({"key": str(data.get("id")), "date": top, "price": data.get("price"), "seats": data.get("stock_qty"), "code": data.get("code")})
    som_nhat = rag.ngay_som_nhat_goi_y()
    dots = [x for x in dots if x["date"] >= som_nhat and (x["seats"] or 0) > 0]
    return sorted(dots, key=lambda x: x["date"])


# ---------------------------------------------------------------- định dạng
def _dmy(iso: str) -> str:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return iso


def _tien(v) -> str:
    try:
        return f"{int(round(float(v))):,}".replace(",", ".") + " đ"
    except (TypeError, ValueError):
        return "liên hệ"


def _tuoi(dob_iso: str, ngay_di: str) -> int | None:
    try:
        d = datetime.strptime(dob_iso[:10], "%Y-%m-%d").date()
        ref = datetime.strptime(ngay_di[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return ref.year - d.year - ((ref.month, ref.day) < (d.month, d.day))


def _kq(
    reply: str,
    choices: list[dict] | None = None,
    multi: bool = False,
    toi_da: int | None = None,
    booking: dict | None = None,
) -> dict:
    out = {"reply": reply, "tours": [], "goi_y": []}
    if choices:
        out["choices"] = choices
        if multi:
            out["multi"] = True
            out["toi_da"] = toi_da
    if booking:
        out["booking"] = booking
    return out


_NUT_HUY = {"id": "huy", "label": "Huỷ đặt tour"}
_NUT_XAC_NHAN = [{"id": "xn:dong_y", "label": "Đồng ý"}, {"id": "xn:khong", "label": "Không đồng ý"}]
_NUT_DOI = [
    {"id": "doi:ngay", "label": "Đổi ngày khởi hành"},
    {"id": "doi:so_nguoi", "label": "Đổi số người"},
    {"id": "doi:nguoi", "label": "Đổi người đi cùng"},
    _NUT_HUY,
]


def _nut_doi(web: bool = False) -> list[dict]:
    """Các nút "đổi phần nào"; bước thân nhân đang tắt (hoặc khách web, không có thân nhân) thì bỏ nút "Đổi người đi cùng"."""
    return [n for n in _NUT_DOI if (DUNG_THAN_NHAN and not web) or n["id"] != "doi:nguoi"]


def _nut_ngay(dots: list[dict]) -> list[dict]:
    return [{"id": f"dot:{d['key']}", "label": f"{_dmy(d['date'])} · còn {d['seats']} chỗ · {_tien(d['price'])}"} for d in dots[:8]] + [_NUT_HUY]


def _ghi_chu_ngay(dots: list[dict]) -> str:
    """Nút chỉ hiện 8 ngày đầu; còn nhiều hơn thì liệt kê nốt bằng chữ để khách thấy đủ (và gõ ngày muốn chọn)."""
    if len(dots) <= 8:
        return ""
    return "\nCác ngày khác: " + ", ".join(_dmy(d["date"]) for d in dots[8:]) + " (bạn gõ ngày muốn chọn, ví dụ “10/12”)."


def _nut_so_nguoi() -> list[dict]:
    return [{"id": f"sl:{n},0,0", "label": f"{n} người lớn"} for n in (1, 2, 3, 4)] + [_NUT_HUY]


# ---------------------------------------------------------------- các bước
SO_TOUR_GOI_Y = 5


def tour_goi_y(so_luong: int = SO_TOUR_GOI_Y) -> list[dict]:
    """Vài tour để khách bấm khi chưa nói / chatbot không nhận ra tour nào: còn chỗ, khởi hành sớm nhất,
    mỗi điểm đến một tour (dữ liệu Chroma; ngày/chỗ thật được kiểm lại khi khách chọn tour)."""
    som_nhat = rag.ngay_som_nhat_goi_y()
    ung_vien = []
    for m in rag._collection.get()["metadatas"]:
        ngay = str(m.get("ngay_khoi_hanh") or "")[:10]
        try:
            con_cho = int(m.get("so_cho_con") or 0)
        except (TypeError, ValueError):
            con_cho = 0
        if m.get("tour_key") and ngay >= som_nhat and con_cho > 0:
            ung_vien.append((ngay, str(m.get("diem_den") or ""), str(m["tour_key"]), str(m.get("ten") or "")))
    chon, da_co_dd, da_co_key = [], set(), set()
    for ngay, dd, key, ten in sorted(ung_vien):
        if dd in da_co_dd or key in da_co_key:
            continue
        da_co_dd.add(dd)
        da_co_key.add(key)
        chon.append({"key": key, "ten": ten})
        if len(chon) >= so_luong:
            break
    return chon


def _hoi_chon_tour(session_key: str, st: dict, cands: list[dict], cau: str = "") -> dict:
    st["step"] = "chon_tour"
    _ghi(session_key, st)
    if cands:
        return _kq(
            "Bạn muốn đặt tour nào ạ? Bạn bấm chọn bên dưới hoặc gõ tên tour/điểm đến nhé.",
            [{"id": f"tour:{c['key']}", "label": c["ten"][:60]} for c in cands[:5]] + [_NUT_HUY],
        )
    # Không có tour nào để chọn: ưu tiên các tour vừa gợi ý trong cuộc trò chuyện, không có thì gợi ý vài tour sắp đi.
    goi_y = (st.get("last_tours") or [])[:5] or tour_goi_y()
    # Khách có nói tên tour/điểm đến (còn chữ sau khi bỏ "đặt tour", "giúp mình"...) mà không tìm ra -> nói rõ là chưa thấy.
    mo_dau = (
        "Mình chưa tìm thấy tour nào khớp với nơi bạn nói. Bạn gõ tên điểm đến khác (ví dụ Đà Lạt, Nhật Bản, Đài Loan)"
        if cau and _bo_cum_dat_tour(cau)
        else "Bạn muốn đặt tour nào ạ? Bạn gõ tên tour/điểm đến"
    )
    return _kq(
        mo_dau + (" hoặc chọn một tour gợi ý bên dưới nhé." if goi_y else " nhé."),
        [{"id": f"tour:{c['key']}", "label": c["ten"][:60]} for c in goi_y] + [_NUT_HUY],
    )


def _loai_trung(tours: list[dict]) -> list[dict]:
    thay, thay_key = [], set()
    for t in tours:
        k = str(t.get("tour_key", ""))
        if k and k not in thay_key:
            thay_key.add(k)
            thay.append({"key": k, "ten": str(t.get("ten", ""))})
    return thay


def tim_tour_theo_cau(message: str) -> list[dict]:
    """Tour mà khách gọi tên trong câu (đã loại trùng). Rỗng = câu không nói tour/điểm đến nào.
    Thứ tự: (1) chép nguyên tên tour -> đúng 1 tour đó; (2) nói điểm đến -> tour của điểm đến đó,
    ưu tiên tour có tên chứa đúng chữ khách gõ ("đặt tour Sapa" -> chỉ các tour có Sapa, không phải
    mọi tour Hà Nội); (3) còn chữ khác -> tìm theo nghĩa."""
    cau = _chuan(message)
    tat_ca = _loai_trung(rag.tat_ca_luot_con_han())

    # (1) nguyên tên tour nằm trong câu: lấy tên DÀI NHẤT (tên ngắn có thể là phần đầu của tên dài)
    khop_ten = [t for t in tat_ca if _chuan(t["ten"]) and f" {_chuan(t['ten'])} " in f" {cau} "]
    if khop_ten:
        dai_nhat = max(len(_chuan(t["ten"])) for t in khop_ten)
        return [t for t in khop_ten if len(_chuan(t["ten"])) == dai_nhat]

    # (2) điểm đến (xét TRƯỚC khi kiểm tra "còn chữ nào không": "đặt tour Anh" bỏ từ thừa xong là rỗng)
    ten = _bo_cum_dat_tour(message)
    diem_den = trich_diem_den(message)
    if diem_den:
        ung_vien = _loai_trung([m for m in rag.tat_ca_luot_con_han() if m["diem_den"] == diem_den])
        tu_khach = set(ten.split())
        diem = [len(tu_khach & set(_chuan(t["ten"]).split())) for t in ung_vien]
        cao_nhat = max(diem, default=0)
        return [t for t, d in zip(ung_vien, diem) if d == cao_nhat] if cao_nhat else ung_vien

    # (3) tìm theo nghĩa phần còn lại
    if not ten:
        return []
    tours = tim_tour_lien_quan(ten)
    # "đặt tour Noel": mời chọn trong các tour đúng tên, tour chỉ trùng ngày chỉ dùng khi không có tour đúng tên nào.
    return _loai_trung([t for t in tours if t.get("nhom_dip") != "trung_ngay"] or tours)


_THU_TU_CHU = {"nhat": 1, "mot": 1, "hai": 2, "ba": 3, "bon": 4, "tu": 4, "nam": 5}


def _thu_tu(nd: str, so_tour: int) -> int | None:
    """"tour thứ 2", "tour số 2", "tour thứ hai", "tour đầu tiên", "tour cuối" -> vị trí (từ 1) trong danh sách vừa gợi ý.
    Số đứng một mình ("cho 2 người") KHÔNG phải số thứ tự."""
    if re.search(r"\bdau tien\b", nd):
        return 1
    # chỉ "tour cuối" / "cuối cùng": chữ "cuoi" đứng riêng còn là "cưỡi" (tên tour "… Cưỡi Lạc Đà …")
    if re.search(r"\b(tour|cai) cuoi\b|\bcuoi cung\b", nd):
        return so_tour
    m = re.search(r"\b(?:thu|so)\s*(\d|" + "|".join(_THU_TU_CHU) + r")\b", nd)
    if not m:
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else _THU_TU_CHU[m.group(1)]
    return n if 1 <= n <= so_tour else None


def _tim_ung_vien(message: str, st: dict) -> list[dict]:
    """Trả về các tour (đã loại trùng) khớp câu nói. Rỗng = chưa rõ tour nào."""
    nd = _chuan(message)
    last = st.get("last_tours") or []
    if last:
        n = _thu_tu(nd, len(last))
        if n:
            return [last[n - 1]]
    theo_cau = tim_tour_theo_cau(message)
    if last and _CHI_TOUR_VUA_GOI_Y.search(nd):
        if not theo_cau:
            return last
        # "đặt tour Đà Lạt đó": ưu tiên tour Đà Lạt trong danh sách vừa gợi ý
        chung = [t for t in last if t["key"] in {c["key"] for c in theo_cau}]
        return chung or theo_cau
    if last and not theo_cau and not _bo_cum_dat_tour(message):
        return last  # "giữ chỗ giúp tôi", "đặt giúp mình" (chưa nói tour nào) -> tour chatbot vừa gợi ý
    return theo_cau


def _chon_tour(session_key: str, st: dict, tour_key: str) -> dict:
    data = lay_tour_live(tour_key)
    if not data:
        # Giữ lại các tour vừa gợi ý để khách thử lại "đặt tour này" được khi API ổn.
        _ket_thuc_luong(session_key, st)
        return _kq("Mình chưa lấy được thông tin tour lúc này. Bạn thử lại sau ít phút hoặc xem tour trực tiếp trong mục Du lịch nhé.")
    dots = cac_dot_khoi_hanh(data)
    st["tour"] = {
        "key": tour_key,
        "ten": data.get("name", ""),
        "foreign": "/nuoc-ngoai/" in str(data.get("image", "")),
    }
    st["dots"] = dots
    if not dots:
        _ket_thuc_luong(session_key, st)
        return _kq(f"Tour “{st['tour']['ten']}” hiện chưa có ngày khởi hành còn chỗ. Bạn muốn xem tour khác không ạ?")
    if len(dots) == 1:
        return _chon_dot(session_key, st, dots[0], tu_dong=True)
    st["step"] = "chon_ngay"
    _ghi(session_key, st)
    return _kq(
        f"Tour “{st['tour']['ten']}” có {len(dots)} ngày khởi hành. Bạn chọn ngày nào ạ?" + _ghi_chu_ngay(dots),
        _nut_ngay(dots),
    )


_CAU_HOI_SO_NGUOI = "Bạn đi mấy người? Bạn bấm chọn hoặc gõ ví dụ “2 người lớn 1 trẻ em”."


def _hoi_so_nguoi(session_key: str, st: dict, mo_dau: str = "") -> dict:
    st["step"] = "so_nguoi"
    _ghi(session_key, st)
    return _kq(
        (mo_dau + "\n" if mo_dau else "") + _CAU_HOI_SO_NGUOI,
        _nut_so_nguoi(),
    )


def _chon_dot(session_key: str, st: dict, dot: dict, tu_dong: bool = False) -> dict:
    st["dot"] = dot
    da_co_so_nguoi = "adults" in st
    if da_co_so_nguoi:
        # Khách chỉ ĐỔI NGÀY (đã khai số người, người đi cùng): giữ nguyên, quay lại bảng tóm tắt với ngày/giá mới.
        tong = st["adults"] + st["children"] + st["infants"]
        if tong <= (dot["seats"] or 0):
            st.setdefault("relative_ids", [])
            return _tom_tat(session_key, st)
        for k in ("adults", "children", "infants", "relative_ids"):
            st.pop(k, None)
        return _hoi_so_nguoi(session_key, st, f"Ngày {_dmy(dot['date'])} chỉ còn {dot['seats']} chỗ, không đủ cho {tong} khách.")
    mo_dau = (
        f"Tour “{st['tour']['ten']}” chỉ có một ngày khởi hành là {_dmy(dot['date'])}, mình chốt ngày này cho bạn nhé (còn {dot['seats']} chỗ, {_tien(dot['price'])}/người lớn)."
        if tu_dong
        else f"Mình chốt ngày {_dmy(dot['date'])} (còn {dot['seats']} chỗ, {_tien(dot['price'])}/người lớn)."
    )
    return _hoi_so_nguoi(session_key, st, mo_dau)


_SO_CHU = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5, "lam": 5, "sau": 6, "bay": 7, "tam": 8, "chin": 9}


# Chữ số chỉ là SỐ NGƯỜI khi đứng ngay trước một từ đếm người. "Ba tôi", "bà xã", "báo sau", "năm sau" không phải số.
_DV_NGUOI = r"(?:nguoi|khach|ng|nl|te|tre|em be|be|dua|vo chong|lon|nho)"
_SO_DON = "|".join(k for k in _SO_CHU if k != "lam")  # "lăm" chỉ đứng sau "mười"
_CUM_SO_CHU = rf"(?:(?:{_SO_DON}) muoi(?: (?:{'|'.join(_SO_CHU)}))?|muoi(?: (?:{'|'.join(_SO_CHU)}))?|(?:{_SO_DON}))"


def _gia_tri_so_chu(cum: str) -> str:
    tu = cum.split()
    if "muoi" not in tu:
        return str(_SO_CHU[tu[0]])
    i = tu.index("muoi")
    return str((_SO_CHU[tu[0]] if i else 1) * 10 + (_SO_CHU[tu[i + 1]] if len(tu) > i + 1 else 0))


def _so_chu_thanh_so(t: str) -> str:
    """"mười hai người" -> 12, "hai mươi khách" -> 20, "hai người lớn" -> 2, "một mình" -> 1, cả câu chỉ là "ba" -> 3.
    Chữ số KHÔNG đứng trước từ đếm người thì giữ nguyên ("ba tôi và tôi", "hỏi bà xã rồi báo sau")."""
    if re.fullmatch(_CUM_SO_CHU, t):
        return _gia_tri_so_chu(t)
    t = re.sub(r"\bmot(?= minh\b)", "1", t)
    return re.sub(rf"\b{_CUM_SO_CHU}(?= {_DV_NGUOI}\b)", lambda m: _gia_tri_so_chu(m.group(0)), t)


def phan_tich_so_nguoi(text: str, can_don_vi: bool = False) -> tuple[int, int, int] | None:
    """(người lớn, trẻ em, em bé) từ câu khách gõ; None nếu câu không có số người nào.
    can_don_vi=True (câu hỏi): chỉ nhận khi con số đi kèm từ đếm người ("2 người được không?")."""
    # Bỏ số thập phân / tiền / ngày tháng / khoảng ("2.5", "10.000.000", "20/12", "2-3") và phần trăm: không phải số người
    tho = re.sub(r"\d+(?:[.,/\-:]\d+)+|\d+\s*%", " ", text)
    t = _so_chu_thanh_so(_chuan(tho))
    t = re.sub(r"\b\d{4,}\b", " ", t)  # số điện thoại, CCCD, năm…
    # "bé 3 tuổi", "trẻ em 5 tuổi" mà không nói mấy bé -> chưa đủ để chốt, hỏi lại (không lặng lẽ bỏ mất em bé)
    co_tuoi_le = re.search(r"\b(be|tre|con|chau|dua)( \w+)? \d+ ?(tuoi|thang)\b", t)
    # Số đứng trước tuổi / tháng / năm / triệu / k / đ… hoặc sau ngày / tháng / năm không phải số người
    t = re.sub(r"\b\d+ ?(tuoi|thang|trieu|tr|k|d|dong|vnd|ngay|dem|gio|phut|sao)\b", " ", t)
    if "nu" not in t.split():  # "2 nam 1 nữ" là giới tính, không phải "2 năm"
        t = re.sub(r"\b\d+ ?nam\b", " ", t)
    t = re.sub(r"\b(ngay|thang|nam|luc|mung|thu) \d+\b", " ", t)
    sb = re.search(r"\b(\d+) ?(em be|so sinh|baby|infant)\b", t)
    if sb:
        t = t.replace(sb.group(0), " ")
    tre = re.search(r"\b(\d+) ?(tre em|tre|te|be|nho|dua|con nit|con|child|kid)\b", t)
    if tre:
        t = t.replace(tre.group(0), " ")
    if co_tuoi_le and not (tre or sb):
        return None
    c = int(tre.group(1)) if tre else 0
    i = int(sb.group(1)) if sb else 0
    nl = re.search(r"\b(\d+) ?(nguoi lon|ng lon|lon|nl|adult)\b", t)
    if nl:
        return int(nl.group(1)), c, i
    chung = re.search(r"\b(\d+) ?(nguoi|khach|ng)?\b", t)
    if not (chung or tre or sb):
        return None
    if can_don_vi and not (tre or sb or (chung and chung.group(2))):
        return None
    a = int(chung.group(1)) if chung else 0
    # "gia đình 4 người gồm 2 trẻ em" -> 4 là TỔNG, người lớn = 4 - 2
    if (c or i) and a > c + i and re.search(r"\b(gom|trong do|bao gom|ke ca|tinh ca|tong cong|tat ca)\b", t):
        a -= c + i
    return a, c, i


def _chon_so_nguoi(session_key: str, st: dict, token: str, a: int, c: int, i: int) -> dict:
    tong = a + c + i
    seats = st["dot"]["seats"] or 0
    if min(a, c, i) < 0:
        return _hoi_so_nguoi(session_key, st, "Số người chưa hợp lệ.")
    if a < 1:
        return _hoi_so_nguoi(session_key, st, "Cần có ít nhất 1 người lớn đi cùng.")
    if tong > TOI_DA_KHACH:
        return _hoi_so_nguoi(session_key, st, f"Mỗi đơn mình nhận tối đa {TOI_DA_KHACH} khách. Đoàn đông hơn bạn liên hệ nhân viên để được báo giá đoàn nhé.")
    if tong > seats:
        return _hoi_so_nguoi(session_key, st, f"Ngày này chỉ còn {seats} chỗ nên mình chưa nhận được {tong} khách.")
    st.update({"adults": a, "children": c, "infants": i})
    return _hoi_nguoi_di_cung(session_key, st, token)


def _nut_than_nhan(st: dict) -> tuple[list[dict], int]:
    toi_da = st["adults"] + st["children"] + st["infants"] - 1
    ngay = st["dot"]["date"]
    nhan = []
    for r in st.get("rels", []):
        tuoi = _tuoi(r["dob"], ngay)
        nhan.append({"id": f"nguoi:{r['id']}", "label": (r["ten"] or "(chưa có tên)") + (f" · {tuoi} tuổi" if tuoi is not None else "")})
    return nhan + [{"id": "nguoi:skip", "label": "Nhập sau ở trang booking"}, _NUT_HUY], toi_da


def _hoi_nguoi_di_cung(session_key: str, st: dict, token: str) -> dict:
    tong = st["adults"] + st["children"] + st["infants"]
    st["relative_ids"] = []
    if tong == 1 or not DUNG_THAN_NHAN or khach_web(session_key):
        st["rels"] = []
        return _tom_tat(session_key, st)
    rels = lay_than_nhan(token)
    if not rels:
        st["step"] = "xac_nhan"
        st["rels"] = []
        ghi = ("Bạn chưa có thân nhân nào được lưu" if rels == [] else "Mình chưa lấy được danh sách thân nhân của bạn") + ", nên thông tin người đi cùng bạn nhập ở trang booking nhé.\n"
        res = _tom_tat(session_key, st)
        res["reply"] = ghi + res["reply"]
        return res
    st["step"] = "chon_nguoi"
    # Thân nhân cũ có thể thiếu họ tên / ngày sinh (null) -> vẫn hiện, không làm hỏng bước chọn người.
    st["rels"] = [
        {"id": str(r["id"]), "ten": str(r.get("fullName") or "").strip(), "dob": str(r.get("dateOfBirth") or "")}
        for r in rels if isinstance(r, dict) and r.get("id") not in (None, "")
    ]
    _ghi(session_key, st)
    nut, toi_da = _nut_than_nhan(st)
    return _kq(
        f"Bạn là khách số 1. Còn {toi_da} người đi cùng, bạn chọn trong danh sách thân nhân (tối đa {toi_da} người), hoặc chọn “Nhập sau ở trang booking”.",
        nut, multi=True, toi_da=toi_da,
    )


def _chon_nguoi_theo_ten(nd: str, rels: list[dict]) -> list[str]:
    """Khách gõ tên: khớp theo CẢ HỌ TÊN hoặc theo TÊN GỌI (chữ cuối) nguyên từ — "Lan" không được bắt nhầm "An"."""
    tu = set(nd.split())
    chon = []
    for r in rels:
        ho_ten = _chuan(r["ten"])
        if ho_ten and (f" {ho_ten} " in f" {nd} " or ho_ten.split()[-1] in tu):
            chon.append(r["id"])
    return chon


def _tom_tat(session_key: str, st: dict) -> dict:
    a, c, i = st["adults"], st["children"], st["infants"]
    gia = float(st["dot"]["price"] or 0)
    tong_tien = a * gia + c * gia * GIA_TRE_EM + i * gia * GIA_EM_BE
    phan = [f"{a} người lớn"] + ([f"{c} trẻ em"] if c else []) + ([f"{i} em bé"] if i else [])
    ten_di_cung = [r["ten"] for r in st.get("rels", []) if r["id"] in st.get("relative_ids", [])]
    dong = [
        "Mình tóm tắt đơn đặt tour của bạn:",
        f"• Tour: {st['tour']['ten']}",
        f"• Khởi hành: {_dmy(st['dot']['date'])}" + (f" (mã {st['dot']['code']})" if st["dot"].get("code") else ""),
        f"• Số khách: {', '.join(phan)}",
    ]
    if ten_di_cung:
        con_lai = (a + c + i - 1) - len(ten_di_cung)
        dong.append(f"• Người đi cùng: {', '.join(ten_di_cung)}" + (f" (còn {con_lai} người bạn nhập ở trang booking)" if con_lai > 0 else ""))
    web = khach_web(session_key)
    if web and a + c + i > 1:
        dong.append("• Thông tin người đi cùng: nhân viên sẽ hỏi bạn khi liên hệ xác nhận")
    dong.append(f"• Tổng tiền tạm tính: {_tien(tong_tien)}" if gia else "• Tổng tiền: vui lòng liên hệ")
    dong.append("  (trẻ em tính 80%, em bé tính 40% giá người lớn; chưa áp voucher — bạn muốn dùng voucher thì báo nhân viên CSKH khi xác nhận đơn nhé)")
    if st["tour"]["foreign"] and DUNG_THAN_NHAN and not web:
        dong.append("• Tour nước ngoài: mỗi khách cần số hộ chiếu và số visa, bạn nhập ở trang booking.")
    dong.append("Bạn có đồng ý với thông tin này không ạ?")
    st["step"] = "xac_nhan"
    _ghi(session_key, st)
    return _kq("\n".join(dong), list(_NUT_XAC_NHAN))


def _dong_y(session_key: str, st: dict, token: str = "") -> dict:
    """Khách đã xem bảng tóm tắt và bấm “Đồng ý” -> ĐẶT TOUR LUÔN trong chat.
    Khách có thể dừng ở bảng tóm tắt rất lâu nên phải lấy lại ngày / số chỗ /
    giá hiện tại trước khi gửi đơn, tránh đặt theo dữ liệu đã cũ."""
    cu = st["dot"]
    tong = st["adults"] + st["children"] + st["infants"]
    data = lay_tour_live(st["tour"]["key"])
    try:
        dots = cac_dot_khoi_hanh(data) if data else None
    except Exception:
        dots = None
    if dots is None:
        # Không kiểm tra lại được: giữ nguyên phiên ở bước xác nhận để khách bấm lại, không đặt theo dữ liệu có thể đã cũ.
        return _kq(
            "Mình chưa kiểm tra lại được số chỗ và giá của tour lúc này nên chưa đặt tour được. Bạn bấm “Đồng ý” lại sau ít phút giúp mình nhé.",
            list(_NUT_XAC_NHAN),
        )
    st["dots"] = dots
    moi = next((d for d in dots if d["key"] == cu["key"] and d["date"] == cu["date"]), None)
    if not moi or (moi["seats"] or 0) < tong:
        if not dots:
            _ket_thuc_luong(session_key, st)
            return _kq(f"Rất tiếc, tour “{st['tour']['ten']}” vừa hết ngày khởi hành còn chỗ nên mình chưa đặt tiếp được. Bạn muốn xem tour khác không ạ?")
        ly_do = (
            f"Ngày {_dmy(cu['date'])} chỉ còn {moi['seats']} chỗ, không đủ cho {tong} khách"
            if moi
            else f"Rất tiếc, ngày {_dmy(cu['date'])} vừa hết chỗ hoặc không còn mở bán"
        )
        st.pop("dot", None)
        st["step"] = "chon_ngay"
        _ghi(session_key, st)
        return _kq(ly_do + ". Bạn chọn ngày khởi hành khác giúp mình nhé." + _ghi_chu_ngay(dots), _nut_ngay(dots))
    st["dot"] = moi
    if float(moi["price"] or 0) != float(cu["price"] or 0):
        # Giá vừa đổi: không đặt im lặng theo giá mới, hiện lại bảng tóm tắt với tổng tiền mới và hỏi lại.
        res = _tom_tat(session_key, st)
        res["reply"] = (
            f"Giá ngày {_dmy(moi['date'])} vừa thay đổi: {_tien(moi['price'])}/người lớn (trước đó {_tien(cu['price'])}). Mình cập nhật lại đơn cho bạn nhé.\n"
            + res["reply"]
        )
        return res
    if khach_web(session_key):
        return _ghi_nhan_yeu_cau_web(session_key, st)
    booking, loi = tao_booking(token, st)
    if loi:
        # Chưa đặt được: GIỮ nguyên phiên ở bước xác nhận để khách bấm “Đồng ý”
        # lại, không mất hết thông tin đã chọn.
        return _kq(loi, list(_NUT_XAC_NHAN))

    # Đặt xong mới kết thúc phiên — khách bấm “Đồng ý” lần nữa cũng không tạo đơn trùng.
    _ket_thuc_luong(session_key, st)
    ma_don = str(booking.get("id") or "")
    dong = [
        f"Mình đã đặt tour “{st['tour']['ten']}” cho bạn rồi ạ 🎉",
        f"• Khởi hành: {_dmy(st['dot']['date'])}",
        f"• Số khách: {st['adults'] + st['children'] + st['infants']} người",
        "• Thanh toán: tại văn phòng",
        "Đơn đang chờ xác nhận, bộ phận CSKH sẽ liên hệ với bạn sớm nhất. Bạn bấm nút bên dưới để xem trạng thái đơn nhé.",
    ]
    # Chỉ trả mã đơn, KHÔNG trả đường dẫn: app RN mở "/detailTour?id=", Zalo Mini App
    # mở "/booking-detail/:id" — đường dẫn là chuyện của từng app, API dùng chung
    # không nên gắn cứng route của một app.
    res = _kq("\n".join(dong), booking={"booking_id": ma_don})
    # Khoá nội bộ để main.py báo doanh thu lên trang quản trị; main.py gỡ ra trước khi trả cho app.
    a, c, i = st["adults"], st["children"], st["infants"]
    gia = float(st["dot"]["price"] or 0)
    res["_don"] = {
        "tourName": st["tour"]["ten"],
        "guests": a + c + i,
        "amount": int(a * gia + c * gia * GIA_TRE_EM + i * gia * GIA_EM_BE),
        **({"orderCode": ma_don} if ma_don else {}),
        # Mã đợt khởi hành (tour_days[].code), để sale khỏi gõ lại khi xác nhận đơn trên trang quản trị.
        **({"tourCode": st["dot"]["code"]} if st["dot"].get("code") else {}),
    }
    return res


def _ghi_nhan_yeu_cau_web(session_key: str, st: dict) -> dict:
    """Khách web không có tài khoản nên KHÔNG tạo đơn trên NestJS: ghi nhận yêu cầu để nhân viên gọi theo SĐT khách đã để lại
    (main.py gửi "_don" lên trang quản trị, đơn ở trạng thái chờ sale gọi xác nhận, chưa có mã đơn)."""
    _ket_thuc_luong(session_key, st)
    a, c, i = st["adults"], st["children"], st["infants"]
    gia = float(st["dot"]["price"] or 0)
    res = _kq("\n".join([
        f"Mình đã ghi nhận yêu cầu đặt tour “{st['tour']['ten']}” của bạn rồi ạ 🎉",
        f"• Khởi hành: {_dmy(st['dot']['date'])}",
        f"• Số khách: {a + c + i} người",
        "Yêu cầu này CHƯA phải đơn đã giữ chỗ. Nhân viên CSKH sẽ gọi vào số điện thoại bạn đã để lại để xác nhận chỗ, giá và thanh toán.",
    ]))
    res["_don"] = {
        "tourName": st["tour"]["ten"],
        "guests": a + c + i,
        "amount": int(a * gia + c * gia * GIA_TRE_EM + i * gia * GIA_EM_BE),
        **({"tourCode": st["dot"]["code"]} if st["dot"].get("code") else {}),
    }
    return res


def _khong_dong_y(session_key: str, st: dict) -> dict:
    st["step"] = "khong_dong_y"
    _ghi(session_key, st)
    return _kq("Bạn muốn đổi phần nào ạ?", _nut_doi(khach_web(session_key)))


def _huy(session_key: str, st: dict | None = None) -> dict:
    _ket_thuc_luong(session_key, st or {})
    return _kq("Mình đã huỷ việc đặt tour. Khi nào cần, bạn cứ nói “tôi muốn đặt tour…” là mình hỗ trợ tiếp nhé.")


# ---------------------------------------------------------------- điểm vào
def xu_ly(session_key: str, token: str, message: str, action: dict | None) -> dict | None:
    """Trả về kết quả của luồng đặt tour, hoặc None nếu câu này không thuộc luồng (để chat thường xử lý).
    `token` chỉ dùng để gọi NestJS lấy thân nhân trong lượt này, KHÔNG lưu xuống đĩa."""
    st = _doc(session_key) or {}
    try:
        return _xu_ly(session_key, token, message, action, st, bool(st.get("step")))
    except Exception:
        # Trạng thái hỏng / thiếu bước (vd bấm nút của bước cũ): đừng làm sập chat, cho khách bắt đầu lại.
        try:
            _ket_thuc_luong(session_key, st)
        except Exception:
            xoa_trang_thai(session_key)
        return _kq("Mình bị lạc bước đặt tour một chút. Bạn nói lại “tôi muốn đặt tour…” để mình hỗ trợ từ đầu nhé.")


def hoi_tour_khac(session_key: str, tours: list[dict]) -> bool:
    """Câu vừa hỏi (chat thường đã trả lời) cho ra thẻ tour mà KHÔNG có tour đang đặt dở: khách đang xem tour khác giữa chừng."""
    st = _doc(session_key) or {}
    key = (st.get("tour") or {}).get("key")
    keys = {str(t.get("tour_key") or "") for t in tours or []} - {""}
    return bool(st.get("step") and key and keys and key not in keys)


def _ten_ngan(ten: str, toi_da: int = 34) -> str:
    return ten if len(ten) <= toi_da else ten[: toi_da - 1].rstrip() + "…"


def nhac_buoc_dang_do(session_key: str, tour_khac: bool = False) -> dict | None:
    """Khách hỏi câu khác giữa luồng (chat thường đã trả lời): lời nhắc ngắn + các nút của bước đang dở để khách đặt tiếp.
    `tour_khac` (khách đang xem tour khác với tour đang đặt): hỏi khách chọn 3 hướng: tư vấn tour mới / đặt tiếp tour cũ / huỷ.
    None = không có phiên đặt tour nào đang chạy, hoặc khách đã chọn "tiếp tục tư vấn" (tạm dừng, không nhắc nữa)."""
    st = _doc(session_key) or {}
    try:
        step = st.get("step")
        if not step or st.get("tam_dung"):
            return None
        if tour_khac and step != "chon_tour" and st.get("tour"):
            ten = st["tour"]["ten"]
            return _kq(
                f"Bạn đang trong quá trình đặt tour “{ten}”. Bạn muốn làm gì tiếp ạ?",
                [
                    {"id": "dd:tu_van", "label": "Tiếp tục tư vấn tour mới"},
                    {"id": "dd:tiep", "label": f"Tiếp tục đặt “{_ten_ngan(ten)}”"},
                    {"id": "huy", "label": f"Huỷ đặt “{_ten_ngan(ten)}”"},
                ],
            )
        if step == "chon_tour":
            return _kq("Bạn vẫn đang đặt tour dở, bạn gõ tên tour/điểm đến muốn đặt để mình hỗ trợ tiếp nhé.", [_NUT_HUY])
        ten = st["tour"]["ten"]
        if step == "chon_ngay":
            return _kq(f"Bạn đang đặt dở tour “{ten}”, bạn chọn ngày khởi hành để mình đặt tiếp nhé.", _nut_ngay(st["dots"]))
        if step == "so_nguoi":
            return _kq(f"Bạn đang đặt dở tour “{ten}”. " + _CAU_HOI_SO_NGUOI, _nut_so_nguoi())
        if step == "chon_nguoi":
            nut, toi_da = _nut_than_nhan(st)
            return _kq(f"Bạn đang đặt dở tour “{ten}”, bạn chọn người đi cùng bên dưới để mình đặt tiếp nhé.", nut, multi=True, toi_da=toi_da)
        if step == "xac_nhan":
            return _kq(f"Đơn đặt tour “{ten}” của bạn vẫn đang chờ xác nhận, bạn bấm “Đồng ý” hoặc “Không đồng ý” giúp mình nhé.", list(_NUT_XAC_NHAN))
        if step == "khong_dong_y":
            return _kq(f"Bạn đang sửa đơn đặt tour “{ten}”, bạn muốn đổi phần nào ạ?", _nut_doi(khach_web(session_key)))
    except Exception:
        pass
    return None


def _xu_ly(session_key: str, token: str, message: str, action: dict | None, st: dict, dang_chay: bool) -> dict | None:
    aid = (action or {}).get("id", "")
    values = (action or {}).get("values") or []

    # ---- nút bấm
    if aid:
        if aid == "huy":
            return _huy(session_key, st)
        if not dang_chay and not aid.startswith("tour:"):
            # Nút của phiên không có thật (hết hạn, hoặc ai đó gọi API công khai): vẫn trả lời nhưng không ghi vào lịch sử.
            return {**_kq("Phiên đặt tour đã hết hạn. Bạn nói lại “tôi muốn đặt tour…” để mình hỗ trợ nhé."), "_khong_ghi": True}
        if aid == "dd:tiep":
            # Khách chọn "Tiếp tục đặt tour cũ" sau khi xem tour khác: bỏ trạng thái tạm dừng, đưa về đúng bước đang dở.
            st.pop("tam_dung", None)
            _ghi(session_key, st)
            return nhac_buoc_dang_do(session_key) or _kq("Mình tiếp tục đặt tour giúp bạn nhé.")
        if aid == "dd:tu_van":
            # Khách chọn "Tiếp tục tư vấn tour mới": giữ đơn đang dở nhưng tạm dừng, không nhắc lại mỗi câu hỏi.
            st["tam_dung"] = True
            _ghi(session_key, st)
            ten = (st.get("tour") or {}).get("ten", "")
            return _kq(
                f"Dạ mình tiếp tục tư vấn tour mới cho bạn nhé, bạn cứ hỏi mình. Việc đặt tour “{ten}” mình vẫn giữ lại, "
                "khi nào muốn đặt tiếp bạn bấm nút bên dưới hoặc nhắn “đặt tiếp” nhé.",
                [{"id": "dd:tiep", "label": f"Tiếp tục đặt “{_ten_ngan(ten)}”"}, {"id": "huy", "label": f"Huỷ đặt “{_ten_ngan(ten)}”"}],
            )
        if aid.startswith("tour:"):
            return _chon_tour(session_key, st, aid[5:])
        # Nút của bước cũ (khách bấm lại nút đã qua) -> đưa về đúng bước đang dở thay vì lỗi.
        if "tour" not in st:
            return _hoi_chon_tour(session_key, st, [])
        if not aid.startswith("dot:") and "dot" not in st:
            return _quay_lai_chon_ngay(session_key, st)
        if not aid.startswith(("dot:", "sl:")) and "adults" not in st:
            return _hoi_so_nguoi(session_key, st)
        if aid.startswith("dot:"):
            dot = next((d for d in st.get("dots", []) if d["key"] == aid[4:]), None)
            if dot:
                return _chon_dot(session_key, st, dot)
            if st.get("dots"):
                return _quay_lai_chon_ngay(session_key, st)
            return _kq("Mình không tìm thấy ngày này. Bạn nói lại tên tour muốn đặt giúp mình nhé.", [_NUT_HUY])
        if aid.startswith("sl:"):
            try:
                a, c, i = (int(x) for x in aid[3:].split(","))
            except ValueError:
                return None
            return _chon_so_nguoi(session_key, st, token, a, c, i)
        if aid.startswith("nguoi:"):
            chon = [] if aid == "nguoi:skip" else [v for v in values if any(r["id"] == v for r in st.get("rels", []))]
            toi_da = st["adults"] + st["children"] + st["infants"] - 1
            st["relative_ids"] = chon[:toi_da]
            return _tom_tat(session_key, st)
        if aid == "xn:dong_y":
            return _dong_y(session_key, st, token)
        if aid == "xn:khong":
            return _khong_dong_y(session_key, st)
        if aid == "doi:ngay":
            return _quay_lai_chon_ngay(session_key, st)
        if aid == "doi:so_nguoi":
            return _hoi_so_nguoi(session_key, st)
        if aid == "doi:nguoi":
            return _hoi_nguoi_di_cung(session_key, st, token)
        return None

    # ---- gõ chữ
    if dang_chay and _muon_huy(message, st.get("step")):
        return _huy(session_key, st)

    # Đang đặt dở mà muốn "đổi lịch khởi hành" / "đổi ngày": là đổi ngày của đơn này, không phải chuyển nhân viên.
    cau = _chuan(message)
    if dang_chay and st.get("step") != "chon_tour" and "tour" in st and _DOI_NGAY.search(cau) and "da dat" not in cau and not _DA_DAT.search(cau):
        return _quay_lai_chon_ngay(session_key, st)

    # Đang đặt dở: "quay lại", "làm lại từ đầu", "đổi sang tour Đà Lạt".
    if dang_chay and "tour" in st and st.get("step") != "chon_tour" and "da dat" not in cau:
        if _QUAY_LAI.match(cau):
            return _lui_mot_buoc(session_key, st)
        if _DOI_TOUR.search(cau) and not _la_cau_hoi(message):
            moi = {"last_tours": st.get("last_tours", []), "step": None}
            cands = _tim_ung_vien(message, moi)
            return _bat_dau_voi_ung_vien(session_key, moi, cands) if cands else _hoi_chon_tour(session_key, moi, [], message)
        if _LAM_LAI.search(cau) and not tim_tour_theo_cau(message):
            return _quay_lai_chon_ngay(session_key, st)

    # Khiếu nại / hoàn tiền / muốn gặp người thật: nhường cho luồng chuyển nhân viên (main.py), giữ nguyên phiên đặt tour.
    if hoi_muon_gap_nhan_vien(message):
        return None

    if hoi_dat_tour(message) or (not dang_chay and chi_noi_muon_dat(message)):
        cands = _tim_ung_vien(message, st)
        if not dang_chay and not cands and _la_cau_hoi(message):
            # Bug thật: "Đặt tour qua chat thì có cần gửi CCCD không?" bị cuốn vào luồng đặt tour ("chưa tìm thấy tour…")
            return None
        if dang_chay and not st.get("tam_dung") and st.get("step") != "chon_tour" and _van_la_tour_dang_dat(message, st, cands):
            pass  # "ok chốt tour này", "đặt tour này cho 3 người lớn": vẫn là tour đang đặt -> là câu trả lời của bước đang dở
        elif not dang_chay or cands or st.get("step") == "chon_tour" or st.get("tam_dung"):
            # Đang tạm dừng (khách chọn "tiếp tục tư vấn tour mới"): "đặt tour này" là nói về tour vừa tư vấn, mở luồng đặt mới.
            # Bắt đầu mới (hoặc đổi sang tour khác giữa chừng): giữ lại danh sách tour vừa gợi ý, bỏ phần còn lại.
            moi = {"last_tours": st.get("last_tours", []), "step": None}
            return _bat_dau_voi_ung_vien(session_key, moi, cands, message)

    if not dang_chay:
        return None

    # Đang tạm dừng việc đặt tour để tư vấn tour mới: chỉ khi khách nói rõ "đặt tiếp" mới quay lại; còn lại để chat thường trả lời.
    if st.get("tam_dung"):
        if _DAT_TIEP.search(cau):
            st.pop("tam_dung", None)
            _ghi(session_key, st)
            return nhac_buoc_dang_do(session_key)
        return None

    # Khách HỎI câu khác giữa luồng (vd "visa có khó không?") mà bước đang dở không đọc ra câu trả lời hợp lệ nào
    # -> trả None để chat thường (main.py) trả lời; phiên đặt GIỮ NGUYÊN, main.py gắn lời nhắc + nút của bước (nhac_buoc_dang_do).
    step = st["step"]
    nd = _nd(message)
    hoi = _la_cau_hoi(message)
    if step == "chon_tour":
        cands = _tim_ung_vien("đặt tour " + message, st)
        return None if hoi and not cands else _bat_dau_voi_ung_vien(session_key, st, cands, message)
    if step == "chon_ngay":
        dot = _doan_ngay(message, st.get("dots", []), chi_ngay_ro=hoi)
        if dot:
            return _chon_dot(session_key, st, dot)
        return None if hoi else _kq("Mình chưa hiểu ngày bạn chọn. Bạn bấm vào một ngày bên dưới nhé.", _nut_ngay(st.get("dots", [])))
    if step == "so_nguoi":
        r = phan_tich_so_nguoi(message, can_don_vi=hoi)
        if r:
            return _chon_so_nguoi(session_key, st, token, *r)
        return None if hoi else _hoi_so_nguoi(session_key, st, "Mình chưa đọc được số người.")
    if step == "chon_nguoi":
        if _BO_QUA_RO.search(nd):
            st["relative_ids"] = []
            return _tom_tat(session_key, st)
        # Dò tên TRƯỚC: "đi với Lan thôi" là chọn Lan, không phải bỏ qua.
        chon = _chon_nguoi_theo_ten(_chuan(message), st.get("rels", []))
        nut, toi_da = _nut_than_nhan(st)
        if chon:
            st["relative_ids"] = chon[:toi_da]
            return _tom_tat(session_key, st)
        if hoi:
            return None
        if _BO_QUA.search(nd):
            st["relative_ids"] = []
            return _tom_tat(session_key, st)
        return _kq("Mình chưa nhận ra tên nào trong danh sách thân nhân. Bạn chọn bằng các nút bên dưới nhé (hoặc chọn “Nhập sau ở trang booking”).", nut, multi=True, toi_da=toi_da)
    if step == "xac_nhan":
        if hoi:
            return None  # "thanh toán bằng thẻ được chứ?" là câu hỏi, không phải Đồng ý / Không đồng ý
        if _KHONG.search(nd):
            return _khong_dong_y(session_key, st)
        if _DONG_Y.search(nd):
            return _dong_y(session_key, st, token)
        return _kq("Bạn bấm “Đồng ý” hoặc “Không đồng ý” giúp mình nhé.", list(_NUT_XAC_NHAN))
    if step == "khong_dong_y":
        if "ngay" in nd:
            return _quay_lai_chon_ngay(session_key, st)
        if "nguoi" in nd and ("di cung" in nd or "than" in nd):
            return _hoi_nguoi_di_cung(session_key, st, token)
        if "nguoi" in nd or "so" in nd.split():
            return _hoi_so_nguoi(session_key, st)
        if hoi:
            return None
        if _DONG_Y.search(nd) and not _KHONG.search(nd):
            return _dong_y(session_key, st, token)
        if re.search(r"\b(giu nguyen|khong doi|khong can doi)\b", nd):
            return _tom_tat(session_key, st)  # nghĩ lại, không đổi nữa -> quay về bảng tóm tắt
        return _khong_dong_y(session_key, st)
    return None


_DAT_TIEP = re.compile(r"\b(dat|chot) tiep\b|\btiep tuc (viec )?(dat|chot)\b|\bquay lai (viec )?(dat|chot)\b")
_QUAY_LAI = re.compile(r"^(quay lai|lui lai|tro lai|buoc truoc|back)( buoc truoc| di| nha| nhe| a| ban)*$")
_DOI_TOUR = re.compile(r"\b(doi|chuyen|sang) (sang |qua |lai )?tour\b|\btour khac\b")
_LAM_LAI = re.compile(r"\b(lam lai|dat lai|bat dau lai|nhap lai)\b|\btu dau\b")


def _lui_mot_buoc(session_key: str, st: dict) -> dict:
    """"Quay lại": về bước ngay trước bước đang dở (số người -> chọn ngày; tóm tắt/chọn người -> số người)."""
    if st.get("step") in ("xac_nhan", "khong_dong_y", "chon_nguoi"):
        return _hoi_so_nguoi(session_key, st)
    return _quay_lai_chon_ngay(session_key, st)


def _van_la_tour_dang_dat(message: str, st: dict, cands: list[dict]) -> bool:
    """Đang đặt dở tour X mà khách nói "đặt tour này…" / gọi lại đúng tour X -> không bắt đầu lại từ đầu.
    ("đặt lại tour …" thì vẫn làm lại từ đầu.)"""
    key = (st.get("tour") or {}).get("key")
    cau = _chuan(message)
    if not key or re.search(r"\b(dat|lam|chon) lai\b", cau):
        return False
    if [c["key"] for c in cands] == [key]:
        return True
    return bool(_CHI_TOUR_VUA_GOI_Y.search(cau)) and not _thu_tu(cau, len(st.get("last_tours") or [])) and not tim_tour_theo_cau(message)


def _quay_lai_chon_ngay(session_key: str, st: dict) -> dict:
    dots = st.get("dots", [])
    if len(dots) <= 1 and "dot" not in st:
        return _chon_tour(session_key, st, st["tour"]["key"])  # chưa có ngày nào được chọn: lấy lại danh sách ngày
    if len(dots) <= 1:
        if "adults" not in st:
            return _hoi_so_nguoi(session_key, st, "Tour này chỉ có một ngày khởi hành còn chỗ.")
        st["step"] = "xac_nhan"
        _ghi(session_key, st)
        return _kq("Tour này chỉ có một ngày khởi hành còn chỗ nên mình chưa đổi được ngày. Bạn muốn giữ nguyên hay đổi phần khác ạ?", [
            {"id": "xn:dong_y", "label": "Giữ nguyên, đồng ý"},
            {"id": "doi:so_nguoi", "label": "Đổi số người"}] + [n for n in _nut_doi(khach_web(session_key)) if n["id"] == "doi:nguoi"] + [_NUT_HUY])
    st["step"] = "chon_ngay"
    _ghi(session_key, st)
    return _kq("Bạn chọn ngày khởi hành khác nhé." + _ghi_chu_ngay(dots), _nut_ngay(dots))


def _bat_dau_voi_ung_vien(session_key: str, st: dict, cands: list[dict], cau: str = "") -> dict:
    if len(cands) == 1:
        return _chon_tour(session_key, st, cands[0]["key"])
    if not cands:
        return _hoi_chon_tour(session_key, st, [], cau)
    st["step"] = "chon_tour"
    _ghi(session_key, st)
    return _kq(
        "Mình thấy có vài tour phù hợp, bạn muốn đặt tour nào ạ?",
        [{"id": f"tour:{c['key']}", "label": c["ten"][:60]} for c in cands[:5]] + [_NUT_HUY],
    )


def _doan_ngay(text: str, dots: list[dict], chi_ngay_ro: bool = False) -> dict | None:
    """Hiểu "20/12", "20-12-2026", "ngày 20 tháng 12", chỉ "ngày 20" / "tháng 1" (khi đúng 1 đợt khớp), hoặc "ngày đầu/cuối".
    chi_ngay_ro=True (câu hỏi): chỉ nhận khi khách nêu ngày/tháng bằng số."""
    nd = _nd(text)
    m = re.search(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?:\s*[/\-.]\s*(\d{2,4}))?", nd) or re.search(r"(\d{1,2})\s*thang\s*(\d{1,2})", nd)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        khop = [x for x in dots if int(x["date"][8:10]) == d and int(x["date"][5:7]) == mo]
        if len(khop) == 1:
            return khop[0]
    else:
        mn, mt = re.search(r"\bngay\s*(\d{1,2})\b", nd), re.search(r"\bthang\s*(\d{1,2})\b", nd)
        if mn or mt:
            khop = [
                x for x in dots
                if (not mn or int(x["date"][8:10]) == int(mn.group(1))) and (not mt or int(x["date"][5:7]) == int(mt.group(1)))
            ]
            if len(khop) == 1:
                return khop[0]
    if chi_ngay_ro or not dots:
        return None
    # Chỉ "ngày đầu" / "ngày cuối": chữ "đầu", "cuối" đứng riêng còn là "ở đâu", "cuối tuần", "cuối tháng 12"
    if re.search(r"\b(som nhat|gan nhat|dau tien|(ngay|dot|cai) dau)\b", nd):
        return dots[0]
    if re.search(r"\b(muon nhat|cuoi cung|sau cung|(ngay|dot|cai) cuoi(?! (tuan|thang|nam)))\b", nd):
        return dots[-1]
    return None
