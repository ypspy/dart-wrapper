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
| 2026-09-28 | [추출 12묶음 진단 설계](specs/2026-09-28-extraction-review-diagnosis-design.md) | spec |

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
