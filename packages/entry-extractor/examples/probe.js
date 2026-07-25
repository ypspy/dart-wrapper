// 진단용: 여러 공시 유형/기간에 대해 건수만 빠르게 확인
const { fetchDisclosureList } = require('../src');

function ymd(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`;
}

async function main() {
  const now = new Date();
  const weekAgo = new Date(now);
  weekAgo.setDate(weekAgo.getDate() - 7);

  const ranges = [
    ['오늘', ymd(now), ymd(now)],
    ['최근 7일', ymd(weekAgo), ymd(now)],
  ];
  const reportTypes = ['A001', 'A002', 'A003', 'F001', 'F002'];

  for (const [label, start, end] of ranges) {
    for (const reportType of reportTypes) {
      const list = await fetchDisclosureList({
        reportType,
        startDate: start,
        endDate: end,
        maxTotal: 5,
      });
      const sample = list[0] ? ` | 예: ${list[0].corp_name} ${list[0].rcept_dt}` : '';
      console.log(`${label} [${reportType}] ${start}~${end}: ${list.length}건${sample}`);
    }
  }
}

main().catch((err) => {
  console.error('실행 오류:', err.message);
  process.exit(1);
});
