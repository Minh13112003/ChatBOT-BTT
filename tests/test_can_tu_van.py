"""Mục chưa có dữ liệu thì báo nhân viên tư vấn, khách vẫn hỏi bot chuyện khác (chủ dự án chốt 2026-11-25).
Kèm: AI đang trả lời mà nhân viên vừa nhắn thì AI vẫn trả lời xong câu đó, từ câu sau bot im cho nhân viên nhắn."""
import unittest

import main
from rag import can_nhan_vien_som
from tests.test_admin_chat import NenNoiAdmin
from tests.test_nhan_vien_som import NenGhi

CAU_TU_VAN = main.TRA_LOI_NHAN_VIEN_SOM["TU_VAN"]


class NhanDien(unittest.TestCase):
    def test_cac_muc_chua_co_du_lieu(self):
        for cau in [
            "mình ăn chay trường, tour có phục vụ đồ chay ko", "con mình dị ứng hải sản", "nhà mình ăn kiêng",
            "đoàn thường bao nhiêu người vậy", "đoàn có khoảng mấy khách ạ", "1 đoàn bao nhiêu người",
            "có trả góp không", "quẹt thẻ được ko", "thanh toán bằng thẻ tín dụng được không",
            "qua Nhật có sim không", "có phát wifi không", "khách sạn có wi fi ko", "cục phát wifi",
            "mình bận, chuyển nhượng suất cho bạn được ko", "nhường lại suất cho em gái", "đổi tên người đi được không",
            "em đang mang thai 4 tháng đi được không", "vợ mình đang bầu", "bà bầu đi được ko", "bầu 5 tháng đi tour được không",
            "mình bị ốm thì đổi ngày được không", "đổi lịch vì bị sốt có mất phí không",
            "ở nước ngoài có chuyện khẩn cấp thì gọi ai", "ban đêm cần hỗ trợ thì liên hệ số nào",
            "có giảm giá nhóm không", "có ưu đãi early bird không", "đặt sớm có được giảm không", "thẻ thành viên có ưu đãi gì",
            "xin mã giảm giá, mình là khách cũ", "mua gift voucher tặng mẹ",
        ]:
            with self.subTest(cau=cau):
                self.assertEqual(can_nhan_vien_som(cau, True), "TU_VAN")

    def test_khong_bat_nham(self):
        for cau in [
            "tour Phú Quốc 3 ngày giá bao nhiêu", "rượu sim phú quốc có ngon không", "đồi hoa sim đẹp quá", "tour nhật tháng 12",
            "visa Nhật mất bao lâu", "huỷ tour trước 15 ngày mất bao nhiêu", "cọc bao nhiêu", "nhà mình 4 người đi Đà Lạt",
            "tour nào đang giảm giá", "bầu trời Đà Lạt đẹp không", "tour 2 đêm ở khách sạn mấy sao",
        ]:
            with self.subTest(cau=cau):
                self.assertIsNone(can_nhan_vien_som(cau, True))

    def test_doan_dong_van_la_doanh_nghiep(self):
        self.assertEqual(can_nhan_vien_som("đoàn 30 người có giảm giá nhóm không", True), "DOANH_NGHIEP")


class LuongXuLy(NenNoiAdmin):
    def chay(self, text, kenh="WEB"):
        self.nen = NenGhi()
        req = main.ChatRequest(message=text, conversation_id=self.conv)
        return main._xu_ly_chat(req, self.nen, "u1", "", kenh, "web-1", {"name": "An", "phone": "0900000000"})

    def test_bao_nhan_vien_va_gui_cau_rieng_cho_trang_quan_tri(self):
        self.inbound.return_value = {"conversationId": "c1", "action": "CONTACT", "reply": CAU_TU_VAN}
        kq = self.chay("mình ăn chay thì tour có món chay không")
        self.assertEqual(kq["reply"], CAU_TU_VAN)
        self.assertTrue(self.inbound.call_args.args[4])  # cờ wantsHuman
        self.assertEqual(self.inbound.call_args.kwargs["cau_bao"], CAU_TU_VAN)
        self.gemini.assert_not_called()
        self.assertIn("hỏi mình vấn đề khác", CAU_TU_VAN)

    def test_trang_quan_tri_ngung_van_dung_cau_rieng(self):
        self.inbound.return_value = None
        kq = self.chay("có trả góp không bạn")
        self.assertEqual(kq["reply"], CAU_TU_VAN)
        self.assertEqual([args[2] for fn, args in self.nen.viec if fn is self.bot_reply], [CAU_TU_VAN])
        self.gemini.assert_not_called()

    def test_ly_do_khac_khong_gui_cau_rieng(self):
        self.chay("Công ty em đi team building 60 người")
        self.assertIsNone(self.inbound.call_args.kwargs["cau_bao"])

    def test_sau_khi_bao_khach_hoi_chuyen_khac_bot_van_tra_loi(self):
        self.inbound.return_value = {"conversationId": "c1", "action": "CONTACT", "reply": CAU_TU_VAN}
        self.chay("mình ăn chay")
        # Chưa nhân viên nào nhắn: backend vẫn để bot trả lời
        self.inbound.return_value = {"conversationId": "c1", "action": "BOT"}
        kq = self.chay("tour Đà Lạt 3 ngày giá bao nhiêu")
        self.assertEqual(kq["reply"], "(Gemini) Đây là câu trả lời.")

    def test_ai_dang_tra_loi_ma_nhan_vien_vua_nhan_thi_ai_tra_loi_xong_roi_dung(self):
        # Lúc khách gửi, chưa ai xử lý. Trong lúc Gemini đang trả lời thì nhân viên nhắn (hội thoại chuyển sang STAFF).
        def gemini_cham(*a, **k):
            self.inbound.return_value = {"conversationId": "c1", "action": "STAFF"}
            return "(Gemini) Đây là câu trả lời."
        self.gemini.side_effect = gemini_cham
        kq = self.chay("tour Đà Lạt 3 ngày giá bao nhiêu")
        self.assertEqual(kq["reply"], "(Gemini) Đây là câu trả lời.")  # câu AI đang làm vẫn tới khách
        self.assertEqual([args[2] for fn, args in self.nen.viec if fn is self.bot_reply], ["(Gemini) Đây là câu trả lời."])
        # Câu tiếp theo: bot im, để nhân viên nhắn
        kq = self.chay("còn tour Nha Trang thì sao")
        self.assertEqual(kq, {"reply": "", "tours": [], "goi_y": [], "che_do": "STAFF"})
        self.assertEqual(self.gemini.call_count, 1)


if __name__ == "__main__":
    unittest.main()
