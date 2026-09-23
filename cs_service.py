from __future__ import annotations

from dataclasses import dataclass


DISCONTINUED_MODELS = {
    "QP1000A": "QP1000C",
    "QP2000A": "QP2000C",
    "QPD250": "QPD330",
    "QPD365": "QPD365-N",
}


@dataclass(frozen=True)
class DraftResult:
    text: str
    category: str
    risk_level: str
    requires_approval: bool
    policy_refs: tuple[str, ...]


def _combined_text(question: str, operator_note: str) -> str:
    return f"{question}\n{operator_note}".upper()


def _detected_model(text: str, product_model: str) -> str:
    candidates = [product_model.strip().upper(), *DISCONTINUED_MODELS]
    return next((model for model in candidates if model and model in text), product_model.strip().upper())


def transform_operator_note(
    *,
    question: str,
    operator_note: str = "",
    product_model: str = "",
) -> DraftResult:
    """Analyze an inquiry and create a policy-bound customer response.

    An operator note is optional and is treated as additional context when supplied.
    """
    if not question.strip() and not operator_note.strip():
        raise ValueError("분석할 고객 문의가 없습니다.")

    source = _combined_text(question, operator_note)
    model = _detected_model(source, product_model)
    is_discontinued = model in DISCONTINUED_MODELS

    if any(word in source for word in ("팽창", "부풀", "스웰링", "연기", "타는 냄새", "스파크")):
        next_step = (
            f"문의하신 {model}는 단종 제품이므로 제품 정보를 확인한 뒤 "
            f"신형 {DISCONTINUED_MODELS[model]} 보상판매 절차를 안내드리겠습니다."
            if is_discontinued
            else "주문번호와 제품 상태를 확인할 수 있는 사진을 보내주시면 확인 후 새상품 교환 절차를 안내해 드리겠습니다."
        )
        return DraftResult(
            text=(
                "안녕하세요 고객님. 제품이 부풀거나 이상 증상이 있는 경우 안전을 위해 사용과 충전을 즉시 중단해 주세요. "
                "제품을 누르거나 분해하지 마시고 화기나 고온의 장소에서 멀리 보관해 주세요. "
                + next_step
            ),
            category="안전_팽창",
            risk_level="urgent",
            requires_approval=True,
            policy_refs=("즉시 사용 중단", "수리 대신 새상품 교환", "단종 모델은 보상판매"),
        )

    if any(word in source for word in ("발열", "뜨거", "열이", "온도")):
        return DraftResult(
            text=(
                "안녕하세요 고객님. 보조배터리도 전자기기이므로 충전 또는 사용 중 일정한 열이 발생할 수 있습니다. "
                "사용 중 휴대전화에 온도 경고나 충전 중단 문구가 표시되었는지 확인 부탁드립니다. "
                "해당 문구가 확인되거나 충전이 반복해서 중단된다면 제품 모델과 주문정보를 보내주시면 상태 확인 후 안내해 드리겠습니다."
            ),
            category="발열",
            risk_level="review",
            requires_approval=True,
            policy_refs=("전자기기 열 발생 가능", "온도 경고·충전 중단 확인"),
        )

    if is_discontinued:
        replacement = DISCONTINUED_MODELS[model]
        return DraftResult(
            text=(
                f"안녕하세요 고객님. 문의하신 {model}는 판매가 종료된 단종 제품입니다. "
                f"현재는 수리나 동일 모델 교환 대신 신형 {replacement} 보상판매로 안내드리고 있습니다. "
                "구매 정보와 제품 상태를 확인한 후 적용 가능한 절차를 안내해 드리겠습니다."
            ),
            category="단종_보상판매",
            risk_level="review",
            requires_approval=True,
            policy_refs=(f"{model} → {replacement}", "단종 모델 보상판매"),
        )

    if any(word in source for word in (
        "수리", "고장", "AS", "교환", "불량", "충전이 안", "충전 안", "작동 안",
        "인식 안", "켜지지", "전원이 안", "접촉 불량",
    )):
        model_text = f" {model}" if model else ""
        return DraftResult(
            text=(
                f"안녕하세요 고객님. 리큐엠{model_text} 제품은 수리가 아닌 새상품 교환 방식으로 AS를 진행하고 있습니다. "
                "제품 모델과 구매 정보, 발생한 증상을 확인한 뒤 교환 가능 여부와 접수 절차를 안내해 드리겠습니다."
            ),
            category="AS_새상품교환",
            risk_level="review",
            requires_approval=True,
            policy_refs=("수리 미운영", "교환 조건 확인 후 새상품 교환"),
        )

    return DraftResult(
        text=(
            "안녕하세요 고객님. 문의해 주신 내용을 확인했습니다. "
            "정확한 확인을 위해 사용 중인 제품 모델과 구매 정보를 남겨주시면 문의 내용에 맞춰 안내해 드리겠습니다."
        ),
        category="일반",
        risk_level="normal",
        requires_approval=True,
        policy_refs=("작업자 확인 필요",),
    )
