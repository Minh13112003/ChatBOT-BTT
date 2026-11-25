"""Khách đang đặt dở tour X mà hỏi sang tour Y (yêu cầu chủ dự án 2026-11-23): trả lời tour Y kèm câu hỏi 3 hướng,
thay vì chỉ nhắc "bạn đang đặt dở".  Tiếp tục tư vấn tour mới / Tiếp tục đặt tour X / Huỷ đặt tour X."""
import unittest

from tests.helpers import THE_DALAT, THE_NGA, NenTest

CAU_HOI_TOUR_KHAC = "Tour Đà Lạt có gì hay không?"


class HoiTourKhacGiuaChung(NenTest):
    def toi_buoc_chon_ngay_nga(self):
        res = self.gui("Tôi muốn đặt tour Nga")
        self.co_nut(res, "dot:")
        return res

    def hoi_tour_dalat(self):
        self.tours_chat = [dict(THE_DALAT)]
        return self.gui(CAU_HOI_TOUR_KHAC)

    def test_hoi_tour_khac_hien_3_lua_chon(self):
        self.toi_buoc_chon_ngay_nga()
        res = self.hoi_tour_dalat()
        self.assertEqual(self.gemini.call_count, 1)
        self.assertIn("đang trong quá trình đặt tour", res["reply"])
        self.assertIn("Du Lịch Nga", res["reply"])
        self.assertEqual(self.ids(res), ["dd:tu_van", "dd:tiep", "huy"])
        self.assertEqual([t["tour_key"] for t in res["tours"]], ["k-dalat"])
        # Đơn đang dở vẫn còn nguyên, chưa bị đổi sang tour mới.
        self.assertEqual(self.trang_thai()["tour"]["key"], "k-nga")

    def test_hoi_ve_chinh_tour_dang_dat_chi_nhac_binh_thuong(self):
        self.toi_buoc_chon_ngay_nga()
        self.tours_chat = [dict(THE_NGA)]
        res = self.gui("Tour này có bao gồm vé máy bay không?")
        self.assertIn("đặt dở", res["reply"])
        self.khong_nut(res, "dd:")
        self.co_nut(res, "dot:")

    def test_cau_hoi_khong_ra_the_tour_chi_nhac_binh_thuong(self):
        self.toi_buoc_chon_ngay_nga()
        self.tours_chat = []
        res = self.gui("Đi Nga có cần visa không?")
        self.assertIn("đặt dở", res["reply"])
        self.khong_nut(res, "dd:")
        self.co_nut(res, "dot:")

    def test_tiep_tuc_tu_van_tam_dung_va_khong_nhac_lai(self):
        self.toi_buoc_chon_ngay_nga()
        self.hoi_tour_dalat()
        res = self.bam("dd:tu_van")
        self.assertIn("tiếp tục tư vấn", res["reply"])
        self.assertEqual(self.ids(res), ["dd:tiep", "huy"])
        self.assertTrue(self.trang_thai().get("tam_dung"))
        self.assertEqual(self.trang_thai()["tour"]["key"], "k-nga")
        # Hỏi tiếp tour khác: tư vấn bình thường, không nhắc 3 lựa chọn nữa.
        res = self.hoi_tour_dalat()
        self.assertNotIn("đang trong quá trình", res["reply"])
        self.khong_nut(res, "dd:")
        self.khong_nut(res, "dot:")

    def test_tiep_tuc_dat_tour_cu_quay_ve_dung_buoc(self):
        self.toi_buoc_chon_ngay_nga()
        self.hoi_tour_dalat()
        self.bam("dd:tu_van")
        res = self.bam("dd:tiep")
        self.assertIn("đặt dở", res["reply"])
        self.co_nut(res, "dot:")
        self.assertFalse(self.trang_thai().get("tam_dung"))
        self.assertEqual(self.trang_thai()["step"], "chon_ngay")

    def test_bam_tiep_tuc_dat_ngay_khi_dang_hoi_3_lua_chon(self):
        self.toi_buoc_chon_ngay_nga()
        self.hoi_tour_dalat()
        res = self.bam("dd:tiep")
        self.assertIn("đặt dở", res["reply"])
        self.co_nut(res, "dot:")

    def test_huy_xoa_phien_dat_tour(self):
        self.toi_buoc_chon_ngay_nga()
        self.hoi_tour_dalat()
        res = self.bam("huy")
        self.assertIn("huỷ", res["reply"].lower())
        self.assertIsNone(self.trang_thai().get("step"))

    def test_go_chu_dat_tiep_khi_dang_tam_dung(self):
        self.toi_buoc_chon_ngay_nga()
        self.hoi_tour_dalat()
        self.bam("dd:tu_van")
        res = self.gui("ok đặt tiếp nha")
        self.co_nut(res, "dot:")
        self.assertFalse(self.trang_thai().get("tam_dung"))

    def test_dang_tam_dung_muon_dat_tour_moi_thi_mo_luong_moi(self):
        self.toi_buoc_chon_ngay_nga()
        self.hoi_tour_dalat()
        self.bam("dd:tu_van")
        res = self.gui("Tôi muốn đặt tour Đà Lạt")
        self.assertEqual(self.trang_thai()["tour"]["key"], "k-dalat")
        self.assertFalse(self.trang_thai().get("tam_dung"))
        self.assertTrue(res["reply"])

    def test_nut_cu_khi_khong_con_phien_bao_het_han(self):
        res = self.bam("dd:tiep")
        self.assertIn("hết hạn", res["reply"])


if __name__ == "__main__":
    unittest.main()
