"""Câu hỏi khách hàng THẬT hay gõ -> tầng TÌM TOUR phải trả đúng thẻ tour (chạy trên dữ liệu thật trong ChromaDB, chỉ đọc).

Không gọi Gemini, không gọi mạng. Mỗi test là một kiểu câu hỏi của khách (có dấu / không dấu / teencode / câu dài).
Kỳ vọng được TÍNH TỪ DỮ LIỆU lúc chạy (không ghi cứng tên tour) nên chạy lại sync_tours.py xong test vẫn dùng được;
kịch bản nào dữ liệu hiện tại không đủ điều kiện để kiểm thì tự bỏ qua (skipTest kèm lý do).

Chạy:  PYTHONIOENCODING=utf-8 python -m unittest tests.test_cau_hoi_khach -v

Test ĐỎ ở file này = chatbot đang đưa thẻ tour sai/thiếu so với điều khách hỏi (xem thông báo lỗi của từng test).
"""
import re
import statistics
import unittest
from datetime import date, timedelta

import dat_tour
import main
import rag
from rules import TEN_TOUR_DOC_LA, VUOT_NGAN_SACH_TOI_DA

TOAN_BO = rag.tat_ca_luot_con_han()
TR = 1_000_000
# Chatbot cố ý cho vượt nhẹ ngân sách (rules.VUOT_NGAN_SACH_TOI_DA) -> test chấp nhận đúng mức đó, không hơn.
VUOT = VUOT_NGAN_SACH_TOI_DA
HOM_NAY = date.today()
TRUONG_HOP_DONG = ("tour_key", "id", "ten", "gia", "so_ngay", "ngay_khoi_hanh", "so_cho_con", "anh", "url", "diem_den", "loai_hinh")

chuan = dat_tour._chuan  # bỏ dấu + chữ thường + bỏ ký tự lạ: so tên không phân biệt cách gõ

# ---------------------------------------------------------------- dữ liệu thật, gom theo tên tour
THEO_TEN: dict[str, list[dict]] = {}
for _m in TOAN_BO:
    THEO_TEN.setdefault(_m["ten"], []).append(_m)
CAC_DIEM_DEN = sorted({m["diem_den"] for m in TOAN_BO if m["diem_den"]})
GIA_THAP_NHAT = {ten: min(r["gia"] for r in rs) for ten, rs in THEO_TEN.items()}
GIA_CAO_NHAT = {ten: max(r["gia"] for r in rs) for ten, rs in THEO_TEN.items()}
GIA_GIUA = statistics.median(GIA_THAP_NHAT.values()) if GIA_THAP_NHAT else 0
SO_NGAY_CUA = {ten: rs[0]["so_ngay"] for ten, rs in THEO_TEN.items()}
SO_NGAY_GIUA = statistics.median(SO_NGAY_CUA.values()) if SO_NGAY_CUA else 0


def tim(cau: str, lich_su: list[dict] | None = None) -> list[dict]:
    return rag.tim_tour_lien_quan(cau, lich_su=lich_su)


def tim_nhu_khung_chat(cau: str) -> list[dict]:
    """Thẻ tour khách THẤY cho một câu chat thường: main.py chuyển sang nhân viên (không kèm tour) trước khi tìm tour."""
    if rag.hoi_muon_gap_nhan_vien(cau):
        return []
    return tim(cau)


def lich_su(*cau_khach: str) -> list[dict]:
    kq = []
    for c in cau_khach:
        kq += [{"role": "user", "content": c}, {"role": "assistant", "content": "Mình gửi bạn vài tour ở các thẻ bên dưới nhé."}]
    return kq


def tom(tours: list[dict]) -> str:
    return "\n      " + "\n      ".join(
        f"{t['diem_den']} | {t['so_ngay']} ngày | {t['gia']:,}đ | {t['ngay_khoi_hanh']} | {t['ten'][:60]}" for t in tours
    ) if tours else " (không có thẻ tour nào)"


def ten_co(tu: str) -> set[str]:
    """Tên các tour thật có chứa địa danh `tu` (không phân biệt dấu)."""
    return {ten for ten in THEO_TEN if f" {chuan(tu)} " in f" {chuan(ten)} "}


def diem_den_cua(tu: str) -> set[str]:
    return {THEO_TEN[ten][0]["diem_den"] for ten in ten_co(tu)}


def co_tour_ve(tu: str) -> bool:
    return bool(ten_co(tu)) or any(chuan(tu) in chuan(dd) for dd in CAC_DIEM_DEN)


def dau_ten(ten: str) -> str:
    """'Du Lịch Đài Loan (Tết…): Đài Bắc - …' -> 'Đài Loan' (chữ khách nhìn thấy đầu tiên trên thẻ tour)."""
    s = re.sub(r"^Du Lịch\s+", "", ten)
    return re.split(r"\s*[:(]|\s+[-–]\s+", s)[0].strip()


def ngay(t: dict) -> date:
    return date.fromisoformat(t["ngay_khoi_hanh"])


class Nen(unittest.TestCase):
    def setUp(self):
        if not TOAN_BO:
            self.skipTest("ChromaDB chưa có dữ liệu tour (chạy python sync_tours.py)")

    # ---- kiểm tra dùng chung
    def moi_tour(self, cau: str, tours: list[dict], dieu_kien, mo_ta: str):
        sai = [t for t in tours if not dieu_kien(t)]
        if sai:
            self.fail(f"Khách hỏi “{cau}” nhưng nhận {len(sai)}/{len(tours)} thẻ tour KHÔNG {mo_ta}:{tom(sai)}")

    def co_tour(self, cau: str, tours: list[dict]):
        self.assertTrue(tours, f"Khách hỏi “{cau}” mà không ra thẻ tour nào (dữ liệu có tour phù hợp)")

    def khong_tour(self, cau: str, tours: list[dict]):
        if tours:
            self.fail(f"Khách hỏi “{cau}” (không có tour nào khớp) nhưng vẫn nhận {len(tours)} thẻ tour:{tom(tours)}")

    def dung_dia_danh(self, cau: str, dia_danh: str):
        """Khách gọi `dia_danh` kiểu gì thì cũng chỉ ra tour của nơi đó, và phải có tour mang tên nơi đó."""
        dd = diem_den_cua(dia_danh)
        if not dd:
            self.skipTest(f"Dữ liệu hiện không có tour {dia_danh}")
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["diem_den"] in dd, f"thuộc {dia_danh} ({', '.join(sorted(dd))})")
        self.assertTrue({t["ten"] for t in tours} & ten_co(dia_danh), f"“{cau}”: không có tour nào tên {dia_danh}:{tom(tours)}")

    def khong_ban_tour(self, cau: str, noi: str):
        if co_tour_ve(noi):
            self.skipTest(f"Dữ liệu hiện đã có tour {noi}")
        self.khong_tour(cau, tim(cau))

    def trong_ngan_sach(self, cau: str, tours: list[dict], tran: int, san: int = 0):
        self.moi_tour(cau, tours, lambda t: san <= t["gia"] <= tran + VUOT, f"nằm trong ngân sách {san:,}–{tran:,}đ")


# ================================================================ 1. ĐIỂM ĐẾN
class HoiTheoDiemDen(Nen):
    # ---- viết tắt / teencode
    def test_viet_tat_pq_la_phu_quoc(self):
        self.dung_dia_danh("đi pq có tour nào ko", "Phú Quốc")

    def test_viet_tat_hn_la_ha_noi(self):
        self.dung_dia_danh("tour hn", "Hà Nội")

    def test_viet_tat_hq_la_han_quoc(self):
        self.dung_dia_danh("tour hq", "Hàn Quốc")

    def test_viet_tat_nb_la_nhat_ban(self):
        self.dung_dia_danh("tour nb", "Nhật Bản")

    def test_dat_tour_bang_ten_viet_tat(self):
        """'Tôi muốn đặt tour pq' -> luồng đặt tour phải nhận ra Phú Quốc."""
        if not ten_co("Phú Quốc"):
            self.skipTest("Dữ liệu không có tour Phú Quốc")
        cands = dat_tour.tim_tour_theo_cau("Tôi muốn đặt tour pq")
        self.assertTrue(cands, "Khách gõ “Tôi muốn đặt tour pq” -> chatbot không nhận ra tour Phú Quốc nào")
        self.assertTrue({c["ten"] for c in cands} <= ten_co("Phú Quốc"), [c["ten"] for c in cands])

    # ---- tiếng Anh
    def test_tieng_anh_japan(self):
        self.dung_dia_danh("Do you have any Japan tour?", "Nhật Bản")

    def test_tieng_anh_korea(self):
        self.dung_dia_danh("tour Korea giá sao", "Hàn Quốc")

    def test_tieng_anh_thailand(self):
        self.dung_dia_danh("tour Thailand", "Thái Lan")

    def test_tieng_anh_russia(self):
        self.dung_dia_danh("tour Russia", "Nga")

    # ---- không dấu / viết hoa / thừa dấu câu
    def test_khong_dau_nhat_ban(self):
        self.dung_dia_danh("co tour nhat ban ko", "Nhật Bản")

    def test_khong_dau_cau_dai_co_thang(self):
        cau = "e muon di da nang thang 12 nay co tour nao k a"
        if not any(r["ngay_khoi_hanh"][5:7] == "12" for ten in ten_co("Đà Nẵng") for r in THEO_TEN[ten]):
            self.skipTest("Không có tour Đà Nẵng tháng 12")
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["diem_den"] in diem_den_cua("Đà Nẵng") and ngay(t).month == 12, "là tour Đà Nẵng khởi hành tháng 12")

    def test_viet_hoa_va_thua_khoang_trang(self):
        for cau in ["TOUR THÁI LAN", "  tour   thái   lan  ", "tour thái lan!!!???"]:
            with self.subTest(cau=cau):
                self.dung_dia_danh(cau, "Thái Lan")

    # ---- sai chính tả nhẹ
    def test_sai_dau_da_nang(self):
        self.dung_dia_danh("tour Đà Nãng", "Đà Nẵng")

    def test_thieu_chu_singapore(self):
        self.dung_dia_danh("tour Singapor", "Singapore")

    def test_sai_dau_da_lat(self):
        self.dung_dia_danh("tour Dà Lạt", "Đà Lạt")

    def test_go_dau_khong_deu_phu_quoc(self):
        """Gõ telex sót dấu: 'Phu Quôc'."""
        self.dung_dia_danh("tour Phu Quôc", "Phú Quốc")

    def test_viet_lien_phuquoc(self):
        self.dung_dia_danh("tour phuquoc", "Phú Quốc")

    # ---- vùng miền / châu lục
    def test_mien_tay(self):
        self.dung_dia_danh("tour miền Tây sông nước", "Miền Tây")

    def test_mien_bac(self):
        cau = "tour miền Bắc"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["loai_hinh"] == "Trong Nước" and t["diem_den"] in diem_den_cua("Hà Nội") | diem_den_cua("Sapa"), "là tour miền Bắc")

    def test_dong_nam_a(self):
        dna = {"Thái Lan", "Singapore", "Malaysia", "Kuala Lumpur", "Indonesia", "Campuchia", "Lào", "Philippines", "Myanmar", "Brunei"} & set(CAC_DIEM_DEN)
        if not dna:
            self.skipTest("Không có tour Đông Nam Á")
        cau = "tour Đông Nam Á"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["diem_den"] in dna, f"đi nước Đông Nam Á ({', '.join(sorted(dna))})")

    def test_chau_au_phai_co_tour_ten_chau_au(self):
        """Tour có tên bắt đầu bằng 'Du Lịch Châu Âu' phải hiện ra khi khách hỏi 'tour châu Âu'."""
        mong = {ten for ten in THEO_TEN if dau_ten(ten) == "Châu Âu"}
        if not mong:
            self.skipTest("Không có tour tên 'Du Lịch Châu Âu…'")
        cau = "tour châu Âu"
        co = {t["ten"] for t in tim(cau)}
        self.assertFalse(mong - co, f"“{cau}” bỏ sót {len(mong - co)}/{len(mong)} tour tên Châu Âu:\n      " + "\n      ".join(sorted(mong - co)))

    def test_goi_dung_chu_dau_ten_tour_thi_ra_du_tour_do(self):
        """Khách đọc chữ đầu trên thẻ tour ('Đài Loan', 'Malaysia', 'Bắc Âu'…) rồi hỏi lại -> phải ra ĐỦ các tour mang tên đó."""
        nhom: dict[str, set[str]] = {}
        for ten in THEO_TEN:
            if len(dau_ten(ten).split()) <= 3:
                nhom.setdefault(dau_ten(ten), set()).add(ten)
        sot = []
        for dau, mong in sorted(nhom.items()):
            co = {t["ten"] for t in tim(f"Có tour {dau} không?")}
            if mong - co:
                sot.append(f"“tour {dau}”: thiếu {len(mong - co)}/{len(mong)} tour — " + "; ".join(sorted(x[:55] for x in mong - co)))
        self.assertFalse(sot, f"{len(sot)} tên gọi ra thiếu tour:\n      " + "\n      ".join(sot))

    def test_hai_diem_den_trong_mot_cau(self):
        """'tour Đà Lạt và Phú Quốc' -> phải có tour của cả hai nơi."""
        if not (ten_co("Đà Lạt") and ten_co("Phú Quốc")):
            self.skipTest("Thiếu tour Đà Lạt hoặc Phú Quốc")
        cau = "có tour Đà Lạt và Phú Quốc không"
        co = {t["ten"] for t in tim(cau)}
        self.assertTrue(co & ten_co("Đà Lạt"), f"“{cau}”: thiếu tour Đà Lạt:{tom(tim(cau))}")
        self.assertTrue(co & ten_co("Phú Quốc"), f"“{cau}”: thiếu tour Phú Quốc:{tom(tim(cau))}")

    # ---- nơi công ty KHÔNG có tour: không được đưa tour nơi khác như thể khớp
    def test_nuoc_khong_co_tour_trung_quoc(self):
        self.khong_ban_tour("Có tour Trung Quốc không?", "Trung Quốc")

    def test_nuoc_khong_co_tour_my(self):
        self.khong_ban_tour("tour Mỹ giá bao nhiêu", "Mỹ")

    def test_nuoc_khong_co_tour_campuchia(self):
        self.khong_ban_tour("tour Campuchia", "Campuchia")

    def test_khong_co_tour_nam_cuc(self):
        self.khong_ban_tour("bên mình có tour Nam Cực không", "Nam Cực")

    def test_khong_co_tour_chau_phi(self):
        self.khong_ban_tour("tour châu Phi", "Châu Phi")

    def test_trong_nuoc_khong_co_tour_con_dao_vung_tau(self):
        for noi in ["Côn Đảo", "Vũng Tàu"]:
            with self.subTest(noi=noi):
                self.khong_ban_tour(f"tour {noi}", noi)

    def test_dat_tour_noi_khong_co_thi_khong_bia_ung_vien(self):
        for noi in ["Trung Quốc", "Mỹ", "Nam Cực"]:
            if co_tour_ve(noi):
                continue
            with self.subTest(noi=noi):
                self.assertEqual(dat_tour.tim_tour_theo_cau(f"Tôi muốn đặt tour {noi}"), [])


# ================================================================ 2. NGÂN SÁCH
class HoiTheoNganSach(Nen):
    def test_duoi_10_trieu_cac_cach_go(self):
        for cau in ["tour dưới 10 triệu", "tour duoi 10 trieu", "tour dưới 10.000.000đ", "tour dưới 10tr", "tui có 10 triệu thôi"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.trong_ngan_sach(cau, tours, 10 * TR)

    def test_khoang_5_den_7_trieu(self):
        cau = "tour tầm 5-7tr"
        tours = tim(cau)
        if any(5 * TR <= g <= 7 * TR for g in GIA_THAP_NHAT.values()):
            self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: 5 * TR <= t["gia"] <= 7 * TR, "có giá 5–7 triệu")

    def test_tu_10_den_20_trieu(self):
        cau = "tour từ 10 đến 20 triệu"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: 10 * TR <= t["gia"] <= 20 * TR, "có giá 10–20 triệu")

    def test_tieng_long_15_cu(self):
        """'củ' = triệu (khách miền Nam nói rất nhiều)."""
        cau = "tour khoảng 15 củ"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.trong_ngan_sach(cau, tours, 15 * TR)

    def test_bay_trieu_ruoi_viet_7tr5(self):
        cau = "ngân sách 7tr5 đi đâu được"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.trong_ngan_sach(cau, tours, 7_500_000)

    def test_so_le_7_phay_5_trieu(self):
        """'dưới 7,5 triệu' không được bị hiểu thành 5 triệu (bỏ mất tour 5–7,5 triệu)."""
        trong_khoang = [g for g in GIA_THAP_NHAT.values() if 5_500_000 < g <= 7_500_000]
        if not trong_khoang:
            self.skipTest("Không có tour giá 5,5–7,5 triệu")
        for cau in ["tour dưới 7,5 triệu", "tour dưới 7.5 triệu"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.trong_ngan_sach(cau, tours, 7_500_000)
                self.assertTrue(any(t["gia"] > 5_500_000 for t in tours),
                                f"“{cau}” bị hiểu thành 5 triệu: không có tour nào trên 5,5 triệu dù dữ liệu có {len(trong_khoang)} tour:{tom(tours)}")

    def test_re_nhat(self):
        re_nhat = min(GIA_THAP_NHAT.values())
        for cau in ["tour nào rẻ nhất vậy shop", "tour re nhat la tour nao", "cho mình tour rẻ nhất"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.assertTrue(any(GIA_THAP_NHAT[t["ten"]] == re_nhat for t in tours),
                                f"“{cau}”: tour rẻ nhất ({re_nhat:,}đ) không có trong thẻ tour:{tom(tours)}")

    def test_dat_nhat(self):
        dat_nhat = max(GIA_CAO_NHAT.values())
        for cau in ["tour đắt nhất là tour nào", "tour nào mắc nhất"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.assertTrue(any(GIA_CAO_NHAT[t["ten"]] == dat_nhat for t in tours),
                                f"“{cau}”: tour đắt nhất ({dat_nhat:,}đ) không có trong thẻ tour:{tom(tours)}")

    def test_re_nhat_cua_mot_diem_den(self):
        """'tour Thái Lan rẻ nhất' -> thẻ đầu tiên phải là tour Thái rẻ nhất."""
        thai = {ten: g for ten, g in GIA_THAP_NHAT.items() if THEO_TEN[ten][0]["diem_den"] == "Thái Lan"}
        if len(set(thai.values())) < 2:
            self.skipTest("Không đủ tour Thái Lan khác giá")
        cau = "tour Thái Lan rẻ nhất"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["diem_den"] == "Thái Lan", "đi Thái Lan")
        self.assertEqual(GIA_THAP_NHAT[tours[0]["ten"]], min(thai.values()), f"Thẻ đầu tiên không phải tour Thái rẻ nhất:{tom(tours)}")

    def test_tour_cao_cap_khong_dua_tour_re(self):
        for cau in ["tour cao cấp", "tour sang chảnh"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: t["gia"] >= GIA_GIUA, f"thuộc nửa giá cao (từ {int(GIA_GIUA):,}đ)")

    def test_tour_gia_re_khong_dua_tour_dat(self):
        cau = "có tour giá rẻ không"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["gia"] <= GIA_GIUA, f"thuộc nửa giá thấp (đến {int(GIA_GIUA):,}đ)")

    def test_tren_50_trieu(self):
        cau = "tour trên 50 triệu"
        tours = tim(cau)
        if any(g >= 50 * TR for g in GIA_CAO_NHAT.values()):
            self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["gia"] >= 50 * TR, "có giá từ 50 triệu")

    def test_tren_muc_gia_cao_nhat_thi_khong_co_tour(self):
        n = max(GIA_CAO_NHAT.values()) // TR + 50
        cau = f"tour trên {n} triệu"
        self.khong_tour(cau, tim(cau))

    def test_10_trieu_moi_nguoi_cho_4_nguoi(self):
        """Số người không được bị hiểu thành tiền hay số ngày."""
        cau = "tour 10tr/người cho 4 người"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.trong_ngan_sach(cau, tours, 10 * TR)

    def test_20_trieu_cho_2_nguoi(self):
        cau = "20 triệu 2 người đi đâu được"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.trong_ngan_sach(cau, tours, 20 * TR)

    def test_diem_den_kem_ngan_sach(self):
        """'tour <điểm đến> dưới N triệu' -> đúng điểm đến VÀ không quá N triệu (thử trên mọi điểm đến có tour rẻ lẫn tour đắt)."""
        da_thu = 0
        for dd in CAC_DIEM_DEN:
            gia = sorted(g for ten, g in GIA_THAP_NHAT.items() if THEO_TEN[ten][0]["diem_den"] == dd)
            if not gia:
                continue
            n = gia[0] // TR + 1
            if not any(g > n * TR + VUOT for g in gia):
                continue  # điểm đến này không có tour vượt ngân sách -> không kiểm được
            da_thu += 1
            cau = f"tour {dd} dưới {n} triệu"
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: t["diem_den"] == dd or dau_ten(t["ten"]) == dd, f"đi {dd} (điểm đến hoặc chữ đầu tên tour, vd tour 'Du Lịch Châu Âu' có diem_den là Pháp/Thụy Sĩ)")
                self.trong_ngan_sach(cau, tours, n * TR)
        if not da_thu:
            self.skipTest("Không có điểm đến nào vừa có tour trong ngân sách vừa có tour vượt")

    def test_diem_den_ma_khong_tour_nao_vua_tui_tien(self):
        """'tour Phú Quốc dưới X' với X thấp hơn mọi tour Phú Quốc -> không được đưa tour vượt ngân sách."""
        gia = [GIA_THAP_NHAT[ten] for ten in ten_co("Phú Quốc")]
        if not gia or min(gia) // TR < 3:
            self.skipTest("Không có tour Phú Quốc đủ đắt để kiểm")
        n = (min(gia) - VUOT) // TR - 1
        cau = f"tour Phú Quốc dưới {n} triệu"
        tours = tim(cau)
        self.trong_ngan_sach(cau, tours, n * TR)

    def test_khoang_gia_kem_diem_den(self):
        cau = "tour 10-15tr đi Thái"
        tours = tim(cau)
        self.moi_tour(cau, tours, lambda t: t["diem_den"] == "Thái Lan", "đi Thái Lan")
        self.moi_tour(cau, tours, lambda t: 10 * TR <= t["gia"] <= 15 * TR, "có giá 10–15 triệu")

    def test_nuoc_ngoai_duoi_10_trieu(self):
        cau = "tour nước ngoài dưới 10 triệu"
        tours = tim(cau)
        self.moi_tour(cau, tours, lambda t: t["loai_hinh"] == "Nước Ngoài", "là tour nước ngoài")
        self.trong_ngan_sach(cau, tours, 10 * TR)

    def test_trong_nuoc_duoi_5_trieu(self):
        cau = "tour trong nước dưới 5 triệu"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["loai_hinh"] == "Trong Nước", "là tour trong nước")
        self.trong_ngan_sach(cau, tours, 5 * TR)

    def test_trong_nuoc_tu_5_den_10_trieu(self):
        cau = "tour từ 5 đến 10 triệu trong nước"
        tours = tim(cau)
        self.moi_tour(cau, tours, lambda t: t["loai_hinh"] == "Trong Nước", "là tour trong nước")
        self.moi_tour(cau, tours, lambda t: 5 * TR <= t["gia"] <= 10 * TR, "có giá 5–10 triệu")

    def test_trong_nuoc_nuoc_ngoai_go_khong_dau(self):
        for cau, lh in [("tour trong nuoc", "Trong Nước"), ("tour noi dia", "Trong Nước"), ("tour nuoc ngoai", "Nước Ngoài"), ("tour quoc te", "Nước Ngoài")]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: t["loai_hinh"] == lh, f"là tour {lh.lower()}")


# ================================================================ 3. THỜI GIAN / SỐ NGÀY
class HoiTheoThoiGian(Nen):
    def test_thang_12(self):
        for cau in ["có tour nào đi tháng 12 không", "tour thang 12", "T12 có tour gì"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                if any(m["ngay_khoi_hanh"][5:7] == "12" for m in TOAN_BO):
                    self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: ngay(t).month == 12, "khởi hành tháng 12")

    def test_thang_khong_co_chuyen_nao(self):
        trong = [th for th in range(1, 13) if not any(int(m["ngay_khoi_hanh"][5:7]) == th for m in TOAN_BO)]
        if not trong:
            self.skipTest("Tháng nào cũng có tour")
        cau = f"tour tháng {trong[0]}"
        self.khong_tour(cau, tim(cau))

    def test_diem_den_kem_thang(self):
        """Mỗi điểm đến hỏi kèm một tháng có chuyến và một tháng không có chuyến."""
        for dd in CAC_DIEM_DEN:
            thang_co = sorted({int(m["ngay_khoi_hanh"][5:7]) for m in TOAN_BO if m["diem_den"] == dd})
            thang_khong = [th for th in range(1, 13) if th not in thang_co]
            cau = f"tour {dd} tháng {thang_co[0]}"
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: (t["diem_den"] == dd or dau_ten(t["ten"]) == dd) and ngay(t).month == thang_co[0], f"là tour {dd} đi tháng {thang_co[0]}")
            if thang_khong:
                cau = f"tour {dd} tháng {thang_khong[0]}"
                with self.subTest(cau=cau):
                    self.khong_tour(cau, tim(cau))

    def test_tet(self):
        def hop(t):
            return "tết" in t["ten"].lower() or rag.tour_trung_ngay_dip(t, rag.trich_dip_le("tour Tết"))
        if not any(hop(m) for m in TOAN_BO):
            self.skipTest("Không có tour dịp Tết")
        for cau in ["Tết này có tour gì", "tour tết âm lịch"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, hop, "là tour dịp Tết (tên có 'Tết' hoặc đang chạy đúng ngày Tết)")

    def test_noel(self):
        def hop(t):
            return re.search(r"noel|giáng sinh", t["ten"].lower()) or rag.tour_trung_ngay_dip(t, rag.trich_dip_le("tour Noel"))
        if not any(hop(m) for m in TOAN_BO):
            self.skipTest("Không có tour dịp Noel")
        for cau in ["tour Noel", "tour đi dịp giáng sinh"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, hop, "là tour dịp Noel (tên có Noel/Giáng Sinh hoặc đang chạy đúng 24–25/12)")

    def test_le_30_4(self):
        def hop(t):
            return rag.tour_trung_ngay_dip(t, rag.trich_dip_le("tour lễ 30/4"))
        cau = "tour lễ 30/4"
        tours = tim(cau)
        self.moi_tour(cau, tours, hop, "đang chạy đúng lễ 30/4–1/5")
        if any(hop(m) for m in TOAN_BO):
            self.co_tour(cau, tours)

    def test_mua_he(self):
        def hop(t):
            return ngay(t).month in (5, 6, 7, 8)
        for cau in ["tour hè cho bé", "tour mùa hè"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.moi_tour(cau, tours, hop, "khởi hành mùa hè (tháng 5–8)")
                if any(hop(m) for m in TOAN_BO):
                    self.co_tour(cau, tours)

    def test_cuoi_tuan_nay(self):
        chu_nhat = HOM_NAY + timedelta(days=6 - HOM_NAY.weekday())
        cau = "cuối tuần này có tour nào đi không"
        tours = tim(cau)
        self.moi_tour(cau, tours, lambda t: HOM_NAY <= ngay(t) <= chu_nhat, f"khởi hành từ nay đến chủ nhật {chu_nhat:%d/%m}")

    def test_tuan_sau(self):
        thu_hai = HOM_NAY + timedelta(days=7 - HOM_NAY.weekday())
        cau = "tuần sau có tour nào khởi hành"
        tours = tim(cau)
        self.moi_tour(cau, tours, lambda t: thu_hai <= ngay(t) <= thu_hai + timedelta(days=6), f"khởi hành tuần sau ({thu_hai:%d/%m}–{thu_hai + timedelta(days=6):%d/%m})")

    def test_hoi_dung_mot_ngay_khoi_hanh(self):
        """Khách hỏi 'tour khởi hành ngày dd/mm' (ngày có thật trong lịch) -> chỉ ra tour đi đúng ngày đó."""
        tuong_lai = sorted({m["ngay_khoi_hanh"] for m in TOAN_BO if m["ngay_khoi_hanh"] >= HOM_NAY.isoformat()})
        if not tuong_lai:
            self.skipTest("Không còn ngày khởi hành nào trong tương lai")
        d = date.fromisoformat(tuong_lai[len(tuong_lai) // 3])
        cau = f"có tour nào khởi hành ngày {d.day}/{d.month} không"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: ngay(t) == d, f"khởi hành ngày {d:%d/%m/%Y}")


class HoiTheoSoNgay(Nen):
    def test_3_ngay_2_dem(self):
        for cau in ["tour 3 ngày 2 đêm", "tour 3 ngay 2 dem"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                if 3 in SO_NGAY_CUA.values():
                    self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: t["so_ngay"] == 3, "đi đúng 3 ngày")

    def test_viet_tat_3n2d(self):
        if 3 not in SO_NGAY_CUA.values():
            self.skipTest("Không có tour 3 ngày")
        for cau in ["tour 3n2d", "tour 3N2Đ", "tour 3n2đ giá rẻ"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: t["so_ngay"] == 3, "đi đúng 3 ngày")

    def test_viet_tat_4n3d_kem_diem_den(self):
        """'Tour Đà Nẵng 4N3Đ' -> chỉ tour Đà Nẵng 4 ngày."""
        if not any(SO_NGAY_CUA[ten] == 4 for ten in ten_co("Đà Nẵng")):
            self.skipTest("Không có tour Đà Nẵng 4 ngày")
        cau = "Tour Đà Nẵng 4N3Đ"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["so_ngay"] == 4, "đi đúng 4 ngày")

    def test_2_ngay_1_dem_phai_ra_du_lua_chon(self):
        co = [ten for ten, n in SO_NGAY_CUA.items() if n == 2]
        if len(co) < 2:
            self.skipTest("Dưới 2 tour 2 ngày")
        cau = "tour 2 ngày 1 đêm"
        tours = tim(cau)
        self.moi_tour(cau, tours, lambda t: t["so_ngay"] == 2, "đi đúng 2 ngày")
        self.assertGreaterEqual(len(tours), min(3, len(co)), f"“{cau}”: dữ liệu có {len(co)} tour 2 ngày nhưng chỉ đưa {len(tours)}:{tom(tours)}")

    def test_tu_7_ngay_tro_len(self):
        for cau in ["tour trên 7 ngày", "tour ít nhất 7 ngày", "tour từ 7 ngày trở lên"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: t["so_ngay"] >= 7, "đi từ 7 ngày")

    def test_toi_da_4_ngay(self):
        for cau in ["tour tối đa 4 ngày", "tour không quá 4 ngày"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: t["so_ngay"] <= 4, "đi tối đa 4 ngày")

    def test_tour_di_trong_ngay(self):
        if 1 not in SO_NGAY_CUA.values():
            self.skipTest("Không có tour 1 ngày")
        for cau in ["tour 1 ngày", "tour đi trong ngày", "tour đi về trong ngày"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: t["so_ngay"] == 1, "là tour 1 ngày")

    def test_chi_noi_so_ngay(self):
        """'tour 5 ngày' (không kèm 'đêm') cũng là điều kiện số ngày."""
        if 5 not in SO_NGAY_CUA.values():
            self.skipTest("Không có tour 5 ngày")
        cau = "tour 5 ngày"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["so_ngay"] == 5, "đi đúng 5 ngày")

    def test_tour_ngan_ngay(self):
        cau = "tour ngắn ngày"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["so_ngay"] <= SO_NGAY_GIUA, f"ngắn (tối đa {SO_NGAY_GIUA:g} ngày = mức giữa của toàn bộ tour)")

    def test_tour_dai_ngay(self):
        cau = "tour dài ngày"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["so_ngay"] >= SO_NGAY_GIUA, f"dài (từ {SO_NGAY_GIUA:g} ngày = mức giữa của toàn bộ tour)")


# ================================================================ 4. KẾT HỢP NHIỀU ĐIỀU KIỆN
class HoiKetHop(Nen):
    def test_nhat_thang_11_duoi_40_trieu_5_ngay(self):
        cau = "tour Nhật tháng 11 dưới 40 triệu 5 ngày"
        self.moi_tour(cau, tim(cau), lambda t: t["diem_den"] == "Nhật Bản" and ngay(t).month == 11 and t["gia"] <= 40 * TR + VUOT and t["so_ngay"] == 5,
                      "thoả cả 4 điều kiện (Nhật, tháng 11, ≤40 triệu, 5 ngày)")

    def test_nhat_thang_11_duoi_40_trieu(self):
        cau = "tour Nhật tháng 11 dưới 40 triệu"
        tours = tim(cau)
        if any(m["diem_den"] == "Nhật Bản" and m["ngay_khoi_hanh"][5:7] == "11" and m["gia"] <= 40 * TR for m in TOAN_BO):
            self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["diem_den"] == "Nhật Bản" and ngay(t).month == 11 and t["gia"] <= 40 * TR + VUOT, "thoả (Nhật, tháng 11, ≤40 triệu)")

    def test_thai_duoi_8_trieu_thang_12(self):
        cau = "tour Thái dưới 8tr tháng 12"
        tours = tim(cau)
        self.moi_tour(cau, tours, lambda t: t["diem_den"] == "Thái Lan" and ngay(t).month == 12, "là tour Thái đi tháng 12")
        self.trong_ngan_sach(cau, tours, 8 * TR)

    def test_trong_nuoc_thang_11_duoi_5_trieu_3n2d(self):
        cau = "tour trong nước tháng 11 dưới 5 triệu 3 ngày 2 đêm"
        tours = tim(cau)
        if any(m["loai_hinh"] == "Trong Nước" and m["ngay_khoi_hanh"][5:7] == "11" and m["gia"] <= 5 * TR and m["so_ngay"] == 3 for m in TOAN_BO):
            self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["loai_hinh"] == "Trong Nước" and ngay(t).month == 11 and t["gia"] <= 5 * TR + VUOT and t["so_ngay"] == 3, "thoả cả 4 điều kiện")

    def test_nuoc_ngoai_thang_12_duoi_20_trieu_phai_du_lua_chon(self):
        cau = "tour nước ngoài tháng 12 dưới 20 triệu"
        co = {m["ten"] for m in TOAN_BO if m["loai_hinh"] == "Nước Ngoài" and m["ngay_khoi_hanh"][5:7] == "12" and m["gia"] <= 20 * TR}
        tours = tim(cau)
        self.moi_tour(cau, tours, lambda t: t["loai_hinh"] == "Nước Ngoài" and ngay(t).month == 12 and t["gia"] <= 20 * TR + VUOT, "thoả (nước ngoài, tháng 12, ≤20 triệu)")
        self.assertGreaterEqual(len(tours), min(3, len(co)), f"“{cau}”: dữ liệu có {len(co)} tour thoả nhưng chỉ đưa {len(tours)}:{tom(tours)}")

    def test_5_ngay_4_dem_duoi_15_trieu(self):
        cau = "tour 5 ngày 4 đêm dưới 15 triệu"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["so_ngay"] == 5 and t["gia"] <= 15 * TR + VUOT, "thoả (5 ngày, ≤15 triệu)")

    def test_cau_dai_teencode_co_ngan_sach(self):
        cau = "mình muốn đi chơi đâu đó gần Sài Gòn 2 ngày cuối tuần, ngân sách tầm 3 triệu một người thì có tour nào không shop"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.trong_ngan_sach(cau, tours, 3 * TR)

    def test_cau_teencode_phu_quoc_3n2d(self):
        if not any(SO_NGAY_CUA[ten] == 3 for ten in ten_co("Phú Quốc")):
            self.skipTest("Không có tour Phú Quốc 3 ngày")
        cau = "cho mình hỏi tour phú quốc 3 ngày 2 đêm giá nhiêu z"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["ten"] in ten_co("Phú Quốc") and t["so_ngay"] == 3, "là tour Phú Quốc 3 ngày")


# ================================================================ 5. NHU CẦU
class HoiTheoNhuCau(Nen):
    def _hop_le(self, cau: str) -> list[dict]:
        tours = tim(cau)
        self.co_tour(cau, tours)
        ten = [t["ten"] for t in tours]
        self.assertEqual(len(ten), len(set(ten)), f"“{cau}”: thẻ tour bị trùng tên")
        self.assertLessEqual(len(tours), 10, f"“{cau}”: quá nhiều thẻ tour ({len(tours)})")
        return tours

    def _co_tu_khoa(self, cau: str, mau: str, mo_ta: str):
        if not any(re.search(mau, ten, re.IGNORECASE) for ten in THEO_TEN):
            self.skipTest(f"Dữ liệu không có tour {mo_ta}")
        tours = self._hop_le(cau)
        self.assertTrue(any(re.search(mau, t["ten"], re.IGNORECASE) for t in tours), f"“{cau}”: không thẻ nào là tour {mo_ta}:{tom(tours)}")

    def test_gia_dinh_co_tre_nho(self):
        self._hop_le("tour cho gia đình có trẻ nhỏ 3 tuổi")

    def test_nguoi_lon_tuoi(self):
        self._hop_le("tour nhẹ nhàng cho ba mẹ lớn tuổi")

    def test_trang_mat(self):
        self._hop_le("tour trăng mật cho 2 vợ chồng mới cưới")

    def test_team_building(self):
        self._hop_le("công ty mình cần tour team building 30 người")

    def test_di_bien(self):
        self._co_tu_khoa("tour đi biển", r"biển|đảo|beach|vịnh|san hô|phú quốc|nha trang|maldives|bali|phan thiết|quy nhơn", "biển đảo")

    def test_ngam_tuyet(self):
        self._co_tu_khoa("tour ngắm tuyết", r"tuyết|băng|cực quang", "tuyết/băng")

    def test_san_cuc_quang(self):
        self._co_tu_khoa("tour săn cực quang", r"cực quang", "săn cực quang")

    def test_hanh_huong(self):
        self._co_tu_khoa("tour hành hương lễ chùa", r"chùa|tự\b|thánh|bái đính|yên tử|borobudur|núi bà", "hành hương")

    def test_tour_doc_la(self):
        co = TEN_TOUR_DOC_LA & set(THEO_TEN)
        if not co:
            self.skipTest("Dữ liệu không còn tour độc lạ nào")
        for cau in ["Có tour nào độc lạ không?", "tour doc la"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.assertEqual({t["ten"] for t in tours}, co, f"“{cau}”: phải ra đúng {len(co)} tour độc lạ")
                self.assertEqual(len(tours), len(co), "tour độc lạ bị trùng thẻ")


# ================================================================ 6. SO SÁNH / PHỦ ĐỊNH / NỐI TIẾP
class SoSanhVaPhuDinh(Nen):
    def _hai_ben(self, cau: str, a: str, b: str):
        if not (ten_co(a) and ten_co(b)):
            self.skipTest(f"Thiếu tour {a} hoặc {b}")
        tours = tim(cau)
        co = {t["ten"] for t in tours}
        self.assertTrue(co & ten_co(a), f"“{cau}”: thiếu tour {a}:{tom(tours)}")
        self.assertTrue(co & ten_co(b), f"“{cau}”: thiếu tour {b}:{tom(tours)}")
        self.moi_tour(cau, tours, lambda t: t["diem_den"] in diem_den_cua(a) | diem_den_cua(b), f"thuộc {a} hoặc {b}")

    def test_da_nang_hay_phu_quoc(self):
        self._hai_ben("Đà Nẵng hay Phú Quốc rẻ hơn", "Đà Nẵng", "Phú Quốc")

    def test_so_sanh_nhat_voi_han(self):
        self._hai_ben("so sánh tour Nhật với Hàn giúp mình", "Nhật Bản", "Hàn Quốc")

    def test_nen_di_thai_hay_sing(self):
        self._hai_ben("nên đi Thái hay Sing", "Thái Lan", "Singapore")

    def test_khong_di_thai(self):
        for cau in ["tour nước ngoài nào cũng được, không đi Thái", "tôi không muốn đi Thái Lan", "trừ Thái Lan ra thì có tour nước ngoài nào"]:
            with self.subTest(cau=cau):
                tours = tim(cau)
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: t["diem_den"] != "Thái Lan", "khác Thái Lan (khách đã nói KHÔNG đi Thái)")

    def test_nuoc_ngoai_nhung_khong_phai_thai(self):
        cau = "tour nước ngoài nhưng không phải Thái Lan"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["loai_hinh"] == "Nước Ngoài" and t["diem_den"] != "Thái Lan", "là tour nước ngoài khác Thái Lan")

    def test_ngoai_da_lat_ra(self):
        if not ten_co("Đà Lạt"):
            self.skipTest("Không có tour Đà Lạt")
        cau = "ngoài Đà Lạt ra còn tour nào"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["ten"] not in ten_co("Đà Lạt"), "khác Đà Lạt (khách hỏi NGOÀI Đà Lạt)")

    def test_da_di_da_nang_roi_muon_cho_moi(self):
        cau = "đã đi Đà Nẵng rồi, muốn tìm chỗ mới"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["ten"] not in ten_co("Đà Nẵng"), "khác Đà Nẵng (khách nói đã đi rồi)")


class CauNoiTiep(Nen):
    def test_re_hon_nua(self):
        for cau in ["rẻ hơn nữa", "re hon nua di", "có tour nào thấp hơn không"]:
            with self.subTest(cau=cau):
                tours = tim(cau, lich_su("tour dưới 10 triệu"))
                self.co_tour(cau, tours)
                self.moi_tour(cau, tours, lambda t: t["gia"] < 10 * TR, "rẻ hơn mức 10 triệu vừa hỏi")

    def test_giam_mot_nua(self):
        cau = "giảm một nửa đi"
        tours = tim(cau, lich_su("tour dưới 10 triệu"))
        self.co_tour(cau, tours)
        self.trong_ngan_sach(cau, tours, 5 * TR)

    def test_dat_hon_chut(self):
        cau = "đắt hơn chút cũng được"
        tours = tim(cau, lich_su("tour dưới 10 triệu"))
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["gia"] > 10 * TR, "đắt hơn mức 10 triệu vừa hỏi")

    def test_khong_co_lich_su_thi_re_hon_khong_bia_tour(self):
        self.assertEqual(tim("rẻ hơn nữa"), [])
        self.assertEqual(tim("rẻ hơn nữa", []), [])

    def test_tour_do_di_may_ngay(self):
        """Vừa xem tour Đà Lạt, hỏi 'tour đó đi mấy ngày' -> không được kèm thẻ tour nơi khác."""
        if not ten_co("Đà Lạt"):
            self.skipTest("Không có tour Đà Lạt")
        cau = "tour đó đi mấy ngày"
        tours = tim(cau, lich_su("tour Đà Lạt"))
        self.moi_tour(cau, tours, lambda t: t["diem_den"] in diem_den_cua("Đà Lạt"), "thuộc Đà Lạt (tour khách vừa hỏi)")

    def test_them_ngan_sach_cho_diem_den_vua_hoi(self):
        """'tour Thái Lan' rồi 'dưới 10 triệu thôi' -> tour THÁI dưới 10 triệu."""
        if not any(g <= 10 * TR for ten, g in GIA_THAP_NHAT.items() if THEO_TEN[ten][0]["diem_den"] == "Thái Lan"):
            self.skipTest("Không có tour Thái dưới 10 triệu")
        cau = "dưới 10 triệu thôi"
        tours = tim(cau, lich_su("tour Thái Lan"))
        self.co_tour(cau, tours)
        self.trong_ngan_sach(cau, tours, 10 * TR)
        self.moi_tour(cau, tours, lambda t: t["diem_den"] == "Thái Lan", "đi Thái Lan (điểm đến khách vừa hỏi ở câu trước)")

    def test_them_thang_cho_diem_den_vua_hoi(self):
        """'tour Đà Lạt' rồi 'tháng 12 có đi không' -> tour Đà Lạt tháng 12."""
        if not any(r["ngay_khoi_hanh"][5:7] == "12" for ten in ten_co("Đà Lạt") for r in THEO_TEN[ten]):
            self.skipTest("Không có tour Đà Lạt tháng 12")
        cau = "tháng 12 có đi không"
        tours = tim(cau, lich_su("tour Đà Lạt"))
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["diem_den"] in diem_den_cua("Đà Lạt") and ngay(t).month == 12, "là tour Đà Lạt đi tháng 12")

    def test_con_tour_nao_khac_khong(self):
        cau = "còn tour nào khác không"
        tours = tim(cau, lich_su("tour Đà Lạt"))
        self.co_tour(cau, tours)
        self.assertEqual(len({t["ten"] for t in tours}), len(tours))


# ================================================================ 7. CÂU KHÔNG ĐƯỢC KÈM THẺ TOUR
class KhongDuocKemTour(Nen):
    def _khong(self, *cac_cau: str):
        for cau in cac_cau:
            with self.subTest(cau=cau):
                self.khong_tour(cau, tim_nhu_khung_chat(cau))

    def test_chao_hoi(self):
        self._khong("hi", "alo", "chào shop", "hello bttAI", "có ai ở đó không", "em chào anh chị ạ")

    def test_cam_on_tam_biet(self):
        self._khong("thanks nha", "ok cảm ơn", "cam on ban nhieu", "tạm biệt nhé", "ok để mình suy nghĩ thêm")

    def test_hoi_thoi_tiet(self):
        self._khong("thời tiết hôm nay thế nào", "mai trời có mưa không")

    def test_hoi_chinh_sach_huy_hoan(self):
        self._khong("chính sách huỷ tour thế nào", "chính sách hoàn tiền ra sao", "huy tour co mat phi khong")

    def test_hoi_dia_chi_van_phong(self):
        self._khong("địa chỉ văn phòng ở đâu", "công ty mình ở đâu vậy", "mấy giờ công ty mở cửa", "hotline bao nhiêu")

    def test_hoi_van_phong_o_thanh_pho_co_tour(self):
        """Hỏi văn phòng ở Hà Nội không phải hỏi tour Hà Nội."""
        self._khong("văn phòng công ty ở Hà Nội không", "chi nhánh Đà Nẵng nằm ở đường nào")

    def test_ngoai_le_toan_code_chinh_tri(self):
        self._khong("1+1 bằng mấy", "viết code python sắp xếp mảng", "ai là chủ tịch nước", "giá vàng hôm nay", "kể chuyện cười đi")

    def test_hoi_thu_tuc_chung_co_chu_tour(self):
        """Câu hỏi thủ tục/chính sách chung có chữ 'tour' nhưng không tìm tour nào -> không kèm 5 thẻ tour ngẫu nhiên."""
        self._khong("đặt tour có cần đặt cọc không", "trẻ em đi tour tính giá thế nào", "tour có bao gồm vé máy bay không",
                    "tour có bảo hiểm không", "tổng đài tư vấn tour số mấy", "đi tour có cần hộ chiếu không")


# ================================================================ 8. TÍNH ĐÚNG CỦA MỌI THẺ TOUR TRẢ VỀ
CAU_MAU = [
    "tour Thái Lan", "tour Nhật", "tour Đà Nẵng", "tour miền Tây", "tour châu Âu", "tour dưới 10 triệu", "tour tầm 5-7tr", "tour trên 50 triệu",
    "tour tháng 12", "tour 3 ngày 2 đêm", "tour trong nước", "tour nước ngoài", "tour độc lạ", "tour đi biển", "tour cho gia đình",
    "Đà Nẵng hay Phú Quốc rẻ hơn", "tour Hàn Quốc tháng 12", "tour trong nước dưới 5 triệu", "mình muốn đi du lịch", "tour ít nhất 10 ngày",
]


class TinhDungCuaTheTour(Nen):
    def test_khong_trung_ten(self):
        for cau in CAU_MAU:
            with self.subTest(cau=cau):
                ten = [t["ten"] for t in tim(cau)]
                self.assertEqual(len(ten), len(set(ten)), f"“{cau}”: trùng thẻ tour")

    def test_khong_co_ngay_khoi_hanh_da_qua(self):
        for cau in CAU_MAU:
            with self.subTest(cau=cau):
                self.moi_tour(cau, tim(cau), lambda t: ngay(t) >= HOM_NAY, f"còn hạn (ngày khởi hành từ {HOM_NAY:%d/%m/%Y})")

    def test_khong_co_tour_het_cho(self):
        for cau in CAU_MAU:
            with self.subTest(cau=cau):
                self.moi_tour(cau, tim(cau), lambda t: int(t.get("so_cho_con", 0)) > 0, "còn chỗ")

    def test_so_the_tour_vua_phai(self):
        for cau in CAU_MAU:
            with self.subTest(cau=cau):
                self.assertLessEqual(len(tim(cau)), 10, f"“{cau}”: quá nhiều thẻ tour")

    def test_hoi_lich_khoi_hanh_liet_ke_ngay_khong_trung(self):
        cau = "tour Thái Lan có những ngày nào"
        tours = tim(cau)
        self.co_tour(cau, tours)
        self.moi_tour(cau, tours, lambda t: t["diem_den"] == "Thái Lan" and ngay(t) >= HOM_NAY, "là tour Thái còn hạn")
        cap = [(t["ten"], t["ngay_khoi_hanh"]) for t in tours]
        self.assertEqual(len(cap), len(set(cap)), "Trùng cùng tour cùng ngày")
        self.assertLessEqual(len(tours), 15, "Quá nhiều thẻ")

    def test_lich_khoi_hanh_cua_tour_nhieu_ngay(self):
        """Hỏi lịch một điểm đến chỉ có 1 tour nhiều ngày -> phải thấy nhiều hơn 1 ngày khởi hành."""
        for dd in CAC_DIEM_DEN:
            ten = {m["ten"] for m in TOAN_BO if m["diem_den"] == dd}
            if len(ten) == 1 and len(THEO_TEN[next(iter(ten))]) >= 2:
                cau = f"tour {dd} có những ngày khởi hành nào"
                tours = tim(cau)
                self.assertGreaterEqual(len({t["ngay_khoi_hanh"] for t in tours}), 2, f"“{cau}”:{tom(tours)}")
                return
        self.skipTest("Không có điểm đến nào chỉ 1 tour nhiều ngày khởi hành")


# ================================================================ 9. HỢP ĐỒNG THẺ TOUR (main.chuan_hoa_the_tour)
class HopDongTheTour(Nen):
    def setUp(self):
        super().setUp()
        self.the = [main.chuan_hoa_the_tour(m) for m in TOAN_BO]

    def test_du_truong_dung_ten(self):
        for t in self.the:
            self.assertEqual(set(t), set(TRUONG_HOP_DONG), t.get("ten"))

    def test_kieu_du_lieu(self):
        for t in self.the:
            with self.subTest(ten=t["ten"][:40], ngay=t["ngay_khoi_hanh"]):
                for k in ("tour_key", "id", "ten", "ngay_khoi_hanh", "url", "diem_den", "loai_hinh"):
                    self.assertIsInstance(t[k], str, k)
                    self.assertTrue(t[k].strip(), f"Trường {k} rỗng")
                self.assertIs(type(t["gia"]), int)
                self.assertGreater(t["gia"], 0)
                self.assertIs(type(t["so_ngay"]), int)
                self.assertGreaterEqual(t["so_ngay"], 1)
                self.assertIs(type(t["so_cho_con"]), int)
                self.assertGreaterEqual(t["so_cho_con"], 0)
                self.assertTrue(t["anh"] is None or isinstance(t["anh"], str))

    def test_ngay_khoi_hanh_dung_dinh_dang(self):
        for t in self.the:
            self.assertRegex(t["ngay_khoi_hanh"], r"^\d{4}-\d{2}-\d{2}$", t["ten"])
            date.fromisoformat(t["ngay_khoi_hanh"])

    def test_url_va_anh_hop_le(self):
        for t in self.the:
            with self.subTest(ten=t["ten"][:40]):
                self.assertRegex(t["url"], r"^https://benthanhtourist\.com/tour/[a-z0-9-]+$")
                if t["anh"] is not None:
                    self.assertRegex(t["anh"], r"^https://\S+\.(webp|jpg|jpeg|png)$")

    def test_tour_nao_cung_co_anh(self):
        thieu = sorted({t["ten"] for t in self.the if not t["anh"]})
        self.assertFalse(thieu, f"{len(thieu)} tour không có ảnh: {thieu[:5]}")

    def test_loai_hinh_chi_co_hai_gia_tri_va_khop_duong_dan_anh(self):
        """App nhận biết tour nước ngoài (bắt buộc hộ chiếu/visa) qua '/nuoc-ngoai/' trong đường dẫn ảnh."""
        for t in self.the:
            with self.subTest(ten=t["ten"][:40]):
                self.assertIn(t["loai_hinh"], ("Trong Nước", "Nước Ngoài"))
                if t["anh"]:
                    self.assertEqual("/nuoc-ngoai/" in t["anh"], t["loai_hinh"] == "Nước Ngoài", t["anh"])

    def test_id_khong_trung_va_tour_key_khop_ten(self):
        ids = [t["id"] for t in self.the]
        self.assertEqual(len(ids), len(set(ids)), "id (lượt khởi hành) bị trùng")
        key_cua_ten: dict[str, set] = {}
        ten_cua_key: dict[str, set] = {}
        for t in self.the:
            key_cua_ten.setdefault(t["ten"], set()).add(t["tour_key"])
            ten_cua_key.setdefault(t["tour_key"], set()).add(t["ten"])
        self.assertFalse({k: v for k, v in key_cua_ten.items() if len(v) > 1}, "Một tên tour có nhiều tour_key")
        self.assertFalse({k: v for k, v in ten_cua_key.items() if len(v) > 1}, "Một tour_key ứng nhiều tên tour")

    def test_cung_tour_khong_trung_ngay_khoi_hanh(self):
        for ten, rs in THEO_TEN.items():
            ngay_kh = [r["ngay_khoi_hanh"] for r in rs]
            self.assertEqual(len(ngay_kh), len(set(ngay_kh)), ten)

    def test_du_lieu_khong_con_luot_da_qua_hoac_het_cho(self):
        qua = sorted({f"{t['ten'][:40]} ({t['ngay_khoi_hanh']})" for t in self.the if t["ngay_khoi_hanh"] < HOM_NAY.isoformat()})
        self.assertFalse(qua, f"{len(qua)} lượt đã qua ngày khởi hành vẫn lọt qua rag.tat_ca_luot_con_han(): {qua[:5]}")
        het = sorted({f"{t['ten'][:40]} ({t['ngay_khoi_hanh']})" for t in self.the if t["so_cho_con"] <= 0})
        self.assertFalse(het, f"{len(het)} lượt hết chỗ vẫn nằm trong dữ liệu: {het[:5]}")

    def test_the_tra_ve_tu_tim_kiem_giu_nguyen_gia_tri(self):
        for cau in ["tour Thái Lan", "tour dưới 10 triệu", "tour tháng 12"]:
            for goc in tim(cau):
                the = main.chuan_hoa_the_tour(goc)
                for k in TRUONG_HOP_DONG:
                    self.assertEqual(the[k], goc[k], f"{cau}: trường {k} bị đổi khi chuẩn hoá")

    def test_the_thieu_truong_khong_lam_vo(self):
        the = main.chuan_hoa_the_tour({})
        self.assertEqual(set(the), set(TRUONG_HOP_DONG))
        self.assertIsNone(the["gia"])
        self.assertIsNone(the["anh"])
        self.assertIsNone(main.chuan_hoa_the_tour({"anh": "   "})["anh"])
        self.assertEqual(main.chuan_hoa_the_tour({"gia": "12990000"})["gia"], 12_990_000)
        self.assertIsNone(main.chuan_hoa_the_tour({"gia": "liên hệ"})["gia"])


if __name__ == "__main__":
    unittest.main()
