from __future__ import annotations

import unittest

from cs_service import transform_operator_note


class CsDraftTransformerTests(unittest.TestCase):
    def test_swelling_requires_stop_and_new_product_exchange(self) -> None:
        result = transform_operator_note(
            question="배터리가 부풀었어요. 어떻게 하죠?",
            operator_note="사용 중단, 사진과 주문번호 요청, 교환",
            product_model="QP1000C",
        )
        self.assertIn("사용과 충전을 즉시 중단", result.text)
        self.assertIn("새상품 교환", result.text)
        self.assertEqual(result.risk_level, "urgent")
        self.assertTrue(result.requires_approval)

    def test_discontinued_repair_question_routes_to_compensation_sale(self) -> None:
        result = transform_operator_note(
            question="QP1000A 수리되나요?",
            operator_note="고장 확인",
            product_model="QP1000A",
        )
        self.assertIn("신형 QP1000C 보상판매", result.text)
        self.assertNotIn("새상품 교환 방식으로 AS", result.text)

    def test_current_product_repair_question_routes_to_replacement(self) -> None:
        result = transform_operator_note(
            question="수리가 가능한가요?",
            operator_note="AS 접수",
            product_model="QP2000C",
        )
        self.assertIn("수리가 아닌 새상품 교환", result.text)

    def test_heat_question_asks_about_device_warning(self) -> None:
        result = transform_operator_note(
            question="충전 중 너무 뜨거워요",
            operator_note="온도 경고 확인",
            product_model="QPD330",
        )
        self.assertIn("온도 경고나 충전 중단 문구", result.text)


if __name__ == "__main__":
    unittest.main()
