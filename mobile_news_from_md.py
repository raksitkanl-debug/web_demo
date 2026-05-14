#!/usr/bin/env python3
"""Build the premium mobile news HTML page from a daily Markdown file.

Example:
  python mobile_news_from_md.py summary20260507.md
  python mobile_news_from_md.py C:\path\summary20260507.md -o summary_20260507.html
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path

from markdown_renderer import render_basic_markdown


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = SCRIPT_DIR / "summary_20260506.html"
SOURCE_MARKER = '<main id="source-content" class="hidden">'
SCRIPT_MARKER = "</main>\n<script>"
TWITTER_STATUS_RE = re.compile(r"https://(?:x|twitter)\.com/[^/\s)]+/status/(\d+)", re.IGNORECASE)


def default_output_path(md_path: Path) -> Path:
    match = re.search(r"(\d{8})", md_path.stem)
    if match:
        return md_path.with_name(f"summary_{match.group(1)}.html")
    return md_path.with_suffix(".html")


def normalize_report_markdown(markdown_text: str) -> str:
    text = markdown_text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def best_video_variant(media: dict) -> str:
    variants = media.get("video_info", {}).get("variants", [])
    mp4_variants = [
        variant
        for variant in variants
        if variant.get("content_type") == "video/mp4" and variant.get("url")
    ]
    if not mp4_variants:
        return ""
    best = sorted(mp4_variants, key=lambda item: item.get("bitrate", 0), reverse=True)[0]
    return best["url"]


def append_unique(output: list[dict[str, str]], item: dict[str, str]) -> None:
    if item.get("url") and item not in output:
        output.append(item)


def extract_media_entities(tweet_data: dict) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for media in tweet_data.get("mediaDetails") or []:
        media_type = media.get("type")
        if media_type == "photo" and media.get("media_url_https"):
            append_unique(output, {"type": "photo", "url": media["media_url_https"]})
            continue

        video_url = best_video_variant(media)
        if video_url:
            item = {"type": "video", "url": video_url}
            if media.get("media_url_https"):
                item["poster"] = media["media_url_https"]
            append_unique(output, item)

    if not output:
        for photo in tweet_data.get("photos") or []:
            if photo.get("url"):
                append_unique(output, {"type": "photo", "url": photo["url"]})
    return output


def extract_card_images(tweet_data: dict) -> list[dict[str, str]]:
    values = (tweet_data.get("card") or {}).get("binding_values") or {}
    preferred_keys = [
        "photo_image_full_size_large",
        "summary_photo_image_large",
        "thumbnail_image_large",
        "thumbnail_image",
        "player_image_large",
        "player_image",
    ]

    output: list[dict[str, str]] = []
    for key in preferred_keys:
        image = (values.get(key) or {}).get("image_value") or {}
        if image.get("url"):
            append_unique(output, {"type": "photo", "url": image["url"]})
            break

    if not output:
        for value in values.values():
            image = (value or {}).get("image_value") or {}
            if image.get("url"):
                append_unique(output, {"type": "photo", "url": image["url"]})
                break
    return output


def expanded_article_urls(tweet_data: dict) -> list[str]:
    urls: list[str] = []
    for item in (tweet_data.get("entities") or {}).get("urls") or []:
        expanded = item.get("expanded_url")
        if expanded and expanded.startswith(("http://", "https://")):
            urls.append(expanded)
    return urls


def fetch_open_graph_image(url: str, timeout: int = 12) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                return ""
            html = response.read(700_000).decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError):
        return ""

    patterns = [
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            image_url = unescape(match.group(1).strip())
            if image_url.startswith("//"):
                return f"https:{image_url}"
            if image_url.startswith(("http://", "https://")):
                return image_url
    return ""


def extract_tweet_media(tweet_data: dict) -> list[dict[str, str]]:
    output = extract_media_entities(tweet_data)
    if not output and tweet_data.get("quoted_tweet"):
        output = extract_tweet_media(tweet_data["quoted_tweet"])
    if not output:
        output = extract_card_images(tweet_data)
    if not output:
        for article_url in expanded_article_urls(tweet_data):
            image_url = fetch_open_graph_image(article_url)
            if image_url:
                append_unique(output, {"type": "photo", "url": image_url})
                break
    return output


def fetch_tweet_media(tweet_id: str, timeout: int = 12) -> list[dict[str, str]]:
    url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=th&token=a"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    return extract_tweet_media(data)


def collect_tweet_media(markdown_text: str) -> dict[str, list[dict[str, str]]]:
    tweet_ids = sorted(set(TWITTER_STATUS_RE.findall(markdown_text)))
    media_by_id: dict[str, list[dict[str, str]]] = {}
    for tweet_id in tweet_ids:
        media = fetch_tweet_media(tweet_id)
        if media:
            media_by_id[tweet_id] = media
    return media_by_id


def split_template(template_html: str) -> tuple[str, str]:
    source_start = template_html.find(SOURCE_MARKER)
    if source_start < 0:
        raise ValueError(f"Template missing marker: {SOURCE_MARKER}")

    content_start = source_start + len(SOURCE_MARKER)
    source_end = template_html.find(SCRIPT_MARKER, content_start)
    if source_end < 0:
        raise ValueError(f"Template missing marker after source content: {SCRIPT_MARKER!r}")

    prefix = template_html[:content_start]
    suffix = template_html[source_end:]
    return prefix, suffix


def build_mobile_news_html(md_path: Path, template_path: Path = DEFAULT_TEMPLATE) -> str:
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")
    if not template_path.exists():
        raise FileNotFoundError(f"Template HTML not found: {template_path}")

    markdown_text = normalize_report_markdown(read_utf8(md_path))
    source_body = render_basic_markdown(markdown_text)
    tweet_media_json = json.dumps(collect_tweet_media(markdown_text), ensure_ascii=False)
    prefix, suffix = split_template(read_utf8(template_path))
    suffix = suffix.replace(
        SCRIPT_MARKER,
        f'</main>\n<script id="tweet-media-data" type="application/json">{tweet_media_json}</script>\n<script>',
        1,
    )
    return f"{prefix}\n{source_body}\n{suffix}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a daily summary Markdown file into the premium mobile news HTML template.",
    )
    parser.add_argument("markdown", help="Input Markdown file, for example summary20260507.md")
    parser.add_argument(
        "-o",
        "--output",
        help="Output HTML path. Defaults to summary_YYYYMMDD.html beside the input file.",
    )
    parser.add_argument(
        "--template",
        default=str(DEFAULT_TEMPLATE),
        help="Template HTML path. Defaults to summary_20260506.html in this project.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    md_path = Path(args.markdown).expanduser().resolve()
    template_path = Path(args.template).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve() if args.output else default_output_path(md_path).resolve()

    html = build_mobile_news_html(md_path, template_path)
    output_path.write_text(html, encoding="utf-8")
    print(f"HTML ready: {output_path}")


if __name__ == "__main__":
    main()
