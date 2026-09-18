# dart-wrapper PRD

DART 상세검색·상세페이지 HTML을 스크래핑하여 공시 메타데이터 카탈로그를 만들고, 조회 시 `viewer_url`로 원문을 정제하며, 감사 문서에서 연구용 facts를 뽑는 Web App이다. 구현은 `@dart-wrapper/entry-extractor`와 FastAPI `packages/web-api`이다.

엔드포인트·추출 규칙의 세부는 [`packages/web-api/README.md`](packages/web-api/README.md)와 [`packages/entry-extractor/README.md`](packages/entry-extractor/README.md)가 진실의 원천이다.

## 기능

1. **카탈로그 수집** — 기간·유형으로 flat entry를 저장한다. 기본은 정정 전·후 접수 모두, 첨부는 현재 접수 `rcpNo`만, TOC 중간 노드 포함(`leafOnly: false`). 하루 슬라이스·재개·히트맵.
2. **탐색** — Catalog HTML(`/catalog`), Facts HTML(`/facts`), Public JSON API.
3. **Viewer** — Lazy Retrieval. `GET /api/v1/viewer/{rcp_no}`, `GET /api/v1/viewer/{rcp_no}/sections/{entry_id}`. 응답은 `blocks`(heading/paragraph/table).
4. **감사 추출** — F001·F002와 A001 첨부 감사·연결감사. 12묶음, 완전성, 모드 `extract`/`resume`/`reparse`/`patch`.
5. **회사 업종** — OpenDART 기업개황만. KSIC 이름은 11차 표에 코드가 있으면 11차만, 없으면 10차.

공시 목록·본문 HTML은 OpenDART를 쓰지 않는다.

## 스택

FastAPI, Pydantic v2, httpx, BeautifulSoup4, pandas. 수집 CLI는 Node `@dart-wrapper/entry-extractor`.
