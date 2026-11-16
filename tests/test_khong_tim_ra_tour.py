"""Khách muốn đặt tour nhưng chatbot không tìm ra tour nào khớp (bug thật: "Tôi muốn đặt tour đài" chỉ hiện mỗi nút
"Huỷ đặt tour"). Phải nói rõ là chưa tìm thấy và đưa vài tour gợi ý để bấm đặt tiếp."""
from unittest import mock

import dat_tour
from tests.helpers import THE_DALAT, THE_NGA, NenTest

GOI_Y = [{"key": THE_DALAT["tour_key"], "ten": THE_DALAT["ten"]}, {"key": THE_NGA["tour_key"], "ten": THE_NGA["ten"]}]


class KhongTimRaTour(NenTest):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(dat_tour, "tour_goi_y", return_value=[dict(t) for t in GOI_Y])
        self.goi_y = p.start()
        self.addCleanup(p.stop)

    def test_noi_ten_noi_khong_co_tour_thi_bao_chua_tim_thay_va_goi_y(self):
        res = self.gui("Tôi muốn đặt tour Narnia")
        self.assertIn("chưa tìm thấy", res["reply"].lower())
        self.assertEqual(self.ids(res), ["tour:k-dalat", "tour:k-nga", "huy"])
        self.assertEqual(self.trang_thai()["step"], "chon_tour")

    def test_chua_noi_tour_nao_thi_hoi_va_goi_y(self):
        res = self.gui("Tôi muốn đặt tour")
        self.assertNotIn("chưa tìm thấy", res["reply"].lower())
        self.assertIn("tour:k-dalat", self.ids(res))
        self.assertIn("huy", self.ids(res))

    def test_uu_tien_tour_vua_goi_y_trong_cuoc_tro_chuyen(self):
        dat_tour.ghi_tour_gan_nhat(f"{self.nguoi_dung_hien_tai}:{self.conv}", [{"tour_key": "k-nga", "ten": THE_NGA["ten"]}])
        res = self.gui("Tôi muốn đặt tour Narnia")
        self.assertEqual(self.ids(res), ["tour:k-nga", "huy"])
        self.goi_y.assert_not_called()

    def test_bam_tour_goi_y_thi_dat_tiep_binh_thuong(self):
        self.gui("Tôi muốn đặt tour Narnia")
        res = self.bam("tour:k-dalat")  # Đà Lạt chỉ có 1 ngày -> tự chốt ngày, hỏi số người
        self.assertEqual(self.trang_thai()["step"], "so_nguoi")
        self.co_nut(res, "sl:")

    def test_khong_co_tour_goi_y_nao_van_con_nut_huy(self):
        self.goi_y.return_value = []
        res = self.gui("Tôi muốn đặt tour Narnia")
        self.assertEqual(self.ids(res), ["huy"])
        self.assertIn("chưa tìm thấy", res["reply"].lower())

    def test_dang_o_buoc_chon_tour_go_noi_khong_co(self):
        self.gui("Tôi muốn đặt tour Narnia")
        res = self.gui("Atlantis")
        self.assertIn("chưa tìm thấy", res["reply"].lower())
        self.assertIn("tour:k-dalat", self.ids(res))
