// 1단계: DART 상세검색 목록 수집
const cheerio = require('cheerio');
const { BASE_URL, safeGet } = require('./client');
const { parseDisclosureRow } = require('./parse');

/**
 * DART 상세검색(dsab007/detailSearch.ax)을 페이지네이션하며 공시 목록을 수집한다.
 *
 * 기본은 최종보고서 체크 해제와 동일(finalReport 미전송)이라 이력 접수가 포함된다.
 * 최종만 보려면 finalReport: 'recent'를 넘긴다.
 *
 * @param {object} params
 * @param {string} params.reportType 공시 유형(publicType). 예: 'A001', 'F001'
 * @param {string} params.startDate 시작일 YYYYMMDD
 * @param {string} params.endDate 종료일 YYYYMMDD
 * @param {number} [params.maxResults=15] 페이지당 결과 수
 * @param {number} [params.maxTotal=null] 전체 최대 수집 건수(옵션)
 * @param {string|number} [params.year=null] 사업연도 태깅용(옵션)
 * @param {(info: object) => void} [params.onProgress] 진행 콜백(옵션)
 * @param {'recent'|null} [params.finalReport=null] 'recent'면 최종보고서만
 * @param {(url: string) => Promise<string>} [params.fetcher] 테스트용 HTML 공급
 * @returns {Promise<{listedCount: number, disclosures: object[], error: Error|null}>}
 *   원천이 알려준 총건수와 공시 메타데이터 배열(각 항목에 main.do url 포함).
 *   수집 도중 요청이 실패하면 error에 마지막 오류가 담긴다.
 */
async function fetchDisclosureListResult({
  reportType,
  startDate,
  endDate,
  maxResults = 15,
  maxTotal = null,
  year = null,
  onProgress = null,
  finalReport = null,
  fetcher = null,
} = {}) {
  if (!reportType) throw new Error('reportType은 필수입니다.');
  if (!startDate || !endDate) throw new Error('startDate/endDate는 필수입니다 (YYYYMMDD).');

  const allDisclosures = [];
  const seenRceptNos = new Set();

  let currentPage = 1;
  let totalCount = 0;
  let lastError = null;

  while (true) {
    const params = new URLSearchParams({
      currentPage: String(currentPage),
      maxResults: String(maxResults),
      maxLinks: '10',
      startDate,
      endDate,
      publicType: reportType,
    });
    if (finalReport === 'recent') params.set('finalReport', 'recent');
    const url = `${BASE_URL}/dsab007/detailSearch.ax?${params.toString()}`;

    let html;
    try {
      if (fetcher) {
        html = await fetcher(url);
      } else {
        const response = await safeGet(url);
        html = response.data;
      }
    } catch (err) {
      if (onProgress) onProgress({ type: 'error', reportType, currentPage, message: err.message });
      lastError = err;
      break;
    }

    const $ = cheerio.load(html);

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

  const disclosures = maxTotal ? allDisclosures.slice(0, maxTotal) : allDisclosures;
  // 총건수를 못 읽었으면 실제 수집 건수를 기대치로 삼는다.
  const listedCount = maxTotal
    ? Math.min(maxTotal, totalCount || disclosures.length)
    : totalCount || disclosures.length;

  return { listedCount, disclosures, error: lastError };
}

/**
 * 기존 호출부 호환용 래퍼. 공시 배열만 반환한다.
 *
 * @param {object} params fetchDisclosureListResult와 동일
 * @returns {Promise<object[]>} 공시 메타데이터 배열
 */
async function fetchDisclosureList(params = {}) {
  const { disclosures } = await fetchDisclosureListResult(params);
  return disclosures;
}

module.exports = { fetchDisclosureList, fetchDisclosureListResult };
