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

    def test_question_creates_swelling_draft_without_operator_note(self) -> None:
        result = transform_operator_note(
            question="배터리가 부풀었어요. 어떻게 하죠?",
            product_model="QP1000C",
        )
        self.assertIn("사용과 충전을 즉시 중단", result.text)
        self.assertEqual(result.category, "안전_팽창")

    def test_charging_failure_creates_replacement_draft_without_operator_note(self) -> None:
        result = transform_operator_note(
            question="QP2000C가 충전이 안 돼요.",
            product_model="QP2000C",
        )
        self.assertIn("새상품 교환", result.text)

    def test_unknown_question_requests_only_required_context(self) -> None:
        result = transform_operator_note(question="사용 방법을 알려주세요.", product_name="리큐엠 충전기")
        self.assertIn("리큐엠 충전기", result.text)
        self.assertIn("담당 부서", result.text)
        self.assertNotIn("제품 모델과 구매 정보", result.text)

    def test_galaxy_book_question_explains_qpd330_output_limit(self) -> None:
        result = transform_operator_note(
            question="삼성 갤럭시북 노트북도 사용 가능한가요?",
            product_model="QPD330",
            product_name="리큐엠 2포트 30W GaN 고속 충전기 QPD330",
        )
        self.assertIn("최대 30W", result.text)
        self.assertIn("권장 충전 출력", result.text)

    def test_spam_inquiry_does_not_create_customer_answer(self) -> None:
        result = transform_operator_note(question="300만 커뮤니티 핫딜 광고입니다. 오픈채팅으로 연락주세요")
        self.assertEqual(result.category, "스팸_의심")
        self.assertEqual(result.text, "")

    def test_old_purchase_failure_routes_to_compensation_sale(self) -> None:
        result = transform_operator_note(
            question="켜지지 않고 충전도 안 됩니다. 구매 2024.03.10.",
            product_model="QP2000C",
        )
        self.assertIn("무상 AS 기간은 구매일로부터 1년", result.text)
        self.assertIn("보상판매", result.text)

    def test_power_off_question_gives_exact_button_sequence(self) -> None:
        result = transform_operator_note(
            question="보조배터리 전원을 아예 껐다가 켜는 법을 알고 싶어요",
            product_model="QP1000C",
        )
        self.assertIn("약 40초 뒤 자동", result.text)
        self.assertIn("빠르게 두 번", result.text)

    def test_known_model_power_failure_does_not_ask_for_model_again(self) -> None:
        result = transform_operator_note(
            question="액정 화면도 안 나오고 배터리와 폰 충전도 안 됩니다. AS 가능한가요?",
            product_model="QP2000C",
        )
        self.assertIn("C타입 입·출력 포트", result.text)
        self.assertIn("https://reqm.co.kr/cs/", result.text)
        self.assertNotIn("제품 모델", result.text)


if __name__ == "__main__":
    unittest.main()
