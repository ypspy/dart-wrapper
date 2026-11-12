/**
 * DART 상세검색(dsab007/detailSearch.ax) 목록 HTML.
 * F004 20261011처럼 접수 공시가 없는 날의 응답. div.pageInfo와 「총 N건」이 없다.
 */
const emptyNoDataListHtml =
  '<div class="tbListInner"><table class="tbList"><caption>공시서류검색 목록</caption>' +
  '<thead><tr id="tr"><th>번호</th><th>공시대상회사</th><th>보고서명</th>' +
  '<th>제출인</th><th>접수일자</th><th>비고</th></tr></thead>\n' +
  '<tbody id="tbody"><tr><td class="no_data end" colspan="6" align="center">' +
  '조회 결과가 없습니다.</td></tr></tbody></table></div>';

module.exports = {
  emptyNoDataListHtml,
};
