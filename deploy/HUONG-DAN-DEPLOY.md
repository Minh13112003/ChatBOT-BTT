# Deploy chatbot bttAI lên VPS (chatbot.benthanhtourist.com)

Chạy trên **cùng VPS** với trang quản trị (`/opt/btt-chat-admin`) và nginx của VinhSang. Mọi lệnh chạy trên server (SSH vào), **gõ từng dòng một**.

Cần có trước: trang quản trị đang chạy (`btt-backend-1`, `btt-postgres-1` "Up"), đã cập nhật bản có trường `contactReply` (commit `af5c758` trở về sau).

## 1. Tên miền trên Cloudflare

Thêm bản ghi **A**: tên `chatbot`, trỏ về IP server, bật **đám mây cam** (Proxied), giống `chatadmin`. Chế độ SSL/TLS giữ **Full**.

## 2. Tải mã và điền cấu hình

```bash
cd /opt && sudo git clone https://github.com/Minh13112003/ChatBOT-BTT.git btt-chatbot
sudo chown -R $USER btt-chatbot
cd /opt/btt-chatbot/deploy
cp .env.example .env
nano .env
chmod 600 .env
```

Trong `.env` điền:
- `GEMINI_API_KEY`: khoá Gemini đang dùng.
- `INGEST_API_KEY`: **chép đúng** giá trị `INGEST_API_KEY` trong `/opt/btt-chat-admin/deploy/.env` (xem bằng `grep INGEST_API_KEY /opt/btt-chat-admin/deploy/.env`).
- `ADMIN_DATABASE_URL`: thay `<DB_PASSWORD>` bằng `DB_PASSWORD` trong `/opt/btt-chat-admin/deploy/.env`.
- Các dòng còn lại để nguyên như file mẫu.

Đừng chụp màn hình hay gửi nội dung file `.env` cho ai (có khoá bí mật).

## 3. Chạy container

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f chatbot
```

Lần build đầu mất vài phút. Lần chạy đầu chatbot tự tải dữ liệu tour từ website (1 đến 3 phút), log hiện `Đồng bộ tour xong lúc ...` là xong. Bấm `Ctrl+C` để thoát xem log (container vẫn chạy).

## 4. Cho nginx của VinhSang chuyển tên miền về chatbot

1. Mở `docker/nginx/vinhsang.conf` của VinhSang, dán vào **cuối file** (sau khối `chatadmin`) toàn bộ nội dung `/opt/btt-chatbot/deploy/nginx-chatbot.conf`.
2. Kiểm tra cú pháp trước, đúng mới nạp lại (từ thư mục của VinhSang):
   ```bash
   docker compose -f docker-compose.prod.yml exec nginx nginx -t
   docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
   ```
   `nginx -t` báo lỗi thì **không** nạp lại, gửi dòng lỗi để xử lý. VinhSang vẫn chạy bình thường.
3. Kiểm tra: mở https://chatbot.benthanhtourist.com/static/chat.html phải thấy nút chat tròn màu đỏ.

## 5. Gắn khung chat vào website benthanhtourist.com

Gửi bên quản lý website dòng này, nhờ dán **trước thẻ `</body>`** ở phần dùng chung cho mọi trang (footer):

```html
<script src="https://chatbot.benthanhtourist.com/static/widget.js" async></script>
```

Chỉ benthanhtourist.com và tên miền con nhúng được (biến `NHUNG_CHO_PHEP`).

## Cập nhật bản mới sau này

```bash
cd /opt/btt-chatbot && git pull
cd deploy
docker compose up -d --build
```

Dữ liệu tour và lịch sử chat nằm trong volume `bttbot_chatbot-data`, build lại không mất. Tour tự đồng bộ mỗi ngày lúc 3 giờ sáng. Muốn đồng bộ ngay:

```bash
docker compose exec chatbot python sync_tours.py
docker compose restart chatbot
```

## Khi có lỗi

- Xem log: `docker compose logs --tail 100 chatbot`.
- Chatbot không gửi tin vào trang quản trị: kiểm tra `INGEST_API_KEY` hai bên giống nhau, và container `btt-backend-1` đang chạy.
- `network btt_internal not found`: trang quản trị chưa chạy, chạy nó trước (`cd /opt/btt-chat-admin/deploy && docker compose up -d`).
