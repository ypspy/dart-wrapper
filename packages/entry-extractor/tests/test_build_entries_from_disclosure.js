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
      { fetcher, log: () => {} }
    );

    const att = entries.filter((e) => e.source === 'attachment');
    assert.equal(att.length, 1);
    assert.equal(att[0].entry_id, '20260724000650_999_7');
    assert.equal(att[0].document_name, '첨부재무제표');
  });
});
