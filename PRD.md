📄 Web App Product Requirement Document (PRD.md)
1. 프로젝트 개요 (Overview)
본 서비스는 DART 상세검색/상세페이지 HTML 스크래핑 방식(@dart-wrapper/entry-extractor 메커니즘)을 활용하여 공시 문서 메타데이터(Catalog)를 구축하고, 사용자 요청 시 viewer_url 기반으로 본문 원문을 실시간 파싱 및 정제하여 제공하는 DART 공시 파이프라인 Web App입니다.

2. 핵심 기능 요구사항 (Core Features)
🅰️ 기능 1: 카탈로그 구축 (Admin Function)
목적: DART 공시 문서의 메타데이터 및 leaf 단위 섹션 구조를 수집하여 DB 카탈로그 생성

수집 방식:

OpenDART API를 사용하지 않고, DART 상세검색 및 상세페이지 HTML을 스크래핑

공시 문서 컨테이너(접수 단위) 내부 구성 문서 및 섹션을 leaf 단계까지 분해(flatten)

검색 목록에서 추출한 features 데이터와 결합하여 Flat Entry 구조로 카탈로그 DB에 저장

주요 엔드포인트 / 작업:

POST /admin/catalog/extract: 기간/기업별 공시 수집 및 flat entry 저장 트리거

GET /admin/catalog/status: 카탈로그 수집 현황 및 로그 조회

🅱️ 기능 2: 문서 Viewer (Public Function)
목적: 일반 사용자가 특정 공시 문서/섹션 조회 요청 시 원문을 동적 수집하여 정제된 데이터 제공 (Lazy Retrieval)

수집 및 정제 메커니즘:

요청받은 rcp_no 기반으로 viewer_url 파싱 및 비동기 HTTP Fetching (EUC-KR/UTF-8 인코딩 자동 처리)

Raw HTML에서 불필요한 태그(script, style 등) 제거 및 깨끗한 본문 텍스트 추출

HTML 표(Table) 데이터를 JSON 구조로 파싱

주요 엔드포인트:

GET /api/v1/viewer/{rcp_no}: 특정 공시 문서 전체 원문 정제 결과 반환

GET /api/v1/viewer/{rcp_no}/sections/{ele_id}: 특정 leaf 섹션 원문 정제 결과 반환

3. 기술 스택 및 데이터 흐름 (Tech Stack & Flow)
Tech Stack
Backend Framework: FastAPI (Python 3.11+)

HTTP Client: httpx (Async)

Scraping & Parsing: BeautifulSoup4, lxml, pandas

Validation / Data Model: Pydantic v2

Data Architecture Flow
Plaintext
[Admin Admin Task]
  DART 상세검색 HTML 스크래핑 → Container/Leaf 분해 → Flat Entry 결합 → Catalog DB 저장 (Metadata Only)

[Public Viewer Request]
  클라이언트 요청 (rcp_no) → Catalog DB 조회 → viewer_url 파싱 → HTML Fetch & Cleaning → JSON 응답