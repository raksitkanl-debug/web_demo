import os
import json
import requests
import argparse
import csv
import shutil
import sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
MAX_TWEETS_PER_RUN = int(os.getenv("MAX_TWEETS_PER_RUN", 5))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKENS_FILE = os.path.join(SCRIPT_DIR, "tokens.json")
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
NEWS_DIR = "/Users/kumning/twitter/news"
LATEST_RUN_FILE = os.path.join(NEWS_DIR, "latest_twitter_fetch.json")

# GMT+7 Bangkok
TZ_BKK = timezone(timedelta(hours=7))

# ─── State File ─────────────────────────────────────────────────────────────────
def get_date_str():
    now = datetime.now(TZ_BKK)
    # For date used in filenames: always use "yesterday 9am" as the date
    # because the window is yesterday 9am → today 9am
    today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now.hour < 6:
        # Before 6am, still yesterday's window
        dt = today_6am - timedelta(days=1)
    else:
        dt = today_6am
    return dt.strftime("%Y%m%d")

LAST_RUN_FILE = os.path.join(SCRIPT_DIR, "last_run.txt")

def save_last_run(dt_utc):
    with open(LAST_RUN_FILE, "w") as f:
        f.write(fmt_iso(dt_utc))

def load_last_run():
    if not os.path.exists(LAST_RUN_FILE):
        return None
    with open(LAST_RUN_FILE) as f:
        return datetime.fromisoformat(f.read().strip().replace("Z", "+00:00"))

# ─── Time Range Helpers ────────────────────────────────────────────────────────
def get_time_window() -> tuple[datetime, datetime]:
    """
    Calculate window:
      start = last_run.txt if exists, else Yesterday 06:00:00 GMT+7
      end   = Now (UTC)
    """
    now_bkk = datetime.now(TZ_BKK)
    now_utc = now_bkk.astimezone(timezone.utc)

    last_run = load_last_run()
    if last_run:
        start_utc = last_run
    else:
        # First run of the day: start from yesterday 6am GMT+7
        today_6am = now_bkk.replace(hour=6, minute=0, second=0, microsecond=0)
        if now_bkk.hour < 6:
            # Before 6am, use yesterday's 6am
            start_bkk = today_6am - timedelta(days=1)
        else:
            start_bkk = today_6am
        start_utc = start_bkk.astimezone(timezone.utc)

    return start_utc, now_utc

def fmt_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def fmt_display(dt_utc: datetime) -> str:
    return dt_utc.astimezone(TZ_BKK).strftime("%d %b %Y  %H:%M น. (GMT+7)")

def parse_tweet_time(created_raw: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(created_raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse: {created_raw}")

# ─── Token Management ──────────────────────────────────────────────────────────
def save_tokens(tokens):
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)

def load_tokens():
    if not os.path.exists(TOKENS_FILE):
        return None
    with open(TOKENS_FILE, "r") as f:
        return json.load(f)

def refresh_tokens(refresh_token: str) -> dict:
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
    }
    auth = (CLIENT_ID, CLIENT_SECRET) if CLIENT_SECRET else None
    resp = requests.post(TOKEN_URL, data=payload, auth=auth)
    resp.raise_for_status()
    new_tokens = resp.json()
    save_tokens(new_tokens)
    return new_tokens

def get_valid_token() -> str:
    tokens = load_tokens()
    if not tokens or "refresh_token" not in tokens:
        raise RuntimeError("No tokens found. Run twitter_fetcher.py --auth first.")

    try:
        print("  🔄 Refreshing access token...")
        new_tokens = refresh_tokens(tokens["refresh_token"])
        return new_tokens["access_token"]
    except Exception as e:
        print(f"  ⚠️  Refresh failed ({e}). Attempting to use existing access token...")
        return tokens["access_token"]

# ─── API Fetches ───────────────────────────────────────────────────────────────
def get_user_me(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get("https://api.twitter.com/2/users/me", headers=headers)
    response.raise_for_status()
    return response.json()["data"]["id"]

def get_timeline_in_window(access_token, user_id, start_utc, end_utc):
    url = f"https://api.twitter.com/2/users/{user_id}/timelines/reverse_chronological"
    headers = {"Authorization": f"Bearer {access_token}"}

    page_size = min(max(MAX_TWEETS_PER_RUN, 10), 100)
    base_params = {
        "max_results": page_size,
        "start_time": fmt_iso(start_utc),
        "end_time": fmt_iso(end_utc),
        "tweet.fields": "created_at,author_id,text,public_metrics,lang",
        "expansions": "author_id",
        "user.fields": "name,username",
    }

    all_tweets = []
    all_users = {}
    next_token = None
    page = 1

    while True:
        params = {**base_params}
        if next_token:
            params["pagination_token"] = next_token

        print(f"  📄 Fetching Page {page}...", end=" ", flush=True)
        resp = requests.get(url, headers=headers, params=params)

        if resp.status_code != 200:
            print(f"Error {resp.status_code}: {resp.text}")
            break

        data = resp.json()
        tweets = data.get("data", [])
        users = data.get("includes", {}).get("users", [])

        remaining = MAX_TWEETS_PER_RUN - len(all_tweets)
        tweets_to_add = tweets[:remaining]
        all_tweets.extend(tweets_to_add)
        for u in users:
            all_users[u["id"]] = u

        print(f"Got {len(tweets)} tweets  (Total: {len(all_tweets)})")

        if len(all_tweets) >= MAX_TWEETS_PER_RUN:
            print(f"  🛑 Reached limit of {MAX_TWEETS_PER_RUN} tweets.")
            break

        next_token = data.get("meta", {}).get("next_token")
        if not next_token or not tweets:
            break
        page += 1

    return {
        "data": all_tweets,
        "includes": {"users": list(all_users.values())},
        "meta": {"total_count": len(all_tweets)}
    }

# ─── Merge Helpers ─────────────────────────────────────────────────────────────
def load_existing_json(json_path):
    """Load existing timeline JSON if exists."""
    if not os.path.exists(json_path):
        return {"data": [], "includes": {"users": []}, "meta": {"total_count": 0}}
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)

def load_existing_csv(csv_path):
    """Load existing tweet IDs from CSV for dedup."""
    existing_ids = set()
    if not os.path.exists(csv_path):
        return existing_ids
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Extract tweet ID from link
            link = row.get("Tweet Link", "")
            if link:
                # https://x.com/username/status/123456
                parts = link.split("/")
                if parts:
                    existing_ids.add(parts[-1])
    return existing_ids

def merge_data(existing_data, new_data):
    """Merge new tweets with existing, dedupe by tweet ID."""
    existing_ids = {t["id"] for t in existing_data.get("data", [])}
    existing_user_ids = {u["id"] for u in existing_data.get("includes", {}).get("users", [])}

    merged_tweets = list(existing_data.get("data", []))
    merged_users = {u["id"]: u for u in existing_data.get("includes", {}).get("users", [])}

    new_tweets = new_data.get("data", [])
    for tweet in new_tweets:
        if tweet["id"] not in existing_ids:
            merged_tweets.append(tweet)
            # Add author to users dict
            # Users are added from expansions in new_data

    # Merge users from new data
    new_users = new_data.get("includes", {}).get("users", [])
    for user in new_users:
        if user["id"] not in merged_users:
            merged_users[user["id"]] = user

    return {
        "data": merged_tweets,
        "includes": {"users": list(merged_users.values())},
        "meta": {"total_count": len(merged_tweets)}
    }

def filter_new_data(existing_data, new_data):
    """Return only tweets that are not already present in existing daily data."""
    existing_ids = {t["id"] for t in existing_data.get("data", [])}
    new_tweets = [tweet for tweet in new_data.get("data", []) if tweet.get("id") not in existing_ids]
    new_author_ids = {tweet.get("author_id") for tweet in new_tweets}
    new_users = [
        user for user in new_data.get("includes", {}).get("users", [])
        if user.get("id") in new_author_ids
    ]
    return {
        "data": new_tweets,
        "includes": {"users": new_users},
        "meta": {"total_count": len(new_tweets)}
    }

# ─── Display ───────────────────────────────────────────────────────────────────
def display_timeline(data, start_utc, end_utc):
    tweets = data.get("data", [])
    users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

    W = 70
    print(f"\n{'═'*W}")
    print(f"  📰  DAILY SUMMARY — HOME TIMELINE")
    print(f"{'─'*W}")
    print(f"  🕕 เริ่ม  : {fmt_display(start_utc)}")
    print(f"  🕕 สิ้นสุด: {fmt_display(end_utc)}")
    print(f"  📊 พบทั้งหมด {len(tweets)} tweets")
    print(f"{'═'*W}")

    if not tweets:
        print("\n  ⚠️  ไม่มี tweet ในช่วงเวลานี้\n")
        return

    for i, tweet in enumerate(tweets, 1):
        author = users.get(tweet.get("author_id"), {})
        metrics = tweet.get("public_metrics", {})
        name = author.get("name", "Unknown")
        uname = author.get("username", "?")
        lang = tweet.get("lang", "?")

        created_bkk = parse_tweet_time(
            tweet.get("created_at", "1970-01-01T00:00:00Z")
        ).astimezone(TZ_BKK).strftime("%d/%m/%Y  %H:%M น.")

        print(f"\n  [{i:03d}]  👤 {name} (@{uname})")
        print(f"         🕐 {created_bkk}   🌐 ภาษา: {lang}")
        print(f"  {'─'*66}")

        text = tweet["text"]
        print(f"  {text}")

        print(f"\n       ❤️  {metrics.get('like_count',0):>6,}  "
              f"🔁 {metrics.get('retweet_count',0):>5,}  "
              f"💬 {metrics.get('reply_count',0):>5,}")

    print(f"\n{'═'*W}\n")

# ─── CSV Export ────────────────────────────────────────────────────────────────
def save_to_csv(data, filename):
    tweets = data.get("data", [])
    users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

    headers = [
        "Date (GMT+7)", "Author", "Username", "Text",
        "Likes", "Retweets", "Replies", "Language", "Tweet Link"
    ]

    with open(filename, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for tweet in tweets:
            author = users.get(tweet.get("author_id"), {})
            name = author.get("name", "Unknown")
            uname = author.get("username", "Unknown")
            created_bkk = parse_tweet_time(
                tweet.get("created_at", "1970-01-01T00:00:00Z")
            ).astimezone(TZ_BKK).strftime("%Y-%m-%d %H:%M")

            tweet_id = tweet.get("id")
            link = f"https://x.com/{uname}/status/{tweet_id}"

            metrics = tweet.get("public_metrics", {})

            writer.writerow([
                created_bkk,
                name,
                uname,
                tweet.get("text", "").replace("\n", " "),
                metrics.get("like_count", 0),
                metrics.get("retweet_count", 0),
                metrics.get("reply_count", 0),
                tweet.get("lang", ""),
                link
            ])
    print(f"  📊 CSV Exported -> {filename}")

def run_slot_str(dt_utc: datetime) -> str:
    return dt_utc.astimezone(TZ_BKK).strftime("%H%M")

def save_latest_run_manifest(payload):
    os.makedirs(NEWS_DIR, exist_ok=True)
    with open(LATEST_RUN_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)

# ─── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Determine workspace news directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    news_dir = NEWS_DIR
    os.makedirs(news_dir, exist_ok=True)

    start_utc, end_utc = get_time_window()
    date_str = get_date_str()
    slot_str = run_slot_str(end_utc)
    date_dir = os.path.join(news_dir, date_str)
    run_dir = os.path.join(date_dir, f"{date_str}-{slot_str}")
    os.makedirs(run_dir, exist_ok=True)
    json_file = os.path.join(news_dir, f"timeline_{date_str}.json")
    csv_file = os.path.join(news_dir, f"summary_{date_str}.csv")
    run_json_file = os.path.join(run_dir, f"timeline_{date_str}_{slot_str}.json")
    run_csv_file = os.path.join(run_dir, f"summary_{date_str}_{slot_str}.csv")

    print("=" * 70)
    print("  🌅  DAILY SUMMARY AGENT — Twitter/X Home Timeline")
    print("=" * 70)
    print(f"  Date ID: {date_str}")
    print(f"  Range (GMT+7): {fmt_display(start_utc)} → {fmt_display(end_utc)}")

    # Load existing data for merging
    existing_data = load_existing_json(json_file)
    existing_count = len(existing_data.get("data", []))
    if existing_count > 0:
        print(f"  📂 Found existing {existing_count} tweets — will merge")

    try:
        token = get_valid_token()
        user_id = get_user_me(token)

        print(f"\n  📡 Fetching timeline for User ID: {user_id}...")
        new_data = get_timeline_in_window(token, user_id, start_utc, end_utc)

        new_count = len(new_data.get("data", []))
        print(f"\n  🔀 Merging {new_count} new tweets with {existing_count} existing...")

        # Save per-run unique data first. This is the input for hourly mini-summary.
        unique_new_data = filter_new_data(existing_data, new_data)
        unique_new_count = len(unique_new_data.get("data", []))
        print(f"  🧩 Unique new tweets for this run: {unique_new_count}")

        with open(run_json_file, "w", encoding="utf-8") as f:
            json.dump(unique_new_data, f, ensure_ascii=False, indent=2)
        print(f"  💾 Run JSON Saved -> {run_json_file} ({unique_new_count} tweets)")

        save_to_csv(unique_new_data, run_csv_file)

        # Merge
        merged_data = merge_data(existing_data, new_data)
        total_count = len(merged_data.get("data", []))

        display_timeline(merged_data, start_utc, end_utc)

        # Save merged JSON
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=2)
        print(f"  💾 JSON Saved -> {json_file} ({total_count} tweets)")

        # Save merged CSV
        save_to_csv(merged_data, csv_file)

        # Save last run time
        save_last_run(end_utc)
        save_latest_run_manifest({
            "date": date_str,
            "slot": slot_str,
            "date_dir": date_dir,
            "run_dir": run_dir,
            "run_csv": run_csv_file,
            "run_json": run_json_file,
            "daily_csv": csv_file,
            "daily_json": json_file,
            "start_utc": fmt_iso(start_utc),
            "end_utc": fmt_iso(end_utc),
            "fetched_count": new_count,
            "unique_new_count": unique_new_count,
            "daily_total_count": total_count,
        })
        print(f"\n  ✅ Done! Total: {total_count} tweets (was {existing_count}, added {new_count})")
        print(f"  🧾 Latest run manifest -> {LATEST_RUN_FILE}")

    except Exception as e:
        print(f"  ❌ Error: {e}")
        sys.exit(1)
