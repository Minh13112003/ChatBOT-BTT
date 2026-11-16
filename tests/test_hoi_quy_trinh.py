"""Câu hỏi quy trình / dịch vụ chung không kèm thẻ tour, câu tìm tour vẫn có — yêu cầu chủ dự án 03/11/2026:
"Tôi liên hệ đặt Tour như thế nào ?" đang ra 5 thẻ tour không liên quan và bảo khách nhắn "gặp nhân viên"."""
import unittest

import dat_tour
import rag
from rules import TRA_LOI_CACH_DAT_TOUR
from tests.helpers import NenTest

CAU_HOI_CACH_DAT = [
    "Tôi liên hệ đặt Tour như thế nào ?",
    "Làm sao để đặt tour?",
    "Đặt tour ở đâu?",
    "Quy trình đặt tour thế nào?",
    "Các bước đặt tour",
    "Hướng dẫn đặt tour giúp tôi",
    "Cách đặt tour trên app",
    "Muốn đặt tour thì liên hệ ai",
    "Đặt tour online được không",
    "lam sao de dat tour",
    "dat tour nhu the nao",
]
CAU_HOI_CHUNG = [
    "Đặt tour cần những giấy tờ gì",
    "Trẻ em có được đi tour không",
    "Tour có hướng dẫn viên không",
    "Đi tour cần chuẩn bị gì",
    "Khi nào nhận được xác nhận đặt tour",
    "Đặt tour xong thì làm gì tiếp",
    "Giá tour đã bao gồm những gì",
    "Có được đổi ngày khởi hành không",
    "Tour có đưa đón tận nơi không",
]
CAU_TIM_TOUR = [
    "tour Đà Lạt",
    "có tour nào giá rẻ không",
    "tour có giá rẻ không",
    "gợi ý tour cho gia đình",
    "tour tháng 12",
    "Tour Nhật Bản như thế nào",
    "tư vấn tour biển",
    "có tour nào hay không",
    "có tour nào có đưa đón không",
    "Đặt tour Đà Lạt thế nào",
    "tour dưới 10 triệu",
    "tour nước ngoài có gì",
    "tour nào đang hot",
    "Có những tour nào",
    "cho xem vài tour đi",
]


class TimTourTrenDuLieuThat(unittest.TestCase):
    def test_cau_hoi_quy_trinh_khong_co_the(self):
        for cau in CAU_HOI_CACH_DAT + CAU_HOI_CHUNG:
            with self.subTest(cau=cau):
                self.assertEqual(rag.tim_tour_lien_quan(cau), [])

    def test_cau_tim_tour_van_co_the(self):
        for cau in CAU_TIM_TOUR:
            with self.subTest(cau=cau):
                self.assertTrue(rag.tim_tour_lien_quan(cau))


class NhanDienCauHoi(unittest.TestCase):
    def test_hoi_cach_dat_khong_mo_luong_dat(self):
        for cau in CAU_HOI_CACH_DAT:
            with self.subTest(cau=cau):
                self.assertFalse(dat_tour.hoi_dat_tour(cau))

    def test_muon_dat_that_van_mo_luong_dat(self):
        for cau in ["Tôi muốn đặt tour Đà Lạt", "đặt tour này", "book tour Nhật Bản", "chốt tour Phú Quốc"]:
            with self.subTest(cau=cau):
                self.assertTrue(dat_tour.hoi_dat_tour(cau))

    def test_tour_dat_tien_khong_phai_hoi_cach_dat(self):
        self.assertFalse(rag.la_cau_hoi_cach_dat("cách nào chọn tour đỡ đắt"))


class QuaApiChat(NenTest):
    def test_hoi_cach_dat_tra_cau_viet_san(self):
        for cau in CAU_HOI_CACH_DAT:
            with self.subTest(cau=cau):
                res = self.gui(cau)
                self.assertEqual(res["reply"], TRA_LOI_CACH_DAT_TOUR)
                self.assertEqual(res["tours"], [])
                self.assertEqual(res["goi_y"], [])
                self.assertNotIn("choices", res)
        self.gemini.assert_not_called()

    def test_cau_tra_loi_dan_ve_app(self):
        self.assertIn("ngay trên ứng dụng này", TRA_LOI_CACH_DAT_TOUR)
        self.assertNotIn("gặp nhân viên", TRA_LOI_CACH_DAT_TOUR)
        self.assertNotIn("benthanhtourist.com", TRA_LOI_CACH_DAT_TOUR)

    def test_hoi_viec_khac_de_ai_tra_loi_khong_kem_the(self):
        for cau in [
            "Đặt tour xong thanh toán thế nào",
            "Đặt tour thì đặt cọc thế nào",
            "Đặt tour cho trẻ em giá thế nào",
            "Đặt tour cần giấy tờ thế nào",
        ]:
            with self.subTest(cau=cau):
                self.setUp()
                res = self.gui(cau)
                self.assertNotEqual(res["reply"], TRA_LOI_CACH_DAT_TOUR)
                self.assertEqual(self.gemini.call_count, 1)
                self.assertEqual(rag.tim_tour_lien_quan(cau), [])

    def test_co_diem_den_thi_van_kem_the(self):
        self.tours_chat = [{"tour_key": "k-dalat", "ten": "Du Lịch Đà Lạt"}]
        res = self.gui("Đặt tour Đà Lạt thế nào")
        self.assertEqual(res["reply"], TRA_LOI_CACH_DAT_TOUR)
        self.assertEqual([t["tour_key"] for t in res["tours"]], ["k-dalat"])
        self.gemini.assert_not_called()

    def test_dang_dat_do_hoi_cach_dat_van_nhac_buoc_dang_do(self):
        self.toi_buoc_so_nguoi("Tôi muốn đặt tour Nga")
        res = self.gui("Các bước đặt tour thế nào?")
        self.assertIn(TRA_LOI_CACH_DAT_TOUR, res["reply"])
        self.assertTrue(res.get("choices"))


if __name__ == "__main__":
    unittest.main()
