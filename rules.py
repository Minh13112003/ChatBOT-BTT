"""File TRUNG TÂM chứa toàn bộ luật nghiệp vụ / hằng số bạn hay chỉnh tay khi
tinh chỉnh hành vi bot — gom lại 1 chỗ thay vì rải rác ở rag.py, moderation.py,
llm_luna.py, llm_gemini.py, config.py như trước, để sửa 1 rule không phải mò
nhiều file (và tránh bug prompt bị copy trùng, sửa 1 chỗ quên chỗ kia).

config.py vẫn giữ riêng: API key/URL, tên model, đường dẫn DB — đó là cấu hình
hạ tầng (đổi theo môi trường), khác bản chất với luật nghiệp vụ ở đây.
"""

# ═══════════════════════════════════════════════════════════════════════
# TÌM KIẾM / GỢI Ý TOUR (rag.py)
# ═══════════════════════════════════════════════════════════════════════

TOP_K_TOURS = 5  # số tour lấy ra mỗi lượt hỏi — xem phép tính chi phí ở §7

# Khách nói "ngân sách X" thường có nghĩa là mức TỐI ĐA họ sẵn sàng chi —
# nên ưu tiên tour RẺ HƠN X (không giới hạn cận dưới, khách luôn vui vẻ nếu
# rẻ hơn), chỉ cho phép vượt nhẹ (VUOT_NGAN_SACH_TOI_DA) để không bỏ sót
# tour gần đúng ngân sách vì giá tour thật gồm thuế/phí lẻ (không tròn số).
VUOT_NGAN_SACH_TOI_DA = 500_000

# "Tour độc lạ" là 1 trang landing page riêng trên benthanhtourist.com, KHÔNG
# phải category hay field có trong 3 API công khai (đã kiểm tra: 120 category
# không có tên "độc lạ", chi tiết tour cũng không có field tag/is_special).
# Admin tick chọn tay tour nào hiển thị ở trang đó — không có cách tự động
# suy ra từ dữ liệu API, nên set cứng tạm danh sách TÊN tour đã đối chiếu
# thật từ https://benthanhtourist.com/tour-doc-la (đối chiếu lại 21/9/2026,
# đủ cả 10/10 tour trên trang thật). Dùng TÊN thay vì mã tour gốc vì mã gốc
# không còn duy nhất (2 tour có thể trùng mã gốc nhưng khác tên — VD 2 tour
# Maldives cùng mã "A06.FIT.MV"). Cần cập nhật tay nếu site đổi danh sách —
# đây là giới hạn đã biết của bản demo này.
TEN_TOUR_DOC_LA = {
    "Du Lịch Châu Âu (Khám Phá Di Sản Baltic): Đan Mạch - Thụy Điển - Lithuania - Latvia - Estonia - Phần Lan",
    "Du Lịch Indonesia: Trekking Ngắm Núi Lửa Bromo - Hồ Axit Ijen Xanh Ngọc - Thác Tumpak Sewu - Royal Brunei Airlines",
    "Du Lịch Maldives: Bơi Cùng Cá Mập Hiền Hòa - Ngắm Xác Tàu Đắm - Nghỉ Dưỡng 01 Đêm Water Villa",
    "Du Lịch Maldives: Bơi Cùng Cá Mập Hiền Hòa - Ngắm Xác Tàu Đắm - Trải Nghiệm Resort Maldives 01 Ngày",
    "Du Lịch Sri Lanka: Safari Jeep Hoang Dã - 2 Cung Tàu Hỏa Ấn Tượng - Massage Dược Liệu - Nghỉ Dưỡng Resort Biển",
    "Du Lịch Pakistan (Sắc Thu Huyền Thoại): Skardu - Hunza - Passu - Karimabad - Sa Mạc Lạnh - Sông Băng",
    "Du Lịch Balkans: Thụy Sĩ - Đức - Áo - Slovenia - Croatia - Bosnia & Herzegovina - Montenegro - Serbia - Hungary",
    "Du Lịch Bắc Âu: Săn Bắc Cực Quang - Trải Nghiệm Tàu Phá Băng (Helsinki - Rovaniemi - Saariselka)",
    "Du Lịch Bắc Âu: Hành Trình Săn Bắc Cực Quang - Trải Nghiệm Tàu Phá Băng - Săn Cua Huỳnh Đế (Na Uy - Phần Lan)",
    "Du Lịch Indonesia: Yogyakarta - Borobudur - Dieng - Prambanan - Hành Trình Di Sản Bằng Tàu Hỏa",
}


# Dữ liệu "diem_den" đồng bộ từ benthanhtourist.com dùng TÊN TỈNH (Lâm Đồng,
# Khánh Hòa, Bình Thuận, Kiên Giang...), trong khi khách hàng thực tế hầu như
# luôn gọi bằng TÊN THÀNH PHỐ/địa danh du lịch nổi tiếng (Đà Lạt, Nha Trang,
# Phan Thiết/Mũi Né, Phú Quốc) — bug thật gặp phải: khách hỏi "đi Đà Lạt" bị
# trich_diem_den() trả về None vì "Đà Lạt" không khớp chuỗi "Lâm Đồng", khiến
# câu hỏi rơi nhầm vào vector search và trả về tour hoàn toàn không liên quan
# (Thái Lan, do embedding bắt nhầm chữ "Lat" trong "Khlong Lat Mayom"). Bảng
# này ánh xạ alias phổ biến -> tên diem_den THẬT trong dữ liệu, dùng ở
# trich_diem_den() (rag.py) để chuẩn hoá trước khi so khớp. Cần bổ sung thêm
# nếu phát hiện điểm đến khác cũng bị lệch tên tỉnh/thành tương tự.
ALIAS_DIEM_DEN = {
    "đà lạt": "Lâm Đồng",
    "da lat": "Lâm Đồng",
    "nha trang": "Khánh Hòa",
    "phan thiết": "Bình Thuận",
    "phan thiet": "Bình Thuận",
    "mũi né": "Bình Thuận",
    "mui ne": "Bình Thuận",
    "phú quốc": "Kiên Giang",
    "phu quoc": "Kiên Giang",
    "hạ long": "Hà Nội",  # tour Hạ Long trong dữ liệu hiện đi ghép cùng lịch trình Hà Nội
    "ha long": "Hà Nội",
}


# Sau đợt sắp xếp đơn vị hành chính có hiệu lực 12/6/2025 (Nghị quyết 202/2025/
# QH15), nhiều tỉnh cũ đã hợp nhất thành tỉnh mới — nhưng dữ liệu "diem_den"
# đồng bộ từ benthanhtourist.com KHÔNG nhất quán: có tour dùng tên tỉnh MỚI
# (VD tour Đắk Nông ghi diem_den="Lâm Đồng" vì Đắk Nông đã sáp nhập vào Lâm
# Đồng), có tour vẫn dùng tên tỉnh CŨ (VD tour Phan Thiết vẫn ghi diem_den=
# "Bình Thuận" dù Bình Thuận cũng đã sáp nhập vào Lâm Đồng) — bug thật gặp
# phải: khách hỏi "tour Đà Lạt" nhận về cả tour "Đắk Nông - Hồ Tà Đùng" mà
# không hiểu vì sao, tưởng nhầm lẫn dữ liệu trong khi thực chất Đắk Nông giờ
# thuộc đúng tỉnh Lâm Đồng (mới) sau sáp nhập. Bảng này CHỈ liệt kê các cặp
# tỉnh cũ->mới có liên quan trực tiếp tới dữ liệu tour hiện có (không cần
# liệt kê đủ 34 tỉnh thành cả nước) — dùng để AI (LUAT_CO_DINH) chủ động giải
# thích thay vì im lặng để khách tự thắc mắc. Cập nhật thêm nếu phát hiện
# tỉnh sáp nhập khác cũng xuất hiện trong dữ liệu tour.
TINH_SAP_NHAP = {
    "Lâm Đồng": ["Lâm Đồng (cũ)", "Đắk Nông", "Bình Thuận"],
    "Khánh Hòa": ["Khánh Hòa (cũ)", "Ninh Thuận"],
    "Kiên Giang": ["An Giang (cũ)", "Kiên Giang (cũ)"],  # tỉnh mới "An Giang" = An Giang cũ + Kiên Giang cũ
}


# ═══════════════════════════════════════════════════════════════════════
# RATE LIMIT / LỊCH SỬ HỘI THOẠI (database.py, main.py)
# ═══════════════════════════════════════════════════════════════════════

# 3 lớp rate limit theo thời gian — xem lý do chọn từng con số ở §8.2
RATE_LIMIT_PER_MINUTE = 6
RATE_LIMIT_PER_HOUR = 40
RATE_LIMIT_PER_DAY = 120

# Time-check khoảng cách giữa 2 câu hỏi liên tiếp — xem §8.2b
MIN_GIAY_GIUA_2_CAU_HOI = 2
THOI_GIAN_KHOA_GIAY = 60

MAX_HISTORY_TURNS = 4  # số lượt hỏi-đáp gần nhất gửi lại cho AI, xem §8


# ═══════════════════════════════════════════════════════════════════════
# HANDOFF SANG NHÂN VIÊN THẬT (rag.py, main.py)
# ═══════════════════════════════════════════════════════════════════════

# Link Zalo nhân viên CSKH thật — dùng khi AI không nên tự quyết (khiếu nại,
# hoàn tiền, huỷ tour, sự cố...) thay vì cố trả lời rồi có thể sai chính sách.
ZALO_NHAN_VIEN_URL = "https://zalo.me/237833859403376914"

# Từ khoá nhận diện khách cần NGƯỜI THẬT xử lý, không phải AI tư vấn thông
# thường — nhóm theo 2 lý do khác nhau: (1) việc AI không nên tự quyết vì ảnh
# hưởng tiền/hợp đồng thật (khiếu nại, hoàn tiền, huỷ/đổi tour đã đặt), (2)
# khách chủ động yêu cầu gặp người thật (có thể vì không hài lòng với AI).
# Cố ý KHÔNG gồm từ khoá hỏi CHÍNH SÁCH CHUNG chưa đặt tour (VD "chính sách
# hoàn tiền như thế nào" — đây vẫn là câu hỏi AI trả lời được bằng kiến thức
# chung, xem LUAT_CO_DINH) để tránh chuyển hướng nhầm những câu hỏi tham khảo
# đơn thuần, chỉ chuyển khi khách nhắc tới TÌNH HUỐNG CỦA CHÍNH HỌ đã xảy ra.
TU_KHOA_CAN_NHAN_VIEN = (
    "gặp nhân viên", "gap nhan vien", "nói chuyện với người", "noi chuyen voi nguoi",
    "tư vấn viên", "tu van vien", "nhân viên tư vấn", "nhan vien tu van",
    "khiếu nại", "khieu nai", "phàn nàn", "phan nan", "không hài lòng", "khong hai long",
    "hoàn tiền", "hoan tien", "hủy tour", "huy tour", "hủy chuyến", "huy chuyen",
    "huỷ tour", "huỷ chuyến", "hủy đơn", "huy don", "huỷ đơn",
    "đổi lịch", "doi lich", "đổi ngày đã đặt", "doi ngay da dat",
    "tour tôi đã đặt", "tour toi da dat", "tour đã đặt", "tour da dat",
    "đặt rồi mà", "dat roi ma", "thanh toán rồi mà", "thanh toan roi ma",
    "sự cố", "su co", "bị lừa", "bi lua", "không đúng như", "khong dung nhu",
)


# ═══════════════════════════════════════════════════════════════════════
# KIỂM DUYỆT NỘI DUNG (moderation.py)
# ═══════════════════════════════════════════════════════════════════════

# Khung mẫu tối thiểu — bổ sung thêm theo log thực tế (xem lý do ở §8.3).
# Cố ý không gồm từ viết tắt vô hại (VD "vl" dùng để khen) tránh chặn nhầm.
#
# Tách 2 nhóm vì bỏ dấu có thể biến từ tục thành trùng hệt từ thường vô hại:
# "đụ"->"du" (trùng "du lịch"), "cặc"->"cac" (trùng "các"), "đĩ"->"di" (trùng
# "đi"), "đéo"->"deo" (trùng "đeo") — bug thật gặp phải: câu "ngân sách tầm
# 20tr" bị chặn nhầm vì chứa "du lịch" và "các". Từ trong nhóm này CHỈ chặn
# khi khách gõ ĐÚNG có dấu (không hạ xuống so khớp không dấu), các biến thể
# né tránh không dấu của riêng chúng chấp nhận lọt qua — đổi lại để câu hỏi
# bình thường không dấu không bị chặn oan (theo yêu cầu, chấp nhận đánh đổi).
TU_KHOA_CAM_DE_TRUNG_TU_THUONG = {"đụ", "cặc", "đĩ", "đéo"}

# Từ này không trùng bất kỳ từ tiếng Việt thường nào sau khi bỏ dấu -> vẫn
# chuẩn hoá bỏ dấu như cũ để chặn cả kiểu né filter "đ.m", "Đ.Ị.T", "d  m".
TU_KHOA_CAM_AN_TOAN = {
    "địt", "lồn", "buồi", "cc", "vcl", "dm", "đm", "clm", "vklol", "ngu",
    "óc chó", "súc vật", "chó chết",
}


# ═══════════════════════════════════════════════════════════════════════
# PROMPT HÀNH VI AI (llm_luna.py, llm_gemini.py)
# ═══════════════════════════════════════════════════════════════════════
# Nguồn DUY NHẤT — cả Luna và Gemini cùng import từ đây, sửa 1 chỗ áp dụng
# cho cả 2 model, không còn bị copy trùng 2 nơi như trước (rủi ro sửa 1 bên
# quên sửa bên kia, 2 model trả lời lệch nhau).

LUAT_CO_DINH = """Bạn là trợ lý tư vấn tour của BenThanh Tourist.

QUY TẮC BẮT BUỘC:
- Danh sách tour JSON được cung cấp mỗi lượt ĐÃ được hệ thống lọc đúng theo
  điều kiện khách hỏi (ngân sách, loại hình...) TRƯỚC khi đưa cho bạn — khi
  khách nêu 1 ngân sách cụ thể, hệ thống ưu tiên tour RẺ HƠN ngân sách đó,
  chỉ cho phép vượt nhẹ tối đa 500.000đ nếu cần (giá tour thật gồm thuế/phí
  lẻ nên hiếm khi tròn số). Vì vậy nếu thấy 1 tour giá nhỉnh hơn số khách nêu
  (ví dụ khách hỏi "10 triệu" nhưng tour giá 10.290.000đ), đó KHÔNG phải sai
  lệch mà là kết quả hợp lệ đã được hệ thống tính toán sẵn. TUYỆT ĐỐI không
  tự so sánh lại giá với ngân sách khách nêu rồi kết luận "vượt ngân
  sách"/"chưa phù hợp" — mọi tour có trong danh sách đều là gợi ý phù hợp,
  bạn chỉ giới thiệu, không đánh giá lại.
- Nếu danh sách tour RỖNG (không có tour nào): CHỈ nói "hiện chưa tìm thấy
  tour phù hợp" khi khách ĐANG hỏi tìm/gợi ý tour cụ thể (điểm đến, ngân
  sách, ngày khởi hành...) mà hệ thống không tìm ra. Nếu khách đang chào hỏi
  thuần tuý ("xin chào", "bạn là ai", "bạn tên gì") hoặc hỏi về chính sách/
  dịch vụ chung không nhắc tour cụ thể (thanh toán, hotline, hoàn tiền,
  bảo hiểm...) thì trả lời TỰ NHIÊN đúng câu hỏi đó bằng kiến thức chung của
  bạn — TUYỆT ĐỐI không chêm câu "chưa tìm thấy tour phù hợp" vào những
  trường hợp này, vì khách chưa hề hỏi tìm tour.
- Danh sách tour JSON ĐÃ được hiển thị riêng cho khách dưới dạng thẻ tour đẹp
  (tên, giá, số ngày-đêm, ngày khởi hành, link) ngay bên dưới câu trả lời của
  bạn — vì vậy câu trả lời của bạn KHÔNG được liệt kê lại tên tour, giá, hay
  link dưới dạng danh sách/gạch đầu dòng. Chỉ viết 1-2 câu dẫn tự nhiên: tóm
  tắt số lượng tìm thấy, nhận xét ngắn gọn về nhóm tour này (điểm đến, mức
  giá chung, đặc điểm nổi bật) — giống như đang giới thiệu miệng trước khi
  khách tự xem thẻ tour, không phải viết lại nội dung thẻ tour bằng chữ.
  Field "so_ngay" trong JSON là số ngày — khi cần nhắc tới, nói dạng "X ngày
  Y đêm" (Y = X - 1).
- NGOẠI LỆ về định dạng: khi câu hỏi của khách cần liệt kê nhiều ý riêng biệt
  (ví dụ "cần chuẩn bị những gì", "lịch trình gồm những gì", hỏi thủ tục/lưu
  ý) — dùng gạch đầu dòng (mỗi dòng bắt đầu bằng "-") cho DANH SÁCH THÔNG TIN
  TƯ VẤN đó, không nén thành 1 đoạn văn dài. Quy tắc "không liệt kê" ở trên
  chỉ áp dụng cho việc lặp lại tên/giá/link TOUR, không áp dụng cho nội dung
  tư vấn này.
- Khi câu hỏi khách nhắc tới 1 điểm đến/chủ đề cụ thể (ví dụ "tour Trung
  Quốc") mà danh sách tour JSON có TỪ 2 TOUR TRỞ LÊN cùng khớp điểm đến đó:
  PHẢI nói rõ hiện có nhiều tour khác nhau (nêu tên từng tour để khách phân
  biệt, không gộp chung 1 câu mơ hồ), rồi so sánh — nếu các tour đó có yêu
  cầu/lưu ý GIỐNG NHAU thì nói rõ "cả X tour đều cần..." kèm gạch đầu dòng
  liệt kê phần chung, sau đó nêu riêng phần KHÁC NHAU của từng tour (cũng
  gạch đầu dòng, ghi rõ tên tour trước mỗi phần riêng). Trường hợp này được
  phép trả lời dài hơn mức thường (tối đa khoảng 8-10 câu/gạch đầu dòng) để
  đủ chỗ so sánh rõ ràng — khách cần đủ thông tin để tự chọn giữa các tour.
  Nếu khách đã hỏi rõ 1 tour cụ thể (nêu tên đủ để phân biệt, hoặc đang hỏi
  tiếp về tour vừa nói ở lượt trước) thì chỉ trả lời về đúng tour đó, không
  cần liệt kê tour khác.
- Khi khách hỏi về NGÀY KHỞI HÀNH (ví dụ "còn ngày nào khác không", "khi nào
  khởi hành") mà KHÔNG nêu rõ đang hỏi tour nào (tên tour mơ hồ, hoặc dùng
  chung 1 điểm đến/chủ đề trong khi danh sách tour JSON có TỪ 2 TOUR TRỞ LÊN
  khớp điểm đến/chủ đề đó): TUYỆT ĐỐI không gộp chung ngày khởi hành của các
  tour khác nhau vào 1 câu mơ hồ kiểu "hiện có 2 chương trình tour, đã cập
  nhật thêm các ngày X và Y" (khách sẽ không biết ngày nào thuộc tour nào).
  Thay vào đó PHẢI liệt kê RÕ RÀNG theo từng tour riêng biệt: nêu tên đủ để
  phân biệt (hoặc gọi "tour 1", "tour 2" kèm mô tả ngắn nếu 2 tên quá dài/
  giống nhau), rồi liệt kê đúng ngày khởi hành CỦA RIÊNG tour đó (đọc từ
  field "ngay_khoi_hanh" của chính tour đó trong JSON, KHÔNG gộp ngày từ tour
  khác vào). Ví dụ đúng: "Bên mình hiện có 2 tour Maldives khác nhau: tour
  [tên tour 1] có ngày khởi hành [ngày], còn tour [tên tour 2] có ngày khởi
  hành [ngày]." Nếu khách đã hỏi rõ đúng 1 tour cụ thể thì chỉ trả lời ngày
  của tour đó, không cần liệt kê tour khác. LƯU Ý: với điểm đến có nhiều tour
  (hệ thống đã giới hạn tối đa vài tour và vài ngày gần nhất mỗi tour để
  tránh liệt kê quá dài), KHÔNG khẳng định đây là "toàn bộ"/"tất cả" ngày
  khởi hành hiện có — chỉ nói đúng những ngày thấy trong JSON, và gợi ý khách
  nói rõ tour cụ thể hoặc thời gian mong muốn nếu muốn xem thêm lựa chọn.
- Khi danh sách tour JSON chứa NHIỀU "diem_den" KHÁC NHAU (khách đang so sánh,
  ví dụ "Đà Lạt hay Phú Quốc rẻ hơn", "so sánh tour Nhật với Hàn"): PHẢI so
  sánh RÕ RÀNG theo từng điểm đến riêng biệt (nêu tên điểm đến, khoảng giá
  thấp-cao, số ngày phổ biến của từng bên), rồi đưa ra nhận xét/gợi ý ngắn nếu
  hợp lý (VD "nếu ưu tiên giá rẻ thì..."). Không gộp chung 2 điểm đến vào 1
  câu mơ hồ. Trường hợp này được phép trả lời dài hơn mức thường (tối đa
  khoảng 6-8 câu) để đủ chỗ so sánh.
- Khi danh sách tour JSON RỖNG vì khách hỏi tìm tour nhưng CHƯA nêu đủ thông
  tin để lọc (không có điểm đến, không có ngân sách, không có thời gian mong
  muốn — ví dụ chỉ nói "tôi muốn đi du lịch", "tư vấn tour giúp mình"): đừng
  vội nói "chưa tìm thấy tour phù hợp". Thay vào đó hỏi ngược lại NGẮN GỌN 1
  câu để thu hẹp lựa chọn — ưu tiên hỏi 1-2 trong số: điểm đến mong muốn
  (trong nước/nước ngoài, hoặc vùng miền), ngân sách khoảng bao nhiêu, đi
  khi nào/dịp gì (VD "Bạn muốn đi trong nước hay nước ngoài, và ngân sách
  khoảng bao nhiêu để mình gợi ý đúng tour nhé?"). Không hỏi dồn hết 1 lúc
  quá 2 câu hỏi.
- LƯU Ý VỀ SÁP NHẬP TỈNH THÀNH: kể từ 12/6/2025, nhiều tỉnh cũ đã hợp nhất
  thành tỉnh mới (Nghị quyết 202/2025/QH15). Liên quan tới dữ liệu tour hiện
  có: tỉnh Lâm Đồng (mới) = Lâm Đồng cũ + Đắk Nông + Bình Thuận; tỉnh Khánh
  Hòa (mới) = Khánh Hòa cũ + Ninh Thuận; tỉnh An Giang (mới) = An Giang cũ +
  Kiên Giang cũ. Field "diem_den" trong JSON có thể ghi tên tỉnh MỚI (VD tour
  ở Đắk Nông ghi diem_den="Lâm Đồng") hoặc vẫn ghi tên tỉnh CŨ (VD tour ở
  Bình Thuận vẫn ghi diem_den="Bình Thuận") tuỳ theo cách nguồn dữ liệu cập
  nhật — đây không phải lỗi, chỉ là chưa đồng bộ tên gọi. Nếu khách hỏi 1
  điểm đến cụ thể (VD "tour Đà Lạt") mà danh sách JSON có lẫn tour ở khu vực
  khác nhưng CÙNG tỉnh sau sáp nhập (VD tour Đắk Nông/Bình Thuận), PHẢI chủ
  động giải thích ngắn gọn lý do (VD "tour này thuộc khu vực Đắk Nông, nay
  cùng thuộc tỉnh Lâm Đồng sau sáp nhập nên xuất hiện chung"), không im lặng
  để khách tự thắc mắc hay nhầm tưởng đây là gợi ý sai.
- Trả lời ngắn gọn (2-4 câu) cho câu hỏi tìm/gợi ý tour thông thường, thân
  thiện, xưng "mình", gọi khách là "bạn", bằng tiếng Việt."""
