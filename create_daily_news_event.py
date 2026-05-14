#!/usr/bin/env python3
"""Create a 30-minute Google Calendar event for today's Thai news report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import final_summary
import run_final_daily
import send_topic_report


THAI_MONTHS = [
    "",
    "มกราคม",
    "กุมภาพันธ์",
    "มีนาคม",
    "เมษายน",
    "พฤษภาคม",
    "มิถุนายน",
    "กรกฎาคม",
    "สิงหาคม",
    "กันยายน",
    "ตุลาคม",
    "พฤศจิกายน",
    "ธันวาคม",
]
DEFAULT_EMAIL_TO = "raksitkan.l@securitypitch.com"
#DEFAULT_EMAIL_CC: str | None = "raksitkan0072@gmail.com,pongpan.l@securitypitch.com"
DEFAULT_EMAIL_CC: str | None = "raksitkan.l@securitypitch.com,pakawat@securitypitch.com,patiwat.l@securitypitch.com,supanus.s@securitypitch.com,kraipanuch@gmail.com,pakorn.th@securitypitch.com"
DEFAULT_ATTENDEES = [
    "raksitkan.l@securitypitch.com",
    "pakawat@securitypitch.com",
    "patiwat@securitypitch.com",
    "supanus.s@securitypitch.com",
    "kraipanuch@gmail.com",
    "pakorn.th@securitypitch.com"
]


def thai_report_summary(now: datetime) -> str:
    thai_year = now.year + 543
    return f"รายงานข่าวประจำวันที่ {now.day} {THAI_MONTHS[now.month]} {thai_year}"


def create_event(calendar: str, dry_run: bool) -> int:
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    end = now + timedelta(minutes=10)
    summary = thai_report_summary(now)

    attendee_args = [
        arg
        for attendee in DEFAULT_ATTENDEES
        for arg in ("--attendee", attendee)
    ]

    cmd = [
        "gws",
        "calendar",
        "+insert",
        "--calendar",
        calendar,
        "--summary",
        summary,
        "--start",
        now.isoformat(timespec="seconds"),
        "--end",
        end.isoformat(timespec="seconds"),
        *attendee_args,
        "--format",
        "json",
    ]
    
    if dry_run:
        print(json.dumps({"command": cmd, "summary": summary}, ensure_ascii=False, indent=2))
        return 0

    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def daily_pdf_path(date_str: str) -> Path:
    return run_final_daily.SUMMARY_PDF_DIR / f"summary_{date_str}.pdf"


def send_email(
    *,
    to: str,
    cc: str | None,
    subject: str,
    body: str,
    pdf_path: Path,
    dry_run: bool,
    html_body: bool = False,
) -> int:
    if not pdf_path.exists():
        raise FileNotFoundError(
            f"ไม่พบไฟล์ PDF สำหรับแนบอีเมล: {pdf_path}\n"
            "ให้รัน run_final_daily.py เพื่อสร้าง PDF ของวันนั้นก่อน"
        )

    cmd = [
        "gws",
        "gmail",
        "+send",
        "--to",
        to,
        "--subject",
        subject,
        "--body",
        body,
        "--attach",
        pdf_path.name,
        "--format",
        "json",
    ]
    if cc:
        cmd.extend(["--cc", cc])
    if html_body:
        cmd.append("--html")
    if dry_run:
        cmd.append("--dry-run")

    result = subprocess.run(cmd, text=True, capture_output=True, cwd=pdf_path.parent)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def send_daily_news_email(
    *,
    date_str: str,
    to: str = DEFAULT_EMAIL_TO,
    cc: str | None = DEFAULT_EMAIL_CC,
    dry_run: bool = False,
) -> int:
    subject = f"รายงานข่าวประจำวันที่ {final_summary.thai_date(date_str)}"
    body = send_topic_report.build_topic_html_message(date_str)
    return send_email(
        to=to,
        cc=cc,
        subject=subject,
        body=body,
        pdf_path=daily_pdf_path(date_str),
        dry_run=dry_run,
        html_body=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create today's Thai news report calendar event.")
    parser.add_argument("--calendar", default="primary", help="Calendar ID to create the event in.")
    parser.add_argument("--dry-run", action="store_true", help="Print the gws command without creating an event.")
    parser.add_argument("--date", default=run_final_daily.default_report_date(), help="YYYYMMDD date for email body/PDF.")
    parser.add_argument("--email-only", action="store_true", help="Send only email and skip calendar event creation.")
    parser.add_argument("--to", default=DEFAULT_EMAIL_TO, help="Email recipient(s), comma-separated.")
    parser.add_argument("--cc", default=DEFAULT_EMAIL_CC, help="Email CC recipient(s), comma-separated. Use '' to skip.")
    args = parser.parse_args()

    if not args.email_only:
        event_code = create_event(args.calendar, args.dry_run)
        if event_code != 0:
            return event_code

    cc = args.cc or None
    return send_daily_news_email(date_str=args.date, to=args.to, cc=cc, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
