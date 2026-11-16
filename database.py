import sqlite3
from contextlib import contextmanager
from config import DATABASE_PATH


def khoi_tao_database():
    with ket_noi() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id TEXT,
                role TEXT NOT NULL,             -- 'user' hoặc 'assistant'
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tour_click_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                tour_code TEXT NOT NULL,
                tour_name TEXT NOT NULL,
                clicked_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Khách web không đăng nhập đã để lại tên + SĐT. Không tự xoá sau 3 ngày để khách quay lại không phải nhập lại.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS web_khach (
                device_id TEXT PRIMARY KEY,
                ten TEXT NOT NULL,
                sdt TEXT NOT NULL,
                doc_tu TEXT,  -- mốc sớm nhất thiết bị này được đọc tin nhân viên (máy khác nhập trùng số không đọc được tin cũ)
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON chat_messages(session_id)")
        # [GEMINI] T-003: Đảm bảo có cột user_id và index
        cursor = conn.execute("PRAGMA table_info(chat_messages)")
        cols = [row[1] for row in cursor.fetchall()]
        if "user_id" not in cols:
            conn.execute("ALTER TABLE chat_messages ADD COLUMN user_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON chat_messages(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tour_code ON tour_click_events(tour_code)")
    don_tin_nhan_cu_3_ngay()


@contextmanager
def ket_noi():
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# [GEMINI] T-003: Lưu tin nhắn kèm user_id nếu có
def luu_tin_nhan(session_id: str, role: str, content: str, user_id: str | None = None):
    if user_id is None and ":" in session_id:
        user_id = session_id.split(":", 1)[0]
    with ket_noi() as conn:
        conn.execute(
            "INSERT INTO chat_messages (session_id, user_id, role, content) VALUES (?, ?, ?, ?)",
            (session_id, user_id, role, content),
        )


def luu_khach_web(device_id: str, ten: str, sdt: str, doc_tu: str | None) -> None:
    """`doc_tu` = None: đúng thiết bị cũ, giữ nguyên mốc đang có."""
    with ket_noi() as conn:
        conn.execute(
            "INSERT INTO web_khach (device_id, ten, sdt, doc_tu) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET ten = excluded.ten, sdt = excluded.sdt, "
            "doc_tu = COALESCE(excluded.doc_tu, doc_tu), updated_at = datetime('now')",
            (device_id, ten, sdt, doc_tu),
        )


def lay_moc_doc_web(device_id: str) -> str | None:
    with ket_noi() as conn:
        row = conn.execute("SELECT doc_tu FROM web_khach WHERE device_id = ?", (device_id,)).fetchone()
    return row[0] if row else None


def lay_khach_web(device_id: str) -> dict | None:
    with ket_noi() as conn:
        row = conn.execute("SELECT ten, sdt FROM web_khach WHERE device_id = ?", (device_id,)).fetchone()
    return {"name": row[0], "phone": row[1]} if row else None


def lay_lich_su(session_id: str, so_luot: int) -> list[dict]:
    """Lấy N lượt hỏi-đáp gần nhất — dùng nối lại hội thoại (§8) và
    giới hạn gửi lại cho AI (MAX_HISTORY_TURNS ở rules.py)."""
    with ket_noi() as conn:
        rows = conn.execute(
            """SELECT role, content FROM chat_messages
               WHERE session_id = ? ORDER BY id DESC LIMIT ?""",
            (session_id, so_luot * 2),  # x2 vì mỗi lượt có 1 user + 1 assistant
        ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


# [GEMINI] T-003: Rate limit tính theo user_id (tránh đổi conversation_id để né)
def kiem_tra_rate_limit(
    identifier: str,
    gioi_han_phut: int,
    gioi_han_gio: int,
    gioi_han_ngay: int,
    giay_toi_thieu_giua_2_cau: int,
) -> str | None:
    user_id = identifier.split(":", 1)[0] if ":" in identifier else identifier
    with ket_noi() as conn:
        row = conn.execute(
            """SELECT
                SUM(CASE WHEN created_at >= datetime('now', '-1 minute') THEN 1 ELSE 0 END),
                SUM(CASE WHEN created_at >= datetime('now', '-1 hour') THEN 1 ELSE 0 END),
                SUM(CASE WHEN created_at >= datetime('now', '-1 day') THEN 1 ELSE 0 END),
                MAX(created_at)
               FROM chat_messages
               WHERE (user_id = ? OR session_id = ? OR session_id LIKE ?) AND role = 'user'""",
            (user_id, user_id, f"{user_id}:%"),
        ).fetchone()
        so_phut, so_gio, so_ngay, tin_nhan_gan_nhat = row
        so_phut, so_gio, so_ngay = so_phut or 0, so_gio or 0, so_ngay or 0

        if tin_nhan_gan_nhat:
            khoang_cach = conn.execute(
                "SELECT (julianday('now') - julianday(?)) * 86400",
                (tin_nhan_gan_nhat,),
            ).fetchone()[0]
            if khoang_cach < giay_toi_thieu_giua_2_cau:
                return f"Bạn thao tác hơi nhanh, đợi {giay_toi_thieu_giua_2_cau} giây giữa 2 câu hỏi nhé."

    if so_phut >= gioi_han_phut:
        return "Bạn đã hỏi hơi nhiều trong 1 phút, đợi chút rồi hỏi tiếp nhé."
    if so_gio >= gioi_han_gio:
        return "Bạn đã đạt giới hạn số câu hỏi trong 1 giờ, đợi chút rồi hỏi tiếp nhé."
    if so_ngay >= gioi_han_ngay:
        return "Bạn đã đạt giới hạn số câu hỏi trong hôm nay, hẹn gặp lại bạn vào ngày mai nhé."
    return None


def ghi_nhan_click_tour(session_id: str, tour_code: str, tour_name: str):
    with ket_noi() as conn:
        conn.execute(
            """INSERT INTO tour_click_events (session_id, tour_code, tour_name)
               VALUES (?, ?, ?)""",
            (session_id, tour_code, tour_name),
        )


def thong_ke_tour_hot(gioi_han: int = 10) -> list[dict]:
    """Dùng cho mục đích (b) ở §8 — tour nào được click nhiều nhất."""
    with ket_noi() as conn:
        rows = conn.execute(
            """SELECT tour_code, tour_name, COUNT(*) as so_luot_click
               FROM tour_click_events
               GROUP BY tour_code ORDER BY so_luot_click DESC LIMIT ?""",
            (gioi_han,),
        ).fetchall()
    return [{"tour_code": r[0], "tour_name": r[1], "so_luot_click": r[2]} for r in rows]


# [GEMINI] T-003: Dọn tin nhắn cũ hơn 3 ngày trong SQLite
def don_tin_nhan_cu_3_ngay() -> int:
    with ket_noi() as conn:
        cursor = conn.execute("DELETE FROM chat_messages WHERE created_at < datetime('now', '-3 days')")
        return cursor.rowcount


# [GEMINI] T-003: Xoá lịch sử cuộc trò chuyện của đúng người dùng
def xoa_lich_su_cuoc_tro_chuyen(user_id: str, conversation_id: str) -> int:
    session_key = f"{user_id}:{conversation_id}"
    with ket_noi() as conn:
        cursor = conn.execute(
            "DELETE FROM chat_messages WHERE session_id = ? OR (user_id = ? AND session_id LIKE ?)",
            (session_key, user_id, f"%:{conversation_id}"),
        )
        return cursor.rowcount
