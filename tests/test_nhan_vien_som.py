"""Tin khách bot không phục vụ được thì báo nhân viên ngay (số điện thoại ở Zalo/Facebook, đoàn công ty, vé máy bay/khách sạn lẻ),
và đưa tin nhân viên thật vào ngữ cảnh của AI. Mọi lời gọi ra ngoài đều bị thay bằng mock."""
from unittest import mock

import admin_chat
import main
from rag import can_nhan_vien_som, tim_sdt_viet_nam
from tests.test_admin_chat import NenNoiAdmin


class NenGhi:
    """Thay BackgroundTasks: nhớ các việc nền để kiểm tra, không chạy."""

    def __init__(self):
        self.viec = []

    def add_task(self, fn, *args, **kwargs):
        self.viec.append((fn, args))


class NhanDienThuan(NenNoiAdmin):
    def test_tim_so_dien_thoai(self):
        self.assertEqual(tim_sdt_viet_nam("Em gửi 0935321686"), "0935321686")
        self.assertEqual(tim_sdt_viet_nam("034 9694 888"), "0349694888")
        self.assertEqual(tim_sdt_viet_nam("+84 912 345 678"), "0912345678")
        self.assertIsNone(tim_sdt_viet_nam("09977662994"))  # 11 số: gõ nhầm
        self.assertIsNone(tim_sdt_viet_nam("tour ngày 29/11 giá 12000000"))
        # 2 số cách nhau bằng xuống dòng không bị dính thành một
        self.assertEqual(tim_sdt_viet_nam("09977662994" + chr(10) + "0977662994"), "0977662994")

    def test_chi_tinh_sdt_khi_ho_so_chua_co_so(self):
        self.assertEqual(can_nhan_vien_som("Em gửi 0935321686", co_sdt=False), "SDT")
        # Web và app luôn có sẵn số nên khách gõ số trong câu không phải để lại liên hệ
        self.assertIsNone(can_nhan_vien_som("Em gửi 0935321686", co_sdt=True))

    def test_doan_cong_ty_va_dong_nguoi(self):
        for cau in ["Company trip, số lượng dự kiến 60 người, Madagui, có teambuilding", "công ty em muốn đi Nhật", "đoàn 18 người đi Đà Lạt", "gia đình 25 người đi Phú Quốc"]:
            self.assertEqual(can_nhan_vien_som(cau, True), "DOANH_NGHIEP", cau)
        for cau in ["nhà mình 5 người đi Thái", "tour Thái Lan 4 ngày giá bao nhiêu", "đoàn 10 người đi Đà Lạt"]:
            self.assertIsNone(can_nhan_vien_som(cau, True), cau)

    def test_ve_may_bay_khach_san_le(self):
        self.assertEqual(can_nhan_vien_som("em muốn đăng ký vé máy bay và khách sạn thôi, còn lại tự túc", True), "VE_RIENG")
        self.assertEqual(can_nhan_vien_som("bên c có thể tư vấn ks và vé mb cho em đc ko ạ?", True), "VE_RIENG")
        # Hỏi trong chuyện tour thì để AI trả lời
        self.assertIsNone(can_nhan_vien_som("tour này đã bao gồm vé máy bay chưa", True))
        self.assertIsNone(can_nhan_vien_som("khách sạn trong tour là mấy sao", True))

    def test_so_nuoc_ngoai_co_dau_cong(self):
        from rag import tim_sdt_quoc_te
        self.assertEqual(tim_sdt_quoc_te("+61 403 353 800"), "+61403353800")
        self.assertEqual(can_nhan_vien_som("+61 403 353 800", co_sdt=False), "SDT")
        self.assertIsNone(tim_sdt_quoc_te("giá 19.590.000 đ"))
        self.assertIsNone(tim_sdt_quoc_te("+84 912 345 678"))  # số Việt Nam do tim_sdt_viet_nam lo

    def test_tin_co_so_kem_cau_hoi(self):
        from rag import co_cau_hoi_ngoai_sdt
        for cau in ["Má chị 85t vẫn đi được hả\n0935321686", "Cần tư vấn tour sing- malay 21/11, maldive 22/11. Zalo: 0398373353", "0935321686 tour Thái còn chỗ không?"]:
            self.assertTrue(co_cau_hoi_ngoai_sdt(cau), cau)
        for cau in ["Em gửi 0935321686", "Dạ em gửi\n0935321686\nDạ nhắn Zalo giúp em ạ", "Ok em\n0901377556", "0935321686\n0935321686\nNt nhá", "+61 403 353 800"]:
            self.assertFalse(co_cau_hoi_ngoai_sdt(cau), cau)

    def test_nhan_vien_vua_hoi_va_cau_nhieu_noi_nhieu_ngay(self):
        from rag import la_cau_hoi_cua_nhan_vien, nhieu_noi_hoac_nhieu_ngay
        for cau in ["Dạ cho em hỏi mình rớt visa bao lâu rồi ạ", "Dạ mình cần tư vấn tour đi thời gian nào ạ", "Mình đi mấy người ạ?", "Dạ mình đi 1 khách hay sao ạ"]:
            self.assertTrue(la_cau_hoi_cua_nhan_vien(cau), cau)
        for cau in ["Dạ em nhận thông tin ạ", "Dạ em gửi tour Tết Hongkong Mùng 2 ạ", "Dạ đúng rồi ạ"]:
            self.assertFalse(la_cau_hoi_cua_nhan_vien(cau), cau)
        self.assertTrue(nhieu_noi_hoac_nhieu_ngay("Chị muốn đi 12-2-2027 đi Thái. 18-2 chị muốn đi Hà Nội, Hạ Long"))
        self.assertFalse(nhieu_noi_hoac_nhieu_ngay("Đầu tháng 4 e"))
        self.assertFalse(nhieu_noi_hoac_nhieu_ngay("tour Hồng Kông tháng 1"))

    def test_ngay_di_sat_duoi_3_ngay(self):
        from datetime import date
        from rag import hoi_ngay_khoi_hanh_sat
        hom_nay = date(2026, 11, 19)
        for cau in ["tour đi 21/11 còn không", "6 người khởi hành 21/11", "đi ngày mai được không", "đi 19/11", "đi 21-11", "đi ngày 21 tháng 11"]:
            self.assertTrue(hoi_ngay_khoi_hanh_sat(cau, hom_nay), cau)
        for cau in ["tour đi 22/11", "đi 3/12", "dịp 20/11 có tour nào", "tour 4-5 ngày", "đi 5-10 triệu", "tour Thái Lan", "đi 31/12", "mai chị gửi giấy tờ"]:
            self.assertFalse(hoi_ngay_khoi_hanh_sat(cau, hom_nay), cau)
        self.assertTrue(hoi_ngay_khoi_hanh_sat("đi 1/1", date(2026, 12, 30)))  # sang năm mới

    def test_muon_dang_ky_khong_can_chu_tour(self):
        from dat_tour import muon_dang_ky
        for cau in ["Gửi giúp c nhé, nếu phù hợp thì hum nay c đăng ký lun", "em muốn book giữ chỗ 2 người", "chốt giúp chị"]:
            self.assertTrue(muon_dang_ky(cau), cau)
        for cau in ["Mấy nay lu bu quên đăng ký", "mình đã đăng ký rồi", "chưa muốn đăng ký đâu", "đăng ký visa mất bao lâu", "tour này ok"]:
            self.assertFalse(muon_dang_ky(cau), cau)

    def test_sua_hai_cau_bi_hieu_nham(self):
        from rag import dia_danh_khong_co_tour, trich_dieu_kien_so_ngay
        self.assertIsNone(trich_dieu_kien_so_ngay("thường đặt trước 10 ngày được giá ưu đãi hay sao"))
        self.assertEqual(trich_dieu_kien_so_ngay("tour 10 ngày đi Nhật"), ("==", 10))
        self.assertIsNone(dia_danh_khong_co_tour("Má chị 85 tuổi, mới đi TQ về nè"))


class LuongXuLy(NenNoiAdmin):
    def chay(self, text, kenh="ZALO", khach=None):
        nen = NenGhi()
        req = main.ChatRequest(message=text, conversation_id=self.conv)
        kq = main._xu_ly_chat(req, nen, "u1", "", kenh, "zalo-1", khach)
        return kq, nen

    def test_zalo_khach_gui_sdt_bao_nhan_vien_va_dung_cau_cua_trang_quan_tri(self):
        self.inbound.return_value = {"conversationId": "c1", "action": "CONTACT", "reply": "Mình đã báo nhân viên."}
        kq, _ = self.chay("Em gửi 0935321686")
        self.assertEqual(kq["reply"], "Mình đã báo nhân viên.")
        self.assertTrue(self.inbound.call_args.args[4])  # cờ wantsHuman
        self.gemini.assert_not_called()

    def test_zalo_trang_quan_tri_ngung_chay_dung_cau_viet_san_khong_goi_ai(self):
        self.inbound.return_value = None
        kq, nen = self.chay("Em gửi 0935321686")
        self.assertEqual(kq["reply"], main.TRA_LOI_NHAN_VIEN_SOM["SDT"])
        self.gemini.assert_not_called()
        self.assertEqual([fn for fn, _ in nen.viec].count(self.bot_reply), 1)  # câu trả lời vẫn được ghi lại cho nhân viên đọc

    def test_khach_co_san_so_dien_thoai_thi_van_do_ai_tra_loi(self):
        kq, _ = self.chay("Em gửi 0935321686", kenh="WEB", khach={"name": "An", "phone": "0900000000"})
        self.assertFalse(self.inbound.call_args.args[4])
        self.assertEqual(kq["reply"], "(Gemini) Đây là câu trả lời.")

    def test_doan_cong_ty_bao_nhan_vien_o_moi_kenh(self):
        self.inbound.return_value = {"conversationId": "c1", "action": "CONTACT", "reply": "Mình đã báo nhân viên."}
        kq, _ = self.chay("Công ty em đi team building 60 người", kenh="WEB", khach={"name": "An", "phone": "0900000000"})
        self.assertTrue(self.inbound.call_args.args[4])
        self.assertEqual(kq["reply"], "Mình đã báo nhân viên.")
        self.gemini.assert_not_called()


class ZaloFacebook(NenNoiAdmin):
    """Chốt 19/11/2026: Zalo/Facebook vẫn tư vấn, gọi khách theo tên kênh, khách muốn đặt thì báo nhân viên (không chạy luồng đặt tour)."""

    def chay(self, text, kenh="ZALO", khach=None):
        req = main.ChatRequest(message=text, conversation_id=self.conv)
        self.nen = NenGhi()
        return main._xu_ly_chat(req, self.nen, "zalo-1", "", kenh, "zalo-1", khach)

    def cau_bot_ghi_lai(self):
        return [args[2] for fn, args in self.nen.viec if fn is self.bot_reply]

    def test_muon_dat_tour_thi_bao_nhan_vien_khong_vao_luong_dat(self):
        self.inbound.return_value = None
        with mock.patch.object(main.dat_tour, "xu_ly") as xu_ly:
            for kenh in ("ZALO", "FACEBOOK"):
                kq = self.chay("Sau khi xem các tour anh muốn đăng ký 1 chỗ tour hongkong ngày 31.12", kenh=kenh)
                self.assertEqual(kq["reply"], main.TRA_LOI_NHAN_VIEN_SOM["DAT_TOUR"])
                self.assertTrue(self.inbound.call_args.args[4])
            xu_ly.assert_not_called()
        self.gemini.assert_not_called()

    def test_hoi_ngay_di_sat_thi_bao_nhan_vien_khong_goi_y_tour_khac(self):
        from datetime import date
        self.inbound.return_value = None
        with mock.patch.object(main, "hoi_ngay_khoi_hanh_sat", wraps=lambda c: __import__("rag").hoi_ngay_khoi_hanh_sat(c, date(2026, 11, 19))):
            kq = self.chay("Cần tour Singapore đi 21/11 cho 6 người")
        self.assertEqual(kq["reply"], main.TRA_LOI_NHAN_VIEN_SOM["NGAY_SAT"])
        self.assertTrue(self.inbound.call_args.args[4])
        self.gemini.assert_not_called()

    def test_dang_ky_luon_khong_chu_tour_bao_nhan_vien(self):
        self.inbound.return_value = None
        kq = self.chay("Gửi giúp c nhé, nếu phù hợp thì hum nay c đăng ký lun")
        self.assertEqual(kq["reply"], main.TRA_LOI_NHAN_VIEN_SOM["DAT_TOUR"])

    def test_app_van_chay_luong_dat_tour(self):
        with mock.patch.object(main.dat_tour, "xu_ly", return_value={"reply": "Bạn chọn ngày nào ạ?", "tours": []}) as xu_ly:
            req = main.ChatRequest(message="tôi muốn đặt tour Hong Kong", conversation_id=self.conv)
            kq = main._xu_ly_chat(req, NenGhi(), "u1", "tok", "APP", "u1", {"name": "An", "phone": "0900000000"})
        xu_ly.assert_called_once()
        self.assertEqual(kq["reply"], "Bạn chọn ngày nào ạ?")
        self.assertFalse(self.inbound.call_args.args[4])

    def test_khong_hien_nut_dat_tour_va_gui_ten_khach_cho_ai(self):
        kq = self.chay("Mình cần tư vấn tour hongkong", khach={"name": "Lan Nguyễn"})
        self.assertNotIn("Tôi muốn đặt tour này", kq["goi_y"])
        ghi_chu = self.gemini.call_args.kwargs["ghi_chu_kenh"]
        self.assertIn("Lan Nguyễn", ghi_chu)
        self.assertIn("KHÔNG đặt tour được", ghi_chu)
        self.assertIn("ĐỪNG hứa nhân viên", ghi_chu)

    def test_kenh_app_khong_co_ghi_chu_kenh(self):
        self.assertIsNone(main.ghi_chu_kenh("APP", {"name": "An"}))
        self.assertIsNone(main.ghi_chu_kenh("WEB", {"name": "An"}))

    def test_so_kem_cau_hoi_ai_van_tra_loi_va_noi_cau_bao_nhan_vien(self):
        self.inbound.return_value = {"conversationId": "c1", "action": "CONTACT", "reply": "Mình đã báo nhân viên."}
        kq = self.chay("Má chị 85t vẫn đi được hả\n0935321686")
        self.assertTrue(self.inbound.call_args.args[4])
        self.assertEqual(kq["reply"], "(Gemini) Đây là câu trả lời.\n\nMình đã báo nhân viên.")
        # Backend đã tự lưu câu "đã báo nhân viên": chỉ ghi phần AI trả lời
        self.assertEqual(self.cau_bot_ghi_lai(), ["(Gemini) Đây là câu trả lời."])
        # AI được dặn không nhắc lại việc ghi nhận số
        self.assertIn("không nhắc lại số điện thoại", self.gemini.call_args.kwargs["ghi_chu_kenh"])

    def test_so_kem_cau_hoi_khi_trang_quan_tri_ngung(self):
        self.inbound.return_value = None
        kq = self.chay("Má chị 85t vẫn đi được hả\n0935321686")
        cau = "(Gemini) Đây là câu trả lời.\n\n" + main.TRA_LOI_NHAN_VIEN_SOM["SDT"]
        self.assertEqual(kq["reply"], cau)
        self.assertEqual(self.cau_bot_ghi_lai(), [cau])

    def test_chi_gui_so_thi_van_cau_viet_san(self):
        self.inbound.return_value = None
        self.assertEqual(self.chay("Ok em\n0901377556")["reply"], main.TRA_LOI_NHAN_VIEN_SOM["SDT"])
        self.gemini.assert_not_called()

    def test_nhan_vien_vua_hoi_thi_khong_dung_cau_viet_san(self):
        tin = [{"createdAt": "2026-11-18T17:42:00.000Z", "text": "Dạ cho em hỏi mình rớt visa bao lâu rồi ạ", "attachmentType": None, "attachmentName": None}]
        with mock.patch.object(admin_chat, "tin_nhan_vien_gan_day", return_value=tin), \
                mock.patch.object(main, "tra_loi_gan_dung", return_value="VIET SAN") as viet_san, \
                mock.patch.object(main, "tra_loi_noi_khong_co_tour", return_value="VIET SAN") as khong_co:
            kq = self.chay("Đầu tháng 4 e")
        viet_san.assert_not_called()
        khong_co.assert_not_called()
        self.assertEqual(kq["reply"], "(Gemini) Đây là câu trả lời.")
        self.assertIn("câu TRẢ LỜI", self.gemini.call_args.kwargs["ghi_chu_kenh"])


class TinNhanVienChoAI(NenNoiAdmin):
    def chay(self, text="Còn này ạ"):
        req = main.ChatRequest(message=text, conversation_id=self.conv)
        return main._xu_ly_chat(req, NenGhi(), "u1", "", "ZALO", "zalo-1", None)

    def test_tin_nhan_vien_duoc_dua_cho_ai_kem_gio_va_tep(self):
        tin = [{"createdAt": "2026-11-18T03:05:00.000Z", "text": "Dạ em gửi Nhật Mùng 1 ạ", "attachmentType": None, "attachmentName": None},
               {"createdAt": "2026-11-18T03:06:00.000Z", "text": "", "attachmentType": "application/pdf", "attachmentName": "nhat.pdf"}]
        with mock.patch.object(admin_chat, "tin_nhan_vien_gan_day", return_value=tin):
            self.chay()
        ghi_chu = self.gemini.call_args.args[3]
        self.assertIn("18/11 10:05 Nhân viên: Dạ em gửi Nhật Mùng 1 ạ", ghi_chu)  # giờ Việt Nam
        self.assertIn("[đính kèm nhat.pdf]", ghi_chu)

    def test_khong_lay_duoc_tin_nhan_vien_ai_van_tra_loi(self):
        with mock.patch.object(admin_chat, "tin_nhan_vien_gan_day", side_effect=RuntimeError("mạng lỗi")):
            kq = self.chay()
        self.assertEqual(kq["reply"], "(Gemini) Đây là câu trả lời.")
        self.assertIsNone(self.gemini.call_args.args[3])

    def test_chi_lay_tin_cua_chinh_khach_nay_va_tu_moc_lich_su(self):
        with mock.patch.object(admin_chat, "tin_nhan_vien_gan_day", return_value=[]) as m:
            self.chay("Cho mình hỏi tour Thái")
            self.chay("Còn ngày nào khác")
        self.assertEqual(m.call_args_list[0].args[:2], ("ZALO", "zalo-1"))
        self.assertIsNone(m.call_args_list[0].args[2])  # lần đầu chưa có lịch sử: để backend dùng mốc mặc định
        self.assertTrue(m.call_args_list[1].args[2].endswith("Z"))  # lần sau lấy từ tin cũ nhất trong lịch sử
