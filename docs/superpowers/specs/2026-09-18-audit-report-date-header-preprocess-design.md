# 감사보고서일 후행형 머리글 전처리 설계

날짜: 2026-09-18  
상태: 대체됨 — 구현하지 않는다.  
후속: [전수 후보·인증일 일치](2026-09-18-audit-report-date-all-candidates-auth-match-design.md).  
범위: `packages/web-api` — `app/extracting/dates.py`의 `_preprocess`와
`tests/test_extracting_dates.py`만.
창 선택, 날짜 정규식, facts 스키마, 추출기 버전, Admin 모드, LLM 해소 잡은 바꾸지 않는다.

선행: [감사의견 추출](2026-08-28-audit-opinion-extraction-design.md) §6.2 날짜(D-3-3).  
이 스펙이 그 절의 전처리 문장(「`의견근거` 앞과 `재무제표에대한경` 이후를 잇는다」)을
**`의견근거`가 없는 후행형**에 한해 덮어쓴다. 창·정규식·ambiguous→LLM은 그 스펙을 따른다.

## 1. 목표

후행형 의견서에서 보고일(`주주 및 이사회 귀중` 다음 줄의 `YYYY년M월D일`)이
후보에서 빠지지 않게 한다. 고르는 규칙은 그대로다.

성공 기준:

- `의견근거`가 없고 머리글에만 보고일이 있는 compact 본문에서
  그 날짜가 `extract_date_candidates`에 들어온다.
- 같은 본문의 당기말이 창(`period_end < iso ≤ rcept_dt`) 밖이면
  `pick_audit_report_date`는 ISO 하나와 `ok`다.
- `의견근거`가 있는 선행형은 지금과 같다. 중간 구간 날짜는 후보가 아니다.
- `EXTRACTOR_VERSION`은 `audit_opinion.v17`이다. 이미 `ok`인 행은 `extract`/`resume`가
  다시 GET하지 않는다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 실패 원인 | 점 찍은 날짜가 아니라, `의견근거` 없음 → 머리글이 통째로 버려짐 |
| 손대는 함수 | `_preprocess`만. `pick_audit_report_date`·정규식·snippet은 그대로 |
| `의견근거` 있음 | 지금과 같음. 그 앞 + 마지막 `재무제표에대한경` 뒤. 중간은 버림 |
| `의견근거` 없음 · 마커 있음 | 첫 `재무제표에대한경` **앞**을 `first_part`로 넣고, 마지막 마커 뒤는 지금처럼 붙임 |
| 마커 둘 다 없음 | 본문 전체 (지금과 같음) |
| 창 | `period_end < iso ≤ rcept_dt`. 한쪽 `None`이면 그 비교 생략. 후반 우선 없음 |
| 0·1·2+ | `not_found` / `ok` / `ambiguous`(ISO `None`) |
| 버전 | `audit_opinion.v17` 유지 |
| 재실행 | 기존 `reparse`. 어느 필드든 `not_found`인 문서를 다시 fetch |
| ambiguous | 이번 파서가 고르지 않음. 기존 LLM 잡(`POST /admin/extract/resolve-dates`) |
| 패키지 | `packages/web-api` |

2016년 전후 F001 실측: `의견근거` 없이 `독립된감사인의감사보고서…귀중YYYY년M월D일우리는…재무제표에대한경영진의책임` 서식이다.
서명란에는 날짜가 없고 「감사보고서일 현재로 유효」만 있다. 머리글 날짜 형식은 이미 `YYYY년M월D일`이다.

후행형은 `재무제표에대한경`이 한 번인 경우가 많다. 그때 `first_part`+`second_part`는
마커 문자열만 빠진 본문에 가깝다. 당기말은 창이 걸러 준다. 후속사건이 창 안에 더 있으면
`ambiguous`로 남기고 LLM에 둔다.

## 3. 전처리 규칙

입력은 이미 `compact`된 문자열이다. 마커는 지금과 같다.
`의견근거`, `재무제표에대한경`(「재무제표에 대한 경영진의 책임」에 포함).

```text
first_part =
  의견근거 앞,            의견근거가 있으면
  첫 재무제표에대한경 앞,  의견근거가 없고 재무제표에대한경이 있으면
  ""                      그 외

second_part =
  마지막 재무제표에대한경 뒤,  그 마커가 있으면
  ""                          그 외

결과 = first_part + second_part
       둘 다 비었으면 compact 본문 전체
```

본문을 두 번 이어 붙이지 않는다. `extract_date_candidates`는 이 결과에서만
`[0-9]{4}년[0-9]{1,2}월[0-9]{1,2}일`을 찾는다.

## 4. 코드 경계

| 단위 | 역할 |
|------|------|
| `_preprocess` | 위 규칙. docstring을 후행형 머리글까지 맞게 고친다 |
| `extract_date_candidates` | 호출부 불변. 전처리 결과가 달라져 후보가 늘 수 있다 |
| `pick_audit_report_date` | 불변 |
| `ExtractionService`·selector·완전성·UI | 불변 |
| `reparse` | 이미 `_has_not_found_field`로 대상 선정. 모드를 추가하지 않음 |

머리글 날짜는 기존 `audit_report_date_candidates` JSON에 없다. 본문 HTML도 DB에 없다.
재파싱은 `viewer_url`을 다시 GET해야 한다(공유 `DartHttpClient` 1초 간격).

## 5. 재실행

배포 후 운영자는 연구 창에 대해 기존 `reparse`를 한 번 돌린다.
`audit_report_date_status=not_found`인 문서는 다른 필드 `not_found`와 함께 다시 받는다.
이미 `ok`인 선행형·후행형은 건너뛴다. `ambiguous`는 이번 전처리로 고르지 않으므로
이 작업의 성공 조건이 아니다.

`patch`로 보고일 실패(not_found+ambiguous)를 묶지 않는다. 버전을 올려
fetch-ok 전체를 다시 받지 않는다.

## 6. 테스트

`test_extracting_dates.py`에 후행형 compact 한 건을 추가한다.

- 본문: `귀중2015년12월24일우리는…2015년10월31일…재무제표에대한경영진의책임…`
  (`의견근거` 없음, 보고일은 마커 앞, 당기말은 머리글에도 있음)
- 후보에 `2015-12-24`가 있다
- `period_end=2015-10-31`, `rcept_dt=2016-01-13`이면 status `ok`, ISO `2015-12-24`

기존 케이스는 그대로 통과해야 한다.

- 선행형: 중간(`의견근거`와 `재무제표에대한경` 사이) 날짜 제외
- 마커 없음·하나만 있어도 창 안 날짜 1개는 `ok`, 후보 중복 없음
- 창 0개 `not_found`, 창 2개 `ambiguous`이고 ISO `None`

Admin UI·완전성 SQL·`classify_outcome` 테스트는 추가하지 않는다.

## 7. 비범위

점 찍은 날짜(`2016. 3. 15`), `귀중` 직후 고정, 머리글 첫 날짜 우선,
`감사보고서일(` 우선, 후반 우선, LLM 해소 잡 변경, `EXTRACTOR_VERSION` 변경,
날짜 전용 reparse 모드, `patch` 대상 재정의, 창 경계 변경,
2026-08-28 스펙의 「문서 후반 우선」문장과 구현 불일치 정리.
