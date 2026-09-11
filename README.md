# REQM Shipping

택배·면세점 주문을 분석하고 출고용 엑셀을 생성하는 Windows 데스크톱 프로그램입니다.

## 기준 버전

- 애플리케이션: `1.2.5`
- 원본 저장소 기준 브랜치: `main`
- 이카운트 회사코드: `304293`
- 이카운트 ZONE: `AB`

## 주요 기능

- B2C/B2B 주문 양식 판별 및 품목 매칭
- 출고용 엑셀 생성과 출력 양식 관리
- 이카운트 창고이동 API 연동
- 이카운트 사용자·담당자·창고 정보 관리
- 관리자용 API 인증키 암호화 저장
- 위킵 SKU·배송정보 검증, 프로그램 내부 최종 승인, 숨김 브라우저 자동 로그인·출고 등록
- 위킵 등록일·판매처별 송장 조회, 주문 대조 및 기존 택배출고 양식 송장 입력
- 암호화된 로컬 출고 작업 이력과 동일 작업 중복 제출 차단
- 와이즐리 물류팀의 당일 주문 메일과 Excel 첨부파일 자동 수신

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
- `ui/styles/theme.qss`: 공통 색상·간격·버튼·카드·테이블 디자인
- `ui/texts.py`: 기능 코드와 분리된 사용자 표시 문구
- `ui/preview.py`: 외부 서비스에 연결하지 않는 UI 미리보기
- `shipment_domain.py`: 출고 수량·필수값·중복 키 도메인 규칙
- `shipment_job_store.py`: 암호화된 SQLite 출고 작업 및 상태 이력
- `wekeep_order_automation.py`: 위킵 자동 로그인·첨부·최종 등록 및 결과 확인
- `*_dialog.py`, `*_window.py`, `*_module.py`: 운영 기능 화면
- `tests/`: 자동 테스트만 보관하며 배포 파일에는 포함하지 않음
- `tools/`: 업데이트 패키지 생성·배포용 개발 도구
- `assets/`: 공식 실행 파일에 포함되는 양식과 런타임 자산
- `REQM.spec`: 유일한 공식 Windows 빌드 설정

`config.example.json`을 `config.json`으로 복사해 사용하며 실제 인증키와 비밀번호는 커밋하지 않습니다.

위킵 자동 출고는 `연동 계정`에서 저장한 위킵 계정을 현재 Windows 사용자만
복호화할 수 있도록 보호합니다. 최종 등록 전에 프로그램 팝업에서 작업자가 주문 건수와
수량을 승인해야 하며, 성공 응답이 불명확한 작업은 중복 방지를 위해 자동 재시도하지 않습니다.

웹메일 자동 로그인은 HTTPS 주소에서만 실행됩니다. 운영 웹메일 서버의 인증서가 올바르게
설정돼 있어야 하며, 필요한 경우 `REQM_WEBMAIL_URL`과 `REQM_WEBMAIL_INBOX_URL` 환경 변수로
검증된 HTTPS 주소를 지정할 수 있습니다.

## UI와 문구 수정

로그인이나 실제 출고 없이 미리보기 화면을 실행할 수 있습니다.

```powershell
python -m ui.preview
```

미리보기에서 `편집 파일 만들기`를 누르면 `%LOCALAPPDATA%\REQM`에 다음 파일이 만들어집니다.

- `theme.qss`: 기본 테마 뒤에 적용되는 디자인 덮어쓰기
- `ui_texts.json`: 허용된 화면 문구 덮어쓰기

파일을 저장한 뒤 미리보기의 `테마·텍스트 다시 불러오기`를 누르면 변경 내용을 확인할 수
있습니다. 화면 문구 키는 주문 유형·상태 코드·사이트 선택자와 분리돼 있어 문구 변경이
출고 판단 로직에 사용되지 않습니다. 실제 프로그램에는 재실행 후 반영됩니다.
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

위킵 품목 정보를 여러 사용자가 공유하려면 Supabase SQL Editor에서
`supabase/migrations/20260911_wekeep_sku_mappings.sql`도 한 번 실행해야 합니다.
적용 후 관리자가 처음 로그인하면 기존 기본·로컬 SKU 정보가 빈 공용 테이블로 자동 이전됩니다.
이후 위킵 SKU와 상품관리명은 Supabase를 원본으로 사용하며 로컬 JSON은 통신 장애 대비 캐시로 유지됩니다.

- `판매자료 자동 동기화`: 지난주 금요일부터 이번주 목요일까지 이카운트 판매현황을 조회하고 해당 기간을 교체합니다.
- `주간재고조사 Excel 생성`: Supabase 누적 자료를 `RAWDATA_이카운트` 시트에 기록합니다.

주간재고 평가 단가는 Supabase의 `weekly_inventory_item_settings`에서 관리합니다.
관리자는 메인 화면의 `DB 관리 → 주간재고 단가 관리`에서 VAT 별도 단가와 사용 여부를 수정할 수 있으며,
VAT 포함 단가는 10%를 자동 계산합니다. 판매전표 단가와는 별도 데이터입니다.
