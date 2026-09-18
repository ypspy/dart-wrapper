# 살아 있는 문서 정렬과 GitHub 공개 리포 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 워킹 트리의 미커밋 기능을 영역별로 커밋한 뒤, 살아 있는 문서를 `audit_opinion.v19` 코드에 맞추고, 개인 GitHub 계정에 공개 리포 `dart-wrapper`를 `master`로 푸시한다.

**Architecture:** 이력 spec/plan 본문은 수정하지 않고 색인만 추가한다. 운영 세부는 패키지 README가 진실의 원천이고, 루트 README는 공개 랜딩이다. GitHub는 `docs/github-repo.md`를 커밋한 다음에만 만들며 `--push` 없이 `origin`을 달고 `git push -u origin master`한다.

**Tech Stack:** git, GitHub CLI (`gh`), PowerShell, pytest (`packages/web-api/.venv`), MIT LICENSE.

## Global Constraints

- 문서 범위: 살아 있는 문서 + spec/plan **색인**. 이력 본문은 수정하지 않음.
- 호스트: GitHub 개인 계정, **공개**. Cursor Origin 리포가 아님.
- 첫 푸시: 미커밋 기능을 먼저 커밋한 뒤, 문서와 함께 올린다.
- 라이선스: MIT. 루트 `LICENSE`. 연도 2026. 저작권자 = `gh api user -q .login`.
- 리포 이름: `dart-wrapper`. 기본 브랜치: `master` (`main`으로 바꾸지 않음).
- 원격: `origin`이 없을 때만 추가. 있는 원격은 바꾸지 않음.
- OpenDART: 회사 개황 보강에만 사용. 공시 목록·본문은 DART HTML.
- `.env`와 `packages/web-api/*.db`는 커밋·푸시하지 않음.
- 금지: `--force`, `origin` 교체, `gh repo delete`, 카탈로그 DB 삭제, spec/plan 본문 현행화, Render 배포.
- 추출기 버전: 살아 있는 문서는 `packages/web-api/app/extracting/constants.py`의 `EXTRACTOR_VERSION`(현재 `audit_opinion.v19`)과 같아야 한다.
- 명령은 모노레포 루트, PowerShell. 커밋 메시지는 한국어.
- 설계: `docs/superpowers/specs/2026-09-19-docs-and-github-repo-design.md`

## File structure

| 파일 | 책임 |
|------|------|
| 미추적 `docs/superpowers/specs/*.md`, `plans/*.md` (이 계획·이미 커밋된 설계 제외) | 이력 산출물을 그대로 커밋 |
| `packages/web-api/app/ksic.py`, `app/data/ksic11.json`, corp·OpenDART 모듈 | 회사 업종·KSIC 11차 |
| 추출 `completeness`/`selector`/`extraction_service`/extract Admin 템플릿 | 추출 운영 WIP |
| `README.md` | 공개 랜딩 |
| `AGENTS.md` | 에이전트 규칙 |
| `PRD.md` | 현재 제품 범위 |
| `packages/web-api/README.md` | 운영 진실. `v17` 잔여 제거 |
| `packages/entry-extractor/README.md` | 손대지 않음(모순 없을 때) |
| `docs/paper/*.md` | 측정 문서 버전·보고일 |
| `docs/superpowers/README.md` | spec/plan 색인 |
| `docs/github-repo.md` | GitHub 생성 런북 |
| `LICENSE` | MIT 전문 |
| 이 계획 파일 | 색인에 포함 |

---

### Task 1: 시크릿 가드와 이력 spec/plan 커밋

**Files:**
- Create: 없음
- Modify: 없음 (본문 수정 금지)
- Add (untracked as of 2026-09-19):
  - `docs/superpowers/specs/2026-09-11-extract-admin-monitor-design.md`
  - `docs/superpowers/specs/2026-09-16-extract-intake-and-patch-design.md`
  - `docs/superpowers/plans/2026-09-11-extract-admin-monitor.md`
  - `docs/superpowers/plans/2026-09-13-extract-field-bundle-monitor.md`
  - `docs/superpowers/plans/2026-09-15-dart-html-fetch-pacing.md`
  - `docs/superpowers/plans/2026-09-16-extract-intake-and-patch.md`
  - `docs/superpowers/plans/2026-09-17-icfr-expected-missing.md`
  - `docs/superpowers/plans/2026-09-18-audit-report-date-all-candidates-auth-match.md`
  - `docs/superpowers/plans/2026-09-18-audit-report-date-header-preprocess.md`
  - `docs/superpowers/plans/2026-09-18-audit-report-date-window-latest.md`
- Do not add: `docs/paper/` (Task 6), `docs/superpowers/plans/2026-09-19-docs-and-github-repo.md` (Task 6), `LICENSE` (Task 5)

**Interfaces:**
- Consumes: 없음
- Produces: 위 이력 파일이 `master`에 커밋됨. GitHub 리포는 아직 없음.

- [ ] **Step 1: 원격이 없고 시크릿이 추적되지 않는지 확인**

Run (repo root):

```powershell
git remote -v
git check-ignore -v packages/web-api/.env
git check-ignore -v packages/web-api/dart_catalog.db
git ls-files --error-unmatch .env 2>&1
git ls-files --error-unmatch packages/web-api/dart_catalog.db 2>&1
```

Expected: `git remote -v` 빈 출력. 두 `check-ignore`가 `.gitignore` 규칙을 출력. `ls-files --error-unmatch`는 경로가 인덱스에 없어 실패(error)해야 한다. `origin`이 보이면 **전체 계획 중단** (원격 변경 금지).

- [ ] **Step 2: 스테이징 후보에 `.env`·`*.db`가 없는지 확인**

```powershell
git status --short
```

Expected: `.env` / `dart_catalog.db`가 `??` 또는 staged로 보이지 않음. 보이면 gitignore를 고치고 이 태스크를 다시 시작한다.

- [ ] **Step 3: 이력 파일만 add하고 커밋**

본문을 편집하지 않는다. `docs/superpowers/specs/2026-09-09-corp-industry-opendart-design.md`는 KSIC 태스크로 남긴다.

```powershell
git add -- `
  docs/superpowers/specs/2026-09-11-extract-admin-monitor-design.md `
  docs/superpowers/specs/2026-09-16-extract-intake-and-patch-design.md `
  docs/superpowers/plans/2026-09-11-extract-admin-monitor.md `
  docs/superpowers/plans/2026-09-13-extract-field-bundle-monitor.md `
  docs/superpowers/plans/2026-09-15-dart-html-fetch-pacing.md `
  docs/superpowers/plans/2026-09-16-extract-intake-and-patch.md `
  docs/superpowers/plans/2026-09-17-icfr-expected-missing.md `
  docs/superpowers/plans/2026-09-18-audit-report-date-all-candidates-auth-match.md `
  docs/superpowers/plans/2026-09-18-audit-report-date-header-preprocess.md `
  docs/superpowers/plans/2026-09-18-audit-report-date-window-latest.md
git diff --cached --stat
git commit -m "docs: 미커밋이던 추출·날짜 설계와 구현 계획을 남긴다" -m "로컬에만 있던 spec/plan을 이력으로 보존한다. 본문은 수정하지 않는다."
```

Expected: 10 files, 1 commit. `git status --short`에 위 경로가 없음.

---

### Task 2: 회사 업종·KSIC 워킹 트리 커밋

**Files:**
- Modify:
  - `packages/web-api/.env.example`
  - `packages/web-api/app/adapters/opendart_company.py`
  - `packages/web-api/app/api/admin/corps.py`
  - `packages/web-api/app/api/admin/ui.py`
  - `packages/web-api/app/api/deps.py`
  - `packages/web-api/app/config.py`
  - `packages/web-api/app/data/ksic10.json`
  - `packages/web-api/app/ksic.py`
  - `packages/web-api/app/repositories/corp_repository.py`
  - `packages/web-api/app/services/corp_industry_service.py`
  - `packages/web-api/tests/test_corp_industry_service.py`
  - `packages/web-api/tests/test_corps_admin_api.py`
  - `packages/web-api/tests/test_corps_admin_ui.py`
  - `packages/web-api/tests/test_ksic.py`
  - `packages/web-api/tests/test_opendart_company.py`
  - `docs/superpowers/specs/2026-09-09-corp-industry-opendart-design.md` (업종 기능 설계의 워킹 트리 변경을 그대로. 다른 spec은 건드리지 않음)
- Create:
  - `packages/web-api/app/data/ksic11.json`
  - `packages/web-api/scripts/build_ksic10.py`
  - `packages/web-api/scripts/build_ksic11.py`
  - `packages/web-api/scripts/remap_corp_ksic_names.py`
- Do not add: `packages/web-api/README.md`, `AGENTS.md` (문서 태스크)

**Interfaces:**
- Consumes: Task 1 이후 워킹 트리
- Produces: KSIC 11차 우선 조회가 `master`에 있음. `lookup_ksic_names` 동작은 테스트가 고정.

- [ ] **Step 1: 업종 관련 기존 테스트 실행**

새 기능을 작성하지 않는다. 워킹 트리 코드로 테스트를 돌린다.

```powershell
cd packages/web-api
.\.venv\Scripts\python.exe -m pytest tests/test_ksic.py tests/test_opendart_company.py tests/test_corp_industry_service.py tests/test_corps_admin_api.py tests/test_corps_admin_ui.py -v
```

Expected: PASS. 실패하면 **이번 변경으로 새로 깨진 것만** 고치고 같은 명령을 다시 돌린다. 추출 테스트는 이 태스크에서 돌리지 않는다.

- [ ] **Step 2: 시크릿이 add되지 않았는지 확인 후 커밋**

```powershell
cd ../..
git add -- `
  packages/web-api/.env.example `
  packages/web-api/app/adapters/opendart_company.py `
  packages/web-api/app/api/admin/corps.py `
  packages/web-api/app/api/admin/ui.py `
  packages/web-api/app/api/deps.py `
  packages/web-api/app/config.py `
  packages/web-api/app/data/ksic10.json `
  packages/web-api/app/data/ksic11.json `
  packages/web-api/app/ksic.py `
  packages/web-api/app/repositories/corp_repository.py `
  packages/web-api/app/services/corp_industry_service.py `
  packages/web-api/tests/test_corp_industry_service.py `
  packages/web-api/tests/test_corps_admin_api.py `
  packages/web-api/tests/test_corps_admin_ui.py `
  packages/web-api/tests/test_ksic.py `
  packages/web-api/tests/test_opendart_company.py `
  packages/web-api/scripts/build_ksic10.py `
  packages/web-api/scripts/build_ksic11.py `
  packages/web-api/scripts/remap_corp_ksic_names.py `
  docs/superpowers/specs/2026-09-09-corp-industry-opendart-design.md
git diff --cached --name-only
```

Expected: `.env` / `*.db` 없음. `ui.py`/`deps.py`/`config.py`는 업종 Admin과 공유 배선이라 이 커밋에 넣는다(hunk 분할 없음).

```powershell
git commit -m "feat(web-api): 업종 이름은 KSIC 11차를 우선하고 없으면 10차를 쓴다" -m "같은 코드를 두 표에서 이어 붙이면 차수마다 의미가 달라진다."
```

---

### Task 3: 추출 운영 워킹 트리 커밋

**Files:**
- Modify:
  - `packages/web-api/app/extracting/field_bundles.py`
  - `packages/web-api/app/extracting/selector.py`
  - `packages/web-api/app/models/extraction_job.py`
  - `packages/web-api/app/repositories/entry_repository.py`
  - `packages/web-api/app/schemas/extract.py`
  - `packages/web-api/app/services/completeness_service.py`
  - `packages/web-api/app/services/extraction_service.py`
  - `packages/web-api/app/templates/admin/base.html`
  - `packages/web-api/app/templates/admin/extract.html`
  - `packages/web-api/app/templates/admin/partials/extract_completeness.html`
  - `packages/web-api/app/templates/admin/partials/extract_form.html`
  - `packages/web-api/tests/test_entry_repository.py`
  - `packages/web-api/tests/test_extract_admin_api.py`
  - `packages/web-api/tests/test_extract_admin_ui.py`
  - `packages/web-api/tests/test_extracting_selector.py`
  - `packages/web-api/tests/test_extraction_service.py`

**Interfaces:**
- Consumes: Task 2에서 커밋한 `ui.py` 배선
- Produces: 추출 입수/patch·모니터 코드가 `master`에 있음. `EXTRACTOR_VERSION`은 여전히 `audit_opinion.v19`.

- [ ] **Step 1: 추출 관련 기존 테스트 실행**

```powershell
cd packages/web-api
.\.venv\Scripts\python.exe -m pytest tests/test_extraction_service.py tests/test_extract_admin_api.py tests/test_extract_admin_ui.py tests/test_extracting_selector.py tests/test_entry_repository.py -v
```

Expected: PASS. 실패하면 이번 변경으로 깨진 것만 고친다.

- [ ] **Step 2: 커밋**

```powershell
cd ../..
git add -- `
  packages/web-api/app/extracting/field_bundles.py `
  packages/web-api/app/extracting/selector.py `
  packages/web-api/app/models/extraction_job.py `
  packages/web-api/app/repositories/entry_repository.py `
  packages/web-api/app/schemas/extract.py `
  packages/web-api/app/services/completeness_service.py `
  packages/web-api/app/services/extraction_service.py `
  packages/web-api/app/templates/admin/base.html `
  packages/web-api/app/templates/admin/extract.html `
  packages/web-api/app/templates/admin/partials/extract_completeness.html `
  packages/web-api/app/templates/admin/partials/extract_form.html `
  packages/web-api/tests/test_entry_repository.py `
  packages/web-api/tests/test_extract_admin_api.py `
  packages/web-api/tests/test_extract_admin_ui.py `
  packages/web-api/tests/test_extracting_selector.py `
  packages/web-api/tests/test_extraction_service.py
git commit -m "feat(web-api): 추출 입수 현황과 칸 실패 patch를 운영 화면에 둔다" -m "입수와 12칸 품질을 섞지 않고, 파서 수정 뒤에는 실패 문서만 다시 넣는다."
```

Expected: `packages/web-api/README.md`와 `docs/paper/`는 아직 unstaged.

---

### Task 4: AGENTS.md와 PRD.md

**Files:**
- Modify: `AGENTS.md`, `PRD.md`
- Test: 없음 (문서). 카탈로그 보호 절은 HEAD 대비 워킹 트리에 이미 추가된 문구를 **유지**한다.

**Interfaces:**
- Consumes: Task 2–3의 제품 범위 (카탈로그, facts, corps, 추출 모드)
- Produces: 에이전트·PRD가 현재 FastAPI web-api를 사실로 적음.

- [ ] **Step 1: `AGENTS.md` Overview·Architecture만 고친다**

`## 카탈로그 보호` 절과 Code Conventions는 그대로 둔다. Overview와 Architecture를 아래로 교체한다.

```markdown
# dart-wrapper Agent Guidelines

## Overview
OpenDART 목록·재무제표 API가 아니라 DART 상세검색 및 상세페이지 HTML을 스크래핑하여 공시 문서 컨테이너(접수 단위) 내 구성 문서·섹션을 중간 TOC 노드까지 펼친 후, 목록 features와 결합하여 flat entry 형태의 카탈로그를 구축하는 프로젝트입니다. 회사 업종 보강만 OpenDART 기업개황 API를 씁니다.

- Entry 추출 패키지: `@dart-wrapper/entry-extractor`
- Serve/재가공·감사 추출: FastAPI `packages/web-api`

## Code Conventions
```

Code Conventions 블록은 파일을 열어서 **현재 5줄을 유지**한다.

Architecture:

```markdown
## Architecture
- DB에는 카탈로그(`entries`, `disclosures`, 슬라이스·수집 이력), `audit_report_facts`, `corps`를 둡니다. 원문 HTML은 저장하지 않습니다.
- 본문 텍스트·표는 Serve 시점에 `viewer_url`로 동적 파싱합니다(Lazy Retrieval).
- DART 원문 수집 시 한국어 인코딩(EUC-KR / UTF-8) 자동 처리를 적용합니다.
- OpenDART는 기업개황 보강에만 사용합니다.
```

- [ ] **Step 2: `PRD.md`를 현재 제품 범위로 교체**

파일 전체를 아래로 바꾼다.

```markdown
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
```

- [ ] **Step 3: 카탈로그 보호 문구가 사라지지 않았는지 확인 후 커밋**

```powershell
Select-String -Path AGENTS.md -Pattern "카탈로그를 삭제한다" | Should -Not -BeNullOrEmpty
```

PowerShell에서 `Should`가 없으면:

```powershell
Select-String -Path AGENTS.md -Pattern "카탈로그를 삭제한다"
```

Expected: 한 줄 이상 매치.

```powershell
git add -- AGENTS.md PRD.md
git commit -m "docs: 에이전트 규칙과 PRD를 현재 web-api 범위에 맞춘다" -m "파이프라인이 예정이 아니고, DB에는 entry만이 아니라 facts와 corps도 있다."
```

---

### Task 5: LICENSE, GitHub 런북, 루트 README

**Files:**
- Create: `LICENSE`, `docs/github-repo.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `gh api user -q .login` → `<login>`
- Produces: 클론 URL과 MIT 저작권자에 같은 `<login>`. 런북이 리포 생성 전에 커밋됨.

- [ ] **Step 1: GitHub 로그인 이름을 읽는다**

```powershell
gh auth status
gh api user -q .login
```

Expected: 로그인된 계정 한 줄 (예: `yoont`). 실패하면 `gh auth login` 후 같은 명령을 다시 한다. 출력 문자열을 `<login>`으로 쓴다. 채팅에 토큰을 붙여 넣지 않는다.

- [ ] **Step 2: `LICENSE` 작성**

`<login>`을 Step 1 값으로 바꾼다.

```text
MIT License

Copyright (c) 2026 <login>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 3: `docs/github-repo.md` 작성**

파일 내용 전체:

```markdown
# GitHub 공개 리포 런북

모노레포 루트, PowerShell. 살아 있는 문서와 `LICENSE`가 커밋된 뒤에만 실행한다. `--force` 없음. `master`를 `main`으로 바꾸지 않는다.

1. `git remote -v`가 비어 있는지 확인한다. `origin`이 있으면 **중단**한다. URL을 바꾸지 않는다.
2. `.gitignore`에 `.env`, `packages/web-api/*.db`, `.venv/`, `node_modules/`가 있는지 확인한다.
3. `git status`에 `.env`, `*.db`, 키 파일이 없는지 확인한다.
4. `gh auth status`. 실패하면 `gh auth login` 후 재개한다. `gh`가 없으면 설치하고 중단한다.
5. `$login = gh api user -q .login` 후 리포 이름은 `$login/dart-wrapper`.
6. `gh repo view "$login/dart-wrapper"`가 성공하면 **중단**한다. 이름을 임의로 바꾸어 만들지 않는다.
7. `gh repo create dart-wrapper --public --source=. --remote=origin --description "DART 공시 카탈로그·감사 추출 모노레포"` — **`--push` 없음**. 이어서 `git push -u origin master`.
8. 루트 README 클론 URL이 `https://github.com/$login/dart-wrapper`와 다르면 고쳐서 커밋·푸시한다. 같으면 생략한다.
9. 금지: `--force`, 브랜치 이름 변경, `origin` 교체, `gh repo delete`.
```

- [ ] **Step 4: 루트 `README.md`에 랜딩 블록만 끼운다**

설치·실행·Public 표는 유지한다. `<login>`은 Step 1 값이다.

첫 문단 뒤에 삽입:

    저장소: https://github.com/<login>/dart-wrapper
    라이선스: [MIT](./LICENSE)

    클론 (PowerShell): git clone https://github.com/<login>/dart-wrapper.git

    `.env`와 카탈로그 DB(`packages/web-api/*.db`)는 커밋하지 않습니다. DART HTML을 치므로 요청 간격을 지키세요. Admin은 `ADMIN_TOKEN`이 필요합니다.

흐름 항목 4를 아래로 바꾸고 5를 추가한다.

    4. **감사 추출** — 카탈로그 주소로 감사인·의견·보고일·GAAP·당기 등 12묶음을 `audit_report_facts`에 저장 (원문 HTML은 저장하지 않음)
    5. **회사 업종 보강** — 공시 distinct 회사에 OpenDART **기업개황만** 호출하고, KSIC 이름은 저장소 JSON으로 붙임 (목록·본문 HTML과는 별 잡)

모듈 표 web-api 칸을 `수집 트리거, Catalog/Viewer, 감사 추출, 회사 업종`으로 바꾼다.

추출 정책 문단 앞에 문서 지도 표를 넣는다.

    | 문서 | 내용 |
    |------|------|
    | packages/entry-extractor/README.md | 수집 정책 |
    | packages/web-api/README.md | API·Admin·추출 규칙 |
    | docs/paper/variable-measurement.md | 논문용 측정 선택 |
    | docs/superpowers/README.md | spec/plan 색인 (당시 버전일 수 있음) |
    | docs/github-repo.md | GitHub 리포 생성 런북 |
    | PRD.md | 제품 범위 |
    | AGENTS.md | 에이전트 규칙 |

마지막 문장 `재개·슬라이스 엔드포인트는` 을 `재개·슬라이스·추출 모드는` 으로 바꾼다. Admin 세부 표는 루트에 추가하지 않는다.

- [ ] **Step 5: 커밋**

```powershell
git add -- LICENSE docs/github-repo.md README.md
git commit -m "docs: MIT 라이선스와 GitHub 런북, 공개 랜딩을 단다" -m "리포를 만들기 전에 클론 URL과 생성 순서를 문서에 고정한다."
```

---

### Task 6: 패키지 README, 논문 문서, spec 색인

**Files:**
- Modify: `packages/web-api/README.md`, `docs/paper/variable-measurement.md`, `docs/paper/research-data-completion.md`
- Create: `docs/superpowers/README.md`
- Add: `docs/superpowers/plans/2026-09-19-docs-and-github-repo.md` (이 계획 파일, 본문 수정 없이)
- Skip: `packages/entry-extractor/README.md` — `leafOnly` 기본 false·첨부 접수 스코프가 코드와 같으면 수정하지 않음

**Interfaces:**
- Consumes: `EXTRACTOR_VERSION == "audit_opinion.v19"`
- Produces: 살아 있는 문서의 `audit_opinion.v*`가 모두 `v19`

- [ ] **Step 1: web-api README 버전 잔여만 고친다**

`packages/web-api/README.md`에서 완전성 표 `ok` 행의 `audit_opinion.v17`을 `audit_opinion.v19`로 바꾼다. 구조 표와 「추출기 버전은 `audit_opinion.v19`」문장은 그대로 둔다.

찾기:

```text
extractor_version`이 현재 추출기(`audit_opinion.v17`)와 같음
```

바꾸기:

```text
extractor_version`이 현재 추출기(`audit_opinion.v19`)와 같음
```

워킹 트리에 이미 있는 KSIC 11차 절·patch 모드 절은 코드와 맞으면 추가 편집하지 않는다. 없는 API 행을 만들지 않는다.

- [ ] **Step 2: `docs/paper/variable-measurement.md` 버전과 보고일**

`audit_opinion.v17` 세 곳을 `audit_opinion.v19`로 바꾼다 (도입 문단, §4 추출 문단, §12 인용).

`### 4.3 감사보고서일` 본문을 아래로 교체한다.

```markdown
### 4.3 감사보고서일

compact 본문에서 날짜를 전수 모은 뒤 `period_end < iso ≤` 접수번호 앞 8자리(인증일) 창 안에서 **가장 늦은 날**이 `ok`/`letter`이다. 창이 비면 `not_found`(ISO는 null, 후보는 저장). 목록 `rcept_dt`는 쓰지 않는다. 후보가 있는 `not_found`는 `POST /admin/extract/resolve-dates`로 LLM이 인덱스를 고른다. 저장 때 창 검사를 하지 않는다. 의견·GAAP에는 LLM을 쓰지 않는다.
```

§7 표의 감사보고서일 행:

```markdown
| 감사보고서일 | 의견서 후보 ∩ (결산, 인증일] 중 최댓값 | ISO 또는 `not_found` | 문서 | LLM은 후보 있는 `not_found`만 |
```

§12 인용 마지막 문장에서 「복수 후보인 경우」를 「창이 비어 후보만 남은 경우」로 바꾼다.

- [ ] **Step 3: `docs/paper/research-data-completion.md` E1**

E1 확인 방법 칸:

```text
행마다 `extractor_version = audit_opinion.v19` (또는 논문에 적은 버전)
```

표본 잠금 표(결산월 2016–2025 등)는 바꾸지 않는다.

- [ ] **Step 4: `docs/superpowers/README.md` 색인 작성**

서문 다음에 spec 표, plan 표를 둔다. 제목은 각 파일 첫 `#` 헤더를 쓴다. 본문을 요약 재작성하지 않는다.

```markdown
# spec / plan 색인

기능 설계와 구현 계획의 **당시** 기록이다. 파일에 적힌 추출기 버전은 그 날짜의 값이며 현재 `EXTRACTOR_VERSION`(`audit_opinion.v19`)과 다를 수 있다. 운영 진실은 [`packages/web-api/README.md`](../../packages/web-api/README.md)를 본다.

## Specs

| 날짜 | 제목 | 종류 |
|------|------|------|
| 2026-07-25 | [Admin 카탈로그 · Public Viewer 코드 뼈대 설계](specs/2026-07-25-admin-viewer-skeleton-design.md) | spec |
| 2026-07-25 | [카탈로그 목록·검색 API 설계](specs/2026-07-25-catalog-query-api-design.md) | spec |
| 2026-07-25 | [Admin 운영 UI · 불연속 수집 재개·완전성 설계](specs/2026-07-25-admin-ops-resume-design.md) | spec |
| 2026-07-25 | [Admin 완전성 히트맵 설계](specs/2026-07-25-completeness-heatmap-design.md) | spec |
| 2026-07-26 | [Admin Ops Console 설계](specs/2026-07-26-admin-ops-console-design.md) | spec |
| 2026-07-26 | [첨부문서 leaf entry 추출 설계](specs/2026-07-26-attachment-leaf-entries-design.md) | spec |
| 2026-07-26 | [Browse Viewer 계층 목차 설계](specs/2026-07-26-browse-toc-hierarchy-design.md) | spec |
| 2026-07-26 | [Browse 목차 트리 렌더 개선 설계](specs/2026-07-26-browse-toc-tree-render-design.md) | spec |
| 2026-07-26 | [Public 탐색·열람 UI와 Viewer 블록 정제 설계](specs/2026-07-26-browse-viewer-blocks-design.md) | spec |
| 2026-07-27 | [Catalog 응답 필드 보강 설계](specs/2026-07-27-catalog-disclosure-fields-design.md) | spec |
| 2026-07-27 | [Catalog HTML 탐색 설계](specs/2026-07-27-catalog-html-explore-design.md) | spec |
| 2026-07-27 | [공시 이력 목록 + 첨부 최종본만 추출 설계](specs/2026-07-27-disclosure-history-final-attachments-design.md) | spec |
| 2026-07-27 | [중간 TOC 노드 저장 설계](specs/2026-07-27-store-intermediate-toc-nodes-design.md) | spec |
| 2026-07-28 | [접수 스코프 첨부 추출 설계](specs/2026-07-28-reception-scoped-attachments-design.md) | spec |
| 2026-08-27 | [정정 입수 섞임 점검](specs/2026-08-27-correction-scope-audit-design.md) | spec |
| 2026-08-28 | [감사보고서 표지·의견 추출 설계](specs/2026-08-28-audit-opinion-extraction-design.md) | spec |
| 2026-08-29 | [의견서 선행형·후행형 서식 분기 설계](specs/2026-08-29-audit-opinion-letter-format-design.md) | spec |
| 2026-08-29 | [의견서 강조사항 오탐 방지 설계](specs/2026-08-29-audit-opinion-letter-window-design.md) | spec |
| 2026-08-30 | [F001·F002 목록 감사인 최후 해소 설계](specs/2026-08-30-auditor-listing-fallback-design.md) | spec |
| 2026-08-31 | [외부감사 실시내용 추출 설계](specs/2026-08-31-audit-activity-extraction-design.md) | spec |
| 2026-09-02 | [첨부 재무제표 계정 추출 설계](specs/2026-09-02-audit-accounts-extraction-design.md) | spec |
| 2026-09-03 | [내부회계관리제도 감사·검토 의견 추출 설계](specs/2026-09-03-audit-icfr-opinion-extraction-design.md) | spec |
| 2026-09-03 | [제표 비교열 제N기 기간 매핑](specs/2026-09-03-fs-comparative-period-headers-design.md) | spec |
| 2026-09-03 | [당기순이익·순손실 라벨과 금액 부호](specs/2026-09-03-net-income-sign-design.md) | spec |
| 2026-09-04 | [재무상태표 유동자산·유동부채 소계](specs/2026-09-04-current-asset-liability-extraction-design.md) | spec |
| 2026-09-04 | [감사 추출 결과 HTML 탐색 설계](specs/2026-09-04-facts-html-browse-design.md) | spec |
| 2026-09-04 | [부채총계·계속기업·연결 종속기업 수 추출 설계](specs/2026-09-04-liability-gc-subsidiary-extraction-design.md) | spec |
| 2026-09-09 | [회사 마스터 업종 보강 설계](specs/2026-09-09-corp-industry-opendart-design.md) | spec |
| 2026-09-11 | [감사 추출 Admin 모니터 설계](specs/2026-09-11-extract-admin-monitor-design.md) | spec |
| 2026-09-13 | [추출 12묶음 성공·실패 모니터 설계](specs/2026-09-13-extract-field-bundle-monitor-design.md) | spec |
| 2026-09-15 | [DART HTML 요청 간격 공유 설계](specs/2026-09-15-dart-html-fetch-pacing-design.md) | spec |
| 2026-09-16 | [추출 입수 현황판과 칸 실패 패치 설계](specs/2026-09-16-extract-intake-and-patch-design.md) | spec |
| 2026-09-17 | [내부회계 skipped → 제도상없음 재분류 설계](specs/2026-09-17-icfr-expected-missing-design.md) | spec |
| 2026-09-18 | [감사보고서일 전수 후보·인증일 일치 설계](specs/2026-09-18-audit-report-date-all-candidates-auth-match-design.md) | spec |
| 2026-09-18 | [감사보고서일 후행형 머리글 전처리 설계](specs/2026-09-18-audit-report-date-header-preprocess-design.md) | spec |
| 2026-09-18 | [감사보고서일 창 안 최댓값 선택 설계](specs/2026-09-18-audit-report-date-window-latest-design.md) | spec |
| 2026-09-19 | [살아 있는 문서 정렬과 GitHub 공개 리포 설계](specs/2026-09-19-docs-and-github-repo-design.md) | spec |

## Plans

| 날짜 | 제목 | 종류 |
|------|------|------|
| 2026-07-25 | [Admin 카탈로그 · Public Viewer 뼈대](plans/2026-07-25-admin-viewer-skeleton.md) | plan |
| 2026-07-25 | [Catalog Query API](plans/2026-07-25-catalog-query-api.md) | plan |
| 2026-07-25 | [Admin Ops Resume · Completeness](plans/2026-07-25-admin-ops-resume.md) | plan |
| 2026-07-25 | [Admin 완전성 히트맵](plans/2026-07-25-completeness-heatmap.md) | plan |
| 2026-07-26 | [Admin Ops Console](plans/2026-07-26-admin-ops-console.md) | plan |
| 2026-07-26 | [첨부문서 leaf entry 추출](plans/2026-07-26-attachment-leaf-entries.md) | plan |
| 2026-07-26 | [Browse Viewer 계층 목차](plans/2026-07-26-browse-toc-hierarchy.md) | plan |
| 2026-07-26 | [Browse 목차 트리 렌더 개선](plans/2026-07-26-browse-toc-tree-render.md) | plan |
| 2026-07-26 | [Browse UI · Viewer Blocks](plans/2026-07-26-browse-viewer-blocks.md) | plan |
| 2026-07-27 | [Catalog HTML 탐색](plans/2026-07-27-catalog-html-explore.md) | plan |
| 2026-07-27 | [공시 이력 목록 + 첨부 최종본](plans/2026-07-27-disclosure-history-final-attachments.md) | plan |
| 2026-07-27 | [중간 TOC 노드 저장](plans/2026-07-27-store-intermediate-toc-nodes.md) | plan |
| 2026-07-28 | [접수 스코프 첨부 추출](plans/2026-07-28-reception-scoped-attachments.md) | plan |
| 2026-08-28 | [감사보고서 표지·의견 추출](plans/2026-08-28-audit-opinion-extraction.md) | plan |
| 2026-08-29 | [의견서 선행형·후행형 서식 분기](plans/2026-08-29-audit-opinion-letter-format.md) | plan |
| 2026-08-29 | [의견서 강조사항 오탐 방지](plans/2026-08-29-audit-opinion-letter-window.md) | plan |
| 2026-08-30 | [F001·F002 목록 감사인 최후 해소](plans/2026-08-30-auditor-listing-fallback.md) | plan |
| 2026-08-31 | [외부감사 실시내용 추출](plans/2026-08-31-audit-activity-extraction.md) | plan |
| 2026-09-02 | [첨부 재무제표 계정 추출](plans/2026-09-02-audit-accounts-extraction.md) | plan |
| 2026-09-03 | [내부회계관리제도 의견 추출](plans/2026-09-03-audit-icfr-opinion-extraction.md) | plan |
| 2026-09-03 | [제표 비교열 제N기](plans/2026-09-03-fs-comparative-period-headers.md) | plan |
| 2026-09-03 | [당기순이익·순손실 부호](plans/2026-09-03-net-income-sign.md) | plan |
| 2026-09-04 | [유동자산·유동부채 소계](plans/2026-09-04-current-asset-liability-extraction.md) | plan |
| 2026-09-04 | [감사 추출 결과 HTML 탐색](plans/2026-09-04-facts-html-browse.md) | plan |
| 2026-09-04 | [부채총계·계속기업·종속기업 수](plans/2026-09-04-liability-gc-subsidiary-extraction.md) | plan |
| 2026-09-09 | [회사 마스터 업종 보강](plans/2026-09-09-corp-industry-opendart.md) | plan |
| 2026-09-11 | [감사 추출 Admin 모니터](plans/2026-09-11-extract-admin-monitor.md) | plan |
| 2026-09-13 | [추출 12묶음 모니터](plans/2026-09-13-extract-field-bundle-monitor.md) | plan |
| 2026-09-15 | [DART HTML 요청 간격 공유](plans/2026-09-15-dart-html-fetch-pacing.md) | plan |
| 2026-09-16 | [추출 입수 현황판과 칸 실패 패치](plans/2026-09-16-extract-intake-and-patch.md) | plan |
| 2026-09-17 | [내부회계 skipped → 제도상없음](plans/2026-09-17-icfr-expected-missing.md) | plan |
| 2026-09-18 | [감사보고서일 전수 후보·인증일 일치](plans/2026-09-18-audit-report-date-all-candidates-auth-match.md) | plan |
| 2026-09-18 | [감사보고서일 후행형 머리글 전처리](plans/2026-09-18-audit-report-date-header-preprocess.md) | plan |
| 2026-09-18 | [감사보고서일 창 안 최댓값](plans/2026-09-18-audit-report-date-window-latest.md) | plan |
| 2026-09-19 | [살아 있는 문서 정렬과 GitHub 공개 리포](plans/2026-09-19-docs-and-github-repo.md) | plan |
```

디스크에 표와 다른 spec/plan 파일이 있으면 행을 추가한다. 있는 파일의 본문은 수정하지 않는다.

- [ ] **Step 5: 살아 있는 문서 버전 검사 후 커밋**

```powershell
$ver = Select-String -Path packages/web-api/app/extracting/constants.py -Pattern 'EXTRACTOR_VERSION = "([^"]+)"' | ForEach-Object { $_.Matches[0].Groups[1].Value }
$files = @(
  'README.md','AGENTS.md','PRD.md',
  'packages/web-api/README.md','packages/entry-extractor/README.md',
  'docs/paper/variable-measurement.md','docs/paper/research-data-completion.md',
  'docs/superpowers/README.md','docs/github-repo.md'
)
Get-ChildItem $files -ErrorAction SilentlyContinue | ForEach-Object {
  Select-String -Path $_.FullName -Pattern 'audit_opinion\.v\d+' |
    Where-Object { $_.Line -notmatch [regex]::Escape($ver) }
}
```

Expected: 출력 없음 (살아 있는 문서에 다른 버전 없음). spec/plan 본문은 이 검사에 넣지 않는다.

```powershell
git add -- packages/web-api/README.md docs/paper docs/superpowers/README.md docs/superpowers/plans/2026-09-19-docs-and-github-repo.md
git commit -m "docs: 살아 있는 문서를 v19에 맞추고 spec 색인을 단다" -m "이력 spec/plan 본문은 그대로 두고 측정·운영 README의 버전만 코드 상수와 같게 한다."
```

---

### Task 7: GitHub 공개 리포 생성과 푸시

**Files:**
- Modify: `README.md` (클론 URL이 실제와 다를 때만)

**Interfaces:**
- Consumes: Task 5의 `docs/github-repo.md`, `<login>`
- Produces: `origin` = `https://github.com/<login>/dart-wrapper.git`, public, `master` 푸시됨

- [ ] **Step 1: 런북 1–6 확인**

```powershell
git remote -v
Select-String -Path .gitignore -Pattern '^\.env$|packages/web-api/\*\.db|^\.venv/|^node_modules/'
gh auth status
$login = gh api user -q .login
gh repo view "$login/dart-wrapper"
```

Expected:

- `git remote -v` 빈 출력. 값이 있으면 **중단**.
- gitignore 패턴이 각각 매치.
- `gh repo view`는 리포가 없어 **실패**해야 한다. 성공하면 중단하고 사용자에게 이름을 다시 받는다 (임의 변경 금지).

- [ ] **Step 2: 리포 생성 (`--push` 없음) 후 푸시**

```powershell
gh repo create dart-wrapper --public --source=. --remote=origin --description "DART 공시 카탈로그·감사 추출 모노레포"
git push -u origin master
```

Expected: `origin`이 GitHub를 가리킴. 기본 브랜치 `master`. force 없음.

- [ ] **Step 3: 공개 여부와 클론 URL**

```powershell
gh repo view --json isPrivate,url,defaultBranchRef
git remote get-url origin
git ls-files .env packages/web-api/dart_catalog.db
```

Expected: `isPrivate: false`. URL이 `https://github.com/<login>/dart-wrapper`. `ls-files` 해당 경로 없음.

README의 `https://github.com/<login>/dart-wrapper`가 실제 URL과 다르면 고친 뒤:

```powershell
git add -- README.md
git commit -m "docs: GitHub 클론 URL을 생성한 리포에 맞춘다"
git push
```

같으면 이 커밋은 생략한다.

---

## Spec coverage (self-review)

| Spec 절 | Task |
|---------|------|
| 살아 있는 문서 버전 = `EXTRACTOR_VERSION` | 6 Step 5 |
| spec/plan 색인, 본문 미수정 | 1, 6 Step 4 |
| MIT LICENSE | 5 |
| public `origin` + `master` | 7 |
| `.env` / `*.db` 미추적 | 1, 7 |
| README 흐름 5단계·문서 지도 | 5 Step 4 |
| PRD 현재 범위·leafOnly·entry_id·OpenDART 예외 | 4 |
| AGENTS 예정 문구 삭제·DB 범위·카탈로그 보호 유지 | 4 |
| web-api README v17 잔여·KSIC 11 | 3 이후 워킹 README + 6 Step 1 |
| paper 버전·보고일, 표본 잠금 유지 | 6 Step 2–3 |
| 기능 먼저 커밋 | 2, 3 |
| 런북 후 `gh repo create` without `--push` | 5, 7 |
| `origin` 기존 시 중단 | 1, 7 |
