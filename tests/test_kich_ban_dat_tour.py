"""KỊCH BẢN ĐẶT TOUR nhiều lượt theo góc nhìn KHÁCH THẬT (bổ sung cho test_dat_tour_luong.py).

Mỗi test là một cuộc hội thoại: khách gõ gì -> chatbot trả lời/hiện nút gì -> cuối cùng trang booking nhận dữ liệu gì.
Câu hỏi đánh giá: "khách bình thường gõ thế này thì có đặt được tour không, có bị trả lời vô lý không?"

Nhóm:
  A_MoDau          câu mở đầu đa dạng (không có chữ "tour", teencode, viết hoa…)
  B_HoiGiuaLuong   khách hỏi câu khác khi đang đặt dở
  C_SoNguoi        cách nói số người của người Việt
  D_Ngay           cách nói ngày khởi hành
  E_DoiY           đổi ý, quay lại, huỷ rồi đặt lại, đặt 2 tour
  F_ThanNhan       chọn người đi cùng bằng tên
  G_DuLieuDoi      dữ liệu tour đổi giữa chừng, API lỗi, chống spam trong luồng

Test ĐỎ trong file này là lỗi thật của chatbot (đã tái hiện), cố ý giữ lại — không skip.
"""
import unittest
import copy
from datetime import date
from unittest import mock

import database
import dat_tour
from tests.helpers import GIA, NenTest, THAN_NHAN, THE_NGA, TOUR_1NGAY, TOUR_NHIEU, TOURS_LIVE, dmy, ngay, tim_tour_gia

NAM = date.today().year + 1  # mọi ngày bên dưới đều ở tương lai, tháng cố định để test câu "tháng 12", "ngày 20"…

# Tour nước ngoài 4 ngày khởi hành, tháng/giá/số chỗ khác nhau
TOUR_THAI = {
    "id": "T0", "name": "Du Lịch Thái Lan - Bangkok - Pattaya", "image": "https://x/tour/nuoc-ngoai/thai.webp",
    "tour_days": [
        {"id": "T1", "departure_date": f"{NAM}-11-20", "price": 10_000_000, "stock_qty": 5, "code": "TL01"},
        {"id": "T2", "departure_date": f"{NAM}-12-05", "price": 9_000_000, "stock_qty": 20, "code": "TL02"},
        {"id": "T3", "departure_date": f"{NAM}-12-28", "price": 12_000_000, "stock_qty": 8, "code": "TL03"},
        {"id": "T4", "departure_date": f"{NAM + 1}-01-15", "price": 11_000_000, "stock_qty": 2, "code": "TL04"},
    ],
}
# Tour có 12 ngày khởi hành (mỗi tháng 1 ngày)
TOUR_HAN = {
    "id": "K0", "name": "Du Lịch Hàn Quốc - Seoul", "image": "https://x/tour/nuoc-ngoai/han.webp",
    "tour_days": [
        {"id": f"K{m}", "departure_date": f"{NAM}-{m:02d}-10", "price": GIA, "stock_qty": 9, "code": f"HQ{m:02d}"}
        for m in range(1, 13)
    ],
}


def tien(v: float) -> str:
    return f"{int(round(v)):,}".replace(",", ".") + " đ"


class KichBan(NenTest):
    """NenTest + thêm tour Thái Lan / Hàn Quốc + cho phép đổi dữ liệu tour, làm API lỗi giữa chừng."""

    def setUp(self):
        super().setUp()
        self.live = copy.deepcopy(TOURS_LIVE)
        self.live["k-thai"] = copy.deepcopy(TOUR_THAI)
        self.live["k-han"] = copy.deepcopy(TOUR_HAN)
        self.api_tour_loi = False

        def _live(key):
            return None if self.api_tour_loi else copy.deepcopy(self.live.get(key))

        def _tim(cau):
            # hàm thật so khớp trên câu đã bỏ dấu câu (_chuan); helpers.tim_tour_gia thì không -> chuẩn hoá trước
            nd = dat_tour._chuan(cau)
            cau = nd
            if "thai lan" in nd:
                return [{"key": "k-thai", "ten": TOUR_THAI["name"]}]
            if "han quoc" in nd:
                return [{"key": "k-han", "ten": TOUR_HAN["name"]}]
            return [{"key": t["tour_key"], "ten": t["ten"]} for t in tim_tour_gia(cau)]

        for p in (mock.patch.object(dat_tour, "lay_tour_live", _live), mock.patch.object(dat_tour, "tim_tour_theo_cau", _tim)):
            p.start()
            self.addCleanup(p.stop)

    # ---- tiện ích
    def dang_o_buoc_xac_nhan(self, res: dict) -> bool:
        return "xn:dong_y" in self.ids(res)

    def chot(self) -> dict:
        """Khách bấm Đồng ý -> chatbot đặt tour luôn. Trả về nội dung đơn ĐÃ GỬI
        lên backend, quy về dạng phẳng cho dễ kiểm."""
        res = self.bam("xn:dong_y")
        self.assertIn("booking", res, f"Bấm Đồng ý mà chatbot không đặt tour: {res['reply']}")
        return self.don_phang()

    def so_khach(self, co: dict) -> tuple[int, int, int]:
        return co["adults"], co["children"], co["infants"]

    def go_so_nguoi(self, cau: str) -> dict:
        """Đặt tour Nga ngày N1 (còn 30 chỗ, 10tr), không có thân nhân, rồi gõ `cau` ở bước số người."""
        self.than_nhan = []
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        return self.gui(cau)

    def so_khach_da_hieu(self, cau: str) -> tuple[tuple[int, int, int] | None, dict]:
        """(người lớn, trẻ em, em bé) mà chatbot hiểu từ `cau`; None nếu chatbot hỏi lại."""
        res = self.go_so_nguoi(cau)
        if not self.dang_o_buoc_xac_nhan(res):
            return None, res
        return self.so_khach(self.chot()), res

    def thai_toi_chon_ngay(self) -> dict:
        res = self.gui("Tôi muốn đặt tour Thái Lan")
        self.assertEqual(self.ids(res), ["dot:T1", "dot:T2", "dot:T3", "dot:T4", "huy"], res["reply"])
        return res

    def ngay_da_chon(self) -> str | None:
        return self.trang_thai().get("dot", {}).get("key")


# ============================================================================ A
class A_MoDau(KichBan):
    def test_dat_cho_di_nga_khong_co_chu_tour(self):
        """Khách: 'đặt chỗ đi Nga' (không có chữ 'tour') -> phải vào luồng đặt, hiện ngày khởi hành."""
        res = self.gui("đặt chỗ đi Nga")
        self.co_nut(res, "dot:")
        self.gemini.assert_not_called()

    def test_dat_ve_di_da_lat_khong_co_chu_tour(self):
        """Khách: 'Đặt vé đi Đà Lạt giúp mình' -> phải vào luồng đặt tour Đà Lạt."""
        res = self.gui("Đặt vé đi Đà Lạt giúp mình")
        self.assertIn(TOUR_1NGAY["name"], res["reply"])
        self.co_nut(res, "sl:")

    def test_book_tour_nga_go_chu_tu_dau_toi_cuoi(self):
        """Khách không bấm nút nào, gõ hết bằng chữ: book tour Nga -> ngày sớm nhất -> 2 người lớn -> Lan -> đồng ý."""
        self.assertIn(TOUR_NHIEU["name"], self.gui("book tour Nga")["reply"])
        self.assertIn(dmy(ngay(20)), self.gui("ngày sớm nhất")["reply"])
        self.assertTrue(self.gui("2 người lớn").get("multi"))
        res = self.gui("Lan")
        self.assertIn("Trần Thị Lan", res["reply"])
        self.assertIn(tien(2 * GIA), res["reply"])
        res = self.gui("đồng ý")
        self.assertIn("booking", res)
        self.assertEqual(self.don_phang(), {
            "tour_key": "k-nga", "departure_key": "N1", "departure_date": ngay(20),
            "adults": 2, "children": 0, "infants": 0, "relative_ids": ["r-lan"],
        })
        self.gemini.assert_not_called()

    def test_cho_minh_dang_ky_tour_da_lat_di_mot_minh(self):
        """'cho mình đăng ký tour Đà Lạt' -> chốt ngày duy nhất -> 'mình đi 1 mình' -> ok."""
        res = self.gui("cho mình đăng ký tour Đà Lạt")
        self.assertIn("chỉ có một ngày khởi hành", res["reply"])
        res = self.gui("mình đi 1 mình")
        self.assertTrue(self.dang_o_buoc_xac_nhan(res), res["reply"])
        self.assertIn(tien(GIA), res["reply"])
        self.assertNotIn("hộ chiếu", res["reply"])
        res = self.gui("ok")
        self.assertIn("booking", res)
        self.assertEqual(self.don_phang(), {
            "tour_key": "k-dalat", "departure_key": "D1", "departure_date": ngay(30),
            "adults": 1, "children": 0, "infants": 0, "relative_ids": [],
        })

    def test_minh_lay_tour_nay_sau_khi_duoc_goi_y(self):
        """Chatbot vừa gợi ý 1 tour Nga, khách: 'mình lấy tour này' -> phải vào luồng đặt tour Nga."""
        self.tours_chat = [THE_NGA]
        self.gui("Có tour Nga không?")
        res = self.gui("mình lấy tour này")
        self.co_nut(res, "dot:")

    def test_ok_chot_tour_do_sau_khi_duoc_goi_y(self):
        self.tours_chat = [THE_NGA]
        self.gui("Có tour Nga không?")
        res = self.gui("ok chốt tour đó")
        self.assertIn(TOUR_NHIEU["name"], res["reply"])
        self.co_nut(res, "dot:")

    def test_giu_cho_giup_toi_sau_khi_duoc_goi_y(self):
        """Chatbot vừa gợi ý 1 tour, khách: 'giữ chỗ giúp tôi' -> phải vào luồng đặt tour đó."""
        self.tours_chat = [THE_NGA]
        self.gui("Có tour Nga không?")
        res = self.gui("giữ chỗ giúp tôi")
        self.co_nut(res, "dot:")

    def test_khong_dau_viet_hoa_teencode(self):
        for cau in ["TOI MUON DAT TOUR NGA", "TÔI MUỐN ĐẶT TOUR NGA!!!", "mik mún đặt tour nga nha shop", "dat tour nga di ad oi", "e mun book tour nga ạ"]:
            with self.subTest(cau=cau):
                self.setUp()
                res = self.gui(cau)
                self.assertIn(TOUR_NHIEU["name"], res["reply"])
                self.co_nut(res, "dot:")

    def test_mo_dau_noi_luon_so_nguoi_van_dat_duoc(self):
        """'Tôi muốn đặt tour Đà Lạt cho 2 người lớn 1 trẻ em' -> không bị hiểu sai, đi tiếp tới trang booking đúng 2+1."""
        res = self.gui("Tôi muốn đặt tour Đà Lạt cho 2 người lớn 1 trẻ em")
        self.assertIn(TOUR_1NGAY["name"], res["reply"])
        if not self.dang_o_buoc_xac_nhan(res) and not res.get("multi"):
            res = self.gui("2 người lớn 1 trẻ em")  # chatbot hỏi lại số người: chấp nhận được
        if res.get("multi"):
            res = self.bam("nguoi:skip")
        self.assertIn(tien(2 * GIA + 0.8 * GIA), res["reply"])
        self.assertEqual(self.so_khach(self.chot()), (2, 1, 0))

    def test_noi_ro_chua_muon_dat_chi_hoi_gia_thi_khong_mo_luong_dat(self):
        """'Mình chưa muốn đặt tour đâu, chỉ hỏi giá tour Nga thôi' -> trả lời câu hỏi, KHÔNG ép vào luồng đặt."""
        res = self.gui("Mình chưa muốn đặt tour đâu, chỉ hỏi giá tour Nga thôi")
        self.assertFalse(res.get("choices"), f"Khách chưa muốn đặt mà chatbot đã hỏi: {res['reply']}")
        self.assertFalse(self.trang_thai().get("step"))


# ============================================================================ B
class B_HoiGiuaLuong(KichBan):
    def test_hoi_bao_an_o_buoc_chon_ngay_phien_dat_van_con(self):
        """Đang chọn ngày, hỏi 'tour này có bao ăn không?' -> không mất phiên, vẫn còn nút ngày, chọn tiếp được."""
        self.gui("Tôi muốn đặt tour Nga")
        res = self.gui("tour này có bao ăn không?")
        self.assertIsNone(self.ngay_da_chon(), "Câu hỏi không được bị hiểu là chọn ngày")
        self.assertEqual(self.trang_thai().get("tour", {}).get("key"), "k-nga")
        res = self.bam("dot:N2")
        self.co_nut(res, "sl:")

    def test_hoi_bao_an_o_buoc_chon_ngay_phai_duoc_tra_loi(self):
        """Khách hỏi 'tour này có bao ăn không?' thì phải nhận được câu trả lời, không phải 'Mình chưa hiểu ngày bạn chọn'."""
        self.gui("Tôi muốn đặt tour Nga")
        res = self.gui("tour này có bao ăn không?")
        self.assertNotIn("chưa hiểu ngày", res["reply"])

    def test_hoi_gia_tre_em_o_buoc_so_nguoi_phai_duoc_tra_loi(self):
        """Đang ở bước số người, hỏi 'giá trẻ em bao nhiêu?' -> phải được biết giá trẻ em (80%) hoặc được AI trả lời."""
        self.gui("Tôi muốn đặt tour Đà Lạt")
        res = self.gui("giá trẻ em bao nhiêu?")
        self.assertNotIn("adults", self.trang_thai())
        self.assertTrue(self.gemini.called or "80" in res["reply"], f"Khách hỏi giá trẻ em mà chỉ nhận: {res['reply']}")

    def test_hoi_be_3_tuoi_co_tinh_tien_khong_khong_bi_hieu_la_3_nguoi(self):
        """Đang ở bước số người, hỏi 'bé 3 tuổi có tính tiền không?' -> KHÔNG được chốt thành 3 người lớn."""
        self.gui("Tôi muốn đặt tour Đà Lạt")
        res = self.gui("bé 3 tuổi có tính tiền không?")
        self.assertNotIn("adults", self.trang_thai(), f"Câu hỏi bị hiểu thành số khách: {res['reply']}")

    def test_hoi_tre_5_tuoi_tinh_gia_sao_khong_bi_hieu_la_5_nguoi(self):
        self.than_nhan = []
        self.gui("Tôi muốn đặt tour Đà Lạt")
        res = self.gui("trẻ em 5 tuổi thì tính giá sao bạn?")
        self.assertFalse(self.dang_o_buoc_xac_nhan(res), f"Câu hỏi bị chốt thành đơn: {res['reply']}")

    def test_hoi_con_may_cho_o_buoc_so_nguoi_roi_dat_tiep(self):
        """'còn mấy chỗ?' không bị hiểu là số người; sau đó khách trả lời '2 người' vẫn đi tiếp bình thường."""
        self.than_nhan = []
        self.gui("Tôi muốn đặt tour Đà Lạt")
        res = self.gui("còn mấy chỗ vậy bạn?")
        self.assertNotIn("adults", self.trang_thai())
        self.co_nut(res, "sl:")
        res = self.gui("2 người")
        self.assertTrue(self.dang_o_buoc_xac_nhan(res), res["reply"])
        self.assertEqual(self.so_khach(self.chot()), (2, 0, 0))

    def test_hoi_visa_o_buoc_xac_nhan_khong_bi_coi_la_khong_dong_y(self):
        """Ở bảng tóm tắt, hỏi 'visa có khó không?' -> không được trả lời 'Bạn muốn đổi phần nào ạ?'."""
        self.toi_buoc_xac_nhan()
        res = self.gui("visa có khó không?")
        self.assertNotIn("đổi phần nào", res["reply"])
        self.assertNotIn("doi:ngay", self.ids(res))

    def test_hoi_da_gom_ve_may_bay_chua_o_buoc_xac_nhan(self):
        """'giá này đã gồm vé máy bay chưa?' -> là câu hỏi, không phải 'không đồng ý'."""
        self.toi_buoc_xac_nhan()
        res = self.gui("giá này đã gồm vé máy bay chưa?")
        self.assertNotIn("đổi phần nào", res["reply"])

    def test_hoi_thanh_toan_bang_the_duoc_chu_khong_bi_coi_la_dong_y(self):
        """Ở bảng tóm tắt, hỏi 'thanh toán bằng thẻ được chứ?' -> KHÔNG được coi là Đồng ý và đặt tour."""
        self.toi_buoc_xac_nhan()
        res = self.gui("thanh toán bằng thẻ được chứ?")
        self.assertNotIn("booking", res, f"Khách mới hỏi mà chatbot đã đặt tour: {res['reply']}")

    def test_hoi_o_moi_buoc_roi_van_hoan_tat_dung_don(self):
        """Mỗi bước khách chen 1 câu hỏi, cuối cùng đơn vẫn đúng."""
        self.gui("Tôi muốn đặt tour Nga")
        self.gui("tour này đi hãng bay nào?")
        self.bam("dot:N2")
        self.gui("khách sạn mấy sao vậy?")
        self.bam("sl:2,1,0")
        self.gui("ờ để xem")
        res = self.bam("nguoi:ok", ["r-lan", "r-bi"])
        self.gui("hmm")
        self.assertEqual(self.chot(), {
            "tour_key": "k-nga", "departure_key": "N2", "departure_date": ngay(50),
            "adults": 2, "children": 1, "infants": 0, "relative_ids": ["r-lan", "r-bi"],
        })
        self.assertIn(tien(2.8 * GIA), res["reply"])

    def test_gap_nhan_vien_giua_luong_roi_quay_lai_dat_tiep(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        res = self.gui("cho tôi gặp nhân viên tư vấn")
        self.assertIn("handoff", res)
        res = self.gui("3 người lớn")  # quay lại trả lời câu đang dở
        self.assertTrue(res.get("multi"), res["reply"])
        self.bam("nguoi:skip")
        self.assertEqual(self.so_khach(self.chot()), (3, 0, 0))

    def test_muon_doi_lich_khoi_hanh_o_buoc_xac_nhan_khong_bi_day_sang_nhan_vien(self):
        """Ở bảng tóm tắt (CHƯA đặt), khách: 'cho mình đổi lịch khởi hành' -> cho chọn lại ngày, không chuyển Zalo nhân viên."""
        self.toi_buoc_xac_nhan()
        res = self.gui("cho mình đổi lịch khởi hành")
        self.assertNotIn("handoff", res, res["reply"])
        if "doi:ngay" in self.ids(res):
            res = self.bam("doi:ngay")
        self.co_nut(res, "dot:")


# ============================================================================ C
class C_SoNguoi(KichBan):
    def test_ba_toi_va_toi(self):
        """'Ba tôi và tôi' = 2 người (ba = bố). Không được hiểu thành 3 người lớn."""
        so, res = self.so_khach_da_hieu("Ba tôi và tôi")
        self.assertIn(so, (None, (2, 0, 0)), f"Hiểu sai thành {so}: {res['reply']}")

    def test_ba_ma_toi_di_noi_ro_2_nguoi(self):
        """'ba má tôi đi thôi, 2 người' -> khách nói rõ 2 người; chữ 'ba' (= bố) không được biến thành số 3."""
        so, res = self.so_khach_da_hieu("ba má tôi đi thôi, 2 người")
        self.assertEqual(so, (2, 0, 0), res["reply"])

    def test_vo_chong_toi_va_2_dua_con(self):
        """'vợ chồng tôi và 2 đứa con' = 2 người lớn + 2 trẻ em (hoặc hỏi lại). Không được thành 2 người lớn, mất 2 đứa nhỏ."""
        so, res = self.so_khach_da_hieu("vợ chồng tôi và 2 đứa con")
        self.assertIn(so, (None, (2, 2, 0)), f"Hiểu sai thành {so}: {res['reply']}")

    def test_2_vo_chong(self):
        so, res = self.so_khach_da_hieu("2 vợ chồng")
        self.assertEqual(so, (2, 0, 0), res["reply"])
        self.assertIn(tien(2 * GIA), res["reply"])

    def test_gia_dinh_4_nguoi(self):
        so, res = self.so_khach_da_hieu("gia đình 4 người")
        self.assertEqual(so, (4, 0, 0), res["reply"])
        self.assertIn(tien(4 * GIA), res["reply"])

    def test_toi_di_mot_minh(self):
        self.than_nhan = THAN_NHAN
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        res = self.gui("tôi đi một mình")
        self.assertTrue(self.dang_o_buoc_xac_nhan(res), "Đi một mình thì không hỏi người đi cùng")
        self.assertEqual(self.chot()["relative_ids"], [])

    def test_ca_nha_5_nguoi_trong_do_2_be(self):
        """'cả nhà 5 người trong đó 2 bé 3 tuổi và 7 tuổi' -> tổng 5 khách: 3 người lớn + 2 bé."""
        so, res = self.so_khach_da_hieu("cả nhà 5 người trong đó 2 bé 3 tuổi và 7 tuổi")
        self.assertIsNotNone(so, res["reply"])
        self.assertEqual(sum(so), 5, res["reply"])
        self.assertEqual(so[0], 3, res["reply"])

    def test_2_lon_1_nho(self):
        """'2 lớn 1 nhỏ' = 2 người lớn + 1 trẻ em (hoặc hỏi lại). Không được bỏ mất đứa nhỏ."""
        so, res = self.so_khach_da_hieu("2 lớn 1 nhỏ")
        self.assertIn(so, (None, (2, 1, 0)), f"Hiểu sai thành {so}: {res['reply']}")

    def test_viet_tat_2nl_1te(self):
        """'2 NL 1 TE' (cách viết tắt quen thuộc trong ngành du lịch) -> 2 người lớn 1 trẻ em hoặc hỏi lại."""
        so, res = self.so_khach_da_hieu("2 NL 1 TE")
        self.assertIn(so, (None, (2, 1, 0)), f"Hiểu sai thành {so}: {res['reply']}")

    def test_hai_nguoi_lon_mot_em_be(self):
        so, res = self.so_khach_da_hieu("hai người lớn, một em bé")
        self.assertEqual(so, (2, 0, 1), res["reply"])
        self.assertIn(tien(2 * GIA + 0.4 * GIA), res["reply"])
        self.assertIn("2 người lớn, 1 em bé", res["reply"])

    def test_teencode_2ng_lon_1_tre_em(self):
        so, res = self.so_khach_da_hieu("2ng lon 1 tre em")
        self.assertEqual(so, (2, 1, 0), res["reply"])
        self.assertIn(tien(2.8 * GIA), res["reply"])

    def test_khong_dau_5_nguoi(self):
        so, res = self.so_khach_da_hieu("5 nguoi")
        self.assertEqual(so, (5, 0, 0), res["reply"])

    def test_2_nguoi_lon_va_be_5_tuoi(self):
        """'2 người lớn và bé 5 tuổi' -> 2 người lớn + 1 trẻ (hoặc hỏi lại). Không được lặng lẽ bỏ mất em bé."""
        so, res = self.so_khach_da_hieu("2 người lớn và bé 5 tuổi")
        self.assertIn(so, (None, (2, 1, 0)), f"Hiểu sai thành {so}: {res['reply']}")

    def test_so_qua_lon_roi_sua_lai(self):
        res = self.go_so_nguoi("đoàn công ty 100 người")
        self.assertIn("20", res["reply"])
        self.assertIn("nhân viên", res["reply"])
        self.co_nut(res, "sl:")
        res = self.gui("vậy 20 người lớn")
        self.assertTrue(self.dang_o_buoc_xac_nhan(res), res["reply"])
        self.assertIn(tien(20 * GIA), res["reply"])

    def test_so_0(self):
        res = self.go_so_nguoi("0 người")
        self.assertFalse(self.dang_o_buoc_xac_nhan(res))
        self.co_nut(res, "sl:")
        self.assertNotIn("adults", self.trang_thai())

    def test_so_thap_phan(self):
        """'2.5 người' là vô nghĩa -> hỏi lại, không tự chốt 2 người."""
        res = self.go_so_nguoi("2.5 người")
        self.assertFalse(self.dang_o_buoc_xac_nhan(res), f"Tự chốt đơn từ câu '2.5 người': {res['reply']}")

    def test_de_hoi_ba_xa_roi_bao_sau_khong_bi_hieu_la_6_nguoi(self):
        """'để mình hỏi bà xã rồi báo sau' -> chữ 'sau' không phải số 6."""
        res = self.go_so_nguoi("để mình hỏi bà xã rồi báo sau")
        self.assertFalse(self.dang_o_buoc_xac_nhan(res), f"Bị chốt thành đơn: {res['reply']}")
        self.assertNotIn("adults", self.trang_thai())

    def test_so_nguoi_vuot_cho_roi_giam_xuong(self):
        """Ngày chỉ còn 3 chỗ, khách khai 4 -> báo thiếu chỗ; khai lại 3 -> được."""
        self.than_nhan = []
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N3")
        res = self.gui("4 người lớn")
        self.assertIn("3 chỗ", res["reply"])
        res = self.gui("vậy 2 người lớn 1 trẻ em")
        self.assertIn(tien(2.8 * (GIA + 2_000_000)), res["reply"])
        co = self.chot()
        self.assertEqual((co["departure_key"], self.so_khach(co)), ("N3", (2, 1, 0)))


# ============================================================================ D
class D_Ngay(KichBan):
    def test_ngay_20_thang_11_va_20_11(self):
        for cau in ["ngày 20 tháng 11", "20/11", "mình đi 20-11 nha", f"20/11/{NAM}", "ngay 20 thang 11"]:
            with self.subTest(cau=cau):
                self.setUp()
                self.thai_toi_chon_ngay()
                res = self.gui(cau)
                self.assertEqual(self.ngay_da_chon(), "T1", res["reply"])
                self.assertIn(f"20/11/{NAM}", res["reply"])

    def test_cuoi_thang_12(self):
        """'cuối tháng 12' -> ngày 28/12, KHÔNG phải ngày cuối cùng của cả danh sách (15/01 năm sau)."""
        self.thai_toi_chon_ngay()
        res = self.gui("mình đi cuối tháng 12")
        self.assertIn(self.ngay_da_chon(), (None, "T3"), f"Chốt nhầm ngày: {res['reply']}")

    def test_cuoi_tuan_khong_bi_chot_ngay_cuoi_danh_sach(self):
        """'có ngày nào đi cuối tuần không?' là câu hỏi -> không được tự chốt ngày cuối danh sách."""
        self.thai_toi_chon_ngay()
        res = self.gui("có ngày nào đi cuối tuần không?")
        self.assertIsNone(self.ngay_da_chon(), f"Tự chốt ngày: {res['reply']}")

    def test_ngay_som_nhat(self):
        self.thai_toi_chon_ngay()
        res = self.gui("cho mình ngày sớm nhất")
        self.assertEqual(self.ngay_da_chon(), "T1")
        self.assertIn("10.000.000 đ", res["reply"])

    def test_ngay_nao_re_nhat(self):
        """'ngày nào rẻ nhất?' -> chọn/chỉ ra ngày 05/12 (9tr), hoặc ít nhất hiện lại danh sách CÓ GIÁ để khách tự so."""
        self.thai_toi_chon_ngay()
        res = self.gui("ngày nào rẻ nhất?")
        self.assertIn(self.ngay_da_chon(), (None, "T2"), res["reply"])
        if self.ngay_da_chon() is None:
            nhan = " ".join(c["label"] for c in res.get("choices", []))
            self.assertIn("9.000.000", res["reply"] + nhan, f"Hỏi ngày rẻ nhất mà không thấy giá nào: {res['reply']} | {nhan}")

    def test_ngay_nao_con_nhieu_cho_nhat(self):
        """'ngày nào còn nhiều chỗ nhất?' -> chọn 05/12 (20 chỗ) hoặc hiện lại danh sách có số chỗ; không chốt bừa."""
        self.thai_toi_chon_ngay()
        res = self.gui("ngày nào còn nhiều chỗ nhất?")
        self.assertIn(self.ngay_da_chon(), (None, "T2"), res["reply"])
        if self.ngay_da_chon() is None:
            self.assertIn("còn 20 chỗ", " ".join(c["label"] for c in res["choices"]))

    def test_thang_sau_khong_chot_bua(self):
        self.thai_toi_chon_ngay()
        res = self.gui("tháng sau có đi không?")
        self.assertIsNone(self.ngay_da_chon(), res["reply"])
        self.co_nut(res, "dot:")

    def test_ngay_khong_ton_tai(self):
        for cau in ["30/02", "25/12", "ngày 32 tháng 13", "ngày 1 tháng 1"]:
            with self.subTest(cau=cau):
                self.setUp()
                self.thai_toi_chon_ngay()
                res = self.gui(cau)
                self.assertIsNone(self.ngay_da_chon(), res["reply"])
                self.assertEqual(self.ids(res), ["dot:T1", "dot:T2", "dot:T3", "dot:T4", "huy"])

    def test_chi_noi_ngay_20(self):
        """Chỉ có đúng 1 đợt rơi vào ngày 20 -> 'mình đi ngày 20' phải chọn được 20/11."""
        self.thai_toi_chon_ngay()
        res = self.gui("mình đi ngày 20")
        self.assertEqual(self.ngay_da_chon(), "T1", res["reply"])

    def test_chi_noi_thang_1(self):
        """Chỉ có đúng 1 đợt trong tháng 1 -> 'mình đi tháng 1' phải chọn được 15/01."""
        self.thai_toi_chon_ngay()
        res = self.gui("mình đi tháng 1")
        self.assertEqual(self.ngay_da_chon(), "T4", res["reply"])

    def test_tour_12_ngay_khoi_hanh_phai_chon_duoc_moi_ngay(self):
        """Chatbot nói 'có 12 ngày khởi hành' thì khách phải thấy đủ 12 ngày (nút hoặc chữ), không chỉ 8."""
        res = self.gui("Tôi muốn đặt tour Hàn Quốc")
        self.assertIn("12 ngày khởi hành", res["reply"])
        thay = res["reply"] + " ".join(c["label"] for c in res["choices"])
        thieu = [f"10/{m:02d}/{NAM}" for m in range(1, 13) if f"10/{m:02d}/{NAM}" not in thay]
        self.assertEqual(thieu, [], "Các ngày khách không nhìn thấy")

    def test_tour_12_ngay_go_ngay_khong_co_tren_nut_van_chon_duoc(self):
        self.gui("Tôi muốn đặt tour Hàn Quốc")
        res = self.gui("10/11")
        self.assertEqual(self.ngay_da_chon(), "K11", res["reply"])


# ============================================================================ E
class E_DoiY(KichBan):
    def test_doi_tour_khi_da_toi_buoc_xac_nhan(self):
        """Đã tới bảng tóm tắt tour Nga (3 khách, có thân nhân) -> 'à thôi mình muốn đặt tour Đà Lạt cơ' -> đơn mới sạch."""
        self.toi_buoc_xac_nhan(sl="sl:2,1,0", chon=("r-an", "r-bi"))
        res = self.gui("à mình muốn đặt tour Đà Lạt cơ")
        self.assertIn(TOUR_1NGAY["name"], res["reply"])
        self.co_nut(res, "sl:")
        res = self.bam("sl:1,0,0")
        self.assertIn(tien(GIA), res["reply"])
        self.assertNotIn("Nguyễn Văn An", res["reply"])
        self.assertEqual(self.chot(), {
            "tour_key": "k-dalat", "departure_key": "D1", "departure_date": ngay(30),
            "adults": 1, "children": 0, "infants": 0, "relative_ids": [],
        })

    def test_doi_sang_tour_khac_khong_co_chu_dat(self):
        """Ở bảng tóm tắt tour Nga, khách: 'đổi sang tour Đà Lạt' -> phải chuyển sang tour Đà Lạt."""
        self.toi_buoc_xac_nhan()
        res = self.gui("đổi sang tour Đà Lạt")
        self.assertIn(TOUR_1NGAY["name"], res["reply"], "Khách muốn đổi tour nhưng chatbot chỉ cho đổi ngày/số người")

    def test_doi_ngay_roi_doi_so_nguoi_roi_lai_doi_ngay(self):
        """Chuỗi đổi ý dài, sau mỗi lần bảng tóm tắt + đơn gửi đi phải khớp lựa chọn cuối."""
        gia_n3 = GIA + 2_000_000
        res = self.toi_buoc_xac_nhan(sl="sl:2,0,0", chon=("r-an",))
        self.assertIn(tien(2 * GIA), res["reply"])
        # đổi ngày N1 -> N3 (12tr, còn 3 chỗ)
        self.bam("xn:khong")
        self.bam("doi:ngay")
        res = self.bam("dot:N3")
        self.assertIn(tien(2 * gia_n3), res["reply"])
        self.assertIn("Nguyễn Văn An", res["reply"])
        # đổi số người 2 -> 2 lớn 1 trẻ (đủ 3 chỗ)
        self.bam("xn:khong")
        self.bam("doi:so_nguoi")
        res = self.gui("2 người lớn 1 trẻ em")
        self.assertTrue(res.get("multi"), res["reply"])
        res = self.bam("nguoi:ok", ["r-lan", "r-bi"])
        self.assertIn(tien(2.8 * gia_n3), res["reply"])
        # lại đổi ngày N3 -> N2 (10tr)
        self.gui("không")
        self.gui("đổi ngày khởi hành")
        res = self.gui(dmy(ngay(50)))
        self.assertIn(tien(2.8 * GIA), res["reply"])
        self.assertIn(dmy(ngay(50)), res["reply"])
        self.assertIn("NGA02", res["reply"])
        self.assertEqual(self.chot(), {
            "tour_key": "k-nga", "departure_key": "N2", "departure_date": ngay(50),
            "adults": 2, "children": 1, "infants": 0, "relative_ids": ["r-lan", "r-bi"],
        })

    def test_doi_ngay_sang_ngay_thieu_cho_roi_giam_nguoi(self):
        """4 khách đổi sang ngày còn 3 chỗ -> báo thiếu, khách giảm còn 3 -> đơn đúng ngày mới, không còn người cũ."""
        self.toi_buoc_xac_nhan(sl="sl:4,0,0", chon=("r-an", "r-lan"))
        self.bam("xn:khong")
        self.bam("doi:ngay")
        res = self.bam("dot:N3")
        self.assertIn("không đủ cho 4 khách", res["reply"])
        self.bam("sl:3,0,0")
        res = self.bam("nguoi:ok", ["r-lan"])
        self.assertIn(tien(3 * (GIA + 2_000_000)), res["reply"])
        self.assertIn("còn 1 người bạn nhập ở trang booking", res["reply"])
        self.assertEqual(self.chot(), {
            "tour_key": "k-nga", "departure_key": "N3", "departure_date": ngay(90),
            "adults": 3, "children": 0, "infants": 0, "relative_ids": ["r-lan"],
        })

    def test_giam_so_nguoi_thi_khong_con_giu_than_nhan_cu(self):
        """3 khách + 2 thân nhân, đổi còn 1 khách -> trang booking không được nhận 2 thân nhân cũ."""
        self.toi_buoc_xac_nhan(sl="sl:3,0,0", chon=("r-an", "r-lan"))
        self.bam("xn:khong")
        self.bam("doi:so_nguoi")
        res = self.bam("sl:1,0,0")
        self.assertNotIn("Người đi cùng", res["reply"])
        co = self.chot()
        self.assertEqual((self.so_khach(co), co["relative_ids"]), ((1, 0, 0), []))

    def test_quay_lai_o_buoc_so_nguoi(self):
        """Đã chọn ngày, tới bước số người, khách: 'quay lại' -> được chọn lại ngày."""
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        res = self.gui("quay lại")
        self.co_nut(res, "dot:")

    def test_lam_lai_tu_dau_o_buoc_xac_nhan(self):
        """Ở bảng tóm tắt, khách: 'làm lại từ đầu' -> phải cho làm lại (chọn tour/ngày) hoặc hỏi đổi gì, không lặp 'bấm Đồng ý/Không đồng ý'."""
        res0 = self.toi_buoc_xac_nhan()
        res = self.gui("làm lại từ đầu")
        self.assertNotEqual(self.ids(res), self.ids(res0), f"Chatbot không hiểu 'làm lại từ đầu': {res['reply']}")

    def test_thoi_khong_di_nua_la_huy(self):
        """Đang ở bước số người, khách: 'thôi mình không đi nữa' -> huỷ, không hỏi lại số người."""
        self.gui("Tôi muốn đặt tour Đà Lạt")
        res = self.gui("thôi mình không đi nữa")
        self.assertIn("đã huỷ", res["reply"])

    def test_huy_roi_dat_lai_tour_khac_don_moi_sach(self):
        self.toi_buoc_xac_nhan(sl="sl:3,1,0", chon=("r-an", "r-lan"))
        self.assertIn("đã huỷ", self.gui("huỷ đi bạn")["reply"])
        self.assertIn("hết hạn", self.bam("xn:dong_y")["reply"])  # nút cũ không còn tác dụng
        res = self.gui("Tôi muốn đặt tour Đà Lạt")
        self.co_nut(res, "sl:")
        st = self.trang_thai()
        self.assertNotIn("adults", st)
        self.assertNotIn("relative_ids", st)
        self.bam("sl:2,0,0")
        self.bam("nguoi:skip")
        self.assertEqual(self.chot(), {
            "tour_key": "k-dalat", "departure_key": "D1", "departure_date": ngay(30),
            "adults": 2, "children": 0, "infants": 0, "relative_ids": [],
        })

    def test_huy_roi_dat_lai_dung_tour_do(self):
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N3")
        self.gui("huỷ")
        res = self.gui("mình đặt lại tour Nga nhé")
        self.assertEqual(self.ids(res), ["dot:N1", "dot:N2", "dot:N3", "huy"])
        self.assertIsNone(self.ngay_da_chon())

    def test_dat_2_tour_lien_tiep(self):
        """Đặt xong tour Nga (có thân nhân) rồi đặt luôn tour Đà Lạt -> đơn 2 không dính dữ liệu đơn 1."""
        self.toi_buoc_xac_nhan(sl="sl:2,1,0", chon=("r-an", "r-bi"))
        co1 = self.chot()
        self.assertEqual((co1["tour_key"], co1["relative_ids"]), ("k-nga", ["r-an", "r-bi"]))
        res = self.gui("Tôi muốn đặt thêm tour Đà Lạt nữa")
        self.assertIn(TOUR_1NGAY["name"], res["reply"])
        res = self.bam("sl:2,0,0")
        self.assertTrue(res.get("multi"))
        res = self.bam("nguoi:ok", ["r-lan"])
        self.assertNotIn("Nguyễn Văn An", res["reply"])
        self.assertEqual(self.chot(), {
            "tour_key": "k-dalat", "departure_key": "D1", "departure_date": ngay(30),
            "adults": 2, "children": 0, "infants": 0, "relative_ids": ["r-lan"],
        })

    def test_dong_y_xong_hoi_sao_chua_thay_don(self):
        """Sau khi Đồng ý, khách hỏi 'sao chưa thấy đơn?' -> được trả lời (AI/nhân viên), không đặt lại đơn, không lỗi."""
        self.toi_buoc_xac_nhan()
        self.chot()
        res = self.gui("sao mình chưa thấy đơn trong lịch sử?")
        self.assertNotIn("booking", res)
        self.assertTrue(res["reply"])
        self.assertTrue(self.gemini.called or "handoff" in res)
        self.assertFalse(res.get("choices"))

    def test_ok_chot_tour_nay_o_buoc_xac_nhan_la_dong_y(self):
        """Đi từ gợi ý tour -> đặt -> tới bảng tóm tắt, khách: 'ok chốt tour này' -> là ĐỒNG Ý, không bắt chọn lại ngày từ đầu."""
        self.tours_chat = [THE_NGA]
        self.gui("Có tour Nga không?")
        self.gui("Tôi muốn đặt tour này")
        self.bam("dot:N2")
        self.bam("sl:2,0,0")
        self.bam("nguoi:ok", ["r-an"])
        res = self.gui("ok chốt tour này")
        self.assertIn("booking", res, f"Khách đồng ý mà bị đưa về: {res['reply']}")
        self.assertEqual(self.don_da_gui()["dot"]["key"], "N2")

    def test_dat_tour_nay_cho_3_nguoi_o_buoc_so_nguoi_khong_mat_ngay_da_chon(self):
        """Đi từ gợi ý tour, đã chọn ngày N2, tới bước số người khách gõ 'đặt tour này cho 3 người lớn' -> giữ ngày N2, nhận 3 người."""
        self.than_nhan = []
        self.tours_chat = [THE_NGA]
        self.gui("Có tour Nga không?")
        self.gui("Tôi muốn đặt tour này")
        self.bam("dot:N2")
        res = self.gui("đặt tour này cho 3 người lớn")
        self.assertEqual(self.ngay_da_chon(), "N2", f"Mất ngày đã chọn, chatbot hỏi lại: {res['reply']}")
        self.assertEqual(self.so_khach(self.chot()), (3, 0, 0))

    def test_khong_doi_nua_giu_nguyen(self):
        """Bấm 'Không đồng ý' rồi nghĩ lại: 'không đổi nữa, giữ nguyên' -> quay về bảng tóm tắt/Đồng ý, không hỏi mãi 'đổi phần nào'."""
        self.toi_buoc_xac_nhan()
        self.bam("xn:khong")
        res = self.gui("không đổi nữa, giữ nguyên")
        self.assertNotIn("đổi phần nào", res["reply"])

    def test_khong_dong_y_roi_nghi_lai_dong_y(self):
        self.toi_buoc_xac_nhan(sl="sl:2,0,0", chon=("r-lan",))
        self.bam("xn:khong")
        res = self.gui("thôi giữ nguyên, đồng ý")
        self.assertIn("booking", res)
        self.assertEqual(self.don_phang(), {
            "tour_key": "k-nga", "departure_key": "N1", "departure_date": ngay(20),
            "adults": 2, "children": 0, "infants": 0, "relative_ids": ["r-lan"],
        })


# ============================================================================ F
class F_ThanNhan(KichBan):
    def toi_buoc_chon_nguoi(self, sl="sl:3,0,0") -> dict:
        self.gui("Tôi muốn đặt tour Đà Lạt")
        res = self.bam(sl)
        self.assertTrue(res.get("multi"), res["reply"])
        return res

    def test_goi_ten_tat_an_va_lan(self):
        self.toi_buoc_chon_nguoi()
        res = self.gui("An và Lan")
        self.assertIn("Nguyễn Văn An, Trần Thị Lan", res["reply"])
        self.assertEqual(self.chot()["relative_ids"], ["r-an", "r-lan"])

    def test_ten_khong_dau_va_ca_ho_ten(self):
        for cau, mong in [("nguyen van an", ["r-an"]), ("an voi lan", ["r-an", "r-lan"]), ("TRAN THI LAN", ["r-lan"]), ("bé bảo với chị lan", ["r-lan", "r-bi"])]:
            with self.subTest(cau=cau):
                self.setUp()
                self.toi_buoc_chon_nguoi()
                self.gui(cau)
                self.assertEqual(self.chot()["relative_ids"], mong)

    def test_di_voi_lan_thoi(self):
        """'đi với Lan thôi' = chỉ chọn Lan. Không được hiểu chữ 'thôi' là bỏ qua, để trống người đi cùng."""
        self.toi_buoc_chon_nguoi()
        res = self.gui("đi với Lan thôi")
        self.assertIn("Trần Thị Lan", res["reply"])
        self.assertEqual(self.chot()["relative_ids"], ["r-lan"])

    @unittest.skip("Bước thân nhân của chatbot đang tắt (dat_tour.DUNG_THAN_NHAN = False); bỏ skip khi bật lại")
    def test_ten_trung_nhau_phai_hoi_lai(self):
        """Có 2 thân nhân tên An, còn 1 chỗ, khách gõ 'An' -> phải hỏi lại An nào, không tự chọn người đầu tiên."""
        self.than_nhan = THAN_NHAN + [{"id": "r-an2", "fullName": "Trần Hoài An", "dateOfBirth": "2001-03-03"}]
        self.toi_buoc_chon_nguoi("sl:2,0,0")
        res = self.gui("An")
        self.assertFalse(self.dang_o_buoc_xac_nhan(res), f"Tự chọn 1 trong 2 người tên An: {res['reply']}")

    @unittest.skip("Bước thân nhân của chatbot đang tắt (dat_tour.DUNG_THAN_NHAN = False); bỏ skip khi bật lại")
    def test_ten_trung_nhau_khong_chon_ca_hai(self):
        """Đoàn 3 khách, khách gõ 'mình đi với An' (1 người) -> không được tự thêm cả 2 người tên An."""
        self.than_nhan = THAN_NHAN + [{"id": "r-an2", "fullName": "Trần Hoài An", "dateOfBirth": "2001-03-03"}]
        self.toi_buoc_chon_nguoi("sl:3,0,0")
        res = self.gui("mình đi với An")
        if self.dang_o_buoc_xac_nhan(res):
            self.assertLessEqual(len(self.chot()["relative_ids"]), 1, res["reply"])

    @unittest.skip("Bước thân nhân của chatbot đang tắt (dat_tour.DUNG_THAN_NHAN = False); bỏ skip khi bật lại")
    def test_xung_ho_anh_chi_khong_bi_bat_nham_nguoi_ten_anh_chi(self):
        """Có thân nhân 'Lê Tuấn Anh' và 'Phạm Linh Chi'. Khách gõ 'anh An với chị Lan' -> chỉ An và Lan."""
        self.than_nhan = [
            {"id": "r-tanh", "fullName": "Lê Tuấn Anh", "dateOfBirth": "1988-02-02"},
            {"id": "r-chi", "fullName": "Phạm Linh Chi", "dateOfBirth": "1995-09-09"},
        ] + THAN_NHAN
        self.toi_buoc_chon_nguoi("sl:3,0,0")
        res = self.gui("anh An với chị Lan")
        self.assertEqual(sorted(self.chot()["relative_ids"]), ["r-an", "r-lan"], res["reply"])

    def test_go_nhieu_ten_hon_so_cho(self):
        """Đoàn 2 khách (còn 1 người đi cùng) mà gõ 3 tên -> trang booking không nhận quá 1 thân nhân."""
        self.toi_buoc_chon_nguoi("sl:2,0,0")
        res = self.gui("An, Lan và Bảo")
        if self.dang_o_buoc_xac_nhan(res):
            self.assertLessEqual(len(self.chot()["relative_ids"]), 1)
        else:
            self.co_nut(res, "nguoi:")

    @unittest.skip("Bước thân nhân của chatbot đang tắt (dat_tour.DUNG_THAN_NHAN = False); bỏ skip khi bật lại")
    def test_khai_2_nguoi_lon_nhung_chon_be_7_tuoi(self):
        """Khai 2 NGƯỜI LỚN nhưng chọn bé Gia Bảo (trẻ em) đi cùng -> phải nhắc lệch loại khách, không lặng lẽ tính giá người lớn."""
        self.toi_buoc_chon_nguoi("sl:2,0,0")
        res = self.bam("nguoi:ok", ["r-bi"])
        co_canh_bao = (not self.dang_o_buoc_xac_nhan(res)) or "tuổi" in res["reply"] or "trẻ em," in res["reply"]
        self.assertTrue(co_canh_bao, f"Không nhắc gì việc bé Bảo là trẻ em trong đơn 2 người lớn: {res['reply']}")

    @unittest.skip("Bước thân nhân của chatbot đang tắt (dat_tour.DUNG_THAN_NHAN = False); bỏ skip khi bật lại")
    def test_khai_1_lon_1_tre_em_nhung_chon_nguoi_lon(self):
        """Khai 1 người lớn + 1 trẻ em nhưng chọn anh An (người lớn) -> phải nhắc lệch loại khách."""
        self.toi_buoc_chon_nguoi("sl:1,1,0")
        res = self.bam("nguoi:ok", ["r-an"])
        co_canh_bao = (not self.dang_o_buoc_xac_nhan(res)) or "tuổi" in res["reply"]
        self.assertTrue(co_canh_bao, f"Không nhắc gì việc An là người lớn trong suất trẻ em: {res['reply']}")

    def test_danh_sach_20_than_nhan(self):
        """Tài khoản có đủ 20 thân nhân -> hiện đủ 20 nút + 'Nhập sau', chọn người thứ 20 được."""
        self.than_nhan = [{"id": f"r{i}", "fullName": f"Nguyễn Văn Khách{i:02d}", "dateOfBirth": f"19{70 + i}-01-01"} for i in range(1, 21)]
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        res = self.bam("sl:4,0,0")
        self.assertEqual(self.ids(res), [f"nguoi:r{i}" for i in range(1, 21)] + ["nguoi:skip", "huy"])
        self.assertEqual(res["toi_da"], 3)
        res = self.bam("nguoi:ok", ["r1", "r20", "r7"])
        self.assertIn("Khách20", res["reply"])
        self.assertEqual(self.chot()["relative_ids"], ["r1", "r20", "r7"])

    def test_ngay_sinh_dang_iso_co_gio_cua_nestjs(self):
        """NestJS trả ngày sinh kiểu '1990-05-01T00:00:00.000Z' -> vẫn hiện tuổi, không lỗi."""
        self.than_nhan = [{"id": "r-an", "fullName": "Nguyễn Văn An", "dateOfBirth": "1990-05-01T00:00:00.000Z"}]
        res = self.toi_buoc_chon_nguoi("sl:2,0,0")
        self.assertIn("tuổi", res["choices"][0]["label"])
        self.bam("nguoi:ok", ["r-an"])
        self.assertEqual(self.chot()["relative_ids"], ["r-an"])

    def test_than_nhan_thieu_ngay_sinh_khong_lam_hong_luong_dat(self):
        """Một thân nhân cũ chưa có ngày sinh (null) -> vẫn hiện danh sách, không báo 'bị lạc bước'."""
        self.than_nhan = [{"id": "r-x", "fullName": "Nguyễn Văn Cũ", "dateOfBirth": None}] + THAN_NHAN
        self.gui("Tôi muốn đặt tour Đà Lạt")
        res = self.bam("sl:2,0,0")
        self.assertNotIn("lạc bước", res["reply"])
        self.co_nut(res, "nguoi:r-x")

    def test_doi_nguoi_di_cung_bang_ten(self):
        self.toi_buoc_xac_nhan(sl="sl:2,0,0", chon=("r-an",))
        self.gui("chưa đúng")
        res = self.gui("đổi người đi cùng")
        self.assertTrue(res.get("multi"), res["reply"])
        res = self.gui("Trần Thị Lan")
        self.assertIn("Trần Thị Lan", res["reply"])
        self.assertNotIn("Nguyễn Văn An", res["reply"])
        self.assertEqual(self.chot()["relative_ids"], ["r-lan"])


# ============================================================================ G
class G_DuLieuDoi(KichBan):
    def test_ngay_da_chon_het_cho_truoc_khi_dong_y(self):
        """Khách dừng ở bảng tóm tắt, trong lúc đó ngày N1 bán hết. Bấm Đồng ý -> phải báo hết chỗ, không đưa sang trang booking ngày đã hết."""
        self.toi_buoc_xac_nhan()
        for d in self.live["k-nga"]["tour_days"]:
            if d["id"] == "N1":
                d["stock_qty"] = 0
        res = self.bam("xn:dong_y")
        self.assertNotIn("booking", res, "Vẫn đặt tour cho ngày đã hết chỗ")

    def test_ngay_da_chon_bi_go_truoc_khi_dong_y(self):
        """Ngày N1 bị công ty gỡ khỏi tour khi khách đang ở bảng tóm tắt -> không được mở trang booking với ngày không còn tồn tại."""
        self.toi_buoc_xac_nhan()
        self.live["k-nga"]["tour_days"] = [d for d in self.live["k-nga"]["tour_days"] if d["id"] != "N1"]
        res = self.bam("xn:dong_y")
        self.assertNotIn("booking", res, "Vẫn đặt tour cho ngày đã bị gỡ")

    def test_gia_doi_truoc_khi_dong_y(self):
        """Giá ngày N1 tăng 10tr -> 15tr khi khách đang xem tóm tắt. Bấm Đồng ý -> phải báo giá mới (hoặc tóm tắt lại), không im lặng."""
        res = self.toi_buoc_xac_nhan(sl="sl:2,0,0", chon=())
        self.assertIn(tien(2 * GIA), res["reply"])
        for d in self.live["k-nga"]["tour_days"]:
            if d["id"] == "N1":
                d["price"] = 15_000_000
        res = self.bam("xn:dong_y")
        self.assertTrue("booking" not in res or "30.000.000" in res["reply"], "Giá đã đổi nhưng khách vẫn được chốt với tổng tiền cũ, không có thông báo")

    def test_api_tour_loi_khi_dat_tour_nay_thu_lai_van_duoc(self):
        """Gợi ý tour Nga -> 'đặt tour này' đúng lúc API tour lỗi -> khách thử lại 'đặt tour này' khi API đã ổn -> phải vào được tour Nga."""
        self.tours_chat = [THE_NGA]
        self.gui("Có tour Nga không?")
        self.api_tour_loi = True
        self.assertIn("chưa lấy được", self.gui("Tôi muốn đặt tour này")["reply"])
        self.api_tour_loi = False
        res = self.gui("Tôi muốn đặt tour này")
        self.co_nut(res, "dot:")

    def test_api_tour_loi_khi_doi_tour_giua_chung(self):
        """Đang đặt tour Nga, đổi sang Đà Lạt lúc API lỗi -> báo thử lại; thử lại thì đặt được Đà Lạt."""
        self.toi_buoc_xac_nhan()
        self.api_tour_loi = True
        res = self.gui("mình muốn đặt tour Đà Lạt")
        self.assertIn("chưa lấy được", res["reply"])
        self.assertNotIn("booking", res)
        self.api_tour_loi = False
        res = self.gui("mình muốn đặt tour Đà Lạt")
        self.co_nut(res, "sl:")
        self.bam("sl:1,0,0")
        self.assertEqual(self.chot()["tour_key"], "k-dalat")

    def test_api_than_nhan_loi_khi_doi_nguoi_di_cung(self):
        """Đã chọn An, bấm 'Đổi người đi cùng' lúc NestJS lỗi -> báo rõ, đơn vẫn chốt được (nhập ở trang booking)."""
        self.toi_buoc_xac_nhan(sl="sl:2,0,0", chon=("r-an",))
        self.bam("xn:khong")
        self.than_nhan = None
        res = self.bam("doi:nguoi")
        self.assertIn("chưa lấy được danh sách thân nhân", res["reply"])
        self.assertTrue(self.dang_o_buoc_xac_nhan(res))
        co = self.chot()
        self.assertEqual((self.so_khach(co), co["relative_ids"]), ((2, 0, 0), []))

    def test_tour_het_cho_roi_dat_tour_khac(self):
        res = self.gui("Tôi muốn đặt tour Huế")
        self.assertIn("chưa có ngày khởi hành còn chỗ", res["reply"])
        res = self.gui("vậy đặt tour Đà Lạt")
        self.co_nut(res, "sl:")


class G_ChongSpamTrongLuong(KichBan):
    bo_rate_limit = False

    def _lui(self, giay: int):
        with database.ket_noi() as conn:
            conn.execute("UPDATE chat_messages SET created_at = datetime(created_at, ?)", (f"-{giay} seconds",))

    def test_go_chu_tra_loi_nhanh_trong_luong_khong_bi_chan_hoi_nhieu(self):
        """Khách trả lời bằng CHỮ từng bước, mỗi câu cách nhau 8 giây (7 câu trong ~50 giây). Đây là trả lời câu hỏi của chatbot,
        không gọi AI -> không được chặn 'Bạn đã hỏi hơi nhiều trong 1 phút'."""
        cac_cau = ["Tôi muốn đặt tour Nga", "ngày sớm nhất", "2 người lớn", "Lan", "chưa đúng", "đổi ngày khởi hành", "ngày cuối", "đồng ý"]
        for n, cau in enumerate(cac_cau, 1):
            res = self.gui(cau)
            self.assertNotIn("hơi nhiều", res["reply"], f"Bị chặn ở câu thứ {n}: '{cau}'")
            self._lui(8)
        self.assertEqual(self.don_da_gui()["dot"]["key"], "N3")
