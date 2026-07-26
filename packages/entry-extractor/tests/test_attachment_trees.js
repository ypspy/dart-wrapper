const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { extractTree, parseAttachmentDetail } = require('../src/documents');
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
        { source: 'attachment', dcmNo: '111', name: '중복', rcpNo: sampleDisclosure.rcept_no },
        { source: 'attachment', dcmNo: '999', name: '신규', rcpNo: sampleDisclosure.rcept_no },
      ],
      bodyTree,
      { fetcher, log: () => {} }
    );
    assert.equal(calls.length, 1);
    assert.ok(calls[0].includes('dcmNo=999'));
    assert.ok(!Object.prototype.hasOwnProperty.call(trees, '111'));
    assert.ok(Object.prototype.hasOwnProperty.call(trees, '999'));
  });

  it('fetcher 실패 → 해당 dcmNo만 []', async () => {
    const trees = await collectAttachmentTrees(
      [{ source: 'attachment', dcmNo: '999', name: '첨부', rcpNo: sampleDisclosure.rcept_no }],
      [],
      {
        fetcher: async () => {
          throw new Error('network');
        },
        log: () => {},
      }
    );
    assert.deepEqual(trees['999'], []);
  });
});
