# dart-wrapper

DART 공시 소스를 **재가공해 제공**하기 위한 모노레포입니다.

원문 HTML/PDF는 장기 저장하지 않고, 추출한 **entry(메타·주소)** 를 저장한 뒤 필요할 때 소스를 가져와 변환·제공합니다.

## 기본 흐름

1. **수집** — Admin이 기간/유형으로 leaf entry를 카탈로그에 저장
2. **탐색** — Public 카탈로그에서 공시 목록 → leaf 목차(`primary` / 전체) 선택
3. **열람** — Viewer가 `viewer_url`로 원문을 Lazy Retrieval·정제

## 구조

```text
dart-wrapper/
└── packages/
    ├── entry-extractor/   # 공시 컨테이너 → 구성 문서 leaf entry 추출 (Node)
    └── web-api/           # Admin 수집 + 카탈로그 조회 + Public Viewer (FastAPI)
```

## 현재 모듈


| 패키지 | 역할 |
|--------|------|
| [`@dart-wrapper/entry-extractor`](./packages/entry-extractor) | 목록·목차 파싱 후 저장용 flat entry 생성 |
| [`web-api`](./packages/web-api) | 수집 트리거, 공시/목차 조회, Viewer 원문 정제 API |

자세한 API·설정은 [`packages/web-api/README.md`](./packages/web-api/README.md)를 보세요.

## 설치

Node(entry-extractor)와 Python(web-api)을 각각 준비합니다.

```bash
# 루트 — workspace 패키지
npm install

# web-api
cd packages/web-api
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 실행

```bash
# entry-extractor 예제
npm run example
npm run example:entries

# web-api (packages/web-api에서)
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

- API 문서: http://127.0.0.1:8000/docs
- Admin 운영 화면: http://127.0.0.1:8000/admin  
  (처음 열면 `ADMIN_TOKEN` 입력 → 수집 시작·이어하기·슬라이스 완전성 확인)
- Public 탐색·열람 화면: http://127.0.0.1:8000/browse  
  (공시 목록 → 목차 | 본문 2열, 인증 없음)

주요 Public 경로:

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/catalog/disclosures` | 공시 목록 (cursor) |
| GET | `/api/v1/catalog/disclosures/{rcp_no}/entries` | leaf 목차 (primary + all) |
| GET | `/api/v1/viewer/{rcp_no}` | 공시 전체 원문 정제 |
| GET | `/api/v1/viewer/{rcp_no}/sections/{entry_id}` | 섹션 단건 원문 정제 |

Admin API는 `X-Admin-Token`이 필요합니다. 재개·슬라이스 엔드포인트는 [`packages/web-api/README.md`](./packages/web-api/README.md)를 보세요.
