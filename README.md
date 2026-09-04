# dart-wrapper

DART 공시 소스를 **재가공해 제공**하기 위한 모노레포입니다.

원문 HTML/PDF는 장기 저장하지 않고, 추출한 **entry(메타·주소)** 를 저장한 뒤 필요할 때 소스를 가져와 변환·제공합니다.

## 기본 흐름

1. **수집** — Admin이 기간/유형으로 entry를 카탈로그에 저장  
   (목록은 정정 전·후 접수 모두, 첨부는 현재 접수 `rcpNo`만—타 접수는 해당 행에서 입수, TOC 중간 노드 포함)
2. **탐색** — Catalog HTML(/catalog)·Facts HTML(/facts) 또는 Public API로 공시·entry 표/JSON 조회
3. **열람** — Viewer API가 `viewer_url`로 원문을 Lazy Retrieval·정제 (JSON)
4. **감사 추출** — 카탈로그 주소로 감사인·의견·보고일·GAAP·당기를 `audit_report_facts`에 저장 (원문 HTML은 저장하지 않음)

## 구조

```text
dart-wrapper/
└── packages/
    ├── entry-extractor/   # 공시 컨테이너 → flat entry 추출 (Node)
    └── web-api/           # Admin 수집 + Catalog/Viewer API (FastAPI)
```

## 현재 모듈

| 패키지 | 역할 |
|--------|------|
| [`@dart-wrapper/entry-extractor`](./packages/entry-extractor) | 목록·목차 파싱 후 저장용 flat entry 생성 |
| [`web-api`](./packages/web-api) | 수집 트리거, Catalog/Viewer, 감사 표지·의견 추출 |

추출 정책(이력 목록·첨부 접수 스코프·`leafOnly` 등)은 [`packages/entry-extractor/README.md`](./packages/entry-extractor/README.md)를 보세요.  
API·Admin·감사 추출 규칙은 [`packages/web-api/README.md`](./packages/web-api/README.md)를 보세요.

## 설치

Node(entry-extractor)와 Python(web-api)을 각각 준비합니다.

```powershell
# 루트 — workspace 패키지
npm install

# web-api
cd packages/web-api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 실행

```powershell
# entry-extractor 예제 (모노레포 루트)
npm run example
npm run example:entries

# web-api — packages/web-api 로 이동한 뒤 실행
cd packages/web-api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

PowerShell에서는 `.venv\...`가 아니라 **`.\.venv\...`**(앞에 `.\`)로 써야 합니다.
venv는 루트가 아니라 `packages/web-api/.venv`에 있습니다.

- API 문서: http://127.0.0.1:8000/docs
- Admin 운영 화면: http://127.0.0.1:8000/admin  
  (처음 열면 `ADMIN_TOKEN` 입력 → 수집 시작·이어하기·슬라이스 완전성 확인)
- Catalog 탐색: http://127.0.0.1:8000/catalog  
  (공시 목록 → entry 전 컬럼 표·`is_leaf` 구분, 인증 없음)
- Facts 탐색: http://127.0.0.1:8000/facts  
  (추출된 감사 문서 1행 표, 인증 없음)

주요 Public 경로:

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/catalog/disclosures` | 공시 목록 (cursor) |
| GET | `/api/v1/facts` | 감사 추출 결과 목록 (cursor) |
| GET | `/api/v1/catalog/disclosures/{rcp_no}/entries` | entry 목록 (전 feature, `all_entries`) |
| GET | `/api/v1/disclosures/{rcp_no}/audit-facts` | 공시별 감사 추출 결과 |
| GET | `/api/v1/viewer/{rcp_no}` | 공시 전체 원문 정제 |
| GET | `/api/v1/viewer/{rcp_no}/sections/{entry_id}` | 섹션 단건 원문 정제 |

Admin API는 `X-Admin-Token`이 필요합니다. 재개·슬라이스 엔드포인트는 [`packages/web-api/README.md`](./packages/web-api/README.md)를 보세요.
