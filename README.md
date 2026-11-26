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
   Tour lấy từ benthanhtourist.com; riêng **thể loại tour** ("TOUR OF THE YEAR
   2026", "TOUR CAO CẤP", "TOUR MICE", "TOUR HÈ", "DU LỊCH XANH") lấy từ
   `GET {NESTJS_BASE_URL}/api/v1/tours` rồi khớp theo tên tour. Backend NestJS
   **đang tắt** thì script vẫn chạy xong (in cảnh báo, thể loại để rỗng) nhưng
   khách hỏi "tour of the year" sẽ không lọc được theo thể loại — bật backend
   rồi chạy lại `sync_tours.py` là có.

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

#### Luồng đặt tour trong khung chat
Khi khách nói "tôi muốn đặt tour…", chatbot dẫn qua các bước bằng nút bấm
(`choices` / `multi` / `toi_da`), gửi lại bằng `action` trong body:
```json
{ "message": "", "conversation_id": "…", "action": { "id": "xn:dong_y" } }
```
Khách soát bảng tóm tắt rồi bấm **Đồng ý** → chatbot gọi thẳng
`POST /api/v1/bookings` của NestJS (nguồn Laravel, thanh toán mặc định
`AT_OFFICE`, KHÔNG thu CCCD/hộ chiếu — họ tên/email/SĐT lấy từ tài khoản theo
token) và trả thêm:
```json
{ "booking": { "booking_id": "<uuid đơn vừa đặt>" } }
```
App tự mở trang trạng thái đơn từ mã này (app RN: `/detailTour?id=…`,
Zalo Mini App: `/booking-detail/:id`) — API không trả route của riêng app nào.

### 3. Xoá lịch sử cuộc trò chuyện
- `DELETE /chat/{conversation_id}`
- **Header**: `Authorization: Bearer <accessToken_NestJS>`
- **Response**: `204 No Content`

---

### 4. Nối trang quản trị hội thoại (`D:\btt-chat-admin`)
Đặt `ADMIN_CHAT_URL`, `INGEST_API_KEY` (trùng với bên trang quản trị) và `ADMIN_DATABASE_URL` (chính database bên đó) trong `.env`. Bỏ trống thì chatbot chạy độc lập như cũ. Xem `admin_chat.py`.

Mọi câu của khách và của bot đều được lưu: gọi backend trang quản trị trước, backend không chạy thì ghi thẳng vào database ngay (`lich_su_db.py`). Không có hàng chờ gửi bù. Tin nhạy cảm bị chặn và nút bấm đặt tour cũng được lưu (app gửi kèm `action.label`). Tin rỗng, quá dài, quá giới hạn tốc độ khi đang chat với bot thì không lưu. Nhân viên đang xử lý thì giới hạn theo khách không chặn tin (giới hạn theo IP ở `/web/chat` vẫn giữ), và tin vượt giới hạn không bao giờ gọi Gemini.

`lich_su_db.py` viết SQL tay theo `backend/prisma/schema.prisma` bên trang quản trị: đổi các bảng đó thì phải sửa file này.

- `POST /chat` có thể trả `{"reply": "", "che_do": "STAFF", ...}`: nhân viên đang xử lý nên bot im lặng, app không vẽ bong bóng rỗng.
- `GET /chat/updates?after=<cursor>` (Bearer): tin nhân viên `{ "che_do", "items": [{id, text, at}], "cursor" }`. Lưu `cursor` rồi gửi lại lần sau; không có `after` thì lấy từ bây giờ.

### 5. Khách web không đăng nhập (`static/chat.html`)
Các API này công khai, giới hạn theo IP:
- `POST /web/identify` `{device_id, name, phone}`: bắt buộc trước khi chat. Lỗi 400 `INVALID_PHONE`, 409 `NAME_MISMATCH`.
- `POST /web/chat` `{device_id, conversation_id, message}`: chưa có tên + SĐT thì 403 `CAN_THONG_TIN`. Không vào luồng đặt tour.
- `GET /web/updates?device_id=&after=`: như `/chat/updates`, nhưng không đọc được tin trước lúc thiết bị này để lại thông tin.

**Nhúng vào website** (ví dụ benthanhtourist.com): dán 1 dòng trước `</body>`:

```html
<script src="https://<tên miền chatbot>/static/widget.js" async></script>
```

Trên VPS chatbot chạy ở **https://chatbot.benthanhtourist.com** (Docker, xem `deploy/HUONG-DAN-DEPLOY.md`), nên dòng cần dán là `<script src="https://chatbot.benthanhtourist.com/static/widget.js" async></script>`.

`widget.js` tạo iframe ở góc dưới phải nạp `/static/chat.html?nhung=1` (nút tròn, bấm mở khung chat 400px, điện thoại toàn màn hình). Chatbot phải chạy https. Website được nhúng đặt ở `NHUNG_CHO_PHEP` (mặc định benthanhtourist.com và tên miền con); website khác nhúng thì trình duyệt chặn (header `frame-ancestors`).

---

## Chạy test

```bash
python -m unittest discover -s tests -t .
```

Không cần cài thêm gì, không gọi Gemini/NestJS/benthanhtourist.com, dùng file sqlite tạm (không đụng `chatbot.sqlite3`).
- `tests/test_dat_tour_luong.py` — luồng đặt tour theo từng yêu cầu (YC1–YC9).
- `tests/test_api_chat.py` — xác thực, chống spam, kiểm duyệt, chuyển nhân viên, AI lỗi.
- `tests/test_du_lieu_tour.py` — chạy trên dữ liệu tour thật trong `tour_db/`. Chạy lại sau mỗi lần `python sync_tours.py`: test đỏ nghĩa là có tour/điểm đến mới mà chatbot chưa hiểu tên gọi (thêm vào `ALIAS_DIEM_DEN` ở `rules.py`).
- `tests/test_kich_ban_dat_tour.py` — hội thoại đặt tour nhiều lượt (câu hỏi giữa luồng, cách nói số người/ngày, đổi ý, dữ liệu đổi giữa chừng).
- `tests/test_cau_hoi_khach.py` — câu hỏi tìm tour trên dữ liệu thật (điểm đến, ngân sách, số ngày, Tết/Noel/hè, câu nối tiếp).
- `tests/test_do_ben.py` — độ bền/an toàn: đầu vào lạ, kiểm duyệt, chuyển nhân viên, hợp đồng với app, tiêm lệnh.
- `tests/test_khong_tim_ra_tour.py` — khách muốn đặt nhưng không tìm ra tour: báo “chưa tìm thấy” + gợi ý vài tour để bấm (`dat_tour.tour_goi_y`).
- `tests/test_tat_than_nhan.py` — luồng đặt tour khi bước thân nhân đang tắt (`dat_tour.DUNG_THAN_NHAN = False`).
- `tests/kiem_thu_toan_dien.py` — KHÔNG phải test tự động: 49 ca hội thoại THẬT đầu-cuối (đăng nhập NestJS thật, Gemini thật, đặt đơn thật ở nhóm `dat_that`), mỗi ca chấm bằng quy tắc + Gemini làm giám khảo. Tài khoản lấy từ biến môi trường `KIEM_THU_SDT` / `KIEM_THU_MK` (không ghi vào file): `python -m tests.kiem_thu_toan_dien [--nhom ...] [--ma A01,H01] [--khong-dat-that] [--khong-giam-khao]`. Kết quả: `tests/ket_qua_kiem_thu_toan_dien.md`.
- `tests/chay_thu_that.py` — KHÔNG phải test tự động: chạy hội thoại thật với Gemini + benthanhtourist.com, ghi `tests/ket_qua_chay_that.md` (`python -m tests.chay_thu_that`, tốn hạn mức Gemini).

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
