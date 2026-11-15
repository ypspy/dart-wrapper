"""연구 추출 앱이 1층 카탈로그에 쓰지 못하게 하는 순수 검사.

1층은 Seaweed 수집(nightly_catalog.py·app.local)만 바꾼다.
판단이 애매한 SQL은 통과시키지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import (
    _CATALOG_TABLES,
    _COLUMN_PATCHES,
    _column_exists,
    _table_exists,
)

# 카탈로그 6개에 corps를 더한다. corps 모델은 연구 패키지에 있지만 1층으로 본다.
FIRST_LAYER_TABLES: frozenset[str] = frozenset(_CATALOG_TABLES) | {"corps"}

_READ_OR_TRANSACTION = frozenset(
    {
        "select",
        "pragma",
        "begin",
        "commit",
        "rollback",
        "savepoint",
        "release",
        "end",
        "values",
    }
)
_OR_CONFLICT = frozenset({"ignore", "replace", "abort", "fail", "rollback"})
_SEAWEED = "1층은 Seaweed 수집(nightly_catalog.py·app.local)만 바꿉니다."

Token = tuple[str, str]


class CatalogWriteBlocked(RuntimeError):
    """연구 추출 앱이 1층 테이블에 쓰려 할 때 발생시킨다."""


class CatalogSchemaError(RuntimeError):
    """1층 스키마가 연구 앱을 시작하기에 부족할 때 발생시킨다."""


def assert_no_first_layer_write(statement: str) -> None:
    """쓰기 대상이 1층이면 한국어 메시지로 막는다.

    앞 공백·주석과 대소문자는 무시한다. 서브쿼리에서 1층을 읽는 것은 허용한다.
    ``entries_backup``처럼 이름이 단지 겹치는 테이블은 1층이 아니다.
    """
    if not isinstance(statement, str):
        raise CatalogWriteBlocked(
            "연구 추출 앱은 SQL의 쓰기 대상을 확인하지 못해 막습니다. " + _SEAWEED
        )
    for part in _split_statements(_tokenize(statement)):
        _check_statement(part)


@contextmanager
def block_first_layer_writes(sync_engine: Engine) -> Iterator[None]:
    """기동 구간에만 sync 엔진의 각 문장을 1층 쓰기 검사에 올린다."""

    def _guard(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        assert_no_first_layer_write(statement)

    event.listen(sync_engine, "before_cursor_execute", _guard)
    try:
        yield
    finally:
        event.remove(sync_engine, "before_cursor_execute", _guard)


async def verify_catalog_schema(engine: AsyncEngine) -> None:
    """1층 테이블과 알려진 열이 있는지만 읽는다. DDL·DML은 하지 않는다."""
    missing: list[str] = []
    async with engine.connect() as connection:
        dialect = connection.dialect.name
        present: set[str] = set()
        for table in _CATALOG_TABLES:
            if await _table_exists(connection, table, dialect):
                present.add(table)
            else:
                missing.append(f"{table} 없음")
        for table, column, _sqlite_ddl, _postgres_ddl in _COLUMN_PATCHES:
            if table not in present:
                continue
            if not await _column_exists(connection, table, column, dialect):
                missing.append(f"{table}.{column} 없음")
    if not missing:
        return
    detail = ", ".join(missing)
    raise CatalogSchemaError(
        "1층 스키마가 맞지 않아 연구 추출 앱을 시작하지 않습니다: "
        f"{detail}. 연구 앱은 1층 테이블·열을 만들지 않습니다. "
        "수집 쪽(scripts/nightly_catalog.py 또는 uvicorn app.local:app)을 먼저 "
        "실행해 스키마를 맞춘 뒤 다시 시작하세요."
    )


def _check_statement(tokens: list[Token]) -> None:
    """문장 앞머리만 보고 쓰기 대상을 정한다."""
    if not tokens:
        return
    if tokens[0][0] != "word":
        _block_unknown(tokens)
    keyword = tokens[0][1].casefold()
    if keyword == "explain":
        rest = tokens[1:]
        if (
            len(rest) >= 2
            and rest[0][1].casefold() == "query"
            and rest[1][1].casefold() == "plan"
        ):
            rest = rest[2:]
        _check_statement(rest)
        return
    if keyword == "with":
        rest = _main_after_with(tokens)
        if not rest:
            _block_unknown(tokens)
        _check_statement(rest)
        return
    if keyword in _READ_OR_TRANSACTION:
        return
    if keyword == "insert":
        _reject_table(_parse_insert(tokens), "INSERT")
        return
    if keyword == "replace":
        _reject_table(_parse_replace(tokens), "REPLACE")
        return
    if keyword == "update":
        _reject_table(_parse_update(tokens), "UPDATE")
        return
    if keyword == "delete":
        _reject_table(_parse_delete(tokens), "DELETE")
        return
    if keyword == "alter":
        _reject_table(_parse_alter(tokens), "ALTER")
        return
    if keyword == "create":
        operation, table = _parse_create(tokens)
        _reject_table(table, operation)
        return
    if keyword == "drop":
        _parse_drop(tokens)
        return
    _block_unknown(tokens)


def _reject_table(table: str, operation: str) -> None:
    """1층 테이블이면 막는다. 그 외 테이블은 허용한다."""
    normalized = table.casefold()
    if normalized not in FIRST_LAYER_TABLES:
        return
    raise CatalogWriteBlocked(
        "연구 추출 앱은 1층 테이블에 쓰지 않습니다: "
        f"{normalized} ({operation}). " + _SEAWEED
    )


def _parse_insert(tokens: list[Token]) -> str:
    index = _skip_or_conflict(tokens, 1)
    if not _is_word_at(tokens, index, "into"):
        _block_unknown(tokens)
    name, _index = _read_qualified(tokens, index + 1)
    return name


def _parse_replace(tokens: list[Token]) -> str:
    if not _is_word_at(tokens, 1, "into"):
        _block_unknown(tokens)
    name, _index = _read_qualified(tokens, 2)
    return name


def _parse_update(tokens: list[Token]) -> str:
    index = _skip_or_conflict(tokens, 1)
    name, _index = _read_qualified(tokens, index)
    return name


def _parse_delete(tokens: list[Token]) -> str:
    if not _is_word_at(tokens, 1, "from"):
        _block_unknown(tokens)
    name, _index = _read_qualified(tokens, 2)
    return name


def _parse_alter(tokens: list[Token]) -> str:
    if not _is_word_at(tokens, 1, "table"):
        _block_unknown(tokens)
    name, _index = _read_qualified(tokens, 2)
    return name


def _parse_create(tokens: list[Token]) -> tuple[str, str]:
    index = 1
    if _is_word_at(tokens, index, "temp", "temporary"):
        index += 1
    if _is_word_at(tokens, index, "unique"):
        index += 1
        if not _is_word_at(tokens, index, "index"):
            _block_unknown(tokens)
        return _parse_create_index(tokens, index + 1)
    if _is_word_at(tokens, index, "index"):
        return _parse_create_index(tokens, index + 1)
    if _is_word_at(tokens, index, "table"):
        index = _skip_if_not_exists(tokens, index + 1)
        name, _index = _read_qualified(tokens, index)
        return "CREATE TABLE", name
    _block_unknown(tokens)


def _parse_create_index(tokens: list[Token], index: int) -> tuple[str, str]:
    index = _skip_if_not_exists(tokens, index)
    _name, index = _read_qualified(tokens, index)
    if not _is_word_at(tokens, index, "on"):
        _block_unknown(tokens)
    table, _index = _read_qualified(tokens, index + 1)
    return "CREATE INDEX", table


def _parse_drop(tokens: list[Token]) -> None:
    if not _is_word_at(tokens, 1, "table", "index"):
        _block_unknown(tokens)
    kind = tokens[1][1].casefold()
    index = _skip_if_exists(tokens, 2)
    name, _index = _read_qualified(tokens, index)
    if kind == "table":
        _reject_table(name, "DROP TABLE")
        return
    _block_drop_index(name)


def _block_drop_index(name: str) -> None:
    """DROP INDEX는 대상 테이블을 문장만으로 확정하기 어렵다.

    1층 인덱스 이름이면 그 테이블로 막고, 판단이 안 되면 그대로 막는다.
    """
    normalized = name.casefold()
    table = _first_layer_index_table(normalized)
    target = table if table is not None else normalized
    raise CatalogWriteBlocked(
        "연구 추출 앱은 1층 테이블에 쓰지 않습니다: "
        f"{target} (DROP INDEX). "
        "인덱스 대상을 확인할 수 없으면 막습니다. " + _SEAWEED
    )


def _first_layer_index_table(name: str) -> str | None:
    """인덱스 이름이 1층 자동 인덱스이거나 카탈로그 인덱스면 테이블을 돌려준다."""
    for table in FIRST_LAYER_TABLES:
        if name.startswith(f"sqlite_autoindex_{table}_"):
            return table
    from app.models import Base

    for table_name in _CATALOG_TABLES:
        table = Base.metadata.tables.get(table_name)
        if table is None:
            continue
        for index in table.indexes:
            if index.name and index.name.casefold() == name:
                return table_name
    return None


def _main_after_with(tokens: list[Token]) -> list[Token]:
    """WITH 절 뒤의 본문 문장 토큰을 돌려준다."""
    index = 1
    if _is_word_at(tokens, index, "recursive"):
        index += 1
    while True:
        _name, index = _read_qualified(tokens, index)
        if index < len(tokens) and tokens[index] == ("punct", "("):
            index = _skip_paren(tokens, index)
        if not _is_word_at(tokens, index, "as"):
            _block_unknown(tokens)
        index += 1
        if index >= len(tokens) or tokens[index] != ("punct", "("):
            _block_unknown(tokens)
        index = _skip_paren(tokens, index)
        if index < len(tokens) and tokens[index] == ("punct", ","):
            index += 1
            continue
        return tokens[index:]


def _skip_or_conflict(tokens: list[Token], index: int) -> int:
    if not _is_word_at(tokens, index, "or"):
        return index
    if not _is_word_at(tokens, index + 1, *_OR_CONFLICT):
        _block_unknown(tokens)
    return index + 2


def _skip_if_not_exists(tokens: list[Token], index: int) -> int:
    if (
        _is_word_at(tokens, index, "if")
        and _is_word_at(tokens, index + 1, "not")
        and _is_word_at(tokens, index + 2, "exists")
    ):
        return index + 3
    return index


def _skip_if_exists(tokens: list[Token], index: int) -> int:
    if _is_word_at(tokens, index, "if") and _is_word_at(tokens, index + 1, "exists"):
        return index + 2
    return index


def _skip_paren(tokens: list[Token], index: int) -> int:
    if index >= len(tokens) or tokens[index] != ("punct", "("):
        _block_unknown(tokens)
    depth = 0
    while index < len(tokens):
        if tokens[index] == ("punct", "("):
            depth += 1
        elif tokens[index] == ("punct", ")"):
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    _block_unknown(tokens)


def _read_qualified(tokens: list[Token], index: int) -> tuple[str, int]:
    name, index = _read_ident(tokens, index)
    while index < len(tokens) and tokens[index] == ("punct", "."):
        name, index = _read_ident(tokens, index + 1)
    return name, index


def _read_ident(tokens: list[Token], index: int) -> tuple[str, int]:
    if index >= len(tokens) or tokens[index][0] not in {"word", "ident"}:
        _block_unknown(tokens[index:] or tokens)
    return tokens[index][1], index + 1


def _is_word_at(tokens: list[Token], index: int, *words: str) -> bool:
    if index < 0 or index >= len(tokens):
        return False
    kind, value = tokens[index]
    return kind == "word" and value.casefold() in words


def _split_statements(tokens: list[Token]) -> list[list[Token]]:
    parts: list[list[Token]] = []
    current: list[Token] = []
    for token in tokens:
        if token == ("punct", ";"):
            if current:
                parts.append(current)
            current = []
            continue
        current.append(token)
    if current:
        parts.append(current)
    return parts


def _tokenize(statement: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    length = len(statement)
    while index < length:
        char = statement[index]
        if char.isspace():
            index += 1
            continue
        if statement.startswith("--", index):
            newline = statement.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if statement.startswith("/*", index):
            end = statement.find("*/", index + 2)
            if end < 0:
                raise CatalogWriteBlocked(
                    "연구 추출 앱은 주석이 닫히지 않은 SQL의 쓰기 대상을 확인하지 못해 막습니다. "
                    + _SEAWEED
                )
            index = end + 2
            continue
        if char in '"`[':
            value, index = _scan_quoted(statement, index)
            tokens.append(("ident", value))
            continue
        if char == "'":
            index = _skip_string(statement, index)
            tokens.append(("string", ""))
            continue
        if char.isascii() and (char.isalpha() or char == "_"):
            end = index + 1
            while end < length and (
                statement[end].isascii()
                and (statement[end].isalnum() or statement[end] in "_$")
            ):
                end += 1
            tokens.append(("word", statement[index:end]))
            index = end
            continue
        if char in "(),.;":
            tokens.append(("punct", char))
            index += 1
            continue
        tokens.append(("other", char))
        index += 1
    return tokens


def _scan_quoted(statement: str, index: int) -> tuple[str, int]:
    opener = statement[index]
    closer = "]" if opener == "[" else opener
    index += 1
    chars: list[str] = []
    while index < len(statement):
        if statement[index] == closer:
            if index + 1 < len(statement) and statement[index + 1] == closer:
                chars.append(closer)
                index += 2
                continue
            return "".join(chars), index + 1
        chars.append(statement[index])
        index += 1
    raise CatalogWriteBlocked(
        "연구 추출 앱은 식별자가 닫히지 않은 SQL의 쓰기 대상을 확인하지 못해 막습니다. "
        + _SEAWEED
    )


def _skip_string(statement: str, index: int) -> int:
    index += 1
    while index < len(statement):
        if statement[index] == "'":
            if index + 1 < len(statement) and statement[index + 1] == "'":
                index += 2
                continue
            return index + 1
        index += 1
    raise CatalogWriteBlocked(
        "연구 추출 앱은 문자열이 닫히지 않은 SQL의 쓰기 대상을 확인하지 못해 막습니다. "
        + _SEAWEED
    )


def _block_unknown(tokens: list[Token]) -> None:
    preview = " ".join(value for _kind, value in tokens[:8] if value)
    raise CatalogWriteBlocked(
        "연구 추출 앱은 SQL의 쓰기 대상을 확인하지 못해 막습니다: "
        f"{preview}. " + _SEAWEED
    )
