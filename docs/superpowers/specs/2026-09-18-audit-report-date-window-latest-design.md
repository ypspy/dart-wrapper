# 감사보고서일 창 안 최댓값 선택 설계

날짜: 2026-09-18  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` — `pick_audit_report_date` 규칙, `EXTRACTOR_VERSION`,
날짜 LLM 잡 대상(`not_found`)과 저장 검사.  
후보 전수 수집·인증일 파싱·`limit`·API 키 게이트는
[전수 후보·인증일 일치](2026-09-18-audit-report-date-all-candidates-auth-match-design.md)를
유지한다. 그 문서의 **인증일 일치만 ok**와 **해소 잡은 ambiguous만·저장 시 창 검사**는
이 스펙이 덮어쓴다.

facts 스키마·selector·의견/GAAP·완전성 SQL·Admin 추출 화면은 바꾸지 않는다.

선행: [감사의견 추출](2026-08-28-audit-opinion-extraction-design.md) §6.2.  
원전(인증일): 「전자문서제출요령」 제3장. `rcept_no` 앞 8자리. 목록 `rcept_dt` 아님.

## 1. 목표

인증일과 같은 날만 `ok`로 두면 서명일이 하루 앞선 흔한 경우가
`ambiguous`가 된다. 추출은 창 안에서 **가장 늦은 날**을 고른다.
창이 비면 `not_found`로 두고, 운영자가 나중에 LLM으로 후보 인덱스를 고른다.

성공 기준:

- 창 `period_end < iso ≤ 인증일` 안에 날짜가 있으면 그중 최댓값 ISO,
  status `ok`, source `letter`. 인증일과 같을 필요는 없다.
- 같은 창에 `2020-03-30`과 `2020-03-31`이 있으면 `2020-03-31`을 고른다.
  `2020-03-30`만 있으면 그것을 고른다 (`rcept_no`가 `20200331000001`이어도).
- 창이 비면 ISO `None`, status `not_found`. 후보는 그대로 저장한다.
- 추출 잡은 LLM을 호출하지 않는다.
- `POST /admin/extract/resolve-dates`는 후보가 있는 `not_found`만 집어
  LLM 인덱스를 저장한다. 이 경로에서는 창 검사를 하지 않는다.
- 후보 0건 `not_found`는 해소 잡에 넣지 않는다. `PATCH`만 가능하다.
- `EXTRACTOR_VERSION`은 `audit_opinion.v19`이다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 패키지 | `packages/web-api` |
| 인증일 | `rcept_no` 앞 8자리. 목록 `rcept_dt`는 선택·창·프롬프트에 쓰지 않음 |
| 창 (추출) | `period_end < iso ≤ 인증일`. `period_end`가 `None`이면 왼쪽만 생략 |
| 규칙 확정 | 창 안 ISO 중 **최댓값**. 동률이면 그 ISO 하나 |
| 창 빔 | `not_found`. `ambiguous`를 만들지 않음 |
| 인증일 없음 | 오른쪽 끝이 없으면 고르지 않는다 → `not_found` |
| 후보 전수 | 유지. `_preprocess` 없음 |
| 추출 중 LLM | 없음 |
| 해소 큐 | 기존 POST. **후보가 1개 이상인 `not_found`**. `ambiguous`·후보 0건 제외 |
| LLM 저장 | 고른 후보 ISO를 그대로 저장. **창 검사 없음** |
| LLM 출력 | 후보 인덱스. 본문 첨부 없음. 새 ISO 없음 |
| 키·한도 | `DATE_RESOLVER_API_KEY`, body `limit`(양의 정수, 생략 시 대상 전량) |
| 수동 | 기존 `PATCH .../date` |
| 스키마 | 컬럼 추가 없음 |
| 버전 | `audit_opinion.v19` |

`ambiguous` 상태값은 스키마에 남긴다. 이 규칙의 `pick`은 만들지 않는다.
기존 v18 `ambiguous` 행은 버전 상승으로 `extract`가 다시 받는다.

## 3. 선택 규칙

`date_in_auth_window(iso, period_end=, auth_date=)`는 추출 필터에 쓴다.
LLM 저장에는 쓰지 않는다.

`pick_audit_report_date(candidates, *, period_end, auth_date)`:

1. 후보가 없으면 `not_found`.
2. `auth_date`가 `None`이면 `not_found`.
3. 창(`period_end < iso ≤ auth_date`, `period_end` 없으면 `iso ≤ auth_date`)을
   통과한 후보가 없으면 `not_found`.
4. 통과분 ISO 중 최댓값을 `ok`로 반환한다. passing은 그 ISO를 가진 후보.

`ExtractionService._build_fact`는 지금처럼 `parse_auth_date(sample.rcept_no)`를 넘긴다.

## 4. 운영 큐 (LLM)

```text
추출 잡 (창 안 최댓값 또는 not_found)
운영자 검토
  → PATCH 또는
  → POST /admin/extract/resolve-dates { "limit": N }
```

- 추출·`resume`·`reparse`·`patch`는 `DateResolver`를 호출하지 않는다.
- 대상 쿼리: `audit_report_date_status == "not_found"` 이고
  `audit_report_date_candidates`가 비어 있지 않음.
  정렬은 지금과 같이 `rcept_no`, `dcm_no`. `limit`은 그 앞 N건.
- `_resolve_one`: 인덱스만 검증(범위·ISO 파싱). `date_in_auth_window` 호출 없음.
  성공 시 status `ok`, source `llm`.
- 프롬프트는 창 안으로 고르라고 하지 않는다. 저장된 후보 중 실제 감사보고서일을
  고르라고 한다. `DATE_RESOLVER_PROMPT_VERSION` 키는 유지하고 문구만 고친다.

## 5. 코드 경계

| 단위 | 역할 |
|------|------|
| `dates.py` `pick_audit_report_date` | 창 안 최댓값 / 빈 창 `not_found` |
| `constants.py` | `audit_opinion.v19` |
| `FactRepository` | `not_found`+후보 있는 행 목록 (기존 `list_ambiguous_dates`를 바꾸거나 대체) |
| `DateResolverService` | 그 목록을 순회. 저장 시 창 검사 삭제 |
| `LlmDateResolver` | 프롬프트에서 창 제한 문구 제거 |
| 테스트 | `test_extracting_dates.py`, `test_date_resolver.py`, 버전 문자열 |
| README | 보고일 규칙·DATE_RESOLVER 대상 |

## 6. 재실행

`v19`이므로 `extract`/`resume`는 기존 `ok` 행도 다시 GET한다.
override·기존 `llm` 보고일은 `_copy_operator_fields`와 같다.

## 7. 테스트

live DART·live LLM 없음.

`test_extracting_dates.py`:

- 창 안 두 ISO면 큰 쪽이 `ok`.
- 창 안이 인증일 전날 하나면 그날이 `ok` (일치 아님).
- 후보는 있는데 모두 `period_end` 이하이거나 인증일 다음이면 `not_found`.
- 후보 0 → `not_found`.
- `rcept_dt`를 pick에 넣지 않음.

`test_date_resolver.py`:

- 대상이 `not_found`+후보. `ambiguous`만 있는 행은 잡지 않음.
- 후보 0인 `not_found`는 잡지 않음.
- LLM이 창 밖 ISO를 골라도 저장(`ok`/`llm`).
- `limit=1`이면 대상 2건 중 1건만.
- `limit=0`은 400. body 없이 키 있으면 202.

## 8. 비범위

한자 숫자 변환, 본문 LLM 첨부, 새 ISO 생성, `rcept_dt` 창,
날짜 전용 reparse, Admin 해소 UI, 후보 0건을 LLM에 넣기,
`ambiguous`를 다시 만드는 규칙.
