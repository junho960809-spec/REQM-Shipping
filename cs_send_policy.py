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
    if category.startswith("AS_") and "https://reqm.co.kr/cs/" not in text:
        return SendReadiness(False, "불량 답변에 AS 신청 주소가 필요합니다.")
    if category == "일반" and "톡톡" not in text:
        return SendReadiness(False, "판단이 어려운 문의는 네이버 톡톡 안내가 필요합니다.")
    return SendReadiness(True, "필수 안내가 포함되어 있습니다. 저장 후 작업자가 수동 전송할 수 있습니다.")
