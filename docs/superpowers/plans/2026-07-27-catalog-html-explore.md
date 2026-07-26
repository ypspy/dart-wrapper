# Catalog HTML 탐색 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development).

**Goal:** `/catalog` 공시 목록·`/catalog/{rcp_no}` leaf 전 컬럼 표를 skeleton CSS + sticky 헤더로 제공한다.

**Tech Stack:** FastAPI, Jinja2, CatalogQueryService, pytest

**Spec:** `docs/superpowers/specs/2026-07-27-catalog-html-explore-design.md`

## File Structure

| Path | Responsibility |
|------|----------------|
| `app/api/catalog/__init__.py` | 패키지 |
| `app/api/catalog/ui.py` | HTML 라우터 |
| `app/templates/catalog/base.html` | skeleton + sticky CSS (인라인) |
| `app/templates/catalog/list.html` | 공시 목록 표 |
| `app/templates/catalog/entries.html` | 공시 메타 + leaf 표 |
| `app/templates/catalog/404.html` | 없음 |
| `tests/test_catalog_ui.py` | UI 테스트 |
| `app/main.py` | 라우터 등록 |
| `README.md`, `packages/web-api/README.md` | `/catalog` 안내 |

## Task 1: 라우터 + 템플릿 + 테스트

- Fake `CatalogQueryService`로 `/catalog`, `/catalog/{rcp}`, 404, 컬럼 헤더, next_cursor 링크 assert
- `list_disclosures(limit, cursor)` / `list_entries(rcp_no)` 호출
- null → `—`, path → ` › ` join
- sticky: `.page-header`, `.table-scroll thead th`

## Task 2: README + 스펙 상태 승인으로 갱신
