"""Các trường hợp chatbot trả lời VIẾT SẴN (không qua AI) và lọc tour biển — yêu cầu chủ dự án 23/10/2026:
- "tour Hà Nội tầm 10tr" mà không có tour nào: nói thẳng "chưa có tour Hà Nội nào dưới 10 triệu" + tour gần giá nhất.
- "tour Mỹ": nói thẳng chưa có tour đi Mỹ (không hỏi vòng vo).
- Hỏi hotline/văn phòng: có cả địa chỉ.
- "tour biển trong nước": chỉ tour vùng biển (không lẫn Hà Giang, Sapa)."""
import unittest
from unittest import mock

import main
import rag
from rules import TRA_LOI_HOTLINE
from tests.helpers import NenTest

TOAN_BO = rag.tat_ca_luot_con_han()

TOUR_HN = {"tour_key": "k-hn", "id": "hn1", "ten": "Du Lịch Hà Nội - Sapa", "gia": 11_190_000, "so_ngay": 4,
           "ngay_khoi_hanh": "2030-01-01", "so_cho_con": 9, "anh": "", "url": "", "diem_den": "Hà Nội", "loai_hinh": "Trong Nước"}
TOUR_HN2 = dict(TOUR_HN, tour_key="k-hn2", id="hn2", ten="Du Lịch Hà Nội - Hạ Long", gia=12_690_000)


class CauTraLoiVietSan(unittest.TestCase):
    def test_muc_gia(self):
        self.assertEqual(main._muc_gia(10_000_000), "10 triệu")
        self.assertEqual(main._muc_gia(7_500_000), "7,5 triệu")
        self.assertEqual(main._muc_gia(500_000), "500.000 đ")

    def test_khong_co_trong_tam_gia(self):
        goi_y = {"ngan_sach": 10_000_000, "diem_den": "Hà Nội", "tours": [dict(TOUR_HN), dict(TOUR_HN2)]}
        cau = main.tra_loi_khong_co_trong_tam_gia(goi_y, "tour hà nội tầm 10tr")
        self.assertIn("chưa có tour Hà Nội nào dưới 10 triệu", cau)
        self.assertIn("11.190.000 đ", cau)
        self.assertIn("1 tour khác", cau)

    def test_dung_ten_khach_goi_thay_ten_tinh(self):
        da_lat = dict(TOUR_HN, ten="Du Lịch Đà Lạt: Thác Đamb’ri", gia=3_790_000, diem_den="Lâm Đồng")
        dak_nong = dict(TOUR_HN, ten="Du Lịch Tây Nguyên: Đắk Nông", gia=2_690_000, diem_den="Lâm Đồng")
        goi_y = {"ngan_sach": 2_000_000, "diem_den": "Lâm Đồng", "tours": [dak_nong, da_lat]}
        cau = main.tra_loi_khong_co_trong_tam_gia(goi_y, "tour Đà Lạt dưới 2 triệu")
        self.assertIn("tour Đà Lạt nào dưới 2 triệu", cau)
        self.assertIn("Thác Đamb’ri", cau)  # ưu tiên tour có chữ "Đà Lạt" trong tên

    def test_hotline_co_dia_chi(self):
        self.assertIn("1900 6668", TRA_LOI_HOTLINE)
        self.assertIn("70 Lý Tự Trọng", TRA_LOI_HOTLINE)
        self.assertIn("03-05 Nguyễn Huệ", TRA_LOI_HOTLINE)


class QuaApiChat(NenTest):
    def test_khong_co_tour_trong_tam_gia_tra_loi_viet_san_khong_goi_ai(self):
        def tim(cau, *a, goi_y_gia=None, **k):
            goi_y_gia.update(ngan_sach=10_000_000, diem_den="Hà Nội", tours=[dict(TOUR_HN), dict(TOUR_HN2)])
            return []
        with mock.patch.object(main, "tim_tour_lien_quan", tim):
            res = self.gui("ad oi co tour di ha noi ko z, tam 10tr thoi")
        self.assertIn("chưa có tour", res["reply"])
        self.assertEqual([t["tour_key"] for t in res["tours"]], ["k-hn", "k-hn2"])
        self.gemini.assert_not_called()

    def test_noi_khong_co_tour_tra_loi_thang(self):
        res = self.gui("tour mỹ bao nhiêu tiền")
        self.assertIn("chưa có tour đi Mỹ", res["reply"])
        self.assertEqual(res["tours"], [])
        self.gemini.assert_not_called()

    def test_hoi_hotline_co_dia_chi(self):
        res = self.gui("Văn phòng BenThanh Tourist ở đâu, hotline số mấy?")
        self.assertIn("03-05 Nguyễn Huệ", res["reply"])


@unittest.skipUnless(TOAN_BO, "ChromaDB chưa có dữ liệu tour")
class TourBien(unittest.TestCase):
    def test_tour_bien_trong_nuoc_chi_ra_tour_bien(self):
        tours = rag.tim_tour_lien_quan("anh muốn tìm tour biển trong nước cho gia đình")
        self.assertTrue(tours)
        self.assertTrue(all(rag.la_tour_bien(t) for t in tours), [t["ten"] for t in tours])
        self.assertTrue(all(t["loai_hinh"] == "Trong Nước" for t in tours))

    def test_dien_bien_khong_bi_hieu_la_bien(self):
        self.assertFalse(rag.hoi_tour_bien("tour điện biên"))
        self.assertFalse(rag.hoi_tour_bien("tour dien bien phu"))

    def test_noi_ro_diem_den_thi_khong_loc_bien(self):
        """"biển Nha Trang" đã có điểm đến -> lọc theo điểm đến như cũ."""
        tours = rag.tim_tour_lien_quan("tour biển Nha Trang")
        self.assertTrue(tours and all(t["diem_den"] == "Khánh Hòa" for t in tours))

    def test_ngan_sach_khong_co_tour_tra_goi_y_gan_gia(self):
        g = {}
        self.assertEqual(rag.tim_tour_lien_quan("tour Hà Nội dưới 5 triệu", goi_y_gia=g), [])
        self.assertTrue(g["tours"])
        self.assertTrue(all(t["diem_den"] == "Hà Nội" and t["gia"] > 5_000_000 for t in g["tours"]))
        self.assertEqual([t["gia"] for t in g["tours"]], sorted(t["gia"] for t in g["tours"]))
