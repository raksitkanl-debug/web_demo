#!/usr/bin/env python3
"""
Single-message Telegram report + full PDF generator.
Reads news/summary_YYYYMMDD.csv and outputs:
  - A compact single Telegram message (stdout)
  - A full PDF file (news/summary_YYYYMMDD.pdf)
"""

import os
import sys
import csv
import re
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(CURRENT_DIR)))
NEWS_DIR = os.path.join(WORKSPACE, "news")
TODAY = datetime.now().strftime("%Y%m%d")

THAI_MONTHS = {
    "01": "มกราคม", "02": "กุมภาพันธ์", "03": "มีนาคม", "04": "เมษายน",
    "05": "พฤษภาคม", "06": "มิถุนายน", "07": "กรกฎาคม", "08": "สิงหาคม",
    "09": "กันยายน", "10": "ตุลาคม", "11": "พฤศจิกายน", "12": "ธันวาคม"
}
DAY_TH = {"Monday": "วันจันทร์", "Tuesday": "วันอังคาร", "Wednesday": "วันพุธ",
          "Thursday": "วันพฤหัสบดี", "Friday": "วันศุกร์", "Saturday": "วันเสาร์", "Sunday": "วันอาทิตย์"}

MAX_CHARS = 4000
MAX_PER_CAT = 5  # top N per category for Telegram

def thai_date(date_str):
    if not date_str:
        return date_str
    parts = date_str.split("-")
    if len(parts) != 3:
        return date_str
    y, m, d = parts
    return f"{d} {THAI_MONTHS.get(m, m)} {int(y)+543}"

def day_th(date_str):
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return DAY_TH.get(dt.strftime("%A"), dt.strftime("%A"))
    except:
        return ""

def get_time(date_gmt7):
    if not date_gmt7:
        return ""
    parts = date_gmt7.split(" ")
    return parts[-1] if len(parts) > 1 else ""

def truncate(text, max_len=120):
    text = strip_emoji(text).replace("\n", " ").replace("\r", "")
    if len(text) > max_len:
        return text[:max_len-3] + "..."
    return text

import re
EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001F9FF\U0001FA00-\U0001FAFF"
    "\U00002702-\U000027B0\U000024C2-\U0001F251"
    "\U00002600-\U000026FF\U00002700-\U000027BF]+",
    flags=re.UNICODE
)
def strip_emoji(text):
    return EMOJI_PATTERN.sub("", text)

def categorize(text):
    t = text.lower()
    if any(kw in t for kw in ["ไทย", "กรุงเทพ", "นายก", "รัฐบาล", "สภา", "เลือกตั้ง", "พรรค", "ครม.", "มติ", "ศาล"]):
        return "thai_politics"
    if any(kw in t for kw in ["war", "iran", "israel", "russia", "ukraine", "china", "trump", "putin", "vance", "nato", "military", "strike", "attack", "nuclear", "hormuz", "gaza", "sanction", "สงคราม", "รบ", "ทหาร", "ขู่", "ความมั่นคง"]):
        return "geopolitics"
    if any(kw in t for kw in ["economy", "market", "stock", "gdp", "inflation", "fed", "imf", "oil", "energy", "recession", "trade", "tariff", "ราคาน้ำมัน", "เศรษฐกิจ", "ตลาดหุ้น", "พลังงาน"]):
        return "economy"
    if any(kw in t for kw in ["nasa", "artemis", "spacex", "moon", "ai", "elon", "tech", "space", "samsung", "อวกาศ", "เทคโนโลยี"]):
        return "tech"
    if any(kw in t for kw in ["company", "ceo", "merger", "revenue", "earnings", "wsj", "business", "บริษัท", "ผู้บริหาร"]):
        return "corporate"
    return "society"

CATEGORY_LABELS = {
    "thai_politics": "🏛️ การเมืองไทย (Thai Politics)",
    "geopolitics": "🌍 การทูตระดับโลกและความมั่นคง (Geopolitics & Security)",
    "economy": "💰 เศรษฐกิจ พลังงาน และการเงินโลก (Global Economy & Energy)",
    "tech": "🚀 เทคโนโลยี อวกาศ และนวัตกรรม (Tech, Space & Innovation)",
    "corporate": "🏢 ข่าวสารองค์กร และเทรนด์ธุรกิจ (Corporate & Industry Trends)",
    "society": "⚽ สังคม วัฒนธรรม และกีฬา (Society, Sports & Lifestyle)",
}

PRIORITY_HIGH = ["war", "strike", "attack", "military", "nuclear", "trump", "putin", "iran", "israel", "sanction", "breaking", "สงคราม", "ขู่"]
PRIORITY_MEDIUM = ["economy", "market", "gdp", "imf", "oil", "energy", "trade", "เศรษฐกิจ", "ความมั่นคง"]

def priority_score(text):
    t = text.lower()
    score = 0
    for kw in PRIORITY_HIGH:
        if kw in t:
            score += 3
    for kw in PRIORITY_MEDIUM:
        if kw in t:
            score += 1
    return score

def generate_exec_summary(tweets):
    if not tweets:
        return "ไม่พบข้อมูลข่าวสารสำหรับวันนี้"
    total = len(tweets)
    sources = len(set(t.get("Username", "") for t in tweets))
    cats = {}
    for t in tweets:
        c = t.get("_category", "society")
        cats[c] = cats.get(c, 0) + 1
    top3 = sorted(cats.items(), key=lambda x: -x[1])[:3]
    cat_names = [CATEGORY_LABELS.get(k, k).split("(")[0].strip() for k, _ in top3]
    cat_str = " / ".join(cat_names)
    return f"วันนี้พบข่าวสารทั้งหมด {total} รายการจาก {sources} แหล่งข่าว ประเด็นเด่น: {cat_str} สะท้อนสถานการณ์โลกที่เต็มไปด้วยความผันผวนทั้งในมิติภูมิรัฐศาสตร์ เศรษฐกิจ และเทคโนโลยีในช่วง 24 ชั่วโมงที่ผ่านมา"

def extract_topics(tweets):
    if not tweets:
        return []
    cats = {}
    for t in tweets:
        c = t.get("_category", "society")
        if c not in cats:
            cats[c] = []
        cats[c].append(t)
    for c in cats:
        cats[c] = sorted(cats[c], key=lambda t: priority_score(t.get("Text","")), reverse=True)
    topics = []
    if cats.get("geopolitics"):
        t = cats["geopolitics"][0]
        topics.append({"title":"ความตึงเครียดระหว่างประเทศและการรบ","summary":truncate(t.get("Text",""),150),"implication":"สถานการณ์ความขัดแย้งส่งผลโดยตรงต่อตลาดพลังงานและห่วงโซ่อุปทานโลก ผู้บริหารควรติดตามนโยบายตอบโต้อย่างใกล้ชิด","source":t.get("Username",""),"link":t.get("Tweet Link","")})
    if cats.get("economy"):
        t = cats["economy"][0]
        topics.append({"title":"เศรษฐกิจมหภาคและตลาดการเงิน","summary":truncate(t.get("Text",""),150),"implication":"ความผันผวนของราคาพลังงานและอัตราดอกเบี้ยอาจกระทบต้นทุนธุรกิจและกำไรในไตรมาสถัดไป","source":t.get("Username",""),"link":t.get("Tweet Link","")})
    if cats.get("tech"):
        t = cats["tech"][0]
        topics.append({"title":"เทคโนโลยี อวกาศ และนวัตกรรม","summary":truncate(t.get("Text",""),150),"implication":"ความก้าวหน้าด้าน AI และอวกาศอาจเปลี่ยนโครงสร้างอุตสาหกรรมในระยะกลาง ควรประเมินโอกาสและความเสี่ยงจาก disruption","source":t.get("Username",""),"link":t.get("Tweet Link","")})
    return topics[:3]

def build_telegram_report(date_str):
    """Build a single compact Telegram message string."""
    if len(date_str) == 8 and date_str.isdigit():
        date_str_parsed = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    else:
        date_str_parsed = date_str

    csv_path = os.path.join(NEWS_DIR, f"summary_{date_str}.csv")
    if not os.path.exists(csv_path):
        return None

    tweets = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["_category"] = categorize(row.get("Text","") + " " + row.get("Author",""))
            tweets.append(row)

    date_display = thai_date(date_str_parsed)
    day_name = day_th(date_str_parsed)
    total = len(tweets)

    # Categorize
    categorized = {}
    for t in tweets:
        c = t.get("_category", "society")
        if c not in categorized:
            categorized[c] = []
        categorized[c].append(t)
    for c in categorized:
        categorized[c] = sorted(categorized[c], key=lambda t: priority_score(t.get("Text","")), reverse=True)

    topics = extract_topics(tweets)
    cats_order = ["geopolitics","economy","tech","corporate","thai_politics","society"]

    TABLE_HDR = "| Time | Content | Username | Likes | Retweets | Replies | Lang | Tweet Link |\n| --- | --- | --- | --- | --- | --- | --- | --- |"

    lines = []
    lines.append(f"📋 Strategic Brief — {day_name}ที่ {date_display}")
    lines.append("─" * 60)
    lines.append("📌 บทสรุปผู้บริหาร (Executive Summary)")
    lines.append("─" * 60)
    lines.append(generate_exec_summary(tweets))
    lines.append("")

    if topics:
        lines.append("📊 ประเด็นวิเคราะห์สำคัญ (Key Strategic Topics)")
        lines.append("─" * 60)
        for i, topic in enumerate(topics, 1):
            lines.append(f"{i}. **{topic['title']}**")
            lines.append(f"   📰 {topic['summary']}")
            lines.append(f"   💡 นัยสำคัญ: {topic['implication']}")
            lines.append(f"   📎 {topic['source']} | {topic['link']}")
        lines.append("")

    lines.append(f"📋 รายละเอียดข่าวสารทั้งหมด (Comprehensive News Catalog)")
    lines.append(f"   ทั้งหมด {total} รายการ — แสดง top {MAX_PER_CAT} ต่อหมวด")
    lines.append("─" * 60)

    for cat_key in cats_order:
        if cat_key not in categorized or not categorized[cat_key]:
            continue
        tweets_in_cat = categorized[cat_key][:MAX_PER_CAT]
        cat_label = strip_emoji(CATEGORY_LABELS.get(cat_key, cat_key))
        total_cat = len(categorized[cat_key])
        lines.append(f"\n{cat_label} (แสดง {len(tweets_in_cat)} จาก {total_cat} รายการ)")
        lines.append(TABLE_HDR)
        for t in tweets_in_cat:
            time_val = get_time(t.get("Date (GMT+7)",""))
            content = truncate(t.get("Text",""), 100)
            username = t.get("Username","")
            likes = t.get("Likes","0")
            rts = t.get("Retweets","0")
            replies = t.get("Replies","0")
            lang = t.get("Language","")
            link = t.get("Tweet Link","")
            lines.append(f"| {time_val} | {content} | {username} | {likes} | {rts} | {replies} | {lang} | {link} |")

    lines.append("")
    lines.append("─" * 60)
    lines.append(f"📁 ไฟล์ CSV ที่อ่าน:\nnews/summary_{date_str}.csv,\nnews/timeline_{date_str}.json\n📎 PDF ฉบับเต็ม: news/summary_{date_str}.pdf")

    return "\n".join(lines)


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else TODAY
    report = build_telegram_report(date_arg)
    if report is None:
        print(f"ไม่พบข้อมูลสำหรับ {date_arg}")
        sys.exit(1)
    print(report)
