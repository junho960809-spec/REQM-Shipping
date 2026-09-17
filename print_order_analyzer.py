from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess
import sys

import pdfplumber
from openpyxl import load_workbook


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
FIELD_ALIASES = {
    "item_code": ("품목코드", "상품코드", "제품코드", "모델코드"),
    "recipient": ("수령인", "받는사람", "받는 사람", "수취인"),
    "contact": ("연락처", "휴대폰", "핸드폰", "전화번호", "TEL", "전화"),
    "address": ("배송지", "배송주소", "받는곳", "받는 곳", "주소"),
    "request_date": ("납기", "납기일", "출고일", "출고요청일", "발송일"),
    "product": ("품명", "상품명", "제품명", "데이터명"),
    "quantity": ("수량", "주문수량", "발주수량", "총수량"),
    "printing": ("인쇄내용", "인쇄 요청", "인쇄요청", "사용"),
    "packaging": ("포장", "포장선택", "선물포장"),
    "delivery": ("배송", "배송방법", "발송방법"),
}


@dataclass
class AnalysisResult:
    source_type: str
    vendor: str
    fields: dict[str, str]
    confidence: dict[str, int]
    raw_text: str
    issues: list[str] = field(default_factory=list)


def _ocr_script_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / "windows_ocr.ps1"


def extract_text(path: str | Path) -> tuple[str, str]:
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix in IMAGE_EXTENSIONS:
        script = _ocr_script_path()
        if not script.exists():
            raise FileNotFoundError("Windows OCR 구성파일을 찾지 못했습니다.")
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Path", str(source)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "이미지 OCR에 실패했습니다.")
        return completed.stdout.strip(), "이미지 OCR"
    if suffix == ".pdf":
        with pdfplumber.open(source) as document:
            return "\n".join(page.extract_text() or "" for page in document.pages), "PDF"
    if suffix in {".xlsx", ".xlsm"}:
        workbook = load_workbook(source, read_only=True, data_only=True)
        try:
            lines = []
            for sheet in workbook.worksheets:
                lines.append(f"[시트:{sheet.title}]")
                for row in sheet.iter_rows(values_only=True):
                    values = [str(value).strip() for value in row if value not in (None, "")]
                    if values:
                        lines.append(" | ".join(values))
            return "\n".join(lines), "Excel"
        finally:
            workbook.close()
    if suffix in {".txt", ".csv"}:
        return source.read_text(encoding="utf-8-sig", errors="replace"), "텍스트"
    raise ValueError("지원 형식: PNG/JPG/BMP/TIFF, PDF, XLSX/XLSM, TXT/CSV")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" |:-\t")


def _after_alias(text: str, aliases: tuple[str, ...], limit: int = 80) -> str:
    for alias in aliases:
        match = re.search(rf"{re.escape(alias)}\s*[:：]?\s*([^\n|]{{2,{limit}}})", text, re.IGNORECASE)
        if match:
            return _clean(match.group(1))
    return ""


def _recipient_near_delivery(text: str) -> str:
    """배송 정보에 속한 이름만 찾고 발주/디자인 담당자는 제외한다."""
    lines = [_clean(line) for line in text.splitlines() if _clean(line)]
    name_pattern = re.compile(r"(?<![가-힣])([가-힣]{2,4})(?![가-힣])")
    ignored = {
        "담당자", "디자이너", "발주담당", "서울", "부산", "대구", "인천", "광주", "대전",
        "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
        "배송지", "배송주소", "수취인", "연락처", "휴대폰", "전화번호", "받는사람", "받는", "번호",
    }
    # 배송지의 명시적인 이름 표지만 인정한다. 주소에 섞인 업체명이나 지점명을
    # 사람 이름으로 추정하면 자동 등록 단계에서 더 위험한 오류가 된다.
    for line in lines:
        if "담당자" in line or "디자이너" in line:
            continue
        match = re.search(r"(?:수령인|받는\s*사람|수취인|성명)\s*[:：]?\s*([가-힣]{2,4})", line)
        if match and match.group(1) not in ignored:
            return match.group(1)
        address_name = re.search(
            r"(?:배송주소|배송지|받는\s*곳)\s*[:：]?\s*([가-힣]{2,4})\s+(?=서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)",
            line,
        )
        if address_name and address_name.group(1) not in ignored:
            return address_name.group(1)
    return ""


def _first_code(text: str) -> str:
    """DB 대조가 가능한 영문+숫자 품목코드를 우선 보존한다."""
    match = re.search(r"(?<![A-Za-z0-9])([A-Z]\d{6})(?!\d)", text, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _printing_phrase(text: str) -> str:
    """인쇄 방식이 아닌 실제 인쇄 문구만 반환한다."""
    for label in ("인쇄문구", "인쇄 문구", "문구", "인쇄내용", "인쇄 내용"):
        match = re.search(rf"{re.escape(label)}\s*[:：]\s*([^\n|]{{1,80}})", text, re.IGNORECASE)
        if not match:
            continue
        value = _clean(match.group(1))
        if re.search(r"(?:없음|없슴|무인쇄|인쇄\s*안함)", value):
            return ""
        return value
    return ""


def _printing_device(text: str) -> str:
    compact = re.sub(r"\s+", "", text).casefold()
    no_print = any(term in compact for term in ("인쇄없음", "무인쇄", "인쇄안함", "인쇄하지않음"))
    if no_print:
        return ""
    has_uv = "uv인쇄" in compact or "uv프린" in compact
    has_laser = any(term in compact for term in ("레이저인쇄", "레이저각인", "레이져인쇄", "레이져각인"))
    if has_uv and not has_laser:
        return "UV"
    if has_laser and not has_uv:
        return "레이저"
    return ""


def _packaging_value(text: str) -> str:
    compact = re.sub(r"\s+", "", text)
    if re.search(r"(?:선물)?포장(?:없음|안함|제외)", compact):
        return ""
    if "선물포장" in compact or re.search(r"선\s*포\s*장\s*무", text):
        return "선물포장"
    if "기본패키지" in compact:
        return "기본패키지"
    if "OEM포장" in compact.casefold().replace("oem", "OEM"):
        return "OEM포장"
    if "벌크" in compact:
        return "벌크"
    return ""


def _quantity_values(text: str) -> tuple[str, list[int]]:
    """총수량/수량 문맥과 상품표 수량을 비교해 충돌 시 자동 입력하지 않는다."""
    candidates: list[int] = []
    for match in re.finditer(r"(?:총\s*수량|주문\s*수량|발주\s*수량|수량)\s*[:：]?\s*([1-9]\d{0,2}(?:[,.]\d{3})*)\s*(?:개|EA|ea)?", text):
        candidates.append(int(re.sub(r"\D", "", match.group(1))))

    # 고려기프트 표는 보통 '수량 단가' 순서다. 소수점처럼 OCR 된 천 단위
    # 금액 바로 앞의 정수를 상품표 수량 후보로 취급한다.
    for match in re.finditer(r"(?<![\d.,])([1-9]\d{0,4})\s+([1-9]\d{0,2}[,.]\d{3})(?!\d)", text):
        quantity = int(match.group(1))
        price = int(re.sub(r"\D", "", match.group(2)))
        if quantity <= 10000 and price >= 1000:
            candidates.append(quantity)

    unique = list(dict.fromkeys(value for value in candidates if value > 0))
    if len(unique) == 1:
        return f"{unique[0]}개", unique
    return "", unique


def _request_date(text: str) -> str:
    """주소 번지(305-1)를 날짜로 오인하지 않고 납기/출고 문맥을 우선한다."""
    patterns = (
        r"(?:납\s*기|출고(?:요청)?일?|발송일?)\D{0,20}(?:(20\d{2})\s*년?\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일?",
        r"(?:(20\d{2})\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일",
    )
    matches = []
    for pattern in patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            break
    if not matches:
        return ""
    year, month, day = matches[-1].groups()
    if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
        return ""
    return f"{year + '-' if year else ''}{int(month):02d}-{int(day):02d}"


def _shipping_address(text: str) -> str:
    # Windows OCR에서 반복적으로 확인된 광주/울산 오독만 제한적으로 교정한다.
    searchable = text.replace("팡주", "광주").replace("팡산구", "광산구").replace("물산 북구", "울산 북구")
    match = re.search(
        r"주소\s*[:：]?\s*((?:\d{3}[- ]?\d{2}\s*)?(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주).{8,120}?)(?=\s*(?:보내는|고려기프트|고켴기프|TEL|전화\s*[:：]|$))",
        searchable, re.IGNORECASE,
    )
    if match:
        return _clean(match.group(1))
    return ""


def analyze_text(text: str, source_type: str = "텍스트") -> AnalysisResult:
    normalized = text.replace("\r", "\n")
    vendor = "고려기프트" if "고려기프트" in normalized or "고켴기프" in normalized else "신규 업체"
    fields = {key: _after_alias(normalized, aliases) for key, aliases in FIELD_ALIASES.items()}
    issues: list[str] = []
    fields["item_code"] = _first_code(normalized) or fields["item_code"]
    if fields["recipient"] and (re.search(r"\d", fields["recipient"]) or fields["recipient"].startswith("번호")):
        fields["recipient"] = ""
    if not fields["recipient"]:
        fields["recipient"] = _recipient_near_delivery(normalized)

    phones = re.findall(r"0\d{1,2}[- )]\d{3,4}[- ]\d{4}", normalized)
    mobile_phones = [phone for phone in phones if phone.startswith("010")]
    if mobile_phones:
        fields["contact"] = mobile_phones[-1]
    elif not fields["contact"] and phones:
        fields["contact"] = phones[-1]
    fields["request_date"] = _request_date(normalized)
    fields["quantity"], quantity_candidates = _quantity_values(normalized)
    if len(quantity_candidates) > 1:
        issues.append("수량 충돌: " + ", ".join(f"{value:,}개" for value in quantity_candidates))
    if not fields["product"]:
        product_match = re.search(r"([가-힣A-Za-z0-9+*() ]{8,}(?:배터리|충전기)[가-힣A-Za-z0-9+*() ]*)", normalized)
        if product_match:
            fields["product"] = _clean(product_match.group(1))[:100]
    if not fields["product"] and vendor == "고려기프트":
        product_match = re.search(r"([가-힣A-Za-z0-9+*() ]{0,35}보조.{0,8}(?:터리|Ei리).{0,35})", normalized)
        if product_match:
            fields["product"] = _clean(product_match.group(1))[:100]
    fields["address"] = _shipping_address(normalized)
    fields["printing"] = _printing_phrase(normalized)
    fields["device"] = _printing_device(normalized)
    fields["packaging"] = _packaging_value(normalized)
    compact = re.sub(r"\s+", "", normalized).casefold()
    no_print = any(term in compact for term in ("인쇄없음", "무인쇄", "인쇄안함", "인쇄하지않음"))
    has_uv = "uv인쇄" in compact or "uv프린" in compact
    has_laser = any(term in compact for term in ("레이저인쇄", "레이저각인", "레이져인쇄", "레이져각인"))
    if has_uv and has_laser:
        issues.append("기기 충돌: UV와 레이저가 함께 기재됨")
    elif not no_print and not fields["device"] and any(
        term in compact for term in ("컬러인쇄", "실크인쇄", "전사인쇄", "인쇄작업", "인쇄요청")
    ):
        issues.append("기기 확인 필요: UV 또는 레이저를 선택하세요")
    if vendor == "고려기프트" and "선불택" in normalized:
        fields["delivery"] = "택배"

    confidence = {key: (90 if value and source_type != "이미지 OCR" else 70 if value else 0) for key, value in fields.items()}
    return AnalysisResult(source_type, vendor, fields, confidence, normalized.strip(), issues)


def analyze_order_document(path: str | Path) -> AnalysisResult:
    text, source_type = extract_text(path)
    if not text.strip():
        raise ValueError("발주서에서 읽을 수 있는 텍스트가 없습니다.")
    return analyze_text(text, source_type)
