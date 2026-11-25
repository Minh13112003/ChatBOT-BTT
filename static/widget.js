/*
 * Nhúng khung chat bttAI vào website (ví dụ benthanhtourist.com). Website chỉ cần dán 1 dòng trước </body>:
 *   <script src="https://<tên miền chatbot>/static/widget.js" async></script>
 * File này tạo một iframe ở góc dưới phải, nạp /static/chat.html?nhung=1 từ CHÍNH tên miền chatbot (lấy từ đường dẫn của file này).
 * Trang chat báo trạng thái (nút tròn / lời chào / khung mở) qua postMessage, file này đổi kích thước iframe tương ứng.
 * Website nào được nhúng do biến NHUNG_CHO_PHEP của chatbot quyết định (mặc định benthanhtourist.com và tên miền con).
 */
(function () {
  if (window.__bttaiWidget) return; // dán trùng 2 lần thì chỉ chạy 1 lần
  window.__bttaiWidget = true;

  var script = document.currentScript || document.querySelector('script[src*="widget.js"]');
  var goc = new URL(script.src).origin;
  var DIEN_THOAI = 480; // màn hình hẹp hơn thì khung chat mở toàn màn hình

  var iframe = document.createElement("iframe");
  iframe.src = goc + "/static/chat.html?nhung=1";
  iframe.title = "Trò chuyện với bttAI - BenThanh Tourist";
  iframe.setAttribute("allow", "clipboard-write");
  iframe.setAttribute("allowtransparency", "true");
  var s = iframe.style;
  s.position = "fixed";
  s.right = "0";
  s.bottom = "0";
  s.width = "100px";
  s.height = "100px";
  s.border = "0";
  s.background = "transparent";
  s.colorScheme = "normal";
  s.zIndex = "2147483000";
  s.maxWidth = "100vw";
  s.maxHeight = "100vh";

  var trangThai = "dong";

  function apKichThuoc() {
    var hep = window.innerWidth <= DIEN_THOAI;
    s.borderRadius = "0";
    s.boxShadow = "none";
    s.right = "0";
    s.bottom = "0";
    if (trangThai === "mo") {
      if (hep) {
        s.width = "100vw";
        s.height = "100%";
      } else {
        s.right = "20px";
        s.bottom = "20px";
        s.width = "400px";
        s.height = "min(640px, calc(100vh - 40px))";
        s.borderRadius = "16px";
        s.boxShadow = "0 12px 40px rgba(0,0,0,.18), 0 2px 8px rgba(0,0,0,.08)";
      }
    } else if (trangThai === "loi_chao") {
      s.width = hep ? "100vw" : "360px";
      s.height = "110px";
    } else {
      s.width = "100px";
      s.height = "100px";
    }
  }

  window.addEventListener("message", function (e) {
    // Chỉ nghe đúng iframe chatbot, từ đúng tên miền chatbot
    if (e.source !== iframe.contentWindow || e.origin !== goc || !e.data || !e.data.bttai) return;
    if (["dong", "loi_chao", "mo"].indexOf(e.data.trangThai) === -1) return;
    trangThai = e.data.trangThai;
    apKichThuoc();
  });
  window.addEventListener("resize", apKichThuoc);
  iframe.addEventListener("load", function () {
    iframe.contentWindow.postMessage({ bttaiHoi: true }, goc);
  });

  function gan() {
    apKichThuoc();
    document.body.appendChild(iframe);
  }
  if (document.body) gan();
  else document.addEventListener("DOMContentLoaded", gan);
})();
