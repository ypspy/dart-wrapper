# 재무상태표 유동자산·유동부채 소계 (D-5 보완)

날짜: 2026-09-04  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` `app/extracting/accounts.py` — 첨부 재무상태표에서
유동자산·유동부채 **소계**를 읽어 기존 `accounts` JSON에 붙인다.  
선행: [2026-09-02 첨부 재무제표 계정 추출](2026-09-02-audit-accounts-extraction-design.md),
[2026-09-03 제N기 비교열](2026-09-03-fs-comparative-period-headers-design.md),
[2026-09-03 당기순 부호](2026-09-03-net-income-sign-design.md).

기존 D-5는 재무상태표 표를 이미 읽는다. E-4 여덟 계정만 매핑한다.
`Ⅰ. 유동자산` 행은 5칸 fixture에 있으나 계정 키가 없어 저장하지 않는다.
유동비율 같은 파생값은 이번 범위가 아니다.

## 1. 목표

같은 `extract_accounts` 호출에서 `current_asset`·`current_liability` 원소를 만든다.
새 잡·새 컬럼·새 패키지·selector 변경은 없다.
`extract_accounts` 시그니처, `cut_notes`, 기간 헤더, 단위, 내역/합계 칸 규칙은 그대로다.
두 키만 `_TOTAL_ACCOUNTS`에 넣어 소계 칸을 고른다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 산출 | 기존 `audit_report_facts.accounts` 배열. 의견·D-4·D-5와 **같은 행** |
| 실행 | 기존 `POST /admin/extract/audit-opinion`. 새 `extractor_id` 없음 |
| 계정 키 | `current_asset`, `current_liability` |
| JSON 위치 | E-4 여덟 계정 **뒤**. 스키마(`period`/`raw`/`value`/`unit_*`/`value_won`/`status`) 동일 |
| 기간 | 당기 그리고 전기. 전기 열이 없으면 `prior` 원소를 만들지 않음 (현행) |
| 행이 없음 | 그 계정×있는 기간 원소를 넣되 `status=not_found`, `value`/`raw`/`account_raw`는 null |
| `accounts_status` | 표를 하나라도 읽으면 `ok`. 두 소계만 비어도 필드는 `ok` |
| 저장·잡 | 같은 행, 같은 extract 잡. HTML은 저장하지 않음 |
| 버전 | `extractor_version` = `audit_opinion.v15` |

## 3. 라벨

`_account_of`에서 자산총계·자본총계 다음에 본다. compact 기준. **앞 행이 이긴다.**

| compact | `account` |
|---------|-----------|
| `유동자산`이 있고 `비유동`·`기타`가 없음 | `current_asset` |
| `유동부채`가 있고 `비유동`·`기타`가 없음 | `current_liability` |

제외는 문자열 `비유동`과 `기타`다. 글자 `비` 단독이 아니다 (`비교`를 소계에서 떨어내지 않기 위함).

로마숫자(`Ⅰ.` / `I.`)나 `합계` 글자는 요구하지 않는다. `유 동 자 산`은 기존 `compact`가 붙인다.

같은 규칙으로 빠지는 행:

- `비유동자산`·`비유동부채` — `비유동` (`유동자산`/`유동부채` 부분문자열)
- `기타유동자산`·`기타유동부채` — 개별 과목
- `유동화자산`·`유동화부채` — `유동자산`/`유동부채` 부분문자열이 아님
- `유동성장기부채` — `유동부채` 부분문자열이 아님
- `(1) 당좌자산` — `유동자산`이 아님. 앞의 `Ⅰ. 유동자산`이 있으면 그 행이 이김

소계를 현금·당좌·재고 합으로 만들지 않는다. 유동성 배열(은행·보험 등)이나 SPC처럼
`유동부채` 행이 없고 `유동화부채`만 있으면 `current_liability`는 `not_found`다.

## 4. 금액 칸

`_TOTAL_ACCOUNTS`에 `current_asset`·`current_liability`를 넣는다.
`total_asset`/`total_equity`/`net_income`과 같다.

- 기간 그룹 칸이 하나면 그 칸
- 둘이면 비어 있지 않은 쪽. **둘 다 차 있으면 합계(오른쪽) 칸**
- 짝 칸 공란 → 무시. 0이 아님 (5칸 `Ⅰ. 유동자산`의 내역 칸)
- `-` / `－` → `value=0`
- 기간 금액 칸이 모두 비면 그 기간 원소를 만들지 않음 (현행)

부호 규칙은 `_parse_amount` 그대로다. 순손실 라벨 `-abs`는 `net_income`만이다.

## 5. 잡 · API

`EXTRACTOR_VERSION`을 `audit_opinion.v15`로 올린다. v14 `ok` 행은 다음 `extract`에서
제표 URL을 다시 가져온다. Public 스키마·컬럼·`field_partial`·selector·`cut_notes`는 그대로다.
README 계정 목록을 여덟에서 열로 고친다.

## 6. 테스트

실제 DART 호출 없음. HTML fixture.

- 5칸: `current_asset` 당기 `665,809,879`, 전기 `622,084,856`. 내역 공란을 0으로 읽지 않음.
  `current_liability`도 합계 칸.
- `비유동자산`만 있고 `유동자산`이 없으면 `current_asset`은 `not_found`.
  `비유동부채`를 `current_liability`로 쓰지 않음.
- `기타유동자산`·`기타유동부채`는 소계가 아님.
- `Ⅰ. 유동자산`과 `Ⅱ. 유동화자산`·`유동화부채`만 있는 SPC 표:
  `current_asset`은 유동자산 소계, `current_liability`는 `not_found`.
- 기존 8계정·4·6칸·제N기·순손실 부호 테스트는 그대로 통과.

## 7. 범위 밖

- 유동비율·운전자본 등 파생값 저장
- 비유동자산·비유동부채 소계
- 현금·당좌 합산으로 유동자산을 만들기
- BS·IS 전 행 덤프, OpenDART, 별도/연결 금액 교차
- D-6 내부회계, D-7 정관·OCR

## 8. 디렉터리

```text
app/extracting/accounts.py              # 계정 목록, _account_of, _TOTAL_ACCOUNTS
app/extracting/constants.py             # audit_opinion.v15
tests/test_extracting_accounts.py
tests/test_audit_report_fact_repository.py
tests/test_extraction_service.py
packages/web-api/README.md
```
