// 2단계: 공시 상세페이지에서 각 문서/목차 접근 URL 파싱
//
// 상세페이지에는 두 종류의 문서 정보가 있다.
//  - 본문: 스크립트의 treeData 노드(목차). children으로 부모-자식 연결
//  - 첨부/관련: #att(PC), #doc(모바일) select의 option
const cheerio = require('cheerio');
const { BASE_URL, safeGet } = require('./client');
const { normalizeText } = require('./parse');

function documentUrl(rcpNo, dcmNo) {
  return `${BASE_URL}/dsaf001/main.do?rcpNo=${rcpNo}&dcmNo=${dcmNo}`;
}

/**
 * 목차 노드를 실제 본문 내용을 반환하는 viewer.do URL로 변환한다.
 * viewDoc()이 조립하는 파라미터 순서를 그대로 따른다.
 */
function viewerUrl({ rcpNo, dcmNo, eleId, offset, length, dtd }) {
  let params = `?rcpNo=${rcpNo}&dcmNo=${dcmNo}`;
  if (eleId != null) params += `&eleId=${eleId}`;
  if (offset != null) params += `&offset=${offset}`;
  if (length != null) params += `&length=${length}`;
  if (dtd != null) params += `&dtd=${dtd}`;
  return `${BASE_URL}/report/viewer.do${params}`;
}

/**
 * DART 목차 특유의 '글자 사이 공백'을 제거한다.
 * 예: '감 사 보 고 서' → '감사보고서'
 * 일반 띄어쓰기('독립된 감사인의 감사보고서')는 유지한다.
 */
function normalizeDartTitle(text) {
  const value = normalizeText(text);
  if (!value) return '';

  const tokens = value.split(/\s+/);
  const singleCharRatio =
    tokens.filter((t) => t.replace(/[()[\]{}]/g, '').length <= 1).length /
    Math.max(tokens.length, 1);

  if (singleCharRatio < 0.5) return value;

  return value.replace(
    /([\uAC00-\uD7A3A-Za-z0-9])\s+(?=[\uAC00-\uD7A3A-Za-z0-9(])/g,
    '$1'
  );
}

/** 정정신고/기재정정 안내 노드인지 판별 */
function isCorrectionNotice(name) {
  const compact = (name || '').replace(/\s+/g, '');
  return /정정신고/.test(compact) || /^기재정정/.test(compact);
}

/**
 * 문서/섹션명을 보정한다.
 * - 기본: DART 글자사이 공백 정규화
 * - replaceCorrectionNotice=true 이고 정정신고 안내면 목록의 report_nm으로 교체
 */
function correctName(name, disclosure = null, { replaceCorrectionNotice = false } = {}) {
  const originalName = normalizeText(name);
  const normalized = normalizeDartTitle(originalName);
  const spacingChanged = normalized !== originalName;

  if (
    replaceCorrectionNotice &&
    disclosure?.report_nm &&
    isCorrectionNotice(normalized)
  ) {
    return {
      name: disclosure.report_nm,
      originalName,
      corrected: true,
      normalized: spacingChanged,
    };
  }

  return {
    name: normalized,
    originalName,
    corrected: false,
    normalized: spacingChanged,
  };
}

/** 원시 노드 → API 노드 */
function finalizeNode(raw, disclosure, parentEleId = null) {
  if (!raw?.props?.rcpNo || !raw?.props?.dcmNo) return null;

  const naming = correctName(raw.props.text, disclosure, {
    replaceCorrectionNotice: false,
  });

  const node = {
    name: naming.name,
    originalName: naming.originalName,
    corrected: naming.corrected,
    normalized: naming.normalized,
    depth: raw.depth,
    parentEleId,
    rcpNo: raw.props.rcpNo,
    dcmNo: raw.props.dcmNo,
    eleId: raw.props.eleId,
    offset: raw.props.offset,
    length: raw.props.length,
    dtd: raw.props.dtd,
    url: viewerUrl(raw.props),
    children: [],
  };

  const childParentId = node.eleId || null;
  for (const child of raw.children || []) {
    const finalized = finalizeNode(child, disclosure, childParentId);
    if (finalized) node.children.push(finalized);
  }

  return node;
}

/**
 * 상세페이지 스크립트의 treeData를 부모-자식(children) 관계 그대로 파싱한다.
 *
 * DART는 아래와 같은 JS를 생성한다.
 *   var node1 = {}; node1['text'] = "...";
 *   node1['children'] = [];
 *   var node2 = {}; ...; node1['children'].push(node2);
 *   treeData.push(node1);
 *
 * @param {string} html 상세페이지 HTML
 * @param {object} [disclosure] 이름 보정용 공시 메타데이터
 * @returns {object[]} 최상위 목차 트리
 */
function extractTree(html, disclosure = null) {
  const current = Object.create(null); // depth -> raw node
  const roots = [];

  // 목차 구성 구문만 순서대로 읽는다.
  const stmtRe =
    /var\s+node(\d+)\s*=\s*\{\s*\};|node(\d+)\['(\w+)'\]\s*=\s*"([^"]*)"|node(\d+)\['children'\]\s*=\s*\[\s*\]|node(\d+)\['children'\]\.push\(node(\d+)\)|treeData\.push\(node(\d+)\)/g;

  let match;
  while ((match = stmtRe.exec(html)) !== null) {
    if (match[1]) {
      // var nodeN = {};
      const depth = Number(match[1]);
      current[depth] = { depth, props: {}, children: [] };
      continue;
    }

    if (match[2]) {
      // nodeN['key'] = "value";
      const depth = Number(match[2]);
      const key = match[3];
      const value = match[4];
      if (current[depth]) current[depth].props[key] = value;
      continue;
    }

    if (match[5]) {
      // nodeN['children'] = [];
      const depth = Number(match[5]);
      if (current[depth]) current[depth].children = [];
      continue;
    }

    if (match[6]) {
      // nodeN['children'].push(nodeM);
      const parentDepth = Number(match[6]);
      const childDepth = Number(match[7]);
      const parent = current[parentDepth];
      const child = current[childDepth];
      if (parent && child) parent.children.push(child);
      continue;
    }

    if (match[8]) {
      // treeData.push(nodeN);
      const depth = Number(match[8]);
      const raw = current[depth];
      const node = finalizeNode(raw, disclosure, null);
      if (node) roots.push(node);
    }
  }

  return roots;
}

/**
 * 트리를 전위순회로 flat 배열로 펼친다.
 * @param {object[]} tree extractTree 결과
 * @returns {object[]} children 없는 섹션 배열(parentEleId, depth 유지)
 */
function flattenTree(tree) {
  const sections = [];

  function walk(nodes) {
    for (const node of nodes || []) {
      const { children, ...rest } = node;
      sections.push({ ...rest, childCount: (children || []).length });
      walk(children);
    }
  }

  walk(tree);
  return sections;
}

/** @deprecated extractTree + flattenTree 조합. 하위 호환용 */
function extractSections(html, disclosure = null) {
  return flattenTree(extractTree(html, disclosure));
}

/**
 * 동일 dcmNo 섹션들에서 본문 문서의 대표명을 고른다.
 * 정정신고 안내보다 실제 보고서 제목(또는 report_nm)을 우선한다.
 */
function resolveBodyName(sectionsForDcm, disclosure = null) {
  const sorted = [...sectionsForDcm].sort((a, b) => a.depth - b.depth);

  for (const section of sorted) {
    if (!isCorrectionNotice(section.originalName || section.name)) {
      return {
        name: section.name,
        originalName: section.originalName,
        corrected: false,
        normalized: !!section.normalized,
      };
    }
  }

  if (disclosure?.report_nm) {
    return {
      name: disclosure.report_nm,
      originalName: sorted[0]?.originalName || '',
      corrected: true,
      normalized: !!sorted[0]?.normalized,
    };
  }

  const first = sorted[0];
  return {
    name: first?.name || '',
    originalName: first?.originalName || '',
    corrected: false,
    normalized: !!first?.normalized,
  };
}

/** 특정 dcmNo에 해당하는 서브트리만 남긴다. */
function filterTreeByDcmNo(tree, dcmNo) {
  const result = [];
  for (const node of tree || []) {
    if (node.dcmNo === dcmNo) {
      result.push(node);
      continue;
    }
    result.push(...filterTreeByDcmNo(node.children, dcmNo));
  }
  return result;
}

/**
 * 목차에서 본문 문서(dcmNo 단위)를 추려낸다.
 */
function toBodyDocuments(tree, disclosure = null) {
  const sections = flattenTree(tree);
  const grouped = new Map();

  for (const section of sections) {
    if (!grouped.has(section.dcmNo)) grouped.set(section.dcmNo, []);
    grouped.get(section.dcmNo).push(section);
  }

  return [...grouped.entries()].map(([dcmNo, group]) => {
    const naming = resolveBodyName(group, disclosure);
    const top = [...group].sort((a, b) => a.depth - b.depth)[0];

    return {
      name: naming.name,
      originalName: naming.originalName,
      corrected: naming.corrected,
      normalized: naming.normalized,
      url: documentUrl(top.rcpNo, dcmNo),
      viewerUrl: top.url,
      rcpNo: top.rcpNo,
      dcmNo,
      source: 'body',
      tree: filterTreeByDcmNo(tree, dcmNo),
      sections: group,
    };
  });
}

/**
 * 첨부문서 select(option)에서 문서 정보를 추출한다.
 */
function extractAttachments($, options, isMobile = false) {
  const result = [];

  options.each((_, option) => {
    const value = $(option).attr('value');
    if (!value || value === 'null') return;
    if (isMobile && !value.includes('dcmNo')) return;

    const text = normalizeText($(option).text());

    const params = {};
    value.split('&').forEach((pair) => {
      const [k, v] = pair.split('=');
      if (k) params[k] = v;
    });
    if (!params.rcpNo || !params.dcmNo) return;

    const dateMatch = text.match(/\d{4}\.\d{2}\.\d{2}/);
    const reportDate = dateMatch ? dateMatch[0] : '';

    let correctionType = '';
    if (text.includes('[기재정정]')) correctionType = '기재정정';
    else if (text.includes('[정정]')) correctionType = '정정';

    const rawName = text
      .replace(/\d{4}\.\d{2}\.\d{2}/, '')
      .replace(/\[[^\]]+\]/g, '')
      .trim();
    const naming = correctName(rawName);

    result.push({
      name: naming.name,
      originalName: naming.originalName,
      corrected: naming.corrected,
      normalized: naming.normalized,
      url: documentUrl(params.rcpNo, params.dcmNo),
      rcpNo: params.rcpNo,
      dcmNo: params.dcmNo,
      reportDate,
      correctionType,
      source: 'attachment',
    });
  });

  return result;
}

/** rcpNo + dcmNo 기준 중복 제거 (먼저 나온 항목 우선) */
function dedupe(documents) {
  const seen = new Set();
  const unique = [];
  for (const doc of documents) {
    const key = `${doc.rcpNo}_${doc.dcmNo}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(doc);
  }
  return unique;
}

/**
 * 상세페이지를 한 번만 요청해 목차 트리 + flat 섹션 + 문서 목록을 반환한다.
 *
 * @returns {Promise<{ tree: object[], sections: object[], documents: object[] }>}
 */
async function parseDetail(
  disclosureUrl,
  { disclosure = null, body = true, attachments = true, fetcher = null } = {}
) {
  if (!disclosureUrl) throw new Error('disclosureUrl은 필수입니다.');

  const getHtml =
    fetcher ||
    (async (u) => {
      const response = await safeGet(u);
      return response.data;
    });
  const html = await getHtml(disclosureUrl);
  const $ = cheerio.load(html);

  const tree = extractTree(html, disclosure);
  const sections = flattenTree(tree);
  const documents = [];

  if (body) documents.push(...toBodyDocuments(tree, disclosure));
  if (attachments) {
    documents.push(
      ...extractAttachments($, $('#att option'), false),
      ...extractAttachments($, $('#doc option'), true)
    );
  }

  return {
    tree,
    sections,
    documents: dedupe(documents),
  };
}

/**
 * 첨부 dcmNo 전용 상세페이지에서 목차 트리를 파싱한다.
 *
 * @param {string} rcpNo
 * @param {string} dcmNo
 * @param {{ fetcher?: (url: string) => Promise<string> }} [options]
 * @returns {Promise<object[]>}
 */
async function parseAttachmentDetail(rcpNo, dcmNo, { fetcher = null } = {}) {
  if (!rcpNo || !dcmNo) throw new Error('rcpNo와 dcmNo는 필수입니다.');
  const url = documentUrl(rcpNo, dcmNo);
  const getHtml =
    fetcher ||
    (async (u) => {
      const response = await safeGet(u);
      return response.data;
    });
  const html = await getHtml(url);
  return extractTree(html);
}

async function parseDocuments(disclosureUrl, options = {}) {
  const { documents } = await parseDetail(disclosureUrl, options);
  return documents;
}

/**
 * 공시 본문의 목차 트리(부모-자식)를 파싱한다.
 */
async function parseTree(disclosureUrl, { disclosure = null } = {}) {
  if (!disclosureUrl) throw new Error('disclosureUrl은 필수입니다.');
  const response = await safeGet(disclosureUrl);
  return extractTree(response.data, disclosure);
}

/**
 * 공시 본문의 목차 섹션을 flat 배열로 파싱한다.
 * 각 항목에 parentEleId, depth가 포함된다.
 */
async function parseSections(disclosureUrl, { disclosure = null } = {}) {
  if (!disclosureUrl) throw new Error('disclosureUrl은 필수입니다.');
  const response = await safeGet(disclosureUrl);
  return flattenTree(extractTree(response.data, disclosure));
}

module.exports = {
  parseDetail,
  parseAttachmentDetail,
  parseDocuments,
  parseTree,
  parseSections,
  extractTree,
  extractSections,
  flattenTree,
  correctName,
  normalizeDartTitle,
  isCorrectionNotice,
  viewerUrl,
};
