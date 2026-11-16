"""Luồng ĐẶT TOUR qua chatbot — kiểm theo đúng yêu cầu của chủ dự án:

  YC1  Khách nói "tôi muốn đặt tour …" -> chatbot xác định tour.
  YC2  Tour chỉ có 1 ngày khởi hành -> chốt luôn ngày đó.
  YC3  Tour nhiều ngày -> cho khách chọn (chỉ ngày còn chỗ, chưa qua).
  YC4  Hỏi số người theo từng loại (người lớn / trẻ em / em bé).
  YC5  Hỏi người đi cùng, ưu tiên thân nhân đã lưu; người mới nhập ở trang booking (không thu CCCD trong chat).
  YC6  Báo tổng tiền, 2 đáp án "Đồng ý" / "Không đồng ý".
  YC7  "Đồng ý" -> ĐẶT TOUR LUÔN trong chat (POST /api/v1/bookings), trả `booking`
       gồm mã đơn + đường dẫn tới trang trạng thái đơn để app mở.
  YC8  "Không đồng ý" -> hỏi muốn đổi gì (ngày / số người / người đi cùng / huỷ).
  YC9  Chỉ tạo booking khi khách đã xem bảng tóm tắt và bấm "Đồng ý"; bấm lại
       lần 2 KHÔNG tạo đơn trùng; đặt hỏng thì giữ bước xác nhận để bấm lại.
"""
import unittest
from unittest import mock

import database
import dat_tour
from tests.helpers import GIA, NenTest, THE_DALAT, THE_HUE, THE_NGA, TOUR_1NGAY, TOUR_NHIEU, dmy, ngay


class YC1_XacDinhTour(NenTest):
    def test_goi_ten_diem_den(self):
        res = self.gui("Tôi muốn đặt tour Nga")
        self.assertIn(TOUR_NHIEU["name"], res["reply"])
        self.gemini.assert_not_called()

    def test_cac_cach_noi_khac(self):
        for cau in ["đặt tour Nga", "book tour nga giúp mình", "Em muốn đăng ký tour Nga ạ", "chốt tour Nga", "dat tour nga"]:
            with self.subTest(cau=cau):
                self.setUp()
                self.assertIn(TOUR_NHIEU["name"], self.gui(cau)["reply"])

    def test_nhieu_tour_khop_thi_hoi_lai(self):
        res = self.gui("Tôi muốn đặt tour miền Trung")
        self.assertEqual(self.ids(res), ["tour:k-dalat", "tour:k-nga", "tour:k-hue", "huy"])
        res = self.bam("tour:k-nga")
        self.assertIn(TOUR_NHIEU["name"], res["reply"])

    def test_khong_ro_tour_nao_thi_hoi(self):
        res = self.gui("Tôi muốn đặt tour")
        self.assertIn("tour nào", res["reply"])
        # khách trả lời bằng tên điểm đến
        res = self.gui("Đà Lạt")
        self.assertIn(TOUR_1NGAY["name"], res["reply"])

    def test_dat_tour_nay_sau_khi_duoc_goi_y_1_tour(self):
        self.tours_chat = [THE_NGA]
        res = self.gui("Có tour Nga không?")
        self.assertIn("Tôi muốn đặt tour này", res["goi_y"])
        res = self.gui("Tôi muốn đặt tour này")
        self.assertIn(TOUR_NHIEU["name"], res["reply"])
        self.co_nut(res, "dot:")

    def test_dat_tour_nay_khi_vua_goi_y_nhieu_tour_thi_hoi_tour_nao(self):
        self.tours_chat = [THE_DALAT, THE_NGA, THE_HUE]
        self.gui("Gợi ý tour giúp mình")
        res = self.gui("Tôi muốn đặt tour này")
        self.assertEqual(self.ids(res), ["tour:k-dalat", "tour:k-nga", "tour:k-hue", "huy"])

    def test_dat_tour_thu_2_trong_danh_sach_vua_goi_y(self):
        self.tours_chat = [THE_DALAT, THE_NGA, THE_HUE]
        for cau in ["đặt tour thứ 2", "đặt tour số 2", "mình đặt tour thứ hai nhé", "đặt tour thứ 2 đó"]:
            with self.subTest(cau=cau):
                self.setUp()
                self.tours_chat = [THE_DALAT, THE_NGA, THE_HUE]
                self.gui("Gợi ý tour giúp mình")
                self.assertIn(TOUR_NHIEU["name"], self.gui(cau)["reply"])

    def test_dat_tour_dau_tien(self):
        self.tours_chat = [THE_DALAT, THE_NGA]
        self.gui("Gợi ý tour giúp mình")
        self.assertIn(TOUR_1NGAY["name"], self.gui("đặt tour đầu tiên")["reply"])

    def test_so_nguoi_trong_cau_khong_bi_hieu_la_so_thu_tu_tour(self):
        """'đặt tour này cho 2 người' KHÔNG được tự chọn tour thứ 2 trong danh sách."""
        self.tours_chat = [THE_DALAT, THE_NGA, THE_HUE]
        self.gui("Gợi ý tour giúp mình")
        res = self.gui("Tôi muốn đặt tour này cho 2 người")
        self.assertEqual(self.ids(res), ["tour:k-dalat", "tour:k-nga", "tour:k-hue", "huy"], res["reply"])

    def test_dat_tour_nay_khi_chua_co_tour_nao_duoc_goi_y(self):
        """Chưa gợi ý tour nào mà nói "đặt tour này": hỏi tour nào + đưa vài tour gợi ý để bấm (trước đây chỉ có nút Huỷ).
        Khách chưa nêu nơi nào nên KHÔNG nói "chưa tìm thấy"."""
        goi_y = [{"key": "k-dalat", "ten": THE_DALAT["ten"]}]
        with mock.patch.object(dat_tour, "tour_goi_y", return_value=goi_y):
            res = self.gui("Tôi muốn đặt tour này")
        self.assertIn("tour nào", res["reply"])
        self.assertNotIn("chưa tìm thấy", res["reply"].lower())
        self.assertEqual(self.ids(res), ["tour:k-dalat", "huy"])

    def test_goi_ten_tour_khac_van_duoc_du_dang_co_tour_vua_goi_y(self):
        self.tours_chat = [THE_DALAT]
        self.gui("Có tour Đà Lạt không")
        self.assertIn(TOUR_NHIEU["name"], self.gui("Tôi muốn đặt tour Nga")["reply"])

    def test_cau_hoi_chinh_sach_khong_kich_hoat_dat_tour(self):
        for cau in ["Đặt tour thì đặt cọc bao nhiêu?", "Đặt tour xong thanh toán thế nào"]:
            with self.subTest(cau=cau):
                self.setUp()
                res = self.gui(cau)
                self.assertEqual(self.gemini.call_count, 1, f"Phải để AI trả lời: {res['reply']}")
                self.assertFalse(self.trang_thai().get("step"))
        # Hỏi cách đặt tour: trả lời viết sẵn (tests/test_hoi_quy_trinh.py), cũng không mở luồng đặt.
        for cau in ["Cách đặt tour như thế nào?", "Làm sao để đặt tour?", "Hướng dẫn tôi đặt tour"]:
            with self.subTest(cau=cau):
                self.setUp()
                self.gui(cau)
                self.assertFalse(self.trang_thai().get("step"))

    def test_khach_da_dat_roi_gap_su_co_thi_chuyen_nhan_vien_khong_mo_luong_dat(self):
        for cau in ["Tour tôi đã đặt bị sự cố", "Tôi đặt tour rồi mà chưa thấy xác nhận, đặt rồi mà", "Tôi muốn hoàn tiền tour đã đặt"]:
            with self.subTest(cau=cau):
                self.setUp()
                res = self.gui(cau)
                self.assertIn("handoff", res, res["reply"])

    def test_chua_lay_duoc_thong_tin_tour(self):
        with mock.patch.object(dat_tour, "lay_tour_live", lambda key: None):
            res = self.gui("Tôi muốn đặt tour Nga")
        self.assertIn("chưa lấy được", res["reply"])
        self.assertFalse(self.trang_thai().get("step"))

    def test_tour_het_cho(self):
        res = self.gui("Tôi muốn đặt tour Huế")
        self.assertIn("chưa có ngày khởi hành còn chỗ", res["reply"])
        self.assertFalse(res.get("choices"))


class YC2_YC3_NgayKhoiHanh(NenTest):
    def test_mot_ngay_thi_chot_luon(self):
        res = self.gui("Tôi muốn đặt tour Đà Lạt")
        self.assertIn("chỉ có một ngày khởi hành", res["reply"])
        self.assertIn(dmy(ngay(30)), res["reply"])
        self.khong_nut(res, "dot:")
        self.co_nut(res, "sl:")  # hỏi luôn số người
        self.assertEqual(self.trang_thai()["dot"]["key"], "D1")

    def test_nhieu_ngay_chi_hien_ngay_con_cho_va_chua_qua_theo_thu_tu(self):
        res = self.gui("Tôi muốn đặt tour Nga")
        self.assertEqual(self.ids(res), ["dot:N1", "dot:N2", "dot:N3", "huy"])
        self.assertIn("3 ngày khởi hành", res["reply"])
        nhan = res["choices"][0]["label"]
        self.assertIn(dmy(ngay(20)), nhan)
        self.assertIn("còn 30 chỗ", nhan)
        self.assertIn("10.000.000 đ", nhan)

    def test_chon_ngay_bang_nut(self):
        self.gui("Tôi muốn đặt tour Nga")
        res = self.bam("dot:N2")
        self.assertIn(dmy(ngay(50)), res["reply"])
        self.co_nut(res, "sl:")

    def test_go_ngay_bang_chu(self):
        d = ngay(50)
        ngay_so, thang_so = int(d[8:10]), int(d[5:7])
        for cau in [f"{ngay_so}/{thang_so}", dmy(d), f"ngày {ngay_so} tháng {thang_so}", f"mình đi ngày {ngay_so}-{thang_so} nhé"]:
            with self.subTest(cau=cau):
                self.setUp()
                self.gui("Tôi muốn đặt tour Nga")
                self.gui(cau)
                self.assertEqual(self.trang_thai().get("dot", {}).get("key"), "N2")

    def test_go_ngay_dau_ngay_cuoi(self):
        for cau, key in [("ngày đầu tiên", "N1"), ("ngày sớm nhất", "N1"), ("ngày cuối", "N3"), ("ngày gần nhất", "N1")]:
            with self.subTest(cau=cau):
                self.setUp()
                self.gui("Tôi muốn đặt tour Nga")
                self.gui(cau)
                self.assertEqual(self.trang_thai().get("dot", {}).get("key"), key)

    def test_go_ngay_khong_co_thi_hoi_lai_kem_nut(self):
        self.gui("Tôi muốn đặt tour Nga")
        res = self.gui("31/2")
        self.assertEqual(self.ids(res), ["dot:N1", "dot:N2", "dot:N3", "huy"])
        self.assertNotIn("dot", self.trang_thai())

    def test_nut_ngay_khong_hop_le_thi_hien_lai_danh_sach(self):
        self.gui("Tôi muốn đặt tour Nga")
        res = self.bam("dot:khong-co")
        self.assertEqual(self.ids(res), ["dot:N1", "dot:N2", "dot:N3", "huy"])

    def test_khong_cho_chon_ngay_het_cho_hoac_da_qua(self):
        self.gui("Tôi muốn đặt tour Nga")
        for key in ["N0", "N9"]:
            self.bam(f"dot:{key}")
            self.assertNotIn("dot", self.trang_thai())


class YC4_SoNguoi(NenTest):
    def test_bam_nut(self):
        self.toi_buoc_so_nguoi()
        self.bam("sl:2,0,0")
        st = self.trang_thai()
        self.assertEqual((st["adults"], st["children"], st["infants"]), (2, 0, 0))

    def test_go_chu_theo_tung_loai(self):
        cases = {
            "2 người lớn 1 trẻ em": (2, 1, 0),
            "2 người lớn, 1 trẻ em và 1 em bé": (2, 1, 1),
            "hai người lớn một trẻ em": (2, 1, 0),
            "3 người": (3, 0, 0),
            "tôi đi một mình": (1, 0, 0),
            "2 nguoi lon 2 tre em": (2, 2, 0),
            "1 người lớn 1 em bé": (1, 0, 1),
            "Gia đình tôi có 4 người gồm 2 người lớn 2 trẻ em": (2, 2, 0),
            "2 vợ chồng và 1 bé": (2, 1, 0),
            "mười hai người lớn": (12, 0, 0),
        }
        for cau, mong in cases.items():
            with self.subTest(cau=cau):
                self.assertEqual(dat_tour.phan_tich_so_nguoi(cau), mong)

    def test_cau_co_chu_thoi_khong_bi_hieu_la_huy(self):
        """'2 người lớn thôi' là trả lời số người, không phải huỷ đặt tour."""
        self.toi_buoc_so_nguoi()
        for cau in ["2 người lớn thôi", "chỉ 2 người thôi"]:
            with self.subTest(cau=cau):
                res = self.gui(cau)
                self.assertNotIn("đã huỷ", res["reply"])
                self.assertEqual(self.trang_thai().get("adults"), 2)

    def test_phai_co_it_nhat_1_nguoi_lon(self):
        self.toi_buoc_so_nguoi()
        for cau in ["2 trẻ em", "1 em bé"]:
            res = self.gui(cau)
            self.assertIn("ít nhất 1 người lớn", res["reply"])
            self.co_nut(res, "sl:")
            self.assertNotIn("adults", self.trang_thai())

    def test_khong_nhan_qua_so_cho_con(self):
        self.toi_buoc_so_nguoi()  # tour Đà Lạt còn 10 chỗ
        res = self.gui("11 người lớn")
        self.assertIn("chỉ còn 10 chỗ", res["reply"])
        self.assertNotIn("adults", self.trang_thai())

    def test_toi_da_20_khach_thi_bao_dung_ly_do(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")  # còn 30 chỗ
        res = self.gui("25 người lớn")
        self.assertNotIn("adults", self.trang_thai())
        self.assertIn("20", res["reply"], "Phải nói giới hạn 20 khách/đơn, không phải 'chỉ còn 30 chỗ'")
        self.assertNotIn("chỉ còn 30 chỗ", res["reply"])

    def test_so_am_tu_nut_gia_mao_bi_tu_choi(self):
        self.toi_buoc_so_nguoi()
        for aid in ["sl:1,-5,0", "sl:2,0,-1", "sl:-1,3,0", "sl:0,0,0"]:
            with self.subTest(aid=aid):
                self.bam(aid)
                self.assertNotIn("adults", self.trang_thai())

    def test_go_khong_ra_so_thi_hoi_lai(self):
        self.toi_buoc_so_nguoi()
        res = self.gui("để mình tính đã")
        self.co_nut(res, "sl:")
        self.assertNotIn("adults", self.trang_thai())


class YC5_NguoiDiCung(NenTest):
    def test_di_1_minh_thi_khong_hoi_nguoi_di_cung(self):
        self.toi_buoc_so_nguoi()
        res = self.bam("sl:1,0,0")
        self.assertEqual(self.ids(res), ["xn:dong_y", "xn:khong"])

    def test_hien_than_nhan_de_chon_nhieu_nguoi(self):
        self.toi_buoc_so_nguoi()
        res = self.bam("sl:2,1,0")
        self.assertTrue(res.get("multi"))
        self.assertEqual(res["toi_da"], 2)
        self.assertEqual(self.ids(res), ["nguoi:r-an", "nguoi:r-lan", "nguoi:r-bi", "nguoi:skip", "huy"])
        self.assertIn("Nguyễn Văn An", res["choices"][0]["label"])
        self.assertIn("tuổi", res["choices"][0]["label"])
        self.assertIn("khách số 1", res["reply"])

    def test_chon_than_nhan(self):
        self.toi_buoc_so_nguoi()
        self.bam("sl:3,0,0")
        res = self.bam("nguoi:ok", ["r-an", "r-lan"])
        self.assertEqual(self.trang_thai()["relative_ids"], ["r-an", "r-lan"])
        self.assertIn("Nguyễn Văn An, Trần Thị Lan", res["reply"])

    def test_chon_it_hon_so_nguoi_thi_nhac_nhap_o_trang_booking(self):
        self.toi_buoc_so_nguoi()
        self.bam("sl:4,0,0")
        res = self.bam("nguoi:ok", ["r-an"])
        self.assertIn("còn 2 người bạn nhập ở trang booking", res["reply"])

    def test_nhap_sau_o_trang_booking(self):
        self.toi_buoc_so_nguoi()
        self.bam("sl:2,0,0")
        res = self.bam("nguoi:skip")
        self.assertEqual(self.trang_thai()["relative_ids"], [])
        self.assertEqual(self.ids(res), ["xn:dong_y", "xn:khong"])

    def test_khong_nhan_qua_so_nguoi_va_id_la(self):
        self.toi_buoc_so_nguoi()
        self.bam("sl:2,0,0")  # chỉ còn 1 người đi cùng
        self.bam("nguoi:ok", ["id-cua-nguoi-khac", "r-an", "r-lan"])
        self.assertEqual(self.trang_thai()["relative_ids"], ["r-an"])

    def test_chua_co_than_nhan(self):
        self.than_nhan = []
        self.toi_buoc_so_nguoi()
        res = self.bam("sl:2,0,0")
        self.assertIn("chưa có thân nhân", res["reply"])
        self.assertIn("trang booking", res["reply"])
        self.assertEqual(self.ids(res), ["xn:dong_y", "xn:khong"])

    def test_khong_lay_duoc_than_nhan_van_di_tiep(self):
        self.than_nhan = None
        self.toi_buoc_so_nguoi()
        res = self.bam("sl:2,0,0")
        self.assertIn("chưa lấy được danh sách thân nhân", res["reply"])
        self.assertEqual(self.ids(res), ["xn:dong_y", "xn:khong"])

    def test_go_ten_than_nhan(self):
        self.toi_buoc_so_nguoi()
        self.bam("sl:3,0,0")
        self.gui("mình đi với Lan và Bảo")
        self.assertEqual(sorted(self.trang_thai()["relative_ids"]), ["r-bi", "r-lan"])

    def test_go_ten_khong_bat_nham_ten_nam_trong_ten_khac(self):
        """Gõ 'Lan' không được chọn luôn cả 'An' (an nằm trong lan)."""
        self.toi_buoc_so_nguoi()
        self.bam("sl:3,0,0")
        self.gui("Lan")
        self.assertEqual(self.trang_thai()["relative_ids"], ["r-lan"])

    def test_go_khong_hieu_thi_hoi_lai_van_con_nut_chon(self):
        self.toi_buoc_so_nguoi()
        self.bam("sl:3,0,0")
        res = self.gui("ờ để xem")
        self.co_nut(res, "nguoi:r-an")
        self.co_nut(res, "nguoi:skip")
        self.assertTrue(res.get("multi"))

    def test_go_khong_hoac_nhap_sau(self):
        for cau in ["không", "nhập sau", "bỏ qua"]:
            with self.subTest(cau=cau):
                self.setUp()
                self.toi_buoc_so_nguoi()
                self.bam("sl:2,0,0")
                res = self.gui(cau)
                self.assertEqual(self.ids(res), ["xn:dong_y", "xn:khong"])

    def test_khong_luu_giay_to_khach_go_trong_chat_vao_trang_thai(self):
        self.toi_buoc_so_nguoi()
        self.bam("sl:2,0,0")
        self.gui("CCCD của vợ tôi là 079123456789")
        with database.ket_noi() as conn:
            raw = conn.execute("SELECT state FROM booking_state").fetchone()
        self.assertNotIn("079123456789", raw[0] if raw else "")

    def test_chatbot_khong_bao_gio_xin_giay_to_trong_chat(self):
        tat_ca = []
        tat_ca.append(self.gui("Tôi muốn đặt tour Nga"))
        tat_ca.append(self.bam("dot:N1"))
        tat_ca.append(self.bam("sl:3,1,0"))
        tat_ca.append(self.bam("nguoi:ok", ["r-an"]))
        for res in tat_ca:
            thuong = res["reply"].lower()
            for cum in ["cho mình xin", "nhập số cccd", "gửi cccd", "gửi số hộ chiếu", "cho mình số"]:
                self.assertNotIn(cum, thuong)
        self.assertIn("nhập ở trang booking", tat_ca[-1]["reply"])


class YC6_TongTien(NenTest):
    def test_tong_tien_nguoi_lon_tre_em_em_be(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        self.bam("sl:2,1,1")
        res = self.bam("nguoi:skip")
        # 2 x 10tr + 1 x 8tr + 1 x 4tr = 32tr (cùng công thức với trang booking của app)
        self.assertIn("32.000.000 đ", res["reply"])
        self.assertIn("2 người lớn, 1 trẻ em, 1 em bé", res["reply"])
        self.assertIn(TOUR_NHIEU["name"], res["reply"])
        self.assertIn(dmy(ngay(20)), res["reply"])

    def test_gia_theo_dung_ngay_da_chon(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N3")  # ngày này giá 12tr
        res = self.bam("sl:1,0,0")
        self.assertIn("12.000.000 đ", res["reply"])

    def test_dung_2_dap_an(self):
        res = self.toi_buoc_xac_nhan()
        self.assertEqual([c["label"] for c in res["choices"]], ["Đồng ý", "Không đồng ý"])

    def test_tour_nuoc_ngoai_nhac_ho_chieu_visa_tour_trong_nuoc_thi_khong(self):
        res = self.toi_buoc_xac_nhan()
        self.assertIn("hộ chiếu", res["reply"])
        self.setUp()
        self.gui("Tôi muốn đặt tour Đà Lạt")
        res = self.bam("sl:1,0,0")
        self.assertNotIn("hộ chiếu", res["reply"])

    def test_tour_chua_co_gia(self):
        self.gui("Tôi muốn đặt tour Côn Đảo")
        res = self.bam("sl:1,0,0")
        self.assertIn("liên hệ", res["reply"])
        self.assertNotIn("0 đ", res["reply"])

    def test_noi_ro_chua_gom_voucher(self):
        self.assertIn("voucher", self.toi_buoc_xac_nhan()["reply"])


class YC7_DongY(NenTest):
    def test_dong_y_dat_tour_that(self):
        self.toi_buoc_xac_nhan(sl="sl:2,1,0", chon=("r-an", "r-bi"))
        res = self.bam("xn:dong_y")
        don = self.don_da_gui()
        self.assertEqual(don["tour"]["key"], "k-nga")
        self.assertEqual(don["dot"]["key"], "N1")
        self.assertEqual(don["dot"]["date"], ngay(20))
        self.assertEqual((don["adults"], don["children"], don["infants"]), (2, 1, 0))
        self.assertEqual(res["booking"], {"booking_id": "bk-1"})
        self.assertIn("đã đặt tour", res["reply"])
        self.assertIn("trạng thái đơn", res["reply"])

    def test_go_chu_dong_y(self):
        for cau in ["Đồng ý", "ok", "được", "đúng rồi", "chốt", "dong y"]:
            with self.subTest(cau=cau):
                self.setUp()
                self.toi_buoc_xac_nhan()
                self.assertIn("booking", self.gui(cau))

    def test_chi_dat_khi_khach_dong_y(self):
        """YC9: không bước nào khác được tạo booking."""
        for res in [self.gui("Tôi muốn đặt tour Nga"), self.bam("dot:N1"), self.bam("sl:2,0,0"), self.bam("nguoi:skip"), self.bam("xn:khong")]:
            self.assertNotIn("booking", res)
        self.tao_booking.assert_not_called()

    def test_bam_dong_y_lan_2_khong_dat_trung(self):
        self.toi_buoc_xac_nhan()
        self.bam("xn:dong_y")
        res = self.bam("xn:dong_y")
        self.assertNotIn("booking", res)
        self.assertIn("hết hạn", res["reply"])
        self.assertEqual(self.tao_booking.call_count, 1, "Bấm Đồng ý lần 2 không được tạo đơn trùng")

    def test_dat_hong_thi_giu_buoc_xac_nhan_de_bam_lai(self):
        """Backend báo lỗi (hết chỗ, mạng…) -> nói đúng lý do, GIỮ nút Đồng ý, KHÔNG mất thông tin đã chọn."""
        self.toi_buoc_xac_nhan()
        self.booking_ket_qua = (None, "Không đủ chỗ. Còn 1 chỗ, bạn cần 3 chỗ.")
        res = self.bam("xn:dong_y")
        self.assertNotIn("booking", res)
        self.assertIn("Không đủ chỗ", res["reply"])
        self.assertEqual(self.ids(res), ["xn:dong_y", "xn:khong"])

        self.booking_ket_qua = ({"id": "bk-2"}, None)  # khách bấm lại, lần này đặt được
        self.assertEqual(self.bam("xn:dong_y")["booking"]["booking_id"], "bk-2")

    def test_cau_khong_ro_y_thi_hoi_lai(self):
        self.toi_buoc_xac_nhan()
        res = self.gui("hmm")
        self.assertNotIn("booking", res)
        self.assertEqual(self.ids(res), ["xn:dong_y", "xn:khong"])

    def test_sau_khi_dong_y_van_dat_tiep_duoc_tour_khac(self):
        self.toi_buoc_xac_nhan()
        self.bam("xn:dong_y")
        self.assertIn(TOUR_1NGAY["name"], self.gui("Tôi muốn đặt tour Đà Lạt")["reply"])


class YC8_KhongDongY(NenTest):
    def test_hoi_muon_doi_gi(self):
        self.toi_buoc_xac_nhan()
        res = self.bam("xn:khong")
        self.assertEqual(self.ids(res), ["doi:ngay", "doi:so_nguoi", "doi:nguoi", "huy"])
        self.assertNotIn("booking", res)

    def test_go_chu_khong_dong_y(self):
        for cau in ["Không đồng ý", "không", "chưa đúng", "sai rồi"]:
            with self.subTest(cau=cau):
                self.setUp()
                self.toi_buoc_xac_nhan()
                self.assertEqual(self.ids(self.gui(cau)), ["doi:ngay", "doi:so_nguoi", "doi:nguoi", "huy"])

    def test_doi_ngay_giu_nguyen_so_nguoi_va_nguoi_di_cung(self):
        self.toi_buoc_xac_nhan(sl="sl:2,1,0", chon=("r-an",))
        self.bam("xn:khong")
        res = self.bam("doi:ngay")
        self.assertEqual(self.ids(res), ["dot:N1", "dot:N2", "dot:N3", "huy"])
        res = self.bam("dot:N2")
        # Chỉ đổi ngày: phải quay lại bảng tóm tắt với ngày mới, không bắt khách nhập lại số người
        self.assertEqual(self.ids(res), ["xn:dong_y", "xn:khong"], res["reply"])
        self.assertIn(dmy(ngay(50)), res["reply"])
        self.bam("xn:dong_y")
        don = self.don_da_gui()
        self.assertEqual(don["dot"]["key"], "N2")
        self.assertEqual((don["adults"], don["children"]), (2, 1))
        self.assertEqual(don.get("relative_ids"), ["r-an"])

    def test_doi_sang_ngay_khong_du_cho_thi_hoi_lai_so_nguoi(self):
        self.toi_buoc_xac_nhan(sl="sl:4,0,0", chon=())
        self.bam("xn:khong")
        self.bam("doi:ngay")
        res = self.bam("dot:N3")  # ngày này chỉ còn 3 chỗ, đang đặt 4 người
        self.assertIn("3 chỗ", res["reply"])
        self.assertNotIn("xn:dong_y", self.ids(res))

    def test_doi_so_nguoi_bang_nut(self):
        self.toi_buoc_xac_nhan()
        self.bam("xn:khong")
        res = self.bam("doi:so_nguoi")
        self.co_nut(res, "sl:")
        self.bam("sl:1,0,0")
        self.bam("xn:dong_y")
        don = self.don_da_gui()
        self.assertEqual((don["adults"], don["children"]), (1, 0))

    def test_doi_so_nguoi_bang_chu(self):
        self.toi_buoc_xac_nhan()
        self.bam("xn:khong")
        self.gui("đổi số người")
        self.gui("3 người lớn")
        self.assertEqual(self.trang_thai().get("adults"), 3)
        self.assertNotEqual(self.trang_thai().get("step"), "khong_dong_y")

    def test_doi_nguoi_di_cung(self):
        self.toi_buoc_xac_nhan(sl="sl:2,0,0", chon=("r-an",))
        self.bam("xn:khong")
        res = self.bam("doi:nguoi")
        self.co_nut(res, "nguoi:r-lan")
        self.bam("nguoi:ok", ["r-lan"])
        self.bam("xn:dong_y")
        self.assertEqual(self.don_da_gui().get("relative_ids"), ["r-lan"])

    def test_go_chu_doi_ngay_va_doi_nguoi_di_cung(self):
        self.toi_buoc_xac_nhan()
        self.bam("xn:khong")
        self.co_nut(self.gui("đổi ngày khởi hành"), "dot:")
        self.setUp()
        self.toi_buoc_xac_nhan()
        self.bam("xn:khong")
        self.co_nut(self.gui("đổi người đi cùng"), "nguoi:")

    def test_tour_1_ngay_khong_doi_duoc_ngay_va_van_dong_y_lai_duoc(self):
        self.gui("Tôi muốn đặt tour Đà Lạt")
        self.bam("sl:1,0,0")
        self.bam("xn:khong")
        res = self.bam("doi:ngay")
        self.assertIn("chỉ có một ngày", res["reply"])
        self.khong_nut(res, "dot:")
        self.assertIn("booking", self.gui("vậy mình đồng ý"))

    def test_sau_khi_huy_van_noi_dat_tour_nay_duoc(self):
        self.tours_chat = [THE_NGA]
        self.gui("Có tour Nga không?")
        self.gui("Tôi muốn đặt tour này")
        self.bam("huy")
        self.co_nut(self.gui("à thôi mình đặt tour này"), "dot:")

    def test_huy(self):
        self.toi_buoc_xac_nhan()
        self.bam("xn:khong")
        res = self.bam("huy")
        self.assertIn("đã huỷ", res["reply"])
        self.assertFalse(self.trang_thai().get("step"))
        self.assertIn("hết hạn", self.bam("xn:dong_y")["reply"])


class GiuaChung(NenTest):
    def test_go_huy_o_moi_buoc(self):
        for cau in ["huỷ", "hủy", "mình không đặt nữa", "huỷ đặt tour", "dừng lại"]:
            with self.subTest(cau=cau):
                self.setUp()
                self.gui("Tôi muốn đặt tour Nga")
                self.assertIn("đã huỷ", self.gui(cau)["reply"])
                self.assertFalse(self.trang_thai().get("step"))

    def test_doi_sang_tour_khac_giua_chung(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        res = self.gui("à mình muốn đặt tour Đà Lạt")
        self.assertIn(TOUR_1NGAY["name"], res["reply"])
        self.assertEqual(self.trang_thai()["tour"]["key"], "k-dalat")
        self.assertNotIn("adults", self.trang_thai())

    def test_muon_gap_nhan_vien_giua_chung_thi_duoc_chuyen(self):
        self.gui("Tôi muốn đặt tour Nga")
        res = self.gui("cho tôi gặp nhân viên tư vấn")
        self.assertIn("handoff", res, res["reply"])

    def test_nut_cua_buoc_cu_dua_ve_dung_buoc_dang_do(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.co_nut(self.bam("sl:2,0,0"), "dot:")       # chưa chọn ngày
        self.co_nut(self.bam("xn:dong_y"), "dot:")
        self.bam("dot:N1")
        self.co_nut(self.bam("xn:dong_y"), "sl:")       # chưa có số người
        self.co_nut(self.bam("nguoi:ok", ["r-an"]), "sl:")

    def test_nut_la_khong_lam_sap(self):
        self.gui("Tôi muốn đặt tour Nga")
        for aid in ["", "abc", "sl:x,y,z", "sl:1", "dot:", "tour:", "doi:khac"]:
            with self.subTest(aid=aid):
                body = {"message": "", "conversation_id": self.conv, "action": {"id": aid}}
                r = self.client.post("/chat", json=body, headers={"Authorization": "Bearer t"})
                self.assertEqual(r.status_code, 200)
                self.assertTrue(r.json()["reply"])

    def test_phien_het_han_sau_2_gio(self):
        self.gui("Tôi muốn đặt tour Nga")
        with database.ket_noi() as conn:
            conn.execute("UPDATE booking_state SET updated_at = datetime('now', '-121 minutes')")
        res = self.bam("dot:N1")
        self.assertIn("hết hạn", res["reply"])

    def test_bam_nut_khong_luu_tin_nhan_go_chu_thi_co(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        self.bam("sl:1,0,0")
        with database.ket_noi() as conn:
            n = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE role='user'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_khong_goi_ai_trong_ca_luong(self):
        self.toi_buoc_xac_nhan()
        self.bam("xn:dong_y")
        self.gemini.assert_not_called()

    def test_tach_rieng_theo_nguoi_dung_va_cuoc_tro_chuyen(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.nguoi_dung_hien_tai = "u2"
        self.assertIn("hết hạn", self.bam("dot:N1")["reply"])  # u2 không thấy phiên của u1
        self.nguoi_dung_hien_tai = "u1"
        import uuid
        khac = str(uuid.uuid4())
        self.assertIn("hết hạn", self.gui(action="dot:N1", conv=khac)["reply"])
        self.co_nut(self.bam("dot:N1"), "sl:")  # phiên gốc vẫn còn

    def test_xoa_cuoc_tro_chuyen_thi_xoa_luon_phien_dat_tour(self):
        self.gui("Tôi muốn đặt tour Nga")
        r = self.client.delete(f"/chat/{self.conv}", headers={"Authorization": "Bearer t"})
        self.assertEqual(r.status_code, 204)
        self.assertIn("hết hạn", self.bam("dot:N1")["reply"])


class YC10_GoiBackendDatTour(unittest.TestCase):
    """Kiểm CHÍNH hàm dat_tour.tao_booking() — các test trên đều thay nó bằng mock,
    nên đây là chỗ duy nhất soi đúng nội dung gửi lên NestJS và cách xử lý lỗi."""

    ST = {
        "tour": {"key": "k-nga", "ten": "Du Lịch Nga - Moscow", "foreign": True},
        "dot": {"key": "N1", "date": "2026-12-20", "price": 10_000_000, "code": "NGA01"},
        "adults": 2, "children": 1, "infants": 0,
    }

    def goi(self, phan_hoi=None, loi=None):
        """Gọi tao_booking với httpx.post bị thay; trả (kết quả, body đã gửi)."""
        da_gui = {}

        def _post(url, json=None, headers=None, timeout=None):
            da_gui["url"] = url
            da_gui["body"] = json
            da_gui["headers"] = headers
            if loi:
                raise loi
            return phan_hoi

        with mock.patch.object(dat_tour, "NESTJS_BASE_URL", "https://be.test"), \
             mock.patch.object(dat_tour.httpx, "post", _post):
            return dat_tour.tao_booking("token-abc", dict(self.ST)), da_gui

    @staticmethod
    def _resp(status, body):
        r = mock.Mock()
        r.status_code = status
        r.json.return_value = body
        return r

    def test_gui_dung_don_va_khong_kem_thong_tin_hanh_khach(self):
        (booking, loi), da_gui = self.goi(self._resp(201, {"data": {"id": "bk-9"}}))
        self.assertIsNone(loi)
        self.assertEqual(booking["id"], "bk-9")
        self.assertEqual(da_gui["url"], "https://be.test/api/v1/app/bookings")
        self.assertEqual(da_gui["body"], {
            "tourKey": "k-nga", "departureKey": "N1", "departureDate": "2026-12-20",
            "unitPrice": 10_000_000, "adults": 2, "children": 1, "infants": 0,
            "paymentMethod": "AT_OFFICE",
        })
        self.assertEqual(da_gui["headers"]["Authorization"], "Bearer token-abc")
        # Backend đã bỏ bắt buộc thông tin hành khách -> chatbot không được thu/gửi CCCD, hộ chiếu, thân nhân
        for cam in ("guests", "nationalId", "passportNumber", "visaNumber", "saveToRelatives"):
            self.assertNotIn(cam, da_gui["body"])

    def test_khong_bao_gio_tu_doi_gia(self):
        """unitPrice phải đúng giá đợt lấy từ benthanhtourist, không phải số chatbot tự tính."""
        (_, loi), da_gui = self.goi(self._resp(201, {"data": {"id": "bk-1"}}))
        self.assertIsNone(loi)
        self.assertEqual(da_gui["body"]["unitPrice"], self.ST["dot"]["price"])

    def test_backend_bao_loi_thi_noi_dung_ly_do_cho_khach(self):
        (booking, loi), _ = self.goi(self._resp(400, {"message": "Không đủ chỗ. Còn 1 chỗ, bạn cần 3 chỗ."}))
        self.assertIsNone(booking)
        self.assertIn("Không đủ chỗ", loi)

    def test_loi_dang_mang_message_gop_lai(self):
        (_, loi), _ = self.goi(self._resp(400, {"message": ["Thiếu departureKey", "unitPrice không hợp lệ"]}))
        self.assertIn("Thiếu departureKey", loi)
        self.assertIn("unitPrice không hợp lệ", loi)

    def test_token_het_han(self):
        (booking, loi), _ = self.goi(self._resp(401, {"message": "Unauthorized"}))
        self.assertIsNone(booking)
        self.assertIn("đăng nhập lại", loi)

    def test_mat_mang_thi_nhac_kiem_tra_lich_su_khong_tu_dat_lai(self):
        """Request có thể ĐÃ tạo đơn rồi — tuyệt đối không tự đặt lại, tránh 2 đơn trùng."""
        (booking, loi), _ = self.goi(loi=dat_tour.httpx.ConnectError("mat mang"))
        self.assertIsNone(booking)
        self.assertIn("Lịch sử đặt tour", loi)

    def test_chua_dang_nhap_thi_khong_goi_backend(self):
        with mock.patch.object(dat_tour, "NESTJS_BASE_URL", "https://be.test"), \
             mock.patch.object(dat_tour.httpx, "post", side_effect=AssertionError("không được gọi")):
            booking, loi = dat_tour.tao_booking("", dict(self.ST))
        self.assertIsNone(booking)
        self.assertIn("đăng nhập", loi)
