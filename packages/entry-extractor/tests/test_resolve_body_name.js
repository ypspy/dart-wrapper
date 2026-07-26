const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { resolveBodyName } = require('../src/documents');
const { buildEntries } = require('../src/entries');

function section(name, depth = 1) {
  return { name, originalName: name, depth, normalized: false };
}

describe('resolveBodyName 본문 문서명', () => {
  it('report_nm과 같은 TOC 노드를 문서명으로 고른다', () => {
    const naming = resolveBodyName(
      [
        section('정정신고(보고)'),
        section('【 대표이사 등의 확인 】'),
        section('사업보고서'),
        section('1. 회사의 개요', 2),
      ],
      { report_nm: '사업보고서' }
    );
    assert.equal(naming.name, '사업보고서');
    assert.equal(naming.corrected, false);
  });

  it('대표이사 확인만 있으면 report_nm으로 보정한다', () => {
    const naming = resolveBodyName(
      [section('정정신고(보고)'), section('【 대표이사 등의 확인 】')],
      { report_nm: '사업보고서' }
    );
    assert.equal(naming.name, '사업보고서');
    assert.equal(naming.corrected, true);
  });

  it('report_nm이 있으면 TOC 일치 없을 때도 report_nm을 쓴다', () => {
    const naming = resolveBodyName(
      [
        section('정정신고(보고)'),
        section('【 대표이사 등의 확인 】'),
        section('I. 회사의 개요'),
      ],
      { report_nm: '사업보고서' }
    );
    assert.equal(naming.name, '사업보고서');
    assert.equal(naming.corrected, true);
  });

  it('report_nm이 없으면 대표이사 확인을 건너뛴다', () => {
    const naming = resolveBodyName([
      section('정정신고(보고)'),
      section('【 대표이사 등의 확인 】'),
      section('I. 회사의 개요'),
    ]);
    assert.equal(naming.name, 'I. 회사의 개요');
  });
});

describe('buildEntries body document_name', () => {
  it('본문 leaf document_name이 report_nm(사업보고서)을 따른다', () => {
    const disclosure = {
      reportType: 'A001',
      rcept_no: '20260601001725',
      report_nm: '사업보고서',
      url: 'https://example.com/main',
    };
    const tree = [
      {
        name: '정정신고(보고)',
        originalName: '정정신고(보고)',
        depth: 1,
        dcmNo: '1',
        eleId: '1',
        parentEleId: null,
        url: 'https://example.com/1',
        children: [],
      },
      {
        name: '【 대표이사 등의 확인 】',
        originalName: '【 대표이사 등의 확인 】',
        depth: 1,
        dcmNo: '1',
        eleId: '2',
        parentEleId: null,
        url: 'https://example.com/2',
        children: [],
      },
      {
        name: '사업보고서',
        originalName: '사업보고서',
        depth: 1,
        dcmNo: '1',
        eleId: '3',
        parentEleId: null,
        url: 'https://example.com/3',
        children: [],
      },
      {
        name: 'I. 회사의 개요',
        originalName: 'I. 회사의 개요',
        depth: 1,
        dcmNo: '1',
        eleId: '5',
        parentEleId: null,
        url: 'https://example.com/5',
        children: [
          {
            name: '1. 회사의 개요',
            originalName: '1. 회사의 개요',
            depth: 2,
            dcmNo: '1',
            eleId: '6',
            parentEleId: '5',
            url: 'https://example.com/6',
            children: [],
          },
        ],
      },
    ];
    const documents = [
      {
        source: 'body',
        dcmNo: '1',
        name: resolveBodyName(
          [
            section('정정신고(보고)'),
            section('【 대표이사 등의 확인 】'),
            section('사업보고서'),
            section('I. 회사의 개요'),
            section('1. 회사의 개요', 2),
          ],
          disclosure
        ).name,
      },
    ];
    const entries = buildEntries(disclosure, { tree, documents }, { includeAttachments: false });
    assert.ok(entries.length > 0);
    assert.ok(entries.every((e) => e.document_name === '사업보고서'));
  });
});
