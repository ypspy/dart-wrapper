# 추출 입수 현황판과 칸 실패 패치 설계

날짜: 2026-09-16  
상태: 구현 중 (운영 논의·목업 반영)  
범위: `packages/web-api` — `/admin/extract` 완전성 UI, 완전성 집계, 추출 모드 `patch`

선행: 12묶음 모니터 설계, `/admin/extract` 모니터, 연구 창 20160101–20260909.

## 1. 목표

운영자가 문서 **입수**와 12칸 **품질**을 섞지 않고 보고, 파서를 고친 뒤에는
창 전체가 아니라 **칸 실패 문서만** 다시 GET한다.

성공 기준:

- 왼쪽 완전성은 세 유형 비교 표 + 고른 유형의 단계 판이다. 영어 키·부분실패를
  입수 숫자와 같은 줄에 두지 않는다.
- `ok`(입수)와 `all_success`(12묶음 실패 0)와 `field_partial`(묶음 실패 ≥1)을 구분한다.
- 커뮤니케이션 제도상없음은 `field_partial`이 아니다.
- 모드 `patch`는 현재 추출기 `fetch_status=ok`이면서 묶음 실패가 있는 문서만
  대상으로 `_extract_document`를 다시 돌린다. 미추출·fetch 실패는 `resume`에 남긴다.

## 2. 집계

`ok`는 기존과 같다: `fetch_status=ok`이고 현재 `EXTRACTOR_VERSION`.

`field_partial`은 그 부분집합 중 **12묶음 `classify_outcome`이 fail인 행**.
해당없음·제도상없음은 구멍이 아니다.

`all_success`는 `ok`이면서 묶음 실패가 0인 행. `ok = all_success + field_partial`.

목록 `status=field_partial`은 새 정의와 같다.

## 3. 화면

`extract_completeness.html`:

- 비교 표: 유형, 입수됨, 입수율, 아직 안 함, 시도 실패, 구버전
- 유형 칩(F001/F002/A001) → 같은 partial을 `board_type`으로 다시 불러 단계 판
- 단계: 아직 안 함 / 시도 실패 / 구버전 / 입수됨(+ 전부 성공)
- 날짜 모호는 주석. 12묶음 표는 그 아래 유지

폼 모드에 `patch · 칸 실패만`을 추가한다.

## 4. `patch`

`ExtractionService.run_job`이 `mode=="patch"`이면 접수 전체 순회 대신
기간·유형 안 칸 실패 키(`rcept_no`,`dcm_no`)만 순회한다.
`target_count`는 그 키 수다. 문서 통째로 다시 추출한다(칸 단위 GET 없음).

`extract`/`resume`/`reparse` skip 규칙은 유지한다. `reparse`는 계속 `not_found`만.

## 5. 비범위

추출기 버전 올리기, 칸 하나만 재fetch, 날짜 LLM HTML, 유형별 12×3 표.
