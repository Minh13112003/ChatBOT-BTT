"""Chính sách của từng tour (cọc, huỷ/hoàn tiền, thanh toán, giá bao gồm / không bao gồm, tip, phụ thu phòng đơn, visa...) lấy trực tiếp từ
API chi tiết tour của benthanhtourist.com (đánh giá 160 câu 2026-11-23: 76 câu bị trả "chưa có thông tin" dù dữ liệu có sẵn ở đây).

Đã kiểm tra trên 68 tour đang bán: tour TRONG NƯỚC dùng chung một chính sách (cọc 50%, huỷ theo bậc 50/60/80/100%); tour NƯỚC NGOÀI cọc 50% giống
nhau nhưng mức phí huỷ, hạn thanh toán còn lại, tip... KHÁC NHAU theo từng tour (23 phiên bản phí huỷ). Vì vậy lấy theo đúng tour khách đang hỏi;
chưa nói tour nào thì đưa mẫu trong nước + một tour nước ngoài làm ví dụ và bảo AI hỏi lại khách."""
import html
import re
import threading
import time

import httpx

from config import BENTHANH_API_BASE, BENTHANH_HEADERS
from rag import bo_dau

HAN_CACHE_GIAY = 6 * 3600
TIMEOUT_GIAY = 8
SO_TOUR_TOI_DA = 2
# (tên trường trong API, nhãn đưa cho AI, số ký tự tối đa)
TRUONG = (
    ("tuts_booking_payment", "Đặt cọc và thanh toán", 700),
    ("punishment_cancel_booking", "Phí huỷ / hoãn tour", 1400),
    ("cancel_booking", "Thủ tục huỷ, hoàn tiền", 1200),
    ("tour_price_included", "Giá tour BAO GỒM", 1300),
    ("tour_price_not_included", "Giá tour KHÔNG bao gồm (tiền tip, phụ thu phòng đơn...)", 900),
    ("warning_note", "Lưu ý quan trọng (độ tuổi, không đủ khách, bất khả kháng, bị từ chối nhập cảnh...)", 4500),
    ("warning_note_visa", "Lưu ý visa", 700),
)

_cache: dict[str, tuple[float, dict | None]] = {}
_khoa = threading.Lock()

# Khách hỏi về tiền / giấy tờ / dịch vụ đi kèm tour. Chỉ để THÊM dữ liệu vào câu trả lời, không đổi luồng khác.
_MAU_HOI_CHINH_SACH = re.compile(
    r"\b(coc|huy|hoan tien|hoan tour|hoan|phat|phi huy|doi ngay|doi tour|thanh toan|chuyen khoan|tra gop|phu thu|phong don|tip|boi duong|"
    r"bao gom|khong gom|da gom|gia tour gom|bao hiem|hanh ly|visa|ho chieu|passport|rot visa|tu choi nhap canh|thien tai|bao lut|bat kha khang|"
    r"khong du khach|so luong toi thieu|dieu khoan|chinh sach|quy dinh|dieu kien|tuoi|suc khoe|giay kham|giay xac nhan|mang thai|dang bau|co bau|"
    r"xe lan|an chay|di ung|thu cung|chuyen nhuong|doi ten|hoa don|vat|sim|wifi)\b"
)


def hoi_chinh_sach(cau_hoi: str) -> bool:
    return bool(_MAU_HOI_CHINH_SACH.search(bo_dau(cau_hoi.lower())))


def _lam_sach(v) -> str:
    if not isinstance(v, str):
        return ""
    v = re.sub(r"</(li|p|div|h\d)>|<br\s*/?>", "\n", v)
    v = re.sub(r"<[^>]+>", " ", v)
    v = html.unescape(v)
    return "\n".join(re.sub(r"[ \t\xa0]+", " ", dong).strip() for dong in v.splitlines() if dong.strip())


def lay_chinh_sach(tour_key: str) -> dict | None:
    """Chính sách đã làm sạch của một tour (lưu tạm 6 giờ). None = không lấy được (mạng lỗi), khi đó chatbot nói chưa có thông tin."""
    now = time.time()
    with _khoa:
        c = _cache.get(tour_key)
        if c and now - c[0] < HAN_CACHE_GIAY:
            return c[1]
    ket_qua = None
    try:
        r = httpx.get(f"{BENTHANH_API_BASE}/item", params={"tour_key": tour_key}, headers=BENTHANH_HEADERS, timeout=TIMEOUT_GIAY)
        d = r.json().get("data")
        if isinstance(d, dict):
            ket_qua = {"ten": str(d.get("name") or ""), "nuoc_ngoai": "/nuoc-ngoai/" in str(d.get("image") or ""),
                       **{k: _lam_sach(d.get(k)) for k, _, _ in TRUONG}}
    except Exception:
        ket_qua = None
    if ket_qua is not None:  # lỗi mạng thì không nhớ, lần sau thử lại
        with _khoa:
            _cache[tour_key] = (now, ket_qua)
    return ket_qua


def _tour_mau() -> tuple[str | None, str | None]:
    """(tour_key trong nước, tour_key nước ngoài) mẫu lấy từ dữ liệu tour đang bán, khi khách chưa nói tour nào."""
    import rag
    trong = ngoai = None
    for m in rag.tat_ca_luot_con_han():
        if not m.get("tour_key"):
            continue
        if m.get("loai_hinh") == "Trong Nước" and not trong:
            trong = str(m["tour_key"])
        elif m.get("loai_hinh") == "Nước Ngoài" and not ngoai:
            ngoai = str(m["tour_key"])
        if trong and ngoai:
            break
    return trong, ngoai


def _mo_ta(cs: dict, nhan_nhom: str) -> str:
    dong = [f"[{nhan_nhom}: {cs['ten']}]"]
    for k, nhan, toi_da in TRUONG:
        v = cs.get(k) or ""
        if v:
            dong.append(f"- {nhan}: " + (v if len(v) <= toi_da else v[:toi_da].rstrip() + "…"))
    return "\n".join(dong)


_HUONG_DAN = (
    "CHÍNH SÁCH THEO TỪNG TOUR (lấy trực tiếp từ chương trình tour trên hệ thống BenThanh). Đây là nguồn DUY NHẤT để trả lời câu hỏi về "
    "cọc, thanh toán, phí huỷ / hoàn tiền, giá bao gồm / không bao gồm, tiền tip, phụ thu phòng đơn, hành lý, bảo hiểm, visa.\n"
    "Cách trả lời: nêu đúng số liệu và mốc ngày như dưới đây, nói rõ áp dụng cho tour nào; không làm tròn, không suy diễn, không thêm mức không có. "
    "Mục khách hỏi mà khối này không có thì nói mình chưa có thông tin chính xác và mời gọi hotline 1900 6668 hoặc nhắn \"gặp nhân viên\". "
    "Ngày huỷ tính theo ngày làm việc nếu dữ liệu ghi vậy. "
    "NGUYÊN TẮC: (1) chỉ nêu điều CÓ GHI, tuyệt đối không suy ra giới hạn hay quy định không ghi (khách hỏi một mốc tuổi, số tiền, số người mà dữ liệu "
    "không nhắc thì nói dữ liệu chỉ ghi mốc nào, và nói chưa có thông tin cho mốc khách hỏi); (2) giữ đúng mức cam kết của dữ liệu: ghi \"xem xét\", "
    "\"trong điều kiện có thể\" thì không viết thành \"sẽ chắc chắn hoàn trả\"; (3) chỉ nói số liệu cho đúng các tour có trong khối này, "
    "tour khác không có thì nói rõ chưa có số liệu."
)


def khoi_chinh_sach(cau_hoi: str, the_tour: list[dict], lay=None, mau=None) -> str | None:
    """Khối chính sách đưa vào prompt Gemini cho câu hỏi chính sách; None nếu câu không hỏi chính sách hoặc không lấy được dữ liệu."""
    if not hoi_chinh_sach(cau_hoi):
        return None
    lay = lay or lay_chinh_sach
    mau = mau or _tour_mau
    keys, thay = [], set()
    for t in the_tour or []:
        k = str(t.get("tour_key") or "")
        if k and k not in thay:
            thay.add(k)
            keys.append(k)
    phan: list[str] = []
    if keys:
        for k in keys[:SO_TOUR_TOI_DA]:
            cs = lay(k)
            if cs:
                phan.append(_mo_ta(cs, "Tour nước ngoài" if cs.get("nuoc_ngoai") else "Tour trong nước"))
        if phan:
            if any("nước ngoài" in p.split("]", 1)[0] for p in phan):
                phan.append("Lưu ý: tour nước ngoài khác nhau về phí huỷ, hạn thanh toán, tiền tip; mức trên chỉ áp dụng cho đúng tour nêu tên.")
    else:
        trong, ngoai = mau()
        cs_trong = lay(trong) if trong else None
        cs_ngoai = lay(ngoai) if ngoai else None
        if cs_trong:
            phan.append(_mo_ta(cs_trong, "MẪU tour TRONG NƯỚC (các tour trong nước dùng chung chính sách cọc, huỷ, thanh toán này)"))
        if cs_ngoai:
            phan.append(_mo_ta(cs_ngoai, "VÍ DỤ một tour NƯỚC NGOÀI (mỗi tour nước ngoài có phí huỷ, hạn thanh toán, tip khác nhau)"))
            phan.append("Khách chưa nói tour hay nước nào: trả lời phần chung, nêu ví dụ trên và hỏi khách quan tâm tour / nước nào để báo mức chính xác.")
    if not phan:
        return None
    return _HUONG_DAN + "\n\n" + "\n\n".join(phan)
