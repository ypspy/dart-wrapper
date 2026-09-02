# 당기순이익·순손실 라벨과 금액 부호 (D-5 보완)

날짜: 2026-09-03  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` `app/extracting/accounts.py` — `net_income` 칸의 부호를
과목 라벨과 칸 표시에 맞게 맞춘다.  
선행: [2026-09-02 첨부 재무제표 계정 추출](2026-09-02-audit-accounts-extraction-design.md),
[2026-09-03 제N기 비교열](2026-09-03-fs-comparative-period-headers-design.md).

지금 `_parse_amount`는 금액 칸이 `(n)` / `△` / 선행 `-`이면 음수다.
`당기순손실`처럼 과목 이름만으로 손실을 나타내는 행은 칸에 괄호가 없어도
양수로 남는다. `당기순이익(손실)` 비교표는 당기·전기가 한쪽만 `()`일 수 있다.

## 1. 목표

여덟 계정 중 **`net_income`만** 고친다. 이익잉여금·결손금 계정은 추가하지 않는다.
`extract_accounts` 시그니처, selector, `cut_notes`, 내역/합계, 제N기 기간 그룹은 그대로다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 적용 | `account == "net_income"` 원소의 `value` / `value_won` |
| 비교 열 | **칸마다 독립**. 한쪽만 `()`여도 다른 열 부호를 맞추지 않음 |
| `당기순이익` · `당기순이익(손실)` | compact에 **`순이익`**. 칸 부호만 (`()` / `△` / 선행 `-`) |
| `당기순손실` | compact에 **`순손실`이 있고 `순이익`이 없음**. `value = -abs(parsed)` |
| 이미 괄호인 순손실 칸 | 한 번만 음수 (양수로 뒤집지 않음) |
| 대시 `-` / `－` | `value=0` (순손실이어도 0) |
| 저장·잡 | 같은 `audit_report_facts` 행, 같은 extract 잡 |
| 버전 | `extractor_version` = `audit_opinion.v13` |

`당기순이익(손실)`은 compact에 `순이익`이 있어 순손실 분기를 타지 않는다.
`당기순손익`처럼 둘 다 아니면 칸 부호만 쓴다(현행).

## 3. 적용 순서

`_parse_amount`는 그대로 둔다. `net_income` 행에서 칸을 읽은 뒤:

1. 금액이 없으면 그 기간 원소를 만들지 않는다 (현행).
2. 대시면 `value=0`.
3. compact 라벨에 `순이익`이 없으면서 `순손실`이 있으면 `value = -abs(value)`.
4. `value_won`이 있으면 `value * unit_scale`을 다시 계산한다 (음수 유지).

`raw`는 칸 원문 그대로다.

## 4. 잡 · API

`EXTRACTOR_VERSION`을 `audit_opinion.v13`으로 올린다. v12 `ok` 행은 다음 `extract`에서
제표 URL을 다시 가져온다. Public 스키마·컬럼·`field_partial`은 그대로다.

## 5. 테스트

실제 DART 호출 없음. HTML fixture.

- `당기순이익(손실)`: 당기 `1,000` → `+1000`, 전기 `(500)` → `-500`.
  `당기총포괄이익` 행은 `net_income`이 아니다.
- `당기순손실`: 당기 `1,000` → `-1000`, 전기 `(200)` → `-200`.
- 기존 4·5·6칸·제N기·가짜 헤더 fixture의 당기순(이익) 양수는 유지.

## 6. 범위 밖

- BS 이익잉여금(결손금)·결손금 계정 추가
- 비교 두 열 부호를 서로 맞추기
- 자산총계 등 다른 계정의 라벨 부호
- D-6, D-7, 본표 전 행 덤프, OpenDART

## 7. 디렉터리

```text
app/extracting/accounts.py              # net_income 순손실 -abs
app/extracting/constants.py             # audit_opinion.v13
tests/test_extracting_accounts.py
tests/test_audit_report_fact_repository.py
tests/test_extraction_service.py
packages/web-api/README.md
```
