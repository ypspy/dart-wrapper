# Catalog 응답 필드 보강 설계

날짜: 2026-07-27  
상태: 승인 (구현)

## 목표

공시 목록/단건·leaf 목록 Catalog JSON에 DB에 있는 공시 메타를 빠짐없이 노출한다.

## 결정

1. `DisclosureSummary`에 `correction_type`, `submitter`, `year_end`, `bsns_year` 추가
2. `GET .../entries` 응답에 `disclosure: DisclosureSummary` 포함, `all_entries` 유지
3. 최상위 `rcp_no` / `report_type`은 `disclosure`로 대체 (중복 제거)
4. `created_at` / `updated_at` 제외
5. leaf `EntrySummary`는 현행(추출 스키마 전 feature) 유지

## 응답 형태

```json
// GET /disclosures, GET /disclosures/{rcp_no}
{
  "rcp_no": "...",
  "corp_code": "...",
  "corp_name": "...",
  "report_nm": "...",
  "report_type": "...",
  "correction_type": "...",
  "submitter": "...",
  "rcept_dt": "...",
  "year_end": "...",
  "bsns_year": null,
  "entry_count": 147,
  "disclosure_url": "..."
}

// GET /disclosures/{rcp_no}/entries
{
  "disclosure": { /* DisclosureSummary */ },
  "all_entries": [ /* EntrySummary[] */ ]
}
```

## 범위 밖

- HTML catalog 페이지 (후속)
- Viewer JSON 변경
- DB 스키마 변경
