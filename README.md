# bttAI Backend — Trợ lý tư vấn tour du lịch BenThanh Tourist

Backend chatbot tư vấn tour du lịch thông minh, phục vụ ứng dụng BenThanh Tourist Mobile App và Web demo.

## Kiến trúc
- **Framework**: FastAPI (Python 3.10+)
- **Vector DB**: ChromaDB (chỉ mục dữ liệu tour từ benthanhtourist.com)
- **AI Model**: Google Gemini (Flash) qua OpenAI-compatible API
- **Xác thực**: Token Bearer qua NestJS backend (`/api/v1/users/me`)

---

## Cấu hình môi trường (.env)

Tạo file `.env` tại thư mục gốc `D:\ChatBot` (xem mẫu tại `.env.example`):

```env
# Gemini API Key (lấy miễn phí tại https://aistudio.google.com/apikey)
GEMINI_API_KEY=your_gemini_api_key_here

# Base URL của NestJS backend để xác thực AccessToken người dùng
NESTJS_BASE_URL=http://localhost:3000
```

---

## Hướng dẫn cài đặt & Khởi chạy

1. **Cài đặt thư viện**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Đồng bộ dữ liệu tour (nếu cần cập nhật mới)**:
   ```bash
   python sync_tours.py
   ```

3. **Khởi chạy máy chủ**:
   ```bash
   uvicorn main:app --reload --port 8001
   ```

4. **Public tunnel qua Cloudflare (chủ dự án tham khảo)**:
   ```bash
   cloudflared tunnel --url http://localhost:8001
   ```
   *(Sao chép URL `https://...trycloudflare.com` gán vào `EXPO_PUBLIC_CHATBOT_URL` bên mobile app)*

---

## API Endpoints

### 1. Healthcheck
- `GET /health`
- **Response**: `{"ok": true}` (Không cần token)

### 2. Trò chuyện tư vấn tour
- `POST /chat`
- **Header**: `Authorization: Bearer <accessToken_NestJS>`
- **Body**:
  ```json
  {
    "message": "Tư vấn tour Thái Lan dưới 10 triệu",
    "conversation_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
  }
  ```
- **Response**:
  ```json
  {
    "reply": "Mình tìm được tour Thái Lan phù hợp...",
    "tours": [
      {
        "tour_key": "75947046c635b77949f3348cffa389f51789353022",
        "id": "bfade4e5713bff5430f2e48b360aea5e1789353034",
        "ten": "Du Lịch Thái Lan...",
        "gia": 6890000,
        "so_ngay": 5,
        "ngay_khoi_hanh": "2026-11-13",
        "so_cho_con": 6,
        "anh": "https://benthanhtourist.com/resize/800x0/...",
        "url": "https://benthanhtourist.com/tour/...",
        "diem_den": "Thái Lan",
        "loai_hinh": "Nước Ngoài"
      }
    ],
    "goi_y": []
  }
  ```

### 3. Xoá lịch sử cuộc trò chuyện
- `DELETE /chat/{conversation_id}`
- **Header**: `Authorization: Bearer <accessToken_NestJS>`
- **Response**: `204 No Content`

---

## Thử nghiệm nhanh bằng curl

```bash
# Healthcheck
curl http://localhost:8001/health

# Chat
curl -X POST http://localhost:8001/chat \
  -H "Authorization: Bearer <TOKEN_NESTJS>" \
  -H "Content-Type: application/json" \
  -d '{"message":"tour Đà Nẵng","conversation_id":"123e4567-e89b-12d3-a456-426614174000"}'

# Xoá lịch sử cuộc trò chuyện
curl -X DELETE http://localhost:8001/chat/123e4567-e89b-12d3-a456-426614174000 \
  -H "Authorization: Bearer <TOKEN_NESTJS>"
```
