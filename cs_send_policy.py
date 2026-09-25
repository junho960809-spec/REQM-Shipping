from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SendReadiness:
    allowed: bool
    message: str


def evaluate_send_readiness(*, answer: str, category: str, risk_level: str) -> SendReadiness:
    text = answer.strip()
    if not text:
        return SendReadiness(False, "답변 내용이 비어 있습니다.")
    if risk_level == "blocked" or category == "스팸_의심":
        return SendReadiness(False, "스팸 또는 답변 보류 문의는 전송할 수 없습니다.")
    if category == "안전_팽창":
        if "사용과 충전을 즉시 중단" not in text:
            return SendReadiness(False, "팽창 답변에 즉시 사용·충전 중단 안내가 필요합니다.")
        if "https://reqm.co.kr/cs/" not in text:
            return SendReadiness(False, "팽창 답변에 AS 신청 주소가 필요합니다.")
    if category.startswith("AS_"):
        if "https://reqm.co.kr/cs/" not in text:
            return SendReadiness(False, "불량 답변에 CS 신청 주소가 필요합니다.")
        required_exchange_terms = ("구매일로부터 1년", "불량 증상", "새제품", "반송", "배송비", "30%", "보상판매")
        if any(term not in text for term in required_exchange_terms):
            return SendReadiness(False, "교환 답변에 1년 무상 교환·검수·미확인 반송 배송비·기간 경과 30% 보상판매 안내가 필요합니다.")
    if category == "보증기간외_보상판매":
        if "https://reqm.co.kr/cs/" not in text or "30%" not in text or "동일한 제품" not in text:
            return SendReadiness(False, "보증기간 경과 답변에 CS 신청 주소와 동일 제품 30% 보상판매 안내가 필요합니다.")
    if category == "일반" and "톡톡" not in text:
        return SendReadiness(False, "판단이 어려운 문의는 네이버 톡톡 안내가 필요합니다.")
    return SendReadiness(True, "필수 안내가 포함되어 있습니다. 저장 후 작업자가 수동 전송할 수 있습니다.")
