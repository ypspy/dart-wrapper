// 1·2단계 통합 예제: 목록 수집 → 목차 트리 + 문서 URL 파싱
//
// 사용법: node examples/run.js [reportType] [startDate] [endDate] [maxTotal]
const { fetchDisclosureList, parseDetail } = require('../src');

function today() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;
}

function printTree(nodes, indent = 2) {
  for (const node of nodes || []) {
    const pad = ' '.repeat(indent);
    const parent = node.parentEleId ? ` parent=${node.parentEleId}` : '';
    console.log(`${pad}- ${node.name} [eleId=${node.eleId}${parent}] -> ${node.url}`);
    printTree(node.children, indent + 2);
  }
}

async function main() {
  const [reportType = 'A001', startDate = today(), endDate = startDate, maxTotal = '3'] =
    process.argv.slice(2);

  console.log(`조회 조건: ${reportType} / ${startDate} ~ ${endDate} / 최대 ${maxTotal}건\n`);

  const disclosures = await fetchDisclosureList({
    reportType,
    startDate,
    endDate,
    maxTotal: Number(maxTotal),
    onProgress: (info) => {
      if (info.type === 'total') console.log(`전체 건수: ${info.totalCount}`);
      if (info.type === 'page') console.log(`page ${info.currentPage} 누적 ${info.collected}건`);
    },
  });

  console.log(`\n수집된 공시: ${disclosures.length}건\n`);

  for (const d of disclosures) {
    console.log(`▶ [${d.corp_name}] ${d.report_nm} (${d.rcept_dt}) [${d.correction_type}]`);
    console.log(`  공시 URL: ${d.url}`);

    const { tree, sections, documents } = await parseDetail(d.url, { disclosure: d });
    const bodies = documents.filter((doc) => doc.source === 'body');
    const attachments = documents.filter((doc) => doc.source === 'attachment');

    for (const body of bodies) {
      const note = body.corrected
        ? ` (보정: ${body.originalName} → ${body.name})`
        : '';
      console.log(`  본문: ${body.name}${note}`);
      console.log(`        ${body.url}`);
    }

    console.log(`  목차 트리 (${sections.length}개 노드):`);
    printTree(tree);

    if (attachments.length > 0) {
      console.log(`  첨부 ${attachments.length}개:`);
      for (const doc of attachments) {
        console.log(`    - ${doc.name || '(무제)'} -> ${doc.url}`);
      }
    }

    console.log('');
  }
}

main().catch((err) => {
  console.error('실행 오류:', err.message);
  process.exit(1);
});
