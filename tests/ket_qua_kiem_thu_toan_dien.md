# Kết quả kiểm thử toàn diện chatbot bttAI

- Thời điểm: 23/10/2026 14:07 · model trả lời `gemini-3.1-flash-lite` · giám khảo `gemini-3-flash-preview` · 6s · 2 lượt gọi Gemini
- Chạy THẬT: đăng nhập NestJS, Gemini, ChromaDB, benthanhtourist.com, đặt đơn thật (nhóm `dat_that`). Chỉ tắt giới hạn số câu hỏi.
- ✅ ĐẠT = kiểm tự động + giám khảo đều đạt · ⚠️ XEM LẠI = một trong hai không đạt · ❌ TRƯỢT = cả hai không đạt (hoặc kiểm tự động trượt khi không có giám khảo).
- Tổng 1 ca: ⚠️ XEM LẠI 1

| Mã | Nhóm | Tình huống | Kiểm tự động | Giám khảo | Kết luận |
|---|---|---|---|---|---|
| E04 | chinh_sach | Văn phòng, hotline | 2/2 | không đạt (3/5) | ⚠️ XEM LẠI |

## E04 — Văn phòng, hotline  ⚠️ XEM LẠI

conversation `7d80f5bf-2214-457d-a7e4-61e3d09a2bdf`

**Khách:** Văn phòng BenThanh Tourist ở đâu, hotline số mấy?  
*0.5s*
```text
Bạn có thể liên hệ BenThanh Tourist qua hotline 1900 6668, hoặc điện thoại bàn 028 3520 2020. Tư vấn khách lẻ: 0832 666 000. Email: benthanh@benthanhtourist.com.
Trụ sở chính: 70 Lý Tự Trọng, Phường Bến Thành, TP. Hồ Chí Minh. Trung tâm Du lịch Khách lẻ: 03-05 Nguyễn Huệ, Phường Sài Gòn, TP. Hồ Chí Minh.
Công ty còn chi nhánh ở Hà Nội, Đà Nẵng, Huế, Cần Thơ…, bạn hỏi mình chi nhánh gần bạn nhé. Nếu cần nhân viên hỗ trợ trực tiếp, bạn cứ nhắn mình “gặp nhân viên” nhé.
```

**Kiểm tự động:**
- ✔ câu trả lời có “1900 6668”
- ✔ câu trả lời có “nguyễn huệ”

**Giám khảo:** KHÔNG ĐẠT 3/5 — Chatbot cung cấp thông tin liên hệ chính xác nhưng lại tự ý đưa thêm thông tin chi nhánh khác mà không có trong dữ liệu cho phép, vi phạm quy định chỉ nói về dữ liệu được cung cấp.
