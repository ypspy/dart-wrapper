const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const {
  selectReceptionAttachments,
  resolveReceptionRcpNo,
} = require('../src/documents');

function att(overrides) {
  return {
    source: 'attachment',
    name: '감사보고서',
    reportDate: '',
    correctionType: '',
    rcpNo: '1',
    dcmNo: '1',
    ...overrides,
  };
}

describe('selectReceptionAttachments', () => {
  it('rcpNo가 접수와 같은 첨부만 남긴다', () => {
    const out = selectReceptionAttachments(
      [
        att({ dcmNo: 'same', rcpNo: '20170331001902' }),
        att({ dcmNo: 'other', rcpNo: '20170908000524', reportDate: '2017.09.08' }),
      ],
      '20170331001902'
    );
    assert.equal(out.length, 1);
    assert.equal(out[0].dcmNo, 'same');
  });

  it('같은 날짜·다른 rcpNo면 각자 접수에만 남는다', () => {
    const docs = [
      att({
        dcmNo: 'a',
        rcpNo: '20160330004732',
        reportDate: '2016.03.30',
        name: '감사보고서',
      }),
      att({
        dcmNo: 'b',
        rcpNo: '20160330004731',
        reportDate: '2016.03.30',
        name: '연결감사보고서',
      }),
    ];
    const a = selectReceptionAttachments(docs, '20160330004732');
    const b = selectReceptionAttachments(docs, '20160330004731');
    assert.deepEqual(
      a.map((d) => d.dcmNo),
      ['a']
    );
    assert.deepEqual(
      b.map((d) => d.dcmNo),
      ['b']
    );
  });

  it('SAME 첨부가 없으면 첨부 0건', () => {
    const out = selectReceptionAttachments(
      [att({ dcmNo: 'x', rcpNo: 'OTHER' })],
      '20170405000474'
    );
    assert.equal(out.length, 0);
  });

  it('body 문서는 필터하지 않는다', () => {
    const body = { source: 'body', name: '사업보고서', dcmNo: '9', rcpNo: 'x' };
    const out = selectReceptionAttachments(
      [body, att({ dcmNo: 'a', rcpNo: 'R1' }), att({ dcmNo: 'b', rcpNo: 'R2' })],
      'R1'
    );
    assert.equal(out.filter((d) => d.source === 'body').length, 1);
    assert.equal(out.filter((d) => d.source === 'attachment').length, 1);
    assert.equal(out.find((d) => d.source === 'attachment').dcmNo, 'a');
  });

  it('rceptNo가 비면 첨부는 모두 제외하고 body만 남긴다', () => {
    const body = { source: 'body', name: '사업보고서', rcpNo: 'x' };
    const out = selectReceptionAttachments(
      [body, att({ dcmNo: 'a', rcpNo: 'R1' })],
      ''
    );
    assert.equal(out.length, 1);
    assert.equal(out[0].source, 'body');
  });
});

describe('resolveReceptionRcpNo', () => {
  it('disclosure.rcept_no를 우선한다', () => {
    assert.equal(
      resolveReceptionRcpNo({ rcept_no: '111' }, 'https://x/main.do?rcpNo=222'),
      '111'
    );
  });

  it('없으면 URL rcpNo를 쓴다', () => {
    assert.equal(
      resolveReceptionRcpNo(
        null,
        'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20170331001902'
      ),
      '20170331001902'
    );
  });

  it('둘 다 없으면 빈 문자열', () => {
    assert.equal(resolveReceptionRcpNo(null, 'https://example.test/'), '');
  });
});
