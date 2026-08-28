# REQM Shipping

택배·면세점 주문을 분석하고 출고용 엑셀을 생성하는 Windows 데스크톱 프로그램입니다.

## 기준 버전

- 애플리케이션: `1.0.93`
- 원본 저장소 기준 브랜치: `main`
- 이카운트 회사코드: `304293`
- 이카운트 ZONE: `AB`

## 주요 기능

- B2C/B2B 주문 양식 판별 및 품목 매칭
- 출고용 엑셀 생성과 출력 양식 관리
- 이카운트 창고이동 API 연동
- 이카운트 사용자·담당자·창고 정보 관리
- 관리자용 API 인증키 암호화 저장

## 실행

```powershell
pip install -r requirements.txt
python main.py
```

## 빌드

```powershell
pyinstaller --noconfirm --clean REQM.spec
```

공식 배포 빌드 설정은 저장소 루트의 `REQM.spec` 하나뿐입니다. 기능별 화면은
Python 모듈과 단위 테스트로 검증하며, 별도의 `*_TEST.spec` 실행 파일은 만들지 않습니다.

## 저장소 구조

- `main.py`: 프로그램 진입점과 메인 화면
- `*_dialog.py`, `*_window.py`, `*_module.py`: 운영 기능 화면
- `tests/`: 자동 테스트만 보관하며 배포 파일에는 포함하지 않음
- `tools/`: 업데이트 패키지 생성·배포용 개발 도구
- `assets/`: 공식 실행 파일에 포함되는 양식과 런타임 자산
- `REQM.spec`: 유일한 공식 Windows 빌드 설정

`config.example.json`을 `config.json`으로 복사해 사용하며 실제 인증키와 비밀번호는 커밋하지 않습니다.
# 업데이트 배포

새 버전의 업데이트 폴더를 배포할 때는 `tools/publish_update.py`를 사용합니다.
새 청크를 먼저 업로드하고 manifest를 교체한 뒤, 이전 `REQM_*.exe.part*` 청크만 자동 삭제합니다.

```powershell
$env:SUPABASE_SERVICE_ROLE_KEY = "Supabase service_role 키"
python tools/publish_update.py C:\release\reqm-shipping-update-1.0.71
```
# 이카운트 판매 RAWDATA

주간재고조사의 판매 RAWDATA 기능은 Supabase의 `ecount_sales_rawdata` 테이블을 원본 저장소로 사용합니다.
최초 사용 전에 Supabase SQL Editor에서
`supabase/migrations/20260828_ecount_sales_rawdata.sql`을 실행해야 합니다.

- `판매자료 자동 동기화`: 지난주 금요일부터 이번주 목요일까지 이카운트 판매현황을 조회하고 해당 기간을 교체합니다.
- `주간재고조사 Excel 생성`: Supabase 누적 자료를 `RAWDATA_이카운트` 시트에 기록합니다.

주간재고 평가 단가는 Supabase의 `weekly_inventory_item_settings`에서 관리합니다.
관리자는 메인 화면의 `DB 관리 → 주간재고 단가 관리`에서 VAT 별도 단가와 사용 여부를 수정할 수 있으며,
VAT 포함 단가는 10%를 자동 계산합니다. 판매전표 단가와는 별도 데이터입니다.
