// DART 상세검색 결과 HTML 파싱 유틸
function normalizeText(value) {
  if (value === null || value === undefined) return '';
  return value.replace(/\s+/g, ' ').trim();
}

/**
 * 상세검색 결과 테이블의 한 행(tr)을 공시 메타데이터로 변환한다.
 * @param {import('cheerio').CheerioAPI} $ cheerio 인스턴스
 * @param {any} row tr 엘리먼트
 * @param {string} baseUrl DART base URL
 * @param {string} reportType 조회한 공시 유형
 * @returns {object|null} 공시 메타데이터 또는 파싱 실패 시 null
 */
function parseDisclosureRow($, row, baseUrl, reportType) {
  const reportLink = $(row).find('a[href^="/dsaf001/main.do?rcpNo="]').first();
  if (reportLink.length === 0) return null;

  const href = reportLink.attr('href');
  const text = normalizeText(reportLink.text());
  if (!href || !text) return null;

  const reportUrl = new URL(href, baseUrl);
  const rceptNo = reportUrl.searchParams.get('rcpNo') || '';
  if (!rceptNo) return null;

  const tds = $(row).find('td').toArray();

  const corpCell = tds[1] ? $(tds[1]) : null;
  const corpLink = corpCell ? corpCell.find('a[href^="javascript:openCorpInfoNew"]').first() : null;
  // 회사명은 기업개황 링크 텍스트만 사용 (셀 전체 text의 IR 배지·시장구분 제외)
  let corpName = corpLink && corpLink.length > 0
    ? normalizeText(corpLink.text())
    : corpCell
      ? normalizeText(corpCell.text())
      : '';
  // fallback: 시장구분 접두사·끝의 IR 링크 문구 제거
  corpName = corpName.replace(/^(코|유|기|넥)\s+/, '').replace(/\s*IR\s*$/i, '').trim();

  const corpLinkHref = corpLink && corpLink.length > 0 ? corpLink.attr('href') : '';
  const corpCodeMatch = corpLinkHref ? corpLinkHref.match(/openCorpInfoNew\('([\d]+)'/) : null;
  const corpCode = corpCodeMatch ? corpCodeMatch[1] : '';

  const submitter = tds[3] ? normalizeText($(tds[3]).text()) : '';
  const rceptDate = tds[4] ? normalizeText($(tds[4]).text()) : '';

  const prefixMatch = text.match(/^\[([^\]]+)\]/);
  const correctionType = prefixMatch ? prefixMatch[1] : '최초공시';
  const textWithoutPrefix = text.replace(/^\[([^\]]+)\]/, '').trim();

  const yearEndMatch = textWithoutPrefix.match(/\(\d{4}\.\d{2}\)$/);
  const yearEnd = yearEndMatch ? yearEndMatch[0] : '';
  const reportName = textWithoutPrefix.replace(yearEnd, '').trim();

  return {
    reportType,
    rcept_no: rceptNo,
    correction_type: correctionType,
    report_nm: reportName,
    year_end: yearEnd,
    corp_code: corpCode,
    corp_name: corpName,
    submitter,
    rcept_dt: rceptDate,
    url: reportUrl.toString(),
  };
}

module.exports = {
  normalizeText,
  parseDisclosureRow,
};
