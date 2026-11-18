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

`interim_review_facts`는 앱을 켤 때 만들지 않습니다. 테이블은 아래 스크립트로만 만듭니다. 기본은 dry-run이고, `--write`는 백업을 확인하는 `--confirm-backup`이 있을 때만 이미 있는 데이터베이스 파일에 테이블 하나와 인덱스를 추가합니다. `research.models`를 불러 `create_all`을 하면 이 테이블이 ORM DDL로 생길 수 있으므로, 운영 데이터베이스에는 이 스크립트만 쓰세요. 실제 데이터베이스에 실행하는 것은 별도 승인 뒤입니다.

```bash
cd packages/research
PYTHONPATH=.:../web-api python scripts/create_interim_review_table.py --target-db <기존-sqlite-경로>
PYTHONPATH=.:../web-api python scripts/create_interim_review_table.py --target-db <기존-sqlite-경로> --write --confirm-backup
```

실행은 `POST /admin/extract/interim-review` 입니다. 기간은 `YYYYMMDD`이고, `report_types`는 A002·A003(기본 둘 다), `mode`는 `extract` 또는 `resume`입니다. 상태·중단·강제 종료는 기존 추출 잡 경로를 `job_id`로 그대로 씁니다. 실제 추출과 뷰어 다운로드는 승인 뒤에만 합니다. 이 저장소의 테스트는 합성 HTML만 사용합니다.

## 단일 기간 감사시간 표

옛 서식은 당기/전기 열 없이 역할 열만 있다. 추출기(`activity_hours`)는 그 칸의 `period`를 `unknown`으로 두고 `period_raw`를 비운 채 저장한다. 저장된 period는 unknown 그대로다. unknown을 무조건 당기로 보지 않는다.

신호(`reviewing.candidates._hour_cells`)와 골드 채점(`gold.scoring._hours_keys`)만 `research.extracting.hours_period`의 가드를 통과한 표에서 합계(`role=total`)를 당기 합계처럼 읽는다. 가드는 다음 여덟 조건을 모두 만족할 때만 참이다. 가드가 거짓이면 master와 같다.

1. 당기/전기 표시가 없다. 모든 칸의 period가 unknown이고 period_raw가 비어 있다.
2. 기간이 섞여 있지 않다. current 또는 prior 칸이 없다.
3. 역할당 열이 하나다. `(role, role_raw, metric)`이 한 번씩만 나온다. colspan으로 같은 키가 두 번이면 해당하지 않는다.
4. 역할을 모르는 열이 없다. `role="other"`인 칸이 하나라도 있으면 거짓이다. `metric="other"`인 행 하나는 합계 칸 선택에 영향이 없어 조건 4에 넣지 않는다. 같은 역할에서 모르는 지표 행이 둘 이상이면 키가 겹쳐 조건 3으로 거짓이다.
5. 합계 열이 하나다. `role="total"`인 칸의 `role_raw`가 2종류 이상이면 거짓이다.
6. 키 값이 문자열이다. `role`·`role_raw`·`metric`·`period`·`period_raw` 중 하나라도 문자열도 None도 아니면 거짓이다. `0`·`False`·`[]`는 빈 값으로 보지 않는다.
7. 역할 원문·행 라벨·칸 원문에 기수가 없다. 공백과 폭 없는 문자를 지운 뒤 `(제|第)?숫자(기|期)`가 하나라도 있으면 거짓이다. 기수가 한 종류여도 거절한다.
8. 행 라벨에 당기/전기가 없다. `metric_raw`에서 공백과 폭 없는 문자를 지운 뒤 당기 또는 전기가 있으면 거짓이다.

가드가 거짓이면 종전처럼 period가 current인 합계만 본다. 저장소 밖 분석도 이 규칙을 따라야 하고, 저장된 period를 current로 고쳐 쓰지 않는다.

### 한계

1. colspan으로 역할당 열이 2개인 무라벨 표는 가드가 거짓이다. 당기 합계 칸이 없으므로 신호는 `hours_total_missing`이다. 두 열 중 어느 쪽이 당기인지 코드 안에 근거가 없어, 사람 검토로 보내는 것이 의도다. 두 열 값이 달라도, 같아도 신호는 missing이다.
2. 단일 기간(unknown) 표에서 `role_raw`가 다른 합계 열 2개는 가드가 거짓이고 신호는 `hours_total_missing`이며 골드 키는 `(None, None)`이다. 어느 열이 당기인지 근거가 없다. 두 열이 모두 current이면 조건 1로 거짓이고 종전대로 `hours_total_duplicate`(skip)이다.
3. 역할을 모르는 열(`role="other"`)이 있으면 개수와 상관없이 가드가 거짓이고 신호는 `hours_total_missing`이다.
4. 구조로 구분할 수 없는 남은 경우는 새 서식인데 당기/전기 표시를 하나도 읽지 못했고, 역할 헤더는 열마다 하나씩 읽힌 표다. 이 표는 옛 서식과 칸 구조가 같아서 가드가 참이다. 헤더가 아예 없는 6값 열은 키가 겹쳐 가드가 거짓이고 missing이다. 연도 조건은 넣지 않았다. 서식 변경 시점(2016년 7–8월경)이 딱 떨어지지 않고, 구조상 단일 기간인 새 fact 2건이 2017-04 접수다(원문 대조 전). 컷을 넣으면 그런 문서를 잘라낼 수 있다. 원문 대조 249/249는 모두 단일 기간이었다. 「전기」가 역할 열의 헤더나 값 칸에 있으면 period가 prior가 되어 가드가 거짓이다. 라벨 열(모서리)에만 있으면 추출기가 그 열을 건너뛰어 칸에 남지 않고, 가드가 참이다(한계 7). 「제47기」처럼 기수만 있는 표는 여기에 해당하지 않는다(한계 5).
5. 기수가 역할 헤더 아래 소제목 행에만 있고 역할마다 열이 하나인 표는 칸에 기수가 남지 않는다. 추출기 `_match_role`이 첫 역할 토큰의 원문만 `role_raw`로 남기고, `_match_period`는 당기/전기만 읽기 때문이다. 그래서 이런 표는 가드가 참이고 합계가 당기로 쓰인다. 소제목 기수가 열마다 달라도(제48기/제47기/제48기) 같은 메커니즘으로 가드가 참이다. 실측: 골드 원문 캐시의 옛 서식 249건 중 헤더 행에 제N기가 있는 표는 0건이다(2026-11-17 8:16 PM CT). 고치려면 추출기를 바꾸고 재추출해야 해서 별도 결정이 필요하다. 최소 지점은 `activity_hours._match_period`이다. 당기/전기가 없을 때 헤더에 제N기가 있으면 `("unknown", 원문)`을 돌려주면 조건 1이 거절한다. 이렇게 바꿔도 기존 782 테스트는 통과했다(Zucchini 시험, 커밋 안 함, 2026-11-17). `EXTRACTOR_VERSION`을 올릴지는 함께 결정한다. 후속 후보는 헤더의 '제N기' 등으로 기간을 판별할 수 있는지 조사하는 것이다. 원문 헤더 조사가 먼저이고, 네트워크와 live DB가 필요한 별도 결정이다.
6. 역할 원문·행 라벨·칸 원문에 `(제|第)?숫자(기|期)`가 있으면(「(47기)」, 「第47期」 포함) 개수와 상관없이 가드가 거짓이고 missing이다. 공백과 폭 없는 문자는 비교 전에 지운다.
7. 기간 단어(「전기」「당기」)가 라벨 열(모서리)에만 있으면 칸이 정상 옛 서식과 똑같아 가드가 참이고 합계가 당기로 쓰인다. 박스 실측: 골드 원문 캐시 443건 중 모서리에 당기/전기가 있는 표 0건(2026-11-18, review-r5-response.md). 고치려면 추출기가 라벨 열의 기간 단어를 `period_raw`로 남겨야 해서 한계 5와 같이 별도 결정이다.
8. 투입인원수 표가 여러 개면 추출기는 첫 표만 반환하고, 표 밖 캡션의 기간 표시는 칸에 없다. 첫 표가 단일 기간 구조면 가드가 참이다. 한계 4의 한 형태이고 추출기 동작이다.

live 실측(읽기 전용): 조건 4·5·6으로 head-true에서 거짓이 되는 문서는 0건(2026-11-17 7:37 PM CT, 카탈로그 57,898·골드 446). 조건 7과 기간 값 타입 확장도 0건(8:16·8:23 PM CT, 카탈로그 58,324·58,411, 골드 446). r5 확장 조건: 골드 스냅샷 446건에서 판정 변화 0건, 넓은 기수·행 라벨 당기/전기 0건(박스 사본, 2026-11-18). live 카탈로그의 `metric_raw`·`raw`는 재지 않았다.

2026-11-17 2:1x PM CT 재확인 기준, 두 배 열 표는 그룹2 중 5행과 큐 생성 뒤 새 fact 4건이다. 그 뒤 C2 추출로 늘었을 수 있다. live 재측정은 별도다.

검토 큐 재생성과 골드 재채점은 이 규칙만으로 실행하지 않는다. 승인 뒤에만 한다.
