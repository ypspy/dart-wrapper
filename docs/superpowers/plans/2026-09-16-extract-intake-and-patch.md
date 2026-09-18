# 추출 입수 현황판과 칸 실패 패치 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 완전성 화면에서 문서 입수와 12칸 품질을 나누고, `patch` 모드로 칸 실패 문서만 다시 GET한다.

**Architecture:** `field_partial`을 12묶음 fail과 맞춘다. `all_success`를 집계에 넣는다. HTML은 비교 표+유형 판. `run_job(mode=patch)`는 실패 키만 순회한다.

**Tech Stack:** FastAPI, SQLAlchemy, Jinja2, pytest.

## Global Constraints

- 패키지: `packages/web-api`만.
- 주석·Docstring·로그·사용자 메시지는 한국어.
- 테스트: `packages/web-api`에서 `.\.venv\Scripts\python.exe -m pytest …`
- KSIC/OpenDART 워킹 트리 변경은 커밋에 넣지 않음.

## File map

| 파일 | 책임 |
|------|------|
| `app/schemas/extract.py` | `all_success`, mode `patch` |
| `app/services/completeness_service.py` | 묶음 fail = field_partial, all_success, 실패 키 목록 |
| `app/services/extraction_service.py` | patch 순회 |
| `app/templates/admin/partials/extract_completeness.html` | 현황판 |
| `app/templates/admin/partials/extract_form.html` | patch 옵션 |
| `app/templates/admin/base.html` | 입수 막대·칩 CSS |
| `app/templates/admin/extract.html` | board_type include |
| `app/api/admin/ui.py` | board_type |
| `tests/test_extract_admin_api.py` | 집계·patch API |
| `tests/test_extraction_service.py` | patch 스킵/재fetch |
| `tests/test_extract_admin_ui.py` | HTML |
| `README.md` | 모드·집계 |

---

### Task 1: 집계 all_success / field_partial 정렬

- [ ] 테스트: 제도상없음 커뮤니케이션은 field_partial 0, all_success 1
- [ ] 테스트: icfr skipped면 field_partial 1, all_success 0
- [ ] 구현: CompletenessResponse + SQL
- [ ] pytest 해당 파일 통과

### Task 2: patch 모드

- [ ] 테스트: 칸 실패 문서만 GET, 전부 성공·미추출은 안 침
- [ ] 구현: 실패 키 순회
- [ ] pytest 통과

### Task 3: HTML 현황판 + 폼

- [ ] 테스트: 아직 안 함, 입수율, patch 옵션, 부분실패 본문 제거
- [ ] 구현: 템플릿·CSS
- [ ] pytest UI 통과

### Task 4: README

- [ ] patch·all_success·field_partial 정의를 맞춘다
