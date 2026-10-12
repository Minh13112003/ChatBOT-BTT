import re
import unicodedata
from rules import TU_KHOA_CAM_DE_TRUNG_TU_THUONG, TU_KHOA_CAM_AN_TOAN


def chuan_hoa(text: str) -> str:
    """Bỏ dấu tiếng Việt, chữ thường, gộp khoảng trắng — chặn kiểu né filter
    'đ.m', 'd  m', 'Đ.Ị.T'. Dùng cho câu hỏi và cho TU_KHOA_CAM_AN_TOAN."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def chuan_hoa_giu_dau(text: str) -> str:
    """Chữ thường, gộp khoảng trắng, bỏ ký tự chèn giữa để né filter kiểu
    "đ. ụ" — nhưng GIỮ NGUYÊN dấu thanh, để "đụ" không lẫn với "du"."""
    text = text.lower()
    text = re.sub(r"[^a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ0-9\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


# Chuẩn hoá sẵn danh sách từ khoá cấm 1 lần khi nạp module — phải chuẩn hoá
# cả 2 bên (từ khoá lẫn câu hỏi) theo CÙNG 1 cách, nếu không sẽ không bao
# giờ khớp đúng (bug thật gặp phải: "địt" có dấu không khớp "dit" đã chuẩn
# hoá bỏ dấu).
_TU_KHOA_DE_TRUNG_DA_CHUAN_HOA = {chuan_hoa_giu_dau(tu) for tu in TU_KHOA_CAM_DE_TRUNG_TU_THUONG}
_TU_KHOA_AN_TOAN_DA_CHUAN_HOA = {chuan_hoa(tu) for tu in TU_KHOA_CAM_AN_TOAN}


def _khop_tu_khoa(da_chuan_hoa: str, tu_rieng: list[str], tap_tu_khoa: set[str]) -> bool:
    """So khớp theo TỪ/CỤM TỪ NGUYÊN VẸN, không so substring tự do trong cả
    chuỗi — so substring tự do khiến từ khoá ngắn như "ngu" khớp nhầm vào
    giữa từ vô hại (VD "ngu" nằm trong "người" sau khi bỏ dấu thành "nguoi").
    Từ khoá NHIỀU TỪ (VD "óc chó") cũng phải neo theo RANH GIỚI TỪ ở cả 2 đầu
    bằng \\b trong regex, không chỉ kiểm tra "tu_khoa in da_chuan_hoa" — bug
    thật gặp phải: câu "...Phú Qu[ốc ch]o gia đình..." sau khi bỏ dấu thành
    "...quoc cho...", vô tình chứa ĐÚNG substring "oc cho" ở giữa 2 từ "quốc"
    và "cho" hoàn toàn vô hại, bị chặn nhầm thành từ cấm "óc chó" dù không hề
    có ranh giới từ nào khớp thật. \\b của regex chỉ nhận biên from
    word-char/non-word-char nên cụm phải đứng ĐỘC LẬP (có khoảng trắng/đầu-
    cuối chuỗi bao quanh), không được là 1 phần nằm giữa 2 từ khác."""
    return any(
        # Từ khoá 1 từ -> khớp đúng 1 từ trong câu (so trong tập từ đã tách,
        # nhanh hơn regex và không cần lo ranh giới vì đã tách sẵn theo \s).
        # Từ khoá nhiều từ (VD "óc chó") -> so cụm NHƯNG neo \b ở 2 đầu.
        tu_khoa in tu_rieng if " " not in tu_khoa
        else re.search(rf"\b{re.escape(tu_khoa)}\b", da_chuan_hoa) is not None
        for tu_khoa in tap_tu_khoa
    )


def co_noi_dung_nhay_cam(cau_hoi: str) -> bool:
    da_chuan_hoa = chuan_hoa(cau_hoi)
    if _khop_tu_khoa(da_chuan_hoa, da_chuan_hoa.split(), _TU_KHOA_AN_TOAN_DA_CHUAN_HOA):
        return True

    da_chuan_hoa_giu_dau = chuan_hoa_giu_dau(cau_hoi)
    return _khop_tu_khoa(da_chuan_hoa_giu_dau, da_chuan_hoa_giu_dau.split(), _TU_KHOA_DE_TRUNG_DA_CHUAN_HOA)
