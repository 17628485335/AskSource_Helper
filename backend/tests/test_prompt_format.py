from datetime import datetime

from app.prompt import (
    LOCAL_TZ,
    build_system_prompt,
    compute_prompt_hash,
    section_header,
    strip_trailing_date,
)


def test_sections_wrapped_in_xml_tags_with_blank_lines():
    result = build_system_prompt(
        "基础提示词",
        sections=[
            ("soul", "policy", "简洁回答", "行为准则"),
            ("identity", "anchor", "你是助手", "身份锚点"),
        ],
        now=datetime(2026, 1, 1, tzinfo=LOCAL_TZ),
    )
    assert result == (
        "基础提示词\n\n"
        "<soul>\n简洁回答\n</soul>\n\n"
        "<identity>\n你是助手\n</identity>"
    )
    assert "行为准则" not in result
    assert "身份锚点" not in result


def test_section_header_uses_lowercase_tag():
    assert section_header("soul", "policy", "行为准则") == "<soul>\n</soul>"


def test_rebuild_is_idempotent_and_accepts_legacy_brackets():
    once = build_system_prompt(
        "",
        sections=[("soul", "policy", "内容", "准则")],
        now=datetime(2026, 1, 1, tzinfo=LOCAL_TZ),
    )
    twice = build_system_prompt(
        once,
        sections=[("soul", "policy", "内容", "准则")],
        now=datetime(2026, 1, 1, tzinfo=LOCAL_TZ),
    )
    assert twice == once

    legacy = "[SOUL] 准则\n内容\n\n<time>今天是 2026-01-01 周四（北京时间）。</time>"
    rebuilt = build_system_prompt(
        legacy,
        sections=[("soul", "policy", "内容", "准则")],
        now=datetime(2026, 1, 1, tzinfo=LOCAL_TZ),
    )
    assert rebuilt == once


def test_strip_date_handles_both_xml_and_legacy_formats():
    new = "基础提示词\n\n<time>今天是 2026-01-01 周四（北京时间）。</time>"
    old = "基础提示词\n\n今天是 2026-01-01 周四（北京时间）。"
    assert strip_trailing_date(new) == "基础提示词"
    assert strip_trailing_date(old) == "基础提示词"
    assert compute_prompt_hash(new) == compute_prompt_hash(old)
