"""Hỏi tour theo dịp lễ: tour có TÊN đúng dịp không được sót, tour chỉ trùng NGÀY lễ thì bù thêm, không lẫn tour ngoài dịp."""
import unittest
from unittest import mock

import rag
from tests.helpers import NenTest


def luot(id_, ten, ngay_di, so_ngay=4, gia=10_000_000, diem_den="Hàn Quốc"):
    return {
        "id": id_, "tour_key": id_, "ten": ten, "ngay_khoi_hanh": ngay_di, "so_ngay": so_ngay, "gia": gia,
        "diem_den": diem_den, "loai_hinh": "Nước Ngoài", "so_cho_con": 5, "url": "", "anh": "", "ma_tour": id_, "the_loai": "",
    }


TEN_DL = "Du Lịch Đài Loan (Tết Dương Lịch 2027): Đài Bắc"
TEN_NAM_MOI = "Du Lịch Balkans (Đón Giáng Sinh & Năm Mới): Thụy Sĩ"
TEN_NOEL = "Du Lịch Thái Lan (Lễ Noel): Bangkok"
TEN_AM = "Du Lịch Singapore (Tết Âm Lịch 2027): Sentosa"
DU_LIEU = [
    luot("nm", TEN_NAM_MOI, "2026-12-20", 14, 142_990_000),
    luot("noel", TEN_NOEL, "2026-12-18", 4),  # về trước Noel nhưng TÊN đúng dịp -> vẫn phải có
    luot("dl", TEN_DL, "2026-12-30", 5),
    luot("am", TEN_AM, "2027-02-07", 4),
    luot("qua-noel", "Du Lịch Đà Nẵng", "2026-12-23", 3),  # 23–25/12: đang đi đúng Noel
    luot("truoc-noel", "Du Lịch Huế", "2026-12-15", 3),  # 15–17/12: đã về trước Noel
    luot("qua-1-1", "Du Lịch Nhật Bản", "2026-12-29", 5),  # 29/12–2/1: đang đi đúng Tết Dương lịch
    luot("giua-thang-1", "Du Lịch Thái Lan", "2027-01-15", 4),  # giữa tháng 1, không phải Tết nào
    luot("ngay-tet", "Du Lịch Úc", "2027-02-05", 3),  # 5–7/2: trùng Tết Âm 2027 (mùng 1 = 6/2)
    luot("20-11", "Du Lịch Sapa", "2026-11-19", 3),  # 19–21/11: trùng 20/11
]


class TimTheoDip(unittest.TestCase):
    def setUp(self):
        fake = mock.Mock()
        fake.get.return_value = {"metadatas": [dict(m) for m in DU_LIEU]}
        fake.query.return_value = {"metadatas": [[dict(m) for m in DU_LIEU]]}
        self.fake = fake
        for p in [mock.patch.object(rag, "_collection", fake), mock.patch.object(rag, "_con_han", lambda m: True)]:
            p.start()
            self.addCleanup(p.stop)

    def ten(self, cau):
        return [t["ten"] for t in rag.tim_tour_lien_quan(cau)]

    def test_tet_duong_lich_moi_cach_noi(self):
        for cau in ["tour Tết dương lịch", "tour tet duong lich", "tour Tết Tây", "tour tết dl", "tour năm mới",
                    "tour đón năm mới", "tour countdown", "tour 1/1", "tour dịp 1/1"]:
            with self.subTest(cau=cau):
                ket_qua = self.ten(cau)
                self.assertEqual(ket_qua[:2], [TEN_NAM_MOI, TEN_DL], "tour đúng tên phải đứng đầu")
                self.assertIn("Du Lịch Nhật Bản", ket_qua)
                self.assertNotIn(TEN_AM, ket_qua)
                self.assertNotIn("Du Lịch Thái Lan", ket_qua)

    def test_noel_moi_cach_noi(self):
        for cau in ["tour Noel", "tour noen", "tour giáng sinh", "tour giang sinh", "tour lễ noel", "đi chơi dịp giáng sinh", "tour xmas"]:
            with self.subTest(cau=cau):
                ket_qua = self.ten(cau)
                self.assertEqual(set(ket_qua[:2]), {TEN_NOEL, TEN_NAM_MOI})
                self.assertIn("Du Lịch Đà Nẵng", ket_qua)
                self.assertNotIn("Du Lịch Huế", ket_qua, "Tour đã về trước Noel")

    def test_tet_am_lich_moi_cach_noi(self):
        for cau in ["tour Tết âm lịch", "tour tet am lich", "tour tết nguyên đán", "tour tết ta"]:
            with self.subTest(cau=cau):
                ket_qua = self.ten(cau)
                self.assertEqual(ket_qua[0], TEN_AM)
                self.assertIn("Du Lịch Úc", ket_qua)
                self.assertNotIn(TEN_DL, ket_qua)

    def test_tet_chung_gom_ca_hai_nhung_khong_lan_giua_thang_1(self):
        ket_qua = self.ten("tour Tết")
        self.assertIn(TEN_DL, ket_qua)
        self.assertIn(TEN_AM, ket_qua)
        self.assertNotIn("Du Lịch Thái Lan", ket_qua)

    def test_dung_ten_khong_bi_cat_top_k(self):
        self.fake.get.return_value = {"metadatas": [luot(f"t{i}", f"Du Lịch Nơi {i} (Tết Âm Lịch 2027)", "2027-02-07") for i in range(8)]}
        self.assertEqual(len(self.ten("tour Tết âm lịch")), 8)

    def test_le_khac(self):
        self.assertEqual(self.ten("tour 20/11"), ["Du Lịch Sapa"])
        self.assertEqual(self.ten("tour nhà giáo"), ["Du Lịch Sapa"])
        for cau in ["tour quốc khánh", "tour trung thu", "tour valentine"]:
            with self.subTest(cau=cau):
                self.assertEqual(self.ten(cau), [], "Không có tour dịp này thì trả rỗng, không đưa tour ngẫu nhiên")

    def test_dip_le_chung_uu_tien_tour_mang_ten_le(self):
        ket_qua = self.ten("có tour nào đi dịp lễ không")
        self.assertEqual(set(ket_qua[:2]), {TEN_NAM_MOI, TEN_NOEL}, "Lễ gần nhất đứng đầu, tour đúng tên trước")
        self.assertLess(ket_qua.index("Du Lịch Đà Nẵng"), ket_qua.index(TEN_DL))
        self.assertIn(TEN_AM, ket_qua)
        self.assertNotIn("Du Lịch Sapa", ket_qua)

    def test_ket_hop_diem_den_va_gia(self):
        self.fake.get.return_value = {"metadatas": [
            luot("a", TEN_NOEL, "2026-12-18", 4, 8_990_000, "Thái Lan"),
            luot("b", "Du Lịch Thái Lan: Chiang Mai", "2026-12-24", 3, 9_000_000, "Thái Lan"),
            luot("c", "Du Lịch Thái Lan: Pattaya", "2026-11-01", 3, 5_000_000, "Thái Lan"),
            luot("d", TEN_NAM_MOI, "2026-12-20", 14, 142_990_000),
        ]}
        self.assertEqual(self.ten("tour Noel Thái Lan"), [TEN_NOEL, "Du Lịch Thái Lan: Chiang Mai"])
        self.assertNotIn(TEN_NAM_MOI, self.ten("tour Noel dưới 20 triệu"))


class NhanDienKhongNham(unittest.TestCase):
    def test_khong_nham_tet_tay_voi_tay_ninh(self):
        self.assertEqual(rag.trich_dip_le("tour Tết Tây Ninh").mo_ta, "vào dịp Tết")

    def test_so_ngay_gia_so_nguoi_khong_phai_ngay_thang(self):
        for cau in ["tour 3-4 ngày", "tour 5-10 triệu", "đi 2-3 người", "tour 4-5 đêm"]:
            with self.subTest(cau=cau):
                self.assertIsNone(rag.trich_bo_loc_ngay(cau))

    def test_ngay_cu_the_van_la_dung_ngay_khoi_hanh(self):
        loc = rag.trich_bo_loc_ngay("tour đi ngày 15/12")
        self.assertTrue(loc({"ngay_khoi_hanh": "2026-12-15"}))
        self.assertFalse(loc({"ngay_khoi_hanh": "2026-12-14"}))

    def test_mo_ta_dip(self):
        self.assertEqual(rag._mo_ta_dip("tour năm mới"), "vào dịp Tết Dương lịch")
        self.assertEqual(rag._mo_ta_dip("tour noen"), "vào dịp Noel")
        self.assertEqual(rag._mo_ta_dip("tour lễ 30/4"), "vào dịp lễ 30/4")

    def test_so_ngay_loi_khong_lam_sap(self):
        dip = rag.trich_dip_le("tour Noel")
        self.assertTrue(rag.tour_trung_ngay_dip({"ngay_khoi_hanh": "2026-12-25", "so_ngay": None}, dip))
        self.assertFalse(rag.tour_trung_ngay_dip({"ngay_khoi_hanh": "2026-12-26", "so_ngay": "lỗi"}, dip))


class DungDuLieuGia(unittest.TestCase):
    def setUp(self):
        self.fake = mock.Mock()
        self.fake.get.return_value = {"metadatas": [dict(m) for m in DU_LIEU]}
        self.fake.query.return_value = {"metadatas": [[dict(m) for m in DU_LIEU]]}
        for p in [mock.patch.object(rag, "_collection", self.fake), mock.patch.object(rag, "_con_han", lambda m: True)]:
            p.start()
            self.addCleanup(p.stop)

    def dung_ten(self, n, ngay="2026-12-20", ten="Lễ Noel"):
        return [luot(f"t{n}-{i}", f"Du Lịch Nơi {i} ({ten})", ngay) for i in range(n)]

    def trung_ngay(self, n):
        return [luot(f"n{i}", f"Du Lịch Trùng Ngày {i}", "2026-12-23") for i in range(n)]


class ChiaTrang(DungDuLieuGia):
    def trang(self, tours):
        return rag.chia_trang_dip(rag._phan_nhom_theo_dip(tours, rag.trich_dip_le("tour Noel")))

    def so_nhom(self, tours):
        return (sum(t["nhom_dip"] == "dung_ten" for t in tours), sum(t["nhom_dip"] == "trung_ngay" for t in tours))

    def test_toi_da_8_dung_ten_cong_trung_ngay_thanh_10(self):
        trang, con_lai = self.trang(self.dung_ten(13) + self.trung_ngay(6))
        self.assertEqual(self.so_nhom(trang), (8, 2))
        self.assertEqual(self.so_nhom(con_lai), (5, 4))

    def test_it_dung_ten_thi_trung_ngay_bu_du_10(self):
        trang, con_lai = self.trang(self.dung_ten(2) + self.trung_ngay(15))
        self.assertEqual(self.so_nhom(trang), (2, 8))
        self.assertEqual(self.so_nhom(con_lai), (0, 7))

    def test_it_trung_ngay_thi_dung_ten_bu_du_10(self):
        trang, con_lai = self.trang(self.dung_ten(12) + self.trung_ngay(1))
        self.assertEqual(self.so_nhom(trang), (9, 1))
        self.assertEqual(self.so_nhom(con_lai), (3, 0))

    def test_khong_vuot_10_khong_con_lai(self):
        trang, con_lai = self.trang(self.dung_ten(2) + self.trung_ngay(3))
        self.assertEqual(len(trang), 5)
        self.assertEqual(con_lai, [])

    def test_xem_het_khong_sot_khong_trung_tour(self):
        goc = self.dung_ten(13) + self.trung_ngay(14)
        con_lai, da_hien = rag._phan_nhom_theo_dip(goc, rag.trich_dip_le("tour Noel")), []
        while con_lai:
            trang, con_lai = rag.chia_trang_dip(con_lai)
            self.assertLessEqual(len(trang), 10)
            da_hien += [t["id"] for t in trang]
        self.assertCountEqual(da_hien, [t["id"] for t in goc])

    def test_nhan_phan_cach(self):
        trang, _ = self.trang(self.dung_ten(1) + self.trung_ngay(2))
        self.assertNotIn("phan_cach_truoc", trang[0])
        self.assertEqual(trang[1]["phan_cach_truoc"], "Ngoài ra, các tour dưới đây có ngày đi trùng dịp Noel, bạn có thể xem xét thêm:")
        self.assertNotIn("phan_cach_truoc", trang[2])
        trang, _ = self.trang(self.trung_ngay(2))
        self.assertEqual(trang[0]["phan_cach_truoc"], "Các tour dưới đây có ngày đi trùng dịp Noel:")

    def test_toan_dung_ten_khong_co_thanh_ngang(self):
        trang, _ = self.trang(self.dung_ten(3))
        self.assertTrue(all("phan_cach_truoc" not in t for t in trang))

    def test_khong_doi_du_lieu_goc(self):
        rag.chia_trang_dip(rag.tim_tour_lien_quan("tour Noel"))
        self.assertTrue(all("phan_cach_truoc" not in m and "nhom_dip" not in m for m in DU_LIEU))

    def test_cau_khong_co_dip_khong_gan_nhan_khong_chia(self):
        tours = rag.tim_tour_lien_quan("tour Hàn Quốc")
        self.assertTrue(all("nhom_dip" not in t for t in tours))
        self.assertEqual(rag.chia_trang_dip(tours), (tours, []))

    def test_nhanh_khong_loc_theo_dip_khong_gan_nhan_sai(self):
        tours = [luot("x", "Du Lịch Độc Lạ", "2026-07-01"), luot("y", "Du Lịch Đà Nẵng", "2026-12-23")]
        self.assertEqual(rag._phan_nhom_theo_dip(tours, rag.trich_dip_le("tour Noel")), tours)

    def test_hoi_ngay_khoi_hanh_theo_dip_khong_sot_tour(self):
        self.fake.get.return_value = {"metadatas": self.dung_ten(7)}
        self.assertEqual(len({t["ten"] for t in rag.tim_tour_lien_quan("tour Noel khởi hành ngày nào")}), 7)


class DipLeChung(DungDuLieuGia):
    HOM_NAY = rag.date(2026, 11, 4)

    def nhom(self, hom_nay=HOM_NAY):
        tours = rag.tim_tour_lien_quan("có tour nào đi dịp lễ không")
        return rag._phan_nhom_theo_dip(tours, rag.trich_dip_le("dịp lễ"), hom_nay)

    def test_chi_hien_le_gan_nhat(self):
        trang, con_lai = rag.chia_trang_dip(self.nhom())
        self.assertEqual({t["ten_dip"] for t in trang}, {"dịp Noel"})
        self.assertEqual({t["ten"] for t in trang if t["nhom_dip"] == "dung_ten"}, {TEN_NOEL, TEN_NAM_MOI})
        self.assertIn("dịp Tết Dương lịch", {t["ten_dip"] for t in con_lai})

    def test_xem_tiep_sang_le_ke_tiep_theo_thu_tu_ngay(self):
        con_lai, thu_tu = self.nhom(), []
        while con_lai:
            trang, con_lai = rag.chia_trang_dip(con_lai)
            self.assertEqual(len({t["ten_dip"] for t in trang}), 1, "Mỗi lần chỉ hiện 1 dịp")
            thu_tu.append(trang[0]["ten_dip"])
        self.assertEqual(thu_tu, ["dịp Noel", "dịp Tết Dương lịch", "dịp Tết Âm lịch"])

    def test_le_gan_nhat_doi_theo_hom_nay(self):
        trang, _ = rag.chia_trang_dip(self.nhom(rag.date(2026, 12, 28)))
        self.assertEqual(trang[0]["ten_dip"], "dịp Tết Dương lịch")

    def test_tour_mang_ten_tet_duong_lich_khong_bi_xep_vao_noel_du_cham_ngay(self):
        tour = luot("x", "Du Lịch Mỹ (Tết Dương Lịch)", "2026-12-20", 14)
        kq = rag._phan_nhom_theo_dip([tour], rag.trich_dip_le("dịp lễ"), self.HOM_NAY)
        self.assertEqual((kq[0]["ten_dip"], kq[0]["nhom_dip"]), ("dịp Tết Dương lịch", "dung_ten"))


class NhanDienXemTiep(unittest.TestCase):
    def test_xin_xem_tiep(self):
        for cau in ["tiếp tục", "Tiếp tục đi bạn", "tiep tuc", "còn tour nào không", "Còn tour nào không?", "con tour nao khong",
                    "còn tour nào nữa không bạn", "còn tour nào khác không", "có còn tour nào không", "còn nữa không", "xem thêm",
                    "xem tiếp", "cho mình xem thêm tour", "hiện tiếp đi", "còn tour nào ko", "còn không"]:
            with self.subTest(cau=cau):
                self.assertTrue(rag.hoi_xem_tiep_tour(cau))

    def test_cau_hoi_moi_khong_phai_xem_tiep(self):
        for cau in ["còn tour Nhật không", "tour Noel", "còn tour nào rẻ hơn không", "tiếp tục đặt tour Đà Lạt", "còn chỗ không",
                    "tour nào đẹp", "xem tour Hàn Quốc"]:
            with self.subTest(cau=cau):
                self.assertFalse(rag.hoi_xem_tiep_tour(cau))


class QuaApiChat(NenTest, DungDuLieuGia):
    def setUp(self):
        NenTest.setUp(self)
        DungDuLieuGia.setUp(self)
        self.tours_chat = rag._phan_nhom_theo_dip(self.dung_ten(2) + self.trung_ngay(15), rag.trich_dip_le("tour Noel"))

    def test_lan_dau_toi_da_10_the_kem_loi_nhac_va_nut(self):
        res = self.gui("tour Noel")
        self.assertEqual(len(res["tours"]), 10)
        self.assertEqual(res["tours"][2]["phan_cach_truoc"][:8], "Ngoài ra")
        self.assertEqual(res["tours"][2]["nhom_dip"], "trung_ngay")
        self.assertIn('Còn 7 tour nữa, bạn gõ "tiếp tục"', res["reply"])
        self.assertEqual(res["goi_y"][0], "Còn tour nào không")

    def test_xem_tiep_khong_goi_ai_roi_bao_het(self):
        self.gui("tour Noel")
        self.gemini.reset_mock()
        res = self.gui("tiếp tục")
        self.assertEqual(len(res["tours"]), 7)
        self.assertEqual(res["tours"][0]["ten"], "Du Lịch Trùng Ngày 8")
        self.assertIn("các tour cuối cùng", res["reply"])
        self.assertNotIn("Còn tour nào không", res["goi_y"])
        res = self.gui("còn tour nào không")
        self.assertEqual(res["tours"], [])
        self.assertIn("đã hiện hết", res["reply"])
        self.gemini.assert_not_called()

    def test_hoi_le_chung_noi_ro_le_gan_nhat(self):
        res = self.gui("có tour nào đi dịp lễ không")
        self.assertTrue(res["reply"].startswith("Dịp lễ gần nhất là Noel."))

    def test_tim_cau_moi_thi_khong_noi_tiep_danh_sach_cu(self):
        self.gui("tour Noel")
        self.tours_chat = [luot("hq", "Du Lịch Hàn Quốc", "2026-12-01")]
        self.gui("tour Hàn Quốc")
        self.assertIsNone(self.trang_thai().get("tour_con_lai"))
        self.gemini.reset_mock()
        self.gui("còn tour nào không")
        self.gemini.assert_called_once()

    def test_dat_tour_theo_thu_tu_trong_lan_dang_hien(self):
        self.gui("tour Noel")
        self.gui("tiếp tục")
        self.assertEqual(self.trang_thai()["last_tours"][0]["ten"], "Du Lịch Trùng Ngày 8")

    def test_khong_co_dip_thi_nhu_cu(self):
        self.tours_chat = [luot(f"hq{i}", f"Tour {i}", "2026-12-01") for i in range(12)]
        res = self.gui("tour Hàn Quốc")
        self.assertEqual(len(res["tours"]), 12)
        self.assertNotIn("tiếp tục", res["reply"])

    def test_ai_khong_nhan_dong_phan_cach_de_khong_chep_lai(self):
        self.gui("tour Noel")
        tours_cho_ai = self.gemini.call_args.args[1]
        self.assertTrue(all("phan_cach_truoc" not in t for t in tours_cho_ai))
        self.assertEqual(tours_cho_ai[2]["nhom_dip"], "trung_ngay")
