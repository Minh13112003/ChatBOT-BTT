"""Chạy trong Docker sau nginx trên VPS (chatbot.benthanhtourist.com, 2026-11-26): IP khách thật, nạp lại kho tour sau đồng bộ."""
import unittest
from types import SimpleNamespace
from unittest import mock

import main
import rag


def yeu_cau(host, **headers):
    return SimpleNamespace(client=SimpleNamespace(host=host), headers={k.replace("_", "-"): v for k, v in headers.items()})


class IpKhach(unittest.TestCase):
    def test_sau_nginx_lay_ip_that_tu_x_forwarded_for(self):
        with mock.patch.object(main, "TRUST_PROXY", True):
            self.assertEqual(main._ip_khach(yeu_cau("172.18.0.5", x_forwarded_for="113.161.1.2")), "113.161.1.2")
            self.assertEqual(main._ip_khach(yeu_cau("172.18.0.5", x_forwarded_for="113.161.1.2, 10.0.0.1")), "113.161.1.2")

    def test_hai_khach_khac_nhau_khong_chung_gioi_han(self):
        with mock.patch.object(main, "TRUST_PROXY", True):
            a = main._ip_khach(yeu_cau("172.18.0.5", x_forwarded_for="1.1.1.1"))
            b = main._ip_khach(yeu_cau("172.18.0.5", x_forwarded_for="2.2.2.2"))
        self.assertNotEqual(a, b)

    def test_ket_noi_tu_ngoai_internet_khong_tin_header(self):
        with mock.patch.object(main, "TRUST_PROXY", True):
            self.assertEqual(main._ip_khach(yeu_cau("8.8.8.8", x_forwarded_for="1.1.1.1")), "8.8.8.8")

    def test_khong_bat_trust_proxy_thi_nhu_cu(self):
        with mock.patch.object(main, "TRUST_PROXY", False):
            self.assertEqual(main._ip_khach(yeu_cau("172.18.0.5", x_forwarded_for="1.1.1.1")), "172.18.0.5")


class NapLaiKho(unittest.TestCase):
    def test_nap_lai_kho_lay_lai_collection(self):
        cu = rag._collection
        with mock.patch.object(rag._client, "get_or_create_collection", return_value="kho-moi") as lay:
            rag.nap_lai_kho()
            self.assertEqual(rag._collection, "kho-moi")
            lay.assert_called_once()
        rag._collection = cu

    def test_khong_bat_tu_dong_bo_thi_khong_chay_luong(self):
        with mock.patch.object(main, "TU_DONG_BO_TOUR", False), mock.patch.object(main.threading, "Thread") as luong:
            main._bat_dong_bo_tour()
        luong.assert_not_called()


if __name__ == "__main__":
    unittest.main()
