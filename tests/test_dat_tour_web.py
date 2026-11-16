"""Khách web (chỉ có tên + SĐT, không tài khoản) đặt tour trong khung chat: đi hết các bước, cuối cùng ghi nhận yêu cầu cho
nhân viên gọi lại, KHÔNG tạo đơn thật trên NestJS và không dùng thân nhân."""
import uuid

import dat_tour
from tests.helpers import NenTest, dmy, ngay
from tests.test_admin_chat import NenNoiAdmin
import main


class DatTourTrenWeb(NenNoiAdmin):
    def setUp(self):
        super().setUp()
        self.thiet_bi = str(uuid.uuid4())
        main._LUOT_THEO_IP.clear()
        self.client.post("/web/identify", json={"device_id": self.thiet_bi, "name": "Nguyễn Thị Hoa", "phone": "0900000101"})
        self.session = f"web-{self.thiet_bi}:{self.conv}"

    def web(self, text="", action=None):
        body = {"message": text, "conversation_id": self.conv, "device_id": self.thiet_bi}
        if action:
            body["action"] = {"id": action}
        r = self.client.post("/web/chat", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def toi_xac_nhan(self, so="sl:2,1,0"):
        self.web("Tôi muốn đặt tour Nga")
        self.web(action="dot:N1")
        return self.web(action=so)

    def test_chot_tour_hien_nut_chon_tour_nhu_app(self):
        res = self.web("tôi muốn chốt tour")
        self.assertIn("Bạn muốn đặt tour nào", res["reply"])
        self.assertIn("huy", self.ids(res))
        res = self.web("chốt tour miền")  # nhiều tour khớp -> nút chọn tour
        self.assertTrue(sum(i.startswith("tour:") for i in self.ids(res)) >= 2, res)

    def test_chi_noi_chot_sau_khi_xem_tour_thi_dat_tour_vua_goi_y(self):
        self.tours_chat = [{"tour_key": "k-nga", "ten": "Du Lịch Nga - Moscow", "id": "i", "gia": 1, "so_ngay": 1, "ngay_khoi_hanh": "", "so_cho_con": 1, "anh": None, "url": "", "diem_den": "", "loai_hinh": ""}]
        self.web("Cho xem tour Nga")
        res = self.web("chốt")
        self.assertTrue(any(i.startswith("dot:") for i in self.ids(res)), res)

    def test_di_het_cac_buoc_khong_hoi_nguoi_di_cung(self):
        res = self.toi_xac_nhan()
        self.assertIn("xn:dong_y", self.ids(res))
        self.assertNotIn("nguoi:ok", self.ids(res))
        self.assertIn("nhân viên sẽ hỏi bạn khi liên hệ", res["reply"])
        self.assertNotIn("hộ chiếu", res["reply"])
        self.assertNotIn("doi:nguoi", [c["id"] for c in self.web(action="xn:khong")["choices"]])

    def test_dong_y_chi_ghi_nhan_yeu_cau_khong_tao_don_that(self):
        self.toi_xac_nhan()
        res = self.web(action="xn:dong_y")
        self.assertIn("ghi nhận yêu cầu", res["reply"])
        self.assertIn("CHƯA phải đơn đã giữ chỗ", res["reply"])
        self.assertNotIn("booking", res)
        self.assertNotIn("_don", res)
        self.tao_booking.assert_not_called()
        don = self.deal.call_args.args[2]
        self.assertEqual(self.deal.call_args.args[:2], ("WEB", self.thiet_bi))
        self.assertEqual((don["guests"], don["tourCode"]), (3, "NGA01"))
        self.assertNotIn("orderCode", don)

    def test_bam_dong_y_lan_2_khong_gui_trung(self):
        self.toi_xac_nhan()
        self.web(action="xn:dong_y")
        self.web(action="xn:dong_y")
        self.assertEqual(self.deal.call_count, 1)

    def test_con_so_nguoi_gioi_han_cho_va_kiem_tra_lai_nhu_app(self):
        self.web("Tôi muốn đặt tour Nga")
        self.web(action="dot:N3")
        res = self.web(action="sl:5,0,0")
        self.assertIn("chỉ còn 3 chỗ", res["reply"])

    def test_khach_app_van_tao_don_that_va_hoi_than_nhan(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        res = self.bam("sl:2,1,0")
        self.assertIn("nguoi:r-an", self.ids(res))
        self.bam("nguoi:ok", ["r-an"])
        res = self.bam("xn:dong_y")
        self.assertEqual(res["booking"]["booking_id"], "bk-1")
        self.tao_booking.assert_called_once()


class NhanDienChiNoiChot(NenTest):
    def test_cau_chi_noi_muon_dat(self):
        for cau in ["chốt", "Chốt đi", "chốt luôn", "ok chốt", "đặt", "đặt luôn đi bạn", "mình đặt nhé", "giữ chỗ giúp mình", "book", "chốt cái này"]:
            with self.subTest(cau=cau):
                self.assertTrue(dat_tour.chi_noi_muon_dat(cau))

    def test_cau_khac_khong_phai(self):
        for cau in ["đặt cọc thế nào", "tôi đã đặt rồi", "chưa muốn đặt", "chốt giá bao nhiêu", "đặt tour Nga", "ok", "vâng", "chốt tour Đà Lạt 2 người"]:
            with self.subTest(cau=cau):
                self.assertFalse(dat_tour.chi_noi_muon_dat(cau))

    def test_dang_o_buoc_xac_nhan_thi_ok_chot_la_dong_y_khong_bat_dau_lai(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        self.bam("sl:2,1,0")
        self.bam("nguoi:ok", ["r-an"])
        res = self.gui("ok chốt")
        self.assertEqual(res["booking"]["booking_id"], "bk-1")
        self.tao_booking.assert_called_once()

    def test_phien_web_nhan_ra_qua_ma_phien(self):
        self.assertTrue(dat_tour.khach_web("web-abc:cuoc-tro-chuyen"))
        self.assertFalse(dat_tour.khach_web("u1:cuoc-tro-chuyen"))
