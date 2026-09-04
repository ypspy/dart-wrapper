"""외부감사 실시내용 3절 실시내용 추출 테스트."""

from app.extracting.activity_items import extract_activities

_HTML = """
<html><body>
<table>
<tr><td>구분</td><td>담당이사</td></tr>
<tr><td>투입 인원수</td><td>1</td></tr>
</table>
<p>3. 주요 감사실시내용</p>
<table>
<tr>
  <td>구분</td>
  <td colspan="8">내역</td>
</tr>
<tr>
  <td>전반감사계획</td>
  <td>수행시기</td>
  <td>2024.05</td>
  <td>주요내용</td>
  <td colspan="5">감사계획 수립</td>
</tr>
<tr>
  <td rowspan="4">현장감사</td>
  <td colspan="2" rowspan="2">수행시기</td>
  <td colspan="2">투입인원</td>
  <td rowspan="2">주요 감사업무 수행내용</td>
</tr>
<tr>
  <td>상주</td>
  <td>비상주</td>
</tr>
<tr>
  <td>24.06.17~24.07.14</td>
  <td>27일</td>
  <td>20명</td>
  <td>5명</td>
  <td>내부회계관리제도감사 : 설계평가</td>
</tr>
<tr>
  <td>-</td>
  <td>-</td>
  <td>-</td>
  <td>-</td>
  <td>-</td>
</tr>
<tr>
  <td rowspan="3">재고자산실사(입회)</td>
  <td>실사(입회)시기</td>
  <td>2025.01.02</td>
  <td>1일</td>
</tr>
<tr>
  <td>실사(입회)장소</td>
  <td colspan="7">보은사업장, 부산사업장, 인천사업장 등</td>
</tr>
<tr>
  <td>실사(입회)대상</td>
  <td colspan="7">원재료, 재공품, 반제품, 제품, 상품, 저장품 등</td>
</tr>
<tr>
  <td rowspan="3">금융자산실사(입회)</td>
  <td>실사(입회)시기</td>
  <td>-</td>
</tr>
<tr>
  <td>실사(입회)장소</td>
  <td colspan="7">-</td>
</tr>
<tr>
  <td>실사(입회)대상</td>
  <td colspan="7">-</td>
</tr>
<tr>
  <td>외부조회</td>
  <td>금융거래조회</td>
  <td>O</td>
  <td>채권채무조회</td>
  <td>X</td>
  <td>변호사조회</td>
  <td>-</td>
  <td>기타조회</td>
  <td>-</td>
</tr>
<tr>
  <td>지배기구와의 커뮤니케이션</td>
  <td>커뮤니케이션 횟수</td>
  <td>3</td>
  <td>수행내용</td>
  <td colspan="5">핵심감사사항 선정</td>
</tr>
<tr>
  <td>외부전문가 활용</td>
  <td>감사 활용 내용</td>
  <td colspan="7">전산감사 전문가</td>
</tr>
</table>
<p>4. 감사(감사위원회)와의 커뮤니케이션</p>
<table>
<tr><th>구분</th><th>일자</th><th>참석자</th><th>방식</th><th>주요 논의 내용</th></tr>
<tr><td>1</td><td>2024.05.14</td><td>감사위원회 위원 3명</td><td>대면회의</td><td>핵심감사사항 선정</td></tr>
</table>
<p>5. 감사인의 중요성 금액</p>
<table>
<tr><td>재무제표 전체 중요성</td><td>10억원</td></tr>
</table>
</body></html>
"""

_TWO_INVENTORY = """
<html><body>
<p>3. 주요 감사실시내용</p>
<table>
<tr><td>구분</td><td colspan="3">내역</td></tr>
<tr>
  <td rowspan="6">재고자산실사(입회)</td>
  <td>실사(입회)시기</td>
  <td>2025.01.02</td>
  <td>1일</td>
</tr>
<tr>
  <td>실사(입회)장소</td>
  <td colspan="2">보은사업장</td>
</tr>
<tr>
  <td>실사(입회)대상</td>
  <td colspan="2">제품</td>
</tr>
<tr>
  <td>실사(입회)시기</td>
  <td>2025.01.03</td>
  <td>1일</td>
</tr>
<tr>
  <td>실사(입회)장소</td>
  <td colspan="2">서울본사</td>
</tr>
<tr>
  <td>실사(입회)대상</td>
  <td colspan="2">-</td>
</tr>
</table>
</body></html>
"""


_SPLIT_HEADCOUNT = """
<html><body>
<p>3. 주요 감사실시내용</p>
<table>
<tr><td>구분</td><td colspan="8">내역</td></tr>
<tr>
  <td rowspan="3">현장감사</td>
  <td colspan="3" rowspan="2">수행시기</td>
  <td colspan="4">투입인원</td>
  <td rowspan="2">주요 감사업무 수행내용</td>
</tr>
<tr>
  <td colspan="2">상주</td>
  <td colspan="2">비상주</td>
</tr>
<tr>
  <td>2024.09.25~27</td>
  <td>3</td>
  <td>일</td>
  <td>5</td>
  <td>명</td>
  <td>2</td>
  <td>명</td>
  <td>내부통제제도검토</td>
</tr>
</table>
</body></html>
"""


_BLANK_FORM_UNITS = """
<html><body>
<p>3. 주요 감사실시내용</p>
<table>
<tr><td>구분</td><td colspan="8">내역</td></tr>
<tr>
  <td rowspan="4">현장감사</td>
  <td colspan="3" rowspan="2">수행시기</td>
  <td colspan="4">투입인원</td>
  <td rowspan="2">주요 감사업무 수행내용</td>
</tr>
<tr>
  <td colspan="2">상주</td>
  <td colspan="2">비상주</td>
</tr>
<tr>
  <td>2018.12.19~20</td>
  <td>2</td>
  <td>일</td>
  <td>1</td>
  <td>명</td>
  <td>1</td>
  <td>명</td>
  <td>자산의 회수가능성</td>
</tr>
<tr>
  <td>-</td>
  <td>-</td>
  <td>일</td>
  <td>-</td>
  <td>명</td>
  <td>-</td>
  <td>명</td>
  <td>-</td>
</tr>
</table>
</body></html>
"""


_BLOCK_COLSPAN = """
<html><body>
<p>3. 주요 감사실시내용</p>
<table>
<tr><td>구분</td><td colspan="12">내역</td></tr>
<tr>
  <td>전반감사계획 (감사착수단계)</td>
  <td>수행시기</td>
  <td colspan="4">2024.06.29</td>
  <td>1</td>
  <td>일</td>
  <td>일</td>
  <td>주요내용</td>
  <td colspan="3">감사계획 수립</td>
</tr>
<tr>
  <td>외부조회</td>
  <td>금융거래조회</td>
  <td colspan="2">O</td>
  <td>채권채무조회</td>
  <td>O</td>
  <td>변호사조회</td>
  <td>-</td>
  <td>기타조회</td>
  <td colspan="4">-</td>
</tr>
<tr>
  <td>지배기구와의 커뮤니케이션</td>
  <td>커뮤니케이션 횟수</td>
  <td colspan="2">2</td>
  <td>회</td>
  <td>회</td>
  <td>수행시기</td>
  <td colspan="5">중간감사 및 기말감사</td>
</tr>
</table>
</body></html>
"""


def _rows(activities: list[dict[str, object]], **filters: object) -> list[dict[str, object]]:
    """필터와 모두 일치하는 실시내용 행을 반환한다."""
    found: list[dict[str, object]] = []
    for row in activities:
        if all(row.get(key) == value for key, value in filters.items()):
            found.append(row)
    return found


def test_extract_activities_fieldwork_headers_and_visit() -> None:
    """현장감사는 헤더 2행과 날짜 회차 1개를 내고, '-' 줄은 회차가 아니다."""
    activities, status = extract_activities(_HTML)
    assert status == "ok"
    assert all(row["row_type"] != "item" for row in activities)

    column_header = _rows(activities, row_type="column_header")[0]
    assert "수행시기" in column_header["labels"]
    assert "투입인원" in column_header["labels"]

    sub_header = _rows(activities, row_type="sub_header")[0]
    assert sub_header["parent_label"] == "투입인원"
    assert "상주" in sub_header["labels"]

    visits = _rows(activities, section="fieldwork", row_type="visit")
    assert len(visits) == 1
    schedule = visits[0]["fields"]["수행시기"]
    assert schedule["start_date"] == "24.06.17"
    assert schedule["end_date"] == "24.07.14"
    assert schedule["days"] == 27
    resident = visits[0]["fields"]["투입인원"]["상주"]
    assert isinstance(resident["count"], int)
    assert "명" in resident["raw"]


def test_extract_activities_joins_split_headcount_number_and_unit() -> None:
    """상주·비상주가 '5'와 '명'으로 나뉜 칸이면 숫자를 잃지 않는다."""
    activities, status = extract_activities(_SPLIT_HEADCOUNT)
    assert status == "ok"
    visit = _rows(activities, section="fieldwork", row_type="visit")[0]
    resident = visit["fields"]["투입인원"]["상주"]
    nonresident = visit["fields"]["투입인원"]["비상주"]
    assert resident["count"] == 5
    assert "5" in resident["raw"]
    assert "명" in resident["raw"]
    assert nonresident["count"] == 2
    assert "2" in nonresident["raw"]
    schedule = visit["fields"]["수행시기"]
    assert schedule["start_date"] == "2024.09.25"
    assert schedule["end_date"] == "2024.09.27"
    assert schedule["days"] == 3


def test_extract_activities_blank_form_row_does_not_overwrite_headcount() -> None:
    """날짜 없는 빈 서식 줄의 일·명 칸은 회차 투입인원을 덮지 않는다."""
    activities, status = extract_activities(_BLANK_FORM_UNITS)
    assert status == "ok"
    visits = _rows(activities, section="fieldwork", row_type="visit")
    assert len(visits) == 1
    head = visits[0]["fields"]["투입인원"]
    assert head["상주"]["count"] == 1
    assert head["비상주"]["count"] == 1


def _unmapped_values(fields: dict[str, object]) -> list[object]:
    """unmapped_N 값만 모은다."""
    return [value for key, value in fields.items() if str(key).startswith("unmapped_")]


def test_extract_activities_block_does_not_repeat_colspan_cells() -> None:
    """블록은 다음 라벨 전까지 칸을 이어 붙이고 colspan 복제는 unmapped로 남기지 않는다."""
    activities, status = extract_activities(_BLOCK_COLSPAN)
    assert status == "ok"
    planning = _rows(activities, section="planning", row_type="block")[0]["fields"]
    schedule = planning["수행시기"]
    assert schedule["raw"] == "2024.06.29 1 일"
    assert schedule["start_date"] == "2024.06.29"
    assert schedule["end_date"] == "2024.06.29"
    assert schedule["days"] == 1
    assert planning["주요내용"] == "감사계획 수립"
    assert _unmapped_values(planning) == []
    confirmations = _rows(activities, section="external_confirmations", row_type="block")[0][
        "fields"
    ]
    assert confirmations["금융거래조회"] == "O"
    assert confirmations["기타조회"] == "-"
    assert _unmapped_values(confirmations) == []
    tcwg = _rows(activities, section="tcwg_communication", row_type="block")[0]["fields"]
    assert tcwg["커뮤니케이션 횟수"] == "2 회"
    assert tcwg["수행시기"] == "중간감사 및 기말감사"
    assert _unmapped_values(tcwg) == []


def test_extract_activities_planning_schedule_splits_range_and_days() -> None:
    """전반감사계획 수행시기는 현장감사와 같이 start·end·days로 나눈다."""
    html = """
    <html><body>
    <p>3. 주요 감사실시내용</p>
    <table>
    <tr><td>구분</td><td colspan="6">내역</td></tr>
    <tr>
      <td>전반감사계획</td>
      <td>수행시기</td>
      <td>2024.07.22~2024.09.06</td>
      <td>3</td>
      <td>일</td>
      <td>주요내용</td>
      <td>감사계획 수립</td>
    </tr>
    </table>
    </body></html>
    """
    activities, status = extract_activities(html)
    assert status == "ok"
    schedule = _rows(activities, section="planning", row_type="block")[0]["fields"]["수행시기"]
    assert schedule["raw"] == "2024.07.22~2024.09.06 3 일"
    assert schedule["start_date"] == "2024.07.22"
    assert schedule["end_date"] == "2024.09.06"
    assert schedule["days"] == 3



def test_extract_activities_inventory_visit_keeps_schedule_place_target() -> None:
    """재고 실사는 회차 1개이고 시기·장소·대상이 items에 있다."""
    activities, _status = extract_activities(_HTML)
    visits = _rows(activities, section="inventory_observation", row_type="visit")
    assert len(visits) == 1
    labels = [item["label"] for item in visits[0]["items"]]
    assert "실사(입회)시기" in labels
    assert "실사(입회)장소" in labels
    assert "실사(입회)대상" in labels
    timing = next(item for item in visits[0]["items"] if item["label"] == "실사(입회)시기")
    assert timing["start_date"] == timing["end_date"]


def test_extract_activities_two_inventory_timings_are_two_visits() -> None:
    """실사(입회)시기 라벨이 두 번이면 재고 visit이 두 개다."""
    activities, status = extract_activities(_TWO_INVENTORY)
    assert status == "ok"
    visits = _rows(activities, section="inventory_observation", row_type="visit")
    assert len(visits) == 2
    assert not any(row["row_type"] == "item" for row in activities)


def test_extract_activities_external_confirmations_keep_ox_raw() -> None:
    """외부조회 O/X/- 원문을 fields에 유지한다."""
    activities, _status = extract_activities(_HTML)
    block = _rows(activities, section="external_confirmations", row_type="block")[0]
    assert block["fields"]["금융거래조회"] == "O"


def test_extract_activities_section_three_tcwg_is_block_not_section_four() -> None:
    """3절 지배기구는 tcwg_communication block이고 4절 표를 읽지 않는다."""
    activities, _status = extract_activities(_HTML)
    tcwg = _rows(activities, section="tcwg_communication")[0]
    assert tcwg["row_type"] == "block"
    assert "2024.05.14" not in str(activities)
    assert any(row["section"] == "expert" for row in activities)


def test_extract_activities_ignores_section_five_materiality() -> None:
    """5절 중요성 금액 표가 있어도 activities에 10억원이 없다."""
    activities, status = extract_activities(_HTML)
    assert status == "ok"
    assert "10억원" not in str(activities)


def test_extract_activities_missing_table_is_not_found() -> None:
    """3절 표가 없으면 not_found와 빈 목록이다."""
    activities, status = extract_activities("<html><body><p>없음</p></body></html>")
    assert status == "not_found"
    assert activities == []


def test_extract_activities_financial_dash_stays_in_items() -> None:
    """금융 실사 값이 '-'여도 해당 회차 items에 남긴다."""
    activities, _status = extract_activities(_HTML)
    visits = _rows(activities, section="financial_asset_observation", row_type="visit")
    assert len(visits) == 1
    assert any(item["raw"] == "-" for item in visits[0]["items"])
