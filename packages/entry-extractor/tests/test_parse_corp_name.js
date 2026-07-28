const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const cheerio = require('cheerio');
const { parseDisclosureRow } = require('../src/parse');

function rowHtml(corpInner) {
  return `
<table><tbody id="tbody">
<tr>
  <td>1</td>
  <td>${corpInner}</td>
  <td><a href="/dsaf001/main.do?rcpNo=20260605000456">사업보고서</a></td>
  <td>제출인</td>
  <td>2026.06.05</td>
</tr>
</tbody></table>`;
}

describe('parseDisclosureRow corp_name', () => {
  it('IR 배지가 있어도 회사명만 넣는다', () => {
    const html = rowHtml(`
      <span class="innerWrapTag">
        <span class="tagCom_kosdaq">코</span>
        <a href="javascript:openCorpInfoNew('00223762', 'winCorpInfo', '/dsae001/selectPopup.ax');">KT지니뮤직</a>
      </span>
      <span><a href="https://example.com" target="new">
        <span class="tagCom_ir" title="기업 IR페이지 연결">IR</span>
      </a></span>
    `);
    const $ = cheerio.load(html);
    const row = $('#tbody tr').get(0);
    const d = parseDisclosureRow($, row, 'https://dart.fss.or.kr', 'A001');
    assert.equal(d.corp_name, 'KT지니뮤직');
    assert.equal(d.corp_code, '00223762');
  });

  it('IR이 없으면 회사명만 유지한다', () => {
    const html = rowHtml(`
      <span class="innerWrap">
        <span class="tagCom_kospi">유</span>
        <a href="javascript:openCorpInfoNew('00372129', 'winCorpInfo', '/dsae001/selectPopup.ax');">전진건설로봇</a>
      </span>
    `);
    const $ = cheerio.load(html);
    const row = $('#tbody tr').get(0);
    const d = parseDisclosureRow($, row, 'https://dart.fss.or.kr', 'A001');
    assert.equal(d.corp_name, '전진건설로봇');
  });
});
