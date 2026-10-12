import re
import difflib
import unicodedata
import chromadb
from config import CHROMA_PATH, CHROMA_COLLECTION
from rules import TOP_K_TOURS, VUOT_NGAN_SACH_TOI_DA, TEN_TOUR_DOC_LA, ALIAS_DIEM_DEN, TU_KHOA_CAN_NHAN_VIEN

_client = chromadb.PersistentClient(path=CHROMA_PATH)
_collection = _client.get_or_create_collection(CHROMA_COLLECTION)


def _so_sang_dong(so_viet: str, don_vi: str) -> int:
    so = so_viet.replace(",", ".")
    if don_vi and re.match(r"(triệu|trieu|tr)$", don_vi, re.IGNORECASE):
        return int(float(so) * 1_000_000)
    return int(re.sub(r"[.,]", "", so_viet))


def trich_thang_khoi_hanh(cau_hoi: str) -> int | None:
    """Nhận diện khách hỏi theo THÁNG khởi hành cụ thể ("tháng 12", "tháng
    3 năm sau") — bug thật gặp phải: câu "có tour nào khởi hành tháng 12
    không" rơi vào vector search vì không có nhánh lọc riêng, trả về cả tour
    tháng 11, tháng 2 (không phải tháng 12) do vector search chỉ hiểu "tour"
    là từ khoá chính, không hiểu được ràng buộc thời gian chính xác."""
    m = re.search(r"tháng\s*(\d{1,2})|thang\s*(\d{1,2})", cau_hoi, re.IGNORECASE)
    if not m:
        return None
    thang = int(m.group(1) or m.group(2))
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
    r"(trên|tren|tối thiểu|toi thieu|ít nhất|it nhat|trở lên|tro len|"
    r"sang (chảnh|trọng)|cao cấp|cao cap|hạng sang|hang sang|luxury)"
    r"\s*\d*\s*"
    r"(triệu|trieu|tr\b|đồng|dong\b|vnd|vnđ|đ\b|d\b)",
    re.IGNORECASE,
)


def hoi_muc_san_ngan_sach(cau_hoi: str) -> bool:
    return bool(_MAU_MUC_SAN.search(cau_hoi.lower()))


def trich_ngan_sach(cau_hoi: str) -> int | None:
    # Dạng "2 triệu" / "2tr" — số nhỏ, nhân lên thành đồng (kể cả gõ không dấu "2 trieu")
    m = re.search(r"(\d+)\s*(triệu|trieu|tr\b)", cau_hoi, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 1_000_000

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


def tim_tour_trong_khoang(can_duoi: int, can_tren: int, top_k: int) -> list[dict]:
    """Khách đã nêu rõ 2 đầu khoảng -> lọc ĐÚNG khoảng đó."""
    toan_bo = _collection.get()["metadatas"]
    ung_vien = [meta for meta in toan_bo if can_duoi <= meta["gia"] <= can_tren]
    ung_vien.sort(key=lambda meta: meta["gia"])
    # Dedup TRƯỚC khi cắt top_k — mỗi lượt khởi hành là 1 record riêng (xem
    # sync_tours.py), nếu cắt trước dedup thì 1 tour nhiều lượt giá gần nhau
    # có thể chiếm hết top_k, làm mất đa dạng tour khác trong cùng khoảng giá.
    return _dedup_theo_ten(ung_vien)[:top_k]


def tim_tour_theo_ngan_sach(ngan_sach: int, top_k: int) -> list[dict]:
    """Ưu tiên tour GẦN ngân sách nhất trước (rẻ hơn, xét từ dưới lên —
    không nhảy thẳng xuống tour rẻ nhất toàn bộ dữ liệu như bản trước), rồi
    LUÔN dành đúng 1 suất cuối cho tour vượt nhẹ (ngân sách, ngân sách +
    VUOT_NGAN_SACH_TOI_DA] nếu có — vì giá tour thật gồm thuế/phí lẻ nên
    tour sát ngân sách (VD 10tr290 cho ngân sách 10tr) gần như chắc chắn
    đáng giới thiệu, không nên bỏ qua chỉ vì nhỉnh hơn vài trăm nghìn. Chỉ
    khi không đủ tour rẻ hơn mới cần "giảm sâu" xuống các tour rẻ hơn nữa.
    Lọc trên TOÀN BỘ dữ liệu (không qua vector search) vì đây là điều kiện
    số học cần đúng 100%, không phải điều kiện ngữ nghĩa."""
    toan_bo = _collection.get()["metadatas"]

    # Dedup theo tên NGAY TRÊN toàn bộ dữ liệu trước khi xét ngân sách — mỗi
    # lượt khởi hành là 1 record riêng (xem sync_tours.py), không dedup trước
    # thì 1 tour nhiều lượt cùng mức giá sẽ chiếm nhiều vị trí liền kề trong
    # danh sách sort theo giá, đẩy các tour khác ra khỏi top_k.
    toan_bo = _dedup_theo_ten(toan_bo)

    re_hon = sorted(
        (m for m in toan_bo if m["gia"] <= ngan_sach),
        key=lambda m: m["gia"], reverse=True,  # gần ngân sách nhất trước
    )
    vuot_nhe = sorted(
        (m for m in toan_bo if ngan_sach < m["gia"] <= ngan_sach + VUOT_NGAN_SACH_TOI_DA),
        key=lambda m: m["gia"],
    )

    so_suat_vuot_nhe = 1 if vuot_nhe else 0
    ung_vien = re_hon[: top_k - so_suat_vuot_nhe] + vuot_nhe[:so_suat_vuot_nhe]
    ung_vien.sort(key=lambda m: m["gia"])
    return ung_vien[:top_k]


def tim_tour_tren_ngan_sach(muc_san: int, top_k: int) -> list[dict]:
    """Đối xứng với tim_tour_theo_ngan_sach() nhưng cho trường hợp khách nêu
    MỨC SÀN TƯỜNG MINH ("trên X", "tối thiểu X", "sang chảnh hơn X") — lấy
    tour ĐẮT HƠN hoặc bằng muc_san, ưu tiên GẦN mức sàn nhất trước (rẻ nhất
    trong nhóm đạt yêu cầu, thay vì nhảy thẳng lên tour đắt nhất toàn bộ dữ
    liệu). Chỉ dùng khi khách tự nêu số cụ thể làm mốc sàn — với điều chỉnh
    NHẸ suy từ lịch sử ("cao hơn chút"), dùng tim_tour_cao_hon_ngan_sach_goc()
    thay vì hàm này (xem lý do ở đó)."""
    toan_bo = _dedup_theo_ten(_collection.get()["metadatas"])
    ung_vien = sorted(
        (m for m in toan_bo if m["gia"] >= muc_san),
        key=lambda m: m["gia"],  # gần mức sàn nhất trước
    )
    return ung_vien[:top_k]


def tim_tour_cao_hon_ngan_sach_goc(ngan_sach_goc: int, top_k: int) -> list[dict]:
    """Dành riêng cho điều chỉnh NHẸ, KHÔNG rõ mốc ("cao hơn chút", "hơn đi",
    "hơn nữa đi" — nhóm _MAU_TANG_NHE) khi ngan_sach_goc lấy từ lịch sử hội
    thoại. Bug thật gặp phải với cách làm cũ: tính mức sàn cứng = ngan_sach_goc
    * 1.25 rồi lọc "giá >= mức sàn" — với ngân sách gốc 30tr, mức sàn 37.5tr
    LOẠI MẤT chính 2 tour 32.99tr/33.99tr là các tour "cao hơn chút" ĐÚNG Ý
    khách nhất (nằm giữa 30tr và 37.5tr), trong khi khách chỉ muốn xem tour
    nhỉnh hơn ngân sách cũ, không hề đặt ngưỡng +25% làm mốc sàn phải đạt.
    Nên KHÔNG ép ngưỡng nào — chỉ lấy toàn bộ tour giá > ngan_sach_goc, ưu
    tiên GẦN ngan_sach_goc nhất trước (đúng nghĩa "cao hơn chút")."""
    toan_bo = _dedup_theo_ten(_collection.get()["metadatas"])
    ung_vien = sorted(
        (m for m in toan_bo if m["gia"] > ngan_sach_goc),
        key=lambda m: m["gia"],  # gần ngân sách gốc nhất trước
    )
    return ung_vien[:top_k]


def tim_tour_thap_hon_ngan_sach_goc(ngan_sach_goc: int, top_k: int) -> list[dict]:
    """Đối xứng với tim_tour_cao_hon_ngan_sach_goc() cho điều chỉnh NHẸ,
    KHÔNG rõ mốc theo hướng GIẢM ("thấp hơn chút", "rẻ hơn đi", "rẻ nữa đi" —
    nhóm _MAU_GIAM_NHE). Cùng bug với chiều tăng: nhân ngan_sach_goc * 0.75
    rồi lọc "giá <= mức đó" có thể bỏ sót tour NẰM GIỮA ngân sách gốc và mức
    đã nhân (VD gốc 21tr, mức 0.75 = 15.75tr, trong khi tour 20.99tr mới là
    "thấp hơn chút" đúng ý khách nhất lại bị loại vì lớn hơn 15.75tr). Nên
    KHÔNG ép ngưỡng nhân tỉ lệ — chỉ lấy toàn bộ tour giá < ngan_sach_goc, ưu
    tiên GẦN ngan_sach_goc nhất trước."""
    toan_bo = _dedup_theo_ten(_collection.get()["metadatas"])
    ung_vien = sorted(
        (m for m in toan_bo if m["gia"] < ngan_sach_goc),
        key=lambda m: m["gia"], reverse=True,  # gần ngân sách gốc nhất trước
    )
    return ung_vien[:top_k]


def tim_tour_doc_la() -> list[dict]:
    """Không nhận/áp dụng top_k — nhóm tour độc lạ đã cố định 10 tour (không
    phụ thuộc TOP_K_TOURS chung, luôn hiển thị đủ danh sách đã đối chiếu thật)."""
    toan_bo = _collection.get()["metadatas"]
    tours = [m for m in toan_bo if m["ten"] in TEN_TOUR_DOC_LA]
    return _dedup_theo_ten(tours)


def loc_theo_thang(tours: list[dict], thang: int) -> list[dict]:
    """Mỗi record là 1 LƯỢT khởi hành riêng (xem sync_tours.py) nên chỉ cần
    so khớp trực tiếp tháng trong "ngay_khoi_hanh" (format "YYYY-MM-DD")."""
    return [t for t in tours if t["ngay_khoi_hanh"][5:7] == f"{thang:02d}"]


def trich_dieu_kien_so_ngay(cau_hoi: str) -> tuple[str, int] | None:
    """Nhận diện điều kiện về SỐ NGÀY tour ("ít nhất 7 ngày", "dưới 5 ngày",
    "trên 10 ngày", đúng "3 ngày 2 đêm") — bug thật gặp phải: câu "ít nhất
    7 ngày" rơi vào vector search, trả về cả tour 4 ngày (không đạt điều
    kiện) vì vector search không đảm bảo lọc số học chính xác 100%. Trả về
    (toan_tu, so_ngay) với toan_tu là ">=" (tối thiểu/trở lên), "<=" (tối đa/
    dưới), hoặc "==" (đúng N ngày, khi khách nêu rõ dạng "N ngày M đêm")."""
    cau_hoi_thuong = cau_hoi.lower()

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

    return None


def loc_theo_so_ngay(tours: list[dict], toan_tu: str, so_ngay: int) -> list[dict]:
    if toan_tu == ">=":
        return [t for t in tours if t["so_ngay"] >= so_ngay]
    if toan_tu == "<=":
        return [t for t in tours if t["so_ngay"] <= so_ngay]
    return [t for t in tours if t["so_ngay"] == so_ngay]


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
    if "nước ngoài" in cau_hoi_thuong or "quốc tế" in cau_hoi_thuong:
        return "Nước Ngoài"
    if "trong nước" in cau_hoi_thuong or "nội địa" in cau_hoi_thuong:
        return "Trong Nước"
    return None


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


def trich_nhieu_diem_den(cau_hoi: str) -> list[str]:
    """Nhận diện TẤT CẢ điểm đến khách nhắc trong 1 câu (không chỉ 1 cái như
    trich_diem_den) — dùng cho câu SO SÁNH kiểu "Đà Lạt hay Phú Quốc rẻ hơn",
    "so sánh tour Nhật với Hàn". Giới hạn đã biết trước đây: trich_diem_den()
    chỉ trả về 1 giá trị (điểm đến DÀI NHẤT khớp được) nên câu hỏi 2-3 điểm
    đến chỉ tư vấn được đúng 1 nơi, bỏ sót ý so sánh của khách. Duyệt qua
    TOÀN BỘ điểm đến (kể cả alias) và gom mọi cái khớp, giữ thứ tự xuất hiện
    trong câu hỏi (không phải thứ tự trong dữ liệu) để trả lời tự nhiên đúng
    thứ tự khách nêu."""
    cau_hoi_thuong = cau_hoi.lower()
    cau_hoi_khong_dau = bo_dau(cau_hoi_thuong)
    toan_bo = _collection.get()["metadatas"]
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
        vi_tri = cau_hoi_thuong.find(alias)
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
    cau_hoi_thuong = cau_hoi.lower()
    return any(tu in cau_hoi_thuong for tu in _TU_KHOA_SO_SANH)


def tim_tour_so_sanh(cac_diem_den: list[str], top_k_moi_ben: int = 3) -> list[dict]:
    """Lấy tour đại diện cho TỪNG điểm đến trong danh sách so sánh, tách riêng
    theo từng bên (không gộp/dedup xuyên điểm đến) — để tầng AI nhìn thấy rõ
    ràng đủ dữ liệu của mỗi bên mà so sánh giá/thời lượng, thay vì chỉ nhận
    được tour của 1 bên do trich_diem_den() cũ chỉ trả 1 giá trị."""
    toan_bo = _collection.get()["metadatas"]
    ket_qua = []
    for diem_den in cac_diem_den:
        cua_diem_den = _dedup_theo_ten([t for t in toan_bo if t["diem_den"] == diem_den])
        cua_diem_den.sort(key=lambda t: t["gia"])
        ket_qua += cua_diem_den[:top_k_moi_ben]
    return ket_qua


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
    cau_hoi_thuong = cau_hoi.lower()
    toan_bo = _collection.get()["metadatas"]
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
        if alias in cau_hoi_thuong:
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


# Nhận diện khách đang PHỦ ĐỊNH/loại trừ 1 điểm đến (VD "từng đi Đà Nẵng
# rồi, muốn tìm chỗ mới lạ hơn") — bug thật gặp phải: trich_diem_den() vẫn
# bắt được chữ "Đà Nẵng" trong câu rồi lọc CỨNG đúng điểm đến khách vừa nói
# KHÔNG muốn, khiến bot giới thiệu ngược lại đúng nơi khách chê. Chỉ cần
# 1 cụm phủ định xuất hiện BẤT KỲ ĐÂU trong câu là đủ để bỏ qua lọc cứng
# diem_den, nhường cho vector search tự hiểu ngữ nghĩa "muốn nơi khác".
_MAU_PHU_DINH_DIEM_DEN = re.compile(
    r"đã (từng )?đi.{0,20}rồi|da (tung )?di.{0,20}roi|"
    r"không muốn|khong muon|"
    r"(chỗ|noi|nơi) (khác|moi|mới).{0,10}(hơn|hon)|"
    r"(tìm|tim).{0,15}(khác|khac|mới|moi|lạ|la)",
    re.IGNORECASE,
)


def hoi_phu_dinh_diem_den(cau_hoi: str) -> bool:
    return bool(_MAU_PHU_DINH_DIEM_DEN.search(cau_hoi.lower()))


def hoi_muon_gap_nhan_vien(cau_hoi: str) -> bool:
    """Nhận diện khách cần chuyển sang NHÂN VIÊN THẬT thay vì AI tự trả lời
    (xem lý do phân nhóm từ khoá ở TU_KHOA_CAN_NHAN_VIEN, rules.py) — kiểm
    tra bằng so khớp CỤM TỪ đơn giản (không cần regex phức tạp như các hàm
    khác) vì đây là quyết định nhị phân "chuyển hay không", không cần trích
    xuất thêm dữ liệu gì từ câu hỏi."""
    cau_hoi_thuong = cau_hoi.lower()
    return any(tu in cau_hoi_thuong for tu in TU_KHOA_CAN_NHAN_VIEN)


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


def tim_tour_lien_quan(cau_hoi: str, top_k: int = TOP_K_TOURS, lich_su: list[dict] | None = None) -> list[dict]:
    cau_hoi_thuong = cau_hoi.lower()
    if "độc lạ" in cau_hoi_thuong or "doc la" in cau_hoi_thuong:
        return tim_tour_doc_la()

    khoang_ngan_sach = trich_khoang_ngan_sach(cau_hoi)
    ngan_sach = None if khoang_ngan_sach else trich_ngan_sach(cau_hoi)
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
    la_phu_dinh_diem_den = hoi_phu_dinh_diem_den(cau_hoi)
    diem_den = None if la_phu_dinh_diem_den else trich_diem_den(cau_hoi)
    khong_cat_top_k = False

    if hoi_so_sanh_diem_den(cau_hoi):
        # Khách SO SÁNH nhiều điểm đến ("Đà Lạt hay Phú Quốc rẻ hơn") — kiểm
        # tra TRƯỚC nhánh diem_den đơn lẻ, vì trich_diem_den() chỉ trả về 1
        # giá trị (điểm đến dài nhất khớp) nên sẽ bỏ sót vế so sánh còn lại
        # (giới hạn đã biết, xem trich_nhieu_diem_den()). Chỉ tách riêng khi
        # có TỪ 2 điểm đến trở lên — 1 điểm đến duy nhất kèm "hay"/"hơn" vẫn
        # là câu hỏi thường (VD "tour Đà Lạt có rẻ hơn không"), rơi xuống
        # nhánh diem_den bình thường bên dưới.
        cac_diem_den = trich_nhieu_diem_den(cau_hoi)
        if len(cac_diem_den) >= 2:
            return tim_tour_so_sanh(cac_diem_den, top_k_moi_ben=3)

    if diem_den:
        # Khách nhắc rõ 1 điểm đến cụ thể -> lọc CỨNG theo điểm đến đó thay
        # vì vector search, kể cả khi câu hỏi còn có ý khác (VD "cần chuẩn
        # bị gì") — không được để vector search tự chọn có thể lẫn tour sai
        # điểm đến. Lấy TOÀN BỘ tour khớp điểm đến (không cắt top_k ở đây)
        # để tầng gọi Luna biết chính xác có bao nhiêu tour trùng điểm đến
        # cần so sánh/liệt kê rõ, thay vì chỉ thấy 1 phần đã bị cắt bớt.
        # Không cắt top_k trong nhánh này (kể cả sau dedup ở cuối hàm) —
        # xem "khong_cat_top_k" bên dưới.
        toan_bo = _collection.get()["metadatas"]
        tours = [m for m in toan_bo if m["diem_den"] == diem_den]
        khong_cat_top_k = True
    elif khoang_ngan_sach:
        # Khách nêu RÕ 2 đầu khoảng ("từ 8tr đến 12tr") -> lọc đúng khoảng
        # đó, kiểm tra TRƯỚC ngân sách 1 số để tránh bắt nhầm số đầu tiên.
        tours = tim_tour_trong_khoang(*khoang_ngan_sach, top_k)
    elif muon_cao_hon_nhe and ngan_sach_goc_truoc_dieu_chinh is not None:
        # Điều chỉnh NHẸ không mốc rõ ("cao hơn chút", "hơn đi") -> lấy tour
        # GẦN ngân sách gốc nhất theo hướng tăng, KHÔNG ép mức sàn +25% (xem
        # lý do ở tim_tour_cao_hon_ngan_sach_goc() — ép mức sàn từng loại mất
        # đúng các tour "cao hơn chút" gần nhất).
        tours = tim_tour_cao_hon_ngan_sach_goc(ngan_sach_goc_truoc_dieu_chinh, top_k)
    elif muon_thap_hon_nhe and ngan_sach_goc_truoc_dieu_chinh is not None:
        # Đối xứng chiều GIẢM ("thấp hơn chút", "rẻ hơn đi") -> lấy tour GẦN
        # ngân sách gốc nhất theo hướng giảm, KHÔNG ép mức trần *0.75 (xem lý
        # do ở tim_tour_thap_hon_ngan_sach_goc()).
        tours = tim_tour_thap_hon_ngan_sach_goc(ngan_sach_goc_truoc_dieu_chinh, top_k)
    elif ngan_sach is not None and (hoi_muc_san_ngan_sach(cau_hoi) or muon_lam_san):
        # Khách nêu con số làm MỨC SÀN TƯỜNG MINH ("trên 50 triệu", "sang
        # chảnh hơn 20tr") HOẶC vừa xin "tăng gấp đôi" so với ngân sách cũ
        # (muon_lam_san=True, CÓ mốc rõ = ngân sách cũ * 2) -> lấy tour ĐẮT
        # HƠN đúng mức sàn đó, khác hẳn mặc định coi số là mức TRẦN.
        tours = tim_tour_tren_ngan_sach(ngan_sach, top_k)
    elif ngan_sach is not None:
        # Có 1 con số ngân sách (mặc định hiểu là mức TỐI ĐA) -> lọc số học
        # trên toàn bộ dữ liệu theo khoảng cho phép, không dùng vector search
        # (xem lý do ở tài liệu).
        tours = tim_tour_theo_ngan_sach(ngan_sach, top_k)
    elif not hoi_lien_quan_tour(cau_hoi, dieu_kien_cu_the=la_phu_dinh_diem_den):
        # Không có điều kiện cụ thể nào (điểm đến/ngân sách) VÀ câu hỏi không
        # nhắc từ khoá nào liên quan tour/du lịch -> đây là câu chào hỏi
        # thuần tuý ("Xin chào", "Bạn là ai") hoặc hỏi chính sách chung
        # ("Số điện thoại hotline là gì") — bug thật gặp phải: những câu này
        # vẫn bị vector search trả về 5 tour NGẪU NHIÊN không liên quan gì,
        # khiến giao diện luôn kèm thẻ tour vô nghĩa dưới mọi câu trả lời.
        # Trả về rỗng để AI tự trả lời bằng kiến thức chung, không kèm tour.
        return []
    else:
        # Không có ngân sách -> câu hỏi thuần ngữ nghĩa, dùng vector search.
        # Lấy DƯ nhiều hơn top_k rồi mới dedup — mỗi lượt khởi hành là 1
        # record riêng có embedding GIỐNG HỆT nhau (cùng text_embedding, xem
        # sync_tours.py), nên nếu chỉ xin đúng top_k kết quả, 1 tour nhiều
        # lượt khởi hành sẽ chiếm gần hết/toàn bộ slot, chỉ còn 1 tour duy
        # nhất sau dedup thay vì đa dạng nhiều tour như mong đợi.
        ket_qua = _collection.query(query_texts=[cau_hoi], n_results=top_k * 20)
        tours = list(ket_qua["metadatas"][0])

    if loai_hinh:
        # Lọc cứng theo loại hình SAU vector/ngân sách search — nếu vector
        # search trả về ít tour đúng loại hình hơn top_k, tìm bổ sung trên
        # toàn bộ dữ liệu để không bị thiếu kết quả.
        tours = [t for t in tours if t["loai_hinh"] == loai_hinh]
        if len(tours) < top_k:
            # Dedup theo "id" (luôn duy nhất), KHÔNG dùng "ma_tour" — 2 tour
            # khác tên có thể trùng ma_tour (VD 2 tour Trung Quốc khác lịch
            # trình cùng mã gốc "A06.FIT.CN", xem sync_tours.py).
            da_co = {t["id"] for t in tours}
            toan_bo = _collection.get()["metadatas"]
            bo_sung = [
                m for m in toan_bo
                if m["loai_hinh"] == loai_hinh and m["id"] not in da_co
            ]
            tours += bo_sung[: top_k - len(tours)]

    thang_khoi_hanh = trich_thang_khoi_hanh(cau_hoi)
    if thang_khoi_hanh:
        # Lọc cứng theo tháng khởi hành SAU các bước trên — điều kiện đúng/
        # sai tuyệt đối (bug thật gặp phải: "tour khởi hành tháng 12" rơi
        # vào vector search, trả về cả tour tháng 11/tháng 2 không đúng tháng
        # khách hỏi). Nếu nhánh trước (VD lọc theo điểm đến) đã thu hẹp "tours"
        # quá mức trước khi kịp xét tháng, nới ra toàn bộ dữ liệu để không bỏ
        # sót tour đúng tháng — vẫn tôn trọng điểm đến nếu khách có nêu.
        da_loc = loc_theo_thang(tours, thang_khoi_hanh)
        if not da_loc:
            # PHẢI giữ lại mọi điều kiện cứng khác đã xác định khi nới ra
            # toàn bộ dữ liệu (cùng lý do đã sửa ở dieu_kien_so_ngay bên dưới
            # — nới ra mà bỏ mất điều kiện ngân sách là bug thật đã gặp).
            toan_bo = _collection.get()["metadatas"]
            if diem_den:
                toan_bo = [t for t in toan_bo if t["diem_den"] == diem_den]
            if khoang_ngan_sach:
                can_duoi, can_tren = khoang_ngan_sach
                toan_bo = [t for t in toan_bo if can_duoi <= t["gia"] <= can_tren]
            elif ngan_sach is not None and hoi_muc_san_ngan_sach(cau_hoi):
                toan_bo = [t for t in toan_bo if t["gia"] >= ngan_sach]
            elif ngan_sach is not None:
                toan_bo = [t for t in toan_bo if t["gia"] <= ngan_sach + VUOT_NGAN_SACH_TOI_DA]
            da_loc = loc_theo_thang(toan_bo, thang_khoi_hanh)
        tours = da_loc

    dieu_kien_so_ngay = trich_dieu_kien_so_ngay(cau_hoi)
    if dieu_kien_so_ngay:
        # Lọc cứng theo số ngày tour — cùng lý do với tháng khởi hành (bug
        # thật gặp phải: "ít nhất 7 ngày" rơi vào vector search, trả về cả
        # tour 4 ngày không đạt điều kiện).
        toan_tu, so_ngay = dieu_kien_so_ngay
        da_loc = loc_theo_so_ngay(tours, toan_tu, so_ngay)
        if not da_loc:
            # Nhánh trước (VD lọc theo điểm đến/top_k ngân sách) có thể đã
            # thu hẹp "tours" quá mức trước khi kịp xét số ngày -> nới ra
            # toàn bộ dữ liệu, nhưng PHẢI giữ lại mọi điều kiện cứng khác đã
            # xác định (diem_den, ngân sách...) — bug thật gặp phải: nới ra
            # toàn bộ mà chỉ giữ diem_den, làm "mất" luôn điều kiện ngân sách
            # (VD "dưới 10 triệu, ít nhất 5 ngày" trả về cả tour 12.69tr).
            toan_bo = _collection.get()["metadatas"]
            if diem_den:
                toan_bo = [t for t in toan_bo if t["diem_den"] == diem_den]
            if khoang_ngan_sach:
                can_duoi, can_tren = khoang_ngan_sach
                toan_bo = [t for t in toan_bo if can_duoi <= t["gia"] <= can_tren]
            elif ngan_sach is not None and hoi_muc_san_ngan_sach(cau_hoi):
                toan_bo = [t for t in toan_bo if t["gia"] >= ngan_sach]
            elif ngan_sach is not None:
                toan_bo = [t for t in toan_bo if t["gia"] <= ngan_sach + VUOT_NGAN_SACH_TOI_DA]
            da_loc = loc_theo_so_ngay(toan_bo, toan_tu, so_ngay)
        tours = da_loc

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
                if len(ten_giu_lai) >= top_k:
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
