"""Public 감사 추출 결과 목록 조회."""

from __future__ import annotations

import base64
import json

from app.errors import BadRequest


def encode_fact_cursor(rcept_dt: str, rcept_no: str, dcm_no: str) -> str:
    """목록 페이지의 opaque cursor를 만든다."""
    payload = json.dumps(
        {"rcept_dt": rcept_dt, "rcept_no": rcept_no, "dcm_no": dcm_no},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_fact_cursor(cursor: str) -> tuple[str, str, str]:
    """opaque cursor를 (rcept_dt, rcept_no, dcm_no)로 복원한다.

    :raises BadRequest: 손상되었거나 필드가 없는 경우
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return data["rcept_dt"], data["rcept_no"], data["dcm_no"]
    except Exception as exc:
        raise BadRequest(
            "커서 값이 올바르지 않습니다. 이전 응답의 next_cursor를 그대로 전달해 주세요."
        ) from exc
