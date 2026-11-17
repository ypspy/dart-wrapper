"""단일 기간 감사시간 표에서 합계 칸을 고르는 순수 함수.

unknown을 무조건 당기(current)로 보지 않는다.
가드는 아래 세 조건을 모두 만족할 때만 참이다.

1. 당기/전기 표시가 없다. 모든 칸의 period가 unknown이고 period_raw가 비어 있다.
2. 기간이 섞여 있지 않다. current 또는 prior 칸이 없다.
3. 역할당 열이 하나다. (role, role_raw, metric) 키가 각각 한 번만 나온다.
"""

from __future__ import annotations


def is_single_period_hours(hours: object) -> bool:
    """단일 기간 표인지 본다.

    unknown을 무조건 current로 보지 않는다.
    리스트이고 dict 칸이 하나 이상이며, 가드 세 조건을 모두 만족할 때만 True다.
    """
    if not isinstance(hours, list) or not hours:
        return False
    keys: list[tuple[object, object, object]] = []
    for item in hours:
        if not isinstance(item, dict):
            return False
        period = item.get("period")
        period_raw = item.get("period_raw") or ""
        # 2. 섞임 없음. current·prior가 있으면 단일 기간이 아니다.
        if period in {"current", "prior"}:
            return False
        # 1. 당기/전기 표시 없음. unknown이 아니거나 기간 원문이 있으면 거절한다.
        if period != "unknown" or period_raw != "":
            return False
        keys.append((item.get("role"), item.get("role_raw"), item.get("metric")))
    # 3. 역할당 열 1개. colspan 복제는 같은 키가 두 번 나온다.
    return len(keys) == len(set(keys))


def total_cells(hours: object, metric: str) -> list[dict[str, object]] | None:
    """합계 칸을 고른다.

    리스트가 아니면 None이다.
    가드가 참이면 role이 total이고 metric이 일치하며 period가 unknown인 칸을 돌려준다.
    가드가 거짓이면 지금처럼 period가 current인 칸만 돌려준다.
    unknown을 무조건 current로 보지 않는다.
    """
    if not isinstance(hours, list):
        return None
    period = "unknown" if is_single_period_hours(hours) else "current"
    cells: list[dict[str, object]] = []
    for item in hours:
        if not isinstance(item, dict):
            continue
        if (
            item.get("role") == "total"
            and item.get("metric") == metric
            and item.get("period") == period
        ):
            cells.append(item)
    return cells
