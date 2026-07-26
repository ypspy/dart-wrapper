# 중간 TOC 노드 저장 (`leafOnly` 기본 false) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `entry-extractor` 기본값을 `leafOnly: false`로 바꿔 TOC 중간 노드까지 flat entry로 저장하고, `is_leaf`로 구분한다.

**Architecture:** `buildEntries` walk는 이미 `isLeaf || !leafOnly` 분기와 `is_leaf` 필드를 갖고 있다. 기본 인자만 `false`로 바꾸고, 부모+자식 fixture 테스트로 회귀를 고정한 뒤 README를 갱신한다. web-api는 `leaf_only`를 넘기지 않으므로 extractor 기본값을 그대로 탄다.

**Tech Stack:** Node.js (CommonJS), `node --test`, 기존 `tests/fixtures/html.js`의 `childrenDepths`

**Spec:** `docs/superpowers/specs/2026-07-27-store-intermediate-toc-nodes-design.md`

## Global Constraints

- 주석/Docstring/로그/테스트 설명: 한국어
- 제표 leaf 합성 금지 — 원문 TOC만 저장
- web-api 스키마·Admin `leaf_only` UI 추가 없음
- 커밋은 사용자가 요청할 때만 (이 플랜의 Commit 스텝은 사용자 승인 후)

---

## File map

| 파일 | 역할 |
|------|------|
| `packages/entry-extractor/src/entries.js` | `leafOnly` 기본값 `false` (buildEntries / FromDisclosure / collectEntries) |
| `packages/entry-extractor/tests/test_leaf_only_default.js` | 신규: 기본·true·첨부 부모 저장 |
| `packages/entry-extractor/README.md` | 기본값·중간 노드 설명 |
| (변경 없음) `packages/web-api/**` | collector가 leaf_only 미전달 → 새 기본값 적용 |

---

### Task 1: 실패하는 테스트 — 기본값으로 중간 노드 저장

**Files:**
- Create: `packages/entry-extractor/tests/test_leaf_only_default.js`
- Test: 동일

**Interfaces:**
- Consumes: `buildEntries(disclosure, detail, options?)`, `extractTree`, `treeDataHtml`, `sampleDisclosure`
- Produces: 기본 `leafOnly` 동작에 대한 실패 테스트 3건

- [x] **Step 1: Write the failing test file**

`packages/entry-extractor/tests/test_leaf_only_default.js`:

```js
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { extractTree } = require('../src/documents');
const { buildEntries } = require('../src/entries');
const { treeDataHtml, sampleDisclosure } = require('./fixtures/html');

function parentChildTree(dcmNo) {
  return extractTree(
    treeDataHtml({
      rcpNo: sampleDisclosure.rcept_no,
      dcmNo,
      nodes: [
        {
          depth: 1,
          text: '(첨부)재무제표',
          eleId: '4',
          offset: '100',
          length: '900',
          childrenDepths: [2],
        },
        {
          depth: 2,
          text: '주석',
          eleId: '5',
          offset: '200',
          length: '700',
        },
      ],
    })
  );
}

describe('buildEntries leafOnly 기본값', () => {
  it('기본값이면 부모와 자식 모두 저장하고 부모 is_leaf=false', () => {
    const tree = parentChildTree('111');
    const detail = {
      tree,
      documents: [{ source: 'body', dcmNo: '111', name: '사업보고서', url: 'u' }],
    };
    const entries = buildEntries(sampleDisclosure, detail);
    assert.equal(entries.length, 2);
    assert.equal(entries[0].section_name, '(첨부)재무제표');
    assert.equal(entries[0].is_leaf, false);
    assert.equal(entries[0].ele_id, '4');
    assert.equal(entries[1].section_name, '주석');
    assert.equal(entries[1].is_leaf, true);
    assert.equal(entries[1].parent_ele_id, '4');
    assert.deepEqual(entries.map((e) => e.ordinal), [0, 1]);
  });

  it('leafOnly: true면 leaf만 저장', () => {
    const tree = parentChildTree('111');
    const detail = {
      tree,
      documents: [{ source: 'body', dcmNo: '111', name: '사업보고서', url: 'u' }],
    };
    const entries = buildEntries(sampleDisclosure, detail, { leafOnly: true });
    assert.equal(entries.length, 1);
    assert.equal(entries[0].section_name, '주석');
    assert.equal(entries[0].is_leaf, true);
  });

  it('첨부 트리도 기본값에서 부모(첨부)재무제표를 저장', () => {
    const bodyTree = extractTree(
      treeDataHtml({
        rcpNo: sampleDisclosure.rcept_no,
        dcmNo: '111',
        nodes: [{ depth: 1, text: '본문', eleId: '1', offset: '1', length: '2' }],
      })
    );
    const attTree = parentChildTree('999');
    const detail = {
      tree: bodyTree,
      documents: [
        { source: 'body', dcmNo: '111', name: '사업보고서', url: 'u1' },
        {
          source: 'attachment',
          dcmNo: '999',
          name: '감사보고서',
          originalName: '감사보고서',
          url: 'u999',
        },
      ],
    };
    const entries = buildEntries(sampleDisclosure, detail, {
      attachmentTrees: { 999: attTree },
    });
    const att = entries.filter((e) => e.source === 'attachment');
    assert.equal(att.length, 2);
    assert.equal(att[0].section_name, '(첨부)재무제표');
    assert.equal(att[0].is_leaf, false);
    assert.equal(att[1].section_name, '주석');
    assert.equal(att[1].is_leaf, true);
    assert.equal(att[0].document_name, '감사보고서');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (working directory `packages/entry-extractor`):

```bash
node --test tests/test_leaf_only_default.js
```

Expected: FAIL — 기본값 테스트에서 `entries.length`가 `1`(leaf만)이라 `2`와 불일치.

- [ ] **Step 3: Commit tests only (사용자 요청 시에만)**

```bash
git add packages/entry-extractor/tests/test_leaf_only_default.js
git commit -m "test(entry-extractor): leafOnly 기본 false 기대 추가"
```

---

### Task 2: 기본값을 `leafOnly: false`로 변경

**Files:**
- Modify: `packages/entry-extractor/src/entries.js` (`buildEntries`, `buildEntriesFromDisclosure`, `collectEntries` 기본 인자 및 JSDoc)
- Test: `packages/entry-extractor/tests/test_leaf_only_default.js`

**Interfaces:**
- Consumes: Task 1 테스트
- Produces: `leafOnly = false` 기본 (`boolean`, 옵션으로 `true` 유지)

- [ ] **Step 1: Change defaults in `entries.js`**

`buildEntries` 시그니처·JSDoc:

```js
 * @param {boolean} [options.leafOnly=false] true면 leaf만, false면 중간 노드 포함
...
function buildEntries(
  disclosure,
  detail,
  { leafOnly = false, includeAttachments = true, attachmentTrees = {} } = {}
) {
```

`buildEntriesFromDisclosure`:

```js
 * @param {boolean} [options.leafOnly=false]
...
async function buildEntriesFromDisclosure(
  disclosure,
  { leafOnly = false, includeAttachments = true, fetcher = null, log = undefined } = {}
) {
```

`collectEntries` params 기본값도 `leafOnly = false`로, JSDoc `@param {boolean} [params.leafOnly=false]`.

walk 로직(`if (isLeaf || !leafOnly)`)은 **수정하지 않는다**.

- [ ] **Step 2: Run new tests**

```bash
node --test tests/test_leaf_only_default.js
```

Expected: PASS (3)

- [ ] **Step 3: Run full package tests**

```bash
npm test
```

Expected: 전부 PASS. 기존 테스트는 단일 depth leaf fixture라 기본값 변경에 영향 없음. 실패 시 해당 테스트에 `leafOnly: true`를 명시하거나 기대값을 부모 포함으로 수정.

- [ ] **Step 4: Commit (사용자 요청 시에만)**

```bash
git add packages/entry-extractor/src/entries.js packages/entry-extractor/tests/test_leaf_only_default.js
git commit -m "feat(entry-extractor): leafOnly 기본값을 false로 변경"
```

---

### Task 3: README 갱신

**Files:**
- Modify: `packages/entry-extractor/README.md`

**Interfaces:**
- Consumes: Task 2 기본값
- Produces: 문서상 기본값·중간 노드 설명과 코드 일치

- [ ] **Step 1: Update README defaults**

다음을 반영한다:

- `기본값: leafOnly: false, includeAttachments: true`
- 옵션 예시: `leafOnly: false // 중간 노드 포함 (기본)` / `true`면 최하단만
- “중간 노드까지 필요하면 `leafOnly: false`” 문장을  
  “기본은 중간 노드 포함. leaf만 원하면 `leafOnly: true`”로 교체
- entry 예시에서 중간 노드면 `is_leaf: false` 가능함을 한 줄 언급

- [ ] **Step 2: Spot-check**

README에 `leafOnly: true`가 “기본”으로 남아 있는지 검색해 제거.

```bash
rg "leafOnly" packages/entry-extractor/README.md
```

- [ ] **Step 3: Commit (사용자 요청 시에만)**

```bash
git add packages/entry-extractor/README.md
git commit -m "docs(entry-extractor): leafOnly 기본 false 반영"
```

---

### Task 4: 스펙 상태 갱신 + 최종 검증

**Files:**
- Modify: `docs/superpowers/specs/2026-07-27-store-intermediate-toc-nodes-design.md` (상태를 구현 완료로)

- [ ] **Step 1: Mark spec implemented**

스펙 상단 `상태:`를 `구현 완료`로 변경.

- [ ] **Step 2: Final test**

```bash
cd packages/entry-extractor && npm test
```

Expected: all pass.

- [ ] **Step 3: Commit docs (사용자 요청 시에만)**

```bash
git add docs/superpowers/specs/2026-07-27-store-intermediate-toc-nodes-design.md docs/superpowers/plans/2026-07-27-store-intermediate-toc-nodes.md
git commit -m "docs: 중간 TOC 노드 저장 스펙·플랜"
```

---

## Spec coverage check

| Spec 요구 | Task |
|-----------|------|
| 기본 `leafOnly: false` | Task 2 |
| `leafOnly: true` 호환 | Task 1 테스트 + Task 2 |
| 첨부 트리 동일 | Task 1 첨부 테스트 |
| ordinal 부모→자식 | Task 1 assert ordinal |
| README | Task 3 |
| 스키마/web-api 변경 없음 | File map (의도적 no-op) |
| 제표 합성 없음 | 코드 추가 없음 |

## Placeholder scan

없음.
