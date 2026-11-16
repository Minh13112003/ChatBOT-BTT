"""Không có tour khớp đủ điều kiện thì nói rõ và gợi ý tour tương tự — yêu cầu chủ dự án 03/11/2026: "tour Trung Quốc 6
ngày cho Tết" đang trả lời không có, trong khi có tour Trung Quốc Tết 5 ngày."""
import unittest
from datetime import date, timedelta
from unittest import mock

import main
import rag
from tests.helpers import NenTest


def ngay(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def nam_sau(md: str) -> str:
    return f"{date.today().year + 1}-{md}"


def luot(id_, ten, so_ngay, ngay_kh, diem_den, gia=20_000_000, loai_hinh="Nước Ngoài"):
    return {"id": id_, "tour_key": f"k-{id_}", "ten": ten, "diem_den": diem_den, "loai_hinh": loai_hinh, "gia": gia,
            "so_ngay": so_ngay, "ngay_khoi_hanh": ngay_kh, "so_cho_con": 10, "anh": "", "url": ""}


TQ_TET = luot("tq-tet", "Du Lịch Trung Quốc (Tết Âm Lịch): Thượng Hải", 5, nam_sau("02-07"), "Thượng Hải", 34_990_000)
TQ_7 = luot("tq-7", "Du Lịch Trung Quốc: Hàng Châu", 7, ngay(10), "Trung Quốc", 19_990_000)
NHAT_6 = luot("nb-6", "Du Lịch Nhật Bản (Tết Âm Lịch): Tokyo", 6, nam_sau("02-08"), "Nhật Bản", 40_000_000)
DA_LAT = luot("dl", "Du Lịch Đà Lạt: Thác Datanla", 3, ngay(20), "Lâm Đồng", 3_790_000, "Trong Nước")
DAK_NONG = luot("dn", "Du Lịch Tây Nguyên: Đắk Nông", 2, ngay(5), "Lâm Đồng", 2_690_000, "Trong Nước")
DU_LIEU = [TQ_TET, TQ_7, NHAT_6, DA_LAT, DAK_NONG]


class NenDuLieuGia(unittest.TestCase):
    def setUp(self):
        gia = mock.Mock()
        gia.get.return_value = {"metadatas": [dict(m) for m in DU_LIEU]}
        gia.query.return_value = {"metadatas": [[dict(m) for m in DU_LIEU]]}
        p = mock.patch.object(rag, "_collection", gia)
        p.start()
        self.addCleanup(p.stop)

    def tim(self, cau):
        goi_y = {}
        return rag.tim_tour_lien_quan(cau, goi_y_gan_dung=goi_y), goi_y

    def ids(self, goi_y):
        return [t["id"] for t in goi_y.get("tours", [])]


class TimTourGanDung(NenDuLieuGia):
    def test_cau_cua_chu_du_an_giu_dip_tet_noi_so_ngay(self):
        dung, goi_y = self.tim("Tôi muốn hỏi tour Trung quốc 6 ngày cho tết dành cho 2 người")
        self.assertEqual(dung, [])
        self.assertEqual(self.ids(goi_y), ["tq-tet"])

    def test_khong_doi_diem_den_du_noi_khac_khop_dung(self):
        _, goi_y = self.tim("tour Trung Quốc 6 ngày dịp Tết")
        self.assertNotIn("nb-6", self.ids(goi_y))

    def test_noi_so_ngay_uu_tien_tour_gan_so_ngay_nhat(self):
        _, goi_y = self.tim("tour Trung Quốc 6 ngày")
        self.assertEqual(sorted(t["so_ngay"] for t in goi_y["tours"]), [5, 7])

    def test_khop_du_thi_khong_goi_y_gan_dung(self):
        dung, goi_y = self.tim("tour Trung Quốc 5 ngày dịp Tết")
        self.assertEqual([t["id"] for t in dung], ["tq-tet"])
        self.assertEqual(goi_y, {})

    def test_noi_khong_co_tour_khong_goi_y_noi_khac(self):
        for cau in ["tour Mỹ 6 ngày", "tour Nam Cực dịp Tết"]:
            with self.subTest(cau=cau):
                self.assertEqual(self.tim(cau), ([], {}))

    def test_khong_neu_diem_den_thi_giu_it_nhat_mot_dieu_kien(self):
        _, goi_y = self.tim("tour Tết 20 ngày")
        self.assertEqual(set(self.ids(goi_y)), {"tq-tet", "nb-6"})
        self.assertEqual(self.tim("tour 40 ngày"), ([], {}))

    def test_hoi_thu_tuc_khong_thanh_goi_y_tour(self):
        self.assertEqual(self.tim("Tour Trung Quốc 6 ngày dịp Tết có cần visa không"), ([], {}))

    def test_uu_tien_tour_dung_ten_khach_goi(self):
        _, goi_y = self.tim("tour Đà Lạt 10 ngày")
        self.assertEqual(self.ids(goi_y)[0], "dl")

    def test_uu_tien_tour_trong_tam_gia(self):
        _, goi_y = self.tim("tour Trung Quốc 6 ngày dưới 25 triệu")
        self.assertEqual(self.ids(goi_y), ["tq-7"])
        self.assertIsNone(goi_y["vuot_gia"])

    def test_khong_tour_nao_trong_tam_gia_thi_ghi_lai(self):
        _, goi_y = self.tim("tour Trung Quốc 6 ngày dưới 10 triệu")
        self.assertEqual(goi_y["vuot_gia"], 10_000_000)

    def test_khong_truyen_tham_so_thi_giu_hanh_vi_cu(self):
        self.assertEqual(rag.tim_tour_lien_quan("tour Trung Quốc 6 ngày dịp Tết"), [])


class CauTraLoi(unittest.TestCase):
    def test_noi_ro_khong_co_va_tour_tuong_tu(self):
        cau = main.tra_loi_gan_dung({"noi": "Trung Quốc", "yeu_cau": ["kéo dài 6 ngày", "vào dịp Tết"], "tours": [dict(TQ_TET)]})
        self.assertIn("chưa có tour Trung Quốc nào vào dịp Tết kéo dài 6 ngày", cau)
        self.assertIn("tương tự", cau)
        self.assertIn("5 ngày 4 đêm", cau)
        self.assertIn(f"khởi hành 07/02/{date.today().year + 1}", cau)
        self.assertIn("34.990.000 đ", cau)

    def test_nhieu_tour_liet_ke_tung_dong(self):
        cau = main.tra_loi_gan_dung({"noi": "Trung Quốc", "yeu_cau": ["kéo dài 6 ngày"], "tours": [dict(TQ_TET), dict(TQ_7)]})
        self.assertIn("2 tour tương tự", cau)
        self.assertIn(TQ_7["ten"], cau)

    def test_vuot_gia_phai_noi_ra(self):
        cau = main.tra_loi_gan_dung({"noi": "Trung Quốc", "yeu_cau": ["kéo dài 6 ngày"], "tours": [dict(TQ_7)], "vuot_gia": 10_000_000})
        self.assertIn("kéo dài 6 ngày dưới 10 triệu", cau)
        self.assertIn("cao hơn mức 10 triệu", cau)


class QuaApiChat(NenTest):
    def test_tra_cau_viet_san_kem_the_khong_goi_ai(self):
        def tim(cau, *a, goi_y_gan_dung=None, **k):
            goi_y_gan_dung.update(noi="Trung Quốc", yeu_cau=["kéo dài 6 ngày", "vào dịp Tết"], tours=[dict(TQ_TET)])
            return []
        with mock.patch.object(main, "tim_tour_lien_quan", tim):
            res = self.gui("tour Trung Quốc 6 ngày cho tết")
        self.assertIn("chưa có tour Trung Quốc nào vào dịp Tết kéo dài 6 ngày", res["reply"])
        self.assertEqual([t["tour_key"] for t in res["tours"]], ["k-tq-tet"])
        self.assertEqual(res["goi_y"], ["Tôi muốn đặt tour này"])
        self.gemini.assert_not_called()


if __name__ == "__main__":
    unittest.main()
