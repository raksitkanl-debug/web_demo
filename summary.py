#!/usr/bin/env python3
"""
News Summary Generator
อ่าน CSV ข่าวประจำวัน → ส่งไปยัง Local LLM → บันทึกเป็น summaryYYYYMMDD.md
"""

import csv
import sys
import json
import re
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from llm_runtime import API_BASE, MODEL

# ─── CONFIG ───────────────────────────────────────────────────────────────────
MAX_TOKENS  = 8192
TEMPERATURE = 0.0

SYSTEM_PROMPT = """คุณคือ AI นักวิเคราะห์ข่าวเชิงกลยุทธ์ (Strategic News Analyst)
หน้าที่ของคุณคืออ่านข้อมูลข่าวประจำวัน (CSV) และสรุปรายงานข่าวเชิงลึกโดยยึดโครงสร้างและรูปแบบการนำเสนอดังต่อไปนี้อย่างเคร่งครัด:

--- โครงสร้างรายงาน ---

**หน้า 1: Strategic Executive Brief**
ให้ขึ้นต้นหน้าแรกด้วยหัวข้อบรรทัดนี้เท่านั้น:
# รายงานข่าวเชิงกลยุทธ์ประจำวันที่ [วัน เดือน ปี พ.ศ.]

จากนั้นเรียงเนื้อหาตามนี้:
## บทสรุปผู้บริหาร (Executive Summary)
[เขียนเป็นความเรียง 1 ย่อหน้า]

## ประเด็นวิเคราะห์สำคัญ (TOPIC)
### TOPIC #1: [ชื่อหัวข้อประเด็น]
นัยสำคัญ: [วิเคราะห์ผลกระทบสั้นๆ ไม่เกิน 3 บรรทัด]
* [สรุปเนื้อหาข่าวเต็ม] (Likes: [x], Retweets: [x], Replies: [x], ที่มา: [สำนักข่าว] 🔗[Tweet Link])
* [สรุปเนื้อหาข่าวเต็ม] (Likes: [x], Retweets: [x], Replies: [x], ที่มา: [สำนักข่าว] 🔗[Tweet Link])
* [สรุปเนื้อหาข่าวเต็ม] (Likes: [x], Retweets: [x], Replies: [x], ที่มา: [สำนักข่าว] 🔗[Tweet Link])

### TOPIC #2: [ชื่อหัวข้อประเด็น]
นัยสำคัญ: [วิเคราะห์ผลกระทบสั้นๆ ไม่เกิน 3 บรรทัด]
* [สรุปเนื้อหาข่าวเต็ม] (Likes: [x], Retweets: [x], Replies: [x], ที่มา: [สำนักข่าว] 🔗[Tweet Link])
* [สรุปเนื้อหาข่าวเต็ม] (Likes: [x], Retweets: [x], Replies: [x], ที่มา: [สำนักข่าว] 🔗[Tweet Link])
* [สรุปเนื้อหาข่าวเต็ม] (Likes: [x], Retweets: [x], Replies: [x], ที่มา: [สำนักข่าว] 🔗[Tweet Link])

### TOPIC #3: [ชื่อหัวข้อประเด็น]
นัยสำคัญ: [วิเคราะห์ผลกระทบสั้นๆ ไม่เกิน 3 บรรทัด]
* [สรุปเนื้อหาข่าวเต็ม] (Likes: [x], Retweets: [x], Replies: [x], ที่มา: [สำนักข่าว] 🔗[Tweet Link])
* [สรุปเนื้อหาข่าวเต็ม] (Likes: [x], Retweets: [x], Replies: [x], ที่มา: [สำนักข่าว] 🔗[Tweet Link])
* [สรุปเนื้อหาข่าวเต็ม] (Likes: [x], Retweets: [x], Replies: [x], ที่มา: [สำนักข่าว] 🔗[Tweet Link])

ให้จบหน้า 1 ที่ TOPIC #3 เท่านั้น

**หน้า 2: ข่าวต่างประเทศ (International News Catalog)**
ให้ขึ้นต้นหน้าด้วยหัวข้อบรรทัดนี้เท่านั้น:
# ข่าวต่างประเทศ (International News Catalog)

คัดกรองเฉพาะ "ข่าวต่างประเทศเท่านั้น" (คัดกรองเหตุการณ์ที่ เกิดขึ้นภายนอกประเทศไทย ทั้งหมด) และจัดกลุ่มเข้า 5 หมวดหมู่ โดยแต่ละหมวดหมู่ให้มี **บทสรุปภาพรวม (Overall)** ก่อนแสดงรายการข่าว ดังนี้:

### 🌍 การทูตระดับโลกและความมั่นคง
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* ลิสต์ข่าวสำคัญ 3 รายการ โดยแต่ละข่าวต้องขึ้นต้นด้วย `*`

### 💼 เศรษฐกิจ พลังงาน และ การเงินโลก
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* ลิสต์ข่าวสำคัญ 3 รายการ โดยแต่ละข่าวต้องขึ้นต้นด้วย `*`

### 🚀 เทคโนโลยีอวกาศและนวัตกรรม
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* ลิสต์ข่าวสำคัญ 3 รายการ โดยแต่ละข่าวต้องขึ้นต้นด้วย `*`

### 🏢 ข่าวสารองค์กรและเทรนด์ธุรกิจ
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* ลิสต์ข่าวสำคัญ 3 รายการ โดยแต่ละข่าวต้องขึ้นต้นด้วย `*`

### ⚽️ สังคม วัฒนธรรม และกีฬา
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* ลิสต์ข่าวสำคัญ Top 3 โดยแต่ละข่าวต้องขึ้นต้นด้วย `*`

**หน้า 3: ข่าวภายในประเทศไทย (Thailand News)**
ให้ขึ้นต้นหน้าด้วยหัวข้อบรรทัดนี้เท่านั้น:
# ข่าวภายในประเทศไทย (Thailand News)

คัดกรองเฉพาะ "ข่าวในประเทศไทยเท่านั้น" (พิจารณาเฉพาะเหตุการณ์ที่ "เกิดขึ้นภายในพื้นที่ประเทศไทย" หรือเกี่ยวข้องกับนโยบายภายในประเทศโดยตรงเท่านั้น)
** ประเด็นร้อนแรงในไทย เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้โดยให้ความสำคัญจาก Like/RT ความยาว **ไม่เกิน 3 บรรทัด**

   - ลิสต์ข่าวประเด็นร้อนแรงในไทยและมี Like/RT สูงสุด **Top 3** ที่เป็นประเด็นมากที่สุด โดยต้องอยู่ในรูปแบบ `* [เนื้อหาเต็ม] (Likes: x, Retweets: x, Replies: x, ที่มา: สำนักข่าว 🔗Link)`

### 🌍 การทูตระดับโลกและความมั่นคง
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* ลิสต์ข่าวสำคัญ Top 3 โดยแต่ละข่าวต้องขึ้นต้นด้วย `*`

### 💼 เศรษฐกิจ พลังงาน และ การเงินโลก
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* ลิสต์ข่าวสำคัญ Top 3 โดยแต่ละข่าวต้องขึ้นต้นด้วย `*`

### 🚀 เทคโนโลยีอวกาศและนวัตกรรม
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* ลิสต์ข่าวสำคัญ Top 3 โดยแต่ละข่าวต้องขึ้นต้นด้วย `*`

### 🏢 ข่าวสารองค์กรและเทรนด์ธุรกิจ
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* ลิสต์ข่าวสำคัญ Top 3 โดยแต่ละข่าวต้องขึ้นต้นด้วย `*`

### ⚽️ สังคม วัฒนธรรม และกีฬา
ภาพรวม: เขียนสรุปสถานการณ์ที่สำคัญที่สุดในหมวดนี้ ความยาวไม่เกิน 3 บรรทัด
* ลิสต์ข่าวสำคัญ Top 3 โดยแต่ละข่าวต้องขึ้นต้นด้วย `*`

--- กฎข้อบังคับเพิ่มเติม ---
- ห้ามคิดข้อมูลขึ้นเองเด็ดขาด ให้อ้างอิงจาก Data ที่ให้ไปเท่านั้น
- ตัดข้อมูลที่ไร้สาระ (Noise) หรือข่าวที่ไม่มีเนื้อหาสำคัญออก
- ตัดข้อมูลที่ซ้ำซ้อนกันออก (Duplicate)
- ลิงก์อ้างอิง (🔗) จะต้องเป็น URL ที่กดได้จริงจากในข้อมูล (Tweet Link) เสมอ
- ห้ามแสดง URL ยาวแบบตัวเปล่าในรายงาน ให้เขียนเฉพาะ `🔗[Tweet Link]` ในวงเล็บท้ายบรรทัดเท่านั้น
- ต้องจัดเนื้อหาให้ออกมาเป็น 3 หน้า 3 ส่วนที่แยกจากกันโดยสิ้นเชิงตามหัวข้อ `#` ทั้ง 3 อันด้านบน
- การทำ Bullet points: ต้อง "ขึ้นบรรทัดใหม่ (New line)" เสมอก่อนเริ่มเขียน * หรือ -
- การเว้นวรรค: ให้เว้น 1 บรรทัดว่างๆ ระหว่าง "ภาพรวม" และ "ลิสต์ข่าว"
- เขียน Bullet เป็นเนื้อหาข่าวจริงโดยตรง ห้ามขึ้นต้นด้วย "มีรายงาน", "มีรายงานว่า", "มีรายงานข่าว", "มีรายงานเหตุการณ์"
- หลีกเลี่ยงสำนวนเล่าว่าเป็นรายงานข่าว ให้สรุปว่าใครทำอะไร ที่ไหน เมื่อไร และผลกระทบคืออะไร
- ข่าว 1 ข่าว ต่อ 1 Bullet point ห้ามนำมาต่อกันในบรรทัดเดียว"""


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def load_csv(csv_path: str) -> tuple[str, str]:
    """โหลด CSV และดึงวันที่จากคอลัมน์แรก"""
    rows = []
    date_str = datetime.now().strftime("%Y%m%d")

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # ดึงวันที่จากแถวแรกที่มีข้อมูล
            if date_str == datetime.now().strftime("%Y%m%d") and row.get("Date (GMT+7)"):
                try:
                    dt = datetime.strptime(row["Date (GMT+7)"].strip(), "%Y-%m-%d %H:%M")
                    date_str = dt.strftime("%Y%m%d")
                except ValueError:
                    pass

            # ข้ามแถวที่ Text ว่างหรือสั้นเกินไป
            text = row.get("Text", "").strip()
            if len(text) < 20:
                continue

            rows.append(
                f"[{row.get('Date (GMT+7)','')}] "
                f"@{row.get('Username','')} ({row.get('Author','')}) | "
                f"❤️{row.get('Likes','0')} 🔁{row.get('Retweets','0')} | "
                f"{text} | "
                f"🔗{row.get('Tweet Link','')}"
            )

    return "\n".join(rows), date_str


def call_llm(csv_content: str) -> str:
    """เรียก local LLM endpoint (OpenAI-compatible /v1/chat/completions)"""
    url = f"{API_BASE}/chat/completions"

    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "นี่คือข้อมูลข่าวประจำวันในรูปแบบ CSV ที่ถูก parse แล้ว "
                    "กรุณาวิเคราะห์และสรุปตามโครงสร้างที่กำหนดไว้:\n\n"
                    + csv_content
                ),
            },
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except urllib.error.URLError as e:
        print(f"❌ ไม่สามารถเชื่อมต่อ endpoint ได้: {e}")
        print(f"   ตรวจสอบว่า LLM server รันอยู่ที่ {API_BASE}")
        sys.exit(1)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"❌ parse response ไม่ได้: {e}")
        sys.exit(1)


def normalize_output(content: str) -> str:
    """Normalize model output for markdown/PDF rendering."""
    content = content.replace("\r\n", "\n")
    content = re.sub(r"(?is)<think>.*?</think>\s*", "", content)
    content = re.sub(r"(?m)^<think>\s*$", "", content)
    content = re.sub(r"(?m)^</think>\s*$", "", content)
    content = re.sub(r"🔗(https?://\S+)", r"[🔗](\1)", content)
    content = re.sub(r"(\[🔗\]\((https?://[^)]+)\))\s*\2", r"\1", content)
    content = re.sub(r"(?m)^(\d+)\.\s+(🌍|💼|🚀|🏢|⚽️)", r"### \2", content)
    return content


def save_output(content: str, date_str: str, output_dir: str = ".") -> str:
    """บันทึกผลลัพธ์เป็น summaryYYYYMMDD.md"""
    filename = f"summary{date_str}.md"
    output_path = Path(output_dir) / filename
    output_path.write_text(content, encoding="utf-8")
    return str(output_path)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    # รับ path ของ CSV จาก argument หรือใช้ default
    if len(sys.argv) < 2:
        print("Usage: python run_news_summary.py <path_to_csv> [output_dir]")
        print("Example: python run_news_summary.py summary_20260408.csv .")
        sys.exit(1)

    csv_path   = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "."

    # ── 1. โหลด CSV ──────────────────────────────────────────────────────────
    print(f"📂 กำลังโหลด CSV: {csv_path}")
    csv_content, date_str = load_csv(csv_path)
    line_count = csv_content.count("\n") + 1
    print(f"   ✅ โหลดข้อมูล {line_count} รายการ (วันที่: {date_str})")

    # ── 2. เรียก LLM ─────────────────────────────────────────────────────────
    print(f"\n🤖 กำลังส่งข้อมูลไปยัง {MODEL} ...")
    print(f"   endpoint: {API_BASE}/chat/completions")
    summary = call_llm(csv_content)
    summary = normalize_output(summary)
    print("   ✅ ได้รับผลลัพธ์จาก LLM")

    # ── 3. บันทึกไฟล์ ────────────────────────────────────────────────────────
    saved_path = save_output(summary, date_str, output_dir)
    print(f"\n💾 บันทึกไฟล์สำเร็จ: {saved_path}")
    print("\n" + "─" * 60)
    print(summary[:500] + ("..." if len(summary) > 500 else ""))
    print("─" * 60)


if __name__ == "__main__":
    main()
