# Chatbot bttAI chạy trong Docker trên VPS (cùng máy với trang quản trị btt-chat-admin). Xem deploy/HUONG-DAN-DEPLOY.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Ho_Chi_Minh

WORKDIR /app

COPY requirements.txt deploy/constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt

# Tải sẵn mô hình tạo vector của ChromaDB lúc build (khoảng 80 MB), để lần chạy đầu không phải tải và không lỗi khi mạng chập chờn.
RUN python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction as F; F()(['khoi dong'])"

COPY . .

# Không chạy bằng root
RUN useradd --create-home --uid 10001 bot && mkdir -p /data && chown -R bot:bot /data /app \
    && cp -r /root/.cache /home/bot/.cache 2>/dev/null; chown -R bot:bot /home/bot
USER bot

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
