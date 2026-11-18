"""단일 기간 감사시간 표에서 합계 칸을 고르는 순수 함수.

unknown을 무조건 당기(current)로 보지 않는다.
가드는 아래 여섯 조건을 모두 만족할 때만 참이다.
가드가 거짓이면 master와 같다.

1. 당기/전기 표시가 없다. 모든 칸의 period가 unknown이고 period_raw가 비어 있다.
2. 기간이 섞여 있지 않다. current 또는 prior 칸이 없다.
3. 역할당 열이 하나다. (role, role_raw, metric) 키가 각각 한 번만 나온다.
4. 역할을 모르는 열이 없다. role이 other인 칸이 하나라도 있으면 거짓이다.
   metric이 other인 모르는 지표 행은 합계 칸 선택에 영향이 없어 조건에 넣지 않는다.
5. 합계 열이 하나다. role이 total인 칸의 role_raw가 2종류 이상이면 거짓이다.
6. 키 값이 문자열이다. role·role_raw·metric 중 하나라도 str도 None도 아니면 거짓이다.

한계:

1. colspan으로 역할당 열이 2개인 무라벨 표는 가드가 거짓이다. 당기 합계가
   없으므로 hours_total_missing이다. 어느 열이 당기인지 정할 근거가 없어
   사람 검토로 보내는 것이 의도다.
2. role_raw가 다른 합계 열 2개는 가드가 거짓이고 hours_total_missing이다.
   골드 키는 (None, None)이다. 어느 열이 당기인지 근거가 없다.
3. 역할을 모르는 열(role이 other)이 있으면 개수와 상관없이 가드가 거짓이고
   hours_total_missing이다.
4. 구조로 구분할 수 없는 남은 경우는 새 서식인데 당기/전기 표시를 하나도
   읽지 못했고, 역할 헤더는 열마다 하나씩 읽힌 표다. 이 표는 옛 서식과
   칸 구조가 같아서 가드가 참이다. 헤더가 아예 없는 6값 열은 키가 겹쳐
   가드가 거짓(missing)이다. 연도 조건은 넣지 않았다. 서식 변경 시점
   (2016년 7–8월경)이 딱 떨어지지 않고, 구조상 단일 기간인 새 fact 2건이
   2017-04 접수다(원문 대조 전). 컷을 넣으면 그런 문서를 잘라낼 수 있다.
"""

from __future__ import annotations


def is_single_period_hours(hours: object) -> bool:
    """단일 기간 표인지 본다.

    unknown을 무조건 current로 보지 않는다.
    리스트이고 dict 칸이 하나 이상이며, 가드 여섯 조건을 모두 만족할 때만 True다.
    가드가 거짓이면 master와 같다.
    """
    if not isinstance(hours, list) or not hours:
        return False
    keys: list[tuple[object, object, object]] = []
    total_raws: set[object] = set()
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
        role = item.get("role")
        role_raw = item.get("role_raw")
        metric = item.get("metric")
        # 6. 키 값이 문자열. set 비교 전에 확인해 TypeError를 막는다.
        if not all(isinstance(value, str) or value is None for value in (role, role_raw, metric)):
            return False
        # 4. 역할을 모르는 열. unmapped가 아니라 role로 판단한다.
        if role == "other":
            return False
        # 5. 합계 열의 role_raw는 한 종류여야 한다.
        if role == "total":
            total_raws.add(role_raw)
        keys.append((role, role_raw, metric))
    if len(total_raws) > 1:
        return False
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
