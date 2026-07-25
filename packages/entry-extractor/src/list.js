// 1단계: DART 상세검색 목록 수집
const cheerio = require('cheerio');
const { BASE_URL, safeGet } = require('./client');
const { parseDisclosureRow } = require('./parse');

/**
 * DART 상세검색(dsab007/detailSearch.ax)을 페이지네이션하며 공시 목록을 수집한다.
 *
 * @param {object} params
 * @param {string} params.reportType 공시 유형(publicType). 예: 'A001', 'F001'
 * @param {string} params.startDate 시작일 YYYYMMDD
 * @param {string} params.endDate 종료일 YYYYMMDD
 * @param {number} [params.maxResults=15] 페이지당 결과 수
 * @param {number} [params.maxTotal=null] 전체 최대 수집 건수(옵션)
 * @param {string|number} [params.year=null] 사업연도 태깅용(옵션)
 * @param {(info: object) => void} [params.onProgress] 진행 콜백(옵션)
 * @returns {Promise<object[]>} 공시 메타데이터 배열(각 항목에 main.do url 포함)
 */
async function fetchDisclosureList({
  reportType,
  startDate,
  endDate,
  maxResults = 15,
  maxTotal = null,
  year = null,
  onProgress = null,
} = {}) {
  if (!reportType) throw new Error('reportType은 필수입니다.');
  if (!startDate || !endDate) throw new Error('startDate/endDate는 필수입니다 (YYYYMMDD).');

  const allDisclosures = [];
  const seenRceptNos = new Set();

  let currentPage = 1;
  let totalCount = 0;

  while (true) {
    const params = new URLSearchParams({
      currentPage: String(currentPage),
      maxResults: String(maxResults),
      maxLinks: '10',
      startDate,
      endDate,
      finalReport: 'recent',
      publicType: reportType,
    });
    const url = `${BASE_URL}/dsab007/detailSearch.ax?${params.toString()}`;

    let response;
    try {
      response = await safeGet(url);
    } catch (err) {
      if (onProgress) onProgress({ type: 'error', reportType, currentPage, message: err.message });
      break;
    }

    const $ = cheerio.load(response.data);

    if (currentPage === 1) {
      // 페이지 정보는 '[1/3] [총 42건]' 형태로 div.pageInfo에 들어있다.
      const pageInfoText = $('div.pageInfo').first().text() || $('span.total').text();
      const match = pageInfoText.match(/총\s*([\d,]+)\s*건/);
      if (match) totalCount = parseInt(match[1].replace(/,/g, ''), 10);
      if (onProgress) onProgress({ type: 'total', reportType, year, totalCount });
    }

    const rows = $('#tbody tr').toArray();
    if (rows.length === 0) break;

    const beforeCount = allDisclosures.length;
    for (const row of rows) {
      const disclosure = parseDisclosureRow($, row, BASE_URL, reportType);
      if (disclosure && !seenRceptNos.has(disclosure.rcept_no)) {
        seenRceptNos.add(disclosure.rcept_no);
        if (year != null) disclosure.bsns_year = String(year);
        allDisclosures.push(disclosure);
      }
    }

    const newCount = allDisclosures.length - beforeCount;
    if (onProgress) {
      onProgress({ type: 'page', reportType, year, currentPage, collected: allDisclosures.length });
    }

    if (newCount === 0) break;
    if (maxTotal && allDisclosures.length >= maxTotal) break;
    if (totalCount && allDisclosures.length >= totalCount) break;

    currentPage++;
  }

  return maxTotal ? allDisclosures.slice(0, maxTotal) : allDisclosures;
}

module.exports = { fetchDisclosureList };
