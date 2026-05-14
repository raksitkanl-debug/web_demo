#!/usr/bin/env python3
"""
Send a compact Telegram text report extracted from the final daily markdown.

Defaults to today's system date in YYYYMMDD format.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import final_summary


TELEGRAM_TARGET = "-1003897149692"
SCRIPT_DIR = Path(__file__).resolve().parent
NEWS_DIR = Path(os.getenv("NEWS_DIR", "/Users/kumning/twitter/news"))
SUMMARY_DIR = NEWS_DIR / "summary"
MAX_MESSAGE_CHARS = 3900
TOPIC_SEPARATOR = "=" * 28
NEWS_SEPARATOR = "—"


def today_date() -> str:
    return datetime.now().strftime("%Y%m%d")


def strip_markdown_links(text: str) -> str:
    text = re.sub(r"\[🔗\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("🔗", "")
    return re.sub(r"\s+", " ", text).strip()


def clean_source_label(source: str) -> str:
    source = strip_markdown_links(source)
    source = re.sub(r"\s+", " ", source).strip(" ;,")
    return source


def summarize_sources(source_text: str, max_sources: int = 1) -> str:
    sources = []
    seen = set()
    for source in re.split(r"\s*;\s*", source_text):
        source = clean_source_label(source)
        if not source or source in seen:
            continue
        seen.add(source)
        sources.append(source)

    if not sources:
        return ""

    selected = sources[:max_sources]
    remaining = len(sources) - len(selected)
    source_display = ", ".join(selected)
    if remaining > 0:
        source_display += f" และอีก {remaining} แหล่ง"
    return source_display


def split_news_and_source(text: str) -> tuple[str, str]:
    text = strip_markdown_links(text)
    if "ที่มา:" not in text:
        return text, ""

    news, source = text.split("ที่มา:", 1)
    return news.strip(), summarize_sources(source)


def format_topic_heading(line: str, fallback_number: int) -> str:
    heading = strip_markdown_links(line.lstrip("# ").strip())
    match = re.match(r"TOPIC\s*#?(\d+)\s*:\s*(.+)", heading, flags=re.IGNORECASE)
    if match:
        return f"ประเด็นที่ {match.group(1)}: {match.group(2).strip()}"

    heading = re.sub(r"^TOPIC\s*:?\s*", "", heading, flags=re.IGNORECASE).strip()
    return f"ประเด็นที่ {fallback_number}: {heading}"


def summary_path(date_str: str) -> Path:
    return SUMMARY_DIR / f"summary{date_str}.md"


def collect_section(lines: list[str], start_pattern: str, stop_pattern: str) -> list[str]:
    collected = []
    in_section = False
    for line in lines:
        if re.match(start_pattern, line):
            in_section = True
            continue
        if in_section and re.match(stop_pattern, line):
            break
        if in_section:
            collected.append(line)
    return collected


def build_topic_message(date_str: str) -> str:
    path = summary_path(date_str)
    if not path.exists():
        raise FileNotFoundError(f"ไม่พบไฟล์ final summary: {path}")

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    title = next((line.lstrip("# ").strip() for line in lines if line.startswith("# ")), "")
    executive_lines = collect_section(lines, r"^## บทสรุปผู้บริหาร", r"^## ")
    topic_lines = collect_section(lines, r"^## ประเด็นวิเคราะห์สำคัญ", r"^# ข่าวต่างประเทศ")

    output = []
    if title:
        output.append(title.replace("ประจำวันที่", " ประจำวันที่"))
    else:
        output.append(f"รายงานข่าวเชิงกลยุทธ์ ประจำวันที่ {final_summary.thai_date(date_str)}")
    output.append("")

    executive = " ".join(strip_markdown_links(line) for line in executive_lines if line.strip())
    if executive:
        output.append("บทสรุปผู้บริหาร")
        output.append(executive[:900])
        output.append("")

    output.append("ประเด็นวิเคราะห์สำคัญ")
    topic_count = 0
    news_count = 0
    for line in topic_lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("### TOPIC"):
            topic_count += 1
            news_count = 0
            output.append("")
            output.append(format_topic_heading(line, topic_count))
            output.append(TOPIC_SEPARATOR)
            continue
        if line.startswith("นัยสำคัญ:"):
            output.append(strip_markdown_links(line))
            output.append(NEWS_SEPARATOR)
            continue
        if line.startswith("* "):
            news_count += 1
            news, source = split_news_and_source(line[2:])
            output.append(f"ข่าวที่ {news_count}: {news}")
            if source:
                output.append(f"ที่มา: {source}")
            output.append(NEWS_SEPARATOR)

    while output and output[-1] == NEWS_SEPARATOR:
        output.pop()

    message = "\n".join(output).strip()
    if len(message) > MAX_MESSAGE_CHARS:
        message = message[: MAX_MESSAGE_CHARS - 20].rstrip() + "\n"
    return message


def emphasize_label(line: str, label_pattern: str) -> str:
    match = re.match(label_pattern, line)
    if not match:
        return html.escape(line)

    label = html.escape(match.group(1))
    body = html.escape(match.group(2).strip())
    if body:
        return f"<strong>{label}</strong> {body}"
    return f"<strong>{label}</strong>"


def build_topic_html_message(date_str: str) -> str:
    """Build an HTML email body with bold/italic styling like the PDF example."""
    text = build_topic_message(date_str)
    parts: list[str] = []
    in_topic = False
    pending_topic_heading = ""
    just_added_topic_section = False
    just_added_news_separator = False
    pending_topic_after_separator = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if just_added_topic_section or just_added_news_separator:
                continue
            if parts and parts[-1] != "<br>":
                parts.append("<br>")
            continue

        just_added_topic_section = False

        if line == NEWS_SEPARATOR:
            parts.append("<div style=\"line-height:1.4;\">&mdash;</div>")
            just_added_news_separator = True
            continue

        if line == TOPIC_SEPARATOR:
            if pending_topic_heading:
                topic_margin_top = "10px" if pending_topic_after_separator else "18px"
                parts.append(
                    f"<p style=\"margin:{topic_margin_top} 0 4px;\"><strong>{html.escape(pending_topic_heading)}</strong><br>"
                    f"{html.escape(TOPIC_SEPARATOR)}</p>"
                )
                pending_topic_heading = ""
                pending_topic_after_separator = False
            else:
                parts.append(f"<div>{html.escape(TOPIC_SEPARATOR)}</div>")
            continue

        if line.startswith("รายงานข่าวเชิงกลยุทธ์"):
            title = html.escape(line)
            title = title.replace(
                " ประจำวันที่ ",
                " <em>ประจำวันที่ ",
                1,
            )
            if "<em>" in title:
                title += "</em>"
            parts.append(f"<p style=\"margin:0 0 18px;\"><strong>{title}</strong></p>")
            continue

        if line in {"บทสรุปผู้บริหาร", "ประเด็นวิเคราะห์สำคัญ"}:
            in_topic = line == "ประเด็นวิเคราะห์สำคัญ"
            margin = "22px 0 6px" if in_topic else "0 0 4px"
            parts.append(f"<p style=\"margin:{margin};\"><strong>{html.escape(line)}</strong></p>")
            just_added_topic_section = in_topic
            continue

        if line.startswith("ประเด็นที่ "):
            pending_topic_heading = line
            pending_topic_after_separator = just_added_news_separator
            just_added_news_separator = False
            continue

        just_added_news_separator = False

        if line.startswith("นัยสำคัญ:"):
            formatted_line = emphasize_label(line, r"^(นัยสำคัญ:)(.*)$")
            parts.append(
                f"<p style=\"margin:4px 0;\">"
                f"{formatted_line}"
                f"</p>"
            )
            continue

        if re.match(r"^ข่าวที่ \d+:", line):
            formatted_line = emphasize_label(line, r"^(ข่าวที่ \d+:)(.*)$")
            parts.append(
                f"<p style=\"margin:6px 0 0;\">"
                f"{formatted_line}"
                f"</p>"
            )
            continue

        if line.startswith("ที่มา:"):
            formatted_line = emphasize_label(line, r"^(ที่มา:)(.*)$")
            parts.append(
                f"<div style=\"margin:0 0 2px;\">"
                f"{formatted_line}"
                f"</div>"
            )
            continue

        paragraph_margin = "0 0 14px" if not in_topic else "4px 0"
        parts.append(f"<p style=\"margin:{paragraph_margin};\">{html.escape(line)}</p>")

    body = "\n".join(parts)
    return f"<div style=\"font-family:Arial,'Noto Sans Thai',sans-serif;font-size:15px;line-height:1.45;color:#202124;\">{body}</div>"


def send_message(message: str) -> bool:
    try:
        from hermes_send import send_telegram
    except ImportError:
        cmd = [
            "openclaw",
            "message",
            "send",
            "--channel",
            "telegram",
            "--target",
            TELEGRAM_TARGET,
            "--message",
            message,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode == 0

    return send_telegram(TELEGRAM_TARGET, message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send topic text report from final markdown.")
    parser.add_argument("--date", default=today_date(), help="YYYYMMDD date. Defaults to today.")
    parser.add_argument("--dry-run", action="store_true", help="Print message instead of sending.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    message = build_topic_message(args.date)
    if args.dry_run:
        print(message)
        return
    if not send_message(message):
        raise RuntimeError("ส่งข้อความ Telegram ไม่สำเร็จ")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[topic-report] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
