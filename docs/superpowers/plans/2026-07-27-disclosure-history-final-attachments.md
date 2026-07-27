# 공시 이력 목록 + 첨부 최종본만 추출 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상세검색 기본을 최종보고서 체크 해제(이력 포함)로 바꾸고, `#att`/`#doc`에서는 문서명별 최신(최종) 첨부만 남긴다.

**Architecture:** `list.js`는 `finalReport`를 기본 미전송하고 옵션일 때만 `recent`를 붙인다. `documents.js`에 `selectFinalAttachments(docs)`를 두고 `parseDetail`이 첨부 추출 직후·`dedupe` 전에 적용한다. 선정 키는 정규화 `name` + `reportDate` + `correctionType`.

**Tech Stack:** Node.js CommonJS, `node --test`, cheerio(기존)

**Spec:** `docs/superpowers/specs/2026-07-27-disclosure-history-final-attachments-design.md`

## Global Constraints

- 주석/Docstring/로그/테스트 설명: 한국어
- 본문 treeData 변경 없음
- Admin UI `finalReport` 토글 없음
- 커밋은 사용자 요청 시에만

---

## File map

| 파일 | 역할 |
|------|------|
| `packages/entry-extractor/src/list.js` | `finalReport` 기본 미전송 |
| `packages/entry-extractor/src/documents.js` | `selectFinalAttachments` + `parseDetail` 연동, export |
| `packages/entry-extractor/tests/test_final_report_list.js` | 목록 URL 파라미터 |
| `packages/entry-extractor/tests/test_select_final_attachments.js` | 첨부 최종본 필터 |
| `packages/entry-extractor/README.md` | 1단계·첨부 규칙 문서화 |

---

### Task 1: 목록 — `finalReport` 기본 미전송

**Files:**
- Create: `packages/entry-extractor/tests/test_final_report_list.js`
- Modify: `packages/entry-extractor/src/list.js`
- Test: `tests/test_final_report_list.js`

**Interfaces:**
- Consumes: `fetchDisclosureListResult({ reportType, startDate, endDate, finalReport?, fetcher? })`
- Produces: 기본 요청에 `finalReport` 없음; `finalReport: 'recent'`면 쿼리에 포함

- [ ] **Step 1: Write failing tests**

`packages/entry-extractor/tests/test_final_report_list.js`:

```js
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { fetchDisclosureListResult } = require('../src/list');

describe('fetchDisclosureListResult finalReport', () => {
  it('기본이면 요청 URL에 finalReport가 없다', async () => {
    const urls = [];
    await fetchDisclosureListResult({
      reportType: 'A001',
      startDate: '20260101',
      endDate: '20260101',
      maxTotal: 1,
      fetcher: async (url) => {
        urls.push(url);
        return '<html><body><div class="pageInfo">[1/1] [총 0건]</div><table><tbody id="tbody"></tbody></table></body></html>';
      },
    });
    assert.ok(urls.length >= 1);
    assert.equal(urls[0].includes('finalReport='), false);
  });

  it("finalReport: 'recent'이면 쿼리에 포함한다", async () => {
    const urls = [];
    await fetchDisclosureListResult({
      reportType: 'A001',
      startDate: '20260101',
      endDate: '20260101',
      maxTotal: 1,
      finalReport: 'recent',
      fetcher: async (url) => {
        urls.push(url);
        return '<html><body><div class="pageInfo">[1/1] [총 0건]</div><table><tbody id="tbody"></tbody></table></body></html>';
      },
    });
    assert.ok(urls[0].includes('finalReport=recent'));
  });
});
```

**Note:** `list.js`에 아직 `fetcher`가 없으면 Step 1 테스트가 네트워크를 칠 수 있다. 구현 시 `safeGet` 대신 optional `fetcher`를 추가한다 (첨부/상세와 동일 패턴). 시그니처:

```js
async function fetchDisclosureListResult({
  reportType,
  startDate,
  endDate,
  maxResults = 15,
  maxTotal = null,
  year = null,
  onProgress = null,
  finalReport = null, // 'recent' | null
  fetcher = null,
} = {})
```

요청 루프:

```js
const params = new URLSearchParams({
  currentPage: String(currentPage),
  maxResults: String(maxResults),
  maxLinks: '10',
  startDate,
  endDate,
  publicType: reportType,
});
if (finalReport === 'recent') params.set('finalReport', 'recent');
const url = `${BASE_URL}/dsab007/detailSearch.ax?${params.toString()}`;
const response = fetcher
  ? { data: await fetcher(url) }
  : await safeGet(url);
const html = typeof response === 'string' ? response : response.data;
// cheerio.load(html) …
```

`fetcher`가 문자열 HTML을 바로 반환하면 `cheerio.load(await fetcher(url))`로 단순화해도 된다.

- [ ] **Step 2: Run tests — expect fail**

```bash
cd packages/entry-extractor
node --test tests/test_final_report_list.js
```

Expected: FAIL (기본 URL에 아직 `finalReport=recent` 또는 fetcher 미지원)

- [ ] **Step 3: Implement list.js changes** (위 시그니처·파라미터·fetcher)

- [ ] **Step 4: Re-run tests — expect PASS**

```bash
node --test tests/test_final_report_list.js
```

- [ ] **Step 5: Commit (사용자 요청 시만)**

```bash
git add packages/entry-extractor/src/list.js packages/entry-extractor/tests/test_final_report_list.js
git commit -m "feat(entry-extractor): 목록 기본에서 finalReport 제거"
```

---

### Task 2: `selectFinalAttachments` + 단위 테스트

**Files:**
- Create: `packages/entry-extractor/tests/test_select_final_attachments.js`
- Modify: `packages/entry-extractor/src/documents.js` (`selectFinalAttachments` 추가·export)
- Test: `tests/test_select_final_attachments.js`

**Interfaces:**
- Consumes: `object[]` documents (`source`, `name`, `reportDate`, `correctionType`, …)
- Produces: `selectFinalAttachments(documents: object[]): object[]` — body는 그대로, attachment는 name당 1건

- [ ] **Step 1: Write failing tests**

```js
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { selectFinalAttachments } = require('../src/documents');

function att(overrides) {
  return {
    source: 'attachment',
    name: '감사보고서',
    reportDate: '',
    correctionType: '',
    rcpNo: '1',
    dcmNo: '1',
    ...overrides,
  };
}

describe('selectFinalAttachments', () => {
  it('같은 이름이면 더 늦은 reportDate만 남긴다', () => {
    const out = selectFinalAttachments([
      att({ dcmNo: 'a', reportDate: '2026.03.16', rcpNo: 'old' }),
      att({ dcmNo: 'b', reportDate: '2026.03.25', rcpNo: 'new', correctionType: '정정' }),
    ]);
    assert.equal(out.length, 1);
    assert.equal(out[0].dcmNo, 'b');
  });

  it('날짜가 같으면 correctionType 있는 쪽을 고른다', () => {
    const out = selectFinalAttachments([
      att({ dcmNo: 'a', reportDate: '2026.03.25' }),
      att({ dcmNo: 'b', reportDate: '2026.03.25', correctionType: '기재정정' }),
    ]);
    assert.equal(out[0].dcmNo, 'b');
  });

  it('이름이 다르면 둘 다 유지한다', () => {
    const out = selectFinalAttachments([
      att({ name: '감사보고서', dcmNo: '1', reportDate: '2026.03.25' }),
      att({ name: '정관', dcmNo: '2', reportDate: '2026.03.16' }),
    ]);
    assert.equal(out.length, 2);
  });

  it('body 문서는 필터하지 않는다', () => {
    const body = { source: 'body', name: '사업보고서', dcmNo: '9', rcpNo: 'x' };
    const out = selectFinalAttachments([
      body,
      att({ dcmNo: 'a', reportDate: '2026.03.16' }),
      att({ dcmNo: 'b', reportDate: '2026.03.25' }),
    ]);
    assert.equal(out.filter((d) => d.source === 'body').length, 1);
    assert.equal(out.filter((d) => d.source === 'attachment').length, 1);
    assert.equal(out.find((d) => d.source === 'attachment').dcmNo, 'b');
  });

  it('전원 무날짜면 DOM 순 첫 건을 유지한다', () => {
    const out = selectFinalAttachments([
      att({ dcmNo: 'first' }),
      att({ dcmNo: 'second' }),
    ]);
    assert.equal(out[0].dcmNo, 'first');
  });
});
```

- [ ] **Step 2: Run — expect FAIL** (`selectFinalAttachments` undefined)

```bash
node --test tests/test_select_final_attachments.js
```

- [ ] **Step 3: Implement in `documents.js`**

```js
/** YYYY.MM.DD → 비교용 숫자(없으면 -1) */
function reportDateRank(reportDate) {
  const m = String(reportDate || '').match(/(\d{4})\.(\d{2})\.(\d{2})/);
  if (!m) return -1;
  return Number(m[1]) * 10000 + Number(m[2]) * 100 + Number(m[3]);
}

/**
 * 첨부/관련 문서 중 동일 name은 최종본 1건만 남긴다.
 * 우선순위: reportDate 최신 → correctionType 있음 → 기존 순서(안정).
 */
function selectFinalAttachments(documents) {
  const body = [];
  const byName = new Map();
  for (const doc of documents || []) {
    if (doc.source !== 'attachment') {
      body.push(doc);
      continue;
    }
    const key = doc.name || '';
    if (!byName.has(key)) byName.set(key, []);
    byName.get(key).push(doc);
  }
  const attachments = [];
  for (const group of byName.values()) {
    let best = group[0];
    for (let i = 1; i < group.length; i++) {
      const cand = group[i];
      const br = reportDateRank(best.reportDate);
      const cr = reportDateRank(cand.reportDate);
      if (cr > br) {
        best = cand;
        continue;
      }
      if (cr === br) {
        const bHas = !!best.correctionType;
        const cHas = !!cand.correctionType;
        if (cHas && !bHas) best = cand;
      }
    }
    attachments.push(best);
  }
  return [...body, ...attachments];
}
```

`module.exports`에 `selectFinalAttachments` 추가.

- [ ] **Step 4: Run — expect PASS**

```bash
node --test tests/test_select_final_attachments.js
```

- [ ] **Step 5: Commit (사용자 요청 시만)**

---

### Task 3: `parseDetail`에 필터 연결

**Files:**
- Modify: `packages/entry-extractor/src/documents.js` (`parseDetail`)
- Modify or Create: `packages/entry-extractor/tests/test_parse_detail_final_attachments.js`
- Test: 동일

**Interfaces:**
- Consumes: Task 2 `selectFinalAttachments`
- Produces: `parseDetail` documents가 첨부 최종본만 포함

- [ ] **Step 1: Failing integration test**

`#att`에 같은 이름 두 option이 있는 HTML fixture로 `parseDetail({ fetcher })` 호출 → attachment documents length 1, 최신 dcmNo.

`tests/fixtures/html.js`의 `attachmentSelectHtml`을 확장하거나 테스트 내 인라인 HTML:

```html
<select id="att">
  <option value="rcpNo=OLD&dcmNo=111">2026.03.16 감사보고서</option>
  <option value="rcpNo=NEW&dcmNo=222">2026.03.25 [정정] 감사보고서</option>
</select>
<select id="doc"></select>
<script>var treeData = [];</script>
```

본문 tree가 비어도 `attachments: true`면 documents에 첨부만 옴.

- [ ] **Step 2: Wire in parseDetail**

```js
if (attachments) {
  documents.push(
    ...extractAttachments($, $('#att option'), false),
    ...extractAttachments($, $('#doc option'), true)
  );
}
return {
  tree,
  sections,
  documents: dedupe(selectFinalAttachments(documents)),
};
```

순서는 **selectFinal → dedupe** (스펙: dedupe 유지).

- [ ] **Step 3: `npm test` 전부 PASS**

- [ ] **Step 4: Commit (사용자 요청 시만)**

---

### Task 4: README + 스펙 상태

**Files:**
- Modify: `packages/entry-extractor/README.md` (1단계 절)
- Modify: `docs/superpowers/specs/2026-07-27-disclosure-history-final-attachments-design.md` → `상태: 구현 완료`

- [ ] **Step 1: README**

1단계 아래에 추가:

```markdown
**최종보고서 체크:** 기본은 체크 해제와 동일(`finalReport` 미전송)이라
최종·정정 전 접수가 모두 목록에 포함됩니다. 최종만 보려면
`finalReport: 'recent'`를 넘기세요.

**첨부 최종본:** `#att`/`#doc`에서 같은 문서명은 `reportDate`가 가장 늦은
1건만 펼칩니다(동일 날짜면 `[정정]`/`[기재정정]` 우선).
```

- [ ] **Step 2: 스펙 상태 `구현 완료`**

- [ ] **Step 3: `npm test`**

- [ ] **Step 4: Commit (사용자 요청 시만)**

---

## Spec coverage

| Spec | Task |
|------|------|
| 목록 finalReport 기본 미전송 | Task 1 |
| finalReport recent 옵션 | Task 1 |
| 첨부 name별 최신/정정 | Task 2–3 |
| #doc 동일 | Task 3 (extractAttachments doc path) |
| README | Task 4 |
| 본문 불변 | 코드 미변경 |

## Placeholder scan

없음.
