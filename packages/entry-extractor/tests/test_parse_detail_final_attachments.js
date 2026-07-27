const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { parseDetail } = require('../src/documents');

describe('parseDetail 첨부 최종본', () => {
  it('같은 이름 첨부 option은 최신 1건만 documents에 남긴다', async () => {
    const html = `
<html><body>
<select id="att">
  <option value="null">+첨부선택+</option>
  <option value="rcpNo=OLD&dcmNo=111">2026.03.16 감사보고서</option>
  <option value="rcpNo=NEW&dcmNo=222">2026.03.25 [정정] 감사보고서</option>
</select>
<select id="doc"></select>
<script>var treeData = [];</script>
</body></html>`;

    const detail = await parseDetail('https://example.test/main.do?rcpNo=X', {
      body: false,
      attachments: true,
      fetcher: async () => html,
    });

    const att = detail.documents.filter((d) => d.source === 'attachment');
    assert.equal(att.length, 1);
    assert.equal(att[0].dcmNo, '222');
    assert.equal(att[0].rcpNo, 'NEW');
    assert.equal(att[0].correctionType, '정정');
  });
});
