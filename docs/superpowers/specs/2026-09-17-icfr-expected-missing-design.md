# 내부회계 skipped → 제도상없음 재분류 설계

날짜: 2026-09-17  
상태: 초안 (브레인스토밍 승인 반영)  
범위: `packages/web-api` — `classify_outcome`과 완전성 SQL만.
추출 leaf 선택·`icfr_status` 쓰기·facts 스키마는 바꾸지 않는다.

선행: [12묶음 모니터](2026-09-13-extract-field-bundle-monitor-design.md) §2·§5.1,
[입수·patch](2026-09-16-extract-intake-and-patch-design.md),
내부회계 추출 [D-6](2026-09-03-audit-icfr-opinion-extraction-design.md).  
이 스펙이 12묶음 모니터의 「제도상없음은 커뮤니케이션만」을 **내부회계에 한해** 덮어쓴다.

## 1. 목표

운영 화면에서 내부회계 `skipped`(같은 dcm에 leaf 없음)를 전부 실패로 세지 않는다.
외감법상 개별·연결 의무가 없는 문서만 `expected_missing`(제도상없음)으로 옮긴다.
파서를 고친 뒤 `patch`는 진짜 실패만 다시 GET한다.

성공 기준:

- 비상장 F001 `skipped`와 2022년 이전 F002 `skipped`는 12줄 표의 제도상없음이다.
- 그 행은 `field_partial`이 아니고 `patch` 대상도 아니다.
- 주권상장(코스피·코스닥·**코넥스**) F001 `skipped`, A001 `skipped`,
  2023년 이후 F002 `skipped`, 모든 `not_found`는 실패다.
- `icfr_status` 원값(`skipped`/`ok`/`not_found`)은 그대로다. 재추출하지 않아도 화면이 바뀐다.

## 2. 확정된 전제

| 항목 | 결정 |
|------|------|
| 손대는 층 | 묶음 칸 분류만. 추출기·selector·facts 컬럼·EXTRACTOR_VERSION 없음 |
| 상장 신호 | `corps.corp_cls` 현재 스냅샷. `stock_code` 쓰지 않음(폐지 후에도 남음) |
| 주권상장 | `corp_cls` ∈ {`Y`, `K`, `N`}. 코넥스(`N`)는 상장이다 |
| 비상장 | `E`, NULL, 빈 문자열, `corps` 조인 실패(미매핑) |
| 연도 | `parse_year_end(disclosures.year_end)`의 연. 없으면 `parse_rcept_dt(rcept_dt)`의 연 |
| 연결 컷 | F002 `skipped`이고 사업연도 ≥ 2023이면 실패, ≤ 2022이면 제도상없음 |
| 자산 구간 | 안 씀(5천억·2조·단계 시행은 연구 분석) |
| 연구 PUBLIC | dart-wrapper에 넣지 않음. `listing_spells` 복사·facts에 PUBLIC 컬럼 없음 |
| 패키지 | `packages/web-api` |

`corps`는 OpenDART 현재 스냅샷이다. 폐지 후 비상장이어도 `corp_cls`가 Y/K/N으로 남으면
F001 `skipped`는 **실패로 남을 수** 있다. 운영 화면의 보수적 오탐이며, 연구 마스터의
연도별 상장 이력으로 고치지 않는다.

`corps`가 비어 있으면 상장 F001 `skipped`가 제도상없음으로 숨는다.
완전성 화면을 쓰기 전에 기업개황 동기화가 선행이다.

## 3. 분류 규칙

`icfr_status == "ok"`(검토·감사·engagement `none` 포함) → 성공.  
`icfr_status == "not_found"`(leaf는 있는데 fetch·파싱 실패) → 실패.  
그 외 `skipped`가 아니면 실패.

`skipped`일 때만 아래를 본다. `report_type`은 `source_report_type`이다.

| 조건 | 칸 |
|------|-----|
| A001 | 실패 |
| F001 이고 주권상장(Y/K/N) | 실패 |
| F001 이고 그 외 | 제도상없음 |
| F002 이고 사업연도 ≥ 2023 | 실패 |
| F002 이고 사업연도 ≤ 2022 | 제도상없음 |
| F002 이고 연도를 둘 다 못 구함 | 실패 |

F002는 상장 여부를 보지 않는다. 연결 의무 연도만 본다.

선행 순서(`classify_outcome`과 SQL이 같아야 한다):

1. 종속기업 해당없음 (기존)
2. 커뮤니케이션 제도상없음 (기존)
3. **내부회계 제도상없음 (이번)**
4. 상태 `ok` → 성공
5. 그 외 → 실패

## 4. 코드 경계

| 단위 | 역할 |
|------|------|
| `classify_outcome` | `report_type`, `corp_cls`, `period_year`를 선택 인자로 받는다. 다른 묶음은 무시 |
| `add_fact_outcomes` | 잡 카운터. fact만으로는 부족하므로 같은 세 값을 호출부가 넘긴다 |
| `CompletenessService._bundle_predicates("icfr")` | facts ↔ disclosures ↔ `corps` LEFT JOIN. 집계·`field_partial`·`patch` 목록이 공유 |
| 추출 루프 | 변경 없음. `icfr_status=skipped`를 계속 쓴다 |
| UI·README | 「내부회계: 비상장 개별·연결 의무 전 skipped는 제도상없음」 한 줄 |

연도·상장 판정은 `field_bundles`의 순수 함수가 정본이다. `classify_outcome`이 이를 호출한다.
SQL은 커뮤니케이션과 같이 **같은 조건을 CASE로 복제**한다. 서비스에 두 번째 분류 함수를 두지 않는다.

조인:

- 완전성 쿼리는 이미 facts–disclosures를 `rcept_no`로 붙인다.
- `Corp.corp_code == Disclosure.corp_code` LEFT JOIN을 icfr 조건에만 쓰면 된다.
- `period_year`는 disclosures의 `year_end`·`rcept_dt`로 계산한다. facts에 당기 ISO 컬럼이 없다.

## 5. 화면·patch

12줄 표 칸 의미는 그대로다. 내부회계 실패 숫자가 줄고 제도상없음이 는다.

`field_partial` / `all_success` / `list_patch_document_keys`는 기존처럼
`classify_outcome == fail`만 구멍이다. 내부회계만 제도상없음이고 나머지 11칸이 성공이면
`all_success`다.

실패 목록·TSV의 `status`는 계속 `skipped`다. 칸만 제도상없음으로 옮긴다.

## 6. 테스트

`test_field_bundles.py`:

- F001 skipped + `corp_cls` E/None → `expected_missing`
- F001 skipped + Y/K/N → `fail` (N 포함)
- F002 skipped + 2022 → `expected_missing`, 2023 → `fail`, 연도 None → `fail`
- A001 skipped → `fail` (상장·연도와 무관)
- `not_found` → `fail`, `ok` → `ok`

`test_extract_admin_api.py`:

- 비상장 F001 skipped만 있는 eligible 행은 `field_partial=0`, 내부회계 `expected_missing=1`
- 상장(N 포함) F001 skipped는 `field_partial=1`, `patch` 키에 포함
- 기존 「icfr skipped면 field_partial」픽스처는 상장 `corp_cls`를 명시한다

완전성 SQL과 `classify_outcome`이 같은 픽스처에서 같은 칸을 고르는지 한 케이스로 고정한다.

## 7. 비범위

내부회계 leaf를 더 찾기, 자산·인원 예외, 연결 2조/5천억 단계, `listing_spells` 이관,
연구 `PUBLIC` 코딩, facts 재추출, 추출기 버전 올리기, 칸 단위 GET.
