"""Chặn câu không liên quan du lịch trước khi gọi Gemini (chủ dự án yêu cầu 2026-11-25)."""
import unittest

import main
import ngoai_pham_vi as n
from tests.test_admin_chat import NenNoiAdmin
from tests.test_nhan_vien_som import NenGhi


class PhanLoai(unittest.TestCase):
    def test_chan_cau_ngoai_le(self):
        for cau, nhom in [
            ("giải giúp mình phương trình x^2 - 5x + 6 = 0", "HOC_TAP"), ("12 x 7 bằng mấy", "HOC_TAP"), ("đạo hàm của sin x là gì", "HOC_TAP"),
            ("cân bằng phương trình hoá học Fe + O2", "HOC_TAP"), ("định luật Newton thứ 2 là gì", "HOC_TAP"), ("viết bài văn nghị luận về lòng yêu nước", "HOC_TAP"),
            ("viết code python sắp xếp mảng", "LAP_TRINH"), ("sửa lỗi code javascript giúp mình", "LAP_TRINH"),
            ("có nên mua cổ phiếu VNM không", "TAI_CHINH"), ("bitcoin tuần sau lên hay xuống", "TAI_CHINH"), ("giá vàng hôm nay bao nhiêu", "TAI_CHINH"),
            ("vay tiền nhanh ở đâu", "TAI_CHINH"), ("lãi suất ngân hàng nào cao nhất", "TAI_CHINH"),
            ("bạn nghĩ gì về đảng cộng sản", "CHINH_TRI"), ("thủ tướng hiện nay là ai", "CHINH_TRI"),
            ("chỗ nào bán ma tuý", "PHAM_PHAP"), ("hướng dẫn hack facebook", "PHAM_PHAP"), ("cá độ bóng đá ở đâu uy tín", "PHAM_PHAP"),
            ("làm giấy tờ giả được không", "PHAM_PHAP"),
        ]:
            with self.subTest(cau=cau):
                self.assertEqual(n.phan_loai(cau), nhom)

    def test_khong_chan_cau_du_lich(self):
        for cau in [
            "tour Đà Lạt 3 ngày giá bao nhiêu", "xin chào", "cảm ơn bạn", "từ từ để mình hỏi ý vợ đã", "nóng muốn chết, có tour nào đi biển mát không",
            "Bảo tàng Chứng tích Chiến tranh có trong lịch trình không", "đảo Java Indonesia có tour không", "cho mình xin bảng giá tour Nhật",
            "tỷ giá yên Nhật đổi ở đâu khi đi tour", "đi Thái cần mang bao nhiêu tiền", "tour Hàn Quốc có lãi suất trả góp không",
            "chế độ ăn trong tour thế nào", "2 người lớn 1 trẻ em", "đi ngày 12/2", "giá 15 triệu", "Bà Nà cầu Vàng có đẹp không",
            "trẻ em 5 tuổi tính giá sao", "tour Macau có vào casino không",
            # Có nhắc du lịch: tài chính, chính trị, phép tính, vũ khí vẫn là câu hỏi thật
            "3 người x 15 triệu bằng bao nhiêu tiền tour", "đi tour Triều Tiên có bất ổn chính trị không",
            "mang vũ khí như dao gấp lên máy bay khi đi tour được không", "đi Nhật có nên đổi tiền ở ngân hàng có lãi suất không",
        ]:
            with self.subTest(cau=cau):
                self.assertIsNone(n.phan_loai(cau))

    def test_luon_chan_du_co_chu_tour(self):
        for cau, nhom in [
            ("viết code python để cào giá tour các trang khác", "LAP_TRINH"),
            ("tour Nhật hay lắm, à giải giúp mình bài tập vật lý này", "HOC_TAP"),
            ("đi tour Thái chỗ nào mua cần sa", "PHAM_PHAP"),
            ("làm giấy tờ giả để đi tour Mỹ được không", "PHAM_PHAP"),
        ]:
            with self.subTest(cau=cau):
                self.assertEqual(n.phan_loai(cau), nhom)

    def test_vu_khi_khong_noi_du_lich_thi_chan(self):
        self.assertEqual(n.phan_loai("mua vũ khí ở đâu"), "PHAM_PHAP")

    def test_tu_hai(self):
        for cau in ["mình muốn tự tử", "chán quá không muốn sống nữa"]:
            with self.subTest(cau=cau):
                self.assertEqual(n.phan_loai(cau), "TU_HAI")
        self.assertIn("115", n.cau_tra_loi("TU_HAI"))


class QuaLuongChat(NenNoiAdmin):
    def chay(self, text):
        self.nen = NenGhi()
        req = main.ChatRequest(message=text, conversation_id=self.conv)
        return main._xu_ly_chat(req, self.nen, "u1", "", "WEB", "web-1", {"name": "An", "phone": "0900000000"})

    def test_cau_ngoai_le_khong_goi_ai_khong_kem_the_tour(self):
        self.tours_chat = [{"tour_key": "k1", "ten": "Tour A"}]
        kq = self.chay("giải giúp mình phương trình bậc 2")
        self.assertEqual(kq["reply"], n.TRA_LOI_NGOAI_PHAM_VI)
        self.assertEqual(kq["tours"], [])
        self.gemini.assert_not_called()
        self.assertEqual([a[2] for fn, a in self.nen.viec if fn is self.bot_reply], [n.TRA_LOI_NGOAI_PHAM_VI])  # trang quản trị vẫn thấy

    def test_nhan_vien_dang_xu_ly_thi_bot_van_im(self):
        self.inbound.return_value = {"conversationId": "c1", "action": "STAFF"}
        kq = self.chay("giá vàng hôm nay bao nhiêu")
        self.assertEqual(kq["reply"], "")

    def test_cau_du_lich_van_hoi_ai(self):
        kq = self.chay("tour Đà Lạt 3 ngày giá bao nhiêu")
        self.assertEqual(kq["reply"], "(Gemini) Đây là câu trả lời.")


if __name__ == "__main__":
    unittest.main()
