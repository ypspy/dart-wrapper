# Public 탐색·열람 UI와 Viewer 블록 정제 설계

날짜: 2026-07-26  
상태: 승인 (구현 완료)  
범위: `packages/web-api` — 본문 블록 파서, Viewer JSON 확장, Public Browse HTMX UI

## 1. 배경과 목표

Admin 수집은 검증되었고, 카탈로그(`disclosures`/`entries`)와 Viewer Lazy Retrieval API는
이미 동작한다. 다만 (1) Public에서 공시를 찾고 섹션을 읽는 UI가 없고, (2) 본문 정제는
페이지 전체 `get_text`라 표·문단 구조가 없고 `text`와 `tables[]`에 표 내용이 중복된다.

이번 스펙의 목표는 두 축을 한 번에 닫는 것이다.

1. **열람 품질** — 문서 순서의 `blocks[]`(`heading` | `paragraph` | `table`)로 정제
2. **탐색·열람 UI** — 공시 목록 → 목차|본문 2열 Browse (검증용으로 시작, Public 확장 가능)

제품 흐름(README)과 맞춘다.

```text
수집(Admin, 완료) → 탐색(Browse 목록·목차) → 열람(섹션 blocks / Viewer API)
```

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 1차 사용자 | 운영자 검증 + Public으로 확장 가능한 구조 |
| 품질 우선순위 | 본문 정제(구조화). 표 고도화·캐시·allowlist 확장은 후속 |
| 출력 형태 | 문서 순서 `blocks[]`. 기존 `text`/`tables`는 하위호환 유지 |
| UI 스택 | FastAPI + Jinja + HTMX (Admin과 동일 계열, 템플릿·CSS 분리) |
| 아키텍처 | 서비스 직결 3경로. 브라우저가 Public JSON API를 호출하지 않음 |
| 상세 레이아웃 | 목록 단독 페이지 + 공시 안 목차\|본문 2열 |
| 전체 leaf 일괄 UI | 없음. Agent/종합은 기존 `GET /api/v1/viewer/{rcp_no}` JSON 사용 |
| 인증 | Browse는 Public(인증 없음). Admin과 경로·템플릿 분리 |
| 캐시 | Redis 등 응답 캐시 없음 (범위 밖) |

## 3. 아키텍처

```text
[Browse UI]                              [Public JSON API — 동일 파이프라인]
GET /browse                              GET /api/v1/catalog/disclosures
  → CatalogQueryService
GET /browse/{rcp_no}                     GET .../disclosures/{rcp_no}/entries
  → 목차 + (선택 시) 본문 패널
GET /browse/{rcp_no}/sections/{entry_id}
  → ViewerService → DartHttp → extract_blocks → HTML(partial 또는 전체 페이지)
GET /api/v1/viewer/{rcp_no}/sections/{entry_id}  → 동일 파이프라인, JSON(+blocks)
GET /api/v1/viewer/{rcp_no}                      → 각 section에 blocks
```

### 3.1 디렉터리 추가·변경

```text
packages/web-api/app/
├── api/
│   ├── browse/
│   │   └── ui.py              # Public Browse 라우터
│   └── v1/
│       └── viewer.py          # SectionContent에 blocks 반영 (기존)
├── parsing/
│   ├── blocks.py              # extract_blocks (신규, 단일 순회)
│   ├── cleaner.py             # blocks에서 text 유도 또는 얇은 래퍼
│   └── tables.py              # table 블록 파싱 헬퍼 재사용
├── schemas/
│   └── viewer.py              # Block 모델, SectionContent.blocks
├── templates/
│   └── browse/                # Admin templates와 분리
│       ├── base.html
│       ├── list.html
│       ├── disclosure.html    # 2열 셸
│       └── partials/
│           ├── toc.html
│           ├── section.html
│           └── section_error.html
└── static/
    └── browse.css             # Admin과 분리. 공용 토큰만 공유 가능
```

### 3.2 주요 단위 책임

| 단위 | 역할 | 의존 |
|------|------|------|
| `extract_blocks` | HTML → 순서 보존 블록 목록 | BeautifulSoup/lxml |
| `ViewerService` | Lazy Retrieval + blocks/`text`/`tables` 조립 | EntryRepository, DartHttp, blocks |
| `CatalogQueryService` | 목록·목차 (변경 최소) | Disclosure/Entry repos |
| Browse UI 라우터 | HTML 렌더, HTMX partial | 위 두 서비스 |

## 4. 블록 스키마와 정제 규칙

### 4.1 Block 타입

```json
[
  {"type": "heading", "level": 2, "text": "재무상태표"},
  {"type": "paragraph", "text": "..."},
  {"type": "table", "headers": ["과목", "당기"], "rows": [["자산", "100"]]}
]
```

- `heading.level`: 1–3. `h1`→1, `h2`→2, `h3` 이상은 3
- `paragraph.text`: 공백 정규화, 빈 줄 제거
- `table`: 현재 `extract_tables`와 동일 수준(병합셀 고도화 없음)

### 4.2 추출 규칙

1. `script` / `style` / 주석 / `noscript` / `iframe` / `link` / `meta` 제거
2. `body`(없으면 루트)를 **문서 순서**로 한 번 순회
3. `h1`–`h6`(및 뚜렷한 제목성 노드) → `heading`
4. `table` → `table` 블록. 표 안 텍스트는 `paragraph`로 넣지 않음
5. 그 외 텍스트 덩어리 → `paragraph`. 이미 heading/table에 소비한 노드는 중복 수집하지 않음
6. DART 레이아웃 찌꺼기(빈 표, 네비성 링크만 있는 줄 등)는 **보수적** 휴리스틱으로 drop
   (본문 손실을 우선 피한다)

### 4.3 Viewer 응답 하위호환

`SectionContent`에 `blocks`를 추가한다.

- `text`: blocks 중 `paragraph`(및 선택적으로 heading)만 이어 붙인 문자열. **표 텍스트 제외**
- `tables`: blocks 중 `type=table`만 기존 `{headers, rows}` 목록으로
- 전체 공시 조회의 각 section에도 동일 필드

파서는 `extract_blocks` 한 번으로 `blocks`/`text`/`tables`를 모두 만든다.
`cleaner.extract_text` / `tables.extract_tables`는 래퍼로 유지하거나 blocks 유도로 교체한다.

## 5. Browse UI

### 5.1 라우트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/browse` | 공시 목록 + 필터 + cursor |
| GET | `/browse/{rcp_no}` | 2열: 왼쪽 목차, 오른쪽 본문(또는 안내) |
| GET | `/browse/{rcp_no}/sections/{entry_id}` | HTMX면 본문 partial, 직접 접근이면 전체 페이지 |

서버가 `CatalogQueryService` / `ViewerService`를 직접 호출한다.
브라우저가 `/api/v1/...`를 호출하지 않는다.

### 5.2 목록 (`/browse`)

쿼리: 기존 catalog와 동일 — `corp_code`, `corp_name`, `report_nm`, `report_type`,
`start_date`, `end_date`, `limit`, `cursor`.

- 행: `rcept_dt`, `corp_name`, `report_nm`, `report_type`, `entry_count`, DART `disclosure_url`
- 총건수 없음. **다음** 버튼 + `next_cursor`. cursor는 쿼리스트링에 유지해 뒤로가기 가능
- `report_type`은 셀렉트/칩. 표시명은 기존 `report_types` 헬퍼 재사용 가능

### 5.3 공시 상세 2열 (`/browse/{rcp_no}`)

- 상단: 회사명, 보고서명, 접수일, ← 목록, DART 원문 링크
- 왼쪽 목차: 기본 `primary_entries`. **전체 보기**로 `all_entries` 토글(추가 API 호출 없음).
  primary가 비면 처음부터 `all_entries`를 연다
- 항목 클릭: HTMX로 오른쪽 패널만 교체, `hx-push-url`로
  `/browse/{rcp_no}/sections/{entry_id}` 반영
- 오른쪽: 섹션 헤더(`path` 브레드크럼, document/section 이름, DART viewer 링크) +
  blocks 렌더 (`heading`→h2/h3, `paragraph`→p, `table`→HTML table)
- 초기 진입: 안내 문구, 또는 첫 primary(없으면 첫 all) 자동 로드 — 구현 시 하나로 고정.
  **기본은 첫 primary 자동 로드, primary 없으면 안내만**

### 5.4 로딩·에러 UI

- Lazy Retrieval 지연: HTMX `hx-indicator` 스켈레톤
- 섹션 fetch/파싱 실패: 페이지 전체 오류가 아니라 **패널 안 오류 카드**
  (한국어 원인, 다시 시도, DART 원문 링크)
- 없는 `rcp_no` / `entry_id`: 친절한 한국어 404 페이지
- 손상 cursor: 목록에 안내 후 첫 페이지로

### 5.5 템플릿·스타일

- `templates/browse/` · `static/browse.css` — Admin과 섞지 않음
- Admin에서 쓰는 색·간격 토큰만 공용으로 뽑아도 됨 (선택)
- `/browse/{rcp_no}?all=1` 전 섹션 한 페이지 UI는 **만들지 않음**

## 6. 에러 처리 (API)

기존 Viewer/Catalog 계약을 유지한다.

| 상황 | 응답 |
|------|------|
| 카탈로그에 `rcp_no` 없음 | `404` |
| `entry_id`가 해당 `rcp_no`에 속하지 않음 | `404` |
| 단일 섹션 fetch/파싱 실패 | `502` (+ Browse는 패널 오류 카드) |
| 전체 조회 일부 leaf 실패 | `200` + 해당 section `error` |
| 전체 조회 모든 leaf 실패 | `502` |
| 손상 cursor | `400` 한국어 메시지 |

## 7. 성능·동시성

- UI는 **섹션 단건** Lazy Retrieval만 사용
- Viewer 전체 leaf 병렬 fetch는 API 전용 (기존 semaphore 기본 4)
- 응답 캐시 없음
- 목차는 페이지 로드 시 1회, 이후 섹션만 HTMX 교체

## 8. 테스트 범위

실제 DART 호출 없이 픽스처·인메모리 SQLite·MockTransport로 검증한다.

- **`test_blocks.py`** — 순서 보존, heading/paragraph/table 분리, 표 텍스트가 paragraph에
  미포함, noise 태그 제거, 보수적 drop이 본문을 지우지 않음
- **Viewer API** — `blocks` 존재, `text`에 표 미포함, `tables` ≡ table blocks, 기존 404/502
- **Browse UI** — 목록 필터·cursor, 2열 목차 primary/전체 토글, 섹션 partial 200,
  없는 공시 404, 본문 실패 시 오류 패널
- 기존 catalog/viewer 테스트는 `blocks` 추가로 깨지지 않게 갱신

## 9. 범위 밖

- 표 병합셀·단위·다단 헤더 고도화
- Viewer/Browse 응답 Redis 캐시
- F001 외 primary allowlist 확장 (상수 추가만으로 후속 가능)
- SPA / 별도 프론트 빌드
- Browse에서 공시 전체 leaf 일괄 렌더
- Admin Ops Console 변경
- Alembic, 검색엔진, 전역 leaf 목록

## 10. 성공 기준

1. `/browse`에서 DB에 있는 공시를 필터·cursor로 찾을 수 있다.
2. `/browse/{rcp_no}`에서 primary 목차 → 섹션 본문(블록 렌더)이 2열로 동작한다.
3. Viewer JSON에 `blocks`가 있고, 하위호환 `text`/`tables`가 동작한다.
4. 표 내용이 `text`에 중복되지 않는다.
5. 주석·Docstring·로그·UI/예외 메시지는 한국어다.
