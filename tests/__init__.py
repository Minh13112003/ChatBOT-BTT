"""Bộ test của chatbot bttAI.

Chạy từ thư mục gốc repo:   python -m unittest discover -s tests -t . -v

Test KHÔNG đụng dữ liệu thật: dùng file sqlite tạm, không gọi Gemini, không gọi NestJS,
không gọi benthanhtourist.com (trừ tests/test_du_lieu_tour.py đọc ChromaDB trên máy, chỉ đọc).
"""
import atexit
import os
import tempfile

import config

# Phải đổi TRƯỚC khi database.py được import (nó chép giá trị DATABASE_PATH lúc import).
_fd, _DB_TAM = tempfile.mkstemp(prefix="bttai_test_", suffix=".sqlite3")
os.close(_fd)
config.DATABASE_PATH = _DB_TAM


@atexit.register
def _don_dep():
    try:
        os.remove(_DB_TAM)
    except OSError:
        pass
