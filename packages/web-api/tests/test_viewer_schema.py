"""Viewer 블록 스키마 테스트."""

from __future__ import annotations

from app.schemas.viewer import ContentBlock, HeadingBlock, SectionContent, TableBlock


def test_section_content_accepts_discriminated_blocks() -> None:
    section = SectionContent(
        entry_id="e_1",
        source="body",
        blocks=[
            {"type": "heading", "level": 2, "text": "재무상태표"},
            {"type": "paragraph", "text": "자산총계는 다음과 같다."},
            {
                "type": "table",
                "headers": ["과목", "당기"],
                "rows": [["자산총계", "1,000"]],
            },
        ],
    )

    assert isinstance(section.blocks[0], HeadingBlock)
    assert section.blocks[0].level == 2
    assert section.blocks[1].text == "자산총계는 다음과 같다."
    assert isinstance(section.blocks[2], TableBlock)
    assert section.blocks[2].rows[0][1] == "1,000"


def test_content_block_union_roundtrip() -> None:
    raw = {"type": "heading", "level": 1, "text": "제목"}
    block: ContentBlock = HeadingBlock.model_validate(raw)
    assert block.model_dump() == raw
