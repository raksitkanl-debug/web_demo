#!/usr/bin/env python3
"""
End-to-end Twitter news collector.

Default mode currently uses the sample CSV from summarymd so the paid
Twitter/X fetcher is not called while testing the pipeline.

Flow:
1. Get a CSV file (sample CSV by default, or twitter_fetcher_dialy.py with --live)
2. Send the CSV to summary.py to create summaryYYYYMMDD.md
3. Convert that Markdown summary to news/summary_YYYYMMDD.pdf
4. Send the PDF with call_pdf.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from markdown_renderer import render_markdown_body


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
WORKSPACE = SKILL_DIR.parent.parent
NEWS_DIR = Path("/Users/kumning/twitter/news")
SUMMARY_DIR = NEWS_DIR / "summary"
SUMMARY_PDF_DIR = NEWS_DIR / "summary_pdf"
LATEST_FETCH_FILE = NEWS_DIR / "latest_twitter_fetch.json"
DEFAULT_TEST_CSV = WORKSPACE / "skills" / "summarymd" / "summary_20260408.csv"
CHROME_CANDIDATES = [
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
]


def run_step(cmd: list[str], *, cwd: Path = SCRIPT_DIR, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    print(f"[collect] $ {' '.join(cmd)}", flush=True)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        env=env,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}")
    return result


def get_csv_date(csv_path: Path) -> str:
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_date = (row.get("Date (GMT+7)") or "").strip()
            if not raw_date:
                continue
            try:
                return datetime.strptime(raw_date, "%Y-%m-%d %H:%M").strftime("%Y%m%d")
            except ValueError:
                continue
    return datetime.now().strftime("%Y%m%d")


def copy_csv_to_news(source_csv: Path) -> tuple[Path, str]:
    if not source_csv.exists():
        raise FileNotFoundError(f"CSV not found: {source_csv}")

    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = get_csv_date(source_csv)
    destination = NEWS_DIR / f"summary_{date_str}.csv"
    if destination.exists() and source_csv.resolve() == destination.resolve():
        print(f"[collect] CSV already in place: {destination}")
        return destination, date_str

    shutil.copy2(source_csv, destination)
    print(f"[collect] CSV ready: {destination}")
    return destination, date_str


def collect_live_csv() -> tuple[Path, str]:
    print("[collect] Running twitter_fetcher_dialy.py...")
    run_step([sys.executable, "twitter_fetcher_dialy.py"], timeout=1800)

    if LATEST_FETCH_FILE.exists():
        with LATEST_FETCH_FILE.open(encoding="utf-8") as f:
            latest = json.load(f)
        run_csv = Path(latest.get("run_csv", "")).expanduser()
        date_str = latest.get("date") or datetime.now().strftime("%Y%m%d")
        if run_csv.exists():
            print(f"[collect] Latest run CSV ready: {run_csv}")
            return run_csv, date_str
        print(f"[collect] Latest run CSV from manifest was not found: {run_csv}")

    date_str = datetime.now().strftime("%Y%m%d")
    candidates = [
        NEWS_DIR / f"summary_{date_str}.csv",
        SCRIPT_DIR / f"summary_{date_str}.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return copy_csv_to_news(candidate)

    raise FileNotFoundError(
        "twitter_fetcher_dialy.py finished, but no summary CSV was found "
        f"for {date_str}."
    )


def summarize_csv(csv_path: Path, date_str: str) -> Path:
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    run_step([sys.executable, "summary.py", str(csv_path), str(SUMMARY_DIR)], timeout=2400)
    md_path = SUMMARY_DIR / f"summary{date_str}.md"
    if not md_path.exists():
        raise FileNotFoundError(f"summary.py did not create expected file: {md_path}")
    print(f"[collect] Markdown summary ready: {md_path}")
    return md_path


def run_mini_summary(csv_path: Path, date_str: str | None = None) -> Path:
    cmd = [sys.executable, "-u", "mini_summary.py", str(csv_path)]
    if date_str:
        cmd.extend(["--date", date_str])
    run_step(cmd, timeout=1200)

    # Let mini_summary infer the slot, then find the newest matching output.
    pattern = f"mini_{date_str}_*.md" if date_str else "mini_*.md"
    mini_dir = NEWS_DIR / "mini-summary"
    candidates = []
    if date_str:
        dated_dir = mini_dir / f"mini_{date_str}"
        candidates.extend(dated_dir.glob(pattern))
    candidates.extend(mini_dir.glob(pattern))
    candidates = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"mini_summary.py did not create an output in {mini_dir}")
    print(f"[collect] Mini summary ready: {candidates[0]}")
    return candidates[0]


def run_final_summary(date_str: str) -> Path:
    run_step([sys.executable, "final_summary.py", "--date", date_str], timeout=2400)
    md_path = SUMMARY_DIR / f"summary{date_str}.md"
    if not md_path.exists():
        raise FileNotFoundError(f"final_summary.py did not create expected file: {md_path}")
    print(f"[collect] Final summary ready: {md_path}")
    return md_path


def render_markdown_to_html(markdown_text: str) -> str:
    markdown_text = normalize_markdown_for_pdf(markdown_text)
    markdown_text = force_page_sections(markdown_text)
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


def normalize_markdown_for_pdf(markdown_text: str) -> str:
    text = markdown_text.replace("\r\n", "\n")

    # If the summary model emits numbered category headings, strip the numbers
    # so the PDF keeps a bullet/list style without numeric markers.
    text = re.sub(
        r"(?m)^(\d+)\.\s+(🌍|💼|🚀|🏢|⚽️)\s+",
        r"### \2 ",
        text,
    )
    return text


def force_page_sections(markdown_text: str) -> str:
    text = markdown_text.replace("\r\n", "\n")
    page_headings = [
        "# ข่าวต่างประเทศ (International News Catalog)",
        "# ข่าวต่างประเทศ (International News)",
        "# ข่าวภายในประเทศไทย (Thailand News)",
    ]
    seen_canonical_headings = set()
    for heading in page_headings:
        canonical_heading = (
            "# ข่าวต่างประเทศ"
            if heading.startswith("# ข่าวต่างประเทศ")
            else heading
        )
        if canonical_heading in seen_canonical_headings:
            continue

        updated_text, replacement_count = re.subn(
            rf"\n*{re.escape(heading)}",
            lambda match: f'\n\n<div class="page-break"></div>\n\n{match.group(0).strip()}',
            text,
            count=1,
        )
        if replacement_count:
            text = updated_text
            seen_canonical_headings.add(canonical_heading)
    return text


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
    chrome = find_chrome()
    run_step(
        [
            str(chrome),
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            str(html_path),
        ],
        timeout=600,
    )
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF was not created: {pdf_path}")

    print(f"[collect] PDF ready: {pdf_path}")
    return pdf_path


def send_pdf(pdf_path: Path, date_str: str) -> None:
    message = f"สรุปข่าวประจำวันที่ {date_str}"
    run_step([sys.executable, "call_pdf.py", str(pdf_path), message], timeout=90)


def resolve_input_csv(test_csv: str | None) -> Path:
    return Path(test_csv).expanduser() if test_csv else DEFAULT_TEST_CSV


def resolve_date(args: argparse.Namespace, csv_path: Path | None = None) -> str:
    if args.date:
        return args.date
    if csv_path and csv_path.exists():
        return get_csv_date(csv_path)
    return datetime.now().strftime("%Y%m%d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full Twitter news summary flow.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run twitter_fetcher_dialy.py instead of using the sample CSV.",
    )
    parser.add_argument(
        "--mini",
        action="store_true",
        help="Generate an hourly mini-summary with refs.",
    )
    parser.add_argument(
        "--final",
        action="store_true",
        help="Generate the final daily summary from mini-summaries.",
    )
    parser.add_argument(
        "--date",
        help="YYYYMMDD date for mini/final outputs.",
    )
    parser.add_argument(
        "--test-csv",
        help="CSV used for test/default mode.",
    )
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="Generate the PDF but do not send it with call_pdf.py.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.mini and args.final:
        raise ValueError("Use only one mode at a time: --mini or --final")

    if args.mini:
        if args.live:
            csv_path, fetched_date = collect_live_csv()
            date_str = args.date or fetched_date
        else:
            csv_path = resolve_input_csv(args.test_csv)
            date_str = resolve_date(args, csv_path)
        run_mini_summary(csv_path, date_str)
        print("[collect] Done.")
        return

    if args.final:
        csv_path = resolve_input_csv(args.test_csv) if args.test_csv else None
        date_str = resolve_date(args, csv_path)
        if args.test_csv:
            run_mini_summary(csv_path, date_str)
        md_path = run_final_summary(date_str)
        pdf_path = markdown_to_pdf(md_path, date_str)
        if args.no_send:
            print(f"[collect] --no-send enabled; not sending {pdf_path}")
        else:
            send_pdf(pdf_path, date_str)
        print("[collect] Done.")
        return

    if args.live:
        csv_path, date_str = collect_live_csv()
    else:
        print("[collect] Test mode: skipping twitter_fetcher_dialy.py")
        csv_path, date_str = copy_csv_to_news(resolve_input_csv(args.test_csv))

    md_path = summarize_csv(csv_path, date_str)
    pdf_path = markdown_to_pdf(md_path, date_str)

    if args.no_send:
        print(f"[collect] --no-send enabled; not sending {pdf_path}")
    else:
        send_pdf(pdf_path, date_str)

    print("[collect] Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[collect] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
