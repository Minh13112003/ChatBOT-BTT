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

CHROMA_PATH = "./tour_db"
CHROMA_COLLECTION = "benthanh_tours"

DATABASE_PATH = "./chatbot.sqlite3"

# [GEMINI] Cấu hình Gemini API (SDK OpenAI trỏ sang Gemini endpoint)
# Lấy key miễn phí tại https://aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
