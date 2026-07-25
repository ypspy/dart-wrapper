# dart-wrapper Agent Guidelines

## Overview
OpenDART OpenAPI를 사용하지 않고, DART 상세검색 및 상세페이지 HTML을 스크래핑하여 공시 문서 컨테이너(접수 단위) 내 구성 문서·섹션을 leaf 단계까지 펼친 후, 목록 features와 결합하여 flat entry 형태의 카탈로그를 구축하는 프로젝트입니다.

- Entry 추출 패키지: `@dart-wrapper/entry-extractor`
- Serve/재가공 파이프라인: FastAPI 기반 비동기 구조 (예정·확장)

## Code Conventions
- **Language**: Python 3.11+
- **Style**: Black / Flake8 기준 코드 스타일 준수
- **Async First**: I/O 작업(httpx, DB 접근 등)은 반드시 비동기 처리
- **Type Annotations**: 모든 함수 입력/출력 타입 명시
- 주석, Docstring, 로그, 예외/사용자 메시지는 한국어로 작성

## Architecture
- DB에는 entry만 저장합니다.
- 본문 텍스트·표는 Serve 시점에 `viewer_url`로 동적 파싱합니다(Lazy Retrieval).
- DART 원문 수집 시 한국어 인코딩(EUC-KR / UTF-8) 자동 처리를 적용합니다.
