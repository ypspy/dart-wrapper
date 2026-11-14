"""Seaweed schema_version 1 JSONL과 읽기 전용 카탈로그 로더.

``dart_sections.db``는 읽지 않는다. 원문 URL은 저장만 하고 호출하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

SCHEMA_VERSION = 1

REQUIRED_FIELDS = (
    "schema_version",
    "rcept_no",
    "corp_code",
    "corp_name",
    "report_nm",
    "correction_type",
    "submitter",
    "rcept_dt",
    "bsns_year",
    "section_code",
    "section_title",
    "body_text",
    "body_hash",
    "body_chars",
    "source_url",
    "fetched_at",
)

_YEAR_END = re.compile(r"(\d{4})\s*[.\-/]\s*(\d{1,2})")


class FirmRemediationError(Exception):
    """개선권고 추출을 진행할 수 없을 때."""


class FirmRemediationLoadError(FirmRemediationError):
    """스냅샷 검증에 실패해 부분 적재 없이 중단할 때."""


@dataclass(frozen=True)
class SectionRecord:
    """JSONL 한 행에서 적재에 쓰는 필드."""

    rcept_no: str
    corp_code: str
    corp_name: str
    rcept_dt: str
    body_text: str
    body_hash: str


def readonly_file_uri(path: Path) -> str:
    """카탈로그 파일을 mode=ro URI로 가리킨다."""
    return f"{Path(path).resolve().as_uri()}?mode=ro"


def require_readonly_uri(uri: str) -> None:
    """mode=ro가 아닌 SQLite URI는 연결 전에 거부한다."""
    query = uri.split("?", 1)[1] if "?" in uri else ""
    modes = [part for part in query.split("&") if part.startswith("mode=")]
    if modes != ["mode=ro"]:
        raise FirmRemediationLoadError(
            "카탈로그는 SQLite URI mode=ro 로만 열 수 있습니다. 쓰기 연결은 만들지 않습니다."
        )


def connect_catalog(path: Path) -> sqlite3.Connection:
    """카탈로그를 읽기 전용으로 연다. 쓰기 시도는 SQLite가 거절한다."""
    if not Path(path).is_file():
        raise FirmRemediationLoadError(f"카탈로그 파일을 찾지 못했습니다: {path}")
    uri = readonly_file_uri(path)
    require_readonly_uri(uri)
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def period_key_from_year_end(year_end: str | None) -> str | None:
    """카탈로그 ``(2016.03)`` 형태를 ``2016-03``으로 바꾼다."""
    if year_end is None:
        return None
    match = _YEAR_END.search(str(year_end))
    if match is None:
        return None
    month = int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{int(match.group(1)):04d}-{month:02d}"


def fetch_year_ends(catalog_path: Path, rcept_nos: Sequence[str]) -> dict[str, str | None]:
    """``disclosures.year_end``만 SELECT 한다."""
    wanted = list(dict.fromkeys(rcept_nos))
    found: dict[str, str | None] = {}
    if not wanted:
        return found
    connection = connect_catalog(catalog_path)
    try:
        for start in range(0, len(wanted), 400):
            chunk = wanted[start : start + 400]
            placeholders = ",".join("?" for _ in chunk)
            statement = (
                f"SELECT rcept_no, year_end FROM disclosures WHERE rcept_no IN ({placeholders})"
            )
            for row in connection.execute(statement, chunk):
                found[str(row["rcept_no"])] = row["year_end"]
    finally:
        connection.close()
    return found


def resolve_jsonl(input_path: Path) -> tuple[Path, Path]:
    """디렉터리면 ``f004_section6.jsonl`` 또는 유일한 jsonl을 고른다. manifest는 필수다."""
    path = Path(input_path)
    if path.is_dir():
        preferred = path / "f004_section6.jsonl"
        if preferred.is_file():
            jsonl_path = preferred
        else:
            found = sorted(item for item in path.glob("*.jsonl") if item.is_file())
            if len(found) != 1:
                raise FirmRemediationLoadError(
                    "입력 폴더에서 f004_section6.jsonl 또는 유일한 jsonl 파일을 찾지 못했습니다."
                )
            jsonl_path = found[0]
        manifest = path / "manifest.json"
    elif path.is_file():
        jsonl_path = path
        manifest = path.parent / "manifest.json"
    else:
        raise FirmRemediationLoadError(f"입력 경로를 찾지 못했습니다: {path}")
    if not manifest.is_file():
        raise FirmRemediationLoadError(
            "manifest.json이 없습니다. 부분 적재 없이 중단합니다. " f"기대 위치: {manifest}"
        )
    return jsonl_path, manifest


def load_section_records(input_path: Path) -> list[SectionRecord]:
    """JSONL 전체를 검증한 뒤에만 반환한다. 중간 실패 시 결과를 돌려주지 않는다."""
    jsonl_path, manifest_path = resolve_jsonl(input_path)
    payload = jsonl_path.read_bytes()
    _check_manifest(manifest_path, payload)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FirmRemediationLoadError(
            "JSONL이 UTF-8이 아닙니다. 부분 적재 없이 중단합니다."
        ) from exc
    records: list[SectionRecord] = []
    seen: dict[str, int] = {}
    for line_no, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FirmRemediationLoadError(
                f"{line_no}번째 줄을 JSON으로 읽지 못했습니다. 부분 적재 없이 중단합니다."
            ) from exc
        if not isinstance(obj, dict):
            raise FirmRemediationLoadError(
                f"{line_no}번째 줄이 객체가 아닙니다. 부분 적재 없이 중단합니다."
            )
        record = _record_from_row(obj, line_no)
        previous = seen.get(record.rcept_no)
        if previous is not None:
            raise FirmRemediationLoadError(
                f"접수번호 {record.rcept_no}가 중복입니다. "
                f"첫 줄 {previous}, 다시 나온 줄 {line_no}. 부분 적재 없이 중단합니다."
            )
        seen[record.rcept_no] = line_no
        records.append(record)
    return records


def _check_manifest(manifest_path: Path, payload: bytes) -> None:
    """schema_version과 jsonl 해시·바이트를 파일과 대조한다."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FirmRemediationLoadError(
            "manifest.json을 읽지 못했습니다. 부분 적재 없이 중단합니다."
        ) from exc
    if not isinstance(manifest, dict):
        raise FirmRemediationLoadError("manifest.json 형식이 객체가 아닙니다.")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise FirmRemediationLoadError(
            "manifest.json의 schema_version이 1이 아닙니다. 부분 적재 없이 중단합니다."
        )
    field_names = _manifest_field_names(manifest.get("fields"))
    if field_names is not None and field_names != set(REQUIRED_FIELDS):
        raise FirmRemediationLoadError(
            "manifest.json의 fields가 이 로더가 아는 필드와 다릅니다. "
            "이름을 추측하지 않고 중단합니다."
        )
    digest = _manifest_value(manifest, "sha256")
    if digest is None:
        raise FirmRemediationLoadError(
            "manifest.json에 jsonl.sha256이 없습니다. 부분 적재 없이 중단합니다."
        )
    actual = hashlib.sha256(payload).hexdigest()
    if str(digest).lower() != actual:
        raise FirmRemediationLoadError(
            "manifest.json의 jsonl.sha256이 파일과 다릅니다. 부분 적재 없이 중단합니다."
        )
    size = _manifest_value(manifest, "bytes")
    if size is not None:
        try:
            size_int = int(size)
        except (TypeError, ValueError) as exc:
            raise FirmRemediationLoadError(
                "manifest.json의 jsonl.bytes가 정수가 아닙니다. 부분 적재 없이 중단합니다."
            ) from exc
        if isinstance(size, bool) or size_int != len(payload):
            raise FirmRemediationLoadError(
                "manifest.json의 jsonl.bytes가 파일 크기와 다릅니다. 부분 적재 없이 중단합니다."
            )


def _manifest_field_names(fields: Any) -> set[str] | None:
    """fields가 없으면 대조를 건너뛴다. 문자열 또는 ``{name}`` 객체만 이름으로 본다."""
    if fields is None:
        return None
    if not isinstance(fields, list):
        raise FirmRemediationLoadError(
            "manifest.json의 fields가 목록이 아닙니다. 이름을 추측하지 않고 중단합니다."
        )
    names: list[str] = []
    for item in fields:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
        else:
            raise FirmRemediationLoadError(
                "manifest.json의 fields 원소를 해석할 수 없습니다. "
                "이름을 추측하지 않고 중단합니다."
            )
    return set(names)


def _manifest_value(manifest: dict[str, Any], name: str) -> Any:
    """중첩 ``jsonl`` 객체 또는 ``jsonl.sha256`` 평탄 키를 읽는다."""
    nested = manifest.get("jsonl")
    if isinstance(nested, dict) and name in nested:
        return nested[name]
    flat_key = f"jsonl.{name}"
    if flat_key in manifest:
        return manifest[flat_key]
    return None


def _record_from_row(obj: dict[str, Any], line_no: int) -> SectionRecord:
    missing = [name for name in REQUIRED_FIELDS if name not in obj]
    if missing:
        joined = ", ".join(missing)
        raise FirmRemediationLoadError(
            f"{line_no}번째 줄에 필드가 없습니다: {joined}. 이름을 추측하지 않고 중단합니다."
        )
    if obj.get("schema_version") != SCHEMA_VERSION:
        raise FirmRemediationLoadError(
            f"{line_no}번째 줄의 schema_version이 1이 아닙니다. 부분 적재 없이 중단합니다."
        )
    body_text = obj.get("body_text")
    if not isinstance(body_text, str):
        raise FirmRemediationLoadError(
            f"{line_no}번째 줄의 body_text가 문자열이 아닙니다. 부분 적재 없이 중단합니다."
        )
    digest = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
    if str(obj.get("body_hash")).lower() != digest:
        rcept_no = obj.get("rcept_no")
        raise FirmRemediationLoadError(
            f"본문 해시가 일치하지 않습니다. 부분 적재 없이 중단합니다. "
            f"(줄 {line_no}, 접수번호 {rcept_no})"
        )
    if obj.get("body_chars") != len(body_text):
        raise FirmRemediationLoadError(
            f"{line_no}번째 줄의 body_chars가 본문 길이와 다릅니다. 부분 적재 없이 중단합니다."
        )
    return SectionRecord(
        rcept_no=str(obj["rcept_no"]),
        corp_code=str(obj["corp_code"]),
        corp_name="" if obj.get("corp_name") is None else str(obj["corp_name"]),
        rcept_dt="" if obj.get("rcept_dt") is None else str(obj["rcept_dt"]),
        body_text=body_text,
        body_hash=str(obj["body_hash"]),
    )
