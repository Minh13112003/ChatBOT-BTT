import re
import httpx
import chromadb
from config import (
    BENTHANH_API_BASE, BENTHANH_HEADERS, CATEGORY_IDS_LOAI_HINH,
    CHROMA_PATH, CHROMA_COLLECTION, NESTJS_BASE_URL,
)


BANG_KY_TU_VIET = {
    "à":"a","á":"a","ạ":"a","ả":"a","ã":"a","â":"a","ầ":"a","ấ":"a","ậ":"a","ẩ":"a","ẫ":"a",
    "ă":"a","ằ":"a","ắ":"a","ặ":"a","ẳ":"a","ẵ":"a","è":"e","é":"e","ẹ":"e","ẻ":"e","ẽ":"e",
    "ê":"e","ề":"e","ế":"e","ệ":"e","ể":"e","ễ":"e","ì":"i","í":"i","ị":"i","ỉ":"i","ĩ":"i",
    "ò":"o","ó":"o","ọ":"o","ỏ":"o","õ":"o","ô":"o","ồ":"o","ố":"o","ộ":"o","ổ":"o","ỗ":"o",
    "ơ":"o","ờ":"o","ớ":"o","ợ":"o","ở":"o","ỡ":"o","ù":"u","ú":"u","ụ":"u","ủ":"u","ũ":"u",
    "ư":"u","ừ":"u","ứ":"u","ự":"u","ử":"u","ữ":"u","ỳ":"y","ý":"y","ỵ":"y","ỷ":"y","ỹ":"y","đ":"d",
}


def tao_slug(ten: str) -> str:
    """Sinh slug đúng format thật của benthanhtourist.com/tour/{slug}.
    Đối chiếu trực tiếp với site: tên 'Du Lịch Tây Ninh: Núi Bà Đen - Tòa Thánh...'
    ra đúng slug 'du-lich-tay-ninh-nui-ba-den-toa-thanh...' đã kiểm tra thật."""
    s = ten.lower()
    s = "".join(BANG_KY_TU_VIET.get(ch, ch) for ch in s)
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    s = re.sub(r"\s+", "-", s.strip())
    return re.sub(r"-+", "-", s)


def suy_luan_diem_den(ten: str) -> str:
    """API chi tiết đôi khi trả "destination_place" RỖNG dù tên tour có ghi
    rõ điểm đến (bug thật gặp phải từ phía dữ liệu benthanhtourist.com, đã
    xác nhận qua gọi API trực tiếp — không phải lỗi code: 21 tour trong lần
    đồng bộ 25/9/2026 đều bị rỗng field này, gồm cả tour Nhật Bản, Hàn Quốc,
    Thái Lan, Sri Lanka, Đà Nẵng — khiến trich_diem_den() ở rag.py không lọc
    cứng được, câu hỏi rơi nhầm vào vector search kém chính xác hơn). Tên
    tour luôn theo format "Du Lịch {Điểm đến}{ghi chú tùy chọn}: ..." hoặc
    "Du Lịch {Điểm đến} - ...", nên suy luận trực tiếp từ đó khi API thiếu.
    Chỉ dùng làm PHƯƠNG ÁN DỰ PHÒNG — ưu tiên destination_place thật nếu có."""
    khong_tien_to = re.sub(r"^Du Lịch\s+", "", ten)
    # Cắt tại dấu ":" hoặc " - " đầu tiên (phần trước là điểm đến)
    phan_dau = re.split(r":| - ", khong_tien_to, maxsplit=1)[0]
    # Bỏ ghi chú trong ngoặc, VD "Hàn Quốc (Mùa Thu)" -> "Hàn Quốc"
    phan_dau = re.sub(r"\s*\([^)]*\)", "", phan_dau)
    return phan_dau.strip()


def ma_tour_goc(code: str) -> str:
    """'A06.FIT.72.190926.A' -> 'A06.FIT.72' — chỉ dùng làm TIỀN TỐ hiển thị
    cho khách (field "ma_tour" trong metadata), KHÔNG dùng để gộp/định danh
    tour nữa (xem lý do ở dong_bo())."""
    return ".".join(code.split(".")[:3])


def lay_danh_sach_tour(category_id: int) -> list[dict]:
    """Dò hết các trang phân trang của 1 category."""
    tours, page = [], 1
    while True:
        resp = httpx.get(
            f"{BENTHANH_API_BASE}/category",
            params={"category_id": category_id, "page": page},
            headers=BENTHANH_HEADERS,
            timeout=15,
        )
        payload = resp.json()
        tours.extend(payload["data"])
        if page >= payload["meta"]["last_page"]:
            break
        page += 1
    return tours


def lay_chi_tiet_tour(tour_id: str, so_lan_thu_lai: int = 3) -> dict:
    """Gọi tuần tự nhiều tour liên tiếp đôi khi bị site trả chậm/treo 1 request
    riêng lẻ (ReadTimeout) — thử lại vài lần thay vì crash cả tiến trình."""
    loi_gan_nhat = None
    for lan in range(so_lan_thu_lai):
        try:
            resp = httpx.get(
                f"{BENTHANH_API_BASE}/item",
                params={"tour_key": tour_id},
                headers=BENTHANH_HEADERS,
                timeout=30,
            )
            return resp.json()["data"]
        except httpx.TimeoutException as e:
            loi_gan_nhat = e
            print(f"  ⚠ Timeout tour_key={tour_id}, thử lại ({lan + 1}/{so_lan_thu_lai})...")
    raise loi_gan_nhat


def _chuan_hoa_ten(ten: str) -> str:
    """Khoá so khớp tên tour giữa 2 kho dữ liệu (Laravel và NestJS) — gộp
    khoảng trắng thừa + bỏ phân biệt hoa thường. Bảng Tour bên NestJS được
    seed từ chính benthanhtourist.com nên tên trùng khớp; chỉ cần chống lệch
    khoảng trắng/viết hoa."""
    return " ".join(str(ten or "").split()).casefold()


def lay_the_loai_theo_ten() -> dict[str, str]:
    """Map "tên tour -> thể loại" lấy từ backend NestJS (`GET /api/v1/tours`,
    endpoint công khai không cần token). Thể loại là thứ bên kinh doanh gắn
    ("TOUR OF THE YEAR 2026", "TOUR CAO CẤP", "TOUR MICE"...) và KHÔNG có
    trong dữ liệu Laravel, nên phải lấy từ đây rồi gắn vào ChromaDB.

    Một tour có thể thuộc nhiều thể loại (`tourTypes` là mảng; `tourType` là
    cột cũ 1 giá trị) -> nối bằng "|", rag.thuoc_the_loai() tách lại.

    Không với tới được backend (chưa bật, đổi tunnel, mất mạng) thì trả {}
    và đồng bộ vẫn chạy bình thường với thể loại rỗng — KHÔNG để việc này
    làm hỏng cả lần đồng bộ, vì dữ liệu tour chính vẫn lấy từ Laravel.
    """
    if not NESTJS_BASE_URL:
        print("⚠ Chưa cấu hình NESTJS_BASE_URL — bỏ qua thể loại tour.")
        return {}

    theo_ten: dict[str, str] = {}
    goc = NESTJS_BASE_URL.rstrip("/")
    try:
        trang = 1
        while True:
            resp = httpx.get(
                f"{goc}/api/v1/tours",
                params={"page": trang, "limit": 100},
                headers={"Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            than = payload.get("data", payload) if isinstance(payload, dict) else {}
            muc = than.get("items", than) if isinstance(than, dict) else than
            if not isinstance(muc, list) or not muc:
                break
            for t in muc:
                cac_loai = [str(x).strip() for x in (t.get("tourTypes") or []) if str(x).strip()]
                if not cac_loai and t.get("tourType"):
                    cac_loai = [str(t["tourType"]).strip()]
                if cac_loai:
                    theo_ten[_chuan_hoa_ten(t.get("name"))] = "|".join(cac_loai)
            meta = than.get("meta") if isinstance(than, dict) else None
            if not isinstance(meta, dict) or not meta.get("hasNext"):
                break
            trang += 1
    except Exception as e:
        print(f"⚠ Không lấy được thể loại tour từ NestJS ({type(e).__name__}) — đồng bộ tiếp với thể loại rỗng.")
        return {}

    print(f"Lấy được thể loại cho {len(theo_ten)} tour từ NestJS.")
    return theo_ten


def dong_bo():
    the_loai_theo_ten = lay_the_loai_theo_ten()

    # Bước 1+2 — gom tour thô từ các category loại hình, gộp theo TÊN TOUR
    # (không gộp theo mã gốc cắt từ code — đã kiểm tra dữ liệu thật và phát
    # hiện bug: nhiều tour KHÁC HÀNH TRÌNH lại trùng ngẫu nhiên cùng mã gốc,
    # ví dụ "A06.FIT.92.220926.A/B/C" là 3 tour Miền Tây HOÀN TOÀN khác nhau
    # cùng mã gốc "A06.FIT.92", hay 2 tour Trung Quốc khác lịch trình cùng
    # mã gốc "A06.FIT.CN" — gộp theo code làm mất hẳn 1 trong 2 tour khỏi
    # ChromaDB. Tên tour phản ánh đúng nội dung hành trình nên đáng tin hơn.)
    # Ngày khởi hành KHÔNG lấy từ category listing nữa — mỗi tour ở đó chỉ có
    # ĐÚNG 1 bản ghi/1 ngày (khớp lượt khởi hành đang được đưa lên category
    # hiện tại), trong khi 1 tour thật có thể có NHIỀU lượt khởi hành khác
    # (xem popup "NGÀY KHÁC" trên site). Field đầy đủ nằm ở "tour_days" của
    # API chi tiết (/item) — mỗi phần tử là 1 lượt khởi hành riêng kèm giá/
    # chỗ còn. Lấy ở bước 3 khi đã có chi_tiet, khỏi cần gom ở đây nữa.
    tour_theo_ten: dict[str, dict] = {}
    for category_id, ten_category in CATEGORY_IDS_LOAI_HINH.items():
        for tour_tho in lay_danh_sach_tour(category_id):
            ten = tour_tho["name"]
            if ten not in tour_theo_ten:
                tour_theo_ten[ten] = {
                    "id_dai_dien": tour_tho["id"],  # dùng để gọi chi tiết
                    "ma_goc_dai_dien": ma_tour_goc(tour_tho["code"]),  # chỉ để hiển thị
                    "loai_hinh": ten_category,
                }

    print(f"Tìm thấy {len(tour_theo_ten)} tour (đã gộp theo tên, trùng ngày khởi hành).")

    # Bước 3 — lấy chi tiết từng tour DUY NHẤT, chỉ giữ trường tóm tắt (§5)
    documents, metadatas, ids = [], [], []
    slug_da_dung: dict[str, int] = {}  # đếm số lần trùng slug, xử lý như site thật (hậu tố -1, -2...)
    cach_viet_diem_den: dict[str, str] = {}  # điểm đến viết thường -> cách viết dùng chung

    for ten, info in tour_theo_ten.items():
        chi_tiet = lay_chi_tiet_tour(info["id_dai_dien"])

        # Sinh slug từ tên tour — đúng format benthanhtourist.com/tour/{slug} đã xác nhận thật
        slug = tao_slug(chi_tiet["name"])
        if slug in slug_da_dung:
            slug_da_dung[slug] += 1
            slug = f"{slug}-{slug_da_dung[slug]}"  # trùng tên -> thêm hậu tố, giống site thật
        else:
            slug_da_dung[slug] = 0

        # Ưu tiên destination_place THẬT từ API, chỉ suy luận từ tên khi API
        # trả rỗng (xem lý do ở suy_luan_diem_den()).
        diem_den = chi_tiet["destination_place"] or suy_luan_diem_den(chi_tiet["name"])
        # Website ghi cùng một nơi khác chữ hoa thường ("Vương Quốc Anh" / "Vương quốc Anh", 11/2026): gộp về cách viết gặp đầu tiên,
        # nếu không khách hỏi "tour Anh" chỉ thấy tour của một cách viết.
        diem_den = cach_viet_diem_den.setdefault(" ".join(diem_den.split()).casefold(), " ".join(diem_den.split()))

        # [GEMINI] T-002: Lấy URL ảnh đại diện đầy đủ từ API chi tiết
        anh_raw = chi_tiet.get("image") or (chi_tiet.get("images")[0] if chi_tiet.get("images") else "") or ""
        if anh_raw and isinstance(anh_raw, str):
            anh_raw = anh_raw.strip()
            if anh_raw.startswith("//"):
                anh_raw = f"https:{anh_raw}"
            elif anh_raw.startswith("/"):
                anh_raw = f"https://benthanhtourist.com{anh_raw}"
            elif not anh_raw.startswith("http"):
                anh_raw = f"https://benthanhtourist.com/{anh_raw}"
        else:
            anh_raw = ""

        # Text để tạo embedding — mô tả ngắn giúp vector search hiểu ngữ nghĩa
        mo_ta = re.sub("<[^>]+>", " ", chi_tiet.get("featured_description", ""))
        text_embedding = (
            f"{chi_tiet['name']}. Điểm đến: {diem_den}. "
            f"Loại hình: {info['loai_hinh']}. {mo_ta}"
        )

        # "tour_days" của API chi tiết là danh sách ĐẦY ĐỦ các lượt khởi hành
        # thật (khớp popup "NGÀY KHÁC" trên site) — mỗi lượt có ngày/giá/chỗ
        # RIÊNG, khác hẳn category listing vốn chỉ có 1 lượt/tour. Mỗi lượt
        # được lập 1 metadata record RIÊNG (không gộp chung 1 field như trước)
        # để rag.py trả lời đúng câu hỏi "tour X còn ngày nào khác" — liệt kê
        # được rõ giá/ngày của TỪNG lượt thay vì chỉ 1 con số gộp mập mờ. Chỉ
        # giữ lượt còn chỗ (is_available + stock_qty > 0), lượt hết chỗ/đã
        # qua không còn ý nghĩa để tư vấn.
        cac_luot_con_cho = [
            d for d in chi_tiet.get("tour_days", [])
            if d.get("is_available") and d.get("stock_qty", 0) > 0
        ]
        # Đợt khởi hành ở CẤP GỐC của /api/tour/item (đợt gần nhất) có thể KHÔNG nằm trong tour_days[] (dữ liệu
        # Laravel hay lệch) — luồng đặt tour (dat_tour.cac_dot_khoi_hanh) có gộp đợt này, nên thẻ tour cũng phải có,
        # nếu không thẻ hiện ngày/giá khác với lúc đặt (vd Hokkaido thẻ 04/01/2027 60,99tr, lúc đặt có 07/12/2026 58,99tr).
        goc_con_cho = chi_tiet.get("is_available") and (chi_tiet.get("stock_qty") or 0) > 0
        ngay_goc = str(chi_tiet.get("departure_date") or "")[:10]
        if goc_con_cho and ngay_goc and ngay_goc not in {str(d.get("departure_date") or "")[:10] for d in cac_luot_con_cho}:
            cac_luot_con_cho.append({
                "id": chi_tiet.get("id"),
                "departure_date": chi_tiet["departure_date"],
                "price": chi_tiet["price"],
                "stock_qty": chi_tiet.get("stock_qty", 0),
            })
        # Phòng trường hợp tour không còn lượt nào (hết chỗ toàn bộ) — vẫn lập
        # 1 record với ngày/giá của id_dai_dien để không mất tour khỏi ChromaDB.
        # Lưu ý: "tour_days" rỗng KHÔNG đồng nghĩa hết chỗ — đã xác nhận bug
        # thật từ API (VD tour "Hàn Quốc (Mùa Thu): ...Tháp Namsan" ngày
        # 30/9/2026: tour_days=[] dù is_available/stock_qty gốc vẫn còn 9 chỗ
        # thật trên site) nên KHÔNG mặc định stock_qty=0 ở đây — lấy đúng
        # is_available/stock_qty cấp gốc của chi_tiet làm phương án dự phòng.
        if not cac_luot_con_cho:
            cac_luot_con_cho = [{
                "departure_date": chi_tiet["departure_date"],
                "price": chi_tiet["price"],
                "stock_qty": chi_tiet.get("stock_qty", 0) if chi_tiet.get("is_available") else 0,
            }]

        for luot in cac_luot_con_cho:
            # id của từng LƯỢT khởi hành (không phải id_dai_dien của tour) —
            # đảm bảo duy nhất per lượt, cần thiết vì giờ 1 tour ứng nhiều record.
            id_duy_nhat = str(luot.get("id") or info["id_dai_dien"])
            if id_duy_nhat in ids:
                id_duy_nhat += "-goc"  # id đợt cấp gốc trùng id một đợt tour_days (hiếm) -> vẫn phải duy nhất
            ids.append(id_duy_nhat)
            documents.append(text_embedding)
            metadatas.append({
                "id": id_duy_nhat,  # dùng làm key/dedup ở rag.py + Vue :key
                # [GEMINI] T-002: Thêm tour_key và ảnh đại diện vào metadata
                "tour_key": str(info["id_dai_dien"]),
                "anh": str(anh_raw),
                "ma_tour": info["ma_goc_dai_dien"],
                "ten": chi_tiet["name"],
                "url": f"https://benthanhtourist.com/tour/{slug}",
                "gia": luot["price"],
                "so_ngay": chi_tiet["days"],
                "diem_den": diem_den,
                "loai_hinh": info["loai_hinh"],
                "ngay_khoi_hanh": luot["departure_date"],
                # Chỗ còn lại của ĐÚNG lượt này — dùng hiển thị "chỉ còn X chỗ"
                # để tạo cảm giác khan hiếm/thúc đẩy đặt sớm (0 nếu tour rơi vào
                # nhánh "hết chỗ toàn bộ" ở trên, không có field stock_qty thật).
                "so_cho_con": luot.get("stock_qty", 0),
                # Thể loại kinh doanh gắn cho tour (nguồn NestJS, nối bằng "|").
                # Rỗng khi backend không với tới được lúc đồng bộ — rag.py coi
                # như tour chưa được xếp thể loại, không làm hỏng tìm kiếm khác.
                "the_loai": the_loai_theo_ten.get(_chuan_hoa_ten(chi_tiet["name"]), ""),
            })

    # Ghi vào ChromaDB: upsert lượt mới rồi XOÁ các id không còn (lượt hết chỗ / bị huỷ / tour bị ẩn), nếu không chúng nằm lại làm rác
    # (bug thật: record cũ dùng id_dai_dien gộp nhiều ngày còn sót song song với record mới). Trước đây xoá cả kho rồi tạo lại, nhưng
    # chatbot chạy trên VPS tự đồng bộ hằng ngày trong lúc đang phục vụ khách: kho bị xoá giữa chừng thì câu hỏi lúc đó lỗi
    # "Collection does not exist" (gặp khi thử 2026-11-26). Giữ nguyên kho thì không có khoảng trống đó.
    if not ids:
        raise RuntimeError("API không trả tour nào, giữ nguyên dữ liệu cũ")
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(CHROMA_COLLECTION)
    id_cu = set(collection.get(include=[])["ids"])
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    bo_di = sorted(id_cu - set(ids))
    if bo_di:
        collection.delete(ids=bo_di)

    print(f"Đã lập chỉ mục {len(ids)} tour vào ChromaDB (bỏ {len(bo_di)} lượt không còn).")


if __name__ == "__main__":
    dong_bo()
