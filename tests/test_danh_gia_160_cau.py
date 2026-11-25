"""Các lỗi tìm thấy khi hỏi chatbot 160 câu (100 câu của chủ dự án + 60 câu bổ sung, 2026-11-23)."""
import unittest

import dat_tour
import rag
from tests.helpers import NenTest


class ChuNhatKhongPhaiNhatBan(unittest.TestCase):
    def test_chu_nhat_khong_ra_diem_den_nhat(self):
        for cau in [
            "Tôi chỉ có 3 ngày cuối tuần (thứ 6 – chủ nhật) muốn đi biển",
            "đi từ thứ 7 đến chu nhat",
            "Đi vào Chủ Nhật được không",
        ]:
            with self.subTest(cau=cau):
                self.assertNotEqual(rag.trich_diem_den(cau), "Nhật Bản")
                self.assertNotIn("Nhật Bản", rag.trich_nhieu_diem_den(cau))

    def test_nhat_ban_van_nhan_ra(self):
        for cau in ["tour Nhật Bản", "tour nhật mùa thu", "đi Nhật chủ nhật này"]:
            with self.subTest(cau=cau):
                self.assertEqual(rag.trich_diem_den(cau), "Nhật Bản")


class SoNguoiVietTat(unittest.TestCase):
    def test_30_ng_la_doan_dong(self):
        self.assertEqual(rag.can_nhan_vien_som("lớp mình 30 ng muốn tour du lịch 30/4, còn chỗ ko", co_sdt=True), "DOANH_NGHIEP")
        self.assertEqual(rag.can_nhan_vien_som("cty mình 25 ng đi đà lạt", co_sdt=True), "DOANH_NGHIEP")

    def test_it_nguoi_hoac_ngay_khong_bi_nham(self):
        self.assertIsNone(rag.can_nhan_vien_som("nhà mình 4 ng đi phú quốc 3 ngày", co_sdt=True))
        self.assertIsNone(rag.can_nhan_vien_som("tour 10 ngày giá bao nhiêu", co_sdt=True))


class KhongMoNhamLuongDatTour(unittest.TestCase):
    def test_chi_hoi_khong_mo_luong_dat(self):
        for cau in [
            "mình đang đặt tour đà lạt dở nhưng muốn hỏi thêm tour nha trang, hỏi được ko",
            "đặt giùm khách sạn đà lạt 2 đêm dc ko, ko đi tour",
            "Tôi ở Hà Nội muốn đăng ký tour khởi hành từ TP.HCM thì có hỗ trợ đặt vé máy bay nối chuyến không?",
            "Tôi là Việt kiều, đăng ký tour của bên mình thì cần lưu ý gì về visa không?",
            "Tôi từng đi 3 lần rồi, lần này đặt tour tiếp có ưu đãi khách thân thiết không?",
        ]:
            with self.subTest(cau=cau):
                self.assertFalse(dat_tour.hoi_dat_tour(cau))

    def test_muon_dat_that_van_mo_luong_dat(self):
        for cau in ["Tôi muốn đặt tour Đà Lạt", "đặt tour này", "book tour Nhật Bản", "chốt tour Phú Quốc", "mình muốn đặt tour Nha Trang 3 ngày"]:
            with self.subTest(cau=cau):
                self.assertTrue(dat_tour.hoi_dat_tour(cau))

    def test_khach_san_le_khong_di_tour_bao_nhan_vien(self):
        self.assertEqual(rag.can_nhan_vien_som("đặt giùm khách sạn đà lạt 2 đêm dc ko, ko đi tour", co_sdt=True), "VE_RIENG")
        self.assertIsNone(rag.can_nhan_vien_som("đặt khách sạn trong tour đà lạt có được không", co_sdt=True))


class QuaApiChat(NenTest):
    def test_hoi_them_tour_khac_khong_mo_luong_dat(self):
        res = self.gui("mình đang đặt tour đà lạt dở nhưng muốn hỏi thêm tour nha trang, hỏi được ko")
        self.assertNotIn("Bạn chọn ngày nào", res["reply"])
        self.assertIsNone(self.trang_thai().get("step"))
        self.assertEqual(self.gemini.call_count, 1)

    def test_khach_san_khong_di_tour_khong_mo_luong_dat(self):
        res = self.gui("đặt giùm khách sạn đà lạt 2 đêm dc ko, ko đi tour")
        self.assertNotIn("Bạn chọn ngày nào", res["reply"])
        self.assertIsNone(self.trang_thai().get("step"))


if __name__ == "__main__":
    unittest.main()
