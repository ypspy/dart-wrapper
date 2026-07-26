# 첨부문서 leaf entry 추출 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 첨부(`#att`/`#doc`) 전용 `dcmNo`를 `main.do`로 재파싱해 본문과 같은 leaf entry로 저장하고, 목차가 없으면 `..._att` fallback을 유지한다.

**Architecture:** `buildEntries`는 HTTP 없이 `attachmentTrees`를 주입받아 첨부 leaf/fallback을 만든다. `collectAttachmentTrees`(또는 동등)가 body에 없는 첨부 `dcmNo`만 `parseAttachmentDetail`로 fetch한다. `collectEntries`와 CLI `extract` 모드가 동일 오케스트레이션을 쓴다.

**Tech Stack:** Node.js (CommonJS), cheerio, axios, Node built-in test runner (`node --test`)

**Spec:** `docs/superpowers/specs/2026-07-26-attachment-leaf-entries-design.md`

## Global Constraints

- 작업 패키지: `packages/entry-extractor` (web-api 변경 금지)
- 주석·Docstring·로그·stderr 메시지는 **한국어**
- 실제 DART 네트워크 호출 없이 단위 테스트 (fixture HTML + mock fetcher)
- `includeAttachments`만 사용. `expandAttachments` 신규 플래그 금지
- 본문 트리에 있는 `dcmNo`는 첨부 fetch·attachment entry 모두 금지
- 목차 있으면 leaf만 (`..._att` 없음). 목차 없거나 fetch 실패면 `..._att` fallback
- 첨부 fetch 실패는 해당 `dcmNo`만 fallback — 공시 전체 실패로 올리지 않음
- 요청 지연·재시도는 기존 `safeGet` 경로 재사용
- entry 스키마 필드 집합 변경 금지 (`source` 값 `'attachment'` 유지)

## File Structure

| Path | Responsibility |
|------|----------------|
| `packages/entry-extractor/src/documents.js` | `collectBodyDcmNos`, `parseAttachmentDetail` 추가·export |
| `packages/entry-extractor/src/entries.js` | `attachmentTrees` 지원, `collectAttachmentTrees`, `buildEntriesFromDisclosure` |
| `packages/entry-extractor/src/index.js` | 신규 심볼 export |
| `packages/entry-extractor/bin/collect-entries.js` | `extract` 모드도 첨부 leaf 펼침 |
| `packages/entry-extractor/package.json` | `"test": "node --test"` |
| `packages/entry-extractor/tests/fixtures/*.js` | treeData / 빈 HTML / select HTML 헬퍼 |
| `packages/entry-extractor/tests/test_build_entries_attachments.js` | buildEntries 첨부 규칙 |
| `packages/entry-extractor/tests/test_attachment_trees.js` | parseAttachmentDetail · collectAttachmentTrees |
| `packages/entry-extractor/README.md` | 첨부 leaf / fallback / skip 문서화 |

---

### Task 1: 테스트 하네스 + fixture 헬퍼

**Files:**
- Create: `packages/entry-extractor/tests/fixtures/html.js`
- Modify: `packages/entry-extractor/package.json`
- Test: `packages/entry-extractor/tests/test_fixtures_smoke.js` (임시 스모크, Task 2에서 실질 테스트로 대체 가능)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `treeDataHtml({ rcpNo, dcmNo, nodes })` → `extractTree`가 파싱 가능한 HTML 문자열
  - `attachmentSelectHtml({ rcpNo, dcmNo, name })` → `#att` option HTML
  - `disclosureMeta` 샘플 객체

- [ ] **Step 1: package.json에 test 스크립트 추가**

```json
"scripts": {
  "example": "node examples/run.js",
  "example:entries": "node examples/entries.js",
  "test": "node --test tests/**/*.js"
}
```

- [ ] **Step 2: fixture 헬퍼 작성**

`packages/entry-extractor/tests/fixtures/html.js`:

```js
/** extractTree용 최소 treeData 스크립트 HTML을 만든다. */
function treeDataHtml({ rcpNo, dcmNo, nodes }) {
  // nodes: [{ depth, text, eleId, offset, length, dtd, childrenDepths? }]
  // childrenDepths: 이 노드 children으로 push할 depth 목록
  const lines = ['<html><body><script>', 'var treeData = [];'];
  for (const n of nodes) {
    const d = n.depth;
    lines.push(`var node${d} = {};`);
    lines.push(`node${d}['text'] = "${n.text}";`);
    lines.push(`node${d}['rcpNo'] = "${rcpNo}";`);
    lines.push(`node${d}['dcmNo'] = "${dcmNo}";`);
    lines.push(`node${d}['eleId'] = "${n.eleId}";`);
    lines.push(`node${d}['offset'] = "${n.offset ?? '0'}";`);
    lines.push(`node${d}['length'] = "${n.length ?? '10'}";`);
    lines.push(`node${d}['dtd'] = "${n.dtd ?? 'dart4.xsd'}";`);
    lines.push(`node${d}['children'] = [];`);
  }
  for (const n of nodes) {
    for (const childDepth of n.childrenDepths || []) {
      lines.push(`node${n.depth}['children'].push(node${childDepth});`);
    }
  }
  // 루트만 treeData.push (childrenDepths에 등장하지 않은 depth)
  const childSet = new Set(nodes.flatMap((n) => n.childrenDepths || []));
  for (const n of nodes) {
    if (!childSet.has(n.depth)) {
      lines.push(`treeData.push(node${n.depth});`);
    }
  }
  lines.push('</script></body></html>');
  return lines.join('\n');
}

function attachmentSelectHtml({ rcpNo, dcmNo, name }) {
  return [
    '<html><body>',
    '<select id="att">',
    `<option value="rcpNo=${rcpNo}&dcmNo=${dcmNo}">${name}</option>`,
    '</select>',
    '<select id="doc"></select>',
    '</body></html>',
  ].join('\n');
}

function mergeHtml(...parts) {
  return parts.join('\n');
}

const sampleDisclosure = {
  reportType: 'F001',
  rcept_no: '20260724000650',
  report_nm: '감사보고서',
  corp_code: '00224628',
  corp_name: '테스트법인',
  submitter: '테스트회계법인',
  rcept_dt: '2026.07.24',
  url: 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000650',
};

module.exports = {
  treeDataHtml,
  attachmentSelectHtml,
  mergeHtml,
  sampleDisclosure,
};
```

- [ ] **Step 3: 스모크 테스트 — extractTree가 fixture를 읽는지**

`packages/entry-extractor/tests/test_fixtures_smoke.js`:

```js
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { extractTree } = require('../src/documents');
const { treeDataHtml } = require('./fixtures/html');

describe('fixture smoke', () => {
  it('treeDataHtml → extractTree leaf 1건', () => {
    const html = treeDataHtml({
      rcpNo: '20260724000650',
      dcmNo: '11495099',
      nodes: [
        {
          depth: 1,
          text: '재무상태표',
          eleId: '1',
          offset: '100',
          length: '200',
        },
      ],
    });
    const tree = extractTree(html);
    assert.equal(tree.length, 1);
    assert.equal(tree[0].eleId, '1');
    assert.equal(tree[0].dcmNo, '11495099');
  });
});
```

- [ ] **Step 4: 테스트 실행**

Run: `npm test -w @dart-wrapper/entry-extractor`  
Expected: PASS (extractTree는 이미 export되어 있음 — `documents.js` module.exports에 `extractTree` 포함 여부 확인. 없으면 index가 아닌 `require('../src/documents')`로 직접 가져오므로 documents exports에 이미 있음)

- [ ] **Step 5: Commit**

```bash
git add packages/entry-extractor/package.json packages/entry-extractor/tests
git commit -m "test(entry-extractor): 첨부 leaf용 fixture와 node --test 하네스 추가"
```

---

### Task 2: `buildEntries`에 `attachmentTrees` 주입

**Files:**
- Modify: `packages/entry-extractor/src/entries.js`
- Test: `packages/entry-extractor/tests/test_build_entries_attachments.js`

**Interfaces:**
- Consumes: 기존 `buildEntries(disclosure, detail, options)`
- Produces:
  - `buildEntries(disclosure, detail, { leafOnly, includeAttachments, attachmentTrees })`
  - `attachmentTrees`: `Record<string, object[]>` — key=`dcmNo`, value=`extractTree` 결과(빈 배열이면 fallback)
  - 첨부 leaf: `source='attachment'`, `entry_id=rcept_no_dcmNo_eleId`, 문서단위 `..._att` 없음
  - 첨부 fallback: 트리 없거나 빈 배열 → 기존 `..._att` 1건
  - body 트리에 이미 있는 `dcmNo`의 attachment 문서는 **attachmentTrees가 있어도** attachment entry를 만들지 않음 (documents에서 source=attachment이고 body dcmNo에 해당하면 skip — detail.tree에서 body dcmNo 집합 산출)

- [ ] **Step 1: Write the failing tests**

`packages/entry-extractor/tests/test_build_entries_attachments.js`:

```js
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { extractTree } = require('../src/documents');
const { buildEntries } = require('../src/entries');
const {
  treeDataHtml,
  sampleDisclosure,
} = require('./fixtures/html');

function leafTree(dcmNo, eleId, text) {
  return extractTree(
    treeDataHtml({
      rcpNo: sampleDisclosure.rcept_no,
      dcmNo,
      nodes: [{ depth: 1, text, eleId, offset: '10', length: '20' }],
    })
  );
}

describe('buildEntries 첨부 attachmentTrees', () => {
  it('첨부 전용 dcmNo + 트리 → leaf만, ..._att 없음', () => {
    const bodyTree = leafTree('111', '1', '감사보고서');
    const attTree = leafTree('999', '5', '재무상태표');
    const detail = {
      tree: bodyTree,
      documents: [
        {
          source: 'body',
          dcmNo: '111',
          name: '감사보고서',
          url: 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000650&dcmNo=111',
        },
        {
          source: 'attachment',
          dcmNo: '999',
          name: '첨부재무제표',
          originalName: '첨부재무제표',
          url: 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000650&dcmNo=999',
        },
      ],
    };

    const entries = buildEntries(sampleDisclosure, detail, {
      attachmentTrees: { '999': attTree },
    });

    const att = entries.filter((e) => e.source === 'attachment');
    assert.equal(att.length, 1);
    assert.equal(att[0].ele_id, '5');
    assert.equal(att[0].entry_id, '20260724000650_999_5');
    assert.equal(att[0].document_name, '첨부재무제표');
    assert.equal(att[0].section_name, '재무상태표');
    assert.ok(!att.some((e) => e.entry_id.endsWith('_att')));
  });

  it('첨부 전용 + 빈 트리 → ..._att 1건', () => {
    const bodyTree = leafTree('111', '1', '감사보고서');
    const detail = {
      tree: bodyTree,
      documents: [
        {
          source: 'body',
          dcmNo: '111',
          name: '감사보고서',
          url: 'u1',
        },
        {
          source: 'attachment',
          dcmNo: '999',
          name: 'PDF첨부',
          originalName: 'PDF첨부',
          url: 'u999',
        },
      ],
    };

    const entries = buildEntries(sampleDisclosure, detail, {
      attachmentTrees: { '999': [] },
    });

    const att = entries.filter((e) => e.source === 'attachment');
    assert.equal(att.length, 1);
    assert.equal(att[0].entry_id, '20260724000650_999_att');
    assert.equal(att[0].ele_id, null);
    assert.deepEqual(att[0].path, ['PDF첨부']);
  });

  it('body 트리에 이미 있는 dcmNo는 attachment entry를 만들지 않음', () => {
    const bodyTree = leafTree('111', '1', '(첨부)재무제표');
    const detail = {
      tree: bodyTree,
      documents: [
        {
          source: 'body',
          dcmNo: '111',
          name: '(첨부)재무제표',
          url: 'u1',
        },
        {
          source: 'attachment',
          dcmNo: '111',
          name: '재무제표',
          originalName: '재무제표',
          url: 'u1',
        },
      ],
    };

    const entries = buildEntries(sampleDisclosure, detail, {
      attachmentTrees: { '111': leafTree('111', '9', '손익계산서') },
    });

    assert.ok(entries.every((e) => e.source === 'body'));
    assert.ok(!entries.some((e) => e.source === 'attachment'));
  });

  it('includeAttachments=false면 첨부 entry 없음', () => {
    const detail = {
      tree: leafTree('111', '1', '감사보고서'),
      documents: [
        {
          source: 'attachment',
          dcmNo: '999',
          name: '첨부',
          originalName: '첨부',
          url: 'u',
        },
      ],
    };
    const entries = buildEntries(sampleDisclosure, detail, {
      includeAttachments: false,
      attachmentTrees: { '999': leafTree('999', '1', '섹션') },
    });
    assert.ok(entries.every((e) => e.source === 'body'));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -w @dart-wrapper/entry-extractor -- tests/test_build_entries_attachments.js`  
Expected: FAIL — 첨부 leaf가 없고 기존처럼 `..._att`만 생기거나, attachmentTrees를 무시함

- [ ] **Step 3: Implement `buildEntries` 변경**

`packages/entry-extractor/src/entries.js`에서:

1. body `dcmNo` 집합을 `detail.tree`에서 수집하는 헬퍼(파일 내부 함수):

```js
function collectBodyDcmNos(tree) {
  const set = new Set();
  function walk(nodes) {
    for (const node of nodes || []) {
      if (node.dcmNo) set.add(String(node.dcmNo));
      walk(node.children);
    }
  }
  walk(tree);
  return set;
}
```

2. 기존 attachment 루프를 교체:

```js
function buildEntries(
  disclosure,
  detail,
  { leafOnly = true, includeAttachments = true, attachmentTrees = {} } = {}
) {
  // ... 기존 body walk 동일 ...

  if (includeAttachments) {
    const bodyDcmNos = collectBodyDcmNos(tree);

    for (const doc of documents) {
      if (doc.source !== 'attachment') continue;
      const dcmNo = String(doc.dcmNo);
      if (bodyDcmNos.has(dcmNo)) continue;

      const attTree = attachmentTrees[dcmNo];
      const hasLeaves =
        Array.isArray(attTree) &&
        attTree.length > 0;

      if (hasLeaves) {
        function walkAtt(node, path) {
          const currentPath = [...path, node.name];
          const isLeaf = !node.children || node.children.length === 0;
          if (isLeaf || !leafOnly) {
            const entry = {
              ...features,
              disclosure_url: disclosureUrl,
              source: 'attachment',
              dcmNo: node.dcmNo,
              document_name: doc.name,
              section_name: node.name,
              section_original_name: node.originalName,
              depth: node.depth,
              is_leaf: isLeaf,
              parent_ele_id: node.parentEleId,
              ele_id: node.eleId,
              offset: node.offset,
              length: node.length,
              dtd: node.dtd,
              path: currentPath,
              viewer_url: node.url,
            };
            entry.entry_id = makeEntryId(entry);
            entries.push(entry);
          }
          for (const child of node.children || []) {
            walkAtt(child, currentPath);
          }
        }
        for (const root of attTree) {
          walkAtt(root, []);
        }
        continue;
      }

      // fallback: 트리 없음 / 빈 배열 / attachmentTrees 미제공
      const entry = {
        ...features,
        disclosure_url: disclosureUrl,
        source: 'attachment',
        dcmNo: doc.dcmNo,
        document_name: doc.name,
        section_name: doc.name,
        section_original_name: doc.originalName,
        depth: 1,
        is_leaf: true,
        parent_ele_id: null,
        ele_id: null,
        offset: null,
        length: null,
        dtd: null,
        path: [doc.name],
        viewer_url: doc.url,
      };
      entry.entry_id = makeEntryId(entry);
      entries.push(entry);
    }
  }

  return entries;
}
```

**주의:** `attachmentTrees` 키가 아예 없으면(레거시 호출) 기존처럼 fallback `..._att` — 스펙의 “목차 없으면 fallback”과 CLI 구버전 호출 호환.

- [ ] **Step 4: Run tests — PASS**

Run: `npm test -w @dart-wrapper/entry-extractor`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/entry-extractor/src/entries.js packages/entry-extractor/tests/test_build_entries_attachments.js
git commit -m "feat(entry-extractor): attachmentTrees로 첨부 leaf·fallback entry 생성"
```

---

### Task 3: `parseAttachmentDetail` + `collectAttachmentTrees`

**Files:**
- Modify: `packages/entry-extractor/src/documents.js`
- Modify: `packages/entry-extractor/src/entries.js`
- Modify: `packages/entry-extractor/src/index.js`
- Test: `packages/entry-extractor/tests/test_attachment_trees.js`

**Interfaces:**
- Consumes: `extractTree`, `documentUrl`, `safeGet`
- Produces:
  - `async parseAttachmentDetail(rcpNo, dcmNo, { fetcher } = {}) → object[]`  
    - 기본 `fetcher`: `async (url) => (await safeGet(url)).data`  
    - 성공: `extractTree(html)`  
    - fetcher throw: **다시 throw하지 않고** `[]` 반환하지 않음 — 상위에서 구분하려면 `{ tree, error }` 또는 throw를 collect에서 catch. **스펙:** fetch 실패 → fallback. 구현은 `collectAttachmentTrees`에서 try/catch 후 `trees[dcmNo]=[]` + stderr 로그.
  - `async collectAttachmentTrees(documents, bodyTree, { fetcher, onAttachment } = {}) → Record<string, object[]>`  
    - `source==='attachment'` 이고 body dcmNo에 없는 것만  
    - 각 dcmNo 1회 fetch  
    - 실패 시 해당 키 `[]` + stderr `fetch_failed→fallback`  
    - 빈 트리면 stderr `fallback`  
    - 성공 leaf면 stderr `expanded`

- [ ] **Step 1: Write the failing tests**

```js
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { extractTree } = require('../src/documents');
const {
  parseAttachmentDetail,
  // documents에서 export 예정 — 또는 entries의 collectAttachmentTrees
} = require('../src/documents');
const { collectAttachmentTrees } = require('../src/entries');
const { treeDataHtml, sampleDisclosure } = require('./fixtures/html');

describe('parseAttachmentDetail', () => {
  it('fetcher HTML → extractTree 결과', async () => {
    const html = treeDataHtml({
      rcpNo: '20260724000650',
      dcmNo: '999',
      nodes: [{ depth: 1, text: '주석', eleId: '2', offset: '1', length: '2' }],
    });
    const tree = await parseAttachmentDetail('20260724000650', '999', {
      fetcher: async () => html,
    });
    assert.equal(tree.length, 1);
    assert.equal(tree[0].eleId, '2');
  });

  it('빈 treeData HTML → []', async () => {
    const tree = await parseAttachmentDetail('20260724000650', '999', {
      fetcher: async () => '<html><body>no tree</body></html>',
    });
    assert.deepEqual(tree, []);
  });
});

describe('collectAttachmentTrees', () => {
  it('body에 있는 dcmNo는 fetch하지 않음', async () => {
    const bodyTree = extractTree(
      treeDataHtml({
        rcpNo: sampleDisclosure.rcept_no,
        dcmNo: '111',
        nodes: [{ depth: 1, text: '본문', eleId: '1' }],
      })
    );
    const calls = [];
    const fetcher = async (url) => {
      calls.push(url);
      return '<html></html>';
    };
    const trees = await collectAttachmentTrees(
      [
        { source: 'attachment', dcmNo: '111', name: '중복' },
        { source: 'attachment', dcmNo: '999', name: '신규' },
      ],
      bodyTree,
      { fetcher }
    );
    assert.equal(calls.length, 1);
    assert.ok(calls[0].includes('dcmNo=999'));
    assert.ok(!('111' in trees));
    assert.ok('999' in trees);
  });

  it('fetcher 실패 → 해당 dcmNo만 []', async () => {
    const trees = await collectAttachmentTrees(
      [{ source: 'attachment', dcmNo: '999', name: '첨부' }],
      [],
      {
        fetcher: async () => {
          throw new Error('network');
        },
      }
    );
    assert.deepEqual(trees['999'], []);
  });
});
```

- [ ] **Step 2: Run — Expected FAIL** (`parseAttachmentDetail` / `collectAttachmentTrees` 미정의)

- [ ] **Step 3: Implement**

`documents.js`에 추가:

```js
/**
 * 첨부 dcmNo 전용 상세페이지에서 목차 트리를 파싱한다.
 * @param {string} rcpNo
 * @param {string} dcmNo
 * @param {{ fetcher?: (url: string) => Promise<string> }} [options]
 * @returns {Promise<object[]>}
 */
async function parseAttachmentDetail(rcpNo, dcmNo, { fetcher = null } = {}) {
  if (!rcpNo || !dcmNo) throw new Error('rcpNo와 dcmNo는 필수입니다.');
  const url = documentUrl(rcpNo, dcmNo);
  const getHtml =
    fetcher ||
    (async (u) => {
      const response = await safeGet(u);
      return response.data;
    });
  const html = await getHtml(url);
  return extractTree(html);
}
```

`module.exports`에 `parseAttachmentDetail` 추가.

`entries.js`에:

```js
const { parseAttachmentDetail } = require('./documents');

function collectBodyDcmNos(tree) { /* Task 2와 동일 — 중복이면 entries에만 두고 documents로 옮기지 말 것 */ }

/**
 * 첨부 전용 dcmNo의 목차 트리를 수집한다. HTTP 실패는 해당 키 []로 흡수한다.
 */
async function collectAttachmentTrees(
  documents,
  bodyTree,
  { fetcher = null, log = (msg) => process.stderr.write(msg) } = {}
) {
  const bodyDcmNos = collectBodyDcmNos(bodyTree);
  const trees = Object.create(null);
  const seen = new Set();

  for (const doc of documents || []) {
    if (doc.source !== 'attachment') continue;
    const dcmNo = String(doc.dcmNo);
    if (bodyDcmNos.has(dcmNo) || seen.has(dcmNo)) continue;
    seen.add(dcmNo);

    try {
      const tree = await parseAttachmentDetail(doc.rcpNo || '', dcmNo, {
        fetcher,
      });
      // rcpNo가 doc에 없으면 disclosure.rcept_no를 넘기도록 호출측 책임
      trees[dcmNo] = tree || [];
      if (!trees[dcmNo].length) {
        log(`[첨부] dcmNo=${dcmNo} fallback (빈 목차)\n`);
      } else {
        log(`[첨부] dcmNo=${dcmNo} expanded\n`);
      }
    } catch (err) {
      trees[dcmNo] = [];
      log(
        `[첨부] dcmNo=${dcmNo} fetch_failed→fallback (${err.message})\n`
      );
    }
  }
  return trees;
}
```

**rcpNo 전달:** `extractAttachments` 결과에 이미 `rcpNo`가 있음. `collectAttachmentTrees`는 `doc.rcpNo`를 쓰고, 없으면 인자로 `rcpNo`를 받도록 시그니처를 확장:

```js
async function collectAttachmentTrees(
  documents,
  bodyTree,
  { fetcher = null, rcpNo = null, log = (msg) => process.stderr.write(msg) } = {}
) {
  // ...
  const tree = await parseAttachmentDetail(doc.rcpNo || rcpNo, dcmNo, { fetcher });
```

`index.js` export에 `parseAttachmentDetail`, `collectAttachmentTrees` 추가.

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

```bash
git add packages/entry-extractor/src/documents.js packages/entry-extractor/src/entries.js packages/entry-extractor/src/index.js packages/entry-extractor/tests/test_attachment_trees.js
git commit -m "feat(entry-extractor): 첨부 dcmNo 목차 fetch와 트리 수집 추가"
```

---

### Task 4: `collectEntries` · CLI `extract` 오케스트레이션

**Files:**
- Modify: `packages/entry-extractor/src/entries.js`
- Modify: `packages/entry-extractor/bin/collect-entries.js`
- Test: `packages/entry-extractor/tests/test_build_entries_from_disclosure.js`

**Interfaces:**
- Produces:
  - `async buildEntriesFromDisclosure(disclosure, { leafOnly, includeAttachments, fetcher } = {}) → object[]`  
    1. `parseDetail(disclosure.url, { disclosure })`  
    2. `includeAttachments`이면 `collectAttachmentTrees(detail.documents, detail.tree, { fetcher, rcpNo: disclosure.rcept_no })`  
    3. `buildEntries(..., { attachmentTrees })`  
  - `collectEntries`는 공시 루프에서 `buildEntriesFromDisclosure` 호출  
  - `bin/collect-entries.js` `runExtract`도 `buildEntriesFromDisclosure` 사용 (지금처럼 parseDetail+buildEntries만 하면 Admin 슬라이스 extract가 첨부 leaf를 못 받음)

- [ ] **Step 1: Write the failing test**

```js
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { buildEntriesFromDisclosure } = require('../src/entries');
const {
  treeDataHtml,
  attachmentSelectHtml,
  mergeHtml,
  sampleDisclosure,
} = require('./fixtures/html');

describe('buildEntriesFromDisclosure', () => {
  it('상세 HTML + 첨부 HTML을 fetcher로 이어 첨부 leaf 생성', async () => {
    const bodyHtml = mergeHtml(
      treeDataHtml({
        rcpNo: sampleDisclosure.rcept_no,
        dcmNo: '111',
        nodes: [{ depth: 1, text: '감사의견', eleId: '1' }],
      }),
      attachmentSelectHtml({
        rcpNo: sampleDisclosure.rcept_no,
        dcmNo: '999',
        name: '첨부재무제표',
      })
    );
    const attHtml = treeDataHtml({
      rcpNo: sampleDisclosure.rcept_no,
      dcmNo: '999',
      nodes: [{ depth: 1, text: '재무상태표', eleId: '7' }],
    });

    const fetcher = async (url) => {
      if (String(url).includes('dcmNo=999')) return attHtml;
      return bodyHtml;
    };

    const entries = await buildEntriesFromDisclosure(
      { ...sampleDisclosure, url: sampleDisclosure.url },
      { fetcher }
    );

    const att = entries.filter((e) => e.source === 'attachment');
    assert.equal(att.length, 1);
    assert.equal(att[0].entry_id, '20260724000650_999_7');
    assert.equal(att[0].document_name, '첨부재무제표');
  });
});
```

**구현 결정 (이 스텝에서 확정):** `parseDetail`에 optional `fetcher`를 추가한다.

```js
async function parseDetail(disclosureUrl, { disclosure = null, body = true, attachments = true, fetcher = null } = {}) {
  const getHtml =
    fetcher ||
    (async (u) => {
      const response = await safeGet(u);
      return response.data;
    });
  const html = await getHtml(disclosureUrl);
  // cheerio.load(html) ... 기존과 동일
}
```

- [ ] **Step 2: Run — Expected FAIL**

- [ ] **Step 3: Implement `parseDetail` fetcher · `buildEntriesFromDisclosure` · `collectEntries` · CLI**

```js
async function buildEntriesFromDisclosure(
  disclosure,
  { leafOnly = true, includeAttachments = true, fetcher = null } = {}
) {
  const detail = await parseDetail(disclosure.url, { disclosure, fetcher });
  let attachmentTrees = {};
  if (includeAttachments) {
    attachmentTrees = await collectAttachmentTrees(detail.documents, detail.tree, {
      fetcher,
      rcpNo: disclosure.rcept_no,
    });
  }
  return buildEntries(disclosure, detail, {
    leafOnly,
    includeAttachments,
    attachmentTrees,
  });
}

async function collectEntries(params = {}) {
  const {
    leafOnly = true,
    includeAttachments = true,
    onEntry = null,
    fetcher = null,
    ...listParams
  } = params;

  const disclosures = await fetchDisclosureList(listParams);
  const allEntries = [];

  for (const disclosure of disclosures) {
    const entries = await buildEntriesFromDisclosure(disclosure, {
      leafOnly,
      includeAttachments,
      fetcher,
    });
    allEntries.push(...entries);
    if (onEntry) {
      onEntry({
        disclosure,
        entryCount: entries.length,
        totalEntries: allEntries.length,
      });
    }
  }
  return allEntries;
}
```

`bin/collect-entries.js` `runExtract`:

```js
const { buildEntriesFromDisclosure } = require('../src');

async function runExtract(params) {
  const disclosure = params.disclosure;
  if (!disclosure || !disclosure.url) {
    throw new Error('disclosure.url은 필수입니다.');
  }

  const entries = await buildEntriesFromDisclosure(disclosure, {
    includeAttachments: params.include_attachments ?? true,
  });

  process.stderr.write(
    `[상세] ${disclosure.corp_name || disclosure.rcept_no} → ${entries.length}건\n`
  );
  process.stdout.write(JSON.stringify(entries));
}
```

`index.js`에 `buildEntriesFromDisclosure` export.

- [ ] **Step 4: Run all tests — PASS**

Run: `npm test -w @dart-wrapper/entry-extractor`  
Expected: 전 테스트 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/entry-extractor/src/documents.js packages/entry-extractor/src/entries.js packages/entry-extractor/src/index.js packages/entry-extractor/bin/collect-entries.js packages/entry-extractor/tests/test_build_entries_from_disclosure.js
git commit -m "feat(entry-extractor): 수집·extract 경로에서 첨부 leaf 펼침 연동"
```

---

### Task 5: README 갱신

**Files:**
- Modify: `packages/entry-extractor/README.md`

**Interfaces:** 없음 (문서만)

- [ ] **Step 1: README에 첨부 leaf 절 추가**

다음을 “3단계 — leaf 엔트리 생성” 근처 또는 “주의” 위에 넣는다:

```markdown
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
```

엔트리 스키마 예시의 `source`/`path` 설명에 첨부 leaf 한 줄도 보강.

- [ ] **Step 2: Commit**

```bash
git add packages/entry-extractor/README.md
git commit -m "docs(entry-extractor): 첨부 leaf 추출·fallback 동작 설명"
```

---

## Spec Coverage Checklist

| Spec 요구 | Task |
|-----------|------|
| 첨부 전용 dcmNo `main.do` 재파싱 | Task 3–4 |
| 목차 있음 → leaf only | Task 2 |
| 목차 없음 → `..._att` | Task 2 |
| body dcmNo skip | Task 2–3 |
| `includeAttachments`만 사용 | Task 2–4 |
| fetch 실패 → 해당 건 fallback | Task 3 |
| `buildEntries` HTTP 없음 / trees 주입 | Task 2 |
| CLI extract도 동일 품질 | Task 4 |
| README | Task 5 |
| 단위 테스트 5시나리오 | Task 2–4 |
| web-api / Browse / PDF / 마이그레이션 | 범위 밖 (계획에 없음) |

## Self-Review Notes

- `parseDetail`에 `fetcher`를 넣는 것은 테스트 가능성과 CLI 일관성을 위한 스펙 정밀화이며, 기본 동작(safeGet)은 변하지 않는다.
- `collectBodyDcmNos`는 `entries.js`에만 둔다 (documents와 중복 export 금지).
- Windows에서 `npm test` glob이 동작하지 않으면 스크립트를 `node --test tests`로 바꾼다 (Node가 디렉터리를 재귀 실행).
