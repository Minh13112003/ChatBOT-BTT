"""Chặn câu hỏi không liên quan du lịch TRƯỚC khi gọi Gemini (chủ dự án yêu cầu 2026-11-25): giải toán, lý, hoá, bài tập, viết code,
tài chính / đầu tư, chính trị, cờ bạc, ma tuý, vũ khí, hack, lừa đảo... Trả câu viết sẵn, không tốn lượt AI, không kèm thẻ tour.

Học tập, lập trình, phạm pháp: chặn cả khi câu có nhắc tour. Tài chính, chính trị, phép tính, vũ khí: câu có nhắc du lịch (tour, khách sạn,
visa, điểm đến...) thì không chặn, để AI trả lời phần du lịch (xem NHOM_LUON_CHAN). Khớp theo chữ không dấu, chữ thường, theo ranh giới từ. Từ chửi tục do moderation.py lo, không ở đây."""
import re
import unicodedata

from rag import bo_dau, trich_diem_den

TRA_LOI_NGOAI_PHAM_VI = (
    "Mình là trợ lý tour của BenThanh Tourist nên chỉ hỗ trợ được các câu hỏi về du lịch, tour và dịch vụ của công ty thôi ạ. "
    "Bạn đang muốn đi đâu hay cần tư vấn tour nào, mình hỗ trợ ngay nhé!"
)
TRA_LOI_TU_HAI = (
    "Mình rất tiếc khi bạn đang cảm thấy như vậy. Bạn không phải một mình đâu: hãy nói chuyện ngay với người thân hoặc bạn bè bạn tin tưởng. "
    "Nếu đang gặp nguy hiểm, bạn gọi ngay cấp cứu 115 nhé."
)

_NHOM = {
    # Bài tập, học thuật
    "HOC_TAP": r"giai (?:giup |ho |dum |gium )?(?:bai|phuong trinh|he phuong trinh|de|toan|ly|hoa)|bai tap|phuong trinh|dao ham|tich phan|"
               r"nguyen ham|logarit|ma tran|luong giac|hinh hoc|dinh ly|dinh luat|vat ly|hoa hoc|sinh hoc|cong thuc hoa|phan ung hoa|"
               r"can bang phuong trinh|so mol|nguyen tu khoi|bai van|viet van|nghi luan|soan bai|"
               r"tieng anh lop|ngu phap|lam (?:bai|de) thi|dap an de",
    # Lập trình, máy tính ("java" không chặn: đảo Java của Indonesia)
    "LAP_TRINH": r"viet (?:code|chuong trinh|ham|script)|lap trinh|python|javascript|sql|html|css|reactjs|nodejs|debug|"
                 r"thuat toan|sua loi code|code (?:giup|dum|gium)",
    # Tài chính, đầu tư
    "TAI_CHINH": r"chung khoan|co phieu|trai phieu|crypto|bitcoin|btc|eth|tien ao|tien dien tu|forex|dau tu (?:vao|gi|dat|tien)|"
                 r"lai suat|vay (?:tien|von|the chap|tin chap)|gia vang|mua vang|vang mieng|vang sjc|bat dong san|mua dat|"
                 r"quy dau tu|lam giau|kiem tien online|bao hiem nhan tho",
    # Chính trị, nhạy cảm ("chiến tranh" không chặn: Bảo tàng Chứng tích Chiến tranh; "chế độ", "báo động" trùng câu thường)
    "CHINH_TRI": r"chinh tri|dang cong san|tong bi thu|chu tich nuoc|thu tuong|quoc hoi|bau cu|bieu tinh|phan dong|"
                 r"nhan quyen|tranh chap bien dong",
    # Phạm pháp, nguy hiểm ("bảng giá" bỏ dấu trùng "bằng giả" nên không dùng)
    "PHAM_PHAP": r"ma tuy|thuoc lac|can sa|heroin|ke da|sung (?:dan|ngan|truong)|mua sung|che tao bom|lam bom|thuoc no|hack|"
                 r"tan cong mang|lua dao (?:the nao|sao cho|nguoi)|rua tien|lam gia giay to|giay to gia|lam bang gia|ca do|ca cuoc|lo de|"
                 r"danh bai an tien|cho vay nang lai|tin dung den|mua ban nguoi|mai dam|gai goi|sex|khieu dam|phim nguoi lon",
}
_MAU_NHOM = {ten: re.compile(rf"\b(?:{m})\b") for ten, m in _NHOM.items()}
# Nhóm chặn cả khi câu có nhắc du lịch ("viết code cào giá tour", "tour Nhật xong giải giúp bài toán"): không có cách hiểu nào là hỏi tour.
# Tài chính, chính trị, phép tính, vũ khí thì câu có nhắc du lịch vẫn có thể là câu hỏi thật ("3 người x 15 triệu là bao nhiêu",
# "Triều Tiên có bất ổn chính trị không", "mang vũ khí / dao lên máy bay được không") nên chỉ chặn khi câu không nói về du lịch.
NHOM_LUON_CHAN = ("HOC_TAP", "LAP_TRINH", "PHAM_PHAP")
_MAU_VU_KHI = re.compile(r"\bvu khi\b")
# So CÓ DẤU: bỏ dấu thì "tự tử" trùng "từ từ"; không dùng "muốn chết" (khách hay nói "nóng muốn chết").
_MAU_TU_HAI = re.compile(r"(?<!\w)(?:tự tử|tự sát|không muốn sống nữa|chẳng muốn sống nữa|kết liễu bản thân|kết liễu đời)(?!\w)")
# Phép tính kiểu "12 x 7 bằng mấy", "(3+5)*2 = ?"
_MAU_PHEP_TINH = re.compile(r"\d+\s*[+\-*/x:^]\s*\d+.*(?:bang may|bang bao nhieu|=\s*\?|ket qua)|\d+\s*[+\-*/^]\s*\d+\s*=\s*\??\s*$")
# Dấu hiệu câu đang nói về du lịch: không chặn, để AI trả lời.
_MAU_DU_LICH = re.compile(
    r"\b(?:tour|du lich|di choi|chuyen di|lich trinh|khach san|resort|homestay|ve may bay|visa|ho chieu|passport|dat cho|"
    r"khoi hanh|benthanh|ben thanh|huong dan vien|hdv|nghi duong|tham quan|check ?in|di nuoc ngoai)\b"
)


def phan_loai(cau_hoi: str) -> str | None:
    """"TU_HAI" (câu có ý tự làm hại, luôn ưu tiên), tên nhóm ngoài phạm vi, hoặc None nếu được hỏi AI."""
    co_dau = re.sub(r"\s+", " ", unicodedata.normalize("NFC", cau_hoi or "").lower()).strip()
    if _MAU_TU_HAI.search(co_dau):
        return "TU_HAI"
    t = bo_dau(co_dau)
    for ten in NHOM_LUON_CHAN:
        if _MAU_NHOM[ten].search(t):
            return ten
    if _MAU_DU_LICH.search(t) or trich_diem_den(cau_hoi):
        return None
    if _MAU_PHEP_TINH.search(t):
        return "HOC_TAP"
    if _MAU_VU_KHI.search(t):
        return "PHAM_PHAP"
    for ten, mau in _MAU_NHOM.items():
        if mau.search(t):
            return ten
    return None


def cau_tra_loi(loai: str) -> str:
    return TRA_LOI_TU_HAI if loai == "TU_HAI" else TRA_LOI_NGOAI_PHAM_VI
