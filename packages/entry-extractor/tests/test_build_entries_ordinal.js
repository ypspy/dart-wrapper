const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { extractTree } = require('../src/documents');
const { buildEntries } = require('../src/entries');
const { treeDataHtml, sampleDisclosure } = require('./fixtures/html');

function leafTree(dcmNo, eleId, text) {
  return extractTree(
    treeDataHtml({
      rcpNo: sampleDisclosure.rcept_no,
      dcmNo,
      nodes: [{ depth: 1, text, eleId, offset: '10', length: '20' }],
    })
  );
}

describe('buildEntries ordinal', () => {
  it('본문 leaf 후 첨부 leaf에 0부터 연속 ordinal', () => {
    const bodyTree = leafTree('111', '1', '감사의견');
    const attTree = leafTree('999', '5', '재무상태표');
    const detail = {
      tree: bodyTree,
      documents: [
        { source: 'body', dcmNo: '111', name: '감사보고서', url: 'u1' },
        {
          source: 'attachment',
          dcmNo: '999',
          name: '첨부재무제표',
          originalName: '첨부재무제표',
          url: 'u999',
        },
      ],
    };

    const entries = buildEntries(sampleDisclosure, detail, {
      attachmentTrees: { 999: attTree },
    });

    assert.deepEqual(
      entries.map((e) => e.ordinal),
      [0, 1]
    );
    assert.equal(entries[0].source, 'body');
    assert.equal(entries[1].source, 'attachment');
  });

  it('첨부 fallback도 ordinal을 받는다', () => {
    const detail = {
      tree: leafTree('111', '1', '본문'),
      documents: [
        { source: 'body', dcmNo: '111', name: '본문', url: 'u1' },
        {
          source: 'attachment',
          dcmNo: '999',
          name: 'PDF',
          originalName: 'PDF',
          url: 'u9',
        },
      ],
    };
    const entries = buildEntries(sampleDisclosure, detail, {
      attachmentTrees: { 999: [] },
    });
    assert.deepEqual(
      entries.map((e) => e.ordinal),
      [0, 1]
    );
    assert.ok(entries[1].entry_id.endsWith('_att'));
  });
});
