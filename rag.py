import re
from datetime import date, timedelta
from typing import Callable, NamedTuple
from itertools import combinations
import difflib
import statistics
import unicodedata
import chromadb
from config import CHROMA_PATH, CHROMA_COLLECTION
from rules import (
    TOP_K_TOURS, VUOT_NGAN_SACH_TOI_DA, TEN_TOUR_DOC_LA, ALIAS_DIEM_DEN, ALIAS_LOAI_TRU, DIA_DANH_PHO_BIEN,
    TU_KHOA_CAN_NHAN_VIEN, TU_KHOA_TIEN_HOP_DONG, TU_KHOA_DA_DAT, TU_KHOA_HOI_CHINH_SACH, TU_KHOA_Y_MUON, TU_KHOA_DANG_HOI,
    VUNG_DIEM_DEN, THE_LOAI_TOUR, TU_KHOA_TOUR_BIEN, DAU_HIEU_TOUR_BIEN,
)

_client = chromadb.PersistentClient(path=CHROMA_PATH)
_collection = _client.get_or_create_collection(CHROMA_COLLECTION)


def nap_lai_kho() -> None:
    """Gọi sau khi sync_tours.dong_bo() xoá rồi tạo lại kho tour: chatbot đang chạy phải lấy kho mới, kho cũ đã bị xoá."""
    global _collection
    _collection = _client.get_or_create_collection(CHROMA_COLLECTION)


# Chỉ gợi ý lượt khởi hành từ 3 ngày sau hôm nay trở đi (chủ dự án chốt 19/11/2026): sát ngày thì sale không kịp chốt, làm giấy tờ
# (bug thật: ngày 19/11 bot gợi ý tour Hồng Kông khởi hành chính ngày 19/11).
SO_NGAY_BAO_TRUOC_GOI_Y = 3


def ngay_som_nhat_goi_y() -> str:
    return (date.today() + timedelta(days=SO_NGAY_BAO_TRUOC_GOI_Y)).isoformat()


def _con_han(m: dict) -> bool:
    return str(m.get("ngay_khoi_hanh") or "")[:10] >= ngay_som_nhat_goi_y()


def tat_ca_luot_con_han() -> list[dict]:
    """Mọi lượt khởi hành từ SO_NGAY_BAO_TRUOC_GOI_Y ngày sau trở đi. Dữ liệu Chroma chỉ đổi khi chạy sync_tours.py nên phải lọc lúc
    đọc: lượt quá hạn tự ẩn, không cần đồng bộ lại (bug thật: thẻ tour ghi khởi hành 25/10 khi đã sang tháng 11)."""
    return [m for m in _collection.get()["metadatas"] if _con_han(m)]


def _so_sang_dong(so_viet: str, don_vi: str) -> int:
    so = so_viet.replace(",", ".")
    if don_vi and re.match(r"(triệu|trieu|tr|củ)$", don_vi, re.IGNORECASE):
        return int(float(so) * 1_000_000)
    return int(re.sub(r"[.,]", "", so_viet))


def trich_thang_khoi_hanh(cau_hoi: str) -> int | None:
    """Nhận diện khách hỏi theo THÁNG khởi hành cụ thể ("tháng 12", "tháng
    3 năm sau") — bug thật gặp phải: câu "có tour nào khởi hành tháng 12
    không" rơi vào vector search vì không có nhánh lọc riêng, trả về cả tour
    tháng 11, tháng 2 (không phải tháng 12) do vector search chỉ hiểu "tour"
    là từ khoá chính, không hiểu được ràng buộc thời gian chính xác."""
    m = re.search(r"tháng\s*(\d{1,2})|thang\s*(\d{1,2})|(?<!\w)t(\d{1,2})(?!\w)", cau_hoi, re.IGNORECASE)
    if not m:
        return None
    thang = int(m.group(1) or m.group(2) or m.group(3))
    return thang if 1 <= thang <= 12 else None


def trich_khoang_ngan_sach(cau_hoi: str) -> tuple[int, int] | None:
    """Khách nêu RÕ 2 đầu khoảng — "từ 8 triệu đến 12 triệu", "8tr-12tr",
    "khoảng 8-12 triệu". Phải kiểm tra TRƯỚC trich_ngan_sach(), nếu không
    regex số đơn lẻ sẽ bắt nhầm số đầu tiên (8tr) làm tâm rồi cộng lệch
    ±2tr sai hẳn hướng khách muốn (khách nói rõ 2 đầu, không cần đoán thêm)."""
    m = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(triệu|trieu|tr)?\s*(?:-|đến|den|~|tới|toi)\s*"
        r"(\d+(?:[.,]\d+)?)\s*(triệu|trieu|tr\b|đ\b|d\b|vnd|vnđ|đồng|dong\b)",
        cau_hoi, re.IGNORECASE,
    )
    if not m:
        return None
    so1, dv1, so2, dv2 = m.groups()
    # Đơn vị chỉ ghi ở số thứ 2 ("từ 8 đến 12 triệu") -> áp dụng cho cả 2 đầu
    dv1 = dv1 or dv2
    can_duoi = _so_sang_dong(so1, dv1)
    can_tren = _so_sang_dong(so2, dv2)
    if can_duoi > can_tren:
        can_duoi, can_tren = can_tren, can_duoi
    return can_duoi, can_tren


# Nhận diện khách nêu con số TIỀN làm MỨC SÀN ("trên 50 triệu", "tối thiểu
# 20tr", "sang chảnh hơn 30 triệu") thay vì mức TRẦN mặc định (xem lý do mặc
# định ở VUOT_NGAN_SACH_TOI_DA/tim_tour_theo_ngan_sach) — bug thật gặp phải:
# "trên 50 triệu" bị hiểu nhầm thành ngân sách TỐI ĐA 50tr, trả về tour rẻ
# (27tr, 29tr) thay vì tour ĐẮT HƠN 50tr như khách thật sự muốn.
#
# QUAN TRỌNG: cụm "ít nhất"/"tối thiểu"/"trở lên" cũng dùng để mô tả SỐ NGÀY
# tour (xem trich_dieu_kien_so_ngay) — nếu chỉ tìm cụm từ này ở BẤT KỲ ĐÂU
# trong câu (không neo vào đơn vị tiền), câu "dưới 10 triệu, ít nhất 5 ngày"
# sẽ bị bắt nhầm "ít nhất" thuộc về ngân sách, ghi đè luôn ý "dưới 10 triệu"
# (bug thật gặp phải khi thêm tính năng lọc số ngày). Bắt buộc cụm mức sàn
# phải đứng NGAY TRƯỚC 1 con số + đơn vị tiền (triệu/tr/đồng/vnd...), không
# đứng trước "ngày/đêm".
_MAU_MUC_SAN = re.compile(
    r"(trên|tren|từ|tu|tối thiểu|toi thieu|ít nhất|it nhat|trở lên|tro len|"
    r"sang (chảnh|trọng)|cao cấp|cao cap|hạng sang|hang sang|luxury)"
    r"\s*\d*\s*"
    r"(triệu|trieu|tr\b|đồng|dong\b|vnd|vnđ|đ\b|d\b)",
    re.IGNORECASE,
)


def hoi_muc_san_ngan_sach(cau_hoi: str) -> bool:
    return bool(_MAU_MUC_SAN.search(cau_hoi.lower()))


def trich_ngan_sach(cau_hoi: str) -> int | None:
    # Dạng "2 triệu" / "2tr" — số nhỏ, nhân lên thành đồng (kể cả gõ không dấu "2 trieu").
    # Nhận cả số lẻ "7,5 triệu" / "7.5tr" — bug thật: chỉ bắt (\d+) nên "dưới 7,5 triệu" bị hiểu thành 5 triệu.
    # "7tr5" = 7,5 triệu (cách viết tắt rất hay gặp)
    m = re.search(r"(\d+)\s*(?:triệu|trieu|tr)(\d)(?!\d)", cau_hoi, re.IGNORECASE)
    if m:
        return int(float(f"{m.group(1)}.{m.group(2)}") * 1_000_000)
    # "củ" = triệu (khách miền Nam nói "15 củ")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(triệu|trieu|tr\b|củ(?!\w))", cau_hoi, re.IGNORECASE)
    if m:
        return _so_sang_dong(m.group(1), m.group(2))

    # Dạng số đầy đủ viết liền hoặc có dấu chấm phân cách: "2000000đ", "2.000.000 đồng",
    # kể cả gõ không dấu "2000000d", "2000000 dong" (phổ biến khi gõ nhanh trên điện thoại)
    m = re.search(r"(\d[\d.,]*\d|\d)\s*(đ\b|d\b|vnd|vnđ|đồng|dong\b)", cau_hoi, re.IGNORECASE)
    if m:
        so = re.sub(r"[.,]", "", m.group(1))
        if so.isdigit():
            return int(so)

    return None


# Nhận diện khách đang ĐIỀU CHỈNH TƯƠNG ĐỐI ngân sách đã hỏi ở lượt trước
# ("giảm nữa đi", "rẻ hơn nữa", "tăng lên", "đắt hơn chút") thay vì nêu số
# tuyệt đối mới — bug thật gặp phải: sau khi hỏi "tour dưới 10 triệu" rồi hỏi
# tiếp "giảm nửa đi", trich_ngan_sach() không tìm được số nào trong câu này
# (không có "5 triệu"/"10tr" viết ra), nên tim_tour_lien_quan() rơi vào nhánh
# hoi_lien_quan_tour() → không đủ từ khoá tour → trả về RỖNG, dù AI vẫn còn
# nguyên lịch sử hội thoại trong prompt và "biết" khách vừa hỏi 10 triệu —
# AI không được dặn tự tính lại con số, nên chỉ nói "cho mình biết ngân sách
# cụ thể" dù đáng lẽ tự suy ra được.
#
# QUAN TRỌNG: "giảm NỬA đi" (chia đôi, có mốc tỉ lệ RÕ RÀNG là 1/2) và "giảm
# NỮA đi" (tiếp tục giảm thêm, KHÔNG nói rõ bao nhiêu — "nữa" chỉ là trạng từ
# tiếp diễn, không phải con số) là 2 CÂU KHÁC NGHĨA dù chỉ khác 1 dấu — lỗi
# thật gặp phải khi thiết kế: gộp chung 1 regex rồi áp cùng tỉ lệ 50% cho cả
# hai, khiến "giảm nữa đi" bị tính sai thành chia đôi dù khách không hề có ý
# đó. Tách riêng 2 nhóm regex: nhóm "NỬA" (or "một nửa", "phân nửa") dùng tỉ
# lệ CHÍNH XÁC 50%; nhóm còn lại (không kèm "nửa" — "giảm nữa", "rẻ hơn",
# "tăng lên"...) không có mốc tỉ lệ nào trong câu, dùng mức nhẹ hơn hẳn (25%)
# để tránh đoán quá tay — 1 lần "giảm nữa" hợp lý là hạ thấp hơn 1 chút, không
# phải đứt gãy hẳn 1 nửa.
_MAU_GIAM_MOT_NUA = re.compile(
    r"(giảm|giam|hạ|ha)\s*(một\s*)?nửa|(giảm|giam|hạ|ha)\s*(mot\s*)?nua|"
    r"phân nửa|phan nua",
    re.IGNORECASE,
)
_MAU_TANG_GAP_DOI = re.compile(
    r"(tăng|tang|nhân|nhan)\s*(lên\s*)?(gấp\s*)?đôi|(tang|nhan)\s*(len\s*)?(gap\s*)?doi",
    re.IGNORECASE,
)

_MAU_GIAM_NHE = re.compile(
    r"giảm (nữa|thêm)?|giam (nua|them)?|rẻ hơn|re hon|thấp hơn|thap hon|"
    r"hạ (xuống|gia)|ha (xuong|gia)|bớt (chút|xíu|tí)|bot (chut|xiu|ti)|"
    r"rẻ (nữa\s*)?đi|re (nua\s*)?di|thấp (nữa\s*)?đi|thap (nua\s*)?di|"
    r"ít (nữa\s*)?đi|it (nua\s*)?di|ít hơn|it hon",
    re.IGNORECASE,
)
_MAU_TANG_NHE = re.compile(
    r"tăng (nữa|lên|thêm)?|tang (nua|len|them)?|đắt hơn|dat hon|cao hơn|cao hon|"
    r"sang (hơn|hon)|nâng (lên|len)|nang len|hơn (nữa\s*)?đi|hon (nua\s*)?di|"
    r"nhiều hơn|nhieu hon|mắc hơn|mac hon",
    re.IGNORECASE,
)

_TI_LE_CHIA_DOI = 0.5  # "giảm/tăng một nửa", "gấp đôi" — có mốc rõ ràng
_TI_LE_DIEU_CHINH_NHE = 0.25  # "giảm/tăng nữa", "rẻ/đắt hơn" — không có mốc, hạ thấp mức đoán


def trich_ngan_sach_tu_lich_su(lich_su: list[dict]) -> int | None:
    """Tìm lại con số ngân sách GẦN NHẤT khách từng nêu trong lịch sử hội
    thoại (chỉ xét tin nhắn role="user", duyệt từ MỚI NHẤT về cũ) — dùng làm
    "mốc" để tính điều chỉnh tương đối. Tái dùng trich_ngan_sach()/
    trich_khoang_ngan_sach() đã có, không viết lại logic trích số."""
    for tin in reversed(lich_su):
        if tin["role"] != "user":
            continue
        khoang = trich_khoang_ngan_sach(tin["content"])
        if khoang:
            return khoang[1]  # lấy cận trên của khoảng làm mốc
        so = trich_ngan_sach(tin["content"])
        if so is not None:
            return so
    return None


def trich_dieu_chinh_ngan_sach(cau_hoi: str, lich_su: list[dict]) -> int | None:
    """Trả về ngân sách MỚI đã tính lại nếu câu hỏi là điều chỉnh tương đối
    dựa trên ngân sách đã hỏi ở lượt trước, None nếu không áp dụng được (câu
    không phải điều chỉnh tương đối, hoặc không tìm được mốc ngân sách nào
    trong lịch sử để tính). Nếu câu hỏi TỰ nó đã có số tuyệt đối ("giảm
    xuống còn 5 triệu") thì không cần hàm này — trich_ngan_sach() ở nhánh
    gọi trước đã xử lý đúng rồi, hàm này CHỈ xử lý phần "không có số cụ thể".
    Kiểm tra nhóm "có mốc rõ" (nửa/gấp đôi) TRƯỚC nhóm "chung chung" — 1 câu
    như "giảm một nửa" khớp cả 2 nhóm regex nếu không ưu tiên đúng thứ tự."""
    if trich_ngan_sach(cau_hoi) is not None or trich_khoang_ngan_sach(cau_hoi):
        return None  # câu đã tự nêu số tuyệt đối, không cần suy từ lịch sử

    cau_hoi_thuong = cau_hoi.lower()

    if _MAU_GIAM_MOT_NUA.search(cau_hoi_thuong):
        # "Giảm một nửa" = còn ĐÚNG 1/2 mức cũ -> nhân 0.5 (không phải "giảm
        # thêm 50% của phần chênh lệch" — không có phần chênh lệch nào ở đây).
        ngan_sach_cu = trich_ngan_sach_tu_lich_su(lich_su)
        return int(ngan_sach_cu * _TI_LE_CHIA_DOI) if ngan_sach_cu is not None else None
    if _MAU_TANG_GAP_DOI.search(cau_hoi_thuong):
        # "Tăng gấp đôi" = thành ĐÚNG 2 LẦN mức cũ -> nhân 2 (1 / 0.5), khác
        # hẳn công thức "cộng thêm 1 tỉ lệ" dùng cho nhóm điều chỉnh nhẹ bên
        # dưới — bug thật gặp phải khi lần đầu viết: dùng nhầm công thức
        # "1 + 0.5" (tăng thêm 50%) cho câu "gấp đôi", ra kết quả 1.5x thay vì
        # đúng 2x khách yêu cầu.
        ngan_sach_cu = trich_ngan_sach_tu_lich_su(lich_su)
        return int(ngan_sach_cu / _TI_LE_CHIA_DOI) if ngan_sach_cu is not None else None

    muon_giam = bool(_MAU_GIAM_NHE.search(cau_hoi_thuong))
    muon_tang = bool(_MAU_TANG_NHE.search(cau_hoi_thuong))
    if not muon_giam and not muon_tang:
        return None

    ngan_sach_cu = trich_ngan_sach_tu_lich_su(lich_su)
    if ngan_sach_cu is None:
        return None

    if muon_giam:
        return int(ngan_sach_cu * (1 - _TI_LE_DIEU_CHINH_NHE))
    return int(ngan_sach_cu * (1 + _TI_LE_DIEU_CHINH_NHE))


def _nguon(nguon: list[dict] | None) -> list[dict]:
    """Nguồn dữ liệu để lọc giá: mặc định toàn bộ ChromaDB; có thể là tập đã lọc sẵn theo điểm đến / loại hình /
    tháng / số ngày (xem tim_tour_lien_quan) — điều kiện giá luôn áp lên đúng tập đó."""
    return tat_ca_luot_con_han() if nguon is None else nguon


def tim_tour_trong_khoang(can_duoi: int, can_tren: int, top_k: int, nguon: list[dict] | None = None) -> list[dict]:
    """Khách đã nêu rõ 2 đầu khoảng -> lọc ĐÚNG khoảng đó."""
    ung_vien = [meta for meta in _nguon(nguon) if can_duoi <= meta["gia"] <= can_tren]
    ung_vien.sort(key=lambda meta: meta["gia"])
    # Lọc giá TRƯỚC rồi mới dedup theo tên: mỗi lượt khởi hành là 1 record riêng (xem sync_tours.py) với giá khác
    # nhau; dedup trước sẽ giữ lượt sớm nhất (có thể ngoài khoảng giá) rồi loại mất cả tour dù lượt khác đạt.
    return _dedup_theo_ten(ung_vien)[:top_k]


def tim_tour_theo_ngan_sach(ngan_sach: int, top_k: int, nguon: list[dict] | None = None) -> list[dict]:
    """Ưu tiên tour GẦN ngân sách nhất trước (rẻ hơn, xét từ dưới lên —
    không nhảy thẳng xuống tour rẻ nhất toàn bộ dữ liệu như bản trước), rồi
    LUÔN dành đúng 1 suất cuối cho tour vượt nhẹ (ngân sách, ngân sách +
    VUOT_NGAN_SACH_TOI_DA] nếu có — vì giá tour thật gồm thuế/phí lẻ nên
    tour sát ngân sách (VD 10tr290 cho ngân sách 10tr) gần như chắc chắn
    đáng giới thiệu, không nên bỏ qua chỉ vì nhỉnh hơn vài trăm nghìn. Chỉ
    khi không đủ tour rẻ hơn mới cần "giảm sâu" xuống các tour rẻ hơn nữa.
    Lọc trên TOÀN BỘ dữ liệu (không qua vector search) vì đây là điều kiện
    số học cần đúng 100%, không phải điều kiện ngữ nghĩa."""
    # Lọc giá TRƯỚC, dedup theo tên SAU (cùng lý do ở tim_tour_trong_khoang) — mỗi tên chỉ còn 1 lượt, nên 1 tour
    # không chiếm nhiều vị trí liền kề trong danh sách sort theo giá.
    trong_tam = _dedup_theo_ten([m for m in _nguon(nguon) if m["gia"] <= ngan_sach + VUOT_NGAN_SACH_TOI_DA])
    re_hon = sorted((m for m in trong_tam if m["gia"] <= ngan_sach), key=lambda m: m["gia"], reverse=True)  # gần ngân sách nhất trước
    vuot_nhe = sorted((m for m in trong_tam if m["gia"] > ngan_sach), key=lambda m: m["gia"])

    so_suat_vuot_nhe = 1 if vuot_nhe else 0
    ung_vien = re_hon[: top_k - so_suat_vuot_nhe] + vuot_nhe[:so_suat_vuot_nhe]
    ung_vien.sort(key=lambda m: m["gia"])
    return ung_vien[:top_k]


def tim_tour_tren_ngan_sach(muc_san: int, top_k: int, nguon: list[dict] | None = None) -> list[dict]:
    """Đối xứng với tim_tour_theo_ngan_sach() nhưng cho trường hợp khách nêu
    MỨC SÀN TƯỜNG MINH ("trên X", "tối thiểu X", "sang chảnh hơn X") — lấy
    tour ĐẮT HƠN hoặc bằng muc_san, ưu tiên GẦN mức sàn nhất trước (rẻ nhất
    trong nhóm đạt yêu cầu, thay vì nhảy thẳng lên tour đắt nhất toàn bộ dữ
    liệu). Chỉ dùng khi khách tự nêu số cụ thể làm mốc sàn — với điều chỉnh
    NHẸ suy từ lịch sử ("cao hơn chút"), dùng tim_tour_cao_hon_ngan_sach_goc()
    thay vì hàm này (xem lý do ở đó)."""
    toan_bo = _dedup_theo_ten([m for m in _nguon(nguon) if m["gia"] >= muc_san])
    return sorted(toan_bo, key=lambda m: m["gia"])[:top_k]  # gần mức sàn nhất trước


def tim_tour_cao_hon_ngan_sach_goc(ngan_sach_goc: int, top_k: int, nguon: list[dict] | None = None) -> list[dict]:
    """Dành riêng cho điều chỉnh NHẸ, KHÔNG rõ mốc ("cao hơn chút", "hơn đi",
    "hơn nữa đi" — nhóm _MAU_TANG_NHE) khi ngan_sach_goc lấy từ lịch sử hội
    thoại. Bug thật gặp phải với cách làm cũ: tính mức sàn cứng = ngan_sach_goc
    * 1.25 rồi lọc "giá >= mức sàn" — với ngân sách gốc 30tr, mức sàn 37.5tr
    LOẠI MẤT chính 2 tour 32.99tr/33.99tr là các tour "cao hơn chút" ĐÚNG Ý
    khách nhất (nằm giữa 30tr và 37.5tr), trong khi khách chỉ muốn xem tour
    nhỉnh hơn ngân sách cũ, không hề đặt ngưỡng +25% làm mốc sàn phải đạt.
    Nên KHÔNG ép ngưỡng nào — chỉ lấy toàn bộ tour giá > ngan_sach_goc, ưu
    tiên GẦN ngan_sach_goc nhất trước (đúng nghĩa "cao hơn chút")."""
    toan_bo = _dedup_theo_ten([m for m in _nguon(nguon) if m["gia"] > ngan_sach_goc])
    return sorted(toan_bo, key=lambda m: m["gia"])[:top_k]  # gần ngân sách gốc nhất trước


def tim_tour_thap_hon_ngan_sach_goc(ngan_sach_goc: int, top_k: int, nguon: list[dict] | None = None) -> list[dict]:
    """Đối xứng với tim_tour_cao_hon_ngan_sach_goc() cho điều chỉnh NHẸ,
    KHÔNG rõ mốc theo hướng GIẢM ("thấp hơn chút", "rẻ hơn đi", "rẻ nữa đi" —
    nhóm _MAU_GIAM_NHE). Cùng bug với chiều tăng: nhân ngan_sach_goc * 0.75
    rồi lọc "giá <= mức đó" có thể bỏ sót tour NẰM GIỮA ngân sách gốc và mức
    đã nhân (VD gốc 21tr, mức 0.75 = 15.75tr, trong khi tour 20.99tr mới là
    "thấp hơn chút" đúng ý khách nhất lại bị loại vì lớn hơn 15.75tr). Nên
    KHÔNG ép ngưỡng nhân tỉ lệ — chỉ lấy toàn bộ tour giá < ngan_sach_goc, ưu
    tiên GẦN ngan_sach_goc nhất trước."""
    toan_bo = _dedup_theo_ten([m for m in _nguon(nguon) if m["gia"] < ngan_sach_goc])
    return sorted(toan_bo, key=lambda m: m["gia"], reverse=True)[:top_k]  # gần ngân sách gốc nhất trước


def tim_tour_doc_la() -> list[dict]:
    """Không nhận/áp dụng top_k — nhóm tour độc lạ đã cố định 10 tour (không
    phụ thuộc TOP_K_TOURS chung, luôn hiển thị đủ danh sách đã đối chiếu thật)."""
    toan_bo = tat_ca_luot_con_han()
    tours = [m for m in toan_bo if m["ten"] in TEN_TOUR_DOC_LA]
    return _dedup_theo_ten(tours)


def loc_theo_thang(tours: list[dict], thang: int) -> list[dict]:
    """Mỗi record là 1 LƯỢT khởi hành riêng (xem sync_tours.py) nên chỉ cần
    so khớp trực tiếp tháng trong "ngay_khoi_hanh" (format "YYYY-MM-DD")."""
    return [t for t in tours if t["ngay_khoi_hanh"][5:7] == f"{thang:02d}"]


def _so_ngay_giua() -> float:
    """Trung vị số ngày của các tour (mỗi tên tour tính một lần)."""
    theo_ten = {m["ten"]: m["so_ngay"] for m in tat_ca_luot_con_han()}
    return statistics.median(theo_ten.values()) if theo_ten else 4


def trich_dieu_kien_so_ngay(cau_hoi: str) -> tuple[str, int] | None:
    """Nhận diện điều kiện về SỐ NGÀY tour ("ít nhất 7 ngày", "dưới 5 ngày",
    "trên 10 ngày", đúng "3 ngày 2 đêm") — bug thật gặp phải: câu "ít nhất
    7 ngày" rơi vào vector search, trả về cả tour 4 ngày (không đạt điều
    kiện) vì vector search không đảm bảo lọc số học chính xác 100%. Trả về
    (toan_tu, so_ngay) với toan_tu là ">=" (tối thiểu/trở lên), "<=" (tối đa/
    dưới), hoặc "==" (đúng N ngày, khi khách nêu rõ dạng "N ngày M đêm")."""
    cau_hoi_thuong = cau_hoi.lower()
    # "đặt trước 10 ngày", "sớm 7 ngày", "cách 3 ngày" là khoảng thời gian, không phải số ngày của tour (bug thật: bị hiểu là "tour 10 ngày").
    cau_hoi_thuong = re.sub(r"(trước|truoc|sớm|som|cách|cach)\s*\d+\s*ngày", " ", cau_hoi_thuong)

    # "3n2d", "4N3Đ" (viết tắt ngày-đêm) và "đi trong ngày" (= 1 ngày)
    m = re.search(r"(?<!\w)(\d{1,2})\s*n\s*\d{1,2}\s*[dđ](?!\w)", cau_hoi_thuong)
    if m:
        return "==", int(m.group(1))
    if re.search(r"(?<!\w)(trong ngày|trong ngay)(?!\w)", cau_hoi_thuong):
        return "==", 1
    # "ngắn ngày" / "dài ngày" không có con số -> so với mức giữa (trung vị) số ngày của các tour đang có
    if re.search(r"(?<!\w)(ngắn ngày|ngan ngay)(?!\w)", cau_hoi_thuong):
        return "<=", _so_ngay_giua()
    if re.search(r"(?<!\w)(dài ngày|dai ngay)(?!\w)", cau_hoi_thuong):
        return ">=", _so_ngay_giua()

    # Dạng "X ngày Y đêm" -> khách nêu ĐÚNG số ngày cụ thể của 1 tour
    m = re.search(r"(\d+)\s*ngày\s*\d+\s*đêm|(\d+)\s*ngay\s*\d+\s*dem", cau_hoi_thuong)
    if m:
        return "==", int(m.group(1) or m.group(2))

    m = re.search(r"(ít nhất|it nhat|tối thiểu|toi thieu|trên|tren|trở lên|tro len).{0,10}?(\d+)\s*ngày|"
                  r"(\d+)\s*ngày.{0,10}?(trở lên|tro len)", cau_hoi_thuong)
    if m:
        so = m.group(2) or m.group(3)
        return ">=", int(so)

    m = re.search(r"(dưới|duoi|tối đa|toi da|không quá|khong qua|ít hơn|it hon).{0,10}?(\d+)\s*ngày", cau_hoi_thuong)
    if m:
        return "<=", int(m.group(2))

    # Chỉ nói "tour 5 ngày" (không kèm đêm) -> đúng 5 ngày. "ngày 29/11" (ngày đứng TRƯỚC số) không phải số ngày tour.
    m = re.search(r"(?<![\d/])(\d{1,2})\s*(?:ngày|ngay)(?!\s*\d)(?!\w)", cau_hoi_thuong)
    if m:
        return "==", int(m.group(1))

    return None


# Đuôi loại trừ: "tour 3-4 ngày", "đi 5-10 triệu", "2-3 người" là số ngày / giá / số khách, không phải ngày tháng.
_MAU_NGAY_CU_THE = re.compile(
    r"(?:ngày|ngay|khởi hành|khoi hanh|đi|di|vào|vao|tour|dịp|dip)\s*(\d{1,2})\s*(?:/|-|tháng|thang)\s*(\d{1,2})(?!\d)"
    r"(?!\s*(?:ngày|ngay|đêm|dem|người|nguoi|khách|khach|triệu|trieu|tr\b|củ|cu\b|/))",
    re.IGNORECASE,
)

_MAU_NGAY_DI_SAT = re.compile(
    r"(?<!\w)(?:ngày|ngay|khởi hành|khoi hanh|đi|di|vào|vao|tour)\s*(\d{1,2})\s*(?:/|-|\.|tháng|thang)\s*(\d{1,2})(?!\d)"
    r"(?!\s*(?:ngày|ngay|đêm|dem|người|nguoi|khách|khach|triệu|trieu|tr\b|củ|cu\b|/|\.\d|-\d))",
    re.IGNORECASE,
)
_MAU_NGAY_MAI = re.compile(r"\b(?:di|khoi hanh|xuat phat)\b.{0,12}\b(?:ngay mai|ngay mot|ngay kia|sang mai)\b|\b(?:ngay mai|ngay mot|ngay kia)\b.{0,12}\b(?:di|khoi hanh|xuat phat)\b")


def hoi_ngay_khoi_hanh_sat(cau_hoi: str, hom_nay: date | None = None) -> bool:
    """Khách nêu ngày đi cụ thể mà còn dưới SO_NGAY_BAO_TRUOC_GOI_Y ngày nữa là tới ("đi 21/11" khi hôm nay 19/11, "đi ngày mai"). Chatbot
    đã ẩn tour sát ngày nên không thể trả lời đúng; chủ dự án chốt (2026-11-19): báo nhân viên kiểm tra chỗ, không gợi ý tour khác.
    Chỉ tính ngày đi (có chữ "đi", "ngày", "khởi hành"...), không tính "dịp 20/11" hay "tour 4-5 ngày"."""
    hom_nay = hom_nay or date.today()
    moc = hom_nay + timedelta(days=SO_NGAY_BAO_TRUOC_GOI_Y)
    c = unicodedata.normalize("NFC", cau_hoi).lower()
    if _MAU_NGAY_MAI.search(bo_dau(c)):
        return True
    for mm in _MAU_NGAY_DI_SAT.finditer(c):
        ngay_, thang_ = int(mm.group(1)), int(mm.group(2))
        for nam in (hom_nay.year, hom_nay.year + 1):
            try:
                d = date(nam, thang_, ngay_)
            except ValueError:
                continue
            if hom_nay <= d < moc:
                return True
    return False


# Ngày dương của lễ tính theo lịch âm. Hết năm thì thêm năm mới vào đây; năm chưa có thì chỉ còn khớp theo tên tour.
_MUNG_1_TET_AM = {2027: date(2027, 2, 6), 2028: date(2028, 1, 26)}
_TRUNG_THU = {2027: date(2027, 9, 15), 2028: date(2028, 10, 3)}
_GIO_TO = {2027: date(2027, 4, 16), 2028: date(2028, 4, 4)}


def _co_dinh(thang: int, ngay_: int, thang_cuoi: int | None = None, ngay_cuoi: int | None = None):
    return lambda nam: [(date(nam, thang, ngay_), date(nam, thang_cuoi or thang, ngay_cuoi or ngay_))]


def _mot_ngay_am(bang: dict[int, date]):
    return lambda nam: [(bang[nam], bang[nam])] if nam in bang else []


def _ngay_tet_am(nam: int) -> list[tuple[date, date]]:
    if nam not in _MUNG_1_TET_AM:
        return []
    mung_1 = _MUNG_1_TET_AM[nam]
    return [(mung_1 - timedelta(days=2), mung_1 + timedelta(days=4))]


def _ngay_tet_duong(nam: int) -> list[tuple[date, date]]:
    return [(date(nam, 12, 31), date(nam, 12, 31)), (date(nam, 1, 1), date(nam, 1, 1))]


_ngay_noel = _co_dinh(12, 24, 12, 25)
_ngay_30_4 = _co_dinh(4, 30, 5, 1)
_ngay_2_9 = _co_dinh(9, 1, 9, 2)


def _rx_ngay(ngay_: int, thang: int) -> str:
    """"tour 8/3", "dịp 20-11", "lễ 2 tháng 9" là nói tới DỊP; còn "ngày 8/3", "đi 8/3" vẫn là đúng ngày khởi hành."""
    return rf"\b(?:tour|dip|le|nghi)\s+(?:ngay\s+)?{ngay_}\s*(?:/|-|thang)\s*{thang}(?![\d/])"


class DipLe(NamedTuple):
    mo_ta: str
    mau: str  # so trên câu đã bỏ dấu, viết thường
    tu_trong_ten: str  # regex tìm trong tên tour đã bỏ dấu
    cac_khoang: Callable[[int], list[tuple[date, date]]]  # năm -> các khoảng ngày của dịp đó


# Thứ tự quan trọng: dịp cụ thể phải đứng trước "Tết" chung và "dịp lễ" chung.
_CAC_DIP_LE = (
    DipLe(
        "vào dịp Tết Âm lịch",
        r"\btet\b.*\bam lich\b|\btet (am|ta|nguyen dan|co truyen)\b|\bnguyen dan\b",
        r"tet am lich|tet nguyen dan",
        _ngay_tet_am,
    ),
    DipLe(
        "vào dịp Tết Dương lịch",
        r"\btet\b.*\bduong lich\b|\btet (duong|dl)\b|\btet tay\b(?! (ninh|nguyen|bac|nam|au|tang))|\bnam moi\b|\bcountdown\b|" + _rx_ngay(1, 1),
        r"tet duong lich|nam moi",
        _ngay_tet_duong,
    ),
    DipLe(
        "vào dịp Tết",
        r"\btet\b",
        r"tet",
        lambda nam: _ngay_tet_duong(nam) + _ngay_tet_am(nam),
    ),
    DipLe("vào dịp Noel", r"\b(noel|noen|no en|giang sinh|christmas|xmas)\b", r"noel|giang sinh", _ngay_noel),
    DipLe(
        "vào dịp lễ 30/4",
        r"(?<![\w/])30\s*/\s*4(?![\d/])|" + _rx_ngay(30, 4) + "|" + _rx_ngay(1, 5) + r"|\bquoc te lao dong\b",
        r"30[/-]4",
        _ngay_30_4,
    ),
    DipLe("vào dịp lễ 2/9", r"\bquoc khanh\b|" + _rx_ngay(2, 9), r"2[/-]9|quoc khanh", _ngay_2_9),
    DipLe("vào dịp Giỗ Tổ", r"\bgio to\b", r"gio to", _mot_ngay_am(_GIO_TO)),
    DipLe("vào dịp Trung Thu", r"\btrung thu\b", r"trung thu", _mot_ngay_am(_TRUNG_THU)),
    DipLe("vào dịp Valentine", r"\bvalentine\b|\ble tinh nhan\b|" + _rx_ngay(14, 2), r"valentine|tinh nhan", _co_dinh(2, 14)),
    DipLe("vào dịp 8/3", r"\bquoc te phu nu\b|" + _rx_ngay(8, 3), r"8[/-]3", _co_dinh(3, 8)),
    DipLe("vào dịp 20/10", r"\bphu nu viet nam\b|" + _rx_ngay(20, 10), r"20[/-]10", _co_dinh(10, 20)),
    DipLe("vào dịp 20/11", r"\bnha giao\b|" + _rx_ngay(20, 11), r"20[/-]11", _co_dinh(11, 20)),
    DipLe(
        "vào dịp lễ",
        r"\b(dip le|ngay le|mua le|nghi le|ky nghi le)\b",
        r"noel|giang sinh|tet|nam moi",
        lambda nam: _ngay_noel(nam) + _ngay_tet_duong(nam) + _ngay_tet_am(nam) + _ngay_30_4(nam) + _ngay_2_9(nam),
    ),
)


def trich_dip_le(cau_hoi: str) -> DipLe | None:
    kd = bo_dau(unicodedata.normalize("NFC", cau_hoi).lower())
    return next((dip for dip in _CAC_DIP_LE if re.search(dip.mau, kd)), None)


def tour_dung_ten_dip(m: dict, dip: DipLe) -> bool:
    return re.search(rf"\b(?:{dip.tu_trong_ten})\b", bo_dau(m["ten"].lower())) is not None


def tour_trung_ngay_dip(m: dict, dip: DipLe) -> bool:
    """Tour TRÙNG dịp khi khoảng ngày đi (khởi hành -> hết tour) chạm ngày lễ, không chỉ khởi hành gần ngày đó:
    tour 15/12 đi 3 ngày đã về trước Noel, còn tour 20/12 đi 14 ngày thì khách đón Noel ngay trên tour."""
    bat_dau = date.fromisoformat(m["ngay_khoi_hanh"][:10])
    try:
        so_ngay = max(int(m.get("so_ngay") or 1), 1)
    except (ValueError, TypeError):
        so_ngay = 1
    ket_thuc = bat_dau + timedelta(days=so_ngay - 1)
    return any(
        tu <= ket_thuc and bat_dau <= den
        for nam in range(bat_dau.year, ket_thuc.year + 1)
        for tu, den in dip.cac_khoang(nam)
    )


def trich_bo_loc_ngay(cau_hoi: str, hom_nay: date | None = None):
    """Nhận diện khách hỏi theo DỊP/KHOẢNG NGÀY: Tết, Noel, hè, lễ 30/4, 2/9, "cuối tuần này", "tuần sau", "ngày 29/11".
    Trả về hàm nhận 1 record tour -> True/False, hoặc None nếu câu không nói tới dịp nào. "Tháng N" thuần túy do
    trich_thang_khoi_hanh() lo. Ngày trong dữ liệu là ngày thật (YYYY-MM-DD); dịp lễ so theo tháng-ngày, không theo năm."""
    hom_nay = hom_nay or date.today()
    c = unicodedata.normalize("NFC", cau_hoi).lower()
    kd = bo_dau(c)

    def md(m: dict) -> tuple[int, int]:
        return int(m["ngay_khoi_hanh"][5:7]), int(m["ngay_khoi_hanh"][8:10])

    dip = trich_dip_le(cau_hoi)
    if dip:
        return lambda m: tour_dung_ten_dip(m, dip) or tour_trung_ngay_dip(m, dip)
    if re.search(r"(?<!\w)(mùa hè|mua he|hè|he)(?!\w)", c) and ("mùa hè" in c or "hè" in c):
        return lambda m: 5 <= md(m)[0] <= 8
    if re.search(r"(?<!\w)(cuối tuần|cuoi tuan)\s+(này|nay|tới|toi)(?!\w)", c):
        chu_nhat = hom_nay + timedelta(days=6 - hom_nay.weekday())
        return lambda m: hom_nay <= date.fromisoformat(m["ngay_khoi_hanh"]) <= chu_nhat
    if re.search(r"(?<!\w)(tuần sau|tuan sau|tuần tới|tuan toi)(?!\w)", c):
        thu_hai = hom_nay + timedelta(days=7 - hom_nay.weekday())
        return lambda m: thu_hai <= date.fromisoformat(m["ngay_khoi_hanh"]) <= thu_hai + timedelta(days=6)
    mm = _MAU_NGAY_CU_THE.search(c)
    if mm:
        ngay_, thang_ = int(mm.group(1)), int(mm.group(2))
        if 1 <= ngay_ <= 31 and 1 <= thang_ <= 12:
            return lambda m: md(m) == (thang_, ngay_)
    return None


def loc_theo_so_ngay(tours: list[dict], toan_tu: str, so_ngay: int) -> list[dict]:
    if toan_tu == ">=":
        return [t for t in tours if t["so_ngay"] >= so_ngay]
    if toan_tu == "<=":
        return [t for t in tours if t["so_ngay"] <= so_ngay]
    return [t for t in tours if t["so_ngay"] == so_ngay]


def _gom_theo_ten(tours: list[dict]) -> dict[str, list[dict]]:
    theo_ten: dict[str, list[dict]] = {}
    for t in tours:
        theo_ten.setdefault(t["ten"], []).append(t)
    return theo_ten


def _dedup_theo_ten(tours: list[dict]) -> list[dict]:
    """Mỗi lượt khởi hành (tour_days) giờ là 1 record RIÊNG trong ChromaDB
    (xem sync_tours.py) — cùng 1 tour có thể xuất hiện nhiều lần, chỉ khác
    "gia"/"ngay_khoi_hanh". Với câu hỏi THƯỜNG (không hỏi về ngày khởi hành),
    giữ lại đúng 1 record/tên tour để không chiếm hết top_k bởi 1 tour nhiều
    ngày, làm mất đa dạng các tour khác — ưu tiên record có ngày khởi hành
    GẦN NHẤT (đại diện hợp lý nhất khi khách chưa hỏi cụ thể ngày nào)."""
    theo_ten: dict[str, dict] = {}
    for t in tours:
        hien_tai = theo_ten.get(t["ten"])
        if hien_tai is None or t["ngay_khoi_hanh"] < hien_tai["ngay_khoi_hanh"]:
            theo_ten[t["ten"]] = t
    return list(theo_ten.values())


# Nhận diện câu hỏi về LỊCH/NGÀY KHỞI HÀNH bằng REGEX thay vì liệt kê cụm từ
# cố định — liệt kê cứng ("ngày khác", "còn ngày nào"...) luôn thiếu sót vì
# tiếng Việt có vô số cách diễn đạt cùng ý (bug thật gặp phải: "gồm những
# ngày nào" không khớp bất kỳ cụm nào đã liệt kê, khiến câu hỏi rơi nhầm vào
# vector search chung chung). Quy tắc: có nhắc "ngày"/"lịch"/"suất" CÙNG với
# 1 từ nghi vấn/liệt kê ("nào", "khác", "gồm", "những", "khi nào") thì coi là
# hỏi về ngày khởi hành. KHÔNG dùng "mấy" trong nhóm nghi vấn — "mấy ngày mấy
# đêm" là hỏi THỜI LƯỢNG tour (field so_ngay), không phải lịch khởi hành, dễ
# bị bắt nhầm nếu gộp chung (bug thật gặp phải khi thêm "mấy" vào ban đầu).
_MAU_HOI_NGAY_KHOI_HANH = re.compile(
    r"(ngày|ngay|lịch|lich|suất|suat|khởi hành|khoi hanh)"
    r".{0,15}"
    r"(nào|nao|khác|khac|gồm|gom|những|nhung|khi nào|khi nao)"
    r"|"
    r"(nào|nao|khác|khac|gồm|gom|những|nhung|khi nào|khi nao)"
    r".{0,15}"
    r"(ngày|ngay|lịch|lich|suất|suat|khởi hành|khoi hanh)",
    re.IGNORECASE,
)

# Loại trừ rõ mẫu "hỏi thời lượng tour" ("mấy ngày mấy đêm", "bao nhiêu
# ngày") để không bị pattern trên bắt nhầm khi câu hỏi chỉ có "ngày" đứng
# cạnh "nào"/"mấy" nhưng thực chất đang hỏi so_ngay chứ không phải lịch.
_MAU_HOI_THOI_LUONG = re.compile(
    r"mấy ngày|may ngay|bao nhiêu ngày|bao nhieu ngay", re.IGNORECASE,
)


def hoi_ve_ngay_khoi_hanh(cau_hoi: str) -> bool:
    cau_hoi_thuong = cau_hoi.lower()
    if _MAU_HOI_THOI_LUONG.search(cau_hoi_thuong):
        return False
    return bool(_MAU_HOI_NGAY_KHOI_HANH.search(cau_hoi_thuong))


def trich_loai_hinh(cau_hoi: str) -> str | None:
    """"trong nước"/"nước ngoài" là điều kiện rạch ròi (đúng/sai), không phải
    sắc thái ngữ nghĩa mờ — vector search có thể xếp nhầm tour Châu Âu vào
    câu hỏi "tour trong nước" vì 2 câu "giống nghĩa" theo hướng khác (VD cùng
    nói về giá cả/trải nghiệm). Lọc cứng theo field loai_hinh bằng code thay
    vì tin tưởng vector search cho điều kiện có-hoặc-không này.
    Kiểm tra "nước ngoài" trước vì chuỗi "trong nước" không phải lúc nào
    cũng loại trừ (câu có thể chỉ chứa 1 trong 2, nhưng ưu tiên rõ ràng)."""
    cau_hoi_thuong = cau_hoi.lower()
    # Kể cả gõ không dấu ("tour trong nuoc", "tour noi dia") — so theo ranh giới từ.
    if any(alias_khop(tu, cau_hoi_thuong) != -1 for tu in ("nước ngoài", "quốc tế", "nuoc ngoai", "quoc te")):
        return "Nước Ngoài"
    if any(alias_khop(tu, cau_hoi_thuong) != -1 for tu in ("trong nước", "nội địa", "trong nuoc", "noi dia")):
        return "Trong Nước"
    return None


def trich_the_loai(cau_hoi: str) -> str | None:
    """Thể loại tour khách nhắc tới ("tour of the year", "tour cao cấp",
    "MICE", "tour hè", "du lịch xanh") — xem THE_LOAI_TOUR ở rules.py.
    Là điều kiện rạch ròi giống loai_hinh/diem_den nên lọc CỨNG bằng code,
    không để vector search tự đoán. Ưu tiên alias DÀI nhất khớp được, tránh
    alias ngắn ("mice") thắng alias dài hơn chứa nó."""
    cau_hoi_thuong = cau_hoi.lower()
    khop_dai_nhat, the_loai_khop = 0, None
    for the_loai, cac_alias in THE_LOAI_TOUR.items():
        for alias in cac_alias:
            if alias_khop(alias, cau_hoi_thuong) != -1 and len(alias) > khop_dai_nhat:
                khop_dai_nhat, the_loai_khop = len(alias), the_loai
    return the_loai_khop


def thuoc_the_loai(meta: dict, the_loai: str) -> bool:
    """1 tour có thể thuộc NHIỀU thể loại — field `the_loai` lưu dạng chuỗi nối
    bằng "|" nên so khớp theo từng phần tử, không dùng `in` trên cả chuỗi
    (tránh "TOUR HÈ" khớp nhầm một thể loại khác có chứa chuỗi đó)."""
    co = [p.strip().upper() for p in str(meta.get("the_loai") or "").split("|") if p.strip()]
    return the_loai.strip().upper() in co


def bo_dau(text: str) -> str:
    """Bỏ dấu tiếng Việt — dùng để so khớp điểm đến khi khách gõ KHÔNG DẤU
    (rất phổ biến khi nhắn tin nhanh, VD "ha noi" thay vì "Hà Nội"). So khớp
    không dấu là CHÍNH XÁC TUYỆT ĐỐI (khác fuzzy match/gần đúng), nên đặt ưu
    tiên cao, kiểm tra trước cả fuzzy — bug thật gặp phải: "tour Ha Noi" và
    "di Da Nang" không khớp được field diem_den có dấu, rơi vào vector search
    kém chính xác hơn, dù bản chất đây là khớp ĐÚNG 100% chỉ khác cách gõ."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


_CHU_NHAT = re.compile(r"ch[uủ]\s+nh[aậ]t", re.IGNORECASE)


def _bo_chu_nhat(text: str) -> str:
    """"chủ nhật" là thứ trong tuần, không phải Nhật Bản (bug thật: "thứ 6 – chủ nhật" ra "chưa có tour Nhật 3 ngày")."""
    return _CHU_NHAT.sub("cn", text)


def trich_nhieu_diem_den(cau_hoi: str) -> list[str]:
    """Nhận diện TẤT CẢ điểm đến khách nhắc trong 1 câu (không chỉ 1 cái như
    trich_diem_den) — dùng cho câu SO SÁNH kiểu "Đà Lạt hay Phú Quốc rẻ hơn",
    "so sánh tour Nhật với Hàn". Giới hạn đã biết trước đây: trich_diem_den()
    chỉ trả về 1 giá trị (điểm đến DÀI NHẤT khớp được) nên câu hỏi 2-3 điểm
    đến chỉ tư vấn được đúng 1 nơi, bỏ sót ý so sánh của khách. Duyệt qua
    TOÀN BỘ điểm đến (kể cả alias) và gom mọi cái khớp, giữ thứ tự xuất hiện
    trong câu hỏi (không phải thứ tự trong dữ liệu) để trả lời tự nhiên đúng
    thứ tự khách nêu."""
    cau_hoi_thuong = _bo_chu_nhat(cau_hoi.lower())
    cau_hoi_khong_dau = bo_dau(cau_hoi_thuong)
    toan_bo = tat_ca_luot_con_han()
    cac_diem_den = sorted(
        {m["diem_den"] for m in toan_bo if m["diem_den"]},
        key=len, reverse=True,
    )

    tim_thay: dict[int, str] = {}  # vị trí xuất hiện trong câu -> điểm đến (khử trùng theo giá trị bên dưới)
    da_them: set[str] = set()

    def _them(diem_den: str, vi_tri: int):
        if diem_den not in da_them:
            tim_thay[vi_tri] = diem_den
            da_them.add(diem_den)

    for diem_den in cac_diem_den:
        vi_tri = cau_hoi_thuong.find(diem_den.lower())
        if vi_tri != -1:
            _them(diem_den, vi_tri)
    for diem_den in cac_diem_den:
        if diem_den in da_them:
            continue
        vi_tri = cau_hoi_khong_dau.find(bo_dau(diem_den.lower()))
        if vi_tri != -1:
            _them(diem_den, vi_tri)
    for alias in sorted(ALIAS_DIEM_DEN, key=len, reverse=True):
        vi_tri = alias_khop(alias, cau_hoi_thuong)
        if vi_tri != -1:
            diem_den_that = ALIAS_DIEM_DEN[alias]
            if diem_den_that in cac_diem_den:
                _them(diem_den_that, vi_tri)

    return [tim_thay[vi_tri] for vi_tri in sorted(tim_thay)]


# Từ khoá cho thấy khách đang SO SÁNH nhiều điểm đến/tour với nhau, không chỉ
# liệt kê ngẫu nhiên nhiều điểm đến trong 1 câu (tránh bug ngược: câu "Có tour
# Đà Lạt và Phú Quốc không" liệt kê tour 2 nơi CÙNG LÚC, không phải so sánh —
# 2 trường hợp cần xử lý khác nhau: so sánh nên tách riêng từng bên để đối
# chiếu giá/thời lượng, còn liệt kê thường chỉ cần gộp chung danh sách).
_TU_KHOA_SO_SANH = (
    "hay", "hoặc", "hon", "hơn", "rẻ hơn", "re hon", "so sánh", "so sanh",
    "hay là", "hay la", "nên chọn", "nen chon", "cái nào", "cai nao",
    "tốt hơn", "tot hon", "vs", "hay tour",
)


def hoi_so_sanh_diem_den(cau_hoi: str) -> bool:
    # Khớp theo RANH GIỚI TỪ: so chuỗi con tự do làm "hon" khớp trong "thong nhat", "hay" trong "thay"
    # (bug thật: "tour cac tieu vuong quoc a rap thong nhat" bị coi là câu so sánh).
    cau_hoi_thuong = cau_hoi.lower()
    return any(alias_khop(tu, cau_hoi_thuong) != -1 for tu in _TU_KHOA_SO_SANH)


def tim_tour_so_sanh(cac_diem_den: list[str], top_k_moi_ben: int = 3) -> list[dict]:
    """Lấy tour đại diện cho TỪNG điểm đến trong danh sách so sánh, tách riêng
    theo từng bên (không gộp/dedup xuyên điểm đến) — để tầng AI nhìn thấy rõ
    ràng đủ dữ liệu của mỗi bên mà so sánh giá/thời lượng, thay vì chỉ nhận
    được tour của 1 bên do trich_diem_den() cũ chỉ trả 1 giá trị."""
    toan_bo = tat_ca_luot_con_han()
    ket_qua = []
    for diem_den in cac_diem_den:
        cua_diem_den = _dedup_theo_ten([t for t in toan_bo if t["diem_den"] == diem_den])
        cua_diem_den.sort(key=lambda t: t["gia"])
        ket_qua += cua_diem_den[:top_k_moi_ben]
    return ket_qua


def alias_khop(alias: str, cau_hoi_thuong: str) -> int:
    """Vị trí alias trong câu hỏi, -1 nếu không có. Khớp theo RANH GIỚI TỪ (không dính chữ cái hai bên)
    để alias ngắn như "nga" không bắt nhầm trong "ngày", "ngân sách", "nghĩ"... — bug thật gặp phải:
    khách hỏi "Tour nga có không" không ra tour Nga vì diem_den trong dữ liệu là "Liên bang Nga"."""
    for cum in ALIAS_LOAI_TRU.get(alias, ()):  # "mỹ" trong "Mỹ Tho", "thẩm mỹ" không phải nước Mỹ; thay bằng khoảng trắng để giữ vị trí
        cau_hoi_thuong = re.sub(r"(?<!\w)" + re.escape(cum) + r"(?!\w)", lambda k: " " * len(k.group()), cau_hoi_thuong)
    m = re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", cau_hoi_thuong)
    return m.start() if m else -1


def trich_diem_den(cau_hoi: str) -> str | None:
    """Tên điểm đến (field diem_den) là điều kiện rạch ròi giống loai_hinh —
    khách hỏi "tour Trung Quốc" phải chỉ ra đúng tour Trung Quốc, không để
    vector search tự chọn (bug thật gặp phải: câu hỏi về Trung Quốc lẫn cả
    tour Nhật Bản do 2 câu "giống nghĩa" ở khía cạnh khác — cùng nói về thủ
    tục/chuẩn bị đi tour). So khớp trực tiếp với các giá trị diem_den đang
    có trong dữ liệu — nếu 1 giá trị xuất hiện nguyên vẹn trong câu hỏi
    (không phân biệt hoa/thường), coi là khách đã nhắc rõ điểm đến đó.
    Ưu tiên giá trị DÀI HƠN trước (VD "Trung Quốc" phải thắng "Trung" nếu có
    2 giá trị lồng nhau) để tránh khớp nhầm phần chung chung."""
    cau_hoi_thuong = _bo_chu_nhat(cau_hoi.lower())
    toan_bo = tat_ca_luot_con_han()
    cac_diem_den = sorted(
        {m["diem_den"] for m in toan_bo if m["diem_den"]},
        key=len, reverse=True,
    )
    for diem_den in cac_diem_den:
        if diem_den.lower() in cau_hoi_thuong:
            return diem_den

    # Không khớp có dấu -> thử so khớp KHÔNG DẤU (chính xác tuyệt đối, chỉ
    # khác cách gõ — ưu tiên trước fuzzy match vì đây không phải "gần đúng").
    cau_hoi_khong_dau = bo_dau(cau_hoi_thuong)
    for diem_den in cac_diem_den:
        if bo_dau(diem_den.lower()) in cau_hoi_khong_dau:
            return diem_den

    # Không khớp trực tiếp -> thử bảng ALIAS_DIEM_DEN (rules.py) — dữ liệu
    # diem_den dùng TÊN TỈNH (VD "Lâm Đồng") trong khi khách hàng thực tế
    # luôn gọi bằng tên thành phố/địa danh du lịch (VD "Đà Lạt"). Kiểm tra
    # alias DÀI HƠN trước, cùng lý do tránh khớp nhầm phần chung chung.
    for alias in sorted(ALIAS_DIEM_DEN, key=len, reverse=True):
        if alias_khop(alias, cau_hoi_thuong) != -1:
            diem_den_that = ALIAS_DIEM_DEN[alias]
            if diem_den_that in cac_diem_den:
                return diem_den_that

    # Alias nhiều chữ nhưng khách gõ sai dấu / không dấu / viết liền ("Dà Lạt", "Phu Quôc") -> so trên bản bỏ dấu.
    # Chỉ alias có khoảng trắng: alias 1 chữ bỏ dấu dễ trùng từ thường ("nhật" -> "nhat" dính "nhất").
    for alias in sorted(ALIAS_DIEM_DEN, key=len, reverse=True):
        if " " in alias and alias_khop(bo_dau(alias), cau_hoi_khong_dau) != -1:
            diem_den_that = ALIAS_DIEM_DEN[alias]
            if diem_den_that in cac_diem_den:
                return diem_den_that

    # Không khớp chính xác -> thử khớp GẦN ĐÚNG từng từ trong câu hỏi với
    # từng điểm đến, để chịu được lỗi chính tả nhẹ (bug thật gặp phải: khách
    # gõ "Madives" thiếu chữ "l" so với "Maldives" đúng, khớp chính xác thất
    # bại khiến câu hỏi rơi nhầm vào vector search chung chung, trả lời sai
    # cả kết luận "không có" lẫn tour gợi ý). Chỉ so từ có độ dài tương đương
    # (chênh lệch ≤ 2 ký tự) để tránh khớp nhầm từ ngắn không liên quan, và
    # yêu cầu độ giống nhau khá cao (cutoff 0.75) để không khớp bừa.
    for tu in re.findall(r"[a-zà-ỹ]+", cau_hoi_thuong):
        if len(tu) < 5:
            continue
        for diem_den in cac_diem_den:
            diem_den_thuong = diem_den.lower()
            if abs(len(tu) - len(diem_den_thuong)) > 2:
                continue
            if difflib.SequenceMatcher(None, tu, diem_den_thuong).ratio() >= 0.75:
                return diem_den
    return None


def _dau_ten_tour(ten: str) -> str:
    """'Du Lịch Bắc Âu (Tết…): …' -> 'Bắc Âu' (chữ khách nhìn thấy đầu tiên trên thẻ tour)."""
    s = re.sub(r"^Du Lịch\s+", "", ten)
    return re.split(r"\s*[:(]|\s+[-–]\s+", s)[0].strip()


def trich_tap_theo_ten(cau_hoi: str):
    """Khách gọi theo CHỮ ĐẦU TÊN TOUR ("tour Châu Âu", "Bắc Âu", "Đài Loan") hoặc theo VÙNG ("Đông Nam Á") mà diem_den
    trong dữ liệu lại là nước/thành phố cụ thể (tour Châu Âu có diem_den = Pháp). Trả về hàm nhận record -> True/False
    (tour mang đúng chữ đầu tên đó, hoặc thuộc điểm đến của vùng), hoặc None nếu không gọi tên như vậy."""
    kd = bo_dau(unicodedata.normalize("NFC", cau_hoi).lower())
    dau_ten_khop: set[str] = set()
    for ten in {m["ten"] for m in tat_ca_luot_con_han()}:
        dau = _dau_ten_tour(ten)
        dau_kd = bo_dau(dau.lower())
        if 1 <= len(dau.split()) <= 3 and len(dau_kd) >= 4 and alias_khop(dau_kd, kd) != -1:
            dau_ten_khop.add(dau)
    vung_khop: set[str] = set()
    for vung, cac_noi in VUNG_DIEM_DEN.items():
        if alias_khop(bo_dau(vung), kd) != -1:
            vung_khop |= cac_noi
    if not dau_ten_khop and not vung_khop:
        return None
    return lambda m: m["diem_den"] in vung_khop or _dau_ten_tour(m["ten"]) in dau_ten_khop


def diem_den_tu_lich_su(lich_su: list[dict] | None, ca_cau_tra_loi: bool = False) -> str | None:
    """Điểm đến khách nhắc ở các câu hỏi gần nhất (mới nhất trước, tối đa 3 câu) — để "dưới 10 triệu thôi" sau
    "tour Thái Lan" hiểu là Thái Lan.
    ca_cau_tra_loi=True (khách nói "tour đó/này"): khách chưa từng nêu điểm đến thì lấy điểm đến trong câu trả lời GẦN
    NHẤT của chatbot (bug thật: "tour nào rẻ nhất" -> bot nói Tây Ninh rẻ nhất -> "tour đó đi mấy ngày?" ra tour Singapore)."""
    if not lich_su:
        return None
    cau_khach = [m["content"] for m in lich_su if m.get("role") == "user" and m.get("content")]
    for c in reversed(cau_khach[-3:]):
        d = trich_diem_den(c)
        if d:
            return d
    if ca_cau_tra_loi:
        tra_loi = [m["content"] for m in lich_su if m.get("role") == "assistant" and m.get("content")]
        if tra_loi:
            return trich_diem_den(tra_loi[-1])
    return None


_MAU_THAM_CHIEU_TOUR = re.compile(r"(?<!\w)(tour|chuyến|chuyen)\s+(đó|do|này|nay|kia|ấy|ay)(?!\w)", re.IGNORECASE)


# Nhận diện khách đang PHỦ ĐỊNH/loại trừ 1 điểm đến (VD "từng đi Đà Nẵng
# rồi, muốn tìm chỗ mới lạ hơn") — bug thật gặp phải: trich_diem_den() vẫn
# bắt được chữ "Đà Nẵng" trong câu rồi lọc CỨNG đúng điểm đến khách vừa nói
# KHÔNG muốn, khiến bot giới thiệu ngược lại đúng nơi khách chê. Chỉ cần
# 1 cụm phủ định xuất hiện BẤT KỲ ĐÂU trong câu là đủ để bỏ qua lọc cứng
# diem_den, nhường cho vector search tự hiểu ngữ nghĩa "muốn nơi khác".
_MAU_PHU_DINH_DIEM_DEN = re.compile(
    r"đã (từng )?đi.{0,20}rồi|da (tung )?di.{0,20}roi|"
    r"(chỗ|noi|nơi) (khác|moi|mới).{0,10}(hơn|hon)|"
    # Neo ranh giới từ ở cụm cuối — bug thật: "tìm tour Thái Lan" khớp "tim ... la(n)" nên bị coi là phủ định.
    r"(tìm|tim).{0,15}(?<!\w)(khác|khac|mới|moi|lạ|la)(?!\w)|"
    r"(?<!nước )(?<!nuoc )(?<!\w)(ngoài|ngoai)\s.{1,25}?\sra(?!\w)",
    re.IGNORECASE,
)

# Phủ định NÊU RÕ nơi không đi: "không đi Thái", "không muốn đi Thái Lan", "không phải Thái Lan", "trừ Thái Lan ra".
# Điểm đến phải đứng NGAY SAU cụm này (xem trich_diem_den_bi_loai) — "có tour Đà Lạt không đi 2 người" thì chữ
# "không" chỉ là từ để hỏi, không được loại Đà Lạt. Bug thật: "tour nước ngoài, không đi Thái" vẫn ra tour Thái.
_MAU_KHONG_DI = re.compile(
    r"(?<!\w)(?:(?:không|khong|ko|chưa|chua|đừng)\s+"
    r"(?:(?:muốn|muon|thích|thich)\s+(?:(?:đi|di|tới|toi|đến|den|sang|chọn|chon)\s+)?|(?:đi|di|phải|phai|chọn|chon|lấy|lay|sang)\s+)"
    r"|(?:ngoại trừ|ngoai tru|trừ|tru)\s+)"
    r"(?:(?:tour|du lịch|du lich|nước|nuoc)\s+)?",
    re.IGNORECASE,
)


def trich_diem_den_bi_loai(cau_hoi: str) -> set[str]:
    """Các điểm đến khách nói KHÔNG muốn đi — phải bị loại khỏi kết quả ở mọi nhánh tìm."""
    cau_hoi_thuong = cau_hoi.lower()
    bi_loai: set[str] = set()
    if _MAU_PHU_DINH_DIEM_DEN.search(cau_hoi_thuong):
        bi_loai.update(trich_nhieu_diem_den(cau_hoi_thuong))
    for m in _MAU_KHONG_DI.finditer(cau_hoi_thuong):
        ngay_sau = " ".join(cau_hoi_thuong[m.end():].split()[:4])
        bi_loai.update(trich_nhieu_diem_den(ngay_sau))
    return bi_loai


def hoi_phu_dinh_diem_den(cau_hoi: str) -> bool:
    return bool(_MAU_PHU_DINH_DIEM_DEN.search(cau_hoi.lower())) or bool(trich_diem_den_bi_loai(cau_hoi))


def _co_cum_tu(cau_hoi_thuong: str, cac_cum: tuple) -> bool:
    return any(alias_khop(cum, cau_hoi_thuong) != -1 for cum in cac_cum)


def hoi_muon_gap_nhan_vien(cau_hoi: str) -> bool:
    """Nhận diện khách cần chuyển sang NHÂN VIÊN THẬT thay vì AI tự trả lời (các nhóm từ khoá ở rules.py).
    So theo RANH GIỚI TỪ; gộp NFC trước vì iPhone có thể gửi chữ dạng tổ hợp (bug thật: "khiếu nại" gõ trên
    iPhone không khớp từ khoá). Việc tiền/hợp đồng (hoàn tiền, huỷ tour...) chỉ chuyển khi là chuyện của CHÍNH
    khách, câu hỏi tham khảo chính sách thì để AI trả lời — xem TU_KHOA_TIEN_HOP_DONG."""
    cau_hoi_thuong = unicodedata.normalize("NFC", cau_hoi).lower()
    # Khách thường nói "hành lý của tôi bị mất" thay vì cụm cố định "mất
    # hành lý". Đây là sự cố trong chuyến đi, luôn cần người thật xử lý.
    cau_khong_dau = bo_dau(cau_hoi_thuong)
    if re.search(r"(?:mat|that lac|bo quen).{0,40}hanh ly|hanh ly.{0,40}(?:mat|that lac|bo quen)", cau_khong_dau):
        return True
    if _co_cum_tu(cau_hoi_thuong, TU_KHOA_CAN_NHAN_VIEN):
        return True
    if not _co_cum_tu(cau_hoi_thuong, TU_KHOA_TIEN_HOP_DONG):
        return False
    if _co_cum_tu(cau_hoi_thuong, TU_KHOA_DA_DAT):
        return True
    if _co_cum_tu(cau_hoi_thuong, TU_KHOA_HOI_CHINH_SACH):
        return False
    if _co_cum_tu(cau_hoi_thuong, TU_KHOA_Y_MUON):
        return True
    return not _co_cum_tu(cau_hoi_thuong, TU_KHOA_DANG_HOI)


def tim_sdt_viet_nam(cau_hoi: str) -> str | None:
    """Số điện thoại di động Việt Nam khách gõ trong tin (có thể cách bằng dấu cách, chấm, gạch; +84 hoặc 84 đầu), chuẩn hoá về 10 số.
    Số dài/ngắn hơn 10 số (gõ nhầm) hoặc đầu số lạ thì không tính. Xuống dòng ngăn cách 2 số khác nhau."""
    for m in re.finditer(r"(?<!\d)(?:\+?84|0)[\d \t.\-]{8,13}\d(?!\d)", cau_hoi):
        so = re.sub(r"\D", "", m.group(0))
        if so.startswith("84") and len(so) == 11:
            so = "0" + so[2:]
        if len(so) == 10 and so[:2] in ("03", "05", "07", "08", "09"):
            return so
    return None


_MAU_SDT_QUOC_TE = re.compile(r"(?<![\w+])\+(?!84)\d{1,3}[\d \t.\-]{6,14}\d(?!\d)")


def tim_sdt_quoc_te(cau_hoi: str) -> str | None:
    """Số nước ngoài có mã quốc gia "+" đầu (khách Việt kiều, bug thật: "+61 403 353 800" không được nhận). Trả số đã bỏ dấu cách,
    giữ dấu "+". Không có "+" thì không tính, để không nhầm với giá tiền hay mã tour."""
    for m in _MAU_SDT_QUOC_TE.finditer(cau_hoi):
        so = "+" + re.sub(r"\D", "", m.group(0))
        if 9 <= len(so) - 1 <= 15:
            return so
    return None


# Chữ hay đi kèm khi khách chỉ gửi số ("Em gửi", "sđt zalo đây ạ", "Ok em", "nhắn zalo giúp em"): còn lại toàn những chữ này thì
# tin chỉ là để lại số. Có câu hỏi thật thì AI vẫn trả lời (bug thật: "Má chị 85t vẫn đi được hả" kèm số bị trả "đã ghi nhận số").
_CHU_DI_KEM_SDT = {
    "da", "vang", "ok", "oke", "okay", "em", "anh", "chi", "minh", "toi", "c", "a", "e", "ah", "nhe", "nha", "nhen",
    "gui", "lai", "so", "sdt", "dt", "dien", "thoai", "zalo", "lien", "he", "lh", "day", "nay", "o", "ben", "cua", "la", "cho",
    "nhan", "nt", "goi", "giup", "dum", "gium", "voi", "cam", "on", "thanks", "tks", "nho", "qua", "duoc", "ko", "khong",
}


def co_cau_hoi_ngoai_sdt(cau_hoi: str) -> bool:
    """Tin có số điện thoại mà còn hỏi chuyện khác (có dấu "?" hoặc từ 4 chữ có nghĩa trở lên sau khi bỏ số và chữ đi kèm)."""
    bo_so = _MAU_SDT_QUOC_TE.sub(" ", cau_hoi)
    bo_so = re.sub(r"(?<!\d)(?:\+?84|0)[\d \t.\-]{8,13}\d(?!\d)", " ", bo_so)
    if "?" in bo_so:
        return True
    chu = re.findall(r"\w+", bo_dau(unicodedata.normalize("NFC", bo_so).lower()))
    return len([c for c in chu if c not in _CHU_DI_KEM_SDT]) >= 4


_MAU_NHAN_VIEN_HOI = re.compile(
    r"\b(bao lau|bao nhieu|khi nao|bao gio|nao|o dau|the nao|ra sao|cho em hoi|cho minh hoi|phai khong|hay sao)\b"
    r"|\b(khong|ko|chua|ha)( a| ah| vay| nhi)?$"
)
_MAU_NGAY_THANG = re.compile(r"(?<![\d/.\-])\d{1,2}\s*[/\-.]\s*\d{1,2}(?:\s*[/\-.]\s*\d{2,4})?(?![\d/.\-])")


def la_cau_hoi_cua_nhan_vien(text: str) -> bool:
    """Tin nhân viên là câu hỏi khách ("rớt visa bao lâu rồi ạ", "mình đi thời gian nào ạ"): câu khách nhắn ngay sau đó là câu trả lời,
    không được đem đi dò "chưa có tour tháng Y" (bug thật: khách đáp "Đầu tháng 4 e", bot trả "chưa có tour Hồng Kông tháng 4")."""
    t = bo_dau(unicodedata.normalize("NFC", text or "").lower()).strip(" .!")
    return "?" in t or bool(_MAU_NHAN_VIEN_HOI.search(t))


def nhieu_noi_hoac_nhieu_ngay(cau_hoi: str) -> bool:
    """Câu nêu từ 2 nơi hoặc 2 ngày trở lên: câu viết sẵn chỉ hiểu một nơi một ngày nên dễ ghép sai (bug thật: "12-2 đi Thái, 18-2 đi
    Hạ Long" thành "chưa có tour Hà Nội ngày 12/02")."""
    return len(trich_nhieu_diem_den(cau_hoi)) >= 2 or len(_MAU_NGAY_THANG.findall(cau_hoi)) >= 2


_MAU_DOANH_NGHIEP = re.compile(
    r"\b(company trip|team ?building|gala ?dinner|incentive|hoi nghi|hoi thao|doan cong ty|du lich cong ty|tour cong ty|"
    r"di cong ty|to chuc cho cong ty|cong ty (?:em|minh|toi|anh|chi|tui))\b"
)
_MAU_SO_NGUOI = re.compile(r"\b(\d{2,3})\s*(?:nguoi|ng|khach|pax|thanh vien)\b")  # "30 ng" = 30 người (chat viết tắt)
_MAU_VE_RIENG = re.compile(r"\b(?:ve may bay|ve mb|khach san|ks|mb)\b")
_MAU_HANH_DONG_DAT = re.compile(r"\b(?:dat|mua|ban|book|dang ky|tu van|ho tro)\b")
_MAU_CO_TOUR = re.compile(r"\b(?:tour|chuong trinh|tron goi|bao gom|da gom|gom)\b")
_MAU_KHONG_DI_TOUR = re.compile(r"\b(?:khong|ko|k|chang)\s+(?:di|mua|dat|di theo)\s+tour\b")  # "đặt khách sạn, ko đi tour" = chỉ muốn lẻ
# Mục API tour không có dữ liệu (đánh giá 160 câu 2026-11-23), chủ dự án chốt 2026-11-25: không để AI nói "chưa có thông tin" mà báo
# nhân viên tư vấn, khách vẫn hỏi bot chuyện khác được. Khớp trên chữ không dấu, chữ thường.
_MAU_CAN_TU_VAN = re.compile(
    r"\ban chay\b|\bdi ung\b|\ban kieng\b|\bkieng (?:an|hai san|thit|do)\b|\bhalal\b"  # ăn chay, dị ứng
    r"|\bdoan(?: \w+){0,2} (?:bao nhieu|may) (?:nguoi|khach)\b|\b(?:bao nhieu|may) (?:nguoi|khach) (?:1|mot|trong|moi) doan\b"  # số người trong đoàn
    r"|\btra gop\b|\bquet the\b|\bca the\b|\bthe tin dung\b|\bcredit card\b|\bmastercard\b"  # trả góp, quẹt thẻ
    r"|(?<!ruou )(?<!hoa )\be?sim\b(?! phu quoc)|\bwi ?fi\b|\bcuc phat\b|\broaming\b|\bchuyen vung\b"  # SIM, wifi
    r"|\bchuyen nhuong\b|\bnhuong (?:lai )?(?:suat|cho|ve|slot)\b|\bdoi ten\b|\bsang ten\b|\bchuyen (?:suat|cho|ve) (?:cho|sang)\b"  # chuyển suất
    r"|\bmang thai\b|\bdang bau\b|\bco bau\b|\bba bau\b|\bbau \d+ (?:thang|tuan)\b|\bthai \d+ (?:thang|tuan)\b"  # bà bầu
    r"|\b(?:om|benh|sot|nam vien|cap cuu|tai nan)\b.*\b(?:doi ngay|doi lich|doi dot|lui ngay|doi sang)\b"  # đổi ngày vì ốm
    r"|\b(?:doi ngay|doi lich|doi dot|lui ngay|doi sang)\b.*\b(?:om|benh|sot|nam vien|cap cuu|tai nan)\b"
    r"|\bkhan cap\b|\bso cap cuu\b|\b(?:ban dem|nua dem|dem khuya)\b.*\b(?:lien he|goi|hotline|so)\b"  # khẩn cấp ban đêm
    r"|\bearly ?bird\b|\bgiam gia (?:nhom|doan|khach cu|khach than thiet)\b|\bthe thanh vien\b|\bma giam gia\b|\bgift ?voucher\b"  # ưu đãi
    r"|\buu dai (?:khach cu|khach than thiet|dat som)\b|\bdat som (?:co )?(?:duoc )?(?:giam|uu dai)\b"
)


def can_nhan_vien_som(cau_hoi: str, co_sdt: bool) -> str | None:
    """Tin KHÔNG đòi gặp nhân viên nhưng bot không phục vụ được, cần nhân viên thật nhận ngay (không để AI trả lời lạc đề):
    - "SDT": khách để lại số điện thoại mà hồ sơ chưa có số (Zalo, Facebook; web và app luôn có số nên không bao giờ rơi vào đây).
    - "DOANH_NGHIEP": đoàn công ty, team building, hội nghị, đoàn đông người (từ 20 người; có chữ "đoàn" thì từ 15 người).
    - "VE_RIENG": chỉ muốn mua/đặt vé máy bay hoặc khách sạn lẻ (câu có nhắc tour/chương trình/trọn gói thì là hỏi tour, không tính).
    - "TU_VAN": hỏi mục chưa có dữ liệu (ăn chay, dị ứng, số người trong đoàn, trả góp, quẹt thẻ, SIM, wifi, chuyển suất, bà bầu,
      đổi ngày vì ốm, số khẩn cấp ban đêm, giảm giá nhóm, Early Bird, thẻ thành viên, mã giảm giá).
    Trả mã lý do, hoặc None."""
    cau_khong_dau = bo_dau(unicodedata.normalize("NFC", cau_hoi).lower())
    if not co_sdt and (tim_sdt_viet_nam(cau_hoi) or tim_sdt_quoc_te(cau_hoi)):
        return "SDT"
    if _MAU_DOANH_NGHIEP.search(cau_khong_dau):
        return "DOANH_NGHIEP"
    doan = re.search(r"\bdoan\b", cau_khong_dau) is not None
    if any(int(n) >= (15 if doan else 20) for n in _MAU_SO_NGUOI.findall(cau_khong_dau)):
        return "DOANH_NGHIEP"
    if _MAU_VE_RIENG.search(cau_khong_dau) and _MAU_HANH_DONG_DAT.search(cau_khong_dau) and not _MAU_CO_TOUR.search(_MAU_KHONG_DI_TOUR.sub(" ", cau_khong_dau)):
        return "VE_RIENG"
    if _MAU_CAN_TU_VAN.search(cau_khong_dau):
        return "TU_VAN"
    return None


# Từ viết hoa hay đứng sau "tour"/"đi" nhưng KHÔNG phải địa danh (bỏ dấu, chữ thường) — xem
# hoi_diem_den_khong_co_tour(): gặp các từ này thì không kết luận gì, để các nhánh tìm phía sau xử lý như cũ.
_TU_VIET_HOA_KHONG_PHAI_DIA_DANH = {
    "tet", "noel", "giang", "he", "mua", "xuan", "thu", "dong", "le", "gia", "bien", "dao", "nui", "trang", "team",
    "teambuilding", "mice", "vip", "cao", "sang", "re", "tiet", "nghi", "golf", "honeymoon", "trong", "nuoc", "ngoai",
    "quoc", "noi", "nao", "gi", "nay", "do", "khac", "moi", "hot", "sale", "khuyen", "combo", "free", "thang", "ngay",
    "cuoi", "dau", "nam", "minh", "toi", "ban", "em", "anh", "chi", "shop", "ad", "admin", "benthanh", "ben", "btt",
    "viet", "tour", "du", "choi", "chau", "mien", "doc", "khoi", "ve", "may", "bao", "co", "khong", "a", "oi",
    # chủ đề tour hay được gõ hoa: Hành Hương, Ẩm Thực, Khám Phá, Sinh Thái, Văn Hóa, Tâm Linh, Trải Nghiệm, Mạo Hiểm...
    "hanh", "huong", "am", "thuc", "kham", "pha", "sinh", "van", "tam", "linh", "trai", "nghiem", "mao", "hiem", "the",
    "thao", "trekking", "camping", "picnic", "da", "giai", "tri", "mua", "sam", "an", "uong", "duong", "cap", "tuan",
    "mat", "lang", "man", "tiet", "kiem", "tron", "goi", "ghep", "doan", "rieng", "tu", "tuc", "sieu", "dep", "tot",
}
_TU_DUNG_TRUOC_TEN_RIENG = {"tour", "lịch", "đi", "sang", "đến", "tới"}
# Tên bỏ dấu dễ trùng câu thường ("co to" = "có to", "ba lan" = "ba lần", "my", "lao") -> chỉ so khi khách gõ CÓ dấu.
_DIA_DANH_CHI_SO_CO_DAU = {
    "mỹ", "lào", "cô tô", "ma cao", "ba lan", "ấn độ", "côn đảo", "ba vì", "nam du", "cần giờ", "bình ba", "long an",
    "phú quý", "bến tre", "nước ý", "nước áo", "nước bỉ", "nước đức", "sơn la", "tam đảo",
}


def hoi_tour_bien(cau_hoi_thuong: str) -> bool:
    return any(alias_khop(k, cau_hoi_thuong) != -1 for k in TU_KHOA_TOUR_BIEN)


def la_tour_bien(m: dict) -> bool:
    ten = str(m.get("ten") or "").lower()
    return any(k in ten for k in DAU_HIEU_TOUR_BIEN)


def ten_goi_diem_den(cau_hoi: str, diem_den: str) -> str:
    """Tên khách dùng để gọi điểm đến (VD "Đà Lạt" thay vì tên tỉnh "Lâm Đồng" trong dữ liệu), để câu trả lời viết
    sẵn dùng đúng chữ khách quen."""
    cau = cau_hoi.lower()
    if alias_khop(diem_den.lower(), cau) != -1:
        return diem_den
    for alias, dich in sorted(ALIAS_DIEM_DEN.items(), key=lambda x: -len(x[0])):
        if dich == diem_den and len(alias) > 3 and alias_khop(alias, cau) != -1:
            return " ".join(w[:1].upper() + w[1:] for w in alias.split())
    return diem_den


def hoi_diem_den_khong_co_tour(cau_hoi: str) -> bool:
    return dia_danh_khong_co_tour(cau_hoi) is not None


def dia_danh_khong_co_tour(cau_hoi: str) -> str | None:
    """True khi khách nêu rõ một nơi mà dữ liệu KHÔNG có tour nào mang tên nơi đó — khi ấy phải trả rỗng, không
    để vector search đưa tour nơi khác như thể khớp (bug thật: "có tour Nam Cực không" ra tour Singapore). Chỉ gọi
    khi trich_diem_den() đã không khớp điểm đến/alias nào. Hai cách nhận ra, đều kiểm lại trên dữ liệu lúc chạy:
    (1) địa danh trong DIA_DANH_PHO_BIEN (rules.py); (2) cụm VIẾT HOA ngay sau "tour"/"du lịch"/"đi"/"sang"/
    "đến"/"tới" ("tour Bình Hưng") mà không tour nào có đủ các chữ đó trong tên.
    Trả về TÊN nơi đó (viết hoa chữ đầu) để trả lời thẳng "chưa có tour đi …"; None nếu không phải trường hợp này."""
    cau_hoi = unicodedata.normalize("NFC", cau_hoi)
    cau_hoi_thuong = cau_hoi.lower()
    # Kể chuyện đã đi ("mới đi TQ về nè", "vừa qua Nhật rồi") không phải hỏi tour đi nơi đó (bug thật: trả "chưa có tour đi TQ").
    if re.search(r"(mới|vừa|đã|năm ngoái|năm rồi)\s+(đi|du lịch|qua|sang).{0,30}(về|rồi)", cau_hoi_thuong):
        return None
    # Tên + điểm đến của từng tour, bỏ dấu, tách sẵn thành từ
    van_ban = {bo_dau(f"{m['ten']} {m['diem_den']}".lower()) for m in tat_ca_luot_con_han()}
    van_ban = [" ".join(re.findall(r"\w+", v)) for v in van_ban]
    bo_tu = [set(v.split()) for v in van_ban]

    go_khong_dau = cau_hoi_thuong == bo_dau(cau_hoi_thuong)
    for dia_danh in DIA_DANH_PHO_BIEN:
        khong_dau = bo_dau(dia_danh)
        co_trong_cau = alias_khop(dia_danh, cau_hoi_thuong) != -1 or (
            go_khong_dau and dia_danh not in _DIA_DANH_CHI_SO_CO_DAU and alias_khop(khong_dau, cau_hoi_thuong) != -1
        )
        if co_trong_cau and not any(alias_khop(khong_dau, v) != -1 for v in van_ban):
            return " ".join(w[:1].upper() + w[1:] for w in dia_danh.split())

    if cau_hoi.isupper():  # GÕ HOA CẢ CÂU thì chữ hoa không nói lên tên riêng
        return None
    cac_tu = re.findall(r"[^\W\d_]+|\d+", cau_hoi)
    alias_khong_dau = {bo_dau(a) for a in ALIAS_DIEM_DEN}
    for i, tu in enumerate(cac_tu[:-1]):
        if tu.lower() not in _TU_DUNG_TRUOC_TEN_RIENG or (tu.lower() == "lịch" and (i == 0 or cac_tu[i - 1].lower() != "du")):
            continue
        cum = []
        for sau in cac_tu[i + 1:i + 5]:
            if not sau[0].isupper():
                break
            cum.append(bo_dau(sau.lower()))
        if not cum or any(c in _TU_VIET_HOA_KHONG_PHAI_DIA_DANH for c in cum) or " ".join(cum) in alias_khong_dau:
            continue
        if not any(all(c in tu_cua_tour for c in cum) for tu_cua_tour in bo_tu):
            return " ".join(cac_tu[i + 1:i + 1 + len(cum)])
    return None


# Hỏi về CÔNG TY (văn phòng, chi nhánh, tổng đài...) -> không kèm thẻ tour dù câu có tên thành phố (bug thật: "văn
# phòng công ty ở Hà Nội không" ra thẻ tour Hà Nội).
_TU_KHOA_HOI_CONG_TY = (
    "văn phòng", "van phong", "chi nhánh", "chi nhanh", "trụ sở", "tru so", "tổng đài", "tong dai", "hotline",
    "số điện thoại", "so dien thoai", "giờ làm việc", "gio lam viec", "mở cửa", "mo cua",
)
# Hỏi THỦ TỤC / CHÍNH SÁCH chung, không nêu điểm đến hay ngân sách ("tour có bảo hiểm không", "đặt tour có cần đặt
# cọc không") -> không kèm 5 thẻ tour ngẫu nhiên từ vector search; AI trả lời thẳng câu hỏi.
_TU_KHOA_HOI_THU_TUC = (
    "chính sách", "chinh sach", "quy định", "quy dinh", "điều khoản", "dieu khoan", "hoàn tiền", "hoan tien",
    "hủy tour", "huỷ tour", "huy tour", "đặt cọc", "dat coc", "tiền cọc", "tien coc", "bảo hiểm", "bao hiem",
    "hộ chiếu", "ho chieu", "passport", "visa", "thanh toán", "thanh toan", "chuyển khoản", "chuyen khoan",
    "trả góp", "tra gop", "vé máy bay", "ve may bay", "tính giá", "tinh gia", "giá trẻ em", "gia tre em",
    "phụ thu", "phu thu", "hóa đơn", "hoá đơn", "hoa don", "mất phí", "mat phi",
)


# "tour nào rẻ nhất" / "tour đắt nhất" -> sắp theo giá trên dữ liệu đã lọc (không phải câu ngữ nghĩa cho vector search).
_MAU_RE_NHAT = re.compile(r"(?<!\w)(rẻ|re)\s+(nhất|nhat)(?!\w)|(giá|gia)\s+(thấp|thap)\s+(nhất|nhat)(?!\w)", re.IGNORECASE)
_MAU_DAT_NHAT = re.compile(r"(?<!\w)(đắt|dat|mắc|mac)\s+(nhất|nhat)(?!\w)|(giá|gia)\s+cao\s+(nhất|nhat)(?!\w)", re.IGNORECASE)


# Từ khoá cho thấy câu hỏi CÓ liên quan tới tour/du lịch — dùng để chặn câu
# chào hỏi thuần tuý ("Xin chào", "Bạn là ai") hoặc câu hỏi chính sách chung
# không nhắc tour cụ thể ("Số điện thoại hotline là gì", "Thanh toán bằng
# cách nào") khỏi việc bị vector search trả về 5 tour NGẪU NHIÊN không liên
# quan gì (bug thật gặp phải: mọi câu hỏi, kể cả "Bạn tên gì", đều kèm 5 thẻ
# tour vô nghĩa dưới câu trả lời). Không cần bao phủ tuyệt đối — câu hỏi có
# điều kiện cụ thể (điểm đến/ngân sách/ngày/số ngày/loại hình) đã được nhận
# diện riêng ở các hàm trich_*() phía trên, không phụ thuộc vào danh sách này.
_TU_KHOA_LIEN_QUAN_TOUR = (
    "tour", "du lịch", "du l", "đi chơi", "đi du", "khách sạn", "resort",
    "nghỉ dưỡng", "biển", "khởi hành", "đặt tour", "đặt chỗ", "book",
    "lịch trình", "hành trình", "điểm đến", "giá vé", "chuyến đi",
)


_MAU_CAO_CAP = re.compile(r"(?<!\w)(cao cấp|cao cap|sang chảnh|sang chanh|hạng sang|hang sang|luxury|sang trọng|sang trong)(?!\w)", re.IGNORECASE)
_MAU_GIA_RE = re.compile(r"(?<!\w)(giá rẻ|gia re|tour rẻ|tour re|giá thấp|gia thap|tiết kiệm|tiet kiem|bình dân|binh dan)(?!\w)", re.IGNORECASE)


def hoi_lien_quan_tour(cau_hoi: str, dieu_kien_cu_the: bool) -> bool:
    """dieu_kien_cu_the=True khi đã trích được điểm đến/ngân sách/ngày/số
    ngày/loại hình cụ thể — trường hợp đó luôn coi là liên quan tour, không
    cần xét thêm từ khoá (vì điều kiện cụ thể chỉ có ý nghĩa khi đang hỏi
    tour, không nhầm lẫn được với câu chào hỏi/hỏi chính sách chung)."""
    if dieu_kien_cu_the:
        return True
    cau_hoi_thuong = cau_hoi.lower()
    return any(tu in cau_hoi_thuong for tu in _TU_KHOA_LIEN_QUAN_TOUR)


# Câu hỏi thể hiện Ý ĐỊNH tìm/đặt tour nhưng chưa nêu điều kiện cụ thể nào
# (khác với hoi_lien_quan_tour() ở chỗ: hàm đó chỉ cần 1 từ khoá tour/du lịch
# là đủ để KHÔNG trả về rỗng, còn hàm này xét xem có nên hỏi ngược lại khách
# hay không — 2 mục đích khác nhau nên tách riêng, không tái dùng chung).
_TU_KHOA_Y_DINH_TIM_TOUR = (
    "muốn đi", "muon di", "tư vấn tour", "tu van tour", "gợi ý tour", "goi y tour",
    "gợi ý giúp", "goi y giup", "tìm tour", "tim tour", "muốn du lịch", "muon du lich",
    "đi du lịch", "di du lich", "đi chơi", "di choi", "cần đi", "can di",
)


def hoi_tim_tour_thieu_thong_tin(cau_hoi: str) -> bool:
    """True khi khách rõ ràng đang muốn tìm/đặt tour nhưng KHÔNG nêu bất kỳ
    điều kiện cụ thể nào (điểm đến/ngân sách/loại hình/tháng/số ngày) — dùng
    để quyết định có nên hỏi ngược khách trước khi tư vấn hay không, thay vì
    im lặng trả tour không sát nhu cầu (kể cả khi vector search "may mắn" trả
    về vài tour nghe có vẻ liên quan, tour đó vẫn không dựa trên điều kiện
    thật nào khách nêu). Xét trực tiếp trên các hàm trich_*() đã có thay vì
    suy luận qua kết quả "tours" rỗng/không rỗng — vector search fallback
    trong tim_tour_lien_quan() luôn trả về vài tour cho câu có từ khoá
    "du lịch" dù không hề có điều kiện cụ thể nào, nên không thể dùng "tours
    rỗng" làm dấu hiệu đáng tin. Chỉ áp dụng cho câu có Ý ĐỊNH tìm tour rõ
    ràng (khác câu chào hỏi/hỏi chính sách chung, vốn không nên bị hỏi ngược
    vì khách chưa hề ngỏ ý tìm tour)."""
    if (
        trich_khoang_ngan_sach(cau_hoi) or trich_ngan_sach(cau_hoi) is not None
        or trich_loai_hinh(cau_hoi) or trich_diem_den(cau_hoi)
        or trich_thang_khoi_hanh(cau_hoi) or trich_dieu_kien_so_ngay(cau_hoi)
    ):
        return False
    cau_hoi_thuong = cau_hoi.lower()
    return any(tu in cau_hoi_thuong for tu in _TU_KHOA_Y_DINH_TIM_TOUR)


_DONG_TU_DAT = r"(dat|book|dang ky|dang ki|mua)"
# Hỏi CÁCH đặt tour ("tôi liên hệ đặt tour như thế nào", "các bước đặt tour", "đặt tour ở đâu"). So trên chữ không dấu.
_MAU_HOI_CACH_DAT = re.compile(
    rf"\b(lam sao|lam the nao|cach|quy trinh|thu tuc|cac buoc|huong dan(?! vien))\b.*\b{_DONG_TU_DAT}\b"
    rf"|\b{_DONG_TU_DAT} tour\b.*\b(the nao|ra sao|lam sao|cach nao|o dau)\b"
    rf"|\b{_DONG_TU_DAT} tour (online|truc tuyen|qua mang|tren app|qua app|tren ung dung|qua ung dung)\b"
    rf"|\blien he\b.*\b{_DONG_TU_DAT}\b|\b{_DONG_TU_DAT}\b.*\blien he\b"
)
# Hỏi CHUNG về dịch vụ của tour, không nhằm tìm tour ("tour có hướng dẫn viên không", "giá tour bao gồm những gì").
_MAU_HOI_CHUNG_VE_TOUR = re.compile(
    r"\btour (co|da|gom|bao gom)\b.*\b(khong|ko|chua)\b"
    r"|\b(bao gom|gom) (nhung )?gi\b|\bco duoc\b.*\b(khong|ko)\b"
    r"|\b(giay to|chuan bi gi|can chuan bi|huong dan vien|dua don|doi ngay|doi lich|xac nhan dat|sau khi dat|dat tour xong|dat xong)\b"
)
# Khách đang muốn XEM tour -> vẫn kèm thẻ dù câu có các cụm trên ("có tour nào có đưa đón không").
_MAU_MUON_XEM_TOUR = re.compile(r"\b(tour nao|nhung tour|cac tour|goi y|tu van|tim tour|xem tour|muon di)\b")


def _chu_khong_dau(cau_hoi: str) -> str:
    return " ".join(re.findall(r"\w+", bo_dau(unicodedata.normalize("NFC", cau_hoi).lower())))


def la_cau_hoi_cach_dat(cau_hoi: str) -> bool:
    """Câu hỏi CÁCH đặt tour, chưa xét có nêu điểm đến hay không. Bỏ dấu thì "đắt" thành "dat" nên loại riêng."""
    return "đắt" not in unicodedata.normalize("NFC", cau_hoi).lower() and bool(_MAU_HOI_CACH_DAT.search(_chu_khong_dau(cau_hoi)))


def hoi_cach_dat_tour(cau_hoi: str) -> bool:
    """True khi khách hỏi cách đặt tour -> main.py trả câu viết sẵn dẫn về app (thẻ tour vẫn theo tim_tour_lien_quan:
    "Đặt tour Đà Lạt thế nào" kèm thẻ Đà Lạt, câu không nêu điều kiện thì không kèm). "Đặt tour xong thanh toán thế
    nào", "đặt tour giá thế nào" hỏi việc khác nên để AI trả lời."""
    if not la_cau_hoi_cach_dat(cau_hoi):
        return False
    hoi_viec_khac = _co_cum_tu(cau_hoi.lower(), _TU_KHOA_HOI_THU_TUC) or re.search(
        r"\b(gia|dat xong|dat tour xong|sau khi dat|giay to)\b", _chu_khong_dau(cau_hoi)
    )
    return not hoi_viec_khac


def hoi_chung_ve_tour(cau_hoi: str) -> bool:
    """Câu hỏi quy trình / dịch vụ chung -> không kèm thẻ tour (bug thật: "Tôi liên hệ đặt tour như thế nào" có chữ
    "tour" nên rơi vào vector search và ra 5 thẻ tour không liên quan)."""
    kd = _chu_khong_dau(cau_hoi)
    if _MAU_MUON_XEM_TOUR.search(kd) or _MAU_GIA_RE.search(kd) or _MAU_CAO_CAP.search(kd):
        return False
    return la_cau_hoi_cach_dat(cau_hoi) or bool(_MAU_HOI_CHUNG_VE_TOUR.search(kd))


_SO_TOUR_GAN_DUNG = 3


def _mo_ta_dip(cau_hoi: str) -> str:
    """Cụm chữ tả dịp khách nêu (trich_bo_loc_ngay chỉ trả hàm lọc) để câu trả lời nói đúng điều khách hỏi."""
    c = unicodedata.normalize("NFC", cau_hoi).lower()
    kd = bo_dau(c)
    dip = trich_dip_le(cau_hoi)
    if dip:
        return dip.mo_ta
    if "hè" in c:
        return "vào dịp hè"
    if re.search(r"\bcuoi tuan\b", kd):
        return "vào cuối tuần này"
    if re.search(r"\btuan (sau|toi)\b", kd):
        return "vào tuần sau"
    m = _MAU_NGAY_CU_THE.search(c)
    return f"vào ngày {int(m.group(1)):02d}/{int(m.group(2)):02d}" if m else "vào thời gian bạn chọn"


def _mo_ta_so_ngay(toan_tu: str, so_ngay: int) -> str:
    if toan_tu == ">=":
        return f"từ {so_ngay} ngày trở lên"
    return f"không quá {so_ngay} ngày" if toan_tu == "<=" else f"kéo dài {so_ngay} ngày"


def _ten_noi_khach_hoi(cau_hoi: str, diem_den: str | None, tap: list[dict]) -> str:
    if diem_den:
        return ten_goi_diem_den(cau_hoi, diem_den)
    kd = bo_dau(unicodedata.normalize("NFC", cau_hoi).lower())
    for vung in VUNG_DIEM_DEN:
        if alias_khop(bo_dau(vung), kd) != -1:
            return vung.title()
    for dau in sorted({_dau_ten_tour(m["ten"]) for m in tap}, key=len, reverse=True):
        if alias_khop(bo_dau(dau.lower()), kd) != -1:
            return dau
    return ""


def _tim_tour_gan_dung(
    tap_noi: list[dict], co_noi: bool, ten_noi: str, dieu_kien: list[tuple],
    so_ngay: tuple[str, int] | None, gia_tran: int | None,
) -> dict:
    """Không tour nào khớp ĐỦ điều kiện -> nới dần, đúng điểm đến (bug thật: "tour Trung Quốc 6 ngày cho Tết" nói không
    có, trong khi có tour Tết 5 ngày). `dieu_kien` xếp theo thứ tự ưu tiên nới; không nêu điểm đến thì phải giữ lại ít
    nhất 1 điều kiện, kẻo gợi ý cả tour chẳng liên quan. Trả {} nếu không có gì gần đúng."""
    for so_bo in range(1, len(dieu_kien) + (1 if co_noi else 0)):
        for bo in combinations(range(len(dieu_kien)), so_bo):
            tap = tap_noi
            for i, (_, loc) in enumerate(dieu_kien):
                if i not in bo:
                    tap = loc(tap)
            if not tap:
                continue
            trong_gia = [m for m in tap if gia_tran is not None and m["gia"] <= gia_tran]
            lech_ngay = (lambda m: abs(m["so_ngay"] - so_ngay[1])) if so_ngay else (lambda m: 0)
            # "Đà Lạt" nằm trong tỉnh Lâm Đồng (cùng tỉnh còn tour Đắk Nông): ưu tiên tour có đúng chữ khách gõ trong tên.
            khac_ten = lambda m: bool(ten_noi) and ten_noi.lower() not in m["ten"].lower()
            theo_ten: dict[str, dict] = {}
            for m in sorted(trong_gia or tap, key=lambda m: (khac_ten(m), lech_ngay(m), m["ngay_khoi_hanh"])):
                theo_ten.setdefault(m["ten"], m)
            return {
                "noi": ten_noi,
                "yeu_cau": [mo_ta for mo_ta, _ in dieu_kien],
                "tours": list(theo_ten.values())[:_SO_TOUR_GAN_DUNG],
                # Có mức giá mà không tour tương tự nào vừa: câu trả lời phải nói rõ, không im lặng đưa tour đắt hơn.
                "vuot_gia": gia_tran if gia_tran is not None and not trong_gia else None,
            }
    return {}


def tim_tour_lien_quan(
    cau_hoi: str, top_k: int = TOP_K_TOURS, lich_su: list[dict] | None = None, goi_y_gia: dict | None = None,
    goi_y_gan_dung: dict | None = None,
) -> list[dict]:
    """Tìm tour theo câu hỏi; câu hỏi theo dịp lễ thì tách nhóm tour đúng tên / chỉ trùng ngày, xem _phan_nhom_theo_dip()."""
    tours = _tim_tour_chua_phan_nhom(cau_hoi, top_k, lich_su, goi_y_gia, goi_y_gan_dung)
    dip = trich_dip_le(cau_hoi)
    return _phan_nhom_theo_dip(tours, dip) if dip else tours


SO_THE_DIP_MOI_LAN = 10
SO_THE_DUNG_TEN_MOI_LAN = 8
_MO_TA_LE_CHUNG = "vào dịp lễ"
_MO_TA_DIP_TRONG_LE_CHUNG = {"vào dịp Noel", "vào dịp Tết Dương lịch", "vào dịp Tết Âm lịch", "vào dịp lễ 30/4", "vào dịp lễ 2/9"}


def _gan_nhom(tours: list[dict], dip: DipLe, nhom: str) -> list[dict]:
    return [{**t, "ten_dip": dip.mo_ta.removeprefix("vào "), "nhom_dip": nhom} for t in tours]


def _ngay_gan_nhat_cua_dip(dip: DipLe, hom_nay: date) -> date:
    return min(
        (tu for nam in range(hom_nay.year, hom_nay.year + 3) for tu, den in dip.cac_khoang(nam) if den >= hom_nay),
        default=date.max,
    )


def _phan_nhom_theo_dip(tours: list[dict], dip: DipLe, hom_nay: date | None = None) -> list[dict]:
    """Gắn "ten_dip" + "nhom_dip" (dung_ten / trung_ngay), tour đúng tên đứng trước. Hỏi "dịp lễ" chung thì xếp theo từng
    dịp, dịp gần nhất trước. Có tour không thuộc dịp nào (nhánh không lọc theo dịp, VD "tour độc lạ") thì giữ nguyên, không gắn nhãn sai."""
    if not all(tour_dung_ten_dip(t, dip) or tour_trung_ngay_dip(t, dip) for t in tours):
        return tours
    if dip.mo_ta != _MO_TA_LE_CHUNG:
        return (
            _gan_nhom([t for t in tours if tour_dung_ten_dip(t, dip)], dip, "dung_ten")
            + _gan_nhom([t for t in tours if not tour_dung_ten_dip(t, dip)], dip, "trung_ngay")
        )
    hom_nay = hom_nay or date.today()
    cac_dip = sorted(
        (d for d in _CAC_DIP_LE if d.mo_ta in _MO_TA_DIP_TRONG_LE_CHUNG),
        key=lambda d: _ngay_gan_nhat_cua_dip(d, hom_nay),
    ) + [dip]  # dip chung cuối cùng: tên chỉ ghi "Tết", không rõ dịp nào
    con_lai, ket_qua = list(tours), []
    # Xét tên trước cả danh sách: tour "Tết Dương Lịch" khởi hành sớm có thể chạm Noel nhưng vẫn phải thuộc Tết Dương lịch.
    dung_ten = {d.mo_ta: [] for d in cac_dip}
    for t in tours:
        d = next((d for d in cac_dip if tour_dung_ten_dip(t, d)), None)
        if d:
            dung_ten[d.mo_ta].append(t)
            con_lai.remove(t)
    for d in cac_dip:
        trung_ngay = [t for t in con_lai if tour_trung_ngay_dip(t, d)]
        con_lai = [t for t in con_lai if not tour_trung_ngay_dip(t, d)]
        ket_qua += _gan_nhom(dung_ten[d.mo_ta], d, "dung_ten") + _gan_nhom(trung_ngay, d, "trung_ngay")
    return ket_qua


def chia_trang_dip(tours: list[dict]) -> tuple[list[dict], list[dict]]:
    """Tách lần hiện này và phần còn lại: chỉ 1 dịp mỗi lần, tối đa 10 thẻ, trong đó tối đa 8 tour đúng tên để luôn còn chỗ
    cho tour trùng ngày (nhóm kia thiếu thì nhóm này được bù cho đủ 10). Thẻ trùng ngày đầu tiên mang "phan_cach_truoc" là
    dòng chữ app hiện cùng thanh ngang. Danh sách không gắn nhãn dịp thì trả nguyên, không chia."""
    if not tours or not tours[0].get("nhom_dip"):
        return tours, []
    ten_dip = tours[0]["ten_dip"]
    cung_dip = [t for t in tours if t["ten_dip"] == ten_dip]
    dip_sau = [t for t in tours if t["ten_dip"] != ten_dip]
    dung_ten = [t for t in cung_dip if t["nhom_dip"] == "dung_ten"]
    trung_ngay = [t for t in cung_dip if t["nhom_dip"] == "trung_ngay"]
    so_trung_ngay = min(len(trung_ngay), SO_THE_DIP_MOI_LAN - min(len(dung_ten), SO_THE_DUNG_TEN_MOI_LAN))
    so_dung_ten = min(len(dung_ten), SO_THE_DIP_MOI_LAN - so_trung_ngay)
    the_trung_ngay = [dict(t) for t in trung_ngay[:so_trung_ngay]]
    if the_trung_ngay:
        the_trung_ngay[0]["phan_cach_truoc"] = (
            f"Ngoài ra, các tour dưới đây có ngày đi trùng {ten_dip}, bạn có thể xem xét thêm:"
            if so_dung_ten else f"Các tour dưới đây có ngày đi trùng {ten_dip}:"
        )
    return dung_ten[:so_dung_ten] + the_trung_ngay, dung_ten[so_dung_ten:] + trung_ngay[so_trung_ngay:] + dip_sau


def hoi_dip_le_chung(cau_hoi: str) -> bool:
    dip = trich_dip_le(cau_hoi)
    return bool(dip and dip.mo_ta == _MO_TA_LE_CHUNG)


_MAU_XEM_TIEP = re.compile(
    r"tiep|tiep tuc|next|(cho )?(xem|hien) (tiep|them)( tour)?|them tour|tour khac|con nua( khong)?|con khong"
    r"|con tour( nao)?( nua| khac)?( khong)?|con tour khac( khong)?"
)
_TU_LICH_SU_KHI_XEM_TIEP = re.compile(r"\b(ban|oi|nhe|nha|di|a|voi|gium|giup|minh|toi|co|ad|ah|vay|the|ko|k)\b")


def hoi_xem_tiep_tour(cau_hoi: str) -> bool:
    """Cả câu chỉ là xin xem tiếp ("tiếp tục", "còn tour nào không"). "còn tour Nhật không" là câu hỏi mới, không phải xem tiếp."""
    kd = re.sub(r"[^\w\s]", " ", bo_dau(unicodedata.normalize("NFC", cau_hoi).lower()))
    kd = re.sub(r"\bko\b|\bk\b", "khong", kd)
    kd = " ".join(_TU_LICH_SU_KHI_XEM_TIEP.sub(" ", kd).split())
    return _MAU_XEM_TIEP.fullmatch(kd) is not None


def _tim_tour_chua_phan_nhom(
    cau_hoi: str, top_k: int = TOP_K_TOURS, lich_su: list[dict] | None = None, goi_y_gia: dict | None = None,
    goi_y_gan_dung: dict | None = None,
) -> list[dict]:
    """goi_y_gia (dict truyền vào để nhận kết quả): khi khách nêu mức giá TỐI ĐA mà không tour nào vừa (kể cả vượt nhẹ),
    hàm trả [] và ghi vào goi_y_gia {"ngan_sach", "diem_den", "tours": vài tour rẻ nhất trong đúng điều kiện} để
    main.py trả lời thẳng "chưa có tour X nào dưới N, tour gần nhất giá …" (bug thật: "tour Hà Nội tầm 10tr" -> không
    đưa gì, trong khi có tour 12,69 triệu).
    goi_y_gan_dung (cũng để nhận kết quả): không tour nào khớp đủ điều kiện nhưng có tour tương tự, xem _tim_tour_gan_dung()."""
    cau_hoi_thuong = cau_hoi.lower()
    if "độc lạ" in cau_hoi_thuong or "doc la" in cau_hoi_thuong:
        return tim_tour_doc_la()

    # "3n2d" = 3 ngày 2 đêm, không phải "2 đồng": bỏ khỏi câu trước khi tìm ngân sách
    cau_hoi_gia = re.sub(r"(?<!\w)\d{1,2}\s*n\s*\d{1,2}\s*[dđ](?!\w)", " ", cau_hoi, flags=re.IGNORECASE)
    khoang_ngan_sach = trich_khoang_ngan_sach(cau_hoi_gia)
    ngan_sach = None if khoang_ngan_sach else trich_ngan_sach(cau_hoi_gia)
    # Câu hỏi không tự nêu số ngân sách nào, nhưng có thể là điều chỉnh TƯƠNG
    # ĐỐI so với ngân sách đã hỏi ở lượt trước ("giảm nửa đi", "tăng lên") —
    # chỉ xét khi có lich_su truyền vào (tránh vỡ các lời gọi cũ/test không
    # có lịch sử). muon_lam_san=True nghĩa là khách chủ động xin ĐẮT HƠN, nên
    # coi số tính được là mức SÀN mới (giống ý nghĩa "trên X") thay vì mức
    # trần mặc định — đối xứng với hoi_muc_san_ngan_sach() đã có.
    muon_lam_san = False
    # True riêng cho nhóm điều chỉnh NHẸ, KHÔNG mốc rõ ("cao hơn chút", "hơn
    # đi") — khác muon_lam_san (bao gồm cả "tăng gấp đôi", vốn CÓ mốc rõ =
    # ngan_sach*2 nên vẫn hợp lý coi là mức sàn cứng). Xem lý do tách riêng ở
    # tim_tour_cao_hon_ngan_sach_goc().
    muon_cao_hon_nhe = False
    # Đối xứng với muon_cao_hon_nhe nhưng cho chiều GIẢM ("thấp hơn chút",
    # "rẻ hơn đi") — cùng lý do tách riêng: không ép ngưỡng nhân tỉ lệ, lấy
    # tour gần ngân sách gốc nhất theo hướng giảm (tim_tour_thap_hon_ngan_sach_goc()).
    muon_thap_hon_nhe = False
    ngan_sach_goc_truoc_dieu_chinh = None
    if ngan_sach is None and not khoang_ngan_sach and lich_su:
        ngan_sach_dieu_chinh = trich_dieu_chinh_ngan_sach(cau_hoi, lich_su)
        if ngan_sach_dieu_chinh is not None:
            ngan_sach = ngan_sach_dieu_chinh
            co_moc_ro = bool(_MAU_GIAM_MOT_NUA.search(cau_hoi_thuong) or _MAU_TANG_GAP_DOI.search(cau_hoi_thuong))
            muon_lam_san = bool(_MAU_TANG_NHE.search(cau_hoi_thuong) or _MAU_TANG_GAP_DOI.search(cau_hoi_thuong))
            # Chỉ coi là "điều chỉnh nhẹ không mốc rõ" khi KHÔNG khớp mốc rõ
            # trước đó — "tăng gấp đôi" chứa sẵn từ "tăng" nên vẫn khớp
            # _MAU_TANG_NHE, phải loại trừ tường minh kẻo đè nhầm lên nhánh
            # mức sàn cứng x2 (bug thật gặp phải khi ghép logic lần đầu). Áp
            # dụng tương tự cho _MAU_GIAM_NHE/_MAU_GIAM_MOT_NUA — "giảm một
            # nửa" cũng chứa từ "giảm" nên khớp cả 2 nhóm nếu không loại trừ.
            # Ưu tiên GIẢM khi câu khớp CẢ 2 mẫu (VD "ít hơn đi" chứa sẵn cụm
            # con "hơn đi" nên vẫn khớp _MAU_TANG_NHE dù ý nghĩa thật là
            # giảm) — nhất quán với thứ tự "if muon_giam" đứng trước trong
            # trich_dieu_chinh_ngan_sach().
            muon_thap_hon_nhe = bool(_MAU_GIAM_NHE.search(cau_hoi_thuong)) and not co_moc_ro
            muon_cao_hon_nhe = (
                bool(_MAU_TANG_NHE.search(cau_hoi_thuong)) and not co_moc_ro and not muon_thap_hon_nhe
            )
            if muon_cao_hon_nhe or muon_thap_hon_nhe:
                ngan_sach_goc_truoc_dieu_chinh = trich_ngan_sach_tu_lich_su(lich_su)
    loai_hinh = trich_loai_hinh(cau_hoi)
    bi_loai = trich_diem_den_bi_loai(cau_hoi)
    la_phu_dinh_diem_den = hoi_phu_dinh_diem_den(cau_hoi)
    if la_phu_dinh_diem_den:
        # Khách nói KHÔNG đi nơi nào đó: không lọc cứng theo nơi đó. Nếu còn đúng 1 điểm đến khác được nêu
        # ("tour Nhật, không đi Thái") thì lọc theo điểm đến ấy.
        con_lai = [d for d in trich_nhieu_diem_den(cau_hoi) if d not in bi_loai]
        diem_den = con_lai[0] if bi_loai and len(con_lai) == 1 else None
    else:
        diem_den = trich_diem_den(cau_hoi)
    thang_khoi_hanh = trich_thang_khoi_hanh(cau_hoi)
    dieu_kien_so_ngay = trich_dieu_kien_so_ngay(cau_hoi)
    bo_loc_ngay = trich_bo_loc_ngay(cau_hoi)  # Tết / Noel / hè / lễ 30-4 / cuối tuần / tuần sau / "ngày 29/11"
    dip_le = trich_dip_le(cau_hoi)
    loc_ten = None if la_phu_dinh_diem_den else trich_tap_theo_ten(cau_hoi)  # "tour Châu Âu", "Đông Nam Á"
    the_loai = trich_the_loai(cau_hoi)  # "tour of the year", "tour cao cấp", MICE, "tour hè", "du lịch xanh"
    if the_loai and not any(thuoc_the_loai(m, the_loai) for m in tat_ca_luot_con_han()):
        # Dữ liệu CHƯA được gắn thể loại này (field `the_loai` chỉ có sau khi
        # đồng bộ lúc backend NestJS bật — xem sync_tours.lay_the_loai_theo_ten).
        # Bỏ qua điều kiện thay vì trả rỗng, để các cách hiểu SẴN CÓ của cùng
        # cụm từ vẫn chạy: "tour hè" -> tour khởi hành mùa hè (bộ lọc ngày),
        # "tour cao cấp" -> tour nửa giá cao, "team building" -> tour phù hợp.
        the_loai = None
    co_gia = bool(khoang_ngan_sach) or ngan_sach is not None or muon_cao_hon_nhe or muon_thap_hon_nhe
    # CÂU NỐI TIẾP: không nêu điểm đến nhưng thêm điều kiện ("dưới 10 triệu thôi", "tháng 12 có đi không") hoặc nói
    # "tour đó" -> hiểu là điểm đến khách vừa hỏi ở các câu trước.
    if lich_su and not (diem_den or bi_loai or loai_hinh or loc_ten or la_phu_dinh_diem_den):
        if co_gia or thang_khoi_hanh or dieu_kien_so_ngay or bo_loc_ngay or _MAU_THAM_CHIEU_TOUR.search(cau_hoi_thuong):
            diem_den = diem_den_tu_lich_su(lich_su, ca_cau_tra_loi=bool(_MAU_THAM_CHIEU_TOUR.search(cau_hoi_thuong)))
    loc_bien = not (diem_den or loc_ten) and hoi_tour_bien(cau_hoi_thuong)
    co_dieu_kien_cung = bool(diem_den or bi_loai or loai_hinh or thang_khoi_hanh or dieu_kien_so_ngay or bo_loc_ngay or loc_ten or the_loai or loc_bien)

    # Hỏi về CÔNG TY (văn phòng, tổng đài...) -> không kèm thẻ tour dù câu có tên thành phố.
    if _co_cum_tu(cau_hoi_thuong, _TU_KHOA_HOI_CONG_TY):
        return []
    # Hỏi THỦ TỤC / CHÍNH SÁCH chung -> AI trả lời thẳng, không kèm thẻ tour.
    # "đi nước ngoài" trong câu hỏi hộ chiếu/visa chỉ là ngữ cảnh thủ tục,
    # không phải yêu cầu tìm tour nước ngoài. Các điều kiện cụ thể khác (điểm
    # đến, giá, ngày, thời lượng...) vẫn cho phép truy xuất tour.
    thu_tuc_chung = _co_cum_tu(cau_hoi_thuong, _TU_KHOA_HOI_THU_TUC)
    if (thu_tuc_chung and not (diem_den or bi_loai or thang_khoi_hanh or dieu_kien_so_ngay or bo_loc_ngay or loc_ten or the_loai or co_gia)) or (
        hoi_chung_ve_tour(cau_hoi) and not (co_dieu_kien_cung or co_gia)
    ):
        return []
    # Nêu rõ một nơi công ty KHÔNG có tour ("tour Nam Cực", "tour Mỹ") -> rỗng, không đưa tour nơi khác như thể khớp.
    if not diem_den and not loc_ten and not la_phu_dinh_diem_den and hoi_diem_den_khong_co_tour(cau_hoi):
        return []

    nhieu_noi_khong_so_sanh = not (co_gia or thang_khoi_hanh or loai_hinh or dieu_kien_so_ngay or la_phu_dinh_diem_den or bo_loc_ngay or loc_ten)
    if hoi_so_sanh_diem_den(cau_hoi) or nhieu_noi_khong_so_sanh:
        # Khách SO SÁNH nhiều điểm đến ("Đà Lạt hay Phú Quốc rẻ hơn") — kiểm
        # tra TRƯỚC nhánh diem_den đơn lẻ, vì trich_diem_den() chỉ trả về 1
        # giá trị (điểm đến dài nhất khớp) nên sẽ bỏ sót vế so sánh còn lại
        # (giới hạn đã biết, xem trich_nhieu_diem_den()). Chỉ tách riêng khi
        # có TỪ 2 điểm đến trở lên — 1 điểm đến duy nhất kèm "hay"/"hơn" vẫn
        # là câu hỏi thường (VD "tour Đà Lạt có rẻ hơn không"), rơi xuống
        # nhánh diem_den bình thường bên dưới.
        cac_diem_den = [d for d in trich_nhieu_diem_den(cau_hoi) if d not in bi_loai]
        if len(cac_diem_den) >= 2:
            return tim_tour_so_sanh(cac_diem_den, top_k_moi_ben=3)

    # TẬP ỨNG VIÊN sau mọi điều kiện CỨNG (đúng/sai tuyệt đối, lọc bằng code trên toàn bộ dữ liệu, không để vector
    # search tự chọn): điểm đến, điểm đến bị loại, loại hình, tháng khởi hành, số ngày. Điều kiện giá áp lên đúng
    # tập này ở bên dưới — nên "Thái Lan dưới 7 triệu", "nước ngoài dưới 10 triệu" không bao giờ lọt tour ngoài
    # điều kiện. Tháng/số ngày lọc TRƯỚC khi dedup theo tên để tour có lượt đúng tháng không bị loại nhầm.
    toan_bo = tat_ca_luot_con_han()
    tap = toan_bo
    if loc_ten:
        tap = [m for m in tap if loc_ten(m) or (diem_den and m["diem_den"] == diem_den)]
    elif diem_den:
        tap = [m for m in tap if m["diem_den"] == diem_den]
    if bi_loai:
        tap = [m for m in tap if m["diem_den"] not in bi_loai]
    tap_noi = tap  # chỉ theo nơi khách hỏi, trước các điều kiện có thể nới khi tìm tour gần đúng
    if loai_hinh:
        tap = [m for m in tap if m["loai_hinh"] == loai_hinh]
    if the_loai:
        tap = [m for m in tap if thuoc_the_loai(m, the_loai)]
    if loc_bien:
        tap = [m for m in tap if la_tour_bien(m)]
    if thang_khoi_hanh:
        tap = loc_theo_thang(tap, thang_khoi_hanh)
    if dieu_kien_so_ngay:
        tap = loc_theo_so_ngay(tap, *dieu_kien_so_ngay)
    if bo_loc_ngay:
        tap = [m for m in tap if bo_loc_ngay(m)]
    if co_dieu_kien_cung and not tap:
        if goi_y_gan_dung is not None and not _co_cum_tu(cau_hoi_thuong, _TU_KHOA_HOI_THU_TUC):
            # Thứ tự trong danh sách là thứ tự nới: số ngày trước, dịp/tháng sau.
            dieu_kien = []
            if dieu_kien_so_ngay:
                dieu_kien.append((_mo_ta_so_ngay(*dieu_kien_so_ngay), lambda t: loc_theo_so_ngay(t, *dieu_kien_so_ngay)))
            if the_loai:
                dieu_kien.append((f"thuộc nhóm {the_loai.lower()}", lambda t: [m for m in t if thuoc_the_loai(m, the_loai)]))
            if loai_hinh:
                dieu_kien.append((loai_hinh.lower(), lambda t: [m for m in t if m["loai_hinh"] == loai_hinh]))
            if loc_bien:
                dieu_kien.append(("đi biển", lambda t: [m for m in t if la_tour_bien(m)]))
            if thang_khoi_hanh:
                dieu_kien.append((f"vào tháng {thang_khoi_hanh}", lambda t: loc_theo_thang(t, thang_khoi_hanh)))
            if bo_loc_ngay:
                dieu_kien.append((_mo_ta_dip(cau_hoi), lambda t: [m for m in t if bo_loc_ngay(m)]))
            gia_tran = ngan_sach if ngan_sach is not None and not (hoi_muc_san_ngan_sach(cau_hoi) or muon_lam_san) else None
            goi_y_gan_dung.update(_tim_tour_gan_dung(
                tap_noi, bool(diem_den or loc_ten or bi_loai), _ten_noi_khach_hoi(cau_hoi, diem_den, tap_noi),
                dieu_kien, dieu_kien_so_ngay, gia_tran,
            ))
        return []
    khong_cat_top_k = False

    gia_giua = None
    if toan_bo:
        gia_giua = statistics.median(min(r["gia"] for r in rs) for rs in _gom_theo_ten(toan_bo).values())

    if khoang_ngan_sach:
        # Khách nêu RÕ 2 đầu khoảng ("từ 8tr đến 12tr") -> lọc đúng khoảng
        # đó, kiểm tra TRƯỚC ngân sách 1 số để tránh bắt nhầm số đầu tiên.
        tours = tim_tour_trong_khoang(*khoang_ngan_sach, top_k, tap)
    elif muon_cao_hon_nhe and ngan_sach_goc_truoc_dieu_chinh is not None:
        # Điều chỉnh NHẸ không mốc rõ ("cao hơn chút", "hơn đi") -> lấy tour
        # GẦN ngân sách gốc nhất theo hướng tăng, KHÔNG ép mức sàn +25% (xem
        # lý do ở tim_tour_cao_hon_ngan_sach_goc() — ép mức sàn từng loại mất
        # đúng các tour "cao hơn chút" gần nhất).
        tours = tim_tour_cao_hon_ngan_sach_goc(ngan_sach_goc_truoc_dieu_chinh, top_k, tap)
    elif muon_thap_hon_nhe and ngan_sach_goc_truoc_dieu_chinh is not None:
        # Đối xứng chiều GIẢM ("thấp hơn chút", "rẻ hơn đi") -> lấy tour GẦN
        # ngân sách gốc nhất theo hướng giảm, KHÔNG ép mức trần *0.75 (xem lý
        # do ở tim_tour_thap_hon_ngan_sach_goc()).
        tours = tim_tour_thap_hon_ngan_sach_goc(ngan_sach_goc_truoc_dieu_chinh, top_k, tap)
    elif ngan_sach is not None and (hoi_muc_san_ngan_sach(cau_hoi) or muon_lam_san):
        # Khách nêu con số làm MỨC SÀN TƯỜNG MINH ("trên 50 triệu", "sang
        # chảnh hơn 20tr") HOẶC vừa xin "tăng gấp đôi" so với ngân sách cũ
        # (muon_lam_san=True, CÓ mốc rõ = ngân sách cũ * 2) -> lấy tour ĐẮT
        # HƠN đúng mức sàn đó, khác hẳn mặc định coi số là mức TRẦN.
        tours = tim_tour_tren_ngan_sach(ngan_sach, top_k, tap)
    elif ngan_sach is not None:
        # Có 1 con số ngân sách (mặc định hiểu là mức TỐI ĐA) -> lọc số học
        # trên toàn bộ dữ liệu theo khoảng cho phép, không dùng vector search
        # (xem lý do ở tài liệu).
        tours = tim_tour_theo_ngan_sach(ngan_sach, top_k, tap)
        if not tours and tap and goi_y_gia is not None:
            gan_nhat = sorted(_dedup_theo_ten([m for m in tap if m["gia"] > ngan_sach]), key=lambda m: m["gia"])[:3]
            if gan_nhat:
                goi_y_gia.update(ngan_sach=ngan_sach, diem_den=diem_den, tours=gan_nhat)
    elif _MAU_RE_NHAT.search(cau_hoi_thuong) or _MAU_DAT_NHAT.search(cau_hoi_thuong):
        # "tour rẻ nhất" / "tour đắt nhất": sắp theo giá trên tập đã lọc, mỗi tour giữ lượt rẻ nhất (hoặc đắt nhất).
        re_nhat = bool(_MAU_RE_NHAT.search(cau_hoi_thuong))
        moi_tour = [(min if re_nhat else max)(rs, key=lambda m: m["gia"]) for rs in _gom_theo_ten(tap).values()]
        return sorted(moi_tour, key=lambda m: m["gia"], reverse=not re_nhat)[:top_k]
    elif gia_giua is not None and _MAU_CAO_CAP.search(cau_hoi_thuong):
        # "tour cao cấp", "sang chảnh" (không kèm số) -> nửa giá cao của bảng giá, đắt trước.
        return sorted(_dedup_theo_ten([m for m in tap if m["gia"] >= gia_giua]), key=lambda m: m["gia"], reverse=True)[:top_k]
    elif gia_giua is not None and _MAU_GIA_RE.search(cau_hoi_thuong):
        # "tour giá rẻ", "tiết kiệm" (không kèm số) -> nửa giá thấp của bảng giá, rẻ trước.
        return sorted(_dedup_theo_ten([m for m in tap if m["gia"] <= gia_giua]), key=lambda m: m["gia"])[:top_k]
    elif dip_le:
        # Hỏi theo dịp lễ -> tour có TÊN đúng dịp đứng trước và luôn hiện đủ (bug thật: vector search xếp ngẫu nhiên
        # rồi cắt 5 làm rớt tour "Đài Loan (Tết Dương Lịch 2027)"); tour chỉ trùng NGÀY lễ cũng hiện đủ, đứng sau.
        tours = sorted(tap, key=lambda m: (not tour_dung_ten_dip(m, dip_le), m["ngay_khoi_hanh"]))
        khong_cat_top_k = True
    elif diem_den or loc_ten:
        # Khách nhắc rõ 1 điểm đến cụ thể -> lọc CỨNG theo điểm đến đó thay
        # vì vector search, kể cả khi câu hỏi còn có ý khác (VD "cần chuẩn
        # bị gì") — không được để vector search tự chọn có thể lẫn tour sai
        # điểm đến. Lấy TOÀN BỘ tour khớp điểm đến (không cắt top_k) để tầng
        # AI biết chính xác có bao nhiêu tour trùng điểm đến cần liệt kê.
        tours = tap
        khong_cat_top_k = True
    elif not hoi_lien_quan_tour(cau_hoi, dieu_kien_cu_the=co_dieu_kien_cung):
        # Không có điều kiện cụ thể nào VÀ câu hỏi không nhắc từ khoá nào liên
        # quan tour/du lịch -> câu chào hỏi thuần tuý ("Xin chào", "Bạn là
        # ai") hoặc hỏi chính sách chung — bug thật: những câu này vẫn bị
        # vector search trả về 5 tour NGẪU NHIÊN, khiến giao diện luôn kèm
        # thẻ tour vô nghĩa. Trả về rỗng để AI tự trả lời, không kèm tour.
        return []
    else:
        # Không có ngân sách -> câu hỏi thuần ngữ nghĩa, dùng vector search.
        # Lấy DƯ nhiều hơn top_k rồi mới dedup — mỗi lượt khởi hành là 1
        # record riêng có embedding GIỐNG HỆT nhau (cùng text_embedding, xem
        # sync_tours.py), nên nếu chỉ xin đúng top_k kết quả, 1 tour nhiều
        # lượt khởi hành sẽ chiếm gần hết/toàn bộ slot, chỉ còn 1 tour duy
        # nhất sau dedup thay vì đa dạng nhiều tour như mong đợi.
        ket_qua = _collection.query(query_texts=[cau_hoi], n_results=top_k * 20)
        tours = [m for m in ket_qua["metadatas"][0] if _con_han(m)]
        if co_dieu_kien_cung:
            # Chỉ giữ kết quả nằm trong tập ứng viên; thiếu thì bổ sung từ chính tập đó (lọc cứng đã chạy ở trên).
            id_hop = {m["id"] for m in tap}
            tours = [t for t in tours if t["id"] in id_hop]
            if len(_dedup_theo_ten(tours)) < top_k:
                da_co = {t["id"] for t in tours}
                tours += sorted((m for m in tap if m["id"] not in da_co), key=lambda m: m["ngay_khoi_hanh"])

    # Khách hỏi về ngày/lịch khởi hành -> giữ ĐẦY ĐỦ mọi lượt của các tour đã
    # khớp (không dedup theo lượt) để trả lời rõ "tour X có ngày A và B". Mọi
    # câu hỏi khác -> dedup về 1 record/tên tour, tránh 1 tour nhiều ngày
    # chiếm hết top_k làm mất đa dạng tour khác (xem _dedup_theo_ten()).
    if hoi_ve_ngay_khoi_hanh(cau_hoi):
        # Vẫn phải giới hạn số TÊN TOUR khác nhau (không giới hạn số lượt/tên)
        # — bug thật gặp phải: điểm đến phổ biến như "Hà Nội" có tới hơn chục
        # TOUR khác nhau, mỗi tour lại nhiều lượt khởi hành -> trả nguyên
        # "tours" không giới hạn khiến khách nhận về HÀNG CHỤC thẻ cùng lúc
        # (hiện gần như toàn bộ dữ liệu), vừa tràn giao diện vừa khiến AI
        # không thể mô tả rõ ràng từng tour. Giữ tối đa top_k TÊN tour khác
        # nhau (ưu tiên tên xuất hiện SỚM NHẤT trong "tours", vì các nhánh
        # trên đã sort theo mức độ liên quan/giá), rồi lấy đủ mọi lượt của
        # đúng các tên đó.
        SO_LUOT_TOI_DA_MOI_TOUR = 3
        ten_giu_lai: list[str] = []
        for t in tours:
            if t["ten"] not in ten_giu_lai:
                if len(ten_giu_lai) >= top_k and not dip_le:  # hỏi theo dịp lễ thì không được sót tour nào
                    continue
                ten_giu_lai.append(t["ten"])

        # Với mỗi tên tour được giữ, chỉ lấy tối đa SO_LUOT_TOI_DA_MOI_TOUR
        # lượt khởi hành GẦN NHẤT — tour có nhiều lượt (VD 6 lượt) vẫn có thể
        # khiến tổng số thẻ vượt 20 nếu ghép với top_k=5 tên tour, tràn giao
        # diện dù đã giới hạn số TÊN. Tour ít lượt (VD Maldives 2 lượt) không
        # bị ảnh hưởng vì đã dưới ngưỡng.
        theo_ten: dict[str, list[dict]] = {}
        for t in tours:
            if t["ten"] in ten_giu_lai:
                theo_ten.setdefault(t["ten"], []).append(t)

        ket_qua = []
        for ten in ten_giu_lai:
            cac_luot = sorted(theo_ten[ten], key=lambda t: t["ngay_khoi_hanh"])
            ket_qua += cac_luot[:SO_LUOT_TOI_DA_MOI_TOUR]
        return ket_qua
    da_dedup = _dedup_theo_ten(tours)
    return da_dedup if khong_cat_top_k else da_dedup[:top_k]
