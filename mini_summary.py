#!/usr/bin/env python3
"""
Hourly mini-summary generator.

Reads a news CSV, assigns stable news refs, updates the daily manifest, and
writes a compact mini-summary that only cites refs such as N0900_001.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from llm_runtime import API_BASE, MODEL


MAX_TOKENS = 8192
TEMPERATURE = 0.0

NEWS_DIR = Path("/Users/kumning/twitter/news")
MINI_DIR = NEWS_DIR / "mini-summary"

MANIFEST_FIELDS = [
    "Date (GMT+7)",
    "Author",
    "Username",
    "Text",
    "Likes",
    "Retweets",
    "Replies",
    "Language",
    "Tweet Link",
    "Source CSV",
]

SYSTEM_PROMPT = """คุณคือ AI นักวิเคราะห์ข่าวเชิงกลยุทธ์รายชั่วโมง
หน้าที่ของคุณคืออ่านรายการข่าวที่มี news_id แล้วสร้าง mini-summary ภาษาไทยตามโครงเดียวกับรายงานข่าวประจำวัน แต่ต้องอ้างอิงด้วย refs เท่านั้น

--- โครงสร้างรายงาน ---

**หน้า 1: Strategic Executive Brief**
ให้ขึ้นต้นหน้าแรกด้วยหัวข้อบรรทัดนี้เท่านั้น:
# Mini Strategic Brief [YYYYMMDD HHMM]

จากนั้นเรียงเนื้อหาตามนี้:
## บทสรุปผู้บริหาร (Executive Summary)
[เขียนเป็นความเรียง 1 ย่อหน้าสั้น สรุปภาพรวมข่าวสำคัญในรอบชั่วโมงนี้]

## ประเด็นวิเคราะห์สำคัญ (TOPIC)
### TOPIC #1: [ชื่อหัวข้อประเด็น]
นัยสำคัญ: [วิเคราะห์ผลกระทบสั้นๆ ไม่เกิน 3 บรรทัด]
* [สรุปเนื้อหาข่าวเต็ม] (refs: NHHMM_001)
* [สรุปเนื้อหาข่าวเต็ม] (refs: NHHMM_002)
* [สรุปเนื้อหาข่าวเต็ม] (refs: NHHMM_003)

### TOPIC #2: [ชื่อหัวข้อประเด็น]
นัยสำคัญ: [วิเคราะห์ผลกระทบสั้นๆ ไม่เกิน 3 บรรทัด]
* [สรุปเนื้อหาข่าวเต็ม] (refs: NHHMM_004)
* [สรุปเนื้อหาข่าวเต็ม] (refs: NHHMM_005)
* [สรุปเนื้อหาข่าวเต็ม] (refs: NHHMM_006)

### TOPIC #3: [ชื่อหัวข้อประเด็น]
นัยสำคัญ: [วิเคราะห์ผลกระทบสั้นๆ ไม่เกิน 3 บรรทัด]
* [สรุปเนื้อหาข่าวเต็ม] (refs: NHHMM_007)
* [สรุปเนื้อหาข่าวเต็ม] (refs: NHHMM_008)
* [สรุปเนื้อหาข่าวเต็ม] (refs: NHHMM_009)

**หน้า 2: ข่าวต่างประเทศ (International News)**
ให้ขึ้นต้นหน้าด้วยหัวข้อบรรทัดนี้เท่านั้น:
# ข่าวต่างประเทศ (International News)

คัดกรองเฉพาะข่าวต่างประเทศเท่านั้น และจัดกลุ่มเข้า 5 หมวดหมู่ โดยแต่ละหมวดหมู่ให้มีภาพรวมก่อนแสดงรายการข่าว:

### 🌍 การทูตระดับโลกและความมั่นคง
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* [ข่าวสำคัญ] (refs: NHHMM_010)


### 💼 เศรษฐกิจ พลังงาน และ การเงินโลก
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* [ข่าวสำคัญ] (refs: NHHMM_011)

### 🚀 เทคโนโลยีอวกาศและนวัตกรรม
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* [ข่าวสำคัญ] (refs: NHHMM_012)

### 🏢 ข่าวสารองค์กรและเทรนด์ธุรกิจ
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* [ข่าวสำคัญ] (refs: NHHMM_013)

### ⚽️ สังคม วัฒนธรรม และกีฬา
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* [ข่าวสำคัญ] (refs: NHHMM_014)

**หน้า 3: ข่าวภายในประเทศไทย (Thailand News)**
ให้ขึ้นต้นหน้าด้วยหัวข้อบรรทัดนี้เท่านั้น:
# ข่าวภายในประเทศไทย (Thailand News)

คัดกรองเฉพาะข่าวในประเทศไทยเท่านั้น
## ประเด็นร้อนแรงในไทย
[เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้โดยให้ความสำคัญจาก Like/RT ความยาวไม่เกิน 3 บรรทัด]
* [ข่าวร้อนแรง] (refs: NHHMM_015)

### 🌍 การทูตระดับโลกและความมั่นคง
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* [ข่าวสำคัญ] (refs: NHHMM_016)

### 💼 เศรษฐกิจ พลังงาน และ การเงินโลก
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* [ข่าวสำคัญ] (refs: NHHMM_017)

### 🚀 เทคโนโลยีอวกาศและนวัตกรรม
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* [ข่าวสำคัญ] (refs: NHHMM_018)

### 🏢 ข่าวสารองค์กรและเทรนด์ธุรกิจ
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* [ข่าวสำคัญ] (refs: NHHMM_019)

### ⚽️ สังคม วัฒนธรรม และกีฬา
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* [ข่าวสำคัญ] (refs: NHHMM_020)

--- กฎข้อบังคับเพิ่มเติม ---
- ห้ามคิดข้อมูลขึ้นเองเด็ดขาด ให้อ้างอิงจาก data ที่ให้ไปเท่านั้น
- ห้ามสร้าง URL หรือคัดลอก URL ใดๆ ลงใน markdown
- ห้ามเขียน Likes, Retweets, Replies, Username, Tweet Link ลงใน markdown
- ทุก bullet ข่าวต้องลงท้ายด้วย `(refs: NEWS_ID)` เพียง 1 ref เท่านั้น
- ใช้เฉพาะ news_id ที่มีอยู่ในข้อมูลเท่านั้น
- link ข่าวและ metadata ทั้งหมดถูกบันทึกใน manifest แล้ว ให้ markdown เก็บเฉพาะ refs
- เขียน bullet เป็นเนื้อหาข่าวจริงโดยตรง ห้ามขึ้นต้นด้วย "มีรายงาน", "มีรายงานว่า", "มีรายงานข่าว", "มีรายงานเหตุการณ์"
- หลีกเลี่ยงสำนวนเล่าว่าเป็นรายงานข่าว ให้สรุปว่าใครทำอะไร ที่ไหน เมื่อไร และผลกระทบคืออะไร
- ตัดข่าวซ้ำ ข่าวโฆษณา และข่าว noise ออก
- ถ้าหมวดใดไม่มีข่าว ให้เขียน `* ไม่มีข่าวสำคัญในรอบนี้`
- การทำ bullet points ต้องขึ้นบรรทัดใหม่ก่อนเริ่ม `*`
- ข่าว 1 ข่าว ต่อ 1 bullet point ห้ามนำมาต่อกันในบรรทัดเดียว
"""


def read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def infer_date(csv_path: Path, rows: list[dict[str, str]], fallback: str | None = None) -> str:
    if fallback:
        return fallback

    match = re.search(r"_(\d{8})(?:_\d{4})?\.csv$", csv_path.name)
    if match:
        return match.group(1)

    for row in rows:
        raw = (row.get("Date (GMT+7)") or "").strip()
        if not raw:
            continue
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M").strftime("%Y%m%d")
        except ValueError:
            continue
    return datetime.now().strftime("%Y%m%d")


def infer_slot(csv_path: Path, rows: list[dict[str, str]], explicit_slot: str | None = None) -> str:
    if explicit_slot:
        return explicit_slot

    match = re.search(r"_(\d{8})_(\d{4})\.csv$", csv_path.name)
    if match:
        return match.group(2)

    for row in rows:
        raw = (row.get("Date (GMT+7)") or "").strip()
        if not raw:
            continue
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M").strftime("%H00")
        except ValueError:
            continue
    return datetime.now().strftime("%H00")


def manifest_path(date_str: str) -> Path:
    return MINI_DIR / f"mini_{date_str}" / f"manifest_{date_str}.json"


def legacy_manifest_path(date_str: str) -> Path:
    return MINI_DIR / f"manifest_{date_str}.json"


def load_manifest(date_str: str) -> dict:
    path = manifest_path(date_str)
    if not path.exists() and legacy_manifest_path(date_str).exists():
        path = legacy_manifest_path(date_str)
    if not path.exists():
        return {"date": date_str, "items": {}, "tweet_links": {}}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("date", date_str)
    data.setdefault("items", {})
    data.setdefault("tweet_links", {})
    return data


def save_manifest(date_str: str, manifest: dict) -> None:
    manifest_path(date_str).parent.mkdir(parents=True, exist_ok=True)
    path = manifest_path(date_str)
    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)


def next_index_for_slot(manifest: dict, slot: str) -> int:
    prefix = f"N{slot}_"
    max_index = 0
    for news_id in manifest.get("items", {}):
        if not news_id.startswith(prefix):
            continue
        try:
            max_index = max(max_index, int(news_id.rsplit("_", 1)[1]))
        except ValueError:
            continue
    return max_index + 1


def add_new_manifest_items(
    rows: list[dict[str, str]],
    manifest: dict,
    slot: str,
    source_name: str,
) -> list[tuple[str, dict[str, str]]]:
    new_items = []
    next_index = next_index_for_slot(manifest, slot)

    for row in rows:
        text = (row.get("Text") or "").strip()
        link = (row.get("Tweet Link") or "").strip()
        if len(text) < 20 or not link:
            continue
        if link in manifest["tweet_links"]:
            continue

        news_id = f"N{slot}_{next_index:03d}"
        next_index += 1

        item = {field: row.get(field, "") for field in MANIFEST_FIELDS}
        item["Source CSV"] = item.get("Source CSV") or source_name
        manifest["items"][news_id] = item
        manifest["tweet_links"][link] = news_id
        new_items.append((news_id, item))

    return new_items


def format_items_for_llm(items: list[tuple[str, dict[str, str]]]) -> str:
    lines = []
    for news_id, item in items:
        text = re.sub(r"https?://\S+", "", item.get("Text", "")).strip()
        lines.append(
            f"[{news_id}] "
            f"{item.get('Author','')} (@{item.get('Username','')}) | "
            f"Likes {item.get('Likes','0')} | RT {item.get('Retweets','0')} | "
            f"Replies {item.get('Replies','0')} | Lang {item.get('Language','')} | "
            f"{text}"
        )
    return "\n".join(lines)


def call_llm(user_content: str) -> str:
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    def read_response() -> str:
        with urllib.request.urlopen(req, timeout=900) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]

    try:
        print(f"[mini] Sending request to {MODEL} at {API_BASE}/chat/completions", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(read_response)
            elapsed = 0
            while True:
                try:
                    return future.result(timeout=20)
                except concurrent.futures.TimeoutError:
                    elapsed += 20
                    print(f"[mini] Waiting for LLM response... {elapsed}s", flush=True)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot connect to LLM endpoint {API_BASE}: {e}") from e
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Cannot parse LLM response: {e}") from e


def normalize_summary(content: str, valid_refs: set[str]) -> str:
    content = content.replace("\r\n", "\n")
    content = re.sub(r"(?is)<think>.*?</think>\s*", "", content)
    content = re.sub(r"https?://\S+", "", content)
    content = clean_report_phrasing(content)

    def clean_refs(ref_text: str, *, max_refs: int) -> str:
        refs = re.findall(r"N\d{4}_\d{3}", ref_text)
        kept = []
        for ref in refs:
            if ref in valid_refs and ref not in kept:
                kept.append(ref)
            if len(kept) >= max_refs:
                break
        return f"(refs: {', '.join(kept)})" if kept else "(refs: INVALID)"

    def normalize_line(line: str) -> str:
        if not line.lstrip().startswith("*"):
            return re.sub(r"\s*\(refs:\s*[^)]+\)", "", line)

        def repl(match: re.Match[str]) -> str:
            return clean_refs(match.group(1), max_refs=1)

        return re.sub(r"\(refs:\s*([^)]+)\)", repl, line)

    normalized_lines = [normalize_line(line) for line in content.splitlines()]
    content = "\n".join(line for line in normalized_lines if "(refs: INVALID)" not in line)
    return content.strip() + "\n"


def clean_report_phrasing(content: str) -> str:
    report_prefix = r"มีรายงาน(?:ข่าว)?(?:ว่า)?\s*"
    content = re.sub(rf"(?m)^(\s*\*\s*){report_prefix}", r"\1", content)
    content = re.sub(rf"(?m)^(\s*ภาพรวม(?:\s+Overall)?\s*:\s*){report_prefix}", r"\1", content)
    return content

def write_empty_mini(date_str: str, slot: str, output_path: Path) -> None:
    output_path.write_text(
        f"# Mini Summary {date_str} {slot}\n\nไม่มีข่าวใหม่ในรอบนี้\n",
        encoding="utf-8",
    )


def build_mini_summary(csv_path: Path, date_str: str | None = None, slot: str | None = None) -> Path:
    rows = read_csv_rows(csv_path)
    resolved_date = infer_date(csv_path, rows, date_str)
    resolved_slot = infer_slot(csv_path, rows, slot)

    output_dir = MINI_DIR / f"mini_{resolved_date}"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(resolved_date)
    new_items = add_new_manifest_items(rows, manifest, resolved_slot, csv_path.name)

    output_path = output_dir / f"mini_{resolved_date}_{resolved_slot}.md"
    if not new_items:
        write_empty_mini(resolved_date, resolved_slot, output_path)
        print(f"[mini] No new items. Wrote {output_path}")
        return output_path

    user_content = (
        f"สร้าง mini-summary สำหรับ {resolved_date} {resolved_slot}\n"
        "ข้อมูลข่าวต่อไปนี้มี news_id อยู่ในวงเล็บเหลี่ยม ห้ามสร้าง URL เอง:\n\n"
        + format_items_for_llm(new_items)
    )
    raw_summary = call_llm(user_content)
    summary = normalize_summary(raw_summary, {news_id for news_id, _ in new_items})
    output_path.write_text(summary, encoding="utf-8")
    save_manifest(resolved_date, manifest)
    print(f"[mini] Added {len(new_items)} items")
    print(f"[mini] Wrote {output_path}")
    print(f"[mini] Manifest {manifest_path(resolved_date)}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an hourly mini-summary from a news CSV.")
    parser.add_argument("csv_path", help="Path to summary_YYYYMMDD.csv or hourly test CSV.")
    parser.add_argument("--date", help="Override YYYYMMDD date.")
    parser.add_argument("--slot", help="Override HHMM slot, e.g. 0900.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_mini_summary(Path(args.csv_path).expanduser(), args.date, args.slot)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[mini] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
