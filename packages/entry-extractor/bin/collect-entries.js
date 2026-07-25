#!/usr/bin/env node
// Python Admin 수집기가 호출하는 CLI 브릿지.
// stdin으로 JSON 파라미터를 받고, stdout에는 엔트리 배열 JSON만 출력한다.
// 진행 로그는 stdout을 오염시키지 않도록 stderr로 보낸다.
const { collectEntries } = require('../src');

function readStdin() {
  return new Promise((resolve, reject) => {
    let buffer = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      buffer += chunk;
    });
    process.stdin.on('end', () => resolve(buffer));
    process.stdin.on('error', reject);
  });
}

async function main() {
  const raw = await readStdin();
  const params = raw.trim() ? JSON.parse(raw) : {};

  if (!params.report_type) throw new Error('report_type은 필수입니다.');
  if (!params.start_date || !params.end_date) {
    throw new Error('start_date/end_date는 필수입니다 (YYYYMMDD).');
  }

  const entries = await collectEntries({
    reportType: params.report_type,
    startDate: params.start_date,
    endDate: params.end_date,
    maxTotal: params.max_total ?? null,
    includeAttachments: params.include_attachments ?? true,
    onEntry: (info) => {
      process.stderr.write(
        `[수집] ${info.disclosure.corp_name} ${info.disclosure.report_nm} → ${info.entryCount}건\n`
      );
    },
  });

  process.stdout.write(JSON.stringify(entries));
}

main().catch((err) => {
  process.stderr.write(`수집 실패: ${err.message}\n`);
  process.exit(1);
});
