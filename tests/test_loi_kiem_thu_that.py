"""Lỗi tìm ra khi chạy tests/kiem_thu_toan_dien.py (hội thoại thật, 23/10/2026) — giữ lại để không tái phát."""
import unittest

import dat_tour
import llm_gemini
import rag
from tests.helpers import NenTest

TOAN_BO = rag.tat_ca_luot_con_han()


class LocChoGiuChoCuaAI(unittest.TestCase):
    def test_bo_cho_giu_cho_the_tour(self):
        for raw in ("Tây Ninh rẻ nhất.\n[Chèn thẻ tour tại đây]", "Xem bên dưới [the tour se hien thi o day]", "Mời bạn xem [Tour card]"):
            with self.subTest(raw=raw):
                out = llm_gemini.loc_dau_ra(raw)
                self.assertNotIn("[", out)

    def test_khong_xoa_ngoac_vuong_binh_thuong(self):
        self.assertEqual(llm_gemini.loc_dau_ra("Giá [đã gồm VAT] là 5 triệu"), "Giá [đã gồm VAT] là 5 triệu")


class HoiVeViecDatTourKhongMoLuong(NenTest):
    def test_hoi_can_cccd_khong_bi_cuon_vao_luong_dat(self):
        res = self.gui("Đặt tour qua chat thì có cần gửi CCCD hay hộ chiếu cho bạn không?")
        self.assertEqual(self.trang_thai().get("step"), None)
        self.assertFalse(res.get("choices"))

    def test_noi_ro_muon_dat_van_mo_luong(self):
        self.gui("Tôi muốn đặt tour Đà Lạt")
        self.assertEqual(self.trang_thai()["step"], "so_nguoi")

    def test_hoi_dat_tour_co_ten_tour_van_mo_luong(self):
        """Câu hỏi nhưng CÓ nêu tour ("đặt tour Đà Lạt được không?") vẫn là ý muốn đặt."""
        self.gui("Mình đặt tour Đà Lạt được không?")
        self.assertEqual(self.trang_thai()["step"], "so_nguoi")


@unittest.skipUnless(TOAN_BO, "ChromaDB chưa có dữ liệu tour")
class TourDoSauCauTraLoiCuaBot(unittest.TestCase):
    def test_tour_do_lay_diem_den_trong_cau_tra_loi_gan_nhat(self):
        ls = [{"role": "user", "content": "tour nào rẻ nhất"},
              {"role": "assistant", "content": "Trong đó, tour đi Tây Ninh có mức giá ưu đãi nhất."}]
        tours = rag.tim_tour_lien_quan("tour đó đi mấy ngày?", lich_su=ls)
        self.assertTrue(tours)
        self.assertTrue(all(t["diem_den"] == "Tây Ninh" for t in tours))

    def test_cau_cua_khach_van_uu_tien_hon_cau_tra_loi(self):
        ls = [{"role": "user", "content": "Có tour Nhật Bản không?"},
              {"role": "assistant", "content": "Có ạ, ngoài ra tour Hàn Quốc cũng đang hot."}]
        self.assertEqual(rag.diem_den_tu_lich_su(ls, ca_cau_tra_loi=True), "Nhật Bản")

    def test_khong_tham_chieu_thi_khong_doc_cau_tra_loi(self):
        ls = [{"role": "user", "content": "tour nào rẻ nhất"}, {"role": "assistant", "content": "Tour Tây Ninh rẻ nhất."}]
        self.assertIsNone(rag.diem_den_tu_lich_su(ls))
