"""Nối với trang quản trị (D:\\btt-chat-admin): mọi lời gọi ra ngoài đều bị thay bằng mock."""
import uuid
from unittest import mock

import admin_chat
import config
import main
from tests.helpers import NenTest


class PhanHoiGia:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}
        self.headers = {"content-type": "application/json"}
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._data


class NenNoiAdmin(NenTest):
    def setUp(self):
        super().setUp()
        self.inbound = mock.Mock(return_value={"conversationId": "c1", "action": "BOT"})
        self.bot_reply = mock.Mock()
        self.deal = mock.Mock()
        self.updates = mock.Mock(return_value=None)
        for ten, gia_tri in [("inbound", self.inbound), ("bot_reply", self.bot_reply), ("deal", self.deal), ("updates", self.updates)]:
            p = mock.patch.object(admin_chat, ten, gia_tri)
            p.start()
            self.addCleanup(p.stop)


class KhachApp(NenNoiAdmin):
    def test_bot_tra_loi_bao_tin_khach_va_cau_tra_loi(self):
        res = self.gui("Có tour Nga không?")
        self.assertEqual(res["reply"], "(Gemini) Đây là câu trả lời.")
        self.assertNotIn("che_do", res)
        kenh, ma, text, _khach, doi_nguoi = self.inbound.call_args.args
        self.assertEqual((kenh, ma, text, doi_nguoi), ("APP", "u1", "Có tour Nga không?", False))
        self.assertEqual(self.bot_reply.call_args.args[:3], ("APP", "u1", "(Gemini) Đây là câu trả lời."))

    def test_nhan_vien_dang_xu_ly_thi_bot_im_khong_goi_ai(self):
        self.inbound.return_value = {"conversationId": "c1", "action": "STAFF"}
        res = self.gui("Em ơi cho hỏi thêm")
        self.assertEqual(res, {"reply": "", "tours": [], "goi_y": [], "che_do": "STAFF"})
        self.gemini.assert_not_called()
        self.bot_reply.assert_not_called()

    def test_doi_gap_nhan_vien_khong_con_link_zalo(self):
        self.inbound.return_value = {"conversationId": "c1", "action": "CONTACT", "reply": "Mình đã báo nhân viên."}
        res = self.gui("Cho tôi gặp nhân viên")
        self.assertEqual(res["reply"], "Mình đã báo nhân viên.")
        self.assertNotIn("handoff", res)
        self.assertTrue(self.inbound.call_args.args[4])
        self.tom_tat.assert_not_called()
        self.gemini.assert_not_called()

    def test_tra_loi_tu_dong_khong_goi_ai(self):
        self.inbound.return_value = {"conversationId": "c1", "action": "AUTO_REPLY", "reply": "Mẫu tự động"}
        self.assertEqual(self.gui("giá đoàn")["reply"], "Mẫu tự động")
        self.gemini.assert_not_called()

    def test_trang_quan_tri_ngung_chay_bot_van_tra_loi(self):
        self.inbound.return_value = None
        self.assertEqual(self.gui("Có tour Nga không?")["reply"], "(Gemini) Đây là câu trả lời.")
        # Câu trả lời vẫn được chuyển đi để ghi thẳng vào database (admin_chat.bot_reply tự lo).
        self.bot_reply.assert_called_once()

    def test_trang_quan_tri_ngung_chay_doi_nhan_vien_van_co_zalo(self):
        self.inbound.return_value = None
        self.assertIn("handoff", self.gui("Cho tôi gặp nhân viên"))

    def test_dat_don_xong_bao_doanh_thu_va_khong_lo_khoa_noi_bo(self):
        ket_qua = {"reply": "Đã đặt", "tours": [], "goi_y": [], "booking": {"booking_id": "bk-1"},
                   "_don": {"tourName": "Đà Lạt", "guests": 2, "amount": 100, "orderCode": "bk-1"}}
        with mock.patch.object(main.dat_tour, "xu_ly", return_value=ket_qua):
            res = self.gui(action="xn:dong_y")
        self.assertNotIn("_don", res)
        self.deal.assert_called_once_with("APP", "u1", {"tourName": "Đà Lạt", "guests": 2, "amount": 100, "orderCode": "bk-1"}, None)

    def test_cap_nhat_lan_dau_lay_moc_bay_gio_de_khong_doc_tin_cu(self):
        self.updates.return_value = {"mode": "STAFF", "items": []}
        res = self.client.get("/chat/updates", headers={"Authorization": "Bearer t"}).json()
        self.assertEqual(res["cursor"], self.updates.call_args.args[2])
        self.assertTrue(res["cursor"].endswith("Z"))

    def test_cap_nhat_tra_tin_va_doi_con_tro(self):
        self.updates.return_value = {"mode": "STAFF", "items": [{"id": "m1", "text": "Dạ", "createdAt": "2026-11-05T01:00:00.000Z"}]}
        res = self.client.get("/chat/updates?after=2026-11-05T00:00:00.000Z", headers={"Authorization": "Bearer t"}).json()
        self.assertEqual(res, {"che_do": "STAFF", "items": [{"id": "m1", "text": "Dạ", "at": "2026-11-05T01:00:00.000Z"}], "cursor": "2026-11-05T01:00:00.000Z"})


class HoSoKhach(NenTest):
    def test_chi_lay_ten_va_sdt(self):
        ho_so = main.trich_ho_so_khach({"firstName": "Thị Hoa", "lastName": "Nguyễn", "phonenumber": " 0900000101 ", "nationalId": "012345678901", "passportNumber": "B1234567", "email": "a@b.c"})
        self.assertEqual(ho_so, {"name": "Thị Hoa Nguyễn", "phone": "0900000101"})

    def test_thieu_thong_tin_thi_bo_truong_do(self):
        self.assertEqual(main.trich_ho_so_khach({"firstName": None, "lastName": "", "phonenumber": None}), {})


class KhachWeb(NenNoiAdmin):
    def setUp(self):
        super().setUp()
        self.thiet_bi = str(uuid.uuid4())
        main._LUOT_THEO_IP.clear()
        with main.khoi_tao_database.__globals__["ket_noi"]() as conn:
            conn.execute("DELETE FROM web_khach")

    def _chat(self, text="Có tour Nga không?", thiet_bi=None):
        return self.client.post("/web/chat", json={"message": text, "conversation_id": self.conv, "device_id": thiet_bi or self.thiet_bi})

    def _identify(self, ten="Nguyễn Thị Hoa", sdt="0900 000 101"):
        return self.client.post("/web/identify", json={"device_id": self.thiet_bi, "name": ten, "phone": sdt})

    def test_chua_co_ten_sdt_thi_may_chu_tu_choi_khong_goi_ai(self):
        r = self._chat()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["code"], "CAN_THONG_TIN")
        self.assertIn("họ tên và số điện thoại", r.json()["message"])
        self.gemini.assert_not_called()
        self.inbound.assert_not_called()

    def test_de_lai_thong_tin_roi_chat_duoc_va_gui_kem_ten_sdt(self):
        self.assertEqual(self._identify().status_code, 200)
        r = self._chat()
        self.assertEqual(r.json()["reply"], "(Gemini) Đây là câu trả lời.")
        kenh, ma, _text, khach, _doi = self.inbound.call_args.args
        self.assertEqual((kenh, ma), ("WEB", self.thiet_bi))
        self.assertEqual(khach, {"name": "Nguyễn Thị Hoa", "phone": "0900000101"})

    def test_khach_web_vao_luong_dat_tour_khong_co_token(self):
        self._identify()
        self.tours_chat = [{"tour_key": "k", "ten": "T", "id": "i", "gia": 1, "so_ngay": 1, "ngay_khoi_hanh": "", "so_cho_con": 1, "anh": None, "url": "", "diem_den": "", "loai_hinh": ""}]
        res = self._chat("Cho xem tour").json()
        # Từ 2026-11-26 web đặt bằng nút "Đặt tour này" trên từng thẻ (static/chat.html), không còn nút chung bắt chọn lại tour.
        self.assertNotIn("Tôi muốn đặt tour này", res["goi_y"])
        self.assertEqual(res["tours"][0]["tour_key"], "k")
        with mock.patch.object(main.dat_tour, "xu_ly", return_value=None) as xu_ly:
            self._chat("Cho xem tour")
        self.assertEqual(xu_ly.call_args.args[1], "", "Khách web không có token tài khoản")

    def test_so_sai_bi_chan_ngay_tai_chatbot(self):
        r = self._identify(sdt="12345")
        self.assertEqual((r.status_code, r.json()["code"]), (400, "INVALID_PHONE"))

    def test_ten_khac_han_chuyen_nguyen_thong_bao_va_khong_cho_chat(self):
        with mock.patch.object(config, "ADMIN_CHAT_URL", "http://admin"), mock.patch.object(config, "INGEST_API_KEY", "k"), \
                mock.patch.object(admin_chat, "identify", return_value=PhanHoiGia(409, {"code": "NAME_MISMATCH", "message": "Nhập lại giúp mình"})):
            r = self._identify()
        self.assertEqual((r.status_code, r.json()["message"]), (409, "Nhập lại giúp mình"))
        self.assertEqual(self._chat().status_code, 403)

    def test_trang_quan_tri_loi_thi_chua_nhan_khach(self):
        with mock.patch.object(config, "ADMIN_CHAT_URL", "http://admin"), mock.patch.object(config, "INGEST_API_KEY", "k"), \
                mock.patch.object(admin_chat, "identify", return_value=None):
            r = self._identify()
        self.assertEqual((r.status_code, r.json()["code"]), (503, "UNAVAILABLE"))
        self.assertEqual(self._chat().status_code, 403)

    def test_khong_tiet_lo_id_hoi_thoai_noi_bo(self):
        with mock.patch.object(config, "ADMIN_CHAT_URL", "http://admin"), mock.patch.object(config, "INGEST_API_KEY", "k"), \
                mock.patch.object(admin_chat, "identify", return_value=PhanHoiGia(200, {"conversationId": "bi-mat", "returning": True, "loadHistory": False})):
            r = self._identify()
        self.assertEqual(r.json(), {"returning": True, "load_history": False})

    def test_may_khac_khong_lui_moc_de_doc_tin_cu_duoc(self):
        self._identify()
        self.updates.return_value = {"mode": "STAFF", "items": []}
        self.client.get(f"/web/updates?device_id={self.thiet_bi}&after=2020-01-01T00:00:00.000Z")
        moc_gui_di = self.updates.call_args.args[2]
        self.assertGreater(moc_gui_di, "2026-01-01")

    def test_moc_sai_dinh_dang_khong_lot_qua(self):
        self._identify()
        self.updates.return_value = {"mode": "BOT", "items": []}
        self.client.get(f"/web/updates?device_id={self.thiet_bi}&after=khong-phai-ngay")
        self.assertNotEqual(self.updates.call_args.args[2], "khong-phai-ngay")

    def test_moc_moi_hon_van_duoc_giu_de_khong_nhan_trung(self):
        self._identify()
        self.updates.return_value = {"mode": "STAFF", "items": []}
        self.client.get(f"/web/updates?device_id={self.thiet_bi}&after=2099-01-01T00:00:00.000Z")
        self.assertEqual(self.updates.call_args.args[2], "2099-01-01T00:00:00.000Z")

    def test_dung_thiet_bi_cu_giu_moc_cu_khi_nhap_lai(self):
        with mock.patch.object(config, "ADMIN_CHAT_URL", "http://admin"), mock.patch.object(config, "INGEST_API_KEY", "k"):
            with mock.patch.object(admin_chat, "identify", return_value=PhanHoiGia(200, {"returning": False, "loadHistory": False})):
                self._identify()
            moc_dau = main.lay_moc_doc_web(self.thiet_bi)
            with mock.patch.object(admin_chat, "identify", return_value=PhanHoiGia(200, {"returning": True, "loadHistory": True})):
                self._identify()
        self.assertEqual(main.lay_moc_doc_web(self.thiet_bi), moc_dau)

    def test_thiet_bi_chua_de_lai_thong_tin_khong_hoi_trang_quan_tri(self):
        r = self.client.get(f"/web/updates?device_id={self.thiet_bi}")
        self.assertEqual(r.json()["items"], [])
        self.updates.assert_not_called()

    def test_ma_thiet_bi_sai_bi_tu_choi(self):
        self.assertEqual(self._chat(thiet_bi="khong-phai-uuid").status_code, 422)
        self.assertEqual(self.client.get("/web/updates?device_id=abc").status_code, 422)

    def test_qua_gioi_han_theo_ip_bi_chan_du_doi_ma_thiet_bi(self):
        with mock.patch.dict(main.GIOI_HAN_IP_MOI_PHUT, {"chat": 2}):
            ma = [self._chat(thiet_bi=str(uuid.uuid4())).status_code for _ in range(3)]
        self.assertEqual(ma, [403, 403, 429])

    def test_header_cloudflare_khong_duoc_tin_khi_ket_noi_thang(self):
        yeu_cau = mock.Mock(client=mock.Mock(host="203.0.113.9"), headers={"cf-connecting-ip": "1.1.1.1"})
        self.assertEqual(main._ip_khach(yeu_cau), "203.0.113.9")
        yeu_cau = mock.Mock(client=mock.Mock(host="127.0.0.1"), headers={"cf-connecting-ip": "1.1.1.1"})
        self.assertEqual(main._ip_khach(yeu_cau), "1.1.1.1")

    def test_ma_nguoi_dung_web_khong_co_dau_hai_cham_de_khong_gop_gioi_han(self):
        self._identify()
        with mock.patch.object(main, "kiem_tra_rate_limit", return_value=None) as gioi_han:
            self._chat()
        self.assertEqual(gioi_han.call_args.args[0], f"web-{self.thiet_bi}")
        self.assertNotIn(":", gioi_han.call_args.args[0])
