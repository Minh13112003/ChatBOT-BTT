"""Câu trả lời của AI không được dừng giữa chừng trước mặt khách: hỏi lại 1 lần, vẫn dở thì cắt về câu trọn vẹn."""
import unittest
from types import SimpleNamespace
from unittest import mock

import openai

import llm_gemini

CAU_DO = "Mình có 2 tour Noel rất đẹp. Ngoài ra còn tour đi Thái Lan, chương"
CAU_DU = "Mình có 2 tour Noel rất đẹp, bạn xem thẻ bên dưới nhé."
CAU_DU_PHONG_CHUNG = "Mình tìm được vài tour phù hợp, bạn xem chi tiết bên dưới nhé:"


def tra_ve(noi_dung, finish_reason="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=noi_dung), finish_reason=finish_reason)])


def loi_qua_tai():
    return openai.APITimeoutError(request=mock.Mock())


class HoiGemini(unittest.TestCase):
    def chay(self, *ket_qua):
        with mock.patch.object(llm_gemini.client.chat.completions, "create", side_effect=list(ket_qua)) as goi:
            self.goi = goi
            return llm_gemini.hoi_gemini("tour Noel", [], [])

    def test_cau_du_khong_goi_lai(self):
        self.assertEqual(self.chay(tra_ve(CAU_DU)), CAU_DU)
        self.assertEqual(self.goi.call_count, 1)

    def test_luon_giam_suy_luan_an(self):
        self.chay(tra_ve(CAU_DU))
        self.assertEqual(self.goi.call_args.kwargs["reasoning_effort"], "low")

    def test_bi_cat_thi_hoi_lai_bang_model_du_phong(self):
        self.assertEqual(self.chay(tra_ve(CAU_DO, "length"), tra_ve(CAU_DU)), CAU_DU)
        self.assertEqual(self.goi.call_args_list[1].kwargs["model"], llm_gemini.GEMINI_MODEL_DU_PHONG)

    def test_dung_giua_chung_du_bao_stop_cung_hoi_lai(self):
        self.assertEqual(self.chay(tra_ve(CAU_DO, "stop"), tra_ve(CAU_DU)), CAU_DU)

    def test_van_bi_cat_thi_giu_cau_tron_ven(self):
        self.assertEqual(self.chay(tra_ve(CAU_DO, "length"), tra_ve(CAU_DO, "length")), "Mình có 2 tour Noel rất đẹp.")

    def test_hoi_lai_loi_thi_van_khong_de_lo_cau_do(self):
        self.assertEqual(self.chay(tra_ve(CAU_DO, "length"), loi_qua_tai()), "Mình có 2 tour Noel rất đẹp.")

    def test_khong_con_cau_nao_tron_ven_thi_dung_cau_chung(self):
        self.assertEqual(self.chay(tra_ve("Mình có 2 tour", "length"), tra_ve("Mình có 2 tour", "length")), CAU_DU_PHONG_CHUNG)

    def test_het_thoi_gian_thi_khong_hoi_lai(self):
        with mock.patch.object(llm_gemini.time, "monotonic", side_effect=[0.0, 27.0]):
            self.assertEqual(self.chay(tra_ve(CAU_DO, "length")), "Mình có 2 tour Noel rất đẹp.")
        self.assertEqual(self.goi.call_count, 1)

    def test_timeout_lan_hoi_lai_khong_vuot_thoi_gian_con_lai(self):
        with mock.patch.object(llm_gemini.time, "monotonic", side_effect=[0.0, 24.0]):
            self.chay(tra_ve(CAU_DO, "length"), tra_ve(CAU_DU))
        self.assertEqual(self.goi.call_args_list[1].kwargs["timeout"], 4.0)


class NhanBietCauDo(unittest.TestCase):
    def test_cau_tron_ven(self):
        for cau in ["Mời bạn xem nhé.", "Bạn xem thẻ bên dưới nhé:", "Có ngay ạ!", "Đi không?", "Tuyệt lắm 🎄",
                    "Các tour:\n- Thái Lan\n- Giá 10.000.000đ"]:
            with self.subTest(cau=cau):
                self.assertFalse(llm_gemini._bi_cat_giua_chung(cau, "stop"))

    def test_cau_do_dang(self):
        for cau in ["Đối với Thái Lan, hiện có 2 chương", "từ Đài Loan, Hong Kong,", "đi từ 3 -"]:
            with self.subTest(cau=cau):
                self.assertTrue(llm_gemini._bi_cat_giua_chung(cau, "stop"))
        self.assertTrue(llm_gemini._bi_cat_giua_chung("Câu đủ.", "length"))

    def test_cat_khong_nham_dau_cham_trong_gia(self):
        self.assertEqual(llm_gemini._cat_ve_cau_tron_ven("Giá từ 10.000.000đ đến 20.000"), "")
        self.assertEqual(llm_gemini._cat_ve_cau_tron_ven("Có tour. Giá từ 10.000.000đ đến"), "Có tour.")
        self.assertEqual(llm_gemini._cat_ve_cau_tron_ven("- Tour A\n- Tour B dở"), "- Tour A")


if __name__ == "__main__":
    unittest.main()
