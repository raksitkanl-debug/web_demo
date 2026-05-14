#!/usr/bin/env python3
"""Render report markdown to HTML consistently across Python environments."""

from __future__ import annotations

import html
import re

try:
    import markdown
except ImportError:  # pragma: no cover - depends on runtime environment
    markdown = None


def render_markdown_body(markdown_text: str) -> str:
    if markdown is not None:
        return markdown.markdown(markdown_text, extensions=["tables", "fenced_code", "nl2br"])
    return render_basic_markdown(markdown_text)


def render_basic_markdown(markdown_text: str) -> str:
    """Small fallback renderer for the report format when python-markdown is absent."""
    blocks: list[str] = []
    paragraph: list[str] = []
    in_list = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append("<p>" + "<br />\n".join(paragraph) + "</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            blocks.append("</ul>")
            in_list = False

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            close_list()
            continue

        if stripped == '<div class="page-break"></div>':
            flush_paragraph()
            close_list()
            blocks.append(stripped)
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{render_inline(heading.group(2))}</h{level}>")
            continue

        bullet = re.match(r"^\*\s+(.+)$", stripped)
        if bullet:
            flush_paragraph()
            if not in_list:
                blocks.append("<ul>")
                in_list = True
            blocks.append(f"<li>{render_inline(bullet.group(1))}</li>")
            continue

        if in_list and line.startswith((" ", "\t")) and blocks and blocks[-1].endswith("</li>"):
            blocks[-1] = blocks[-1][:-5] + "<br />\n" + render_inline(stripped) + "</li>"
            continue

        close_list()
        paragraph.append(render_inline(stripped))

    flush_paragraph()
    close_list()
    return "\n".join(blocks)


def render_inline(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2">\1</a>',
        escaped,
    )

