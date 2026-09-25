from __future__ import annotations

import unittest

from cs_send_policy import evaluate_send_readiness


class CsSendPolicyTests(unittest.TestCase):
    def test_as_answer_requires_application_url(self) -> None:
        result = evaluate_send_readiness(answer="새상품 교환으로 진행합니다.", category="AS_새상품교환", risk_level="review")
        self.assertFalse(result.allowed)
        self.assertIn("CS 신청 주소", result.message)

    def test_ambiguous_answer_requires_talktalk_route(self) -> None:
        result = evaluate_send_readiness(answer="추가 확인이 필요합니다.", category="일반", risk_level="normal")
        self.assertFalse(result.allowed)
        self.assertIn("톡톡", result.message)

    def test_complete_defect_answer_is_ready_for_manual_send(self) -> None:
        result = evaluate_send_readiness(
            answer=(
                "구매일로부터 1년 이내 제품은 검수 후 불량 증상이 확인되면 새상품을 출고합니다. "
                "미확인 시 반송되며 배송비가 발생합니다. https://reqm.co.kr/cs/"
            ),
            category="AS_새상품교환",
            risk_level="review",
        )
        self.assertTrue(result.allowed)

    def test_as_answer_requires_complete_exchange_inspection_policy(self) -> None:
        result = evaluate_send_readiness(
            answer="불량 확인 후 새상품 교환합니다. https://reqm.co.kr/cs/",
            category="AS_새상품교환",
            risk_level="review",
        )
        self.assertFalse(result.allowed)
        self.assertIn("반송 배송비", result.message)

    def test_spam_is_never_ready_to_send(self) -> None:
        result = evaluate_send_readiness(answer="답변", category="스팸_의심", risk_level="blocked")
        self.assertFalse(result.allowed)


if __name__ == "__main__":
    unittest.main()
