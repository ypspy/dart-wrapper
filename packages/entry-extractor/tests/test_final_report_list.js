const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { fetchDisclosureListResult } = require('../src/list');

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
