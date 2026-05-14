#!/usr/bin/env python3
"""
Build the final daily news summary, render it to PDF, and optionally send it.

Defaults to today's system date in YYYYMMDD format.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import final_summary
import send_topic_report
from markdown_renderer import render_markdown_body


NEWS_DIR = Path("/Users/kumning/twitter/news")
SUMMARY_PDF_DIR = NEWS_DIR / "summary_pdf"
CHROME_CANDIDATES = [
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
]


def today_date() -> str:
    return datetime.now().strftime("%Y%m%d")


def default_report_date() -> str:
    # Final daily closes the report for today. Hourly jobs intentionally write
    # into tomorrow's report folder after the 09:00 cycle starts, but the final
    # job normally runs around 09:00 to summarize today's just-closed folder.
    return today_date()


def run_step(cmd: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    print(f"[final-daily] $ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}")
    return result


def normalize_markdown_for_pdf(markdown_text: str) -> str:
    text = markdown_text.replace("\r\n", "\n")
    return re.sub(r"(?m)^(\d+)\.\s+(🌍|💼|🚀|🏢|⚽️)\s+", r"### \2 ", text)


def force_page_sections(markdown_text: str) -> str:
    text = markdown_text.replace("\r\n", "\n")
    page_headings = [
        "# ข่าวต่างประเทศ (International News Catalog)",
        "# ข่าวต่างประเทศ (International News)",
        "# ข่าวภายในประเทศไทย (Thailand News)",
    ]
    seen_canonical_headings = set()
    for heading in page_headings:
        canonical_heading = "# ข่าวต่างประเทศ" if heading.startswith("# ข่าวต่างประเทศ") else heading
        if canonical_heading in seen_canonical_headings:
            continue
        updated_text, count = re.subn(
            rf"\n*{re.escape(heading)}",
            lambda match: f'\n\n<div class="page-break"></div>\n\n{match.group(0).strip()}',
            text,
            count=1,
        )
        if count:
            text = updated_text
            seen_canonical_headings.add(canonical_heading)
    return text


def render_markdown_to_html(markdown_text: str) -> str:
    markdown_text = force_page_sections(normalize_markdown_for_pdf(markdown_text))
    body = render_markdown_body(markdown_text)

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    @page {{ size: A4; margin: 18mm 14mm; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
      color: #202124;
      line-height: 1.55;
      font-size: 13px;
    }}
    h1, h2, h3 {{ color: #0b3d6e; margin: 18px 0 8px; }}
    h1 {{ font-size: 24px; border-bottom: 2px solid #0b3d6e; padding-bottom: 8px; }}
    h2 {{ font-size: 18px; border-bottom: 1px solid #d9e2ec; padding-bottom: 5px; }}
    h3 {{ font-size: 15px; }}
    p {{ margin: 7px 0; }}
    ul, ol {{ padding-left: 22px; }}
    ol {{ list-style-type: disc; }}
    li {{ margin: 5px 0; }}
    a {{ color: #1259a7; text-decoration: none; overflow-wrap: anywhere; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 11px; }}
    th, td {{ border: 1px solid #d8dee4; padding: 6px; vertical-align: top; }}
    th {{ background: #f3f6f9; }}
    pre {{ white-space: pre-wrap; background: #f6f8fa; padding: 10px; border-radius: 4px; }}
    .page-break {{
      break-before: page;
      page-break-before: always;
      margin-top: 0;
      padding-top: 0;
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def find_chrome() -> Path:
    for candidate in CHROME_CANDIDATES:
        if candidate.exists():
            return candidate
    for name in ("google-chrome", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise FileNotFoundError("Google Chrome/Chromium was not found for PDF rendering.")


def markdown_to_pdf(md_path: Path, date_str: str) -> Path:
    SUMMARY_PDF_DIR.mkdir(parents=True, exist_ok=True)
    html_path = SUMMARY_PDF_DIR / f"summary_{date_str}.html"
    pdf_path = SUMMARY_PDF_DIR / f"summary_{date_str}.pdf"
    html_path.write_text(render_markdown_to_html(md_path.read_text(encoding="utf-8")), encoding="utf-8")

    run_step(
        [
            str(find_chrome()),
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            str(html_path),
        ],
        timeout=3600,
    )
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF was not created: {pdf_path}")
    print(f"[final-daily] PDF ready: {pdf_path}")
    return pdf_path


def debug_inputs(date_str: str) -> None:
    mini_dir = final_summary.MINI_DIR / f"mini_{date_str}"
    manifest_path = final_summary.manifest_path(date_str)
    all_paths = sorted(mini_dir.glob(f"mini_{date_str}_*.md")) if mini_dir.exists() else []
    used = final_summary.read_mini_summaries(date_str)
    used_paths = {path for path, _ in used}

    print(f"[final-daily] date: {date_str}")
    print(f"[final-daily] mini dir: {mini_dir}")
    print(f"[final-daily] manifest: {manifest_path} ({'exists' if manifest_path.exists() else 'missing'})")
    print(f"[final-daily] mini files found: {len(all_paths)}")
    for path in all_paths:
        status = "USE" if path in used_paths else "SKIP"
        reason = "" if status == "USE" else " (empty/no-news marker)"
        size = path.stat().st_size
        print(f"[final-daily] {status} {path.name} ({size} bytes){reason}")
    print(f"[final-daily] mini files used: {len(used)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate final daily summary and PDF.")
    parser.add_argument(
        "--date",
        default=default_report_date(),
        help="YYYYMMDD date. Defaults to today's system date.",
    )
    parser.add_argument("--no-send", action="store_true", help="Create files but do not send PDF.")
    parser.add_argument(
        "--debug-inputs",
        action="store_true",
        help="Print the mini-summary files that would be used, then exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.debug_inputs:
        debug_inputs(args.date)
        return

    md_path = final_summary.build_final_summary(args.date)
    pdf_path = markdown_to_pdf(md_path, args.date)

    if args.no_send:
        print(f"[final-daily] --no-send enabled; not sending {pdf_path}")
        return

    topic_message = send_topic_report.build_topic_message(args.date)
    if not send_topic_report.send_message(topic_message):
        raise RuntimeError("ส่งข้อความสรุป Telegram ไม่สำเร็จ")

    message = f"รายงานข่าวประจำวันที่ {final_summary.thai_date(args.date)}"
    run_step([sys.executable, str(Path(__file__).with_name("call_pdf.py")), str(pdf_path), message], timeout=90)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[final-daily] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
