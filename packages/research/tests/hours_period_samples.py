"""단일 기간·비교표시 감사시간 표의 합성 칸.

실제 회사명과 실제 접수번호는 쓰지 않는다.
"""

from __future__ import annotations

_ROLES: tuple[tuple[str, str], ...] = (
    ("qcr", "품질관리검토자"),
    ("engagement_partner", "담당이사"),
    ("cpa", "등록공인회계사"),
    ("junior_cpa", "수습공인회계사"),
    ("specialist", "전산감사ㆍ세무ㆍ가치평가 등 전문가"),
    ("total", "합계"),
)
_METRICS: tuple[str, ...] = ("headcount", "interim_review", "audit", "total")


def single_period_hours(
    *,
    audit_total: int = 100,
    headcount_total: int = 15,
) -> list[dict[str, object]]:
    """역할 6열 × 지표 4행 = 24칸. period는 unknown, period_raw는 빈 문자열."""
    cells: list[dict[str, object]] = []
    for metric in _METRICS:
        for role, role_raw in _ROLES:
            if role == "total" and metric == "audit":
                value: int = audit_total
            elif role == "total" and metric == "headcount":
                value = headcount_total
            else:
                value = 1
            cells.append(
                {
                    "role": role,
                    "role_raw": role_raw,
                    "metric": metric,
                    "metric_raw": metric,
                    "period": "unknown",
                    "period_raw": "",
                    "raw": str(value),
                    "value": value,
                    "unmapped": False,
                }
            )
    return cells


def comparative_hours(
    *,
    audit_current: int | None,
    audit_prior: int,
    headcount_current: int | None = 7,
    headcount_prior: int = 5,
) -> list[dict[str, object]]:
    """당기·전기가 있는 새 서식. None이면 그 지표의 당기 합계 칸을 넣지 않는다."""
    cells: list[dict[str, object]] = []
    totals = (
        ("audit", audit_current, audit_prior),
        ("headcount", headcount_current, headcount_prior),
    )
    for metric, current, prior in totals:
        if current is not None:
            cells.append(_cell("total", "합계", metric, "current", "당기", current))
        cells.append(_cell("total", "합계", metric, "prior", "전기", prior))
    cells.append(_cell("engagement_partner", "담당이사", "audit", "current", "당기", 3))
    cells.append(_cell("engagement_partner", "담당이사", "audit", "prior", "전기", 2))
    return cells


def _cell(
    role: str,
    role_raw: str,
    metric: str,
    period: str,
    period_raw: str,
    value: int,
) -> dict[str, object]:
    """합성 칸 하나."""
    return {
        "role": role,
        "role_raw": role_raw,
        "metric": metric,
        "metric_raw": metric,
        "period": period,
        "period_raw": period_raw,
        "raw": str(value),
        "value": value,
        "unmapped": False,
    }
