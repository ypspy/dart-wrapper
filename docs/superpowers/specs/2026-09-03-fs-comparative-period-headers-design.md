# 제표 비교열 `제N기` 기간 매핑 (D-5 보완)

날짜: 2026-09-03  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` `app/extracting/accounts.py` — 헤더에 `당기`/`전기`가 없을 때
비교 열을 current/prior로 붙인다. 가짜 헤더(`당기순이익` 행)로 `ok`+빈 금액이 나오지 않게 한다.  
선행: [2026-09-02 첨부 재무제표 계정 추출](2026-09-02-audit-accounts-extraction-design.md).

실측: 동서식품 연결감사보고서 `20170328000756` dcm `5511049`. TOC에 BS/IS leaf가 없고
부모 `(첨부)연결재무제표`만 있다. 표는 4칸 과목\|주석\|`제49기 기말`\|`제48기 기말`.
자산총계·당기순이익 숫자는 있다. `_find_bs_table`/`_find_is_table`은 표를 고른다.
`_col_role`이 기수 열을 기간으로 보지 않아 그룹이 비고, 손익 `당기순이익` 행이
`당기`를 포함해 헤더로 오인되며 `accounts_status=ok`에 여덟 계정 `not_found`가 된다.

## 1. 목표

D-5 계정 JSON 계약은 그대로다. 헤더가 `제49기 기말`/`제48기`처럼 **기수만 있는 비교표**에서도
당기·전기를 채운다. `당기`/`전기`가 있는 4·5·6칸 표는 지금 동작을 유지한다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 당기/전기 헤더 | 기존 `_col_role`이 **항상 이김** |
| 둘 다 없을 때 | compact `제(\d+)기` 기수. **큰 기=당기, 작은 기=전기** |
| 기수 실패 | 주석이 아닌 금액 열, 왼쪽=당기, 그다음=전기 |
| 가짜 헤더 | 과목/라벨 칸과 compact `당기순` 칸은 기간 열이 아님 |
| 저장·잡 | 같은 `audit_report_facts` 행, 같은 extract 잡 |
| 버전 | `extractor_version` = `audit_opinion.v12` |
| `period=unknown` | 쓰지 않음 |
| `period_raw` | 헤더 칸 원문 (예: `제49기 기말`) |

## 3. 기간 그룹 순서

`_period_groups`(또는 그 직후 한 단계)만 확장한다. `extract_accounts` 시그니처,
여덟 계정, 내역/합계, `cut_notes`, selector, fetch는 바꾸지 않는다.

1. 칸 역할: `주석`/`주기` → note. `당기` 또는 `(당)기` → current. `전기` 또는 `(전)기` → prior.
   **과목 칸(보통 맨 왼쪽)과 compact에 `당기순`이 있는 칸은 이 매칭에서 제외**한다.
2. current·prior 그룹이 하나라도 있으면 그 그룹을 쓰고 끝낸다.
   (`제 3(당) 기` 5칸은 여기서 끝. 기수 분기를 타지 않는다.)
3. 그룹이 비면 같은 헤더 행에서 note가 아니고 1번에서 제외되지 않은 칸의 compact에
   `제(\d+)기`가 있는지 본다.
   - 기수 **둘 이상**: 최댓값=당기, 최솟값=전기. 중간 기는 버린다.
   - 기수 **하나**: 그 열만 당기 (`prior` 없음).
   - 기수가 둘인데 **값이 같으면** 기수 실패 → 4번.
4. 3번도 그룹을 못 만들면 주석·과목·`당기순`이 아닌 열을 왼쪽부터 당기, 그다음 전기.
   금액 열이 하나면 당기만.
5. 1~4 후에도 그룹이 없으면 그 표는 기간을 읽지 못한 것이다. 다른 표도 없으면
   `accounts_status=not_found`, `accounts=[]`.
   **데이터 행 `당기순이익`만으로 그룹을 만들어 `ok`를 내면 안 된다.**

`_is_header_row`는 과목/`당기순` 칸의 `당기`만으로는 헤더라고 보지 않는다.
`제`+`기`·`과목`·당기/전기(제외 칸이 아닌 것)는 기존처럼 헤더 신호다.

열 두 개가 같은 기간이면 기존처럼 왼쪽=내역, 오른쪽=합계다. 기수 매핑 뒤에도 같다.

## 4. 잡 · API

`EXTRACTOR_VERSION`을 `audit_opinion.v12`로 올린다. v11 `ok` 행은 다음 `extract`에서
제표 URL을 다시 가져온다. Public 스키마·`field_partial`·컬럼은 그대로다.

## 5. 테스트

실제 DART 호출 없음. HTML fixture.

- 동서식품 축약: 과목\|주석\|제49기 기말\|제48기 기말, 자산총계·자본총계·당기순이익 숫자.
  `total_asset` current=제49기 칸, prior=제48기 칸. `당기순이익` 행이 있어도 헤더가 아니다.
  `accounts_status=ok`.
- 기존 5칸 `제 3(당) 기` fixture는 금액·단위가 v11과 같다 (기수 분기 미사용).
- 기수 파싱 실패(같은 숫자 두 열) 또는 `제N기` 없이 금액 열 두 개: 왼쪽 current, 오른쪽 prior.
- 헤더가 과목뿐이고 본문에 `당기순이익`만 있으면 `not_found`+`[]`이지 `ok`가 아니다.

## 6. 범위 밖

- D-6, D-7, 본표 전 행 덤프, OpenDART
- 달력 연도만 있는 헤더를 연도로 해석하기 (왼쪽·오른쪽 fallback이면 위치만 쓴다)
- 3개 이상 기를 각각 period로 저장하기
- `cut_notes`가 TH `주석 `에서 잘리는 경우 (동서식품 본표는 유지됨)

## 7. 디렉터리

```text
app/extracting/accounts.py              # 기간 그룹 2단계, 가짜 헤더 제외
app/extracting/constants.py             # audit_opinion.v12
tests/test_extracting_accounts.py       # 제N기 fixture
tests/test_audit_report_fact_repository.py
tests/test_extraction_service.py        # 버전 문자열
packages/web-api/README.md
```
