"""DART 상세페이지 목차(treeData)에서 감리결과 섹션을 고른다.

entry-extractor의 extractTree와 같이 main.do 스크립트의 node 대입을 순서대로 읽는다.
부모 노드의 viewer.do는 하위 절과 표를 포함하므로, 로마 숫자 절 노드만 고른다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_TOC_STMT = re.compile(
    r"var\s+node(\d+)\s*=\s*\{\s*\};"
    r"|node(\d+)\['(\w+)'\]\s*=\s*\"((?:\\.|[^\"\\])*)\""
    r"|node(\d+)\['children'\]\s*=\s*\[\s*\]"
    r"|node(\d+)\['children'\]\.push\(node(\d+)\)"
    r"|treeData\.push\(node(\d+)\)"
)
_JS_ESCAPES = {
    r"\n": "\n",
    r"\r": "\r",
    r"\t": "\t",
    r"\\": "\\",
    r"\"": '"',
    r"\'": "'",
}
_PUNCT = re.compile(
    r"[\s\u00a0\u3000\.．。·ㆍ,，:：;；\-–—_~'\"“”‘’()（）\[\]{}【】「」『』<>〈〉/]+"
)
# 긴 토큰을 먼저 맞춰 VIII가 VI로 잘리지 않게 한다.
_ROMAN_VALUES: tuple[tuple[str, int], ...] = (
    ("XII", 12),
    ("XI", 11),
    ("X", 10),
    ("IX", 9),
    ("VIII", 8),
    ("VII", 7),
    ("VI", 6),
    ("V", 5),
    ("IV", 4),
    ("III", 3),
    ("II", 2),
    ("I", 1),
)
_VALUE_TO_ROMAN = {value: token for token, value in _ROMAN_VALUES}
_CHAPTER = re.compile(r"^제(\d{1,2})(?:장|절|항)")
_ARABIC = re.compile(r"^(\d{1,2})(?!\d)")
_SPACES = re.compile(r"[\s\u00a0\u3000]+")
_DART_LETTER_GAP = re.compile(
    r"([\uac00-\ud7a3A-Za-z0-9])[ \t\u00a0\u3000]+(?=[\uac00-\ud7a3A-Za-z0-9(])"
)
_VIEWER_BASE = "https://dart.fss.or.kr/report/viewer.do"
_MAIN_BASE = "https://dart.fss.or.kr/dsaf001/main.do"


@dataclass
class TocNode:
    """목차 노드 하나. children은 문서 순서다."""

    title: str
    depth: int
    rcp_no: str
    dcm_no: str
    ele_id: str | None = None
    offset: str | None = None
    length: str | None = None
    dtd: str | None = None
    children: list[TocNode] = field(default_factory=list)

    @property
    def viewer_url(self) -> str:
        """viewDoc()과 같은 순서로 viewer.do 주소를 만든다."""
        parts = [f"rcpNo={self.rcp_no}", f"dcmNo={self.dcm_no}"]
        if self.ele_id is not None:
            parts.append(f"eleId={self.ele_id}")
        if self.offset is not None:
            parts.append(f"offset={self.offset}")
        if self.length is not None:
            parts.append(f"length={self.length}")
        if self.dtd is not None:
            parts.append(f"dtd={self.dtd}")
        return f"{_VIEWER_BASE}?{'&'.join(parts)}"


def disclosure_main_url(rcept_no: str, disclosure_url: str | None) -> str:
    """카탈로그의 상세 주소가 있으면 쓰고, 없으면 접수번호로 main.do를 만든다."""
    if disclosure_url and disclosure_url.strip():
        url = disclosure_url.strip()
        if url.startswith("/"):
            return f"https://dart.fss.or.kr{url}"
        return url
    return f"{_MAIN_BASE}?rcpNo={rcept_no}"


def compact_title(text: str) -> str:
    """제목 비교용으로 호환 문자를 펼치고 공백·문장부호를 뺀다."""
    normalized = unicodedata.normalize("NFKC", text or "")
    return _PUNCT.sub("", normalized).upper()


def section_number(code: str) -> int | None:
    """섹션 코드가 로마 숫자나 정수면 그 값을 반환한다. 예: VI, Ⅵ, 6 → 6."""
    compact = compact_title(code)
    if not compact:
        return None
    if compact.isdigit():
        return int(compact)
    for token, value in _ROMAN_VALUES:
        if compact == token:
            return value
    return None


def canonical_section_code(code: str) -> str:
    """저장 키로 쓸 섹션 코드. 1–12는 ASCII 로마 숫자로 통일한다."""
    number = section_number(code)
    if number is not None and number in _VALUE_TO_ROMAN:
        return _VALUE_TO_ROMAN[number]
    collapsed = unicodedata.normalize("NFKC", code or "").strip().upper()
    return collapsed


def display_title(text: str) -> str:
    """목차 제목을 저장용으로 정리한다. 글자 사이 공백이 많으면 붙인다."""
    collapsed = _SPACES.sub(" ", unicodedata.normalize("NFC", text or "")).strip()
    if not collapsed:
        return ""
    tokens = collapsed.split(" ")
    single = 0
    for token in tokens:
        core = re.sub(r"[()\[\]{}]", "", token)
        if len(core) <= 1:
            single += 1
    if single / max(len(tokens), 1) < 0.5:
        return collapsed
    return _DART_LETTER_GAP.sub(r"\1", collapsed)


def title_matches(title: str, section_code: str, *, depth: int) -> bool:
    """요청한 절 번호의 감리 제목인지 판별한다.

    로마 숫자(Ⅵ, VI, 전각 ＶＩ), `제6장`, 최상위 아라비아 숫자, 번호 없는
    `감리결과`를 맞춘다. `1. 감사보고서 감리결과` 같은 하위 절은 제외한다.
    """
    compact = compact_title(title)
    if "감리" not in compact:
        return False
    target = section_number(section_code)
    if target is None:
        needle = compact_title(section_code)
        return bool(needle) and needle in compact
    roman = _leading_roman(compact)
    if roman == target:
        return True
    chapter = _CHAPTER.match(compact)
    if chapter is not None and int(chapter.group(1)) == target:
        return True
    if depth == 1 and roman is None and chapter is None:
        arabic = _ARABIC.match(compact)
        if arabic is not None and int(arabic.group(1)) == target:
            return True
        if arabic is None and "감리결과" in compact:
            return True
    return False


def parse_toc(html: str) -> list[TocNode]:
    """상세페이지 HTML에서 최상위 목차 노드를 읽는다. 실패하면 빈 목록이다."""
    current: dict[str, dict[str, object]] = {}
    roots: list[dict[str, object]] = []
    for match in _TOC_STMT.finditer(html or ""):
        if match.group(1):
            current[match.group(1)] = {
                "depth": int(match.group(1)),
                "props": {},
                "children": [],
            }
            continue
        if match.group(2):
            node = current.get(match.group(2))
            if node is not None:
                props = node["props"]
                assert isinstance(props, dict)
                props[match.group(3)] = _unescape_js(match.group(4))
            continue
        if match.group(5):
            node = current.get(match.group(5))
            if node is not None:
                node["children"] = []
            continue
        if match.group(6):
            parent = current.get(match.group(6))
            child = current.get(match.group(7))
            if parent is not None and child is not None:
                children = parent["children"]
                assert isinstance(children, list)
                children.append(child)
            continue
        if match.group(8):
            node = current.get(match.group(8))
            if node is None:
                continue
            props = node["props"]
            assert isinstance(props, dict)
            if props.get("rcpNo") and props.get("dcmNo"):
                roots.append(node)
    return [_to_node(raw) for raw in roots]


def find_section(roots: list[TocNode], section_code: str) -> TocNode | None:
    """감리 절을 고른다. 더 얕은 노드, 그다음 본문이 긴 노드, 같으면 뒤 노드."""
    matches = [
        node
        for node in _preorder(roots)
        if title_matches(node.title, section_code, depth=node.depth)
    ]
    if not matches:
        return None
    shallowest = min(node.depth for node in matches)
    layer = [node for node in matches if node.depth == shallowest]
    longest = max(_span_length(node) for node in layer)
    tied = [node for node in layer if _span_length(node) == longest]
    return tied[-1]


def _leading_roman(compact: str) -> int | None:
    """제목 앞의 로마 숫자 값을 읽는다. 뒤에 영문이 이어지면 숫자가 아니다."""
    for token, value in _ROMAN_VALUES:
        if not compact.startswith(token):
            continue
        rest = compact[len(token) :]
        if rest[:1].isascii() and rest[:1].isalpha():
            continue
        return value
    return None


def _unescape_js(value: str) -> str:
    """목차 문자열의 단순 이스케이프를 푼다."""

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith("\\u"):
            return chr(int(token[2:], 16))
        return _JS_ESCAPES.get(token, token)

    return re.sub(r"\\u[0-9a-fA-F]{4}|\\.", replace, value)


def _to_node(raw: dict[str, object]) -> TocNode:
    """파서 딕셔너리를 TocNode로 바꾼다."""
    props = raw["props"]
    children = raw["children"]
    assert isinstance(props, dict)
    assert isinstance(children, list)
    depth = raw["depth"]
    assert isinstance(depth, int)
    return TocNode(
        title=str(props.get("text") or ""),
        depth=depth,
        rcp_no=str(props.get("rcpNo") or ""),
        dcm_no=str(props.get("dcmNo") or ""),
        ele_id=_optional_str(props.get("eleId")),
        offset=_optional_str(props.get("offset")),
        length=_optional_str(props.get("length")),
        dtd=_optional_str(props.get("dtd")),
        children=[_to_node(child) for child in children],
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def _preorder(nodes: list[TocNode]) -> list[TocNode]:
    ordered: list[TocNode] = []
    for node in nodes:
        ordered.append(node)
        ordered.extend(_preorder(node.children))
    return ordered


def _span_length(node: TocNode) -> int:
    try:
        return int(node.length or "0")
    except ValueError:
        return 0
