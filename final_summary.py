#!/usr/bin/env python3
"""
Final daily summary generator.

Reads hourly mini-summaries, asks the LLM for a final 3-page report using refs,
then renders those refs into real source links from the daily manifest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from llm_runtime import API_BASE, MODEL


MAX_TOKENS = 8192
TEMPERATURE = 0.0

NEWS_DIR = Path("/Users/kumning/twitter/news")
MINI_DIR = NEWS_DIR / "mini-summary"
SUMMARY_DIR = NEWS_DIR / "summary"

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

SYSTEM_PROMPT = """คุณคือ AI นักวิเคราะห์ข่าวเชิงกลยุทธ์
หน้าที่ของคุณคืออ่าน mini-summary รายชั่วโมงแล้วสร้าง final daily report ภาษาไทยแบบ 3 หน้า

กฎสำคัญ:
- ใช้เฉพาะข้อมูลจาก mini-summary ที่ให้มาเท่านั้น
- ห้ามสร้าง URL หรือคัดลอก URL ใดๆ
- ทุก bullet ข่าวต้องมี `(refs: NEWS_ID)` หรือ `(refs: NEWS_ID, NEWS_ID)`
- ใช้เฉพาะ refs ที่ปรากฏใน mini-summary เท่านั้น
- ตัดข่าวซ้ำและรวมประเด็นที่ใกล้กัน
- แต่ละ TOPIC แสดงข่าว/ประเด็นได้สูงสุด 3 bullet เท่านั้น
- ข่าวต่างประเทศแต่ละหมวดแสดงข่าวสำคัญสูงสุด 3 bullet เท่านั้น
- ข่าวภายในประเทศไทยแต่ละหมวดแสดงข่าวสำคัญสูงสุด 3 bullet เท่านั้น
- ประเด็นร้อนแรงในไทยให้เลือก Top 5 โดยพิจารณาความสำคัญจาก Likes, Retweets และ Replies
- เขียน bullet เป็นเนื้อหาข่าวจริงโดยตรง ห้ามขึ้นต้นด้วย "มีรายงาน", "มีรายงานว่า", "มีรายงานข่าว", "มีรายงานเหตุการณ์"
- หลีกเลี่ยงสำนวนเล่าว่าเป็นรายงานข่าว ให้สรุปว่าใครทำอะไร ที่ไหน เมื่อไร และผลกระทบคืออะไร
- รายงานต้องมี 3 ส่วนแยกด้วยหัวข้อ # ดังนี้

# รายงานข่าวเชิงกลยุทธ์ประจำวันที่ [วัน เดือน ปี พ.ศ.]
ตัวอย่าง: # รายงานข่าวเชิงกลยุทธ์ประจำวันที่ 3 พฤษภาคม 2569

## บทสรุปผู้บริหาร (Executive Summary)
[เขียน 1 ย่อหน้า]

## ประเด็นวิเคราะห์สำคัญ (TOPIC)
### TOPIC #1: [ชื่อหัวข้อ]
นัยสำคัญ: [ไม่เกิน 3 บรรทัด]
* [ข่าว/ประเด็นเต็ม] (refs: N0900_001)
* [ข่าว/ประเด็นเต็ม] (refs: N0900_003)
* [ข่าว/ประเด็นเต็ม] (refs: N0900_004)

### TOPIC #2: [ชื่อหัวข้อ]
นัยสำคัญ: [ไม่เกิน 3 บรรทัด]
* [ข่าว/ประเด็นเต็ม] (refs: N1100_001)
* [ข่าว/ประเด็นเต็ม] (refs: N1100_002)
* [ข่าว/ประเด็นเต็ม] (refs: N1100_003)

### TOPIC #3: [ชื่อหัวข้อ]
นัยสำคัญ: [ไม่เกิน 3 บรรทัด]
* [ข่าว/ประเด็นเต็ม] (refs: N1200_001)
* [ข่าว/ประเด็นเต็ม] (refs: N1200_002)
* [ข่าว/ประเด็นเต็ม] (refs: N1200_003)

# ข่าวต่างประเทศ (International News)
ภาพรวม : [สรุปภาพรวมของหมวดต่อไปนี้ การทูตระดับโลกและความมั่นคง,เศรษฐกิจ พลังงาน และ การเงินโลก,เทคโนโลยีอวกาศและนวัตกรรม,ข่าวสารองค์กรและเทรนด์ธุรกิจ,สังคม วัฒนธรรม และกีฬา]
### 🌍 การทูตระดับโลกและความมั่นคง
ภาพรวม : [สรุปภาพรวมของหมวดนี้ ไม่เกิน 3 บรรทัด]
* [ข่าวสำคัญ] (refs: N0900_001)
* [ข่าวสำคัญ] (refs: N0900_002)
* [ข่าวสำคัญ] (refs: N0900_003)

### 💼 เศรษฐกิจ พลังงาน และ การเงินโลก
ภาพรวม : [สรุปภาพรวมของหมวดนี้ ไม่เกิน 3 บรรทัด]
* [ข่าวสำคัญ] (refs: N1000_001)
* [ข่าวสำคัญ] (refs: N1000_002)
* [ข่าวสำคัญ] (refs: N1000_003)

### 🚀 เทคโนโลยีอวกาศและนวัตกรรม
ภาพรวม : [สรุปภาพรวมของหมวดนี้ ไม่เกิน 3 บรรทัด]
* [ข่าวสำคัญ] (refs: N1100_001)
* [ข่าวสำคัญ] (refs: N1100_002)
* [ข่าวสำคัญ] (refs: N1100_003)

### 🏢 ข่าวสารองค์กรและเทรนด์ธุรกิจ
ภาพรวม : [สรุปภาพรวมของหมวดนี้ ไม่เกิน 3 บรรทัด]
* [ข่าวสำคัญ] (refs: N1200_001)
* [ข่าวสำคัญ] (refs: N1200_002)
* [ข่าวสำคัญ] (refs: N1200_003)

### ⚽️ สังคม วัฒนธรรม และกีฬา
ภาพรวม : [สรุปภาพรวมของหมวดนี้ ไม่เกิน 3 บรรทัด]
* [ข่าวสำคัญ] (refs: N1300_001)
* [ข่าวสำคัญ] (refs: N1300_002)
* [ข่าวสำคัญ] (refs: N1300_003)

# ข่าวภายในประเทศไทย (Thailand News)
ภาพรวม : [สรุปภาพรวมของหมวดต่อไปนี้ การทูตระดับโลกและความมั่นคง,เศรษฐกิจ พลังงาน และ การเงินโลก,เทคโนโลยีอวกาศและนวัตกรรม,ข่าวสารองค์กรและเทรนด์ธุรกิจ,สังคม วัฒนธรรม และกีฬา,ประเด็นร้อนแรงในไทย]

## ประเด็นร้อนแรงในไทย
[ภาพรวม : ไม่เกิน 3 บรรทัด]
* [ข่าวร้อนแรง] (refs: N1400_001)
* [ข่าวร้อนแรง] (refs: N1400_002)
* [ข่าวร้อนแรง] (refs: N1400_003)
* [ข่าวร้อนแรง] (refs: N1400_004)
* [ข่าวร้อนแรง] (refs: N1400_005)

### 🌍 การทูตระดับโลกและความมั่นคง
ภาพรวม : [สรุปภาพรวมของหมวดนี้ ไม่เกิน 3 บรรทัด]
* [ข่าวสำคัญ] (refs: N1500_001)
* [ข่าวสำคัญ] (refs: N1500_002)
* [ข่าวสำคัญ] (refs: N1500_003)

### 💼 เศรษฐกิจ พลังงาน และ การเงินโลก
ภาพรวม : [สรุปภาพรวมของหมวดนี้ ไม่เกิน 3 บรรทัด]
* [ข่าวสำคัญ] (refs: N1600_001)
* [ข่าวสำคัญ] (refs: N1600_002)
* [ข่าวสำคัญ] (refs: N1600_003)

### 🚀 เทคโนโลยีอวกาศและนวัตกรรม
ภาพรวม : [สรุปภาพรวมของหมวดนี้ ไม่เกิน 3 บรรทัด]
* [ข่าวสำคัญ] (refs: N1700_001)
* [ข่าวสำคัญ] (refs: N1700_002)
* [ข่าวสำคัญ] (refs: N1700_003)

### 🏢 ข่าวสารองค์กรและเทรนด์ธุรกิจ
ภาพรวม : [สรุปภาพรวมของหมวดนี้ ไม่เกิน 3 บรรทัด]
* [ข่าวสำคัญ] (refs: N1800_001)
* [ข่าวสำคัญ] (refs: N1800_002)
* [ข่าวสำคัญ] (refs: N1800_003)

### ⚽️ สังคม วัฒนธรรม และกีฬา
ภาพรวม : [สรุปภาพรวมของหมวดนี้ ไม่เกิน 3 บรรทัด]
* [ข่าวสำคัญ] (refs: N1900_001)
* [ข่าวสำคัญ] (refs: N1900_002)
* [ข่าวสำคัญ] (refs: N1900_003)
"""


def thai_date(date_str: str) -> str:
    if not re.fullmatch(r"\d{8}", date_str):
        return date_str
    year = int(date_str[:4]) + 543
    month = THAI_MONTHS.get(date_str[4:6], date_str[4:6])
    day = int(date_str[6:8])
    return f"{day} {month} {year}"


def manifest_candidates(date_str: str) -> list[Path]:
    return [
        MINI_DIR / f"mini_{date_str}" / f"manifest_{date_str}.json",
        MINI_DIR / f"manifest_{date_str}.json",
    ]


def manifest_path(date_str: str) -> Path:
    for path in manifest_candidates(date_str):
        if path.exists():
            return path
    return manifest_candidates(date_str)[0]


def load_manifest(date_str: str) -> dict:
    path = manifest_path(date_str)
    if not path.exists():
        tried = "\n".join(f"- {candidate}" for candidate in manifest_candidates(date_str))
        raise FileNotFoundError(f"Manifest not found for {date_str}. Tried:\n{tried}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("items", {})
    return data


def read_mini_summaries(date_str: str) -> list[tuple[Path, str]]:
    dated_dir = MINI_DIR / f"mini_{date_str}"
    paths = sorted(dated_dir.glob(f"mini_{date_str}_*.md")) if dated_dir.exists() else []
    if not paths:
        paths = sorted(MINI_DIR.glob(f"mini_{date_str}_*.md"))
    summaries = []
    for path in paths:
        text = path.read_text(encoding="utf-8").strip()
        if text and "ไม่มีข่าวใหม่" not in text:
            summaries.append((path, text))
    return summaries


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
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot connect to LLM endpoint {API_BASE}: {e}") from e
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Cannot parse LLM response: {e}") from e


def normalize_model_output(content: str) -> str:
    content = content.replace("\r\n", "\n")
    content = re.sub(r"(?is)<think>.*?</think>\s*", "", content)
    content = re.sub(r"https?://\S+", "", content)
    content = re.sub(r"(?m)^(\d+)\.\s+(🌍|💼|🚀|🏢|⚽️)", r"### \2", content)
    content = content.replace(
        "# ข่าวต่างประเทศ (International News Catalog)",
        "# ข่าวต่างประเทศ (International News)",
    )
    content = clean_report_phrasing(content)
    return content.strip()


def normalize_report_title(content: str, date_str: str) -> str:
    title = f"# รายงานข่าวเชิงกลยุทธ์ประจำวันที่ {thai_date(date_str)}"
    pattern = r"(?m)^#\s*รายงานข่าวเชิงกลยุทธ์ประจำวันที่.*$"
    if re.search(pattern, content):
        return re.sub(pattern, title, content, count=1)
    return title + "\n\n" + content.lstrip()


def clean_report_phrasing(content: str) -> str:
    report_prefix = r"มีรายงาน(?:ข่าว)?(?:ว่า)?\s*"
    content = re.sub(rf"(?m)^(\s*\*\s*){report_prefix}", r"\1", content)
    content = re.sub(rf"(?m)^(\s*ภาพรวม(?:\s+Overall)?\s*:\s*){report_prefix}", r"\1", content)
    return content


def bullet_limit_for_heading(line: str) -> int | None:
    if re.match(r"^###\s+TOPIC\s+#\d+:", line):
        return 3
    if line.startswith("## ประเด็นร้อนแรงในไทย"):
        return 5
    if re.match(r"^###\s+(🌍|💼|🚀|🏢|⚽️)", line):
        return 3
    if line.startswith("#") or line.startswith("## "):
        return None
    return None


def limit_section_bullets(content: str) -> str:
    lines = []
    current_limit = None
    bullet_count = 0
    skipping_extra_bullet = False

    for line in content.splitlines():
        heading_limit = bullet_limit_for_heading(line)
        if line.startswith("#"):
            current_limit = heading_limit
            bullet_count = 0
            skipping_extra_bullet = False
            lines.append(line)
            continue

        if line.startswith("* "):
            skipping_extra_bullet = False
            if current_limit is not None:
                bullet_count += 1
                if bullet_count > current_limit:
                    skipping_extra_bullet = True
                    continue
            lines.append(line)
            continue

        if skipping_extra_bullet and (line.startswith("  ") or not line.strip()):
            continue

        skipping_extra_bullet = False
        lines.append(line)

    return "\n".join(lines)


def render_ref_links(
    ref_text: str,
    manifest: dict,
    *,
    include_metrics: bool,
    multiline: bool,
) -> str:
    refs = re.findall(r"N\d{4}_\d{3}", ref_text)
    seen = set()
    rendered = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        item = manifest["items"].get(ref)
        if not item:
            continue
        source = item.get("Author") or item.get("Username") or ref
        link = item.get("Tweet Link", "")
        likes = item.get("Likes", "0")
        retweets = item.get("Retweets", "0")
        replies = item.get("Replies", "0")
        if link:
            source_text = f"{source} [🔗]({link})"
        else:
            source_text = source
        if include_metrics:
            source_text += f" (Likes: {likes}, Retweets: {retweets}, Replies: {replies})"
        rendered.append(source_text)

    if not rendered:
        return ""
    prefix = "\n  ที่มา: " if multiline else " ที่มา: "
    return prefix + "; ".join(rendered)


def replace_refs_with_links(content: str, manifest: dict) -> str:
    lines = []
    in_thailand_section = False
    for line in content.splitlines():
        if line.startswith("# ข่าวภายในประเทศไทย"):
            in_thailand_section = True
        elif line.startswith("# ข่าวต่างประเทศ"):
            in_thailand_section = False

        def repl(match: re.Match[str]) -> str:
            return render_ref_links(
                match.group(1),
                manifest,
                include_metrics=in_thailand_section,
                multiline=in_thailand_section and line.lstrip().startswith("*"),
            )

        lines.append(re.sub(r"\s*\(refs:\s*([^)]+)\)", repl, line))
    return "\n".join(lines)


def build_user_content(date_str: str, summaries: list[tuple[Path, str]]) -> str:
    parts = [f"สร้าง final daily report สำหรับวันที่ {date_str}", "Mini summaries:"]
    for path, text in summaries:
        parts.append(f"\n--- {path.name} ---\n{text}")
    return "\n".join(parts)


def build_final_summary(date_str: str) -> Path:
    manifest = load_manifest(date_str)
    summaries = read_mini_summaries(date_str)
    if not summaries:
        raise FileNotFoundError(f"No mini summaries found for {date_str} in {MINI_DIR}")

    raw = call_llm(build_user_content(date_str, summaries))
    normalized = normalize_model_output(raw)
    titled = normalize_report_title(normalized, date_str)
    limited = limit_section_bullets(titled)
    rendered = replace_refs_with_links(limited, manifest).strip() + "\n"

    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    output_path = SUMMARY_DIR / f"summary{date_str}.md"
    output_path.write_text(rendered, encoding="utf-8")
    print(f"[final] Read {len(summaries)} mini summaries")
    print(f"[final] Wrote {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate final daily summary from mini summaries.")
    parser.add_argument("--date", required=True, help="YYYYMMDD date to summarize.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_final_summary(args.date)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[final] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
