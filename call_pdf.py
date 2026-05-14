#!/usr/bin/env python3
"""
Send a summary PDF to Telegram.

Defaults to today's PDF:
  /Users/kumning/twitter/news/summary_pdf/summary_YYYYMMDD.pdf
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


TELEGRAM_TARGET = "-1003897149692"
SUMMARY_PDF_DIR = Path("/Users/kumning/twitter/news/summary_pdf")
THAI_MONTHS = {
    "01": "มกราคม",
    "02": "กุมภาพันธ์",
    "03": "มีนาคม",
    "04": "เมษายน",
    "05": "พฤษภาคม",
    "06": "มิถุนายน",
    "07": "กรกฎาคม",
    "08": "สิงหาคม",
    "09": "กันยายน",
    "10": "ตุลาคม",
    "11": "พฤศจิกายน",
    "12": "ธันวาคม",
}


def today_date() -> str:
    return datetime.now().strftime("%Y%m%d")


def thai_date(date_str: str) -> str:
    if len(date_str) != 8 or not date_str.isdigit():
        return date_str
    return f"{int(date_str[6:8])} {THAI_MONTHS.get(date_str[4:6], date_str[4:6])} {int(date_str[:4]) + 543}"


def default_pdf_path(date_str: str) -> Path:
    return SUMMARY_PDF_DIR / f"summary_{date_str}.pdf"


def resolve_pdf_path(pdf_arg: str | None, date_str: str) -> Path:
    if not pdf_arg:
        return default_pdf_path(date_str)

    expanded = Path(os.path.expanduser(pdf_arg))
    if expanded.exists():
        return expanded

    fallback = SUMMARY_PDF_DIR / expanded.name
    if fallback.exists():
        return fallback

    return expanded


def send_pdf(pdf_path: Path, message: str) -> bool:
    if not pdf_path.exists():
        print(f"❌ ไม่พบไฟล์ PDF: {pdf_path}")
        print(f"   ตรวจสอบใน: {SUMMARY_PDF_DIR}")
        return False

    cmd = [
        "openclaw",
        "message",
        "send",
        "--channel",
        "telegram",
        "--target",
        TELEGRAM_TARGET,
        "--media",
        str(pdf_path),
        "--message",
        message,
    ]

    print(f"📤 กำลังส่งไฟล์: {pdf_path}")
    print(f"💬 ข้อความ: {message}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print("✅ ส่งไฟล์สำเร็จ!")
            return True
        print(f"❌ ผิดพลาด: {result.stderr}")
        return False
    except subprocess.TimeoutExpired:
        print("❌ คำสั่งใช้เวลานานเกินไป (timeout)")
        return False
    except Exception as exc:
        print(f"❌ ผิดพลาด: {exc}")
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send daily summary PDF to Telegram.")
    parser.add_argument("pdf_path", nargs="?", help="PDF path or filename. Defaults to today's summary PDF.")
    parser.add_argument("message", nargs="?", help="Telegram message. Defaults to Thai date message.")
    parser.add_argument("--date", default=today_date(), help="YYYYMMDD date. Defaults to today.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = resolve_pdf_path(args.pdf_path, args.date)
    message = args.message or f"รายงานข่าวประจำวันที่ {thai_date(args.date)}"
    if not send_pdf(pdf_path, message):
        sys.exit(1)


if __name__ == "__main__":
    main()
