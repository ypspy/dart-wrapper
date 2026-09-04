"""첨부 제표 계정 추출 테스트."""

from app.extracting.accounts import cut_notes, extract_accounts
from app.extracting.text import compact


_FIVE_COL_BS = """
<html><body>
<p>재무상태표</p>
<p>회사명 : 예 (단위 : 원)</p>
<table>
<tr>
  <td>과 목</td><td>제 3(당) 기</td><td>제 3(당) 기</td>
  <td>제 2(전) 기</td><td>제 2(전) 기</td>
</tr>
<tr><td>Ⅰ. 유동자산</td><td></td><td>665,809,879</td><td></td><td>622,084,856</td></tr>
<tr><td>1. 현금및현금성자산(주석 3)</td><td>173,181,742</td><td></td><td>198,404,558</td><td></td></tr>
<tr><td>자 산 총 계</td><td></td><td>30,665,809,879</td><td></td><td>30,322,084,856</td></tr>
<tr><td>Ⅰ. 유동부채</td><td></td><td>12,345,678</td><td></td><td>11,111,111</td></tr>
<tr><td>부 채 총 계</td><td></td><td>20,000,000</td><td></td><td>19,000,000</td></tr>
<tr><td>Ⅰ. 자본금</td><td></td><td>100</td><td></td><td>100</td></tr>
<tr><td>자 본 총 계</td><td></td><td>100</td><td></td><td>100</td></tr>
<tr><td>부채와자본총계</td><td></td><td>30,665,809,879</td><td></td><td>30,322,084,856</td></tr>
</table>
</body></html>
"""

_SIX_COL = """
<html><body>
<p>재무상태표</p>
<p>(단위: 천원)</p>
<table>
<tr>
  <td>과 목</td><td>주석</td>
  <td>제 9 (당)기</td><td>제 9 (당)기</td>
  <td>제 8 (전)기</td><td>제 8 (전)기</td>
</tr>
<tr><td>매출채권및기타채권</td><td>4,6</td><td>123,367</td><td></td><td>44,901</td><td></td></tr>
<tr><td>재고자산</td><td>7</td><td>27,435</td><td></td><td>46,508</td><td></td></tr>
<tr><td>자 산 총 계</td><td></td><td></td><td>825,062</td><td></td><td>685,537</td></tr>
<tr><td>자 본 총 계</td><td></td><td></td><td>316,553</td><td></td><td>265,039</td></tr>
</table>
<p>포괄손익계산서</p>
<table>
<tr>
  <td>과 목</td><td>주석</td>
  <td>제 9 (당)기</td><td>제 9 (당)기</td>
  <td>제 8 (전)기</td><td>제 8 (전)기</td>
</tr>
<tr><td>XI.당기순이익</td><td></td><td></td><td>22,755</td><td></td><td>12,095</td></tr>
<tr><td>XV. 당기총포괄이익</td><td></td><td></td><td>11,226</td><td></td><td>4,010</td></tr>
</table>
</body></html>
"""

_FOUR_COL = """
<html><body>
<p>재무상태표</p>
<p>(단위 : 원)</p>
<table>
<tr><td>과 목</td><td>주 석</td><td>제 8(당) 기말</td><td>제 7(전) 기말</td></tr>
<tr><td>매출채권</td><td>3,5</td><td>21,738,646,030</td><td>19,325,663,336</td></tr>
<tr><td>재고자산</td><td>8</td><td>13,054,289,195</td><td>12,002,449,673</td></tr>
<tr><td>자 산 총 계</td><td></td><td>93,277,152,562</td><td>91,337,960,197</td></tr>
<tr><td>자 본 총 계</td><td></td><td>67,463,232,976</td><td>63,561,665,542</td></tr>
<tr><td>계약자산</td><td>9</td><td>-</td><td>15,621,952</td></tr>
</table>
</body></html>
"""

_EQUITY_CHANGE = """
<html><body>
<table>
<tr><td>과 목</td><td>자본금</td><td>이익잉여금</td><td>총 계</td></tr>
<tr><td>당기순이익</td><td>-</td><td>12,095</td><td>12,095</td></tr>
</table>
</body></html>
"""


def _by_account_period(rows: list[dict], account: str, period: str) -> dict:
    return next(r for r in rows if r["account"] == account and r["period"] == period)


_JEN_GI_BS = """
<html><body>
<p>재무상태표</p>
<p>(단위: 원)</p>
<table>
<tr><td>과 목</td><td>주석</td><td>제49기 기말</td><td>제48기 기말</td></tr>
<tr><td>자 산 총 계</td><td></td><td>1,179,628,362,898</td><td>1,084,097,944,847</td></tr>
<tr><td>자 본 총 계</td><td></td><td>910,667,791,486</td><td>854,085,976,617</td></tr>
</table>
<p>연결포괄손익계산서</p>
<table>
<tr><td>과 목</td><td>주석</td><td>제49기</td><td>제48기</td></tr>
<tr><td>당기순이익</td><td></td><td>166,912,885,242</td><td>170,246,170,594</td></tr>
<tr><td>당기총포괄이익</td><td></td><td>1</td><td>2</td></tr>
</table>
</body></html>
"""

_SAME_GI = """
<html><body>
<p>재무상태표</p>
<table>
<tr><td>과 목</td><td>제49기</td><td>제49기</td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
</table>
</body></html>
"""

_NO_GI_TWO_AMOUNTS = """
<html><body>
<p>재무상태표</p>
<table>
<tr><td>과 목</td><td>비고A</td><td>비고B</td></tr>
<tr><td>자 산 총 계</td><td>100</td><td>200</td></tr>
</table>
</body></html>
"""

_FAKE_NI_HEADER = """
<html><body>
<p>재무상태표</p>
<table>
<tr><td>과 목</td></tr>
<tr><td>당기순이익</td></tr>
<tr><td>자 산 총 계</td></tr>
</table>
</body></html>
"""


def test_extract_accounts_five_col_uses_pair_not_blank() -> None:
    """5칸 표에서 총계는 합계 칸, 공란 내역은 0이 아니다."""
    accounts, status = extract_accounts(bs_html=_FIVE_COL_BS, is_html=None)
    assert status == "ok"
    total = _by_account_period(accounts, "total_asset", "current")
    assert total["value"] == 30665809879
    assert total["value_won"] == 30665809879
    assert total["unit_scale"] == 1
    assert total["period"] == "current"
    prior = _by_account_period(accounts, "total_asset", "prior")
    assert prior["value"] == 30322084856
    equity = _by_account_period(accounts, "total_equity", "current")
    assert equity["value"] == 100
    assert not any(
        r["account"] == "total_equity" and "부채" in (r["account_raw"] or "") for r in accounts
    )


def test_extract_accounts_jen_gi_larger_is_current() -> None:
    """제N기 기수가 있으면 큰 기가 당기이고 당기순 행은 헤더가 아니다."""
    accounts, status = extract_accounts(bs_html=_JEN_GI_BS, is_html=_JEN_GI_BS)
    assert status == "ok"
    total = _by_account_period(accounts, "total_asset", "current")
    assert total["value"] == 1179628362898
    assert "49" in compact(total["period_raw"])
    prior = _by_account_period(accounts, "total_asset", "prior")
    assert prior["value"] == 1084097944847
    ni = _by_account_period(accounts, "net_income", "current")
    assert ni["value"] == 166912885242
    assert not any(
        r["account"] == "net_income" and r["value"] == 1 for r in accounts
    )


def test_extract_accounts_same_gi_falls_back_left_right() -> None:
    """기수가 같으면 왼쪽이 당기다."""
    accounts, status = extract_accounts(bs_html=_SAME_GI, is_html=None)
    assert status == "ok"
    assert _by_account_period(accounts, "total_asset", "current")["value"] == 1000
    assert _by_account_period(accounts, "total_asset", "prior")["value"] == 900


def test_extract_accounts_no_gi_two_amount_cols_left_is_current() -> None:
    """제N기 없이 금액 열 두 개면 왼쪽이 당기다."""
    accounts, status = extract_accounts(bs_html=_NO_GI_TWO_AMOUNTS, is_html=None)
    assert status == "ok"
    assert _by_account_period(accounts, "total_asset", "current")["value"] == 100
    assert _by_account_period(accounts, "total_asset", "prior")["value"] == 200


def test_extract_accounts_danggisun_row_is_not_period_header() -> None:
    """과목만 있는 표의 당기순이익 행으로 ok를 내면 안 된다."""
    accounts, status = extract_accounts(bs_html=_FAKE_NI_HEADER, is_html=None)
    assert status == "not_found"
    assert accounts == []


def test_extract_accounts_six_col_skips_note_column() -> None:
    """6칸 주석 열은 금액이 아니고, 재고는 내역·총계는 합계 칸이다."""
    accounts, status = extract_accounts(bs_html=_SIX_COL, is_html=_SIX_COL)
    assert status == "ok"
    inv = _by_account_period(accounts, "inventory", "current")
    assert inv["value"] == 27435
    assert inv["unit_scale"] == 1000
    assert inv["value_won"] == 27435000
    rec = _by_account_period(accounts, "receivable", "current")
    assert rec["value"] == 123367
    total = _by_account_period(accounts, "total_asset", "current")
    assert total["value"] == 825062
    ni = _by_account_period(accounts, "net_income", "current")
    assert ni["value"] == 22755
    assert not any(
        r["account"] == "net_income" and r["value"] == 11226 for r in accounts
    )


def test_extract_accounts_four_col_dash_is_zero() -> None:
    """4칸 표의 '-' 금액은 0이고 주석 공란은 무시한다."""
    accounts, status = extract_accounts(bs_html=_FOUR_COL, is_html=None)
    assert status == "ok"
    contract = _by_account_period(accounts, "contract_asset", "current")
    assert contract["value"] == 0
    assert contract["value_won"] == 0
    assert contract["raw"] in {"-", "－"}
    missing = _by_account_period(accounts, "unbilled", "current")
    assert missing["status"] == "not_found"
    assert missing["value"] is None


def test_extract_accounts_ignores_equity_change_net_income() -> None:
    """자본변동표만 있으면 당기순을 읽지 않는다."""
    accounts, status = extract_accounts(bs_html=None, is_html=_EQUITY_CHANGE)
    assert status == "not_found"
    assert accounts == []


def test_extract_accounts_no_html_is_skipped() -> None:
    """제표 HTML이 없으면 skipped다."""
    accounts, status = extract_accounts(bs_html=None, is_html=None)
    assert status == "skipped"
    assert accounts == []


def test_cut_notes_drops_after_notes_heading() -> None:
    """부모 HTML은 '주석 ' 앞만 남긴다."""
    html = "<p>재무상태표</p><table><tr><td>자산총계</td></tr></table>주석 1. 중요한"
    assert "자산총계" in cut_notes(html)
    assert "중요한" not in cut_notes(html)


_MISALIGNED_SHORT_ROW = """
<html><body>
<p>재무상태표</p>
<p>(단위 : 원)</p>
<table>
<tr><td>과 목</td><td>주석</td><td>당기</td><td>전기</td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
</table>
</body></html>
"""

_TITLE_THEN_PERIOD_HEADER = """
<html><body>
<p>재무상태표</p>
<p>(단위 : 원)</p>
<table>
<tr><td colspan="3">제 12 기 2020년 12월 31일 현재</td></tr>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
</table>
</body></html>
"""

_BLANK_HEADING_THEN_INVENTORY = """
<html><body>
<p>재무상태표</p>
<p>(단위 : 원)</p>
<table>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>Ⅱ. 재고자산</td><td></td><td></td></tr>
<tr><td>재고자산</td><td>100</td><td>90</td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
</table>
</body></html>
"""

_BLANK_INVENTORY_ONLY = """
<html><body>
<p>재무상태표</p>
<p>(단위 : 원)</p>
<table>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>Ⅱ. 재고자산</td><td></td><td></td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
</table>
</body></html>
"""

_CAPTION_SPLIT_THEN_DANGGI = """
<html><body>
<p>재무상태표</p>
<table>
<tr><td>제 12 기</td><td>2020년 12월 31일 현재</td><td></td></tr>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
</table>
</body></html>
"""

_CAPTION_COLSPAN_GIMAL_THEN_DANGGI = """
<html><body>
<p>재무상태표</p>
<table>
<tr><td colspan="3">제 49 기말</td></tr>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
</table>
</body></html>
"""


def test_extract_accounts_skips_misaligned_short_row() -> None:
    """주석 칸이 빠진 짧은 행은 잘못된 당기 금액을 ok로 저장하지 않는다."""
    accounts, status = extract_accounts(bs_html=_MISALIGNED_SHORT_ROW, is_html=None)
    assert status == "ok"
    total = _by_account_period(accounts, "total_asset", "current")
    assert total["status"] == "not_found"
    assert total["value"] is None
    assert not any(
        r["account"] == "total_asset" and r.get("value") == 900 for r in accounts
    )


def test_extract_accounts_skips_title_row_without_period_groups() -> None:
    """제n기 제목 행만 있는 가짜 헤더는 건너뛰고 당기/전기 헤더를 쓴다."""
    accounts, status = extract_accounts(bs_html=_TITLE_THEN_PERIOD_HEADER, is_html=None)
    assert status == "ok"
    total = _by_account_period(accounts, "total_asset", "current")
    assert total["status"] == "ok"
    assert total["value"] == 1000
    prior = _by_account_period(accounts, "total_asset", "prior")
    assert prior["value"] == 900


def test_extract_accounts_blank_heading_does_not_block_later_amount() -> None:
    """금액 없는 재고 제목 행이 이후 금액 행을 가로채지 않는다."""
    accounts, status = extract_accounts(bs_html=_BLANK_HEADING_THEN_INVENTORY, is_html=None)
    assert status == "ok"
    inv = _by_account_period(accounts, "inventory", "current")
    assert inv["status"] == "ok"
    assert inv["value"] == 100
    assert inv["account_raw"] == "재고자산"


def test_extract_accounts_blank_only_label_emits_not_found() -> None:
    """금액 없는 계정 라벨만 있어도 해당 계정×기간 not_found가 남는다."""
    accounts, status = extract_accounts(bs_html=_BLANK_INVENTORY_ONLY, is_html=None)
    assert status == "ok"
    inv_cur = _by_account_period(accounts, "inventory", "current")
    inv_pri = _by_account_period(accounts, "inventory", "prior")
    assert inv_cur["status"] == "not_found"
    assert inv_pri["status"] == "not_found"
    assert inv_cur["value"] is None


def test_extract_accounts_caption_gi_row_then_danggi_jeonki() -> None:
    """제N기 캡션 행 뒤 당기/전기 헤더가 있으면 당기/전기를 쓴다."""
    accounts, status = extract_accounts(bs_html=_CAPTION_SPLIT_THEN_DANGGI, is_html=None)
    assert status == "ok"
    total = _by_account_period(accounts, "total_asset", "current")
    assert total["status"] == "ok"
    assert total["value"] == 1000
    prior = _by_account_period(accounts, "total_asset", "prior")
    assert prior["value"] == 900


def test_extract_accounts_colspan_gimal_caption_then_danggi_jeonki() -> None:
    """colspan 제N기말 캡션 뒤 당기/전기 헤더가 있으면 당기/전기를 쓴다."""
    accounts, status = extract_accounts(
        bs_html=_CAPTION_COLSPAN_GIMAL_THEN_DANGGI, is_html=None
    )
    assert status == "ok"
    total = _by_account_period(accounts, "total_asset", "current")
    assert total["status"] == "ok"
    assert total["value"] == 1000
    prior = _by_account_period(accounts, "total_asset", "prior")
    assert prior["value"] == 900


_NI_PROFIT_LOSS_MIXED = """
<html><body>
<p>포괄손익계산서</p>
<p>(단위: 원)</p>
<table>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>당기순이익(손실)</td><td>1,000</td><td>(500)</td></tr>
<tr><td>당기총포괄이익</td><td>9</td><td>8</td></tr>
</table>
</body></html>
"""

_NI_LOSS_LABEL = """
<html><body>
<p>손익계산서</p>
<p>(단위: 원)</p>
<table>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>당기순손실</td><td>1,000</td><td>(200)</td></tr>
</table>
</body></html>
"""


def test_extract_accounts_net_income_paren_loss_is_per_cell() -> None:
    """당기순이익(손실)은 칸마다 괄호만 음수이고 총포괄은 당기순이 아니다."""
    accounts, status = extract_accounts(bs_html=None, is_html=_NI_PROFIT_LOSS_MIXED)
    assert status == "ok"
    assert _by_account_period(accounts, "net_income", "current")["value"] == 1000
    assert _by_account_period(accounts, "net_income", "prior")["value"] == -500
    assert not any(
        r["account"] == "net_income" and r["value"] == 9 for r in accounts
    )


def test_extract_accounts_net_loss_label_is_always_negative() -> None:
    """당기순손실은 괄호 없는 칸도 음수이고, 이미 괄호인 칸은 한 번만 음수다."""
    accounts, status = extract_accounts(bs_html=None, is_html=_NI_LOSS_LABEL)
    assert status == "ok"
    assert _by_account_period(accounts, "net_income", "current")["value"] == -1000
    assert _by_account_period(accounts, "net_income", "prior")["value"] == -200


_NONCURRENT_ONLY_BS = """
<html><body>
<p>재무상태표</p>
<p>(단위: 원)</p>
<table>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>비유동자산</td><td>800</td><td>700</td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
<tr><td>비유동부채</td><td>200</td><td>150</td></tr>
<tr><td>자 본 총 계</td><td>800</td><td>750</td></tr>
</table>
</body></html>
"""

_OTHER_CURRENT_ONLY_BS = """
<html><body>
<p>재무상태표</p>
<p>(단위: 원)</p>
<table>
<tr><td>과 목</td><td>당기</td><td>전기</td></tr>
<tr><td>기타유동자산</td><td>50</td><td>40</td></tr>
<tr><td>자 산 총 계</td><td>1000</td><td>900</td></tr>
<tr><td>기타유동부채</td><td>30</td><td>20</td></tr>
<tr><td>자 본 총 계</td><td>800</td><td>750</td></tr>
</table>
</body></html>
"""

_SPC_BS = """
<html><body>
<p>재무상태표</p>
<p>(단위: 원)</p>
<table>
<tr>
  <td>과 목</td><td>제 3(당) 기</td><td>제 3(당) 기</td>
  <td>제 2(전) 기</td><td>제 2(전) 기</td>
</tr>
<tr><td>Ⅰ. 유동자산</td><td></td><td>588,065,798</td><td></td><td>644,317,902</td></tr>
<tr><td>Ⅱ. 유동화자산(주석4)</td><td></td><td>30,000,000,000</td><td></td><td>29,700,000,000</td></tr>
<tr><td>자 산 총 계</td><td></td><td>30,588,065,798</td><td></td><td>30,344,317,902</td></tr>
<tr><td>Ⅱ. 유동화부채(주석2,5)</td><td></td><td>30,000,000,000</td><td></td><td>29,700,000,000</td></tr>
<tr><td>자 본 총 계</td><td></td><td>100</td><td></td><td>100</td></tr>
</table>
</body></html>
"""


def test_extract_accounts_current_totals_use_pair_not_blank() -> None:
    """5칸 유동자산·유동부채 소계는 합계 칸이고 내역 공란은 0이 아니다."""
    accounts, status = extract_accounts(bs_html=_FIVE_COL_BS, is_html=None)
    assert status == "ok"
    asset = _by_account_period(accounts, "current_asset", "current")
    assert asset["status"] == "ok"
    assert asset["value"] == 665809879
    assert asset["value_won"] == 665809879
    prior_asset = _by_account_period(accounts, "current_asset", "prior")
    assert prior_asset["value"] == 622084856
    liab = _by_account_period(accounts, "current_liability", "current")
    assert liab["status"] == "ok"
    assert liab["value"] == 12345678
    prior_liab = _by_account_period(accounts, "current_liability", "prior")
    assert prior_liab["value"] == 11111111
    assert not any(
        r["account"] == "current_asset" and r.get("value") == 0 for r in accounts
    )


def test_extract_accounts_noncurrent_is_not_current() -> None:
    """비유동자산·비유동부채는 유동 소계가 아니다."""
    accounts, status = extract_accounts(bs_html=_NONCURRENT_ONLY_BS, is_html=None)
    assert status == "ok"
    asset = _by_account_period(accounts, "current_asset", "current")
    assert asset["status"] == "not_found"
    assert asset["value"] is None
    liab = _by_account_period(accounts, "current_liability", "current")
    assert liab["status"] == "not_found"
    assert liab["value"] is None
    assert not any(
        r["account"] in {"current_asset", "current_liability"} and r.get("value")
        for r in accounts
    )


def test_extract_accounts_other_current_is_not_subtotal() -> None:
    """기타유동자산·기타유동부채는 소계가 아니다."""
    accounts, status = extract_accounts(bs_html=_OTHER_CURRENT_ONLY_BS, is_html=None)
    assert status == "ok"
    asset = _by_account_period(accounts, "current_asset", "current")
    assert asset["status"] == "not_found"
    liab = _by_account_period(accounts, "current_liability", "current")
    assert liab["status"] == "not_found"
    assert not any(
        r["account"] in {"current_asset", "current_liability"}
        and "기타" in (r["account_raw"] or "")
        for r in accounts
    )


def test_extract_accounts_securitized_liability_is_not_current() -> None:
    """유동화자산은 유동자산이 아니고, 유동화부채만 있으면 유동부채는 not_found다."""
    accounts, status = extract_accounts(bs_html=_SPC_BS, is_html=None)
    assert status == "ok"
    asset = _by_account_period(accounts, "current_asset", "current")
    assert asset["status"] == "ok"
    assert asset["value"] == 588065798
    assert "유동화" not in (asset["account_raw"] or "")
    liab = _by_account_period(accounts, "current_liability", "current")
    assert liab["status"] == "not_found"
    assert liab["value"] is None
    assert not any(
        r["account"] == "current_liability" and r.get("value") == 30000000000
        for r in accounts
    )


def test_total_liability_five_col_uses_total_cell() -> None:
    """부채총계는 합계 칸이고, 부채와자본총계·유동부채와 키가 갈린다."""
    rows, status = extract_accounts(bs_html=_FIVE_COL_BS, is_html=None)
    assert status == "ok"
    current = _by_account_period(rows, "total_liability", "current")
    assert current["status"] == "ok"
    assert current["value"] == 20000000
    prior = _by_account_period(rows, "total_liability", "prior")
    assert prior["value"] == 19000000
    assert _by_account_period(rows, "current_liability", "current")["value"] == 12345678


def test_liability_and_equity_total_is_not_total_liability() -> None:
    """부채와자본총계만 있는 표는 total_liability가 not_found다."""
    html = """
    <html><body>
    <p>재무상태표</p>
    <table>
    <tr><td>과 목</td><td>당기</td><td>전기</td></tr>
    <tr><td>자 산 총 계</td><td>100</td><td>90</td></tr>
    <tr><td>부채와자본총계</td><td>100</td><td>90</td></tr>
    </table>
    </body></html>
    """
    rows, status = extract_accounts(bs_html=html, is_html=None)
    assert status == "ok"
    item = _by_account_period(rows, "total_liability", "current")
    assert item["status"] == "not_found"
    assert item["value"] is None
