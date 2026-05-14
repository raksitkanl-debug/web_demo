#!/usr/bin/env python3
"""
Fetch new Twitter/X posts for this run and generate one hourly mini-summary.

The fetcher writes a per-run CSV under:
  /Users/kumning/twitter/news/YYYYMMDD/YYYYMMDD-HHMM/summary_YYYYMMDD_HHMM.csv

Then collect.py sends that per-run CSV to mini_summary.py.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
LOG_PATH = Path("/Users/kumning/twitter/news/hourly_mini.log")
REPORT_CUTOFF = time(hour=8)


def report_date_for_run(now: datetime | None = None) -> str:
    """Return the report date for the 09:00 yesterday -> 08:00 today cycle."""
    now = now or datetime.now()
    report_day = now.date()
    if now.time() > REPORT_CUTOFF:
        report_day += timedelta(days=1)
    return report_day.strftime("%Y%m%d")


def main() -> None:
    report_date = report_date_for_run()
    cmd = [sys.executable, "-u", "collect.py", "--mini", "--live", "--date", report_date]
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] $ {' '.join(cmd)}\n")
        log.flush()
        process = subprocess.Popen(
            cmd,
            cwd=str(SCRIPT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        return_code = process.wait()
        log.write(f"[{datetime.now().isoformat(timespec='seconds')}] exit={return_code}\n")
        log.flush()
    if return_code != 0:
        raise SystemExit(return_code)


if __name__ == "__main__":
    main()
