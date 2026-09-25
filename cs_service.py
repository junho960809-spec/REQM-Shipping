from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from product_knowledge import detect_model, discontinued_replacements, get_product_knowledge

DISCONTINUED_MODELS = discontinued_replacements()


@dataclass(frozen=True)
class DraftResult:
    text: str
    category: str
    risk_level: str
    requires_approval: bool
    policy_refs: tuple[str, ...]


@dataclass(frozen=True)
class OperatorMemoSections:
    customer_guidance: tuple[str, ...] = ()
    customer_requests: tuple[str, ...] = ()
    processing_results: tuple[str, ...] = ()
    internal_notes: tuple[str, ...] = ()


MEMO_SECTION_PREFIXES = {
    "고객 안내": "customer_guidance",
    "고객안내": "customer_guidance",
    "고객 요청": "customer_requests",
    "고객요청": "customer_requests",
    "처리 결과": "processing_results",
    "처리결과": "processing_results",
    "내부 메모": "internal_notes",
    "내부메모": "internal_notes",
    "내부 확인": "internal_notes",
    "내부확인": "internal_notes",
}


def parse_operator_note(operator_note: str) -> OperatorMemoSections:
    sections: dict[str, list[str]] = {
        "customer_guidance": [],
        "customer_requests": [],
        "processing_results": [],
        "internal_notes": [],
    }
    for raw_line in operator_note.splitlines():
        line = raw_line.strip().lstrip("-• ").strip()
        if not line:
            continue
        matched = False
        for prefix, target in MEMO_SECTION_PREFIXES.items():
            marker = prefix + ":"
            if line.startswith(marker):
                content = line[len(marker):].strip()
                if content:
                    sections[target].append(content)
                matched = True
                break
        if not matched:
            # Unlabelled notes remain internal classification context for safety.
            sections["internal_notes"].append(line)
    return OperatorMemoSections(**{key: tuple(value) for key, value in sections.items()})


def _apply_operator_memo(result: DraftResult, operator_note: str) -> DraftResult:
    memo = parse_operator_note(operator_note)
    if not result.text or not any((memo.customer_guidance, memo.customer_requests, memo.processing_results)):
        return result
    additions: list[str] = []
    additions.extend(_sentence(value) for value in memo.customer_guidance)
    additions.extend(f"처리 결과: {_sentence(value)}" for value in memo.processing_results)
    additions.extend(f"확인을 위해 {_sentence(value)}" for value in memo.customer_requests)
    additions = [value for value in additions if value]
    if not additions:
        return result
    reflected = []
    if memo.customer_guidance:
        reflected.append("고객 안내")
    if memo.processing_results:
        reflected.append("처리 결과")
    if memo.customer_requests:
        reflected.append("고객 요청")
    return DraftResult(
        text=f"{result.text.rstrip()} {' '.join(additions)}",
        category=result.category,
        risk_level=result.risk_level,
        requires_approval=result.requires_approval,
        policy_refs=(*result.policy_refs, f"작업자 메모 반영: {', '.join(reflected)}"),
    )


def _combined_text(question: str, operator_note: str) -> str:
    return f"{question}\n{operator_note}".upper()


def _detected_model(text: str, product_model: str, product_name: str = "") -> str:
    return detect_model(product_model, text, product_name) or product_model.strip().upper()


def _product_label(product_name: str, model: str) -> str:
    if model:
        return model
    cleaned = re.sub(r"\s+", " ", product_name).strip()
    return cleaned[:45] if cleaned else "문의하신 제품"


def _looks_like_spam(source: str) -> bool:
    markers = ("오픈채팅", "카카오톡", "핫딜", "커뮤니티", "광고", "최대 주문", "회원 300만")
    return sum(marker in source for marker in markers) >= 2


def _order_status(product_name: str) -> str:
    match = re.search(r"주문상태:\s*([^/\n]+)", product_name)
    return match.group(1).strip() if match else ""


def _sentence(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return ""
    return value if value.endswith((".", "!", "?")) else value + "."


def compose_customer_reply(
    *,
    direct_answer: str,
    verified_context: str = "",
    customer_action: str = "",
    service_policy: str = "",
    closing: str = "",
) -> str:
    """Build a customer reply in a stable, non-repetitive order."""
    sections = [
        "안녕하세요 고객님.",
        _sentence(direct_answer),
        _sentence(verified_context),
        _sentence(customer_action),
        _sentence(service_policy),
        _sentence(closing),
    ]
    return " ".join(section for section in sections if section)


def _verified_order_context(order_status: str) -> str:
    return f"현재 주문 상태는 {order_status}로 확인됩니다" if order_status else ""


def _exchange_inspection_policy() -> str:
    return (
        "https://reqm.co.kr/cs/ 에서 접수해 주세요. 구매일로부터 1년 이내인 제품은 입고 후 검수하며, "
        "불량 증상이 확인되면 무상으로 새상품 교환 출고(새제품 출고)를 진행합니다. 검수 결과 불량 증상이 확인되지 않으면 "
        "제품은 고객님께 반송되며 배송비가 발생합니다. 구매일로부터 1년이 지난 제품은 불량이 확인되더라도 "
        "무상 교환 대상이 아니며, 동일 제품을 30% 할인된 금액으로 재구매하는 보상판매 제도로 안내드립니다"
    )


def _purchase_is_outside_warranty(source: str, now: datetime | None = None) -> bool:
    today = (now or datetime.now()).date()
    full_date = re.search(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})", source)
    if full_date:
        try:
            purchased = datetime(
                int(full_date.group(1)), int(full_date.group(2)), int(full_date.group(3))
            ).date()
        except ValueError:
            return False
        return (today - purchased).days > 365
    purchase_years = [
        int(value)
        for value in re.findall(r"(?:구매|구입|구매일)[^\n]{0,15}?(20\d{2})", source)
    ]
    return bool(purchase_years and min(purchase_years) < today.year - 1)


def _transform_policy_answer(
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
    order_status = _order_status(product_name)
    knowledge = get_product_knowledge(model)

    if _looks_like_spam(source):
        return DraftResult(
            text="",
            category="스팸_의심",
            risk_level="blocked",
            requires_approval=True,
            policy_refs=("광고성 문의는 답변하지 않고 작업자 확인",),
        )

    # Safety reports always take precedence over compatibility, travel, and order questions.
    if any(word in source for word in ("팽창", "부풀", "스웰링", "연기", "타는 냄새", "스파크")):
        next_step = (
            f"문의하신 {model}는 단종 제품이므로 제품 정보를 확인한 뒤 "
            f"신형 {DISCONTINUED_MODELS[model]} 보상판매 절차로 접수해 주세요: https://reqm.co.kr/cs/"
            if is_discontinued
            else "제품 상태 사진을 첨부해 CS 신청서를 작성해 주세요. " + _exchange_inspection_policy()
        )
        return DraftResult(
            text=compose_customer_reply(
                direct_answer="제품이 부푼 경우 안전을 위해 사용과 충전을 즉시 중단해 주세요",
                verified_context=_verified_order_context(order_status),
                customer_action="제품을 누르거나 분해하지 마시고 화기나 고온의 장소에서 멀리 보관해 주세요",
                service_policy=next_step,
            ),
            category="안전_팽창",
            risk_level="urgent",
            requires_approval=True,
            policy_refs=("즉시 사용 중단", "수리 대신 새상품 교환", "단종 모델은 보상판매"),
        )

    if any(word in source for word in ("발열", "뜨거", "열이", "온도")):
        return DraftResult(
            text=compose_customer_reply(
                direct_answer=f"{product}도 전자기기이므로 충전 또는 사용 중 일정한 열이 발생하는 것은 자연스러운 현상입니다",
                verified_context=_verified_order_context(order_status),
                customer_action="사용 중 휴대전화에 온도 경고나 충전 중단 문구가 표시되는지 확인해 주세요",
                service_policy=(
                    "해당 문구 없이 느껴지는 발열만으로는 제품 불량으로 판단하기 어려워 교환이 어렵습니다. "
                    "문구가 표시되거나 충전이 반복해서 중단되면 즉시 사용을 중단하고 어댑터·케이블 정보와 증상 사진을 첨부해 AS를 신청해 주세요: https://reqm.co.kr/cs/"
                ),
            ),
            category="발열",
            risk_level="review",
            requires_approval=True,
            policy_refs=("전자기기 열 발생 가능", "온도 경고·충전 중단 확인"),
        )

    if any(word in source for word in (
        "언제 출고", "언제 배송", "언제 도착", "배송 언제", "출고 언제", "송장", "배송조회",
        "도착보장", "아직 도착", "배송 지연", "배송이 늦", "도착 안", "도착안",
    )):
        is_delayed = any(word in source for word in ("도착보장", "아직 도착", "배송 지연", "배송이 늦", "도착 안", "도착안"))
        if is_delayed and order_status != "배송 완료":
            detail = "도착 예정일이 지났는데 아직 받지 못하신 내용으로 확인됩니다. 현재 배송조회에 표시된 택배 이동 내역을 확인한 뒤 지연 또는 분실 여부를 확인해 안내드리겠습니다."
        elif order_status == "배송 완료":
            detail = "현재 주문은 배송 완료 상태입니다. 네이버 주문 상세의 배송조회에서 수령 장소를 먼저 확인해 주세요. 수령하지 못하셨다면 배송조회에 표시된 택배사로 확인 부탁드립니다."
        elif order_status == "배송 중":
            detail = "현재 주문은 배송 중입니다. 네이버 주문 상세의 배송조회에서 택배사 이동 내역과 예상 도착 정보를 확인하실 수 있습니다."
        elif order_status == "결제 완료":
            detail = "현재 주문은 결제 완료 상태로 출고 준비 중입니다. 송장이 등록되면 네이버 주문 상세에서 배송조회가 가능합니다."
        elif order_status == "구매 확정":
            detail = "현재 주문은 배송 후 구매 확정된 상태입니다. 상품을 받지 못하셨다면 주문 상세의 배송 이력과 수령 장소를 확인해 주세요."
        else:
            detail = "주문 상세에 송장이 등록되면 네이버에서 배송조회가 가능합니다. 정확한 출고 여부는 주문 상태를 확인한 후 안내드리겠습니다."
        return DraftResult(
            text=compose_customer_reply(
                direct_answer=detail,
                verified_context=_verified_order_context(order_status),
            ),
            category="주문_배송조회",
            risk_level="normal",
            requires_approval=True,
            policy_refs=(f"주문상태:{order_status or '미확인'}", "실제 주문 상태 기준 배송 안내"),
        )

    if any(word in source for word in ("주소 변경", "배송지 변경", "주소를 바", "배송지를 바")):
        if order_status in ("배송 중", "배송 완료", "구매 확정"):
            detail = "이미 출고가 진행되어 판매자가 배송지를 변경하기 어렵습니다. 배송조회에 표시된 택배사로 배송 가능 여부를 확인해 주세요."
        else:
            detail = "출고 전이라면 변경 가능 여부를 확인할 수 있습니다. 변경할 배송지는 공개 문의에 남기지 말고 네이버 톡톡으로 보내 주세요."
        return DraftResult(
            text=compose_customer_reply(
                direct_answer=detail,
                verified_context=_verified_order_context(order_status),
            ),
            category="주문_배송지변경",
            risk_level="review",
            requires_approval=True,
            policy_refs=(f"주문상태:{order_status or '미확인'}", "개인정보는 공개 문의에 작성 금지"),
        )

    if any(word in source for word in ("주문 취소", "취소해", "취소 가능", "취소될", "취소하고", "취소 요청")):
        if order_status == "취소 완료":
            detail = "현재 주문은 취소 완료 상태입니다. 환불 진행 내용은 네이버 주문 상세에서 확인해 주세요."
        elif order_status in ("배송 중", "배송 완료", "구매 확정"):
            detail = "이미 출고가 진행되어 주문 취소로 처리하기 어렵습니다. 네이버 주문 상세에서 반품 요청을 접수해 주세요."
        else:
            detail = "네이버 주문 상세에서 취소 요청을 접수해 주세요. 출고 처리 시점에 따라 취소 또는 반품 절차로 진행될 수 있습니다."
        return DraftResult(
            text=compose_customer_reply(
                direct_answer=detail,
                verified_context=_verified_order_context(order_status),
            ),
            category="주문_취소",
            risk_level="review",
            requires_approval=True,
            policy_refs=(f"주문상태:{order_status or '미확인'}", "주문 상태에 따른 취소·반품 구분"),
        )

    if any(word in source for word in ("반품", "환불")) and any(
        word in source for word in ("금액", "예상액", "배송비", "무료", "차감", "왜")
    ):
        return DraftResult(
            text=compose_customer_reply(
                direct_answer="반품 예정 금액은 상품 결제금액에서 주문 할인, 쿠폰 반환 조건과 반품 배송비 등이 반영되어 네이버에서 계산됩니다",
                verified_context=_verified_order_context(order_status),
                customer_action="네이버 주문 상세의 반품비용 내역을 확인해 주세요",
                service_policy="표시된 차감 사유와 실제 주문 조건이 다르면 해당 주문의 결제·반품 내역을 확인한 후 안내드리겠습니다",
            ),
            category="주문_반품환불금액",
            risk_level="review",
            requires_approval=True,
            policy_refs=("네이버 반품비용 산정 내역 확인", "할인·쿠폰·배송비 확인 후 안내"),
        )

    if any(word in source for word in ("단순 변심", "반품하고", "반품 요청", "교환하고", "교환 요청")):
        return DraftResult(
            text=compose_customer_reply(
                direct_answer="네이버 주문 상세에서 교환 또는 반품 요청을 접수해 주세요",
                verified_context=_verified_order_context(order_status),
                service_policy="상품 사용 여부와 회수 상태를 확인한 후 네이버에 표시된 절차에 따라 처리됩니다",
            ),
            category="주문_교환반품",
            risk_level="review",
            requires_approval=True,
            policy_refs=(f"주문상태:{order_status or '미확인'}", "네이버 주문 상세에서 교환·반품 접수"),
        )

    if any(word in source for word in ("누락", "빠져", "다른 상품", "오배송", "잘못 왔", "파손")):
        return DraftResult(
            text=compose_customer_reply(
                direct_answer="구성품 누락·오배송·파손은 확인 후 새상품 교환 또는 누락 구성품 발송으로 처리해 드립니다",
                verified_context=f"대상 제품은 {product}입니다" if product else "",
                customer_action="받으신 상품 전체와 택배 상자, 송장, 문제가 확인되는 부분을 함께 촬영해 네이버 톡톡으로 보내 주세요",
            ),
            category="배송_오배송파손누락",
            risk_level="review",
            requires_approval=True,
            policy_refs=("택배 상자·송장·상품 사진 확인", "확인 후 새상품 교환 또는 누락품 발송"),
        )

    if any(word in source for word in (
        "전원을 아예", "전원 끄", "전원 종료", "어떻게 꺼", "끄는 방법", "끄나요",
    )) and knowledge and knowledge.supports_power_off_sequence:
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
            text=compose_customer_reply(
                direct_answer=f"{product} {color} 색상의 재입고 일정은 현재 확정된 정보만으로 안내하기 어렵습니다",
                customer_action="최신 입고 일정 확인이 필요하므로 네이버 톡톡으로 문의해 주세요",
            ),
            category="재고_확인",
            risk_level="review",
            requires_approval=True,
            policy_refs=("재입고 일정은 물류팀·온라인팀 확인",),
        )

    if any(word in source for word in ("대량구매", "대량 구매", "대량", "제작")):
        return DraftResult(
            text=compose_customer_reply(
                direct_answer=f"{product}의 소재 변경과 대량 제작은 생산 부서 검토가 필요합니다",
                customer_action="상호명, 담당자 성함과 연락처, 희망 수량, 소재 사양을 네이버 톡톡으로 보내 주세요",
                service_policy="전달한 조건을 기준으로 제작 가능 여부와 진행 과정을 안내합니다",
            ),
            category="기업_대량구매",
            risk_level="review",
            requires_approval=True,
            policy_refs=("대량구매 필수 정보 확인 후 온라인팀 전달",),
        )

    if any(word in source for word in ("중국", "상하이", "비행기", "기내", "3C", "CCC")):
        capacity = f"{knowledge.capacity_wh}Wh" if knowledge and knowledge.capacity_wh else "제품에 표시된 Wh 용량"
        return DraftResult(
            text=(
                f"안녕하세요 고객님. {product}의 정격 전력량은 {capacity}이며 일반적인 기내 휴대 가능 범위에 해당합니다. "
                "다만 중국 국내선은 제품 본체의 CCC(3C) 표시 여부에 따라 반입이 제한될 수 있고, 국제선도 항공사와 경유지별 기준이 다를 수 있습니다. "
                "탑승하시는 항공사에 제품의 Wh 용량과 CCC 표시 요건을 출발 전에 확인해 주세요. 보조배터리는 위탁수하물이 아닌 기내 휴대로 소지해야 합니다."
            ),
            category="여행_기내반입",
            risk_level="review",
            requires_approval=True,
            policy_refs=((f"{model} {capacity}" if model and knowledge and knowledge.capacity_wh else "제품 표시 Wh 확인"), "항공사·도착 지역 규정 확인"),
        )

    if any(word in source for word in ("노트북", "갤럭시북", "맥북")):
        output = f"최대 {knowledge.max_output_w}W" if knowledge and knowledge.max_output_w else "해당 제품의 최대 출력"
        return DraftResult(
            text=(
                f"안녕하세요 고객님. {product}은 {output} 출력 제품입니다. 갤럭시북은 모델별 권장 충전 출력이 달라 "
                "권장 출력이 30W를 초과하는 모델에서는 충전 속도가 매우 느리거나 사용 중 충전량이 늘지 않을 수 있으며, 낮은 전력을 차단하는 모델은 충전되지 않을 수 있습니다. "
                "갤럭시북에 표시된 권장 충전 출력이 30W 이하인지 먼저 확인해 주세요."
            ),
            category="노트북_호환",
            risk_level="normal",
            requires_approval=True,
            policy_refs=((f"{model} 최대 {knowledge.max_output_w}W" if model and knowledge and knowledge.max_output_w else "제품 최대 출력 확인"), "기기 권장 출력 확인"),
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
            text=compose_customer_reply(
                direct_answer=f"{product}의 표면 손상은 사진 확인 후 교환 가능 여부를 판단합니다",
                customer_action="추가로 문지르거나 세정제를 사용하지 말고 벗겨진 부위 사진과 구매일자를 네이버 톡톡으로 보내 주세요",
                service_policy=_exchange_inspection_policy(),
            ),
            category="외관_손상",
            risk_level="review",
            requires_approval=True,
            policy_refs=("사진과 구매일 확인 후 교환 가능 여부 판단",),
        )

    if any(word in source for word in ("초고속", "고속충전", "고속 충전", "15W", "25W")):
        if model == "Q1500" and knowledge and knowledge.max_output_w:
            detail = f"Q1500은 휴대전화 무선 충전을 최대 {knowledge.max_output_w}W까지 지원하며, 15W 이상 출력의 어댑터와 케이블을 연결해야 합니다."
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
            text=compose_customer_reply(
                direct_answer=f"{product}의 워치 충전은 구매 옵션의 충전 모듈과 실제 호환 테스트 결과가 있어야 확정할 수 있습니다",
                customer_action="사용할 워치의 정확한 모델명과 구매하려는 상품 옵션을 네이버 톡톡으로 보내 주세요",
                service_policy="확인되지 않은 신제품은 규격만으로 정상 충전을 보장하지 않습니다",
            ),
            category="신제품_호환확인",
            risk_level="review",
            requires_approval=True,
            policy_refs=("신제품은 실제 호환 테스트 결과 확인",),
        )

    if is_discontinued:
        replacement = DISCONTINUED_MODELS[model]
        return DraftResult(
            text=compose_customer_reply(
                direct_answer=f"{model}는 판매가 종료되어 수리나 동일 모델 교환 대신 신형 {replacement} 보상판매로 안내드립니다",
                verified_context=_verified_order_context(order_status),
                customer_action="구매 정보와 제품 상태를 보내주시면 적용 가능한 보상판매 절차를 확인해 드리겠습니다",
            ),
            category="단종_보상판매",
            risk_level="review",
            requires_approval=True,
            policy_refs=(f"{model} → {replacement}", "단종 모델 보상판매"),
        )

    if any(word in source for word in (
        "수리", "고장", "AS", "불량", "충전이 안", "충전 안", "작동 안",
        "인식 안", "켜지지", "전원이 안", "접촉 불량",
    )):
        outside_warranty = _purchase_is_outside_warranty(source)
        if outside_warranty:
            return DraftResult(
                text=compose_customer_reply(
                    direct_answer="문의에 남겨주신 구매일은 1년의 무상 교환 기간이 지나 보상판매 대상으로 안내드립니다",
                    verified_context=f"{product}이 켜지지 않고 충전되지 않는 증상으로 확인됩니다",
                    customer_action="먼저 다른 어댑터와 케이블로 C타입 입·출력 포트에 연결해 확인해 주세요",
                    service_policy=(
                        "동일한 증상이 계속되면 https://reqm.co.kr/cs/ 에서 접수해 주세요. 구매일로부터 1년이 지난 제품은 "
                        "불량이 확인되더라도 무상 새제품 교환 대상이 아니며, 불량 제품과 동일한 제품을 30% 할인된 금액으로 "
                        "재구매하는 보상판매 제도로 진행됩니다"
                    ),
                ),
                category="보증기간외_보상판매",
                risk_level="review",
                requires_approval=True,
                policy_refs=("무상 교환 1년", "기간 경과 시 동일 제품 30% 보상판매"),
            )
        if any(word in source for word in ("충전도 안", "충전이 안", "켜지지", "액정 화면도 안", "전원도 안")):
            return DraftResult(
                text=compose_customer_reply(
                    direct_answer="동일 증상이 계속되면 구매일과 제품 검수 결과에 따라 새상품 교환(새제품 출고) 또는 보상판매로 진행합니다",
                    verified_context=f"{product}의 화면·제품 충전·휴대전화 충전이 정상 작동하지 않는 증상으로 확인됩니다",
                    customer_action="먼저 어댑터와 케이블을 다른 제품으로 바꾼 뒤 C타입 입·출력 포트에 연결해 확인해 주세요",
                    service_policy="동일한 경우 " + _exchange_inspection_policy(),
                ),
                category="AS_전원충전불량",
                risk_level="review",
                requires_approval=True,
                policy_refs=("어댑터·케이블 교체 확인", "C타입 입·출력 포트 확인", "검수 후 새상품 교환"),
            )
        model_text = f" {model}" if model else ""
        return DraftResult(
            text=compose_customer_reply(
                direct_answer=f"리큐엠{model_text} 제품은 수리가 아닌 새상품 교환(새제품 출고) 또는 보상판매 방식으로 진행합니다",
                verified_context="문의하신 증상은 제품 검수가 필요합니다",
                customer_action="CS 사이트에서 증상과 구매 정보를 입력해 접수해 주세요",
                service_policy=_exchange_inspection_policy(),
            ),
            category="AS_새상품교환",
            risk_level="review",
            requires_approval=True,
            policy_refs=("수리 미운영", "구매일 기준 1년", "불량 확인 시 무상 새제품 출고", "불량 미확인 시 반송 배송비 발생", "1년 초과 시 동일 제품 30% 보상판매"),
        )

    return DraftResult(
        text=compose_customer_reply(
            direct_answer=f"{product} 관련 문의는 현재 확인된 내용만으로 정확한 답변을 확정하기 어렵습니다",
            customer_action="제품 사진, 사용 환경 또는 확인이 필요한 세부 내용을 네이버 톡톡으로 보내 주세요",
            service_policy="톡톡에서 상품 정보와 문의 내용을 함께 확인해 한 번에 필요한 처리 방법을 안내합니다",
        ),
        category="일반",
        risk_level="normal",
        requires_approval=True,
        policy_refs=("작업자 확인 필요",),
    )


def transform_operator_note(
    *,
    question: str,
    operator_note: str = "",
    product_model: str = "",
    product_name: str = "",
) -> DraftResult:
    result = _transform_policy_answer(
        question=question,
        operator_note=operator_note,
        product_model=product_model,
        product_name=product_name,
    )
    return _apply_operator_memo(result, operator_note)
