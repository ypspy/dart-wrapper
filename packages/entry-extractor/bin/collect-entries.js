#!/usr/bin/env node
// Python Admin 수집기가 호출하는 CLI 브릿지.
// stdin으로 JSON 파라미터를 받고, stdout에는 결과 JSON만 출력한다.
// 진행 로그는 stdout을 오염시키지 않도록 stderr로 보낸다.
//
// mode 별 계약:
//   list    → { listed_count, items }   기간(보통 하루) 목록과 원천 총건수
//   extract → Entry[]                   공시 1건의 leaf 엔트리
//   collect → Entry[]                   기간 전체 일괄 수집(기존 동작)
const {
  collectEntries,
  fetchDisclosureListResult,
  buildEntriesFromDisclosure,
} = require('../src');

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

function requireRange(params) {
  if (!params.report_type) throw new Error('report_type은 필수입니다.');
  if (!params.start_date || !params.end_date) {
    throw new Error('start_date/end_date는 필수입니다 (YYYYMMDD).');
  }
}

async function runList(params) {
  requireRange(params);

  const { listedCount, disclosures, error } = await fetchDisclosureListResult({
    reportType: params.report_type,
    startDate: params.start_date,
    endDate: params.end_date,
    maxTotal: params.max_total ?? null,
    onProgress: (info) => {
      if (info.type === 'total') {
        process.stderr.write(`[목록] ${params.start_date} 총 ${info.totalCount}건\n`);
      }
    },
  });

  // 목록을 온전히 못 가져오면 완전성 판정이 어긋나므로 실패로 알린다.
  if (error) throw new Error(`목록 수집 실패: ${error.message}`);

  process.stdout.write(JSON.stringify({ listed_count: listedCount, items: disclosures }));
}

async function runExtract(params) {
  const disclosure = params.disclosure;
  if (!disclosure || !disclosure.url) {
    throw new Error('disclosure.url은 필수입니다.');
  }

  const entries = await buildEntriesFromDisclosure(disclosure, {
    includeAttachments: params.include_attachments ?? true,
  });

  process.stderr.write(
    `[상세] ${disclosure.corp_name || disclosure.rcept_no} → ${entries.length}건\n`
  );
  process.stdout.write(JSON.stringify(entries));
}

async function runCollect(params) {
  requireRange(params);

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

async function main() {
  const raw = await readStdin();
  const params = raw.trim() ? JSON.parse(raw) : {};
  const mode = params.mode || 'collect';

  if (mode === 'list') return runList(params);
  if (mode === 'extract') return runExtract(params);
  if (mode === 'collect') return runCollect(params);

  throw new Error(`알 수 없는 mode입니다: ${mode}`);
}

main().catch((err) => {
  process.stderr.write(`수집 실패: ${err.message}\n`);
  process.exit(1);
});
