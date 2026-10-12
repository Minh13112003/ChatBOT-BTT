# mobile/ — tài nguyên cho app di động bttAI

Thư mục này chỉ chứa **tài nguyên và tài liệu** dùng chung cho app di động (React Native, repo `D:\App Mobile\MyFirstApp`). Code giao diện app nằm trong repo app, **không** để ở đây. Backend chatbot (FastAPI) vẫn ở thư mục gốc `D:\ChatBot`.

- `assets/bttai-icon.svg` — icon bttAI chính thức (robot thân thiện, nền đỏ BenThanh). App dựng lại bằng `react-native-svg` (`components/chatbot/ChatbotLogo.tsx`).
- Kế hoạch, hợp đồng API, đặc tả giao diện và danh sách task: xem `docs/COLLAB.md` trong repo app (mục "DỰ ÁN CHATBOT bttAI").

Lưu ý: không đưa `.env`, khoá API, `chatbot.sqlite3` hay `tour_db/` vào thư mục này hoặc vào git.
