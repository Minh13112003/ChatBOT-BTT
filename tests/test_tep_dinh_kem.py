"""Khách gửi ảnh/PDF cho nhân viên và nhận file nhân viên gửi. Mọi lời gọi ra trang quản trị đều bị thay bằng mock."""
import uuid
from unittest import mock

import admin_chat
import config
import main
from tests.test_admin_chat import NenNoiAdmin, PhanHoiGia

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class NenTep(NenNoiAdmin):
    def setUp(self):
        super().setUp()
        main._LUOT_TEP.clear()
        main._LUOT_THEO_IP.clear()
        self.inbound_file = mock.Mock(return_value=PhanHoiGia(200, {"conversationId": "c1", "action": "BOT"}))
        p = mock.patch.object(admin_chat, "inbound_file", self.inbound_file)
        p.start()
        self.addCleanup(p.stop)

    def gui_tep(self, noi_dung=PNG, ten="anh.png", loai="image/png", chu="", duong_dan="/chat/attachment", **them):
        return self.client.post(duong_dan, files={"file": (ten, noi_dung, loai)}, data={"message": chu, **them})


class KhachAppGuiTep(NenTep):
    def test_chuyen_file_cho_trang_quan_tri_va_bot_tra_loi_co_dinh_khong_goi_ai(self):
        r = self.gui_tep(chu="Ảnh vé của mình")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reply"], main.TRA_LOI_KHI_NHAN_ANH)
        kenh, ma, chu, _khach, du_lieu, ten, loai, _ma_tin = self.inbound_file.call_args.args
        self.assertEqual((kenh, ma, chu, du_lieu, ten, loai), ("APP", "u1", "Ảnh vé của mình", PNG, "anh.png", "image/png"))
        self.gemini.assert_not_called()
        self.assertEqual(self.bot_reply.call_args.args[:3], ("APP", "u1", main.TRA_LOI_KHI_NHAN_ANH))

    def test_nhan_vien_dang_xu_ly_thi_bot_im_lang(self):
        self.inbound_file.return_value = PhanHoiGia(200, {"conversationId": "c1", "action": "STAFF"})
        r = self.gui_tep()
        self.assertEqual(r.json(), {"reply": "", "tours": [], "goi_y": [], "che_do": "STAFF"})
        self.bot_reply.assert_not_called()

    def test_loi_file_khong_hop_le_cua_backend_duoc_chuyen_cho_khach(self):
        self.inbound_file.return_value = PhanHoiGia(400, {"message": "Chỉ gửi được ảnh (JPG, PNG, WebP) hoặc file PDF"})
        r = self.gui_tep(b"MZ\x90\x00", "virus.jpg", "image/jpeg")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Chỉ gửi được ảnh", r.json()["message"])
        self.bot_reply.assert_not_called()

    def test_backend_tat_thi_bao_chua_gui_duoc_khong_mat_im_lang(self):
        self.inbound_file.return_value = None
        r = self.gui_tep()
        self.assertEqual((r.status_code, r.json()["code"]), (503, "KHONG_GUI_DUOC"))

    def test_backend_loi_may_chu_thi_bao_chua_gui_duoc(self):
        self.inbound_file.return_value = PhanHoiGia(500, {})
        self.assertEqual(self.gui_tep().status_code, 503)

    def test_file_qua_lon_bi_chan_ngay_o_chatbot_khong_goi_backend(self):
        r = self.gui_tep(b"\x00" * (main.GIOI_HAN_BYTE_TEP + 1))
        self.assertEqual((r.status_code, r.json()["code"]), (413, "TEP_QUA_LON"))
        self.inbound_file.assert_not_called()

    def test_file_trong(self):
        r = self.gui_tep(b"")
        self.assertEqual((r.status_code, r.json()["code"]), (400, "TEP_TRONG"))
        self.inbound_file.assert_not_called()

    def test_chu_kem_nhay_cam_khong_chuyen_di_nhung_file_van_toi_nhan_vien(self):
        with mock.patch.object(main, "co_noi_dung_nhay_cam", return_value=True):
            self.gui_tep(chu="câu thô tục")
        self.assertEqual(self.inbound_file.call_args.args[2], "")

    def test_khach_gui_lien_tiep_bi_giu_nhip(self):
        self.assertEqual(self.gui_tep().status_code, 200)
        r = self.gui_tep()
        self.assertEqual((r.status_code, r.json()["code"]), (429, "QUA_NHANH"))
        self.assertEqual(self.inbound_file.call_count, 1)

    def test_gioi_han_moi_phut_va_moi_gio(self):
        for i in range(4):
            main._LUOT_TEP.setdefault("u1", main.deque()).append(main.time.monotonic() - 10 - i)
        r = self.gui_tep()
        self.assertEqual(r.status_code, 429)
        self.assertIn("1 phút", r.json()["message"])
        main._LUOT_TEP.clear()
        main._LUOT_TEP["u1"] = main.deque(main.time.monotonic() - 100 - i for i in range(30))
        self.assertIn("1 giờ", self.gui_tep().json()["message"])

    def test_phai_dang_nhap(self):
        main.app.dependency_overrides.pop(main.lay_nguoi_dung, None)
        self.assertEqual(self.gui_tep().status_code, 401)
        self.inbound_file.assert_not_called()


class KhachWebGuiTep(NenTep):
    def setUp(self):
        super().setUp()
        self.thiet_bi = str(uuid.uuid4())
        with main.khoi_tao_database.__globals__["ket_noi"]() as conn:
            conn.execute("DELETE FROM web_khach")

    def _gui(self, thiet_bi=None, **kw):
        return self.gui_tep(duong_dan="/web/attachment", device_id=thiet_bi or self.thiet_bi, **kw)

    def _identify(self):
        return self.client.post("/web/identify", json={"device_id": self.thiet_bi, "name": "Nguyễn Thị Hoa", "phone": "0900 000 101"})

    def test_chua_de_lai_ten_sdt_thi_khong_nhan_file(self):
        r = self._gui()
        self.assertEqual((r.status_code, r.json()["code"]), (403, "CAN_THONG_TIN"))
        self.inbound_file.assert_not_called()

    def test_da_de_lai_thong_tin_thi_chuyen_file_kem_ten_sdt(self):
        self._identify()
        r = self._gui(chu="Giấy xác nhận")
        self.assertEqual(r.status_code, 200)
        kenh, ma, _chu, khach, *_ = self.inbound_file.call_args.args
        self.assertEqual((kenh, ma, khach), ("WEB", self.thiet_bi, {"name": "Nguyễn Thị Hoa", "phone": "0900000101"}))

    def test_ma_thiet_bi_khong_hop_le(self):
        self.assertEqual(self._gui(thiet_bi="abc").status_code, 422)


class NhanFileNhanVienGui(NenTep):
    def test_link_file_duoc_them_dia_chi_cong_khai_de_khach_mo_duoc(self):
        tep = {"url": "/files/m1?exp=9999999999&sig=abc", "type": "image/jpeg", "name": "tour.jpg", "size": 1234}
        self.updates.return_value = {"mode": "STAFF", "items": [{"id": "m1", "text": "", "createdAt": "2026-11-06T04:00:00.000Z", "attachment": tep}]}
        with mock.patch.object(config, "ADMIN_CHAT_PUBLIC_URL", "https://admin.btt.vn/api/v1"):
            r = self.client.get("/chat/updates?after=2020-01-01T00:00:00.000Z&tep=1").json()
        self.assertEqual(r["items"][0]["attachment"], {**tep, "url": "https://admin.btt.vn/api/v1/files/m1?exp=9999999999&sig=abc"})

    def test_app_cu_khong_biet_hien_file_thi_nhan_link_trong_chu_khong_bi_tin_trong(self):
        tep = {"url": "/files/m1?exp=9999999999&sig=abc", "type": "image/jpeg", "name": "tour.jpg", "size": 1234}
        self.updates.return_value = {"mode": "STAFF", "items": [{"id": "m1", "text": "Xem ảnh nhé", "createdAt": "2026-11-06T04:00:00.000Z", "attachment": tep}]}
        with mock.patch.object(config, "ADMIN_CHAT_PUBLIC_URL", "https://admin.btt.vn/api/v1"):
            r = self.client.get("/chat/updates?after=2020-01-01T00:00:00.000Z").json()
        muc = r["items"][0]
        self.assertNotIn("attachment", muc)
        self.assertEqual(muc["text"], "Xem ảnh nhé" + chr(10) + "[Nhân viên gửi ảnh: https://admin.btt.vn/api/v1/files/m1?exp=9999999999&sig=abc]")

    def test_tin_khong_co_file_khong_co_truong_attachment(self):
        self.updates.return_value = {"mode": "STAFF", "items": [{"id": "m2", "text": "Chào bạn", "createdAt": "2026-11-06T04:00:00.000Z", "attachment": None}]}
        r = self.client.get("/chat/updates?after=2020-01-01T00:00:00.000Z").json()
        self.assertNotIn("attachment", r["items"][0])
