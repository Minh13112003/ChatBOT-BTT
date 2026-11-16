"""Trạng thái THỰC TẾ hiện nay: bước "người đi cùng" (thân nhân) đang tắt (dat_tour.DUNG_THAN_NHAN = False)."""
from unittest import mock

import dat_tour
from tests.helpers import NenTest

# Hàm thật (NenTest mock dat_tour.tao_booking trong setUp).
_TAO_BOOKING_THAT = dat_tour.tao_booking


class DatTourKhongCoThanNhan(NenTest):
    dung_than_nhan = False

    def test_chon_so_nguoi_xong_di_thang_toi_bang_tom_tat(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        res = self.bam("sl:2,1,0")
        self.assertEqual(self.trang_thai()["step"], "xac_nhan")
        self.assertIn("xn:dong_y", self.ids(res))
        self.khong_nut(res, "nguoi:")
        self.assertNotIn("thân nhân", res["reply"].lower())

    def test_khong_goi_nestjs_lay_than_nhan(self):
        with mock.patch.object(dat_tour, "lay_than_nhan", side_effect=AssertionError("không được gọi")):
            self.gui("Tôi muốn đặt tour Nga")
            self.bam("dot:N1")
            res = self.bam("sl:3,0,0")
        self.assertIn("xn:dong_y", self.ids(res))

    def test_dong_y_dat_tour_khong_co_nguoi_di_cung(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        self.bam("sl:2,1,0")
        res = self.bam("xn:dong_y")
        self.assertIn("booking", res)
        don = self.don_da_gui()
        self.assertEqual((don["adults"], don["children"], don["infants"]), (2, 1, 0))
        self.assertEqual(don.get("relative_ids", []), [])

    def test_tour_nuoc_ngoai_khong_nhac_ho_chieu_visa(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        res = self.bam("sl:2,0,0")
        low = res["reply"].lower()
        self.assertNotIn("hộ chiếu", low)
        self.assertNotIn("visa", low)

    def test_goi_chu_van_chay_het_luong(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.gui("ngày đầu")
        res = self.gui("2 người lớn 1 trẻ em")
        self.assertIn("xn:dong_y", self.ids(res))
        res = self.gui("đồng ý")
        self.assertIn("booking", res)

    def test_khong_dong_y_khong_hien_nut_doi_nguoi_di_cung(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        self.bam("sl:2,0,0")
        res = self.bam("xn:khong")
        self.assertIn("doi:ngay", self.ids(res))
        self.assertIn("doi:so_nguoi", self.ids(res))
        self.assertNotIn("doi:nguoi", self.ids(res))

    def test_body_gui_nestjs_khong_co_giay_to(self):
        """Body THẬT của POST /bookings: chỉ tour, đợt, số khách, thanh toán — không có CCCD/hộ chiếu/visa/hành khách."""
        st = {
            "tour": {"key": "T1", "ten": "Tour Nga", "foreign": True},
            "dot": {"key": "N1", "date": "2030-01-10", "price": 1000000, "seats": 9},
            "adults": 2, "children": 1, "infants": 0, "relative_ids": [],
        }
        tra_ve = mock.Mock(status_code=201)
        tra_ve.json.return_value = {"data": {"id": "b1"}}
        with mock.patch.object(dat_tour, "NESTJS_BASE_URL", "http://nest"),                 mock.patch.object(dat_tour.httpx, "post", return_value=tra_ve) as post:
            booking, loi = _TAO_BOOKING_THAT("tok", st)
        self.assertIsNone(loi)
        self.assertEqual(booking, {"id": "b1"})
        body = post.call_args.kwargs["json"]
        self.assertEqual(
            set(body),
            {"tourKey", "departureKey", "departureDate", "unitPrice", "adults", "children", "infants", "paymentMethod"},
        )
