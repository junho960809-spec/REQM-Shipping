from __future__ import annotations

import unittest

from cs_service import compose_customer_reply, transform_operator_note


class CsDraftTransformerTests(unittest.TestCase):
    def test_reply_composer_keeps_direct_answer_before_context_and_action(self) -> None:
        reply = compose_customer_reply(
            direct_answer="바로 교환 절차를 안내해 드립니다",
            verified_context="현재 주문은 배송 완료 상태입니다",
            customer_action="제품 사진을 보내 주세요",
            service_policy="수리가 아닌 새상품 교환으로 진행합니다",
        )
        self.assertLess(reply.index("바로 교환"), reply.index("배송 완료"))
        self.assertLess(reply.index("배송 완료"), reply.index("제품 사진"))
        self.assertLess(reply.index("제품 사진"), reply.index("새상품 교환"))

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

    def test_old_qpd365_routes_to_exact_renewed_model_name(self) -> None:
        result = transform_operator_note(question="QPD365 수리 가능한가요?", product_model="QPD365")
        self.assertIn("신형 QPD365N 보상판매", result.text)

    def test_sales_sku_alias_uses_canonical_qp1000c_policy(self) -> None:
        result = transform_operator_note(
            question="전원을 바로 끄는 방법이 있나요?",
            product_name="[리큐엠] 보조배터리 QP1000C1 네온그린",
        )
        self.assertEqual(result.category, "보조배터리_전원종료")
        self.assertIn("QP1000C", result.text)

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
        self.assertIn("발열만으로는", result.text)
        self.assertIn("교환이 어렵", result.text)

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
        self.assertIn("네이버 톡톡", result.text)
        self.assertIn("처리 방법", result.text)
        self.assertNotIn("제품 모델과 구매 정보", result.text)

    def test_defect_answer_finishes_with_as_application_route(self) -> None:
        result = transform_operator_note(question="충전이 안 되고 전원도 켜지지 않아요", product_model="QP2000C")
        self.assertIn("https://reqm.co.kr/cs/", result.text)
        self.assertIn("새상품", result.text)

    def test_swelling_answer_finishes_with_as_application_route(self) -> None:
        result = transform_operator_note(question="배터리가 부풀었습니다", product_model="QP1000C")
        self.assertIn("https://reqm.co.kr/cs/", result.text)
        self.assertIn("새상품 교환", result.text)

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

    def test_shipping_answer_uses_actual_delivered_status(self) -> None:
        result = transform_operator_note(
            question="언제 배송되나요?",
            product_model="QP1000C",
            product_name="리큐엠 QP1000C / 옵션: 화이트 / 주문상태: 배송 완료 / 수량: 1",
        )
        self.assertEqual(result.category, "주문_배송조회")
        self.assertIn("배송 완료 상태", result.text)
        self.assertNotIn("주문번호", result.text)

    def test_address_change_after_shipping_explains_carrier_route(self) -> None:
        result = transform_operator_note(
            question="배송지 변경해 주세요",
            product_model="QPD330",
            product_name="리큐엠 QPD330 / 주문상태: 배송 중 / 수량: 1",
        )
        self.assertEqual(result.category, "주문_배송지변경")
        self.assertIn("택배사", result.text)
        self.assertIn("배송지를 변경하기 어렵", result.text)

    def test_cancel_after_delivery_routes_to_return(self) -> None:
        result = transform_operator_note(
            question="주문 취소 가능한가요?",
            product_model="QP2000C",
            product_name="리큐엠 QP2000C / 주문상태: 배송 완료 / 수량: 1",
        )
        self.assertEqual(result.category, "주문_취소")
        self.assertIn("반품 요청", result.text)

    def test_swelling_has_priority_over_travel_question(self) -> None:
        result = transform_operator_note(
            question="비행기에 가져가려는데 배터리가 부풀었어요",
            product_model="QP1000C",
        )
        self.assertEqual(result.category, "안전_팽창")
        self.assertIn("즉시 중단", result.text)

    def test_wrong_item_routes_to_photo_based_exchange_review(self) -> None:
        result = transform_operator_note(
            question="주문한 것과 다른 상품이 왔어요",
            product_model="QPD330",
        )
        self.assertEqual(result.category, "배송_오배송파손누락")
        self.assertIn("택배 상자", result.text)
        self.assertIn("새상품 교환", result.text)

    def test_natural_cancel_wording_is_classified_as_order_cancel(self) -> None:
        result = transform_operator_note(
            question="혹시 아직 출발 안 했으면 취소될까요?",
            product_name="리큐엠 보조배터리 / 주문상태: 결제 완료 / 수량: 1",
        )
        self.assertEqual(result.category, "주문_취소")
        self.assertIn("취소 요청", result.text)

    def test_arrival_guarantee_delay_is_classified_as_delivery(self) -> None:
        result = transform_operator_note(
            question="내일도착보장 제품이 아직 도착 안 했습니다",
            product_name="리큐엠 충전기 / 주문상태: 배송 중 / 수량: 1",
        )
        self.assertEqual(result.category, "주문_배송조회")
        self.assertIn("도착 예정일이 지났", result.text)

    def test_return_amount_question_is_not_misclassified_as_product_as(self) -> None:
        result = transform_operator_note(
            question="무료교환반품인데 반품 예정 금액은 왜 다르죠?",
            product_model="QP1000C",
            product_name="리큐엠 QP1000C / 주문상태: 배송 완료 / 수량: 1",
        )
        self.assertEqual(result.category, "주문_반품환불금액")
        self.assertIn("할인", result.text)
        self.assertNotIn("AS 신청서", result.text)


if __name__ == "__main__":
    unittest.main()
