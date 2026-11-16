"""Chat thường + các lớp bảo vệ của POST /chat (xác thực, chống spam, kiểm duyệt, chuyển nhân viên)."""
import uuid

import main
from moderation import co_noi_dung_nhay_cam
from tests.helpers import NenTest, THE_DALAT, THE_NGA

THE_DAY_DU = {
    "tour_key": "k-nga", "id": "i1", "ten": "Du Lịch Nga - Moscow", "gia": "135990000", "so_ngay": 9,
    "ngay_khoi_hanh": "2026-12-04", "so_cho_con": 9, "anh": " ", "url": "https://x", "diem_den": "Liên bang Nga", "loai_hinh": "Nước Ngoài",
}


class XacThucVaDauVao(NenTest):
    def test_health_khong_can_token(self):
        self.assertEqual(self.client.get("/health").json(), {"ok": True})

    def test_thieu_token_tra_401(self):
        main.app.dependency_overrides.clear()
        r = self.client.post("/chat", json={"message": "hi", "conversation_id": self.conv})
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/chat", json={"message": "hi", "conversation_id": self.conv}, headers={"Authorization": "Basic abc"})
        self.assertEqual(r.status_code, 401)
        self.gemini.assert_not_called()

    def test_conversation_id_sai_tra_422(self):
        for cid in ["abc", "", "x" * 65]:
            r = self.client.post("/chat", json={"message": "hi", "conversation_id": cid}, headers={"Authorization": "Bearer t"})
            self.assertEqual(r.status_code, 422)

    def test_tin_nhan_rong_khong_goi_ai(self):
        for msg in ["", "   ", "\n"]:
            with self.subTest(msg=repr(msg)):
                r = self.client.post("/chat", json={"message": msg, "conversation_id": self.conv}, headers={"Authorization": "Bearer t"})
                self.assertIn(r.status_code, (200, 422))
                self.gemini.assert_not_called()

    def test_tin_nhan_qua_dai_bi_tu_choi_khong_goi_ai(self):
        r = self.client.post("/chat", json={"message": "a " * 3000, "conversation_id": self.conv}, headers={"Authorization": "Bearer t"})
        self.assertIn(r.status_code, (200, 422))
        self.gemini.assert_not_called()


class ChatThuong(NenTest):
    def test_tra_loi_kem_the_tour_dung_hop_dong(self):
        self.tours_chat = [THE_DAY_DU]
        res = self.gui("Có tour Nga không?")
        self.assertEqual(res["reply"], "(Gemini) Đây là câu trả lời.")
        the = res["tours"][0]
        self.assertEqual(set(the), {"tour_key", "id", "ten", "gia", "so_ngay", "ngay_khoi_hanh", "so_cho_con", "anh", "url", "diem_den", "loai_hinh"})
        self.assertEqual(the["gia"], 135990000)
        self.assertIsNone(the["anh"])  # ảnh rỗng -> null để app hiện ảnh mặc định
        self.assertEqual(res["goi_y"], ["Tôi muốn đặt tour này"])

    def test_chao_hoi_khong_kem_tour_khong_goi_y_dat(self):
        res = self.gui("Xin chào")
        self.assertEqual(res["tours"], [])
        self.assertEqual(res["goi_y"], [])

    def test_lich_su_duoc_gui_lai_cho_ai(self):
        self.gui("Xin chào")
        self.gui("Bạn tên gì?")
        lich_su = self.gemini.call_args[0][2]
        self.assertEqual([m["role"] for m in lich_su], ["user", "assistant"])
        self.assertEqual(lich_su[0]["content"], "Xin chào")

    def test_ai_loi_thi_van_tra_loi_tu_te_kem_tour(self):
        """Gemini treo/lỗi/hết quota: khách vẫn phải nhận được câu trả lời và thẻ tour, không phải lỗi 500."""
        self.tours_chat = [THE_DAY_DU]
        self.gemini.side_effect = RuntimeError("quota")
        r = self.client.post("/chat", json={"message": "Có tour Nga không?", "conversation_id": self.conv}, headers={"Authorization": "Bearer t"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["reply"])
        self.assertEqual(len(r.json()["tours"]), 1)

    def test_xoa_cuoc_tro_chuyen_xoa_lich_su(self):
        self.gui("Xin chào")
        self.client.delete(f"/chat/{self.conv}", headers={"Authorization": "Bearer t"})
        self.gui("Bạn tên gì?")
        self.assertEqual(self.gemini.call_args[0][2], [])

    def test_nguoi_khac_khong_xoa_duoc_lich_su_cua_minh(self):
        self.gui("Xin chào")
        self.nguoi_dung_hien_tai = "u2"
        self.client.delete(f"/chat/{self.conv}", headers={"Authorization": "Bearer t"})
        self.nguoi_dung_hien_tai = "u1"
        self.gui("Bạn tên gì?")
        self.assertEqual(len(self.gemini.call_args[0][2]), 2)


class ChuyenNhanVien(NenTest):
    def test_khieu_nai_hoan_tien_gap_nguoi_that(self):
        for cau in ["Tôi muốn khiếu nại", "Cho tôi gặp nhân viên", "Tôi muốn hoàn tiền", "Tôi muốn huỷ tour", "toi muon huy tour"]:
            with self.subTest(cau=cau):
                self.setUp()
                res = self.gui(cau)
                self.assertIn("zalo.me", res["reply"])
                self.assertEqual(res["handoff"]["tom_tat"], "(tóm tắt)")
                self.gemini.assert_not_called()


class KiemDuyet(NenTest):
    def test_chan_tu_tuc_khong_goi_ai(self):
        for cau in ["đm tour gì mà đắt", "Đ.M", "óc chó", "tour như lồn"]:
            with self.subTest(cau=cau):
                res = self.gui(cau)
                self.assertEqual(res["reply"], main.TRA_LOI_KHI_BI_CHAN)
                self.gemini.assert_not_called()

    def test_khong_chan_nham_cau_binh_thuong(self):
        cau_thuong = [
            "Tour này có ngủ đêm trên tàu không?",
            "Khách sạn mấy sao, phòng ngủ có rộng không",
            "Tư vấn tour Phú Quốc cho gia đình",
            "Tôi muốn đi du lịch các nước châu Âu",
            "ngân sách tầm 20tr",
            "Tour có đi Đà Nẵng không",
            "toi muon di du lich",
            "Cho mình hỏi tour đi Ngũ Hành Sơn",
            "2 người lớn 1 trẻ em",
            "Tôi muốn đặt tour Nga",
            "toi di 2 nguoi lon va 1 tre em, buoi sang khoi hanh",
        ]
        for cau in cau_thuong:
            with self.subTest(cau=cau):
                self.assertFalse(co_noi_dung_nhay_cam(cau))


class ChongSpam(NenTest):
    bo_rate_limit = False

    def test_hai_cau_lien_tiep_qua_nhanh(self):
        self.gui("Xin chào")
        res = self.gui("Bạn tên gì?")
        self.assertIn("hơi nhanh", res["reply"])
        self.assertEqual(self.gemini.call_count, 1)

    def test_bam_nut_khong_bi_tinh_la_spam(self):
        self.gui("Tôi muốn đặt tour Nga")
        res = self.bam("dot:N1")
        self.assertNotIn("hơi nhanh", res["reply"])
        self.co_nut(res, "sl:")

    def test_doi_cuoc_tro_chuyen_khong_ne_duoc_gioi_han(self):
        self.gui("Xin chào")
        res = self.gui("Bạn tên gì?", conv=str(uuid.uuid4()))
        self.assertIn("hơi nhanh", res["reply"])

    def test_nguoi_khac_khong_bi_anh_huong(self):
        self.gui("Xin chào")
        self.nguoi_dung_hien_tai = "u2"
        self.assertNotIn("hơi nhanh", self.gui("Xin chào")["reply"])
