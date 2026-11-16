"""Dữ liệu giả + lớp nền cho test. Mọi thứ gọi ra ngoài (Gemini, NestJS, benthanhtourist.com) đều bị thay."""
import unittest
import uuid
from datetime import date, timedelta
from unittest import mock

from fastapi.testclient import TestClient

import config
import database
import dat_tour
import main

GIA = 10_000_000


def ngay(n: int) -> str:
    """Ngày ISO cách hôm nay n ngày (để test không hết hạn theo thời gian)."""
    return (date.today() + timedelta(days=n)).isoformat()


def dmy(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}"


# Tour trong nước, CHỈ 1 ngày khởi hành
TOUR_1NGAY = {
    "id": "D1", "name": "Du Lịch Đà Lạt - Thác Datanla", "image": "https://x/tour/trong-nuoc/da-lat.webp",
    "tour_days": [{"id": "D1", "departure_date": ngay(30), "price": GIA, "stock_qty": 10, "code": "DL01"}],
}
# Tour nước ngoài, 3 ngày còn chỗ + 1 ngày đã qua + 1 ngày hết chỗ
TOUR_NHIEU = {
    "id": "N1", "name": "Du Lịch Nga - Moscow", "image": "https://x/tour/nuoc-ngoai/nga.webp",
    "tour_days": [
        {"id": "N3", "departure_date": ngay(90), "price": GIA + 2_000_000, "stock_qty": 3, "code": "NGA03"},
        {"id": "N1", "departure_date": ngay(20), "price": GIA, "stock_qty": 30, "code": "NGA01"},
        {"id": "N2", "departure_date": ngay(50), "price": GIA, "stock_qty": 9, "code": "NGA02"},
        {"id": "N0", "departure_date": ngay(-5), "price": GIA, "stock_qty": 9, "code": "NGA00"},
        {"id": "N9", "departure_date": ngay(70), "price": GIA, "stock_qty": 0, "code": "NGA09"},
    ],
}
TOUR_HET_CHO = {
    "id": "H1", "name": "Du Lịch Huế", "image": "https://x/tour/trong-nuoc/hue.webp",
    "tour_days": [{"id": "H1", "departure_date": ngay(10), "price": GIA, "stock_qty": 0, "code": "HUE01"}],
}
TOUR_KHONG_GIA = {
    "id": "G1", "name": "Du Lịch Côn Đảo", "image": "https://x/tour/trong-nuoc/con-dao.webp",
    "tour_days": [{"id": "G1", "departure_date": ngay(15), "price": None, "stock_qty": 5, "code": "CD01"}],
}
TOURS_LIVE = {"k-dalat": TOUR_1NGAY, "k-nga": TOUR_NHIEU, "k-hue": TOUR_HET_CHO, "k-condao": TOUR_KHONG_GIA}

THE_DALAT = {"tour_key": "k-dalat", "ten": TOUR_1NGAY["name"]}
THE_NGA = {"tour_key": "k-nga", "ten": TOUR_NHIEU["name"]}
THE_HUE = {"tour_key": "k-hue", "ten": TOUR_HET_CHO["name"]}
THE_CONDAO = {"tour_key": "k-condao", "ten": TOUR_KHONG_GIA["name"]}

THAN_NHAN = [
    {"id": "r-an", "fullName": "Nguyễn Văn An", "dateOfBirth": "1990-05-01"},
    {"id": "r-lan", "fullName": "Trần Thị Lan", "dateOfBirth": "1992-08-15"},
    {"id": "r-bi", "fullName": "Nguyễn Gia Bảo", "dateOfBirth": "2019-01-20"},
]


def tim_tour_gia(cau_hoi: str, *a, **k) -> list[dict]:
    """Thay cho dat_tour.tim_tour_theo_cau: tìm theo từ khoá không dấu."""
    nd = dat_tour._nd(cau_hoi)
    if "da lat" in nd:
        return [dict(THE_DALAT)]
    if "nga" in nd.split():
        return [dict(THE_NGA)]
    if "hue" in nd.split():
        return [dict(THE_HUE)]
    if "con dao" in nd:
        return [dict(THE_CONDAO)]
    if "mien" in nd.split():  # "tour miền ..." -> nhiều tour
        return [dict(THE_DALAT), dict(THE_NGA), dict(THE_HUE)]
    return []


class NenTest(unittest.TestCase):
    """Mỗi test có DB sạch, 1 người dùng 'u1', 1 cuộc trò chuyện riêng."""

    user = "u1"
    than_nhan: list | None = THAN_NHAN
    dung_than_nhan = True  # mặc định bật bước thân nhân để các test cũ vẫn bảo vệ code; test_tat_than_nhan.py thử trạng thái tắt (thực tế đang chạy)
    bo_rate_limit = True

    def setUp(self):
        with database.ket_noi() as conn:
            conn.execute("DELETE FROM chat_messages")
            conn.execute("DELETE FROM booking_state")
        self.conv = str(uuid.uuid4())
        self.nguoi_dung_hien_tai = self.user
        self.gemini = mock.Mock(return_value="(Gemini) Đây là câu trả lời.")
        self.tom_tat = mock.Mock(return_value="(tóm tắt)")
        self.tours_chat = []  # tour mà chat thường (RAG) trả về
        # Kết quả giả của NestJS POST /api/v1/bookings — (booking, lỗi).
        # Test nào cần mô phỏng đặt hỏng thì gán lại, VD: (None, "Hết chỗ rồi").
        self.booking_ket_qua: tuple[dict | None, str | None] = ({"id": "bk-1"}, None)
        # Mock để test đếm số lần đặt (chống đặt trùng) và soi đơn gửi lên backend.
        self.tao_booking = mock.Mock(side_effect=lambda token, st: self.booking_ket_qua)

        async def _user():
            return self.nguoi_dung_hien_tai

        main.app.dependency_overrides[main.lay_nguoi_dung] = _user
        patches = [
            # .env trên máy có thể đã trỏ tới trang quản trị thật: test không bao giờ được gọi ra đó.
            mock.patch.object(config, "ADMIN_CHAT_URL", ""),
            mock.patch.object(config, "ADMIN_DATABASE_URL", ""),
            mock.patch.object(main, "hoi_gemini", self.gemini),
            mock.patch.object(main, "tom_tat_hoi_thoai", self.tom_tat),
            mock.patch.object(main, "tim_tour_lien_quan", lambda *a, **k: [dict(t) for t in self.tours_chat]),
            mock.patch.object(dat_tour, "tim_tour_theo_cau", lambda cau: [{"key": t["tour_key"], "ten": t["ten"]} for t in tim_tour_gia(cau)]),
            mock.patch.object(dat_tour, "lay_tour_live", lambda key: TOURS_LIVE.get(key)),
            mock.patch.object(dat_tour, "lay_than_nhan", lambda token: self.than_nhan),
            mock.patch.object(dat_tour, "DUNG_THAN_NHAN", self.dung_than_nhan),
            mock.patch.object(dat_tour, "tao_booking", self.tao_booking),
            # Tour gợi ý khi không tìm ra tour: mặc định rỗng để test không phụ thuộc dữ liệu Chroma thật trên máy
            mock.patch.object(dat_tour, "tour_goi_y", lambda *a, **k: []),
        ]
        if self.bo_rate_limit:
            patches.append(mock.patch.object(main, "kiem_tra_rate_limit", lambda *a, **k: None))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(main.app.dependency_overrides.clear)
        self.client = TestClient(main.app)

    # ---- gọi API
    def gui(self, message: str = "", action: str | None = None, values: list[str] | None = None, conv: str | None = None) -> dict:
        body = {"message": message, "conversation_id": conv or self.conv}
        if action:
            body["action"] = {"id": action, **({"values": values} if values is not None else {})}
        r = self.client.post("/chat", json=body, headers={"Authorization": "Bearer token-gia"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def bam(self, action: str, values: list[str] | None = None) -> dict:
        return self.gui(action=action, values=values)

    # ---- tiện ích kiểm tra
    @staticmethod
    def ids(res: dict) -> list[str]:
        return [c["id"] for c in res.get("choices", [])]

    def co_nut(self, res: dict, tien_to: str):
        self.assertTrue(any(i.startswith(tien_to) for i in self.ids(res)), f"Thiếu nút '{tien_to}…' trong {self.ids(res)} | reply: {res['reply']}")

    def khong_nut(self, res: dict, tien_to: str):
        self.assertFalse(any(i.startswith(tien_to) for i in self.ids(res)), f"Không được có nút '{tien_to}…': {self.ids(res)}")

    def trang_thai(self) -> dict:
        return dat_tour._doc(f"{self.nguoi_dung_hien_tai}:{self.conv}") or {}

    def don_da_gui(self) -> dict:
        """Trạng thái chatbot dùng để tạo booking ở lần đặt gần nhất (tour / đợt / số khách)."""
        self.assertTrue(self.tao_booking.called, "Chatbot chưa gọi đặt tour lần nào")
        return self.tao_booking.call_args[0][1]

    def don_phang(self) -> dict:
        """Đơn vừa gửi lên backend, quy về dạng phẳng cho dễ so sánh trong test."""
        st = self.don_da_gui()
        return {
            "tour_key": st["tour"]["key"],
            "departure_key": st["dot"]["key"],
            "departure_date": st["dot"]["date"],
            "adults": st["adults"],
            "children": st["children"],
            "infants": st["infants"],
            "relative_ids": st.get("relative_ids", []),
        }

    # ---- đi nhanh tới một bước
    def toi_buoc_so_nguoi(self, cau="Tôi muốn đặt tour Đà Lạt") -> dict:
        return self.gui(cau)

    def toi_buoc_xac_nhan(self, sl="sl:2,1,0", chon=("r-an",)) -> dict:
        self.gui("Tôi muốn đặt tour Nga")
        self.bam("dot:N1")
        res = self.bam(sl)
        if "nguoi:skip" in self.ids(res):
            res = self.bam("nguoi:ok", list(chon))
        return res
