const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const {
  applyAttachmentOptionNames,
  attachmentOptionDisplayName,
  parseDetail,
} = require('../src/documents');
const { buildEntries, isAttachmentCorrectionFiling } = require('../src/entries');
const {
  treeDataHtml,
  attachmentSelectHtml,
  mergeHtml,
} = require('./fixtures/html');

describe('attachmentOptionDisplayName', () => {
  it('[정정] 접두를 붙인다', () => {
    assert.equal(
      attachmentOptionDisplayName({
        name: '연결감사보고서',
        correctionType: '정정',
      }),
      '[정정] 연결감사보고서'
    );
  });

  it('correctionType 없으면 name만', () => {
    assert.equal(
      attachmentOptionDisplayName({ name: '정관', correctionType: '' }),
      '정관'
    );
  });
});

describe('applyAttachmentOptionNames', () => {
  it('같은 dcmNo 본문 이름을 #att option명으로 덮어쓴다', () => {
    const docs = applyAttachmentOptionNames([
      {
        source: 'body',
        name: '사업보고서',
        dcmNo: '5032112',
        rcpNo: '20160330004731',
      },
      {
        source: 'attachment',
        name: '연결감사보고서',
        correctionType: '정정',
        dcmNo: '5032112',
        rcpNo: '20160330004731',
        originalName: '연결감사보고서',
      },
    ]);
    const body = docs.find((d) => d.source === 'body');
    assert.equal(body.name, '[정정] 연결감사보고서');
    assert.equal(body.correctionType, '정정');
  });
});

describe('isAttachmentCorrectionFiling', () => {
  it('correction_type 첨부정정을 인식한다', () => {
    assert.equal(
      isAttachmentCorrectionFiling({ correction_type: '첨부정정' }),
      true
    );
  });

  it('최초공시는 false', () => {
    assert.equal(
      isAttachmentCorrectionFiling({ correction_type: '최초공시' }),
      false
    );
  });
});

describe('첨부정정 document_name', () => {
  it('tree와 #att가 같은 dcmNo면 option명을 쓰고 source=attachment', async () => {
    const html = mergeHtml(
      treeDataHtml({
        rcpNo: '20160330004731',
        dcmNo: '5032112',
        nodes: [
          { depth: 1, text: '정 정 신 고 (보 고)', eleId: '1' },
          { depth: 2, text: '연 결 재 무 제 표', eleId: '2' },
        ],
      }),
      attachmentSelectHtml({
        rcpNo: '20160330004731',
        dcmNo: '5032112',
        name: '2016.03.30 [정정] 연결감사보고서',
      })
    );

    const disclosure = {
      rcept_no: '20160330004731',
      report_nm: '사업보고서',
      correction_type: '첨부정정',
      url: 'https://example.test/main.do?rcpNo=20160330004731',
    };

    const detail = await parseDetail(disclosure.url, {
      disclosure,
      fetcher: async () => html,
    });
    const bodyDoc = detail.documents.find((d) => d.source === 'body');
    assert.ok(bodyDoc);
    assert.equal(bodyDoc.name, '[정정] 연결감사보고서');

    const entries = buildEntries(disclosure, detail, {
      includeAttachments: true,
    });
    assert.ok(entries.length >= 1);
    assert.ok(entries.every((e) => e.source === 'attachment'));
    assert.ok(
      entries.every((e) => e.document_name === '[정정] 연결감사보고서')
    );
  });
});
