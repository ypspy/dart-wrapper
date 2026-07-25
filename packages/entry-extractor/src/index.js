// dart-wrapper: DART 공시 목록 수집 + 문서 접근 URL 파싱
const { BASE_URL, sleep, safeGet } = require('./client');
const { normalizeText, parseDisclosureRow } = require('./parse');
const { fetchDisclosureList } = require('./list');
const {
  parseDetail,
  parseDocuments,
  parseTree,
  parseSections,
  flattenTree,
  correctName,
  normalizeDartTitle,
  viewerUrl,
} = require('./documents');
const {
  buildEntries,
  collectEntries,
  pickFeatures,
  makeEntryId,
} = require('./entries');

module.exports = {
  // 1단계
  fetchDisclosureList,
  parseDisclosureRow,
  // 2단계
  parseDetail,
  parseDocuments,
  parseTree,
  parseSections,
  flattenTree,
  correctName,
  normalizeDartTitle,
  viewerUrl,
  // 3단계
  buildEntries,
  collectEntries,
  pickFeatures,
  makeEntryId,
  // 유틸
  BASE_URL,
  sleep,
  safeGet,
  normalizeText,
};
