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
      attachmentTrees: { 999: attTree },
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
      attachmentTrees: { 999: [] },
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
      attachmentTrees: { 111: leafTree('111', '9', '손익계산서') },
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
      attachmentTrees: { 999: leafTree('999', '1', '섹션') },
    });
    assert.ok(entries.every((e) => e.source === 'body'));
  });
});
