import sqlite3
from contextlib import contextmanager
from config import DATABASE_PATH


def khoi_tao_database():
    with ket_noi() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON chat_messages(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tour_code ON tour_click_events(tour_code)")


@contextmanager
def ket_noi():
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def luu_tin_nhan(session_id: str, role: str, content: str):
    with ket_noi() as conn:
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )


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


def kiem_tra_rate_limit(session_id: str, gioi_han_phut: int, gioi_han_gio: int, gioi_han_ngay: int, giay_toi_thieu_giua_2_cau: int) -> str | None:
    """3 lớp rate limit theo thời gian + time-check khoảng cách 2 câu liên
    tiếp (§8.2, §8.2b ở rules.py) — CHỈ đếm tin nhắn role='user' (không tính
    'assistant', tránh đếm gấp đôi mỗi lượt hỏi-đáp). Trả về chuỗi lý do nếu
    bị chặn, None nếu được phép gửi tiếp. Dùng SQLite datetime('now') làm mốc
    thời gian chung, tránh lệch múi giờ giữa server và client."""
    with ket_noi() as conn:
        row = conn.execute(
            """SELECT
                SUM(CASE WHEN created_at >= datetime('now', '-1 minute') THEN 1 ELSE 0 END),
                SUM(CASE WHEN created_at >= datetime('now', '-1 hour') THEN 1 ELSE 0 END),
                SUM(CASE WHEN created_at >= datetime('now', '-1 day') THEN 1 ELSE 0 END),
                MAX(created_at)
               FROM chat_messages WHERE session_id = ? AND role = 'user'""",
            (session_id,),
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
