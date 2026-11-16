"""Ghi lịch sử chat khi backend trang quản trị không chạy, và các tin chỉ ghi lại (nhạy cảm, nút bấm). Không chạm database thật."""
import time
import uuid
from unittest import mock

import httpx

import admin_chat
import config
import lich_su_db
import main
from tests.helpers import NenTest


class HamThuanKhopBackend(NenTest):
    """Cùng các ca trong backend/src/common/text.spec.ts: lệch với TypeScript là 2 đường ghi xử lý khách khác nhau."""

    def test_cung_mot_nguoi(self):
        for ten in ["Hoa", "Nguyễn Hoa", "Thị Hoa", "nguyen thi hoa"]:
            self.assertTrue(lich_su_db.cung_mot_nguoi("Nguyễn Thị Hoa", ten), ten)
        self.assertFalse(lich_su_db.cung_mot_nguoi("Nguyễn Thị Hoa", "Tuấn"))
        self.assertFalse(lich_su_db.cung_mot_nguoi("", "Hoa"))

    def test_chuan_hoa_sdt(self):
        self.assertEqual(lich_su_db.chuan_hoa_sdt("0900 000 101"), "0900000101")
        self.assertEqual(lich_su_db.chuan_hoa_sdt("+84900000101"), "0900000101")
        self.assertEqual(lich_su_db.chuan_hoa_sdt("84900000101"), "0900000101")
        self.assertIsNone(lich_su_db.chuan_hoa_sdt("091234567"))  # số mặc định 9 chữ số của tài khoản chưa cập nhật
        self.assertIsNone(lich_su_db.chuan_hoa_sdt(None))

    def test_gop_ten_giu_ban_day_du_nhat(self):
        self.assertEqual(lich_su_db.gop_ten("Hoa", [], "Nguyễn Thị Hoa"), ("Nguyễn Thị Hoa", ["Hoa"]))
        self.assertEqual(lich_su_db.gop_ten("Nguyễn Thị Hoa", ["Hoa"], "hoa"), ("Nguyễn Thị Hoa", ["Hoa"]))

    def test_chuoi_ket_noi(self):
        tu_xa = lich_su_db.chuoi_ket_noi("postgresql://u:p%40ss@aws.pooler.supabase.com:6543/postgres?pgbouncer=true&connection_limit=5")
        self.assertEqual(tu_xa, "postgresql://u:p%40ss@aws.pooler.supabase.com:6543/postgres?sslmode=require")
        self.assertEqual(lich_su_db.chuoi_ket_noi("postgresql://u@127.0.0.1:5432/db"), "postgresql://u@127.0.0.1:5432/db")


class NenMock(NenTest):
    def setUp(self):
        super().setUp()
        self.goi = mock.Mock(return_value=None)  # Backend trang quản trị đang tắt
        self.ghi_tin = mock.Mock(return_value=True)
        self.ghi_token = mock.Mock(return_value=True)
        self.ghi_don = mock.Mock(return_value=True)
        for doi_tuong, ten, gia_tri in [
            (admin_chat, "_goi", self.goi),
            (lich_su_db, "ghi_tin", self.ghi_tin),
            (lich_su_db, "ghi_token", self.ghi_token),
            (lich_su_db, "ghi_don", self.ghi_don),
        ]:
            p = mock.patch.object(doi_tuong, ten, gia_tri)
            p.start()
            self.addCleanup(p.stop)

    def tin_da_ghi(self) -> list[tuple[str, str]]:
        return [(t["loai"], t["text"]) for c in self.ghi_tin.call_args_list for t in c.args[3]]


class BackendTat(NenMock):
    def test_khach_chat_ghi_ca_cau_hoi_va_cau_tra_loi_vao_database(self):
        self.assertEqual(self.gui("Có tour Nga không?")["reply"], "(Gemini) Đây là câu trả lời.")
        self.assertEqual(self.tin_da_ghi(), [("CUSTOMER", "Có tour Nga không?"), ("BOT", "(Gemini) Đây là câu trả lời.")])

    def test_doi_gap_nhan_vien_danh_dau_lien_he_va_van_co_zalo(self):
        res = self.gui("Cho tôi gặp nhân viên")
        self.assertIn("handoff", res)
        self.assertTrue(self.ghi_tin.call_args_list[0].kwargs["doi_nguoi"])
        self.assertEqual(self.tin_da_ghi()[0], ("CUSTOMER", "Cho tôi gặp nhân viên"))
        self.assertEqual(self.tin_da_ghi()[1][0], "BOT")

    def test_token_chi_ghi_khi_ghi_duoc_cau_tra_loi(self):
        admin_chat.bot_reply("APP", "u1", "Câu trả lời", None, {"model": "m", "inputTokens": 1, "outputTokens": 2})
        self.ghi_token.assert_called_once()
        self.ghi_tin.return_value = False
        self.ghi_token.reset_mock()
        admin_chat.bot_reply("APP", "u1", "Câu trả lời", None, {"model": "m", "inputTokens": 1, "outputTokens": 2})
        self.ghi_token.assert_not_called()

    def test_don_dat_tour_ghi_thang(self):
        don = {"tourName": "Đà Lạt", "guests": 2, "amount": 100, "orderCode": "bk-1"}
        admin_chat.deal("APP", "u1", don, None)
        self.ghi_don.assert_called_once_with("APP", "u1", None, don)

    def test_ghi_database_hong_khach_van_nhan_cau_tra_loi(self):
        self.ghi_tin.return_value = False
        self.assertEqual(self.gui("Có tour Nga không?")["reply"], "(Gemini) Đây là câu trả lời.")


class TamNgungGoiBackend(NenTest):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(admin_chat, "_khong_ket_noi_duoc_luc", float("-inf"))
        p.start()
        self.addCleanup(p.stop)
        for ten, gia_tri in [("ADMIN_CHAT_URL", "http://admin"), ("INGEST_API_KEY", "k")]:
            q = mock.patch.object(config, ten, gia_tri)
            q.start()
            self.addCleanup(q.stop)

    def test_vua_khong_ket_noi_duoc_thi_khong_thu_lai_ngay(self):
        with mock.patch.object(admin_chat._client, "request", side_effect=httpx.ConnectError("tắt")) as goi:
            self.assertIsNone(admin_chat._goi("POST", "/inbound"))
            self.assertIsNone(admin_chat._goi("POST", "/bot-reply"))
        self.assertEqual(goi.call_count, 1)

    def test_het_thoi_gian_tam_ngung_thi_goi_lai(self):
        admin_chat._khong_ket_noi_duoc_luc = time.monotonic() - admin_chat.TAM_NGUNG_GOI_GIAY - 1
        with mock.patch.object(admin_chat._client, "request", return_value="ok") as goi:
            self.assertEqual(admin_chat._goi("POST", "/inbound"), "ok")
        goi.assert_called_once()

    def test_loi_doc_cham_khong_tam_ngung(self):
        with mock.patch.object(admin_chat._client, "request", side_effect=httpx.ReadTimeout("chậm")) as goi:
            admin_chat._goi("POST", "/inbound")
            admin_chat._goi("POST", "/inbound")
        self.assertEqual(goi.call_count, 2)


class LoiDatabase(NenTest):
    def test_mat_ket_noi_khong_nem_loi_ra_ngoai(self):
        with mock.patch.object(config, "ADMIN_DATABASE_URL", "postgresql://u@127.0.0.1:1/x"), mock.patch.object(lich_su_db, "_ket_noi", side_effect=OSError("mất mạng")):
            self.assertFalse(lich_su_db.ghi_tin("APP", "u1", None, [{"loai": "BOT", "text": "x"}]))
            self.assertFalse(lich_su_db.ghi_token("APP", "u1", None, {"model": "m", "inputTokens": 1, "outputTokens": 2}))
            self.assertFalse(lich_su_db.ghi_don("APP", "u1", None, {"tourName": "T", "guests": 1, "amount": 1}))
            self.assertIsNone(lich_su_db.dinh_danh("WEB", "d", "Hoa", "0900000101"))


class TinChiGhiLai(NenMock):
    def test_tin_nhay_cam_duoc_luu_khong_goi_ai_khong_bao_nhan_vien(self):
        with mock.patch.object(main, "co_noi_dung_nhay_cam", return_value=True), mock.patch.object(admin_chat, "inbound") as inbound:
            res = self.gui("câu nhạy cảm")
        self.assertEqual(res["reply"], main.TRA_LOI_KHI_BI_CHAN)
        inbound.assert_not_called()
        self.gemini.assert_not_called()
        self.assertEqual(self.tin_da_ghi(), [("CUSTOMER", "câu nhạy cảm"), ("BOT", main.TRA_LOI_KHI_BI_CHAN)])
        with main.khoi_tao_database.__globals__["ket_noi"]() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0], 0)  # không vào ngữ cảnh của AI

    def test_tin_nhay_cam_di_qua_cong_history_khi_backend_chay(self):
        self.goi.return_value = mock.Mock(is_success=True, status_code=200, json=lambda: {"saved": 2})
        with mock.patch.object(main, "co_noi_dung_nhay_cam", return_value=True):
            self.gui("câu nhạy cảm")
        duong_dan = [c.args[1] for c in self.goi.call_args_list]
        self.assertEqual(duong_dan, ["/history"])
        self.ghi_tin.assert_not_called()

    def test_bam_nut_luu_dung_chu_tren_nut_va_khach_truoc_bot(self):
        with mock.patch.object(main.dat_tour, "xu_ly", return_value={"reply": "Bạn chọn ngày", "tours": [], "goi_y": []}):
            self.client.post("/chat", json={"message": "", "conversation_id": self.conv, "action": {"id": "xn:dong_y", "label": "Đồng ý"}}, headers={"Authorization": "Bearer t"})
        self.assertEqual(self.tin_da_ghi(), [("CUSTOMER", "Đồng ý"), ("BOT", "Bạn chọn ngày")])

    def test_app_cu_chua_gui_chu_tren_nut_van_luu_ma_nut(self):
        with mock.patch.object(main.dat_tour, "xu_ly", return_value={"reply": "OK", "tours": [], "goi_y": []}):
            self.gui(action="xn:dong_y")
        self.assertEqual(self.tin_da_ghi()[0], ("CUSTOMER", "[Khách bấm nút xn:dong_y]"))

    def test_web_khong_ghi_nut_bam_de_tranh_nhet_du_lieu(self):
        thiet_bi = str(uuid.uuid4())
        main._LUOT_THEO_IP.clear()
        self.client.post("/web/identify", json={"device_id": thiet_bi, "name": "Hoa", "phone": "0900000101"})
        self.client.post("/web/chat", json={"device_id": thiet_bi, "conversation_id": self.conv, "message": "", "action": {"id": "x", "label": "rác"}})
        self.assertEqual(self.tin_da_ghi(), [])

    def test_qua_gioi_han_toc_do_thi_khong_luu(self):
        with mock.patch.object(main, "kiem_tra_rate_limit", return_value="Bạn thao tác hơi nhanh"):
            self.gui("Spam")
        self.assertEqual(self.tin_da_ghi(), [])


class GioiHanKhiNhanVienXuLy(NenMock):
    GIOI_HAN = "Bạn thao tác hơi nhanh"

    def setUp(self):
        super().setUp()
        p = mock.patch.object(main, "kiem_tra_rate_limit", return_value=self.GIOI_HAN)
        p.start()
        self.addCleanup(p.stop)
        self.inbound = mock.Mock(return_value={"conversationId": "c1", "action": "STAFF"})
        q = mock.patch.object(admin_chat, "inbound", self.inbound)
        q.start()
        self.addCleanup(q.stop)

    def _che_do(self, gia_tri):
        p = mock.patch.object(admin_chat, "updates", return_value={"mode": gia_tri, "items": []})
        p.start()
        self.addCleanup(p.stop)

    def test_nhan_vien_dang_xu_ly_tin_van_toi_noi(self):
        self._che_do("STAFF")
        res = self.gui("Dòng thứ hai gõ nhanh")
        self.assertEqual(res["che_do"], "STAFF")
        self.assertEqual(self.inbound.call_args.args[2], "Dòng thứ hai gõ nhanh")
        self.gemini.assert_not_called()

    def test_bot_dang_tra_loi_van_giu_gioi_han(self):
        self._che_do("BOT")
        self.assertEqual(self.gui("Spam")["reply"], self.GIOI_HAN)
        self.inbound.assert_not_called()
        self.gemini.assert_not_called()
        self.assertEqual(self.tin_da_ghi(), [])

    def test_khong_cham_gioi_han_thi_khong_hoi_trang_thai(self):
        with mock.patch.object(main, "kiem_tra_rate_limit", return_value=None), mock.patch.object(admin_chat, "nhan_vien_dang_xu_ly") as hoi:
            self.gui("Câu bình thường")
        hoi.assert_not_called()

    def test_backend_tat_doc_che_do_tu_database_luu_tin_khong_goi_ai(self):
        self.inbound.return_value = None
        with mock.patch.object(lich_su_db, "che_do", return_value="STAFF"):
            res = self.gui("Tin lúc backend tắt")
        self.assertEqual(res["reply"], self.GIOI_HAN)
        self.assertEqual(self.tin_da_ghi(), [("CUSTOMER", "Tin lúc backend tắt")])
        self.gemini.assert_not_called()

    def test_nhan_vien_vua_tra_khach_cho_bot_khong_goi_ai(self):
        self._che_do("STAFF")
        self.inbound.return_value = {"conversationId": "c1", "action": "BOT"}
        self.assertEqual(self.gui("Tin vượt giới hạn")["reply"], self.GIOI_HAN)
        self.gemini.assert_not_called()

    def test_khong_doc_duoc_che_do_thi_giu_gioi_han(self):
        with mock.patch.object(lich_su_db, "che_do", return_value=None):
            self.assertEqual(self.gui("Spam")["reply"], self.GIOI_HAN)
        self.inbound.assert_not_called()


class KhachWebBackendTat(NenMock):
    def setUp(self):
        super().setUp()
        main._LUOT_THEO_IP.clear()
        self.thiet_bi = str(uuid.uuid4())

    def _identify(self):
        return self.client.post("/web/identify", json={"device_id": self.thiet_bi, "name": "Hoa", "phone": "0900000101"})

    def test_van_nhan_khach_va_ghi_thang(self):
        with mock.patch.object(config, "ADMIN_DATABASE_URL", "postgresql://x"), mock.patch.object(lich_su_db, "dinh_danh", return_value={"returning": False, "loadHistory": False}) as dd:
            r = self._identify()
        self.assertEqual(r.status_code, 200)
        dd.assert_called_once()

    def test_ten_khac_han_van_bi_chan(self):
        with mock.patch.object(config, "ADMIN_DATABASE_URL", "postgresql://x"), mock.patch.object(lich_su_db, "dinh_danh", return_value={"code": "NAME_MISMATCH", "message": "Nhập lại"}):
            r = self._identify()
        self.assertEqual((r.status_code, r.json()["code"]), (409, "NAME_MISMATCH"))

    def test_ca_backend_va_database_deu_hong_thi_bao_ban(self):
        with mock.patch.object(config, "ADMIN_DATABASE_URL", "postgresql://x"), mock.patch.object(lich_su_db, "dinh_danh", return_value=None):
            r = self._identify()
        self.assertEqual(r.status_code, 503)
