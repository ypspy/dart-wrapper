"""첨부 제표 계정 추출 테스트."""

from app.extracting.accounts import extract_accounts


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
<tr><td>Ⅰ. 자본금</td><td></td><td>100</td><td></td><td>100</td></tr>
<tr><td>자 본 총 계</td><td></td><td>100</td><td></td><td>100</td></tr>
<tr><td>부채와자본총계</td><td></td><td>30,665,809,879</td><td></td><td>30,322,084,856</td></tr>
</table>
</body></html>
"""


def _by_account_period(rows: list[dict], account: str, period: str) -> dict:
    return next(r for r in rows if r["account"] == account and r["period"] == period)


_UNREADABLE_BS = """
<html><body>
<p>재무상태표</p>
<table>
<tr><td>과 목</td><td>비고A</td><td>비고B</td></tr>
<tr><td>자 산 총 계</td><td>100</td><td>200</td></tr>
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


def test_extract_accounts_unreadable_table_is_not_found() -> None:
    """제목·표는 있어도 당기/전기 헤더가 없으면 not_found다."""
    accounts, status = extract_accounts(bs_html=_UNREADABLE_BS, is_html=None)
    assert status == "not_found"
    assert accounts == []
