# 추출 진단 Admin 검토 화면 설계

날짜: 2026-09-28  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` — Admin에서 진단을 실행하고, 기본 검토 집합의 한 건을 골라 원문과 대조한 뒤 판정을 저장한다.  
구현 계획이 아니라 **화면 자리·데이터 흐름·오류·테스트 경계**다. 후보 규칙은 바꾸지 않는다.

선행: [`2026-09-28-extraction-review-diagnosis-design.md`](2026-09-28-extraction-review-diagnosis-design.md).

## 1. 목표

진단 후보는 스크립트와 TSV로만 볼 수 있다. 이 스펙은 그 판정 작업을 Admin 화면으로 옮긴다.

성공 기준:

- `/admin/reviews`에서 진단을 실행하고 한글 요약을 본다.
- 왼쪽 목록은 기본 TSV와 같은 활성 행이고, 오른쪽은 고른 한 건의 원문 링크와 판정 폼이다.
- 저장은 `verdict`, `tag`, `note`만 바꾼다.
- 추출 잡이 진행 중이거나 현재 추출기 ok 행이 없으면 진단을 시작하지 않고, 기존 검토 행을 끄지 않는다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 자리 | 기존 Admin. 메뉴 **검토**, 경로 `/admin/reviews` |
| 인증 | 다른 Admin HTML과 같은 토큰 쿠키. 없으면 `/admin/token` |
| 화면 | 기존 Admin과 같은 서버 HTML. 행 선택과 저장은 htmx로 오른쪽·해당 행만 바꾼다 |
| 진단 | 기존 `diagnose`. 성공 시 그 요청이 commit |
| 목록 | `export_tsv(..., next_slice=False)`와 같은 포함 규칙. 한곳에서 공유 |
| 원문 | 새 탭의 DART 문서 주소. 이 앱 안에 넣지 않고, 서버가 DART를 호출하지 않음 |
| 다음 구간·facts `source_tags` | 기존 스크립트. 이 화면에 없음 |
| 파서·카탈로그·facts | 읽기만. `EXTRACTOR_VERSION`과 후보 규칙은 유지 |

포함 규칙은 금지 신호 전부, IQR 순번 1–5, `rare_code`·`auditor_invalid`·`fail` 대표다. `active=false`와 순번 6 이상 IQR은 목록에 없고 이 화면에서 저장하지 않는다.

## 3. 화면

위는 진단 버튼과 요약이다. 아래는 두 칸이다.

왼쪽 행에는 연구 패널 여부, 묶음, 신호, 층, 순번, 판정이 보인다. 정렬은 다음 순서다.

1. `in_research_panel`이 참인 행
2. `queue_order`가 있는 행, 그다음 없는 행
3. `queue_order` 오름차순
4. `stratum`, `signal`, `rcept_no`, `dcm_no`

한 페이지는 50건이다. `page`는 1부터다. 1보다 작으면 1로 보고, 마지막 페이지를 넘으면 빈 목록이다. `bundle`과 `verdict` 쿼리가 비어 있으면 전체를 보여주고, 값이 있으면 그 값으로 기본 집합을 줄인 뒤 페이지를 자른다. `verdict` 필터는 `hold`, `source`, `logic`만 인정한다. 그 밖은 필터 없음으로 본다. `bundle` 필터는 `field_bundles.BUNDLE_KEYS`만 인정하고, 그 밖은 필터 없음으로 본다.

오른쪽은 쿼리에 자연키 다섯 필드가 있고 그 행이 기본 집합에 있을 때만 채운다. 현재 페이지 밖이어도 기본 집합 안이면 연다. 보여줄 내용은 자연키, 연구 패널 여부, 층, 꼬리, 순번, `raw_value`, 추출기 버전, 새 탭 원문 링크, 판정 폼이다. 원문 링크는 기본 내보내기와 같은 `DART_DOCUMENT_VIEW`이고 `target="_blank"`다. 키가 없으면 `왼쪽에서 한 건을 고르세요.`만 있다. 키가 있지만 기본 집합에 없으면 행을 열지 않고 `이 행은 기본 검토 목록에 없습니다.`만 있다.

행을 고르면 오른쪽만 바꾸고 주소에는 자연키를 남긴다. 필터와 페이지도 주소에 남는다. 진단과 저장 뒤에도 그 쿼리를 유지한다.

판정 폼의 `verdict`는 `hold`, `source`, `logic` 중 하나다. `tag`는 빈 값 또는 `as_written`, `real_magnitude`, `rare_but_valid`, `other`다. `note`는 여러 줄이다. 진단이 앞에 붙인 `이전 판정=...` 줄바꿈을 그대로 보여 주고, 저장할 때도 그 줄바꿈을 유지한다. 빈 태그와 빈 메모는 빈 문자열로 저장한다. TSV import에서 빈 칸이 기존 값을 유지하는 규칙과 다르다. 화면에서는 지금 보이는 세 값이 저장할 값이다.

## 4. 데이터 흐름

`GET /admin/reviews`는 검토 행만 읽는다. 요약을 다시 계산하지 않는다. 요약이 없는 조회는 `진단을 실행하면 요약이 나옵니다.`라고 안내한다.

`POST /admin/reviews/diagnose`는 `diagnose`를 호출한다. 성공하면 commit하고, 돌아온 요약 전체를 페이지 위에 그린다. 요약은 테이블에 저장하지 않는다. 이후 GET은 목록만 읽는다. 이 POST 응답을 브라우저가 새로고침하면 진단이 다시 실행될 수 있다. 그때 `raw_value`가 같으면 기존 판정·태그·메모는 유지된다.

`POST /admin/reviews/verdict`는 자연키로 활성 기본 집합 안의 행을 찾아 `verdict`, `tag`, `note`만 갱신하고 commit한다. 성공 응답은 오른쪽 폼과 왼쪽 그 행의 판정 표시를 함께 갱신한다. 다른 열은 그대로다.

진단이 만드는 upsert, 패널 재계산, 값 변경 시 `hold` 되돌림은 선행 스펙의 `diagnose`를 그대로 쓴다. 이 화면은 그 규칙을 다시 구현하지 않는다.

## 5. 오류

토큰 쿠키가 없으면 `/admin/token`으로 보낸다.

진단이 `ExtractionReviewError`를 던지면 그 메시지를 페이지에 보이고 검토 행은 그 호출이 바꾸지 않은 상태로 둔다. 선행 스펙의 문구를 유지한다.

- 추출 잡이 `pending` 또는 `running`: `추출 잡이 진행 중이라 진단을 시작하지 않습니다.`
- 현재 추출기 ok 행이 0: `현재 추출기 ok 행이 없습니다.` 기존 `active`를 끄지 않는다.

판정 저장은 실패하면 그 행을 바꾸지 않고 폼에 이유를 보인다.

- 자연키가 없거나, 비활성이거나, 기본 집합 밖: `해당하는 검토 행이 없습니다.`
- `verdict`가 `hold`, `source`, `logic`이 아님: `판정은 hold, source, logic만 적을 수 있습니다.`
- `tag`가 빈 문자열이 아니고 허용 네 값도 아님: `태그는 as_written, real_magnitude, rare_but_valid, other만 적을 수 있습니다.`
- `verdict`가 `logic` 또는 `hold`인데 `tag`가 비어 있지 않음: `logic 또는 hold 판정에는 태그를 적을 수 없습니다.`

`source`이면서 태그가 빈 것은 허용한다. 폼은 `-`를 보내지 않는다. TSV의 `-`는 이 화면의 규칙이 아니다.

## 6. 구성

- `app/api/admin/reviews.py` — 조회, 진단, 판정 라우트. `app/main.py`에 등록
- `app/templates/admin/base.html` — 수집·추출 옆 검토 링크
- `app/templates/admin/reviews.html`와 목록·상세 partial
- `app/services/extraction_review_service.py` — 기본 집합 조회와 폼 판정 저장. 포함 규칙은 기본 내보내기와 공유

카탈로그 테이블과 `audit_report_facts`에 쓰는 코드는 없다. 원문 HTML은 저장하지 않는다.

## 7. 테스트

기존 Admin 화면 테스트와 같이 앱 클라이언트와 SQLite 메모리 DB를 쓴다. DART는 호출하지 않는다.

- 토큰이 없으면 `/admin/token`으로 간다.
- 목록에는 순번 6 IQR이 없고 금지 값은 있다. 연구 패널이 먼저다. 한 페이지는 50건이다. 묶음·판정 필터가 그 집합을 줄인다.
- 자연키가 없으면 오른쪽은 `왼쪽에서 한 건을 고르세요.`만 있다. 기본 집합의 키를 주면 값, 새 탭 원문 링크, 판정 폼이 나온다. 기본 집합 밖 키는 `이 행은 기본 검토 목록에 없습니다.`만 보이고 저장되지 않는다.
- 진행 중 추출 잡과 ok 행 0건은 각 문구를 보이고 검토 행을 그대로 둔다.
- 진단 성공은 commit되고 한글 요약이 페이지에 있다.
- 판정 저장은 세 열만 바꾼다. 빈 태그는 빈 문자열이다. 거부 네 경우는 행을 바꾸지 않고 이유를 보인다.
- `audit_report_facts`와 카탈로그 행은 이 요청들 전후로 같다.

파서, `export-tsv --next`, facts `--with-reviews`는 이 테스트에 넣지 않는다.

## 8. 범위 밖

- 다음 5건 구간, facts 소스 태그 내보내기, TSV 화면
- 후보 규칙, 연구 패널 규칙, `EXTRACTOR_VERSION` 변경
- 요약의 DB 저장, 진단의 진행률, DART 페이지를 이 화면에 넣기
- 파서 수정
