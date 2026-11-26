import os
from dotenv import load_dotenv

load_dotenv()

BENTHANH_API_BASE = "https://benthanhtourist.com/api/tour"
BENTHANH_HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

# Chỉ đồng bộ các category "loại hình" — bỏ category trùng theo điểm đến
# (xem lý do ở §4 của tài liệu hướng dẫn)
CATEGORY_IDS_LOAI_HINH = {
    1: "Trong Nước",
    2: "Nước Ngoài",
    78: "Free & Easy",
}

# Chạy trong Docker thì đặt ra thư mục lưu lâu dài (volume), ví dụ /data/tour_db và /data/chatbot.sqlite3.
CHROMA_PATH = os.environ.get("CHROMA_PATH", "").strip() or "./tour_db"
CHROMA_COLLECTION = "benthanh_tours"

DATABASE_PATH = os.environ.get("DATABASE_PATH", "").strip() or "./chatbot.sqlite3"

# [GEMINI] Cấu hình Gemini API (SDK OpenAI trỏ sang Gemini endpoint)
# Lấy key miễn phí tại https://aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


# [GEMINI] T-003: Base URL NestJS backend để xác thực người dùng
NESTJS_BASE_URL = os.environ.get("NESTJS_BASE_URL", "").strip()

# Trang quản trị hội thoại (D:\btt-chat-admin). Bỏ trống thì chatbot chạy độc lập như trước.
ADMIN_CHAT_URL = os.environ.get("ADMIN_CHAT_URL", "").strip()
INGEST_API_KEY = os.environ.get("INGEST_API_KEY", "").strip()
# Địa chỉ trang quản trị mà APP, WEB, MINI APP của khách mở được (link ảnh, file nhân viên gửi). Khác ADMIN_CHAT_URL khi chatbot gọi trang quản trị qua mạng nội bộ.
ADMIN_CHAT_PUBLIC_URL = os.environ.get("ADMIN_CHAT_PUBLIC_URL", "").strip() or ADMIN_CHAT_URL
# Chính database của trang quản trị: backend bên đó không chạy thì chatbot ghi thẳng lịch sử vào đây (xem lich_su_db.py).
ADMIN_DATABASE_URL = os.environ.get("ADMIN_DATABASE_URL", "").strip()
# Website được nhúng khung chat web (static/chat.html) bằng static/widget.js, cách nhau dấu cách. Website khác nhúng thì trình duyệt chặn.
# Mặc định: benthanhtourist.com và mọi tên miền con. Đặt "*" để cho mọi website (không nên).
NHUNG_CHO_PHEP = os.environ.get("NHUNG_CHO_PHEP", "").strip() or "https://benthanhtourist.com https://*.benthanhtourist.com"
# Chatbot đứng sau nginx (Docker trên VPS): "1" thì lấy IP khách thật từ X-Forwarded-For khi kết nối đến từ mạng nội bộ. Chạy thẳng ra Internet thì để trống.
TRUST_PROXY = os.environ.get("TRUST_PROXY", "").strip() == "1"
# "1": tự đồng bộ tour từ website mỗi ngày lúc GIO_DONG_BO_TOUR giờ Việt Nam (mặc định 3 giờ sáng), và ngay khi khởi động nếu kho tour trống.
TU_DONG_BO_TOUR = os.environ.get("TU_DONG_BO_TOUR", "").strip() == "1"
GIO_DONG_BO_TOUR = int(os.environ.get("GIO_DONG_BO_TOUR", "").strip() or 3)
