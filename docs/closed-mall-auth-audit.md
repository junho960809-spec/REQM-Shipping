# 폐쇄몰 로그인·송장등록 분석 보류 기록

## 상태

- 보류일: 2026-09-24
- 보류 사유: 현재 휴대폰 인증번호 수신 및 입력이 불가능함
- 재개 문구: `Computer Use를 적용시키고 작업하자`
- 재개 조건: 사용자가 휴대폰 인증번호를 직접 확인하고 브라우저에 입력할 수 있는 상태

## 재개 시 작업 순서

1. Computer Use로 폐쇄몰을 한 곳씩 연다.
2. 아이디·비밀번호와 인증번호는 사용자가 브라우저에 직접 입력한다.
3. 로그인 과정에서 휴대폰·이메일·인증번호 없음 여부를 확인한다.
4. 인증 요청 시점, 번호 자릿수, 제한 시간, 재전송 기능을 기록한다.
5. 로그인 완료 후 주문관리 화면 주소를 확인한다.
6. 송장등록 화면과 Excel 일괄등록 지원 여부를 확인한다.
7. 등록 성공을 판별할 수 있는 화면 상태와 문구를 확인한다.
8. 확인 결과를 `closed_malls.json` 기본 설정과 자동화 어댑터에 반영한다.

## 휴대폰 인증으로 우선 분류된 사이트

- 이알아이
- 삼성쇼핑몰: https://ecpartner.samsungcard.com/loginForm.do
- 한섬: https://po.thehandsome.com/main
- SSF: https://withus.ssfshop.com/pologin#
- 마켓컬리: https://3p-partner.kurly.com/
- 핫트랙스(교보문고): https://admin.hottracks.co.kr/admin/login/form

## 로그인 후 인증 방식 확인이 필요한 사이트

- 현대홈쇼핑: https://partner.hmall.com/
- 29Connect: https://partner-connect.29cm.co.kr/dashboard
- 현대이지웰: https://padmin.ezwel.com/
- ETBS 베네카페: https://malladmin.benecafe.co.kr/common/login?returnUrl=%2Fcommon%2FpoMain
- M포인트몰: https://mpointadmin.hyundaicard.com/login.do
- 베네피아 포인트몰: https://newmallvenadm.benepia.co.kr/login/loginView.do
- 삼성복지몰: https://www.sammall.co.kr/provider/index.html#main-layer75
- 무신사: https://partner.musinsa.com/
- W컨셉 Pin: https://newpin.wconcept.co.kr/Auth/Login
- Shop by 파트너어드민: https://partner.shopby.co.kr/

## 판별 결과 값

- `phone`: 휴대폰 문자 인증
- `email`: 이메일 인증번호
- `none`: 아이디·비밀번호 로그인 후 추가 인증 없음
- `other`: 인증 앱, QR, 보안 프로그램 등 별도 방식
- `unknown`: 로그인 후 확인 전

비밀번호와 인증번호 원문은 프로그램 설정, 공용 DB, 작업 기록에 저장하지 않는다.
