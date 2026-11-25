"""Chính sách theo từng tour lấy từ API chi tiết tour (đánh giá 160 câu 2026-11-23)."""
import unittest
from unittest import mock

import chinh_sach_tour as cs
from tests.helpers import NenTest

CS_NUOC_NGOAI = {
    "ten": "Du Lịch Nhật Bản: Tokyo", "nuoc_ngoai": True,
    "tuts_booking_payment": "Đợt 1: Đặt cọc 50% tiền tour/ khách khi đăng ký tour.\nĐợt 2: Thanh toán số tiền còn lại trước 15 ngày.",
    "punishment_cancel_booking": "Hủy hoặc hoãn tour từ 15 - 20 ngày trước ngày khởi hành: 50% giá tour.",
    "cancel_booking": "Hoàn trả cọc trong vòng 10 ngày nếu không đủ khách.",
    "tour_price_included": "Vé máy bay, khách sạn 3 sao, bảo hiểm du lịch quốc tế.",
    "tour_price_not_included": "Tiền bồi dưỡng HDV 70 euro/khách/tour. Phụ phí phòng đơn.",
    "warning_note": "Dưới 10 khách thì báo trước 05 ngày.", "warning_note_visa": "",
}
CS_TRONG_NUOC = {**CS_NUOC_NGOAI, "ten": "Du Lịch Đà Lạt", "nuoc_ngoai": False,
                 "punishment_cancel_booking": "Từ 30 ngày - 15 ngày: 60% tiền tour.", "tour_price_not_included": "Chi phí cá nhân."}
KHO = {"k-nhat": CS_NUOC_NGOAI, "k-dalat": CS_TRONG_NUOC}


class NhanDienCauHoi(unittest.TestCase):
    def test_cau_hoi_chinh_sach(self):
        for cau in ["cọc bao nhiêu % thì giữ chỗ", "huỷ tour trước 7 ngày có hoàn tiền ko", "phụ thu phòng đơn bao nhiêu", "tiền tip hdv thế nào",
                    "giá đã bao gồm bảo hiểm chưa", "bão thì tour bị huỷ ra sao", "passport còn hạn 5 tháng", "đi 1 mình bị phụ thu phòng không",
                    "ông bà trên 75 tuổi đi được không", "em đang bầu 5 tháng", "mình ăn chay trường", "dị ứng hải sản", "người nhà đi xe lăn"]:
            with self.subTest(cau=cau):
                self.assertTrue(cs.hoi_chinh_sach(cau))

    def test_cau_khong_phai_chinh_sach(self):
        for cau in ["tour phú quốc 3 ngày giá bao nhiêu", "xin chào", "có tour nhật tháng 12 không"]:
            with self.subTest(cau=cau):
                self.assertFalse(cs.hoi_chinh_sach(cau))


class KhoiChinhSach(unittest.TestCase):
    def khoi(self, cau, the):
        return cs.khoi_chinh_sach(cau, the, lay=KHO.get, mau=lambda: ("k-dalat", "k-nhat"))

    def test_hoi_dung_tour_thi_lay_dung_chinh_sach_tour_do(self):
        k = self.khoi("huỷ tour nhật thì mất bao nhiêu", [{"tour_key": "k-nhat"}])
        self.assertIn("Du Lịch Nhật Bản: Tokyo", k)
        self.assertIn("50% giá tour", k)
        self.assertIn("70 euro", k)
        self.assertIn("KHÁC NHAU", k.upper().replace("KHÁC NHAU", "KHÁC NHAU"))
        self.assertNotIn("Du Lịch Đà Lạt", k)

    def test_nhieu_the_cung_tour_chi_lay_mot_lan(self):
        k = self.khoi("cọc bao nhiêu", [{"tour_key": "k-nhat"}, {"tour_key": "k-nhat"}])
        self.assertEqual(k.count("[Tour nước ngoài: Du Lịch Nhật Bản: Tokyo]"), 1)

    def test_toi_da_2_tour(self):
        goi = mock.Mock(side_effect=lambda key: CS_NUOC_NGOAI)
        cs.khoi_chinh_sach("cọc bao nhiêu", [{"tour_key": f"k{i}"} for i in range(5)], lay=goi, mau=lambda: (None, None))
        self.assertEqual(goi.call_count, cs.SO_TOUR_TOI_DA)

    def test_chua_noi_tour_thi_dua_mau_trong_nuoc_va_vi_du_nuoc_ngoai(self):
        k = self.khoi("cọc bao nhiêu % thì giữ chỗ", [])
        self.assertIn("MẪU tour TRONG NƯỚC", k)
        self.assertIn("60% tiền tour", k)
        self.assertIn("VÍ DỤ một tour NƯỚC NGOÀI", k)
        self.assertIn("hỏi khách quan tâm tour / nước nào", k)

    def test_cau_khong_hoi_chinh_sach_thi_khong_them_gi(self):
        self.assertIsNone(self.khoi("tour phú quốc 3 ngày giá bao nhiêu", [{"tour_key": "k-nhat"}]))

    def test_khong_lay_duoc_du_lieu_thi_none(self):
        self.assertIsNone(cs.khoi_chinh_sach("cọc bao nhiêu", [{"tour_key": "x"}], lay=lambda k: None, mau=lambda: (None, None)))

    def test_cat_bot_van_ban_qua_dai(self):
        dai = {**CS_NUOC_NGOAI, "warning_note": "x" * 9000}
        k = cs.khoi_chinh_sach("cọc bao nhiêu", [{"tour_key": "a"}], lay=lambda key: dai, mau=lambda: (None, None))
        self.assertLess(len(k), 8000)
        self.assertIn("…", k)


class LamSachVaCache(unittest.TestCase):
    def setUp(self):
        cs._cache.clear()

    def test_bo_html_va_nho_ket_qua(self):
        phan_hoi = mock.Mock()
        phan_hoi.json.return_value = {"data": {"name": "Tour A", "image": "https://x/nuoc-ngoai/a.webp",
                                               "tuts_booking_payment": "<ul><li>Đặt cọc <strong>50%</strong></li><li>Còn lại trước 7 ngày</li></ul>"}}
        with mock.patch.object(cs.httpx, "get", return_value=phan_hoi) as get:
            a = cs.lay_chinh_sach("key1")
            b = cs.lay_chinh_sach("key1")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(a, b)
        self.assertTrue(a["nuoc_ngoai"])
        self.assertEqual(a["tuts_booking_payment"], "Đặt cọc 50%\nCòn lại trước 7 ngày")

    def test_loi_mang_khong_nho(self):
        with mock.patch.object(cs.httpx, "get", side_effect=OSError("mạng")) as get:
            self.assertIsNone(cs.lay_chinh_sach("key2"))
            self.assertIsNone(cs.lay_chinh_sach("key2"))
        self.assertEqual(get.call_count, 2)


class QuaApiChat(NenTest):
    def test_hoi_huy_tour_dua_chinh_sach_cho_gemini(self):
        self.tours_chat = [{"tour_key": "k-nhat", "ten": "Du Lịch Nhật Bản: Tokyo"}]
        with mock.patch.object(cs, "lay_chinh_sach", side_effect=lambda key: KHO[key]):
            self.gui("tour nhật mà huỷ trước 15 ngày thì mất bao nhiêu")
        kwargs = self.gemini.call_args.kwargs
        self.assertIn("50% giá tour", kwargs["chinh_sach"])

    def test_cau_thuong_khong_co_chinh_sach(self):
        self.tours_chat = [{"tour_key": "k-nhat", "ten": "Du Lịch Nhật Bản: Tokyo"}]
        self.gui("cho mình xem tour nhật tháng 12")
        self.assertNotIn("chinh_sach", self.gemini.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
