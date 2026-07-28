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
