# 접수 스코프 첨부 추출 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `#att`/`#doc` 첨부를 이름별 전역 최신이 아니라 **현재 접수 `rcpNo`와 일치하는 option만** 남긴다. 본문 `treeData`는 변경하지 않는다.

**Architecture:** `selectFinalAttachments` / `reportDateRank`를 제거하고 `selectReceptionAttachments(documents, rceptNo)`로 교체한다. `parseDetail`은 `disclosure.rcept_no` 또는 URL의 `rcpNo`로 접수번호를 구한 뒤 첨부만 필터한다. `rceptNo`를 전혀 못 구하면 첨부는 0건(본문만 유지)으로 두어 전량 오입수를 막는다.

**Tech Stack:** Node.js CommonJS, `node --test`, cheerio(기존)

**Spec:** `docs/superpowers/specs/2026-07-28-reception-scoped-attachments-design.md`

## Global Constraints

- 주석/Docstring/로그/테스트 설명: 한국어
- 본문 `treeData` / `toBodyDocuments` 변경 없음 (ATT 필터만)
- Admin UI·web-api·DB 마이그레이션 없음
- 커밋은 사용자 요청 시에만 (플랜 Step의 Commit은 스테이징 제안만, 실행 시 커밋하지 않음)

---

## File map

| 파일 | 역할 |
|------|------|
| `packages/entry-extractor/src/documents.js` | `selectReceptionAttachments`, `resolveReceptionRcpNo`, `parseDetail` 연동, 구 API 제거 |
| `packages/entry-extractor/tests/test_select_reception_attachments.js` | 단위 테스트 (구 `test_select_final_attachments.js` 대체) |
| `packages/entry-extractor/tests/test_parse_detail_reception_attachments.js` | `parseDetail` 연동 테스트 (구 final 테스트 대체) |
| `packages/entry-extractor/README.md` | 첨부 규칙을 접수 스코프로 수정 |
| `packages/entry-extractor/src/index.js` | 필요 시 export 갱신 (현재 `selectFinalAttachments` 미export면 documents만) |

---

### Task 1: `selectReceptionAttachments` (TDD)

**Files:**
- Create: `packages/entry-extractor/tests/test_select_reception_attachments.js`
- Delete: `packages/entry-extractor/tests/test_select_final_attachments.js`
- Modify: `packages/entry-extractor/src/documents.js` (`reportDateRank`·`selectFinalAttachments` 제거, 신규 함수 추가·export)

**Interfaces:**
- Consumes: `documents: object[]` (`source`, `rcpNo`, …), `rceptNo: string`
- Produces:
  - `selectReceptionAttachments(documents, rceptNo): object[]`
  - `resolveReceptionRcpNo(disclosure, disclosureUrl): string` (Task 2에서도 사용)
  - export에서 `selectFinalAttachments` 제거, `selectReceptionAttachments`·`resolveReceptionRcpNo` 추가

- [ ] **Step 1: Write the failing tests**

`packages/entry-extractor/tests/test_select_reception_attachments.js`:

```js
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const {
  selectReceptionAttachments,
  resolveReceptionRcpNo,
} = require('../src/documents');

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

describe('selectReceptionAttachments', () => {
  it('rcpNo가 접수와 같은 첨부만 남긴다', () => {
    const out = selectReceptionAttachments(
      [
        att({ dcmNo: 'same', rcpNo: '20170331001902' }),
        att({ dcmNo: 'other', rcpNo: '20170908000524', reportDate: '2017.09.08' }),
      ],
      '20170331001902'
    );
    assert.equal(out.length, 1);
    assert.equal(out[0].dcmNo, 'same');
  });

  it('같은 날짜·다른 rcpNo면 각자 접수에만 남는다', () => {
    const docs = [
      att({ dcmNo: 'a', rcpNo: '20160330004732', reportDate: '2016.03.30', name: '감사보고서' }),
      att({
        dcmNo: 'b',
        rcpNo: '20160330004731',
        reportDate: '2016.03.30',
        name: '연결감사보고서',
      }),
    ];
    const a = selectReceptionAttachments(docs, '20160330004732');
    const b = selectReceptionAttachments(docs, '20160330004731');
    assert.deepEqual(
      a.map((d) => d.dcmNo),
      ['a']
    );
    assert.deepEqual(
      b.map((d) => d.dcmNo),
      ['b']
    );
  });

  it('SAME 첨부가 없으면 첨부 0건', () => {
    const out = selectReceptionAttachments(
      [att({ dcmNo: 'x', rcpNo: 'OTHER' })],
      '20170405000474'
    );
    assert.equal(out.length, 0);
  });

  it('body 문서는 필터하지 않는다', () => {
    const body = { source: 'body', name: '사업보고서', dcmNo: '9', rcpNo: 'x' };
    const out = selectReceptionAttachments(
      [body, att({ dcmNo: 'a', rcpNo: 'R1' }), att({ dcmNo: 'b', rcpNo: 'R2' })],
      'R1'
    );
    assert.equal(out.filter((d) => d.source === 'body').length, 1);
    assert.equal(out.filter((d) => d.source === 'attachment').length, 1);
    assert.equal(out.find((d) => d.source === 'attachment').dcmNo, 'a');
  });

  it('rceptNo가 비면 첨부는 모두 제외하고 body만 남긴다', () => {
    const body = { source: 'body', name: '사업보고서', rcpNo: 'x' };
    const out = selectReceptionAttachments(
      [body, att({ dcmNo: 'a', rcpNo: 'R1' })],
      ''
    );
    assert.equal(out.length, 1);
    assert.equal(out[0].source, 'body');
  });
});

describe('resolveReceptionRcpNo', () => {
  it('disclosure.rcept_no를 우선한다', () => {
    assert.equal(
      resolveReceptionRcpNo({ rcept_no: '111' }, 'https://x/main.do?rcpNo=222'),
      '111'
    );
  });

  it('없으면 URL rcpNo를 쓴다', () => {
    assert.equal(
      resolveReceptionRcpNo(null, 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20170331001902'),
      '20170331001902'
    );
  });

  it('둘 다 없으면 빈 문자열', () => {
    assert.equal(resolveReceptionRcpNo(null, 'https://example.test/'), '');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (PowerShell, `packages/entry-extractor`에서):

```powershell
node --test tests/test_select_reception_attachments.js
```

Expected: FAIL (`selectReceptionAttachments` / `resolveReceptionRcpNo` is not a function 또는 require 오류)

- [ ] **Step 3: Implement**

`packages/entry-extractor/src/documents.js`에서:

1. `reportDateRank`와 `selectFinalAttachments` 함수 전체 삭제  
2. 다음 추가:

```js
/**
 * 상세 URL·disclosure에서 현재 접수번호(rcpNo)를 구한다.
 * disclosure.rcept_no 우선, 없으면 URL의 rcpNo.
 * @param {object|null} disclosure
 * @param {string} disclosureUrl
 * @returns {string}
 */
function resolveReceptionRcpNo(disclosure, disclosureUrl) {
  if (disclosure?.rcept_no) return String(disclosure.rcept_no);
  const m = String(disclosureUrl || '').match(/[?&]rcpNo=(\d+)/i);
  return m ? m[1] : '';
}

/**
 * 첨부/관련 문서 중 현재 접수(rcpNo)에 속한 것만 남긴다.
 * 본문(source !== 'attachment')은 그대로 둔다.
 * rceptNo가 비면 첨부는 전부 제외한다(전량 오입수 방지).
 *
 * @param {object[]} documents
 * @param {string} rceptNo
 * @returns {object[]}
 */
function selectReceptionAttachments(documents, rceptNo) {
  const want = String(rceptNo || '');
  const out = [];
  for (const doc of documents || []) {
    if (doc.source !== 'attachment') {
      out.push(doc);
      continue;
    }
    if (want && doc.rcpNo === want) out.push(doc);
  }
  return out;
}
```

3. `module.exports`에서 `selectFinalAttachments` → `selectReceptionAttachments`, `resolveReceptionRcpNo` 추가

- [ ] **Step 4: Delete old unit tests**

Delete `packages/entry-extractor/tests/test_select_final_attachments.js`

- [ ] **Step 5: Run tests to verify they pass**

```powershell
node --test tests/test_select_reception_attachments.js
```

Expected: PASS (전체)

- [ ] **Step 6: Stage (커밋은 사용자 요청 시)**

```powershell
git add packages/entry-extractor/src/documents.js packages/entry-extractor/tests/test_select_reception_attachments.js
git add -u packages/entry-extractor/tests/test_select_final_attachments.js
```

---

### Task 2: `parseDetail`에 접수 스코프 연결

**Files:**
- Create: `packages/entry-extractor/tests/test_parse_detail_reception_attachments.js`
- Delete: `packages/entry-extractor/tests/test_parse_detail_final_attachments.js`
- Modify: `packages/entry-extractor/src/documents.js` (`parseDetail` 본문)

**Interfaces:**
- Consumes: `resolveReceptionRcpNo`, `selectReceptionAttachments` (Task 1)
- Produces: `parseDetail` 반환 `documents`가 접수 스코프 첨부 + 본문(변경 없음)

- [ ] **Step 1: Write the failing tests**

`packages/entry-extractor/tests/test_parse_detail_reception_attachments.js`:

```js
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { parseDetail } = require('../src/documents');

const HTML = `
<html><body>
<select id="att">
  <option value="null">+첨부선택+</option>
  <option value="rcpNo=20170908000524&dcmNo=5781023">2017.09.08 [정정] 연결감사보고서</option>
  <option value="rcpNo=20170331001902&dcmNo=5528618">2017.03.31 감사보고서</option>
  <option value="rcpNo=20170331001902&dcmNo=5528619">2017.03.31 연결감사보고서</option>
</select>
<select id="doc"></select>
<script>var treeData = [];</script>
</body></html>`;

describe('parseDetail 접수 스코프 첨부', () => {
  it('disclosure.rcept_no와 같은 rcpNo 첨부만 남긴다', async () => {
    const detail = await parseDetail(
      'https://example.test/main.do?rcpNo=20170331001902',
      {
        disclosure: { rcept_no: '20170331001902' },
        body: false,
        attachments: true,
        fetcher: async () => HTML,
      }
    );
    const att = detail.documents.filter((d) => d.source === 'attachment');
    assert.equal(att.length, 2);
    assert.ok(att.every((d) => d.rcpNo === '20170331001902'));
    assert.ok(!att.some((d) => d.dcmNo === '5781023'));
  });

  it('첨부정정 행은 자기 rcpNo 1건만', async () => {
    const html = `
<html><body>
<select id="att">
  <option value="rcpNo=20160330004732&dcmNo=5032113">2016.03.30 [정정] 감사보고서</option>
  <option value="rcpNo=20160330004731&dcmNo=5032112">2016.03.30 [정정] 연결감사보고서</option>
  <option value="rcpNo=20160330004553&dcmNo=5031332">2016.03.30 감사보고서</option>
</select>
<select id="doc"></select>
<script>var treeData = [];</script>
</body></html>`;
    const detail = await parseDetail(
      'https://example.test/main.do?rcpNo=20160330004732',
      {
        disclosure: { rcept_no: '20160330004732' },
        body: false,
        attachments: true,
        fetcher: async () => html,
      }
    );
    const att = detail.documents.filter((d) => d.source === 'attachment');
    assert.equal(att.length, 1);
    assert.equal(att[0].dcmNo, '5032113');
  });

  it('disclosure 없이 URL rcpNo로 필터한다', async () => {
    const detail = await parseDetail(
      'https://example.test/main.do?rcpNo=20170331001902',
      { body: false, attachments: true, fetcher: async () => HTML }
    );
    const att = detail.documents.filter((d) => d.source === 'attachment');
    assert.equal(att.length, 2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
node --test tests/test_parse_detail_reception_attachments.js
```

Expected: FAIL (아직 `selectFinalAttachments`라 이후 정정 `5781023`이 남거나 건수 불일치)

- [ ] **Step 3: Wire parseDetail**

`parseDetail` 반환부를 다음처럼 교체:

```js
  const rceptNo = resolveReceptionRcpNo(disclosure, disclosureUrl);

  return {
    tree,
    sections,
    documents: dedupe(selectReceptionAttachments(documents, rceptNo)),
  };
```

- [ ] **Step 4: Delete old parseDetail final 테스트**

Delete `packages/entry-extractor/tests/test_parse_detail_final_attachments.js`

- [ ] **Step 5: Run unit + parseDetail tests**

```powershell
node --test tests/test_select_reception_attachments.js tests/test_parse_detail_reception_attachments.js
```

Expected: PASS

- [ ] **Step 6: Full package test**

```powershell
npm test
```

Expected: PASS (구 final 테스트 파일 없음, 신규 통과)

- [ ] **Step 7: Stage**

```powershell
git add packages/entry-extractor/src/documents.js packages/entry-extractor/tests/test_parse_detail_reception_attachments.js
git add -u packages/entry-extractor/tests/test_parse_detail_final_attachments.js
```

---

### Task 3: README·스펙 상태 문구

**Files:**
- Modify: `packages/entry-extractor/README.md` (첨부 최종본 → 접수 스코프)
- Modify: `docs/superpowers/specs/2026-07-28-reception-scoped-attachments-design.md` (상태: 구현 완료로 — 구현 직후; 플랜 작성 시점에는 Step에서만)

**Interfaces:** 없음 (문서만)

- [ ] **Step 1: Update README attachment section**

다음을 반영하도록 문장 교체 (경로·표 위치는 기존 “첨부 최종본” 단락):

- 「첨부 최종본: 이름별 최신」→  
  **첨부 접수 스코프:** `#att`/`#doc` 첨부 option 중 **`rcpNo`가 현재 목록 행 `rcept_no`와 같은 것만** 남긴다. 이후·이전 접수 첨부는 해당 이력 행에서 입수한다. 본문 `treeData`는 필터하지 않는다.
- API 표: `selectFinalAttachments` → `selectReceptionAttachments(documents, rceptNo)`
- `parseDetail` 설명: 「첨부 최종본 필터」→「첨부 접수 스코프 필터」
- 한계: 「옛 버전은 최종본 필터로」→「타 접수 option은 접수 스코프로 제외」

예시 교체 문단:

```markdown
**첨부 접수 스코프:** `#att`/`#doc`에서 option의 `rcpNo`가 현재 공시
`rcept_no`와 **같은 것만** 남깁니다. 같은 날이라도 다른 접수(첨부정정·최초 등)의
option은 제외되며, 그 내용은 목록의 해당 접수 행을 펼칠 때 입수합니다.
본문(`treeData`)에는 이 필터를 적용하지 않습니다.
```

표 행:

```markdown
| 타 접수·이후 정정 option | `selectReceptionAttachments`에서 제외 |
```

API:

```markdown
| `selectReceptionAttachments(documents, rceptNo)` | 현재 접수 rcpNo 첨부만 유지 |
```

- [ ] **Step 2: Mark design status after code is done**

스펙 상단 `상태: 브레인스토밍 승인 (구현 전)` → `상태: 구현 완료` (Task 1–2 완료 후)

- [ ] **Step 3: Run full tests once more**

```powershell
cd packages/entry-extractor
npm test
```

Expected: PASS

- [ ] **Step 4: Stage docs**

```powershell
git add packages/entry-extractor/README.md docs/superpowers/specs/2026-07-28-reception-scoped-attachments-design.md
```

---

## Spec coverage (self-review)

| Spec 요구 | Task |
|-----------|------|
| `rcpNo === rcept_no` 필터 (A) | Task 1–2 |
| 본문 treeData 불변 | Global + Task 2 (body 경로 미수정) |
| SAME 0건 → 첨부 빈값 | Task 1 테스트 |
| 같은날 다른 첨부정정 분리 | Task 1–2 JW fixture |
| 최초에서 이후 정정 제외 | Task 2 |
| rceptNo 없으면 첨부 0 | Task 1 |
| `selectFinalAttachments` 폐기 | Task 1 delete + export |
| README | Task 3 |
| 목록 finalReport / web-api | 범위 밖 (변경 없음) |

Placeholder scan: 없음.  
타입/이름: `selectReceptionAttachments` · `resolveReceptionRcpNo` 전 태스크 일치.
