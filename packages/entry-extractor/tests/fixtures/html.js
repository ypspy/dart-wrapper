/** extractTree용 최소 treeData 스크립트 HTML을 만든다. */
function treeDataHtml({ rcpNo, dcmNo, nodes }) {
  // nodes: [{ depth, text, eleId, offset, length, dtd, childrenDepths? }]
  const lines = ['<html><body><script>', 'var treeData = [];'];
  for (const n of nodes) {
    const d = n.depth;
    lines.push(`var node${d} = {};`);
    lines.push(`node${d}['text'] = "${n.text}";`);
    lines.push(`node${d}['rcpNo'] = "${rcpNo}";`);
    lines.push(`node${d}['dcmNo'] = "${dcmNo}";`);
    lines.push(`node${d}['eleId'] = "${n.eleId}";`);
    lines.push(`node${d}['offset'] = "${n.offset ?? '0'}";`);
    lines.push(`node${d}['length'] = "${n.length ?? '10'}";`);
    lines.push(`node${d}['dtd'] = "${n.dtd ?? 'dart4.xsd'}";`);
    lines.push(`node${d}['children'] = [];`);
  }
  for (const n of nodes) {
    for (const childDepth of n.childrenDepths || []) {
      lines.push(`node${n.depth}['children'].push(node${childDepth});`);
    }
  }
  const childSet = new Set(nodes.flatMap((n) => n.childrenDepths || []));
  for (const n of nodes) {
    if (!childSet.has(n.depth)) {
      lines.push(`treeData.push(node${n.depth});`);
    }
  }
  lines.push('</script></body></html>');
  return lines.join('\n');
}

function attachmentSelectHtml({ rcpNo, dcmNo, name }) {
  return [
    `<select id="att">`,
    `<option value="rcpNo=${rcpNo}&dcmNo=${dcmNo}">${name}</option>`,
    '</select>',
    '<select id="doc"></select>',
  ].join('\n');
}

/** 본문 HTML(</body> 앞)에 추가 조각을 끼워 넣는다. */
function mergeHtml(mainHtml, ...fragments) {
  const injection = fragments.join('\n');
  if (mainHtml.includes('</body>')) {
    return mainHtml.replace('</body>', `${injection}\n</body>`);
  }
  return `<html><body>${mainHtml}\n${injection}</body></html>`;
}

const sampleDisclosure = {
  reportType: 'F001',
  rcept_no: '20260724000650',
  report_nm: '감사보고서',
  corp_code: '00224628',
  corp_name: '테스트법인',
  submitter: '테스트회계법인',
  rcept_dt: '2026.07.24',
  url: 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724000650',
};

module.exports = {
  treeDataHtml,
  attachmentSelectHtml,
  mergeHtml,
  sampleDisclosure,
};
