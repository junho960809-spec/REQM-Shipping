from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re


DISCONTINUED_MODELS = {
    "QP1000A": "QP1000C",
    "QP2000A": "QP2000C",
    "QPD250": "QPD330",
    "QPD365": "QPD365-N",
}

KNOWN_MODELS = (*DISCONTINUED_MODELS, *DISCONTINUED_MODELS.values(), "Q1500", "ACONE", "QM4100", "QMP5")


@dataclass(frozen=True)
class DraftResult:
    text: str
    category: str
    risk_level: str
    requires_approval: bool
    policy_refs: tuple[str, ...]


def _combined_text(question: str, operator_note: str) -> str:
    return f"{question}\n{operator_note}".upper()


def _detected_model(text: str, product_model: str, product_name: str = "") -> str:
    candidates = [product_model.strip().upper(), *KNOWN_MODELS]
    product_source = f"{text}\n{product_name}".upper()
    return next((model for model in candidates if model and model in product_source), product_model.strip().upper())


def _product_label(product_name: str, model: str) -> str:
    if model:
        return model
    cleaned = re.sub(r"\s+", " ", product_name).strip()
    return cleaned[:45] if cleaned else "문의하신 제품"


def _looks_like_spam(source: str) -> bool:
    markers = ("오픈채팅", "카카오톡", "핫딜", "커뮤니티", "광고", "최대 주문", "회원 300만")
    return sum(marker in source for marker in markers) >= 2


def transform_operator_note(
    *,
    question: str,
    operator_note: str = "",
    product_model: str = "",
    product_name: str = "",
) -> DraftResult:
    """Analyze an inquiry and create a policy-bound customer response.

    An operator note is optional and is treated as additional context when supplied.
    """
    if not question.strip() and not operator_note.strip():
        raise ValueError("분석할 고객 문의가 없습니다.")

    source = _combined_text(question, operator_note)
    model = _detected_model(source, product_model, product_name)
    product = _product_label(product_name, model)
    is_discontinued = model in DISCONTINUED_MODELS

    if _looks_like_spam(source):
        return DraftResult(
            text="",
            category="스팸_의심",
            risk_level="blocked",
            requires_approval=True,
            policy_refs=("광고성 문의는 답변하지 않고 작업자 확인",),
        )

    if any(word in source for word in ("전원을 아예", "전원 끄", "전원 종료", "어떻게 꺼")) and model in ("QP1000C", "QP2000C"):
        return DraftResult(
            text=(
                f"안녕하세요 고객님. {model}은 케이블을 모두 분리하면 약 40초 뒤 자동으로 전원이 꺼집니다. "
                "바로 끄려면 전원이 켜진 상태에서 전원 버튼을 빠르게 두 번 눌러 주세요. "
                "그래도 숫자 표시가 계속 움직인다면 저전력 모드가 켜진 상태일 수 있으므로 전원 버튼을 약 5초간 길게 눌러 해제해 주세요."
            ),
            category="보조배터리_전원종료",
            risk_level="normal",
            requires_approval=True,
            policy_refs=("케이블 분리 후 약 40초 자동 종료", "전원 버튼 빠르게 2회", "저전력 모드 해제"),
        )

    if any(word in source for word in ("재입고", "단종", "품절", "언제 들어")) and not is_discontinued:
        color = next((value for value in ("화이트", "네온그린", "핑크", "블랙", "그린") if value in source), "해당 옵션")
        return DraftResult(
            text=(
                f"안녕하세요 고객님. 문의하신 {product} {color} 색상의 판매 여부와 재입고 일정은 "
                "현재 판매 옵션과 입고 일정을 확인한 후 안내가 필요한 내용입니다. 담당 부서 확인 후 정확히 안내드리겠습니다."
            ),
            category="재고_확인",
            risk_level="review",
            requires_approval=True,
            policy_refs=("재입고 일정은 물류팀·온라인팀 확인",),
        )

    if any(word in source for word in ("대량구매", "대량 구매", "대량", "제작")):
        return DraftResult(
            text=(
                f"안녕하세요 고객님. 문의하신 {product}의 소재 변경 및 대량 제작 가능 여부는 생산 부서 검토가 필요합니다. "
                "상호명, 담당자 성함과 연락처, 희망 수량, 적용하려는 소재의 사양을 남겨주시면 확인 후 안내드리겠습니다."
            ),
            category="기업_대량구매",
            risk_level="review",
            requires_approval=True,
            policy_refs=("대량구매 필수 정보 확인 후 온라인팀 전달",),
        )

    if any(word in source for word in ("중국", "상하이", "비행기", "기내", "3C", "CCC")):
        capacity = "74Wh" if model == "QP2000C" else "37Wh" if model == "QP1000C" else "제품에 표시된 Wh 용량"
        return DraftResult(
            text=(
                f"안녕하세요 고객님. {product}의 정격 전력량은 {capacity}이며 일반적인 기내 휴대 가능 범위에 해당합니다. "
                "다만 중국 국내선은 제품 본체의 CCC(3C) 표시 여부에 따라 반입이 제한될 수 있고, 국제선도 항공사와 경유지별 기준이 다를 수 있습니다. "
                "탑승하시는 항공사에 제품의 Wh 용량과 CCC 표시 요건을 출발 전에 확인해 주세요. 보조배터리는 위탁수하물이 아닌 기내 휴대로 소지해야 합니다."
            ),
            category="여행_기내반입",
            risk_level="review",
            requires_approval=True,
            policy_refs=("QP2000C 74Wh", "QP1000C 37Wh", "항공사·도착 지역 규정 확인"),
        )

    if any(word in source for word in ("노트북", "갤럭시북", "맥북")):
        output = "최대 30W" if model == "QPD330" else "해당 제품의 최대 출력"
        return DraftResult(
            text=(
                f"안녕하세요 고객님. {product}은 {output} 출력 제품입니다. 갤럭시북은 모델별 권장 충전 출력이 달라 "
                "권장 출력이 30W를 초과하는 모델에서는 충전 속도가 매우 느리거나 사용 중 충전량이 늘지 않을 수 있으며, 낮은 전력을 차단하는 모델은 충전되지 않을 수 있습니다. "
                "갤럭시북에 표시된 권장 충전 출력이 30W 이하인지 먼저 확인해 주세요."
            ),
            category="노트북_호환",
            risk_level="normal",
            requires_approval=True,
            policy_refs=("QPD330 최대 30W", "기기 권장 출력 확인"),
        )

    if any(word in source for word in ("계좌", "입금", "케이스", "케이블")) and any(word in source for word in ("구입", "구매", "금액")):
        return DraftResult(
            text=(
                f"안녕하세요 고객님. 문의하신 {product}과 케이스·케이블 구성은 스마트스토어의 각 상품 옵션에서 선택해 주문해 주세요. "
                "상품 문의 게시판에는 계좌번호나 배송지 같은 개인정보를 남기지 마시고, 원하는 색상이나 구성이 옵션에 보이지 않으면 네이버 톡톡으로 문의해 주세요."
            ),
            category="구성품_구매",
            risk_level="normal",
            requires_approval=True,
            policy_refs=("공개 게시판 개인정보 입력 방지", "구매 상세 문의는 톡톡 안내"),
        )

    if any(word in source for word in ("벗겨", "도색", "코팅", "색상")) and any(word in source for word in ("물티슈", "닦", "벗겨")):
        return DraftResult(
            text=(
                f"안녕하세요 고객님. {product}의 표면을 닦은 뒤 색상이 벗겨진 상태로 확인됩니다. "
                "추가로 문지르거나 세정제를 사용하지 마시고, 벗겨진 부위가 보이는 사진과 구매일자를 네이버 톡톡으로 보내주시면 제품 상태와 교환 가능 여부를 확인해 드리겠습니다."
            ),
            category="외관_손상",
            risk_level="review",
            requires_approval=True,
            policy_refs=("사진과 구매일 확인 후 교환 가능 여부 판단",),
        )

    if any(word in source for word in ("초고속", "고속충전", "고속 충전", "15W", "25W")):
        if model == "Q1500":
            detail = "Q1500은 휴대전화 무선 충전을 최대 15W까지 지원하며, 15W 이상 출력의 어댑터와 케이블을 연결해야 합니다."
        else:
            detail = "무선 충전의 최대 출력은 유선 초고속 충전 출력과 다르며, 휴대전화와 케이스의 무선 충전 규격에 따라 실제 속도가 결정됩니다."
        return DraftResult(
            text=f"안녕하세요 고객님. 문의하신 {product}에 대해 안내드립니다. {detail}",
            category="충전규격_호환",
            risk_level="review",
            requires_approval=True,
            policy_refs=("기기·케이스 규격과 어댑터 출력 확인",),
        )

    if any(word in source for word in ("워치", "WATCH")):
        return DraftResult(
            text=(
                f"안녕하세요 고객님. 문의하신 {product}의 갤럭시 워치 충전은 구매 옵션에 포함된 워치 충전 모듈의 종류와 "
                "갤럭시 워치9에 대한 실제 호환 테스트 결과를 기준으로 안내해야 합니다. 신제품은 규격만으로 정상 충전을 보장하기 어려워 담당 부서의 테스트 여부 확인 후 안내드리겠습니다."
            ),
            category="신제품_호환확인",
            risk_level="review",
            requires_approval=True,
            policy_refs=("신제품은 실제 호환 테스트 결과 확인",),
        )

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
                f"안녕하세요 고객님. {product}도 전자기기이므로 충전 또는 사용 중 일정한 열이 발생할 수 있습니다. "
                "사용 중 휴대전화에 온도 경고나 충전 중단 문구가 표시되었는지 확인 부탁드립니다. "
                "해당 문구가 확인되거나 충전이 반복해서 중단된다면 즉시 사용을 중단하고, 사용한 어댑터와 케이블 정보 및 증상 사진을 네이버 톡톡으로 보내주시면 확인해 드리겠습니다."
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
        purchase_years = [int(value) for value in re.findall(r"20\d{2}", source)]
        outside_warranty = bool(purchase_years and min(purchase_years) < datetime.now().year - 1)
        if outside_warranty:
            return DraftResult(
                text=(
                    f"안녕하세요 고객님. {product}이 켜지지 않고 충전도 되지 않는 증상으로 확인됩니다. 먼저 다른 어댑터와 케이블을 이용해 C타입 입·출력 포트에 연결하여 확인해 주세요. "
                    "동일한 경우 제품 검수가 필요합니다. 무상 AS 기간은 구매일로부터 1년이며, 문의에 남겨주신 구매일은 무상 기간이 지난 것으로 확인되어 신제품 보상판매로 안내해 드릴 수 있습니다. "
                    "리큐엠 AS는 수리가 아닌 새상품 교환 방식으로 진행됩니다."
                ),
                category="보증기간외_보상판매",
                risk_level="review",
                requires_approval=True,
                policy_refs=("무상 AS 1년", "기간 경과 시 30% 보상판매", "수리 대신 새상품 교환"),
            )
        if any(word in source for word in ("충전도 안", "충전이 안", "켜지지", "액정 화면도 안", "전원도 안")):
            return DraftResult(
                text=(
                    f"안녕하세요 고객님. {product}의 화면이 켜지지 않고 보조배터리 자체 충전과 휴대전화 충전이 모두 되지 않는 증상으로 확인됩니다. "
                    "먼저 사용 중인 어댑터와 케이블을 다른 제품으로 바꾼 뒤 C타입 입·출력 포트에 연결해 확인해 주세요. "
                    "동일한 경우 제품 검수가 필요하므로 아래 AS 신청서를 작성해 주세요. 리큐엠 AS는 수리가 아닌, 불량 증상 확인 후 새상품으로 교환하는 방식입니다. "
                    "https://reqm.co.kr/cs/"
                ),
                category="AS_전원충전불량",
                risk_level="review",
                requires_approval=True,
                policy_refs=("어댑터·케이블 교체 확인", "C타입 입·출력 포트 확인", "검수 후 새상품 교환"),
            )
        model_text = f" {model}" if model else ""
        return DraftResult(
            text=(
                f"안녕하세요 고객님. 리큐엠{model_text} 제품은 수리가 아닌 새상품 교환 방식으로 AS를 진행하고 있습니다. "
                "문의해 주신 증상은 제품 검수가 필요합니다. 아래 AS 신청서를 작성해 주시면 불량 증상 확인 후 새상품 교환 절차를 안내해 드리겠습니다. "
                "https://reqm.co.kr/cs/"
            ),
            category="AS_새상품교환",
            risk_level="review",
            requires_approval=True,
            policy_refs=("수리 미운영", "교환 조건 확인 후 새상품 교환"),
        )

    return DraftResult(
        text=(
            f"안녕하세요 고객님. 문의하신 {product} 관련 내용은 현재 확인된 상품 정보만으로 바로 확정하기 어려운 사항입니다. "
            "담당 부서에서 해당 제품의 사양과 운영 기준을 확인한 후 정확히 안내드리겠습니다."
        ),
        category="일반",
        risk_level="normal",
        requires_approval=True,
        policy_refs=("작업자 확인 필요",),
    )
