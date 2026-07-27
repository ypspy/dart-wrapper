const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { selectFinalAttachments } = require('../src/documents');

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

describe('selectFinalAttachments', () => {
  it('같은 이름이면 더 늦은 reportDate만 남긴다', () => {
    const out = selectFinalAttachments([
      att({ dcmNo: 'a', reportDate: '2026.03.16', rcpNo: 'old' }),
      att({
        dcmNo: 'b',
        reportDate: '2026.03.25',
        rcpNo: 'new',
        correctionType: '정정',
      }),
    ]);
    assert.equal(out.length, 1);
    assert.equal(out[0].dcmNo, 'b');
  });

  it('날짜가 같으면 correctionType 있는 쪽을 고른다', () => {
    const out = selectFinalAttachments([
      att({ dcmNo: 'a', reportDate: '2026.03.25' }),
      att({ dcmNo: 'b', reportDate: '2026.03.25', correctionType: '기재정정' }),
    ]);
    assert.equal(out[0].dcmNo, 'b');
  });

  it('이름이 다르면 둘 다 유지한다', () => {
    const out = selectFinalAttachments([
      att({ name: '감사보고서', dcmNo: '1', reportDate: '2026.03.25' }),
      att({ name: '정관', dcmNo: '2', reportDate: '2026.03.16' }),
    ]);
    assert.equal(out.length, 2);
  });

  it('body 문서는 필터하지 않는다', () => {
    const body = { source: 'body', name: '사업보고서', dcmNo: '9', rcpNo: 'x' };
    const out = selectFinalAttachments([
      body,
      att({ dcmNo: 'a', reportDate: '2026.03.16' }),
      att({ dcmNo: 'b', reportDate: '2026.03.25' }),
    ]);
    assert.equal(out.filter((d) => d.source === 'body').length, 1);
    assert.equal(out.filter((d) => d.source === 'attachment').length, 1);
    assert.equal(out.find((d) => d.source === 'attachment').dcmNo, 'b');
  });

  it('전원 무날짜면 DOM 순 첫 건을 유지한다', () => {
    const out = selectFinalAttachments([
      att({ dcmNo: 'first' }),
      att({ dcmNo: 'second' }),
    ]);
    assert.equal(out[0].dcmNo, 'first');
  });
});
