# 감사보고서일 전수 후보·인증일 일치 설계

날짜: 2026-09-18  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` — 의견 본문 날짜 후보 추출·선택 규칙,
`EXTRACTOR_VERSION`, 날짜 LLM 잡의 `limit`과 창 오른쪽 끝(인증일).  
facts 스키마·selector·의견/GAAP·완전성 SQL·Admin 추출 화면은 바꾸지 않는다.

선행: [감사의견 추출](2026-08-28-audit-opinion-extraction-design.md) §6.2 날짜(D-3-3).  
이 스펙이 그 절의 **구간 전처리**와 **창 안 1개면 ok**를 덮어쓴다.  
[후행형 머리글 전처리](2026-09-18-audit-report-date-header-preprocess-design.md)는
이 문서로 **대체**한다. 구현하지 않는다.

원전(인증일): 금융감독원 「전자문서제출요령」(2025.9.30. 시행) 제3장.
전송파일(`*.DRT`) 생성의 마지막 단계가 인증서 전자서명이다. 실무상
접수번호 `rcept_no` 앞 8자리(`YYYYMMDD`)가 그 인증일이다.
목록 칸 `rcept_dt`(접수·공시일)와 우리 카탈로그 입수일이 아니다.

## 1. 목표

구간을 잘라 후보를 줄이지 않는다. compact 본문의 날짜를 형식 변칙까지
모아 두고, **인증일과 같은 날만** 규칙으로 확정한다. 나머지는 추출 후
운영자가 검토한 뒤에만 LLM 큐를 넣는다.

성공 기준:

- `_preprocess`가 없다. `의견근거`와 `재무제표에대한경` 사이 날짜도 후보다.
- `2016.01.22`, `2016-01-22`, `2016/1/22`, `2016年1月22日`, 전각 숫자가
  후보 ISO가 된다. 한자 숫자(`二〇一六…`)는 후보가 아니다.
- `rcept_no=20160122000020`이고 후보에 `2016-01-22`가 있으면 status `ok`,
  source `letter`. 목록 `rcept_dt`가 다음날이어도 같다.
- 후보가 있는데 인증일과 다르면 `ambiguous`, ISO `None`. 추출 잡은 LLM을
  호출하지 않는다.
- `POST /admin/extract/resolve-dates`는 키가 있고 운영자가 누를 때만 돈다.
  `limit`이 있으면 그 건수에서 멈춘다.
- `EXTRACTOR_VERSION`은 `audit_opinion.v18`이다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 패키지 | `packages/web-api` |
| 인증일 | `rcept_no` 앞 8자리 → `date`. 형식이 아니거나 달력이 아니면 없음 |
| 규칙 확정 | 후보 ISO == 인증일 이고 `period_end < 인증일` |
| `rcept_dt` | 선택·창·LLM 프롬프트에 쓰지 않음 |
| 구간 전처리 | 삭제. compact 전체에서 찾음 |
| 창 | LLM이 고른 인덱스를 저장하기 **전**에만. `period_end < iso ≤ 인증일` |
| 0·일치·불일치 | `not_found` / `ok` / `ambiguous`(ISO `None`) |
| 후반·머리글 우선 | 없음 |
| 추출 중 LLM | 없음. API 키가 있어도 추출은 규칙만 |
| 해소 큐 | 기존 `POST /admin/extract/resolve-dates`. `ambiguous`만. `not_found` 제외 |
| LLM 출력 | 지금과 같음. 후보 인덱스. 본문에서 새 ISO를 만들지 않음 |
| 키 | `DATE_RESOLVER_API_KEY` 비면 해소 POST 400. 추출은 됨 |
| 한도 | 해소 POST body `limit`(양의 정수). 생략 시 대기 `ambiguous` 전량 |
| 수동 | 기존 `PATCH .../date` override |
| 재추출 보존 | override·기존 `llm` 값은 지금 `_copy_operator_fields`와 같음 |
| 스키마 | `audit_report_date_*` 컬럼 추가 없음 |
| 버전 | `audit_opinion.v18` |

18:00 이후 제출은 접수가 다음 업무일일 수 있다(요령 제1장 접수시간).
규칙 비교는 접수일이 아니라 인증일이다.

## 3. 후보 추출

입력은 의견 leaf HTML을 `get_text`한 문자열이다.

1. `unicodedata.normalize("NFKC", text)`로 전각 숫자를 ASCII에 접는다.
2. `compact()`로 공백을 모두 지운다.
3. 아래를 **한 정규식 대안**으로 등장 순으로 찾는다. 대안 순서는 표와 같다
   (`년월일`이 `.`/`-`/`/`보다 앞). 이미 매칭한 구간은 다시 쓰지 않는다.

| 패턴 | 예 | ISO |
|------|----|-----|
| `[0-9]{4}년[0-9]{1,2}월[0-9]{1,2}일` | `2016년1월22일` | `2016-01-22` |
| `[0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日` | `2016年1月22日` | `2016-01-22` |
| `[0-9]{4}[.][0-9]{1,2}[.][0-9]{1,2}` | `2016.01.22`, compact된 `2016.1.22` | `2016-01-22` |
| `[0-9]{4}[-][0-9]{1,2}[-][0-9]{1,2}` | `2016-01-22` | `2016-01-22` |
| `[0-9]{4}[/][0-9]{1,2}[/][0-9]{1,2}` | `2016/1/22` | `2016-01-22` |

달력에 없는 값(13월, 2월 30일)은 후보에 넣지 않는다.  
한자 숫자, `2016.12`(일 없음), `20160122` 숫자 덩어리는 이번 밖이다.

snippet은 지금과 같다. NFKC·compact **이전 원문**에서 해당 날짜 전후 40자.
원문에 점·공백이 있으면 그 형태를 남긴다.

`audit_report_date_candidates`는 전 구간 매칭을 `{date, snippet}`로 저장한다.
`audit_report_date_raw`는 후보 원문을 공백으로 잇는다.

`_preprocess`와 마커 상수 `의견근거`·`재무제표에대한경`는 날짜 모듈에서 제거한다.

## 4. 선택 규칙

`parse_auth_date(rcept_no: str | None) -> date | None`  
앞 8자가 `YYYYMMDD` 달력이면 그 날, 아니면 `None`.

`pick_audit_report_date(candidates, *, period_end, auth_date)`:

1. `auth_date`가 없고 후보가 있으면 `ambiguous`, 없으면 `not_found`.
2. `period_end`가 있고 `not (period_end < auth_date)`이면 일치를 인정하지 않는다.
   후보가 있으면 `ambiguous`, 없으면 `not_found`.
3. 후보 ISO 중 `auth_date`와 같은 것이 있으면 `ok`, 그 ISO, passing은 그 날들.
4. 후보가 있는데 3이 아니면 `ambiguous`, ISO `None`.
5. 후보가 없으면 `not_found`.

창 안 개수로 `ok`를 만들지 않는다. 인증일과 다른 창 안 날짜가 하나여도
`ambiguous`다.

`ExtractionService._build_fact`는 `parse_rcept_dt(sample.rcept_dt)` 대신
`parse_auth_date(sample.rcept_no)`를 `pick_audit_report_date`에 넘긴다.

## 5. 운영 큐 (LLM)

추출이 끝난 뒤 운영자가 완전성 `ambiguous_dates`를 보고, 일부는 PATCH로
고친 다음, 해소할 만큼만 잡을 시작한다.

```text
추출 잡 (규칙만)
  → ambiguous / not_found 로 남김
운영자 검토
  → PATCH 수동 보정 또는
  → POST /admin/extract/resolve-dates { "limit": N }
```

- 추출 잡·`resume`·`reparse`는 `DateResolver`를 호출하지 않는다.
- `not_found`는 해소 잡 대상이 아니다.
- `limit` 생략: 지금처럼 `list_ambiguous_dates()` 전량.
- `limit` 있음: 양의 정수만. 0·음수·소수 → 400. `list_ambiguous_dates()`
  정렬(`rcept_no`, `dcm_no`)의 앞에서 N건만 `_resolve_one`.
- 창 검증·프롬프트의 오른쪽 끝은 인증일(`rcept_no` 앞 8자리).
  `rcept_dt`를 넘기지 않는다. 후보는 저장 JSON, 출력은 `{"index": n|null}`.
- 고른 ISO가 `period_end < iso ≤ 인증일`이 아니면 행을 바꾸지 않는다.

프롬프트 `v1` 문구의 「접수일(rcept_dt)」은 「인증일」로 바꾼다.
`DATE_RESOLVER_PROMPT_VERSION` 키는 유지하고, 구현에서 쓰는 문자열만 고친다.
본문을 첨부하거나 새 날짜를 만들게 하지 않는다.

## 6. 코드 경계

| 단위 | 역할 |
|------|------|
| `app/extracting/dates.py` | `_preprocess` 삭제. 패턴·NFKC·`parse_auth_date`·`pick` 규칙 |
| `app/extracting/constants.py` | `audit_opinion.v18` |
| `ExtractionService._build_fact` | `auth_date`를 pick에 전달 |
| `DateResolverService` | `start`/`run`이 `limit`을 받고, 창에 인증일 |
| `LlmDateResolver` | 프롬프트 키 이름은 `auth_date`(또는 동등). 접수일 키 제거 |
| Admin `POST /resolve-dates` | optional body `{limit?: int}` |
| `test_extracting_dates.py` | 전수 후보·변칙 형식·인증일 일치 |
| `test_date_resolver.py` | `limit`, 인증일 창 |
| `test_audit_report_fact_repository.py` | 버전 문자열 `v18` |

selector, `classify_opinion`, 완전성 SQL, Admin 추출 HTML, field-bundles는
호출부가 바뀌지 않으면 테스트만 버전 픽스처를 맞춘다.

## 7. 재실행

버전을 올리므로 `extract`/`resume`는 기존 `fetch_status=ok` 행도 다시 GET한다.
연구 창 한 번의 `extract`가 배포 후 운영이다. 날짜 전용 reparse 모드는 없다.

override가 있는 행은 다시 받아도 보고일은 override가 이긴다.

## 8. 테스트

live DART·live LLM 없음.

`test_extracting_dates.py`:

- 선행형 본문에서 `의견근거`와 `재무제표에대한경` **사이** 날짜가 후보다.
- 후행형 머리글 `2015년12월24일`이 후보다. 인증일이 `2015-12-24`면 `ok`.
  인증일이 `2016-01-13`이고 후보에 그 날이 없으면 `ambiguous`(창 안 1개여도).
- `2016.01.22` / `2016-01-22` / `2016/1/22` / `2016年1月22日` / 전각
  `２０１６년１월２２일` → ISO `2016-01-22`.
- 한자 숫자만 있는 본문은 후보 0, `not_found`.
- `rcept_no` 앞자리가 인증일. `rcept_dt`를 pick에 넣지 않는 픽스처.

`test_date_resolver.py`:

- `limit=1`이면 ambiguous 2건 중 1건만 `llm`.
- LLM이 고른 ISO가 인증일 창 밖이면 행 유지.
- 요청 body 없이 키 있으면 202 (전량, 기존과 같음).
- `limit=0`은 400.

기존 창 1개=`ok` 테스트는 인증일 일치 픽스처로 바꾼다.

## 9. 비범위

한자 숫자 변환, `not_found`를 해소 잡에 넣기, 의견 본문을 LLM에 첨부하기,
LLM이 새 ISO를 만들기, 후반·머리글·`귀중` 직후 우선, `rcept_dt`로 일치,
날짜 전용 reparse/`patch` 재정의, Admin 해소 UI, 비용 견적 화면,
2026-08-28 스펙의 「문서 후반 우선」문장 정리(구현은 계속 없음).
