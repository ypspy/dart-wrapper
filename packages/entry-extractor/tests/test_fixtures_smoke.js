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
