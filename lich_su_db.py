"""Ghi thẳng lịch sử chat vào database của trang quản trị (D:\\btt-chat-admin) khi không gọi được backend bên đó.

Chỉ GHI LẠI, không chia việc và không gửi gì cho khách: khách đòi gặp nhân viên thì hội thoại thành CONTACT chưa có người,
bộ chia việc 30 giây một lần bên backend sẽ tự chia khi backend chạy lại.

Bảng do Prisma quản lý: nguồn chuẩn là backend/prisma/schema.prisma bên đó. Đổi bảng customers, customer_identities,
conversations, messages, deals, ai_usage thì phải sửa file này theo. Prisma tự sinh id và updatedAt ở phía ứng dụng nên
SQL ở đây phải tự điền. Không ghi log nội dung tin, tên hay số điện thoại của khách.
"""
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.types.json import Jsonb

import config

log = logging.getLogger("lich_su_db")

TIMEOUT_KET_NOI_GIAY = 5
_MAY_NOI_BO = {"localhost", "127.0.0.1", "::1"}
TEN_KHONG_KHOP = "Số điện thoại này đã được dùng với một tên khác. Bạn vui lòng nhập lại họ tên và số điện thoại giúp mình nhé."


def da_cau_hinh() -> bool:
    return bool(config.ADMIN_DATABASE_URL)


def bay_gio() -> datetime:
    """Prisma lưu DateTime là giờ UTC không kèm múi giờ, chính xác tới mili giây."""
    now = datetime.now(timezone.utc)
    return now.replace(tzinfo=None, microsecond=now.microsecond // 1000 * 1000)


# ---------------------------------------------------------------- hàm thuần, chép đúng từ backend/src/common/text.ts
def _bo_dau(text: str) -> str:
    bo = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return bo.replace("đ", "d").replace("Đ", "D")


def _tach_ten(ten: str) -> list[str]:
    return _bo_dau(ten).lower().split()


def chuan_hoa_sdt(raw: str | None) -> str | None:
    so = re.sub(r"[^\d+]", "", raw or "")
    if so.startswith("+84"):
        so = "0" + so[3:]
    elif so.startswith("84") and len(so) == 11:
        so = "0" + so[2:]
    return so if re.fullmatch(r"0\d{9}", so) else None


def cung_mot_nguoi(a: str, b: str) -> bool:
    ta, tb = _tach_ten(a), _tach_ten(b)
    if not ta or not tb:
        return False
    if ta[-1] == tb[-1]:
        return True
    ngan, dai = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return all(t in dai for t in ngan)


def gop_ten(hien_tai: str, aliases: list[str], moi: str) -> tuple[str, list[str]]:
    ten = " ".join(moi.split())
    tat_ca = [hien_tai, *aliases, ten]
    chinh = hien_tai
    for x in tat_ca:
        if len(_tach_ten(x)) > len(_tach_ten(chinh)):
            chinh = x
    khac: dict[str, str] = {}
    for x in tat_ca:
        khoa = _bo_dau(x).lower()
        if khoa != _bo_dau(chinh).lower() and khoa not in khac:
            khac[khoa] = x
    return chinh, list(khac.values())


def tom_tat(text: str, toi_da: int = 120) -> str:
    t = " ".join(text.split())
    return f"{t[: toi_da - 1]}…" if len(t) > toi_da else t


def chuoi_ket_noi(url: str) -> str:
    """Bỏ tham số riêng của Prisma (psycopg không nhận); máy chủ từ xa thì bắt buộc mã hoá."""
    phan = urlsplit(url)
    tham_so = [(k, v) for k, v in parse_qsl(phan.query) if k not in ("pgbouncer", "connection_limit")]
    if phan.hostname not in _MAY_NOI_BO and not any(k == "sslmode" for k, _ in tham_so):
        tham_so.append(("sslmode", "require"))
    return urlunsplit((phan.scheme, phan.netloc, phan.path, urlencode(tham_so), phan.fragment))


# ---------------------------------------------------------------- đọc ghi database
def _ket_noi():
    # prepare_threshold=None: an toàn khi đi qua pooler của Supabase.
    return psycopg.connect(chuoi_ket_noi(config.ADMIN_DATABASE_URL), connect_timeout=TIMEOUT_KET_NOI_GIAY, prepare_threshold=None)


def _tim_khach(cur, kenh: str, ma_ngoai: str, khach: dict | None, luc: datetime) -> str:
    cur.execute('SELECT "customerId" FROM customer_identities WHERE channel = %s::"Channel" AND "externalId" = %s', (kenh, ma_ngoai))
    dong = cur.fetchone()
    if dong:
        return dong[0]

    khach = khach or {}
    sdt = chuan_hoa_sdt(khach.get("phone"))
    ten = (khach.get("name") or "").strip() or "Khách chưa rõ tên"
    if sdt:
        # DO UPDATE vô hại để RETURNING luôn trả id, kể cả khi 2 tin cùng lúc tạo trùng một số.
        cur.execute(
            'INSERT INTO customers (id, name, phone, "phoneVerified", "updatedAt") VALUES (%s, %s, %s, %s, %s) '
            'ON CONFLICT (phone) DO UPDATE SET phone = EXCLUDED.phone RETURNING id',
            (str(uuid.uuid4()), ten, sdt, kenh == "APP", luc),
        )
    else:
        cur.execute(
            'INSERT INTO customers (id, name, "updatedAt") VALUES (%s, %s, %s) RETURNING id',
            (str(uuid.uuid4()), ten, luc),
        )
    ma_khach = cur.fetchone()[0]
    cur.execute(
        'INSERT INTO customer_identities (id, channel, "externalId", "customerId") VALUES (%s, %s::"Channel", %s, %s) '
        'ON CONFLICT (channel, "externalId") DO UPDATE SET "externalId" = EXCLUDED."externalId" RETURNING "customerId"',
        (str(uuid.uuid4()), kenh, ma_ngoai, ma_khach),
    )
    return cur.fetchone()[0]


def _hoi_thoai(cur, ma_khach: str, kenh: str, luc: datetime) -> str:
    cur.execute(
        'INSERT INTO conversations (id, "customerId", channel, "updatedAt") VALUES (%s, %s, %s::"Channel", %s) '
        'ON CONFLICT ("customerId", channel) DO UPDATE SET channel = EXCLUDED.channel RETURNING id',
        (str(uuid.uuid4()), ma_khach, kenh, luc),
    )
    return cur.fetchone()[0]


def _them_tin(cur, ma_hoi_thoai: str, loai: str, text: str, luc: datetime, *, noi_bo=False, doi_nguoi=False, tours=None, ma_tin=None) -> bool:
    cur.execute(
        'INSERT INTO messages (id, "conversationId", "senderType", text, internal, "isTrigger", tours, "externalMessageId", "createdAt") '
        'VALUES (%s, %s, %s::"SenderType", %s, %s, %s, %s, %s, %s) ON CONFLICT ("externalMessageId") DO NOTHING RETURNING id',
        (str(uuid.uuid4()), ma_hoi_thoai, loai, text, noi_bo, doi_nguoi, Jsonb(tours) if tours else None, ma_tin, luc),
    )
    return cur.fetchone() is not None


def _cap_nhat_hoi_thoai(cur, ma_hoi_thoai: str, text: str, luc: datetime, cua_khach: bool) -> None:
    # Cùng quy tắc với ingest.service.ts: khách nhắn lại vào hội thoại đã xem hoặc đã chốt thì đưa về danh sách cần xử lý.
    cur.execute(
        'UPDATE conversations SET "lastMessageAt" = GREATEST("lastMessageAt", %s::timestamp), "lastMessagePreview" = %s, "updatedAt" = %s, '
        "status = CASE WHEN %s::boolean AND status IN ('READ', 'CLOSED') "
        "THEN (CASE WHEN mode = 'STAFF' THEN 'PENDING' ELSE 'UNREAD' END)::\"ConversationStatus\" ELSE status END "
        "WHERE id = %s",
        (luc, tom_tat(text), luc, cua_khach, ma_hoi_thoai),
    )


def ghi_tin(kenh: str, ma_ngoai: str, khach: dict | None, tin: list[dict], doi_nguoi: bool = False) -> bool:
    """`tin`: các dict {loai: CUSTOMER|BOT, text, luc?, tours?, ma_tin?}. Tất cả trong một transaction, trả False nếu không ghi được."""
    if not da_cau_hinh() or not tin:
        return False
    try:
        with _ket_noi() as conn, conn.cursor() as cur:
            luc_dau = tin[0].get("luc") or bay_gio()
            ma_hoi_thoai = _hoi_thoai(cur, _tim_khach(cur, kenh, ma_ngoai, khach, luc_dau), kenh, luc_dau)
            for t in tin:
                luc = t.get("luc") or bay_gio()
                cua_khach = t["loai"] == "CUSTOMER"
                moi = _them_tin(cur, ma_hoi_thoai, t["loai"], t["text"], luc, doi_nguoi=doi_nguoi and cua_khach, tours=t.get("tours"), ma_tin=t.get("ma_tin"))
                if moi:  # trùng mã tin = backend đã kịp ghi trước khi hết giờ chờ
                    _cap_nhat_hoi_thoai(cur, ma_hoi_thoai, t["text"], luc, cua_khach)
                    if doi_nguoi and cua_khach:
                        cur.execute(
                            "UPDATE conversations SET status = 'CONTACT', \"contactRequestedAt\" = %s WHERE id = %s",
                            (luc, ma_hoi_thoai),
                        )
                        _them_tin(cur, ma_hoi_thoai, "SYSTEM", "Khách yêu cầu gặp nhân viên lúc hệ thống quản trị không hoạt động, chuyển sang Liên hệ. Chưa chia người", luc, noi_bo=True)
        return True
    except Exception as loi:  # Lưu lịch sử hỏng không được làm hỏng câu trả lời của khách.
        log.warning("Không ghi được lịch sử vào database: %s", type(loi).__name__)
        return False


def che_do(kenh: str, ma_ngoai: str) -> str | None:
    """Chế độ hội thoại (BOT hoặc STAFF) của khách, None nếu chưa có hội thoại hoặc không đọc được."""
    if not da_cau_hinh():
        return None
    try:
        with _ket_noi() as conn, conn.cursor() as cur:
            cur.execute(
                'SELECT c.mode::text FROM customer_identities i JOIN conversations c '
                'ON c."customerId" = i."customerId" AND c.channel = i.channel '
                'WHERE i.channel = %s::"Channel" AND i."externalId" = %s',
                (kenh, ma_ngoai),
            )
            dong = cur.fetchone()
        return dong[0] if dong else None
    except Exception as loi:
        log.warning("Không đọc được chế độ hội thoại: %s", type(loi).__name__)
        return None


def ghi_token(kenh: str, ma_ngoai: str, khach: dict | None, su_dung: dict | None) -> bool:
    if not da_cau_hinh() or not su_dung:
        return False
    try:
        with _ket_noi() as conn, conn.cursor() as cur:
            luc = bay_gio()
            ma_hoi_thoai = _hoi_thoai(cur, _tim_khach(cur, kenh, ma_ngoai, khach, luc), kenh, luc)
            cur.execute(
                'INSERT INTO ai_usage (id, "conversationId", model, "inputTokens", "outputTokens") VALUES (%s, %s, %s, %s, %s)',
                (str(uuid.uuid4()), ma_hoi_thoai, su_dung["model"], su_dung["inputTokens"], su_dung["outputTokens"]),
            )
        return True
    except Exception as loi:
        log.warning("Không ghi được token vào database: %s", type(loi).__name__)
        return False


def ghi_don(kenh: str, ma_ngoai: str, khach: dict | None, don: dict) -> bool:
    if not da_cau_hinh():
        return False
    try:
        with _ket_noi() as conn, conn.cursor() as cur:
            luc = bay_gio()
            ma_khach = _tim_khach(cur, kenh, ma_ngoai, khach, luc)
            ma_hoi_thoai = _hoi_thoai(cur, ma_khach, kenh, luc)
            # status, source để mặc định của database: PENDING (chờ sale gọi xác nhận), CHATBOT. Như /ingest/deal.
            ma_tour = (don.get("tourCode") or "").replace(" ", "").upper()[:60] or None
            cur.execute(
                'INSERT INTO deals (id, "conversationId", "customerId", channel, "orderCode", "tourCode", "tourName", guests, amount) '
                'VALUES (%s, %s, %s, %s::"Channel", %s, %s, %s, %s, %s) ON CONFLICT ("orderCode") DO NOTHING RETURNING id',
                (str(uuid.uuid4()), ma_hoi_thoai, ma_khach, kenh, don.get("orderCode"), ma_tour, don["tourName"], don["guests"], don["amount"]),
            )
            if cur.fetchone():
                # Chờ xử lý, chưa phải Đã chốt. Backend chạy lại thì chiaLai tự chia cho một sale (hội thoại chưa ai phụ trách có đơn chờ).
                cur.execute("UPDATE conversations SET status = 'PENDING', \"updatedAt\" = %s WHERE id = %s AND status <> 'CONTACT'", (luc, ma_hoi_thoai))
                tien = f"{don['amount']:,}".replace(",", ".")
                ma = ", ".join(x for x in [ma_tour and f"mã tour {ma_tour}", don.get("orderCode") and f"mã đơn {don['orderCode']}"] if x)
                _them_tin(cur, ma_hoi_thoai, "SYSTEM", f"Khách tự đặt {don['tourName']} qua bttAI{f' ({ma})' if ma else ''}, {don['guests']} khách, {tien} đ. Đơn chờ sale gọi xác nhận.", luc, noi_bo=True)
        return True
    except Exception as loi:
        log.warning("Không ghi được đơn vào database: %s", type(loi).__name__)
        return False


def dinh_danh(kenh: str, ma_ngoai: str, ten: str, sdt_raw: str) -> dict | None:
    """Như /ingest/identify. Trả {returning, loadHistory}, {code: NAME_MISMATCH}, hoặc None nếu không ghi được."""
    sdt = chuan_hoa_sdt(sdt_raw)
    if not da_cau_hinh() or not sdt:
        return None
    try:
        with _ket_noi() as conn, conn.cursor() as cur:
            luc = bay_gio()
            cur.execute('SELECT "customerId" FROM customer_identities WHERE channel = %s::"Channel" AND "externalId" = %s', (kenh, ma_ngoai))
            dong = cur.fetchone()
            khach_cua_may = dong[0] if dong else None
            cur.execute("SELECT id, name, aliases FROM customers WHERE phone = %s", (sdt,))
            theo_so = cur.fetchone()
            if theo_so:
                ma_khach, ten_cu, aliases = theo_so
                if not cung_mot_nguoi(ten_cu, ten) and not any(cung_mot_nguoi(a, ten) for a in aliases):
                    return {"code": "NAME_MISMATCH", "message": TEN_KHONG_KHOP}
                ten_moi, aliases_moi = gop_ten(ten_cu, aliases, ten)
                cur.execute('UPDATE customers SET name = %s, aliases = %s, "updatedAt" = %s WHERE id = %s', (ten_moi, aliases_moi, luc, ma_khach))
            else:
                cur.execute(
                    'INSERT INTO customers (id, name, phone, "updatedAt") VALUES (%s, %s, %s, %s) '
                    'ON CONFLICT (phone) DO UPDATE SET phone = EXCLUDED.phone RETURNING id',
                    (str(uuid.uuid4()), ten, sdt, luc),
                )
                ma_khach = cur.fetchone()[0]
            cur.execute(
                'INSERT INTO customer_identities (id, channel, "externalId", "customerId") VALUES (%s, %s::"Channel", %s, %s) '
                'ON CONFLICT (channel, "externalId") DO UPDATE SET "customerId" = EXCLUDED."customerId"',
                (str(uuid.uuid4()), kenh, ma_ngoai, ma_khach),
            )
            ma_hoi_thoai = _hoi_thoai(cur, ma_khach, kenh, luc)
            if theo_so and khach_cua_may != ma_khach:
                _them_tin(cur, ma_hoi_thoai, "SYSTEM", f'Khách quay lại từ thiết bị khác, nhập tên "{ten}" cùng số cũ. Phía khách không hiện tin cũ', luc, noi_bo=True)
        return {"returning": bool(theo_so), "loadHistory": khach_cua_may == ma_khach}
    except Exception as loi:
        log.warning("Không ghi được khách vào database: %s", type(loi).__name__)
        return None
