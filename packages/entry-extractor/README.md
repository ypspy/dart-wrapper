# Entry Extractor

`dart-wrapper` 모노레포의 **대상 문서 단위(entry) 추출** 패키지 (`@dart-wrapper/entry-extractor`)입니다.

공시 문서 컨테이너(접수 단위)를 찾아, 그 안의 구성 문서·섹션을 leaf까지 펼친 뒤, 목록에서 얻은 features와 합쳐 **flat entry**로 만듭니다.

> OpenDART OpenAPI가 아니라, 상세검색/상세페이지 HTML을 스크래핑하는 방식입니다.

## 설치

모노레포 루트에서:

```bash
npm install
```

패키지를 직접 쓰려면:

```js
const { collectEntries } = require('@dart-wrapper/entry-extractor');
```

의존성: `axios`, `cheerio`

## 빠른 시작 (권장)

최종 산출물은 **leaf 엔트리**입니다. 목록 features + 문서/섹션 정보가 한 객체로 합쳐집니다.

```js
const { collectEntries } = require('./src');

const entries = await collectEntries({
  reportType: 'F001',
  startDate: '20260724',
  endDate: '20260724',
  maxTotal: 10,
});

// entries[0].entry_id  → '20260724000650_11495035_5'
// entries[0].path      → ['(첨부)재무제표', '재무상태표']
// entries[0].viewer_url → 실제 내용 접근 URL
```

기본값: `leafOnly: true`, `includeAttachments: true`

## 엔트리 스키마

```js
{
  entry_id: '20260724000650_11495035_5', // rcept_no_dcmNo_ele_id (첨부는 ..._att)
  // —— 1단계 공시 features ——
  reportType: 'F001',
  rcept_no: '20260724000650',
  correction_type: '기재정정',
  report_nm: '감사보고서',
  year_end: '(2025.12)',
  corp_code: '00224628',
  corp_name: '제이에스어소시에이츠',
  submitter: '한울회계법인',
  rcept_dt: '2026.07.24',
  // —— 문서/섹션 ——
  disclosure_url: 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=...',
  source: 'body',              // 'body' | 'attachment'
  dcmNo: '11495035',
  document_name: '감사보고서',
  section_name: '재무상태표',
  section_original_name: '재 무 상 태 표',
  depth: 2,
  is_leaf: true,
  parent_ele_id: '4',
  ele_id: '5',
  offset: '29168',
  length: '36783',
  dtd: 'dart4.xsd',
  path: ['(첨부)재무제표', '재무상태표'],
  viewer_url: 'https://dart.fss.or.kr/report/viewer.do?...'
}
```

`entry_id`는 저장·조회·중복 제거용 키입니다. 저장 대상은 entry(메타·주소)이며, 공시 원문 본문은 이 모듈의 범위가 아닙니다.

## 단계별 API

### 1단계 — 공시 목록 수집

```js
const { fetchDisclosureList } = require('./src');

const disclosures = await fetchDisclosureList({
  reportType: 'A001',
  startDate: '20240101',
  endDate: '20241231',
  year: 2024,
  maxTotal: 100,
  onProgress: (info) => console.log(info),
});
```

### 2단계 — 목차 트리 + 문서 URL 파싱

```js
const { parseDetail } = require('./src');

const { tree, sections, documents } = await parseDetail(disclosures[0].url, {
  disclosure: disclosures[0],
});
```

DART HTML의 `node1['children'].push(node2)` 관계를 그대로 반영합니다.

**이름 보정**
- `감 사 보 고 서` → `감사보고서` (글자 사이 공백 정규화)
- 본문 문서명: 목차에 정정신고만 있으면 목록의 `report_nm`으로 교체
- 목차의 `정정신고(보고)` 노드는 구조 보존을 위해 유지

| source | 설명 | 출처 |
|--------|------|------|
| `body` | 공시 본문 | `treeData` 목차 |
| `attachment` | 첨부/관련 문서 | `#att` / `#doc` |

### 3단계 — leaf 엔트리 생성

```js
const { buildEntries, collectEntries } = require('./src');

// 이미 파싱한 결과로
const entries = buildEntries(disclosure, detail, {
  leafOnly: true,           // 최하단만 (기본)
  includeAttachments: true, // 첨부 포함 (기본)
});

// 또는 1·2·3단계 통합
const all = await collectEntries({ reportType: 'F001', startDate, endDate });
```

중간 노드(`(첨부)재무제표` 등)까지 필요하면 `leafOnly: false`.

## 첨부문서 leaf

`includeAttachments: true`(기본)이면 `#att`/`#doc`의 첨부 `dcmNo` 중 **본문 treeData에 없는 것**만
추가로 `main.do?rcpNo&dcmNo`를 열어 목차를 leaf까지 펼칩니다.

| 경우 | 결과 |
|------|------|
| 첨부 목차 있음 | `source: 'attachment'` leaf (`entry_id=rcept_no_dcmNo_eleId`) |
| 목차 없음·fetch 실패 | 문서 단위 1건 (`..._att`) |
| 본문 트리에 이미 있는 dcmNo | 재요청·첨부 entry 없음 (body leaf만) |

`buildEntries`에 `attachmentTrees`를 직접 넘기면 HTTP 없이 테스트·재가공할 수 있습니다.
통합 경로는 `buildEntriesFromDisclosure` / `collectEntries`를 사용하세요.

## CLI 브릿지 (Python 연동)

`bin/collect-entries.js`는 Python Admin 수집기가 호출하는 브릿지입니다.
stdin으로 JSON 파라미터를 받고, stdout에는 엔트리 배열 JSON만 출력합니다(진행 로그는 stderr).

```bash
echo {"report_type":"F001","start_date":"20260724","end_date":"20260724","max_total":2} | node bin/collect-entries.js
```

| 파라미터 | 설명 |
|----------|------|
| `report_type` | 공시 유형 (필수) |
| `start_date` / `end_date` | YYYYMMDD (필수) |
| `max_total` | 최대 수집 건수 (옵션) |
| `include_attachments` | 첨부 포함 여부 (기본 true) |

## 예제 실행

```bash
npm test                                 # 단위 테스트
npm run example                          # 목록 + 목차 트리
npm run example:entries                  # leaf 엔트리
node examples/entries.js F001 20260724 20260724 2
```

## API

| 함수 | 설명 |
|------|------|
| `collectEntries(params)` | 목록→상세→첨부 leaf→엔트리 통합 수집 (권장) |
| `buildEntriesFromDisclosure(disclosure, options)` | 공시 1건 상세+첨부 펼침→엔트리 |
| `buildEntries(disclosure, detail, options)` | 파싱 결과(+`attachmentTrees`)로 엔트리 생성 |
| `collectAttachmentTrees(documents, bodyTree, options)` | 첨부 전용 dcmNo 목차 수집 |
| `parseAttachmentDetail(rcpNo, dcmNo, options)` | 첨부 dcmNo 상세 목차 파싱 |
| `makeEntryId({ rcept_no, dcmNo, ele_id, source })` | 저장·중복 제거용 `entry_id` 생성 |
| `fetchDisclosureList(params)` | 상세검색 목록 수집 |
| `parseDetail(url, options)` | `tree` + `sections` + `documents` |
| `parseTree(url, options)` | 목차 트리만 |
| `parseSections(url, options)` | flat 섹션 (`parentEleId` 포함) |
| `parseDocuments(url, options)` | dcmNo 단위 문서 |
| `flattenTree(tree)` | 트리 → flat 배열 |
| `correctName(name, disclosure)` | 제목 정규화·보정 |

## 주의

- DART 서버 부하를 고려해 요청 간 기본 1초 지연 + 지수 백오프 재시도가 적용됩니다.
- 첨부 전용 `dcmNo`마다 상세 요청이 추가되므로 공시당 소요 시간이 늘 수 있습니다.
- HTML 구조 변경 시 셀렉터/`treeData` 파싱 정규식 조정이 필요할 수 있습니다.
- 주말·공휴일에는 접수 건이 없어 결과가 0건입니다.
