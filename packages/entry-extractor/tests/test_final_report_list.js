const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { fetchDisclosureListResult } = require('../src/list');
const { emptyNoDataListHtml } = require('./fixtures/list-pages');

const emptyListHtml =
  '<html><body><div class="pageInfo">[1/1] [총 0건]</div><table><tbody id="tbody"></tbody></table></body></html>';

describe('fetchDisclosureListResult finalReport', () => {
  it('기본이면 요청 URL에 finalReport가 없다', async () => {
    const urls = [];
    await fetchDisclosureListResult({
      reportType: 'A001',
      startDate: '20260101',
      endDate: '20260101',
      maxTotal: 1,
      fetcher: async (url) => {
        urls.push(url);
        return emptyListHtml;
      },
    });
    assert.ok(urls.length >= 1);
    assert.equal(urls[0].includes('finalReport='), false);
  });

  it("finalReport: 'recent'이면 쿼리에 포함한다", async () => {
    const urls = [];
    await fetchDisclosureListResult({
      reportType: 'A001',
      startDate: '20260101',
      endDate: '20260101',
      maxTotal: 1,
      finalReport: 'recent',
      fetcher: async (url) => {
        urls.push(url);
        return emptyListHtml;
      },
    });
    assert.ok(urls[0].includes('finalReport=recent'));
  });
});

describe('fetchDisclosureListResult 총건수', () => {
  it('총 0건이 있으면 totalKnown이고 listedCount는 0이다', async () => {
    const result = await fetchDisclosureListResult({
      reportType: 'F004',
      startDate: '20260816',
      endDate: '20260816',
      fetcher: async () => emptyListHtml,
    });
    assert.equal(result.totalKnown, true);
    assert.equal(result.listedCount, 0);
    assert.deepEqual(result.disclosures, []);
    assert.equal(result.error, null);
  });

  it('총건수 문구가 없는 빈 페이지는 totalKnown이 아니다', async () => {
    const result = await fetchDisclosureListResult({
      reportType: 'F004',
      startDate: '20260817',
      endDate: '20260817',
      fetcher: async () => '<html><body><table><tbody id="tbody"></tbody></table></body></html>',
    });
    assert.equal(result.totalKnown, false);
    assert.equal(result.listedCount, 0);
    assert.equal(result.error, null);
  });

  it('조회 결과가 없습니다 한 행은 확인된 0건이다', async () => {
    const result = await fetchDisclosureListResult({
      reportType: 'F004',
      startDate: '20261011',
      endDate: '20261011',
      fetcher: async () => emptyNoDataListHtml,
    });
    assert.equal(result.totalKnown, true);
    assert.equal(result.listedCount, 0);
    assert.deepEqual(result.disclosures, []);
    assert.equal(result.error, null);
    assert.equal(result.pageSummary, null);
  });

  it('총건수도 no_data도 없는 페이지는 totalKnown이 아니고 요약을 채운다', async () => {
    const html = [
      '<html><body>',
      '<div class="notice">',
      '  시스템   점검',
      '중입니다. 잠시 후 다시 이용해 주세요.',
      '</div>',
      '</body></html>',
    ].join('\n');
    const result = await fetchDisclosureListResult({
      reportType: 'F004',
      startDate: '20261012',
      endDate: '20261012',
      fetcher: async () => html,
    });
    assert.equal(result.totalKnown, false);
    assert.equal(result.listedCount, 0);
    assert.deepEqual(result.disclosures, []);
    assert.equal(result.error, null);
    assert.equal(typeof result.pageSummary, 'string');
    assert.ok(result.pageSummary.includes(String(html.length)));
    assert.ok(result.pageSummary.includes('tbody'));
    assert.ok(result.pageSummary.includes('없음'));
    assert.ok(result.pageSummary.includes('행 0'));
    assert.ok(result.pageSummary.includes('시스템 점검 중입니다.'));
    assert.equal(result.pageSummary.includes('시스템   점검'), false);
  });
});
