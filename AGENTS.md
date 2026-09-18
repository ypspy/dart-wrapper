# dart-wrapper Agent Guidelines

## Overview
OpenDART 목록·재무제표 API가 아니라 DART 상세검색 및 상세페이지 HTML을 스크래핑하여 공시 문서 컨테이너(접수 단위) 내 구성 문서·섹션을 중간 TOC 노드까지 펼친 후, 목록 features와 결합하여 flat entry 형태의 카탈로그를 구축하는 프로젝트입니다. 회사 업종 보강만 OpenDART 기업개황 API를 씁니다.

- Entry 추출 패키지: `@dart-wrapper/entry-extractor`
- Serve/재가공·감사 추출: FastAPI `packages/web-api`

## Code Conventions
- **Language**: Python 3.11+
- **Style**: Black / Flake8 기준 코드 스타일 준수
- **Async First**: I/O 작업(httpx, DB 접근 등)은 반드시 비동기 처리
- **Type Annotations**: 모든 함수 입력/출력 타입 명시
- 주석, Docstring, 로그, 예외/사용자 메시지는 한국어로 작성

## Architecture
- DB에는 카탈로그(`entries`, `disclosures`, 슬라이스·수집 이력), `audit_report_facts`, `corps`를 둡니다. 원문 HTML은 저장하지 않습니다.
- 본문 텍스트·표는 Serve 시점에 `viewer_url`로 동적 파싱합니다(Lazy Retrieval).
- DART 원문 수집 시 한국어 인코딩(EUC-KR / UTF-8) 자동 처리를 적용합니다.
- OpenDART는 기업개황 보강에만 사용합니다.

## 카탈로그 보호 (삭제 금지에 가깝게)
리프 주소 카탈로그(`entries`, `disclosures`, `slice_progress`, `disclosure_attempts`, `catalog_jobs` 및 이를 담은 `dart_catalog.db` 통째 삭제)는 DART에서 다시 모으는 비용이 큽니다. `audit_report_facts`·추출/날짜해소 잡만 비우는 것과 같지 않습니다.

- 사용자가 카탈로그 삭제·초기화·DROP·파일 삭제를 **명시적으로 명령해도 즉시 실행하지 않습니다.**
- 먼저 무엇이 지워지는지(리프 `viewer_url`·공시 메타·수집 이력)와 복구가 수집을 처음부터 다시 하는 일임을 짧게 설명합니다.
- 그다음 **여러 차례**(최소 두 번, 가능하면 세 번) 심사숙고를 권하고, 추출 결과만 지우는 대안을 제안합니다.
- 그래도 진행하려면 사용자가 후속 메시지에 **「카탈로그를 삭제한다」** 를 그대로 적어야 합니다. `응`/`해줘`/`초기화`만으로는 부족합니다.
- 추출 결과(`audit_report_facts`, `extractor_id`가 `audit_opinion`/`resolve_dates`인 잡·로그) 초기화는 이 보호 대상이 아닙니다.
