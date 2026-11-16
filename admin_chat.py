"""Nối chatbot với trang quản trị hội thoại (D:\\btt-chat-admin). Hợp đồng API: docs/ingest-api.md bên đó.

Trang quản trị ngừng chạy KHÔNG được làm khách mất chatbot, cũng không được làm mất lịch sử: gọi backend không được thì
ghi thẳng vào database (lich_su_db.py) ngay lúc đó. Các hàm ở đây không ném lỗi ra ngoài.
Không ghi log nội dung tin nhắn, tên hay số điện thoại của khách.
"""
import json
import logging
import time
import uuid

import httpx

import config
import lich_su_db

log = logging.getLogger("admin_chat")

DO_DAI_TIN_KHACH_TOI_DA = 4000  # giới hạn của /ingest/inbound
DO_DAI_TIN_TOI_DA = 8000  # giới hạn của /ingest/bot-reply
TAM_NGUNG_GOI_GIAY = 15

_khong_ket_noi_duoc_luc = float("-inf")

# Máy chủ tắt thì báo lỗi kết nối nhanh, không bắt khách chờ đủ 4 giây.
_client = httpx.Client(timeout=httpx.Timeout(4.0, connect=1.5))
# Tải file lên lâu hơn tin chữ: backend thu nhỏ ảnh rồi mới lưu.
_client_tep = httpx.Client(timeout=httpx.Timeout(30.0, connect=3.0))


def da_cau_hinh() -> bool:
    return bool(config.ADMIN_CHAT_URL and config.INGEST_API_KEY)


def ma_tin_moi() -> str:
    """Mã chống ghi trùng: backend hết giờ chờ nhưng thực ra đã ghi thì lần ghi thẳng sẽ bị bỏ qua."""
    return str(uuid.uuid4())


def _goi(phuong_thuc: str, duong_dan: str, **kwargs) -> httpx.Response | None:
    global _khong_ket_noi_duoc_luc
    if not da_cau_hinh():
        return None
    # Vừa gọi không được thì khỏi thử lại ngay: mỗi lần thử bắt khách chờ thêm tới 1,5 giây (Windows).
    if time.monotonic() - _khong_ket_noi_duoc_luc < TAM_NGUNG_GOI_GIAY:
        return None
    try:
        return _client.request(
            phuong_thuc,
            f"{config.ADMIN_CHAT_URL.rstrip('/')}/ingest{duong_dan}",
            headers={"x-ingest-key": config.INGEST_API_KEY},
            **kwargs,
        )
    except httpx.HTTPError as loi:
        if isinstance(loi, (httpx.ConnectError, httpx.ConnectTimeout)):
            _khong_ket_noi_duoc_luc = time.monotonic()
        log.warning("Không gọi được trang quản trị %s: %s", duong_dan, type(loi).__name__)
        return None


def _json_neu_thanh_cong(res: httpx.Response | None, duong_dan: str) -> dict | None:
    if res is None:
        return None
    if not res.is_success:
        log.warning("Trang quản trị trả %s cho %s", res.status_code, duong_dan)
        return None
    try:
        data = res.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def identify(kenh: str, ma_ngoai: str, ten: str, sdt: str) -> httpx.Response | None:
    """Trả nguyên phản hồi để main.py chuyển tiếp lỗi INVALID_PHONE / NAME_MISMATCH cho khách."""
    return _goi("POST", "/identify", json={"channel": kenh, "externalUserId": ma_ngoai, "name": ten, "phone": sdt})


def inbound(kenh: str, ma_ngoai: str, text: str, khach: dict | None, wants_human: bool, ma_tin: str | None = None) -> dict | None:
    body = {"channel": kenh, "externalUserId": ma_ngoai, "text": text[:DO_DAI_TIN_KHACH_TOI_DA], "wantsHuman": wants_human}
    if khach:
        body["customer"] = khach
    if ma_tin:
        body["externalMessageId"] = ma_tin
    return _json_neu_thanh_cong(_goi("POST", "/inbound", json=body), "/inbound")


def ghi_tin_khach_truc_tiep(kenh: str, ma_ngoai: str, khach: dict | None, text: str, luc, ma_tin: str, doi_nguoi: bool) -> None:
    """/inbound không thành công: ghi thẳng câu của khách. Giờ `luc` lấy lúc khách gửi, không phải lúc chạy việc nền."""
    tin = {"loai": "CUSTOMER", "text": text[:DO_DAI_TIN_KHACH_TOI_DA], "luc": luc, "ma_tin": ma_tin}
    lich_su_db.ghi_tin(kenh, ma_ngoai, khach, [tin], doi_nguoi=doi_nguoi)


def ghi_lich_su(kenh: str, ma_ngoai: str, khach: dict | None, tin: list[dict]) -> None:
    """Chỉ ghi lại, không báo nhân viên và không trả lời tự động: tin nhạy cảm đã bị chặn, nút bấm trong luồng đặt tour."""
    gui = [
        {
            "senderType": t["loai"],
            "text": t["text"][:DO_DAI_TIN_TOI_DA],
            "externalMessageId": t["ma_tin"],
            "createdAt": t["luc"].isoformat(timespec="milliseconds") + "Z",
        }
        for t in tin
    ]
    body = {"channel": kenh, "externalUserId": ma_ngoai, "messages": gui, **({"customer": khach} if khach else {})}
    if _json_neu_thanh_cong(_goi("POST", "/history", json=body), "/history") is None:
        lich_su_db.ghi_tin(kenh, ma_ngoai, khach, tin)


def bot_reply(kenh: str, ma_ngoai: str, text: str, tours: list | None = None, su_dung: dict | None = None, khach: dict | None = None) -> None:
    if not text:
        return
    ma_tin, luc = ma_tin_moi(), lich_su_db.bay_gio()
    body = {"channel": kenh, "externalUserId": ma_ngoai, "text": text[:DO_DAI_TIN_TOI_DA], "tours": tours or [], "externalMessageId": ma_tin}
    if khach:
        body["customer"] = khach
    if su_dung:
        body.update(su_dung)
    if _json_neu_thanh_cong(_goi("POST", "/bot-reply", json=body), "/bot-reply") is None:
        tin = {"loai": "BOT", "text": text[:DO_DAI_TIN_TOI_DA], "luc": luc, "tours": tours or None, "ma_tin": ma_tin}
        if lich_su_db.ghi_tin(kenh, ma_ngoai, khach, [tin]):
            lich_su_db.ghi_token(kenh, ma_ngoai, khach, su_dung)


def inbound_file(kenh: str, ma_ngoai: str, text: str, khach: dict | None, data: bytes, ten: str, loai: str, ma_tin: str) -> httpx.Response | None:
    """Khách gửi ảnh hoặc PDF. Trả nguyên phản hồi để chuyển tiếp lỗi "file không hợp lệ" cho khách.
    Không có đường ghi thẳng database: file phải qua backend để kiểm tra và lưu vào Storage, nên backend tắt thì chưa gửi file được."""
    if not da_cau_hinh():
        return None
    fields = {"channel": kenh, "externalUserId": ma_ngoai, "text": text[:DO_DAI_TIN_KHACH_TOI_DA], "externalMessageId": ma_tin}
    if khach:
        fields["customer"] = json.dumps(khach, ensure_ascii=False)
    try:
        return _client_tep.post(
            f"{config.ADMIN_CHAT_URL.rstrip('/')}/ingest/inbound-file",
            headers={"x-ingest-key": config.INGEST_API_KEY},
            data=fields,
            files={"file": (ten, data, loai)},
        )
    except httpx.HTTPError as loi:
        log.warning("Không gửi được file tới trang quản trị: %s", type(loi).__name__)
        return None


def link_tep(url: str) -> str:
    """Backend trả link tương đối (/files/...): thêm địa chỉ công khai của trang quản trị để app, web mở được."""
    if url.startswith(("http://", "https://")):
        return url
    return f"{(config.ADMIN_CHAT_PUBLIC_URL or config.ADMIN_CHAT_URL).rstrip('/')}{url}"


def deal(kenh: str, ma_ngoai: str, don: dict, khach: dict | None = None) -> None:
    body = {"channel": kenh, "externalUserId": ma_ngoai, **don}
    if _json_neu_thanh_cong(_goi("POST", "/deal", json=body), "/deal") is None:
        lich_su_db.ghi_don(kenh, ma_ngoai, khach, don)


def updates(kenh: str, ma_ngoai: str, sau_moc: str) -> dict | None:
    params = {"channel": kenh, "externalUserId": ma_ngoai, "after": sau_moc}
    return _json_neu_thanh_cong(_goi("GET", "/updates", params=params), "/updates")


def nhan_vien_dang_xu_ly(kenh: str, ma_ngoai: str) -> bool:
    """Hỏi backend, backend không trả lời thì đọc thẳng database. Không biết chắc thì coi như không, giới hạn vẫn giữ nguyên."""
    kq = updates(kenh, ma_ngoai, lich_su_db.bay_gio().isoformat(timespec="milliseconds") + "Z")
    return (kq.get("mode") if kq is not None else lich_su_db.che_do(kenh, ma_ngoai)) == "STAFF"
