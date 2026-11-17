# 연구 패키지

감사보고서 추출(`audit_opinion.v19`)과 반기·분기 검토보고서 추출(`interim_review.v1`)이 있습니다. 기본 수집·열람 앱은 이 패키지를 실행하지 않습니다.

## 반기·분기 검토보고서 (`interim_review.v1`)

대상은 공시 유형 A002·A003의 첨부입니다. 문서명에서 공백을 없애고 앞의 `[정정]`을 뺀 뒤 아래만 고릅니다.

| 문서명 | doc_kind |
| --- | --- |
| 반기·분기 (연결) 검토보고서 | review |
| 반기·분기 (연결) 감사보고서 | audit |
| 외국법인등의 (반기\|분기) (연결) 검토ㆍ감사보고서 | foreign_mixed |

본문, `기타공시첨부서류`, 문서명에 `사유서`가 있는 것, `내부회계`·`내부감시장치`가 있는 것은 제외합니다. `review_kind`는 문서명의 반기(`half`)·분기(`quarter`)이고, `fs_scope`는 문서명에 `연결`이 있으면 `consolidated`, 없으면 `separate`입니다.

| 필드 | 내용 |
| --- | --- |
| reviewer_raw / reviewer_resolved / reviewer_status | 서명부 회계법인·감사반 |
| conclusion_raw / conclusion_code / conclusion_status | unmodified, qualified, adverse, disclaimer, unknown |
| review_report_date_* | 서명부 날짜. 여러 개면 서명부에 가장 가까운 날짜, 나머지는 candidates |
| review_period_* | 첫 단락의 부터~까지, 또는 `현재` 기준일과 개월 수 |
| gaap_code / gaap_status | 기존 GAAP 규칙 |
| emphasis_of_matter / going_concern / emphasis_raw / emphasis_status | 강조사항·계속기업 문단 유무와 원문 앞 300자 |
| fetch_status | ok, fetch_failed, blocked, section_missing |

`interim_review_facts`는 앱을 켤 때 만들지 않습니다. 테이블은 아래 스크립트로만 만듭니다. 기본은 dry-run이고, `--write`는 이미 있는 데이터베이스 파일에만 테이블 하나와 인덱스를 추가합니다. 실제 데이터베이스에 실행하는 것은 별도 승인 뒤입니다.

```bash
cd packages/research
PYTHONPATH=.:../web-api python scripts/create_interim_review_table.py --target-db <기존-sqlite-경로>
PYTHONPATH=.:../web-api python scripts/create_interim_review_table.py --target-db <기존-sqlite-경로> --write
```

실행은 `POST /admin/extract/interim-review` 입니다. 기간은 `YYYYMMDD`이고, `report_types`는 A002·A003(기본 둘 다), `mode`는 `extract` 또는 `resume`입니다. 상태·중단·강제 종료는 기존 추출 잡 경로를 `job_id`로 그대로 씁니다. 실제 추출과 뷰어 다운로드는 승인 뒤에만 합니다. 이 저장소의 테스트는 합성 HTML만 사용합니다.
