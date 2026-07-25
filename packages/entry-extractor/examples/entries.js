// 3단계 예제: leaf 엔트리 = 공시 features + 문서/섹션 정보
//
// 사용법: node examples/entries.js [reportType] [startDate] [endDate] [maxTotal]
const { collectEntries } = require('../src');

function today() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;
}

async function main() {
  const [reportType = 'F001', startDate = today(), endDate = startDate, maxTotal = '2'] =
    process.argv.slice(2);

  console.log(`조회 조건: ${reportType} / ${startDate} ~ ${endDate} / 최대 ${maxTotal}건\n`);

  const entries = await collectEntries({
    reportType,
    startDate,
    endDate,
    maxTotal: Number(maxTotal),
    onEntry: ({ disclosure, entryCount }) => {
      console.log(`  [${disclosure.corp_name}] ${disclosure.report_nm} → 엔트리 ${entryCount}개`);
    },
  });

  console.log(`\n총 엔트리: ${entries.length}개\n`);

  // 샘플 1건 전체 출력
  if (entries[0]) {
    console.log('── 엔트리 예시 ──');
    console.log(JSON.stringify(entries[0], null, 2));
  }

  console.log('\n── 전체 요약 (entry_id | 회사 | 섹션경로) ──');
  for (const e of entries) {
    console.log(`${e.entry_id} | ${e.corp_name} | ${e.path.join(' > ')}`);
  }
}

main().catch((err) => {
  console.error('실행 오류:', err.message);
  process.exit(1);
});
