"""Chủ dự án yêu cầu 2026-11-26: mỗi thẻ tour trên web có nút "Đặt tour này" riêng; hiểu tên địa điểm gõ tắt ("tour TLan")."""
import unittest
from unittest import mock

import main
import rag
from tests.test_admin_chat import NenNoiAdmin
from tests.test_nhan_vien_som import NenGhi

KHACH = {"name": "An", "phone": "0900000000"}


class VietTat(unittest.TestCase):
    def test_viet_tat_ghep_chu_doi_moi_cho(self):
        for cau, mong in [("tôi muốn tour TLan", "Thái Lan"), ("tour HQuoc tháng 12", "Hàn Quốc"), ("có tour ĐNang không", "Đà Nẵng"),
                          ("PQuoc 3 ngày giá sao", "Phú Quốc"), ("tour Hlong", "Hạ Long"), ("tour NBan mùa thu", "Nhật Bản")]:
            with self.subTest(cau=cau):
                self.assertIn(mong, rag.mo_rong_viet_tat(cau))

    def test_viet_tat_ngan_chi_doi_sau_tour_di(self):
        for cau, mong in [("tour TQ", "tour Trung Quốc"), ("đi PQ 3 ngày", "đi Phú Quốc 3 ngày"), ("sang HQ", "sang Hàn Quốc"),
                          ("tour ĐL 2N1Đ", "tour Đà Lạt 2N1Đ"), ("du lịch NB", "du lịch Nhật Bản")]:
            with self.subTest(cau=cau):
                self.assertEqual(rag.mo_rong_viet_tat(cau), mong)

    def test_khong_doi_cau_thuong(self):
        for cau in ["hn mình rảnh, hỏi tour", "hq mình hỏi rồi", "nt cho mình nhé", "tl giúp em", "cau hoi nay", "đang hỏi giá", "ok em"]:
            with self.subTest(cau=cau):
                self.assertEqual(rag.mo_rong_viet_tat(cau), cau)

    def test_hn_hq_khong_con_bi_hieu_la_dia_diem(self):
        self.assertIsNone(rag.trich_diem_den("hn mình rảnh, hỏi tour"))
        self.assertIsNone(rag.trich_diem_den("hq mình hỏi rồi"))


class QuaLuongChat(NenNoiAdmin):
    def chay(self, text="", kenh="WEB", action=None):
        req = main.ChatRequest(message=text, conversation_id=self.conv, action=action)
        return main._xu_ly_chat(req, NenGhi(), "u1", "", kenh, "web-1", KHACH)

    def test_tim_tour_bang_ten_day_du_nhung_trang_quan_tri_thay_chu_goc(self):
        with mock.patch.object(main, "tim_tour_lien_quan", return_value=[]) as tim:
            self.chay("tôi muốn tour TLan")
        self.assertEqual(tim.call_args.args[0], "tôi muốn tour Thái Lan")
        self.assertEqual(self.inbound.call_args.args[2], "tôi muốn tour TLan")

    def test_web_khong_con_nut_chung_dat_tour(self):
        self.tours_chat = [{"tour_key": "k1", "ten": "Tour Thái Lan"}]
        kq = self.chay("tour Thái Lan", kenh="WEB")
        self.assertTrue(kq["tours"])
        self.assertNotIn("Tôi muốn đặt tour này", kq["goi_y"])

    def test_app_van_giu_nut_chung(self):
        self.tours_chat = [{"tour_key": "k1", "ten": "Tour Thái Lan"}]
        req = main.ChatRequest(message="tour Thái Lan", conversation_id=self.conv)
        kq = main._xu_ly_chat(req, NenGhi(), "u1", "tok", "APP", "u1", KHACH)
        self.assertIn("Tôi muốn đặt tour này", kq["goi_y"])

    def test_nut_dat_tour_tren_the_vao_thang_buoc_chon_tour(self):
        with mock.patch.object(main.dat_tour, "_chon_tour", return_value={"reply": "Bạn chọn ngày khởi hành nhé", "tours": []}) as chon:
            kq = self.chay(action=main.ChatAction(id="tour:k1", label="Đặt tour: Tour Thái Lan"))
        self.assertEqual(chon.call_args.args[2], "k1")
        self.assertEqual(kq["reply"], "Bạn chọn ngày khởi hành nhé")


if __name__ == "__main__":
    unittest.main()
