// 3단계: leaf 노드까지 펼쳐 공시 features와 합친 flat 엔트리 생성
const { fetchDisclosureList } = require('./list');
const { parseDetail } = require('./documents');

// 공시 목록에서 얻는 features (엔트리에 반영할 필드)
const DISCLOSURE_FEATURE_KEYS = [
  'reportType',
  'rcept_no',
  'correction_type',
  'report_nm',
  'year_end',
  'corp_code',
  'corp_name',
  'submitter',
  'rcept_dt',
  'bsns_year',
];

function pickFeatures(disclosure = {}) {
  const features = {};
  for (const key of DISCLOSURE_FEATURE_KEYS) {
    if (disclosure[key] !== undefined) features[key] = disclosure[key];
  }
  return features;
}

/**
 * DB upsert/중복 제거용 엔트리 식별자.
 * 본문: rcept_no + dcmNo + ele_id
 * 첨부(ele_id 없음): rcept_no + dcmNo + 'att'
 */
function makeEntryId({ rcept_no, dcmNo, ele_id, source }) {
  const elePart = ele_id != null && ele_id !== '' ? String(ele_id) : source === 'attachment' ? 'att' : 'root';
  return [rcept_no || '', dcmNo || '', elePart].join('_');
}

/** 본문 목차 트리에 등장하는 dcmNo 집합 */
function collectBodyDcmNos(tree) {
  const set = new Set();
  function walk(nodes) {
    for (const node of nodes || []) {
      if (node.dcmNo) set.add(String(node.dcmNo));
      walk(node.children);
    }
  }
  walk(tree);
  return set;
}

/**
 * parseDetail 결과(tree/documents)와 공시 features를 합쳐
 * leaf 단위 flat 엔트리 배열을 만든다.
 *
 * @param {object} disclosure 1단계에서 수집한 공시 메타데이터
 * @param {object} detail parseDetail 결과 { tree, documents }
 * @param {object} [options]
 * @param {boolean} [options.leafOnly=true] leaf(자식 없는 노드)만 엔트리로
 * @param {boolean} [options.includeAttachments=true] 첨부문서도 엔트리에 포함
 * @param {Record<string, object[]>} [options.attachmentTrees] 첨부 dcmNo → 목차 트리 (HTTP 없음)
 * @returns {object[]} 엔트리 배열
 */
function buildEntries(
  disclosure,
  detail,
  { leafOnly = true, includeAttachments = true, attachmentTrees = {} } = {}
) {
  const { tree = [], documents = [] } = detail || {};
  const features = pickFeatures(disclosure);
  const disclosureUrl = disclosure?.url || null;

  // dcmNo -> 본문 문서명 매핑 (엔트리에 document_name으로 반영)
  const bodyNameByDcmNo = new Map();
  for (const doc of documents) {
    if (doc.source === 'body') bodyNameByDcmNo.set(doc.dcmNo, doc.name);
  }

  const entries = [];

  function walk(node, path) {
    const currentPath = [...path, node.name];
    const isLeaf = !node.children || node.children.length === 0;

    if (isLeaf || !leafOnly) {
      const entry = {
        ...features,
        disclosure_url: disclosureUrl,
        source: 'body',
        dcmNo: node.dcmNo,
        document_name: bodyNameByDcmNo.get(node.dcmNo) || null,
        section_name: node.name,
        section_original_name: node.originalName,
        depth: node.depth,
        is_leaf: isLeaf,
        parent_ele_id: node.parentEleId,
        ele_id: node.eleId,
        offset: node.offset,
        length: node.length,
        dtd: node.dtd,
        path: currentPath,
        viewer_url: node.url,
      };
      entry.entry_id = makeEntryId(entry);
      entries.push(entry);
    }

    for (const child of node.children || []) {
      walk(child, currentPath);
    }
  }

  for (const root of tree) {
    walk(root, []);
  }

  if (includeAttachments) {
    const bodyDcmNos = collectBodyDcmNos(tree);

    for (const doc of documents) {
      if (doc.source !== 'attachment') continue;
      const dcmNo = String(doc.dcmNo);
      if (bodyDcmNos.has(dcmNo)) continue;

      const attTree = attachmentTrees[dcmNo];
      const hasLeaves = Array.isArray(attTree) && attTree.length > 0;

      if (hasLeaves) {
        function walkAtt(node, path) {
          const currentPath = [...path, node.name];
          const isLeaf = !node.children || node.children.length === 0;
          if (isLeaf || !leafOnly) {
            const entry = {
              ...features,
              disclosure_url: disclosureUrl,
              source: 'attachment',
              dcmNo: node.dcmNo,
              document_name: doc.name,
              section_name: node.name,
              section_original_name: node.originalName,
              depth: node.depth,
              is_leaf: isLeaf,
              parent_ele_id: node.parentEleId,
              ele_id: node.eleId,
              offset: node.offset,
              length: node.length,
              dtd: node.dtd,
              path: currentPath,
              viewer_url: node.url,
            };
            entry.entry_id = makeEntryId(entry);
            entries.push(entry);
          }
          for (const child of node.children || []) {
            walkAtt(child, currentPath);
          }
        }
        for (const root of attTree) {
          walkAtt(root, []);
        }
        continue;
      }

      // 트리 없음·빈 배열·미제공 → 문서 단위 fallback
      const entry = {
        ...features,
        disclosure_url: disclosureUrl,
        source: 'attachment',
        dcmNo: doc.dcmNo,
        document_name: doc.name,
        section_name: doc.name,
        section_original_name: doc.originalName,
        depth: 1,
        is_leaf: true,
        parent_ele_id: null,
        ele_id: null,
        offset: null,
        length: null,
        dtd: null,
        path: [doc.name],
        viewer_url: doc.url,
      };
      entry.entry_id = makeEntryId(entry);
      entries.push(entry);
    }
  }

  return entries;
}

/**
 * 1·2·3단계 통합: 목록 수집 → 상세 파싱 → leaf 엔트리 생성.
 * 각 공시마다 상세페이지를 1회 요청한다(요청 간 지연은 client에서 처리).
 *
 * @param {object} params fetchDisclosureList 파라미터 + 아래 옵션
 * @param {boolean} [params.leafOnly=true]
 * @param {boolean} [params.includeAttachments=true]
 * @param {(info: object) => void} [params.onEntry] 공시 단위 진행 콜백
 * @returns {Promise<object[]>} 모든 공시의 leaf 엔트리 flat 배열
 */
async function collectEntries(params = {}) {
  const {
    leafOnly = true,
    includeAttachments = true,
    onEntry = null,
    ...listParams
  } = params;

  const disclosures = await fetchDisclosureList(listParams);
  const allEntries = [];

  for (const disclosure of disclosures) {
    const detail = await parseDetail(disclosure.url, { disclosure });
    const entries = buildEntries(disclosure, detail, { leafOnly, includeAttachments });
    allEntries.push(...entries);

    if (onEntry) {
      onEntry({
        disclosure,
        entryCount: entries.length,
        totalEntries: allEntries.length,
      });
    }
  }

  return allEntries;
}

module.exports = {
  buildEntries,
  collectEntries,
  collectBodyDcmNos,
  pickFeatures,
  makeEntryId,
  DISCLOSURE_FEATURE_KEYS,
};
