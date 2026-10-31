# dart-wrapper

DART 상세검색과 상세페이지 HTML을 스크래핑해 공시 카탈로그를 만들고, 조회할 때 원문을 정제해 보여주는 모노레포입니다.

저장소: https://github.com/ypspy/dart-wrapper  
라이선스: [MIT](./LICENSE)

원문 HTML은 저장하지 않습니다. 카탈로그에는 entry 메타데이터와 `viewer_url`만 둡니다. `.env`와 `packages/web-api/*.db`는 커밋하지 않습니다.

## 기본 흐름

1. **수집** — 로컬 Admin이 기간과 유형으로 entry를 카탈로그에 저장합니다. 목록은 정정 전·후 접수를 모두 담고, 첨부는 현재 접수 `rcpNo`만 담습니다. TOC 중간 노드를 포함합니다.
2. **카탈로그 탐색** — `/catalog` 또는 공개 API로 공시와 entry를 조회합니다.
3. **Viewer** — `viewer_url`로 원문을 가져와 정제된 JSON으로 돌려줍니다.

`packages/research`에는 감사 추출과 회사 업종 코드가 있습니다. 로컬 앱과 공개 앱은 이 코드를 실행하지 않습니다.

DART 원문 요청의 최소 간격은 프로세스 안이며 기본 1초입니다. 로컬 수집과 공개 열람은 시계를 공유하지 않습니다.

## 구조

```text
packages/
├── entry-extractor/   # 공시 컨테이너를 flat entry로 추출 (Node)
├── web-api/           # 로컬 수집, 카탈로그, Viewer (FastAPI)
└── research/          # 감사 추출·회사 업종. 기본 앱은 실행하지 않음
```

| 문서 | 내용 |
|------|------|
| [packages/entry-extractor/README.md](./packages/entry-extractor/README.md) | 수집 정책 |
| [packages/web-api/README.md](./packages/web-api/README.md) | API, Admin, Viewer |
| [PRD.md](./PRD.md) | 제품 범위 |
| [AGENTS.md](./AGENTS.md) | 에이전트 규칙 |
| [docs/paper/variable-measurement.md](./docs/paper/variable-measurement.md) | 논문용 측정 |
| [docs/superpowers/README.md](./docs/superpowers/README.md) | spec/plan 색인 |
| [docs/github-repo.md](./docs/github-repo.md) | GitHub 리포 런북 |

## 설치

```powershell
git clone https://github.com/ypspy/dart-wrapper.git
cd dart-wrapper
npm install

cd packages/web-api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

venv는 `packages/web-api/.venv`에 둡니다. PowerShell에서는 `.\.venv\...`처럼 앞에 `.\`를 붙입니다.

## 실행

로컬 앱은 `packages/web-api`에서 실행합니다. Admin은 `ADMIN_TOKEN`이 필요합니다.

```powershell
cd packages/web-api
.\.venv\Scripts\python.exe -m uvicorn app.local:app --reload
```

- API 문서: http://127.0.0.1:8000/docs
- 수집 화면: http://127.0.0.1:8000/admin
- 카탈로그: http://127.0.0.1:8000/catalog

공개 앱은 `DATABASE_URL`이 `postgresql+asyncpg://`로 시작해야 프로세스가 시작됩니다. `0.0.0.0:$PORT`에 바인딩합니다.

```bash
python -m uvicorn app.public:app --host 0.0.0.0 --port "$PORT"
```

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/catalog/disclosures` | 공시 목록 (cursor) |
| GET | `/api/v1/catalog/disclosures/{rcp_no}` | 공시 단건 |
| GET | `/api/v1/catalog/disclosures/{rcp_no}/entries` | entry 목록 |
| GET | `/api/v1/viewer/{rcp_no}` | 공시 전체 원문 정제 |
| GET | `/api/v1/viewer/{rcp_no}/sections/{entry_id}` | 섹션 단건 원문 정제 |

Admin API는 `X-Admin-Token`이 필요합니다. 재개·슬라이스·화면 규칙은 [packages/web-api/README.md](./packages/web-api/README.md)에 있습니다.

entry-extractor 예제는 모노레포 루트에서 실행합니다.

```powershell
npm run example
npm run example:entries
```
