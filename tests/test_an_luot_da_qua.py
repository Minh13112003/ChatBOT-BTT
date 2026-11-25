"""Lượt khởi hành đã qua tự ẩn lúc chatbot trả lời, không cần chạy lại sync_tours.py (yêu cầu chủ dự án 03/11/2026)."""
import unittest
from datetime import date, timedelta
from unittest import mock

import dat_tour
import rag


def ngay(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def luot(id_: str, ten: str, n: int, diem_den: str = "Bali") -> dict:
    return {"id": id_, "tour_key": f"k-{ten}", "ten": ten, "diem_den": diem_den, "loai_hinh": "Nước Ngoài", "gia": 10_000_000,
            "so_ngay": 4, "ngay_khoi_hanh": ngay(n), "so_cho_con": 10, "anh": "", "url": ""}


HOM_QUA = luot("a0", "Du Lịch Bali", -1)
HOM_NAY = luot("h0", "Du Lịch Bali", 0)  # khởi hành sát ngày (dưới 3 ngày) cũng không gợi ý nữa (chốt 19/11/2026)
HAI_NGAY = luot("h2", "Du Lịch Bali", 2)
BA_NGAY = luot("a1", "Du Lịch Bali", 3)
TUAN_SAU = luot("a2", "Du Lịch Bali", 7)
HET_HAN_HAN = luot("b0", "Du Lịch Bali Cũ", -9)
DU_LIEU = [HOM_QUA, HOM_NAY, HAI_NGAY, BA_NGAY, TUAN_SAU, HET_HAN_HAN]


class Nen(unittest.TestCase):
    def setUp(self):
        gia = mock.Mock()
        gia.get.return_value = {"metadatas": [dict(m) for m in DU_LIEU]}
        gia.query.return_value = {"metadatas": [[dict(m) for m in DU_LIEU]]}
        p = mock.patch.object(rag, "_collection", gia)
        p.start()
        self.addCleanup(p.stop)


class AnLuotDaQua(Nen):
    def test_bo_luot_da_qua_va_luot_duoi_3_ngay(self):
        self.assertEqual([m["id"] for m in rag.tat_ca_luot_con_han()], ["a1", "a2"])

    def test_tu_an_khi_sang_ngay_moi_khong_can_dong_bo(self):
        with mock.patch.object(rag, "date", mock.Mock(wraps=date, today=lambda: date.today() + timedelta(days=1))):
            self.assertEqual([m["id"] for m in rag.tat_ca_luot_con_han()], ["a2"])

    def test_loc_theo_diem_den_khong_ra_luot_da_qua(self):
        self.assertEqual({t["id"] for t in rag.tim_tour_lien_quan("tour Bali")}, {"a1"})

    def test_tim_theo_nghia_khong_ra_luot_da_qua(self):
        self.assertEqual({t["id"] for t in rag.tim_tour_lien_quan("có tour nào hay không")}, {"a1"})

    def test_tour_het_sach_luot_thi_khong_con_xuat_hien(self):
        self.assertNotIn("Du Lịch Bali Cũ", {m["ten"] for m in rag.tat_ca_luot_con_han()})

    def test_goi_y_trong_luong_dat_tour_khong_ra_tour_het_han(self):
        self.assertEqual([g["ten"] for g in dat_tour.tour_goi_y()], ["Du Lịch Bali"])


class TrenDuLieuThat(unittest.TestCase):
    def test_moi_loai_cau_hoi_deu_khong_ra_luot_da_qua(self):
        hom_nay = date.today().isoformat()
        for cau in ["tour Đà Lạt", "có tour nào hay không", "tour nước ngoài", "tour tháng 12", "tour dưới 10 triệu",
                    "tour rẻ nhất", "tour độc lạ", "tour Bali khởi hành ngày nào", "Đà Lạt hay Phú Quốc rẻ hơn", "tour biển"]:
            with self.subTest(cau=cau):
                self.assertFalse([t["ngay_khoi_hanh"] for t in rag.tim_tour_lien_quan(cau) if t["ngay_khoi_hanh"] < rag.ngay_som_nhat_goi_y()])


if __name__ == "__main__":
    unittest.main()
