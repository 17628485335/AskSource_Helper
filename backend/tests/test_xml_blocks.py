from app.xml_blocks import join_blocks, xml_block


def test_xml_block_wraps_parts_with_tag():
    assert xml_block("soul", "行为准则", "简洁回答") == (
        "<soul>\n行为准则\n简洁回答\n</soul>"
    )


def test_xml_block_skips_blank_parts():
    assert xml_block("soul", "行为准则", None, "  ", "") == "<soul>\n行为准则\n</soul>"


def test_xml_block_inline_is_single_line():
    assert xml_block("time", "今天是 2026-01-01 周四（北京时间）。", inline=True) == (
        "<time>今天是 2026-01-01 周四（北京时间）。</time>"
    )


def test_join_blocks_separates_with_blank_lines():
    assert join_blocks("<a>\nA\n</a>", None, "<b>\nB\n</b>", "") == (
        "<a>\nA\n</a>\n\n<b>\nB\n</b>"
    )
