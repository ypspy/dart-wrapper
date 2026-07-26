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
    assert.deepEqual(
      entries.map((e) => e.ordinal),
      [0, 1]
    );
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
