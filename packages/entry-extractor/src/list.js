// 1단계: DART 상세검색 목록 수집
const cheerio = require('cheerio');
const { BASE_URL, safeGet } = require('./client');
const { parseDisclosureRow } = require('./parse');

/**
 * 첫 페이지가 '조회 결과가 없습니다' 한 줄뿐이면 확정된 0건이다.
 * 주말·휴일은 「총 N건」 없이 이 표시만 내려온다.
 * @param {import('cheerio').CheerioAPI} $
 * @param {any[]} rows #tbody tr
 * @returns {boolean}
 */
function isConfirmedEmptyListPage($, rows) {
  if (rows.length !== 1) return false;
  const marker = $(rows[0]).find('td.no_data');
  if (marker.length === 0) return false;
  const text = $(rows[0]).text().replace(/\s+/g, ' ');
  return text.includes('조회 결과가 없습니다');
}

/**
 * 총건수·정상 행·빈 결과 표시가 모두 없는 페이지의 짧은 진단.
 * 응답 길이, tbody 유무, 행 수, 공백을 접은 본문 앞 200자를 담는다.
 * @param {import('cheerio').CheerioAPI} $
 * @param {string} html
 * @returns {string}
 */
function summarizeUnknownListPage($, html) {
  const hasTbody = $('#tbody').length > 0;
  const rowCount = $('#tbody tr').length;
  const source = $('body').length > 0 ? $('body') : $.root();
  const text = source.text().replace(/\s+/g, ' ').trim().slice(0, 200);
  const tbodyState = hasTbody ? '있음' : '없음';
  return `응답 ${html.length}자, tbody ${tbodyState}, 행 ${rowCount}건, 본문: ${text}`;
}

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
 * @returns {Promise<{listedCount: number, totalKnown: boolean, disclosures: object[], error: Error|null, pageSummary: string|null}>}
 *   원천이 알려준 총건수와 공시 메타데이터 배열(각 항목에 main.do url 포함).
 *   totalKnown은 첫 페이지에서 '총 N건'을 읽었거나,
 *   조회 결과 없음(td.no_data) 한 행을 확인했을 때 true다.
 *   총건수도 정상 행도 없고 빈 결과 표시도 없으면 pageSummary에 진단 요약을 담는다.
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
  let totalKnown = false;
  let lastError = null;
  let firstPageHtml = null;

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

    if (currentPage === 1) firstPageHtml = html;

    const $ = cheerio.load(html);

    if (currentPage === 1) {
      // 페이지 정보는 '[1/3] [총 42건]' 형태로 div.pageInfo에 들어있다.
      const pageInfoText = $('div.pageInfo').first().text() || $('span.total').text();
      const match = pageInfoText.match(/총\s*([\d,]+)\s*건/);
      if (match) {
        totalCount = parseInt(match[1].replace(/,/g, ''), 10);
        totalKnown = true;
      }
      if (onProgress) onProgress({ type: 'total', reportType, year, totalCount });
    }

    const rows = $('#tbody tr').toArray();
    // 「총 N건」이 없어도 no_data 한 행이면 그 날은 공시가 없는 것이 확인된 것이다.
    if (currentPage === 1 && !totalKnown && isConfirmedEmptyListPage($, rows)) {
      totalKnown = true;
      totalCount = 0;
      break;
    }
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
  // 총건수를 못 읽었으면 수집 건수를 길잡이로만 쓰고, 완료 판정에는 쓰지 않는다.
  const observed = totalKnown ? totalCount : disclosures.length;
  const listedCount = maxTotal ? Math.min(maxTotal, observed) : observed;

  // 건수도 행도 빈 결과 표시도 없으면 차단·오류·알 수 없는 페이지로 보고 진단만 남긴다.
  let pageSummary = null;
  if (!totalKnown && disclosures.length === 0 && firstPageHtml && !lastError) {
    pageSummary = summarizeUnknownListPage(cheerio.load(firstPageHtml), firstPageHtml);
  }

  return { listedCount, totalKnown, disclosures, error: lastError, pageSummary };
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
