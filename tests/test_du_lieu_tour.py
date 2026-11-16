"""Kiểm trên DỮ LIỆU TOUR THẬT đang có trong ChromaDB của máy (chỉ đọc, không gọi mạng, không gọi AI).

Mục đích: khách gọi tên điểm đến / tên tour kiểu gì thì chatbot cũng phải tìm ra đúng tour.
Nếu vừa chạy sync_tours.py mà test ở đây đỏ thì là dữ liệu mới có tên gọi chatbot chưa hiểu.
"""
import unittest

import dat_tour
import rag
from moderation import co_noi_dung_nhay_cam
from rules import ALIAS_DIEM_DEN

TOAN_BO = rag.tat_ca_luot_con_han()
CAC_DIEM_DEN = sorted({m["diem_den"] for m in TOAN_BO if m["diem_den"]})
TEN_TOUR = {}  # tên -> tour_key
for _m in TOAN_BO:
    TEN_TOUR.setdefault(_m["ten"], _m["tour_key"])


@unittest.skipUnless(TOAN_BO, "ChromaDB chưa có dữ liệu tour (chạy python sync_tours.py)")
class TimTourTheoDiemDen(unittest.TestCase):
    def test_moi_diem_den_trong_du_lieu_deu_tim_ra_tour(self):
        for dd in CAC_DIEM_DEN:
            with self.subTest(diem_den=dd):
                tours = rag.tim_tour_lien_quan(f"Có tour {dd} không?")
                self.assertTrue(tours, f"Không tìm ra tour nào cho '{dd}'")
                # Đúng điểm đến, hoặc tour mang chữ đầu tên đó ("Du Lịch Châu Âu" có diem_den = Pháp/Thụy Sĩ): khách hỏi "tour Châu Âu" vẫn phải thấy
                self.assertTrue(all(t["diem_den"] == dd or rag._dau_ten_tour(t["ten"]) == dd for t in tours), {t["diem_den"] for t in tours})

    def test_go_khong_dau(self):
        for dd in CAC_DIEM_DEN:
            with self.subTest(diem_den=dd):
                tours = rag.tim_tour_lien_quan(f"co tour {rag.bo_dau(dd).lower()} khong")
                self.assertTrue(tours and all(t["diem_den"] == dd or rag._dau_ten_tour(t["ten"]) == dd for t in tours))

    def test_ten_goi_khac_cua_khach(self):
        """Mỗi tên gọi khác (alias) có điểm đến thật trong dữ liệu phải dẫn tới tour của điểm đến đó."""
        co = set(CAC_DIEM_DEN)
        for alias, dich in ALIAS_DIEM_DEN.items():
            if dich not in co:
                continue
            with self.subTest(alias=alias):
                tours = rag.tim_tour_lien_quan(f"tour {alias} có không")
                self.assertTrue(tours, f"'{alias}' không ra tour nào")
                self.assertIn(dich, {t["diem_den"] for t in tours})

    def test_ten_goi_pho_bien(self):
        mong = {
            "Có tour Nga không": "Liên bang Nga", "tour nga": "Liên bang Nga", "Tour đi Đà Lạt": "Lâm Đồng",
            "tour Nha Trang": "Khánh Hòa", "đi Phú Quốc": "Kiên Giang", "tour Úc": "Sydney", "tour Anh": "Vương quốc Anh",
            "tour Dubai": "Các Tiểu vương quốc Ả Rập Thống nhất", "tour Đài Loan": None, "tour Nhật": "Nhật Bản", "tour Hàn": "Hàn Quốc",
            "tour Thái": "Thái Lan", "tour Sing": "Singapore", "tour Bali": "Indonesia", "tour Hạ Long": "Hà Nội", "tour Sapa": "Hà Nội",
        }
        for cau, dd in mong.items():
            with self.subTest(cau=cau):
                kq = {t["diem_den"] for t in rag.tim_tour_lien_quan(cau)}
                if dd is None:
                    self.assertTrue(kq & {"Đài Bắc (Taipei)", "Cao Hùng (Kaohsiung)"}, kq)
                else:
                    self.assertIn(dd, kq)

    def test_dia_danh_trong_ten_tour(self):
        """Khách gọi địa danh nằm trong tên tour (không phải tên tỉnh trong dữ liệu) vẫn phải ra đúng tour."""
        for dia_danh in ["Sapa", "Fansipan", "Ninh Bình", "Hà Giang", "Mộc Châu", "Quy Nhơn", "Huế", "Hội An", "Bà Nà", "Tây Nguyên",
                         "Cà Mau", "Miền Tây", "Phú Quốc", "Nha Trang", "Phan Thiết", "Núi Bà Đen", "Dubai", "Bali", "Chiang Mai",
                         "Penang", "Hokkaido", "Seoul", "Bangkok", "Istanbul", "Balkans", "Bắc Âu", "Scotland", "Melbourne", "Đài Loan"]:
            with self.subTest(dia_danh=dia_danh):
                tours = rag.tim_tour_lien_quan(f"Có tour {dia_danh} không?")
                self.assertTrue(tours, f"'{dia_danh}': không ra tour")
                self.assertTrue(any(dat_tour._chuan(dia_danh) in dat_tour._chuan(t["ten"]) for t in tours),
                                f"'{dia_danh}': ra {[t['ten'][:40] for t in tours]}")

    def test_dat_theo_dia_danh_chi_ra_tour_co_dia_danh_do(self):
        for dia_danh in ["Sapa", "Quy Nhơn", "Đà Lạt", "Huế", "Bali", "Dubai"]:
            with self.subTest(dia_danh=dia_danh):
                cands = dat_tour._tim_ung_vien(f"Tôi muốn đặt tour {dia_danh}", {})
                self.assertTrue(cands)
                self.assertTrue(all(dat_tour._chuan(dia_danh) in dat_tour._chuan(c["ten"]) for c in cands), [c["ten"] for c in cands])

    def test_tu_thuong_khong_bi_hieu_nham_la_diem_den(self):
        """'ngày', 'ngân sách', 'anh/chị', 'thái độ'… không được kéo ra tour Nga/Anh/Thái."""
        for cau in ["Tour mấy ngày?", "ngân sách bao nhiêu", "nghĩ lễ đi đâu", "anh tư vấn giúp em tour biển", "chị ơi cho em hỏi tour",
                    "tour re nhat la tour nao", "tour nao dep nhat", "tôi đồng ý", "2 người lớn 1 trẻ em", "mình có ý kiến"]:
            with self.subTest(cau=cau):
                self.assertIsNone(rag.trich_diem_den(cau), f"'{cau}' bị hiểu thành điểm đến")

    def test_cau_chao_khong_kem_tour(self):
        for cau in ["Xin chào", "Bạn là ai", "Số hotline là gì", "Cảm ơn bạn"]:
            with self.subTest(cau=cau):
                self.assertEqual(rag.tim_tour_lien_quan(cau), [])

    def test_ngan_sach(self):
        tours = rag.tim_tour_lien_quan("tour dưới 10 triệu")
        self.assertTrue(tours)
        self.assertTrue(all(t["gia"] <= 10_500_000 for t in tours), [t["gia"] for t in tours])
        tours = rag.tim_tour_lien_quan("tour trên 100 triệu")
        self.assertTrue(all(t["gia"] >= 100_000_000 for t in tours), [t["gia"] for t in tours])

    def test_trong_nuoc_nuoc_ngoai(self):
        for cau, lh in [("tour trong nước", "Trong Nước"), ("tour nước ngoài", "Nước Ngoài")]:
            tours = rag.tim_tour_lien_quan(cau)
            self.assertTrue(tours and all(t["loai_hinh"] == lh for t in tours))

    def test_khong_tra_trung_ten_tour(self):
        for dd in CAC_DIEM_DEN:
            ten = [t["ten"] for t in rag.tim_tour_lien_quan(f"tour {dd}")]
            self.assertEqual(len(ten), len(set(ten)), dd)


@unittest.skipUnless(TOAN_BO, "ChromaDB chưa có dữ liệu tour")
class DatTourTrenDuLieuThat(unittest.TestCase):
    def test_dat_theo_ten_day_du_cua_tour_phai_ra_dung_tour_do(self):
        """Khách chép nguyên tên tour: 'Tôi muốn đặt tour <tên>' -> phải ra đúng 1 tour đó."""
        sai = []
        for ten, key in TEN_TOUR.items():
            cands = dat_tour._tim_ung_vien(f"Tôi muốn đặt tour {ten}", {})
            if [c["key"] for c in cands] != [key]:
                sai.append(f"{ten}  ->  {len(cands)} ứng viên")
        self.assertFalse(sai, f"{len(sai)}/{len(TEN_TOUR)} tour không đặt được bằng tên:\n  " + "\n  ".join(sai[:15]))

    def test_dat_theo_ten_tour_du_vua_co_tour_khac_duoc_goi_y(self):
        """Tên tour có chữ 'đó/này/đầu/trên' (sau khi bỏ dấu) không được bị hiểu là 'tour vừa gợi ý'."""
        st = {"last_tours": [{"key": "khac", "ten": "Tour khác"}]}
        sai = []
        for ten, key in TEN_TOUR.items():
            cands = dat_tour._tim_ung_vien(f"Tôi muốn đặt tour {ten}", st)
            if [c["key"] for c in cands] != [key]:
                sai.append(ten)
        self.assertFalse(sai, f"{len(sai)} tour bị hiểu nhầm:\n  " + "\n  ".join(sai[:15]))

    def test_dat_theo_diem_den_ra_ung_vien_cua_diem_den_do(self):
        for dd in CAC_DIEM_DEN:
            with self.subTest(diem_den=dd):
                cands = dat_tour._tim_ung_vien(f"mình muốn đặt tour {dd} nhé", {})
                self.assertTrue(cands, f"đặt tour {dd}: không ra ứng viên")
                keys = {m["tour_key"] for m in TOAN_BO if m["diem_den"] == dd}
                self.assertTrue({c["key"] for c in cands} <= keys)

    def test_cau_dat_kem_so_nguoi_va_ngay_van_ra_dung_diem_den(self):
        cands = dat_tour._tim_ung_vien("Đặt tour Nga cho 2 người lớn 1 trẻ em", {})
        keys = {m["tour_key"] for m in TOAN_BO if m["diem_den"] == "Liên bang Nga"}
        self.assertTrue(cands and {c["key"] for c in cands} <= keys)

    def test_dat_tour_khong_noi_ten_khong_tu_bia_tour(self):
        for cau in ["Tôi muốn đặt tour", "đặt tour giúp mình", "Tôi muốn đặt tour này", "cho mình đặt tour đó"]:
            with self.subTest(cau=cau):
                self.assertEqual(dat_tour._tim_ung_vien(cau, {}), [])


@unittest.skipUnless(TOAN_BO, "ChromaDB chưa có dữ liệu tour")
class KiemDuyetTrenDuLieuThat(unittest.TestCase):
    def test_ten_tour_va_diem_den_khong_bi_chan_nham(self):
        for ten in list(TEN_TOUR) + CAC_DIEM_DEN + list(ALIAS_DIEM_DEN):
            for cau in (f"Tôi muốn đặt tour {ten}", rag.bo_dau(f"toi muon dat tour {ten}").lower()):
                with self.subTest(cau=cau):
                    self.assertFalse(co_noi_dung_nhay_cam(cau), f"Bị chặn nhầm: {cau}")


@unittest.skipUnless(TOAN_BO, "ChromaDB chưa có dữ liệu tour (chạy python sync_tours.py)")
class DatTourGoiTatDiemDen(unittest.TestCase):
    """Cách khách hay gọi tắt / gọi dân dã khi muốn ĐẶT tour (bug thật: "Tôi muốn đặt tour đài" không ra tour nào)."""

    CAC_CAU = {
        "Tôi muốn đặt tour đài": "Đài Loan",
        "book tour xứ phù tang giúp mình": "Nhật Bản",
        "đặt tour xứ kim chi": "Hàn Quốc",
        "đặt tour đảo quốc sư tử": "Singapore",
        "đặt tour china": "Trung Quốc",
        "đặt tour shanghai": "Thượng Hải",
        "đặt tour bắc âu": "Phần Lan",
        "đặt tour kl": "Kuala Lumpur",
        "đặt tour đn": "Đà Nẵng",
    }

    def test_goi_tat_van_ra_dung_tour(self):
        co = set(CAC_DIEM_DEN)
        for cau, dd in self.CAC_CAU.items():
            if dd not in co:
                continue  # dữ liệu không còn tour nơi này
            with self.subTest(cau=cau):
                keys = {t["key"] for t in dat_tour.tim_tour_theo_cau(cau)}
                self.assertTrue(keys, "Không ra tour nào")
                self.assertTrue(all(any(m["tour_key"] == k and m["diem_den"] == dd for m in TOAN_BO) for k in keys))

    def test_khong_doan_bua_cho_tu_de_nham(self):
        """"anh" (đại từ), "tàu", "trung", "thổ" đứng một mình KHÔNG được tự hiểu thành điểm đến."""
        for cau in ("đặt tour giúp anh", "đặt tour tàu", "đặt tour trung", "đặt tour thổ cẩm"):
            with self.subTest(cau=cau):
                self.assertIsNone(rag.trich_diem_den(cau))

    def test_tour_goi_y_con_cho_moi_diem_den_mot_tour(self):
        goi_y = dat_tour.tour_goi_y()
        self.assertTrue(0 < len(goi_y) <= dat_tour.SO_TOUR_GOI_Y)
        dd = [next(m["diem_den"] for m in TOAN_BO if m["tour_key"] == t["key"]) for t in goi_y]
        self.assertEqual(len(dd), len(set(dd)))
