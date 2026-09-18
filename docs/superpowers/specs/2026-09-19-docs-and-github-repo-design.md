# 살아 있는 문서 정렬과 GitHub 공개 리포 설계

날짜: 2026-09-19  
상태: 브레인스토밍 승인 반영  
범위: 루트·패키지 README, `AGENTS.md`, `PRD.md`, `docs/paper/*`, spec/plan **색인**, MIT `LICENSE`, GitHub 생성 런북, 로컬 미커밋 기능의 커밋, 개인 계정 **공개** 리포 생성·푸시.

구현 계획이 아니라 **어떤 문서를 진실의 원천으로 둘지, 무엇을 고치지 않을지, 리포를 어떤 순서로 올리는지**다.

## 1. 목표

개발·수정·테스트가 쌓인 뒤에도, 공개 GitHub에서 보는 문서가 **지금 코드**와 같은 제품을 말하게 한다. 로컬에만 있던 git 이력을 원격에 백업한다.

성공 기준:

- 살아 있는 문서의 추출기 버전 문자열이 `packages/web-api/app/extracting/constants.py`의 `EXTRACTOR_VERSION`과 같다. 이력 spec/plan 본문은 이 검사에서 제외한다.
- `docs/superpowers/README.md`가 spec·plan 파일을 날짜순으로 가리킨다. 본문을 재작성하지 않는다.
- `LICENSE`가 MIT이고, `package.json`의 `"license": "MIT"`와 같다.
- `git remote origin`이 `https://github.com/<login>/dart-wrapper.git`을 가리키고, 기본 브랜치 **`master`** 가 푸시되어 있다. 리포는 **public**.
- `.env`와 `packages/web-api/*.db`(카탈로그 DB)는 추적되지 않는다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 문서 범위 | 살아 있는 문서 + spec/plan **색인**. 이력 본문은 수정하지 않음 (대화 선택 B) |
| 호스트 | GitHub 개인 계정, **공개** (선택 B). Cursor Origin 리포가 아님 |
| 첫 푸시 | 미커밋 기능을 먼저 커밋한 뒤, 문서와 함께 올린다 (선택 B). GitHub = 커밋 후 로컬 `master` |
| 라이선스 | MIT. 루트 `LICENSE` 추가. 연도 2026. 저작권자 = `gh api user -q .login` |
| 리포 이름 | `dart-wrapper` (폴더명과 동일) |
| 기본 브랜치 | `master`. `main`으로 바꾸지 않음 |
| 원격 | `origin`이 없을 때만 추가. 있는 원격은 바꾸지 않음 |
| OpenDART | 회사 개황 보강에만 사용. 공시 목록·본문은 DART HTML |

1차에 **안 넣는 것:** spec/plan 본문 현행화, 기능 개발·리팩터, Render 배포, 브랜치 이름 변경, force push, 카탈로그 DB 업로드, `CONTRIBUTING.md`/`SECURITY.md`/`CODE_OF_CONDUCT.md`.

## 3. 문서 체계

한 사실이 두 곳에 길게 반복되면, 짧은 쪽은 링크로 대체한다.

| 층 | 파일 | 독자 | 역할 |
|----|------|------|------|
| 공개 랜딩 | `README.md` | GitHub 방문자 | 무엇·왜·설치·실행·모듈 링크·클론 URL·MIT. API 세부는 패키지로 |
| 운영 | `packages/web-api/README.md`, `packages/entry-extractor/README.md` | 운영자 | 엔드포인트·추출 규칙·수집 정책의 진실 |
| 에이전트 | `AGENTS.md` | Cursor 에이전트 | 규칙·카탈로그 보호. 제품 소개는 한 단락 |
| 제품 요구 | `PRD.md` | 사람(범위 확인) | 현재 기능 목록. 구현 세부는 운영 README |
| 측정 | `docs/paper/*` | 논문 초고 | 측정 선택. 버전은 코드 상수와 같게 |
| 이력 색인 | `docs/superpowers/README.md` | 개발자 | spec/plan 목록만 |
| 공개 절차 | `docs/github-repo.md` | 이번 실행·이후 복제 | GitHub 생성 런북 |
| 라이선스 | `LICENSE` | 재사용자 | MIT 전문 |

### 3.1 루트 `README.md`

지금 골격(흐름·구조·설치·실행·Public GET 표)을 유지하고 다음만 더한다.

- 흐름 5단계: 수집 → 탐색 → 열람 → 감사 추출 → **회사 업종 보강**(OpenDART 기업개황만). 추출과 한 줄에 섞지 않는다.
- 문서 지도: 운영 README, `docs/paper/`, `docs/superpowers/README.md`, `docs/github-repo.md`.
- 클론 URL: `https://github.com/<login>/dart-wrapper.git`. `<login>`은 문서 커밋 전에 `gh api user -q .login`으로 확정한다. 생성 후 URL이 그와 다를 때만 작은 커밋으로 고친다.
- MIT와 `LICENSE` 한 줄.
- 공개 주의 두 줄: `.env`/DB 미추적. DART HTML 스크래핑이므로 요청 간격을 지킬 것. Admin은 토큰 필요.
- Public GET 표만 유지. Admin·추출 모드·12묶음 모니터는 web-api README로 보낸다.

### 3.2 `PRD.md`

초기 카탈로그+Viewer 초안을 **현재 제품 범위**로 다시 쓴다. 튜토리얼이 아니다.

포함할 기능:

1. 카탈로그 수집·하루 슬라이스·재개
2. Catalog/Facts HTML과 Public API
3. Viewer Lazy Retrieval과 `blocks`
4. 감사 추출(12묶음, 완전성, `extract`/`resume`/`reparse`/`patch`)
5. 회사 업종(OpenDART 개황 + KSIC 이름)

반드시 고칠 낡은 문장:

- 「leaf만 분해」 → 기본은 중간 TOC 노드 포함 (`leafOnly: false`)
- Viewer 경로 `{ele_id}` → `{entry_id}`
- OpenDART를 전혀 안 쓴다는 단정 → 목록·본문은 HTML, **기업개황만** OpenDART

### 3.3 `AGENTS.md`

규칙 문서는 유지하고 사실만 고친다.

- 「Serve 파이프라인 예정·확장」 → 이미 있는 FastAPI `packages/web-api`
- 「DB에는 entry만」 → 카탈로그(`entries`·`disclosures`·슬라이스 이력) + `audit_report_facts` + `corps`. 원문 HTML은 저장하지 않음
- 카탈로그 보호 절은 **문구 그대로**
- OpenDART는 기업개황 보강에만 쓴다는 한 줄
- 코드 스타일·한국어 주석·async 규칙은 유지

### 3.4 패키지 README

통째 재작성 금지. **기능 커밋 이후 트리**와 어긋난 문장만 고친다.

`packages/web-api/README.md`:

- 추출기 버전을 `EXTRACTOR_VERSION` **한 값**으로 통일한다. 완전성 표 등 살아 있는 절에 남은 `audit_opinion.v17` 같은 잔여를 없앤다.
- 코드에 있는 KSIC 11차 규칙(코드가 11차에 있으면 11차만, 없으면 10차), 추출 입수/patch·모니터를 해당 절에 반영한다.
- 엔드포인트 표는 코드에 있는 경로만. 없는 API를 추가하지 않는다.

`packages/entry-extractor/README.md`:

- 이력 목록, 첨부 접수 스코프, `leafOnly` 기본 `false`가 코드와 같으면 **수정하지 않는다.**
- 루트 README와 모순이 있을 때만 한 줄을 맞춘다.

### 3.5 `docs/paper/`

측정 선택 본문은 유지한다. **버전·12묶음 구성·보고일 규칙**만 코드와 같게 고친다.

- `variable-measurement.md`의 `audit_opinion.v17`과 논문용 인용 단락의 버전 문자열
- `research-data-completion.md`의 E1 버전 칸

표본 잠금(결산월 2016-01-31 ~ 2025-12-31, 유형 F001/F002/A001, 정정은 패널에서 최종만 등)은 연구 결정이므로 이 작업에서 바꾸지 않는다.

### 3.6 `docs/superpowers/README.md` (신규)

색인만. 열: 날짜, 제목(상대 경로 링크), 종류(spec/plan), 한 줄 주제.

본문을 요약해 다시 쓰지 않는다. 서문에 「파일에 적힌 추출기 버전은 그 당시 값이며 현재 `EXTRACTOR_VERSION`과 다를 수 있다」를 한 번만 적는다. spec/plan 본문은 수정 금지.

### 3.7 `LICENSE` (신규)

표준 MIT 전문. Copyright `(c) 2026 <github-login>`.

## 4. 흐름 (실행 순서)

순서는 고정이다. 문서 커밋 전에 GitHub를 만들지 않는다. 런북을 적기 전에 리포를 만들지 않는다.

```text
1. 시크릿·DB가 스테이징되지 않았는지 확인 (.gitignore)
2. 미커밋 기능·이미 작성된 spec/plan 파일을 영역별로 커밋
3. 살아 있는 문서 + LICENSE + 색인 + docs/github-repo.md 를 코드에 맞춰 커밋
   (클론 URL의 <login>은 이 시점에 gh api user로 넣는다)
4. docs/github-repo.md 대로 gh repo create (public, --push 없이) 후 git push -u origin master
```

### 4.1 기능 커밋 묶음

한 덩어리로 넣지 않는다. 최소 아래 영역으로 나눈다. 영역 안에 파일이 없으면 그 커밋은 생략한다.

| 묶음 | 내용 |
|------|------|
| 이력 spec/plan | 이미 디스크에 있는 미추적 `docs/superpowers/specs|plans` 파일. 본문 수정 없이 그대로 |
| 회사 업종·KSIC | `ksic.py`, `ksic11.json`, 빌드·remap 스크립트, corp 서비스·Admin·테스트 |
| 추출 운영 | completeness, selector, extraction_service, extract Admin UI, field_bundles 등 추출 관련 미커밋 |

커밋 메시지는 각 묶음의 **왜**를 한두 문장으로. 이 설계 파일은 브레인스토밍 직후 **단독 커밋**한다. 살아 있는 문서 묶음(3단계)에 섞지 않는다.

### 4.2 GitHub 런북 (`docs/github-repo.md`)

실행 전 커밋한다. 명령은 리포 루트, PowerShell 기준을 주석으로 밝힌다.

1. `git remote -v`가 비어 있는지. `origin`이 있으면 **중단**. 원격 URL을 바꾸지 않는다.
2. `.gitignore`에 `.env`, `packages/web-api/*.db`, `.venv/`, `node_modules/`가 있는지.
3. `git status`로 스테이징·미추적에 `.env`, `*.db`, 키 파일이 없는지.
4. `gh auth status`. 실패하면 `gh auth login` 후 재개. `gh`가 없으면 설치 안내 후 중단.
5. `gh api user -q .login`으로 `<login>` 확인. 리포 전체 이름: `<login>/dart-wrapper`.
6. 이름이 이미 있으면(`gh repo view <login>/dart-wrapper`가 성공) **중단**. 덮어쓰거나 다른 이름으로 임의 생성하지 않는다. 사용자에게 이름을 다시 받는다.
7. `gh repo create dart-wrapper --public --source=. --remote=origin --description "DART 공시 카탈로그·감사 추출 모노레포"` (**`--push` 없음**). 이어서 `git push -u origin master`.
8. README 클론 URL이 `https://github.com/<login>/dart-wrapper`와 다르면 커밋 후 `git push`. 같으면 이 단계는 생략.
9. 금지: `--force`, 브랜치 이름 변경, `origin` 교체, `gh repo delete`.

## 5. 실패·보호

| 상황 | 동작 |
|------|------|
| `origin`이 이미 있음 | 중단. 새 리포를 만들지 않음 |
| `<login>/dart-wrapper`가 이미 있음 | 중단. 이름 임의 변경 없음 |
| `gh` 미설치·미로그인 | 안내 후 중단 |
| `.env` 또는 DB가 커밋 대상 | 커밋하지 않음. gitignore를 고친 뒤에만 진행 |
| 카탈로그 삭제 요청 | `AGENTS.md` 카탈로그 보호. 이 작업과 무관하며 실행하지 않음 |
| 푸시 중 인증 실패 | 자격 증명을 채팅에 붙여 넣지 않음. `gh auth login`만 |

## 6. 검증

코드 테스트 스위트를 이 작업을 위해 새로 만들지 않는다. 기능 묶음을 커밋하기 전에 그 영역 관련 기존 테스트를 돌린다. **이번 변경으로 새로 깨진 것만** 고친다. 문서-only 커밋에는 테스트를 요구하지 않는다.

문서·리포 완료 판정:

- 살아 있는 문서(`README.md`, `AGENTS.md`, `PRD.md`, `packages/**/README.md`, `docs/paper/*.md`, `docs/superpowers/README.md`, `docs/github-repo.md`)에서 `audit_opinion.v` 문자열이 코드 상수와 다르면 실패. `docs/superpowers/specs/`·`plans/`는 제외.
- `git check-ignore -v packages/web-api/.env` 와 `packages/web-api/dart_catalog.db`가 ignore로 나옴.
- `git ls-files`에 `.env`·`dart_catalog.db`가 없음.
- `git remote get-url origin`이 GitHub `dart-wrapper`를 가리킴.
- `gh repo view --json isPrivate,url`에서 `isPrivate=false`.

## 7. 비범위 (재확인)

- 이력 spec/plan 본문을 현재 추출기에 맞게 고치기
- `master` → `main`
- Render Blueprint·배포
- 카탈로그 재수집, facts 재추출 실행
- 공개 웹 데모 호스팅
