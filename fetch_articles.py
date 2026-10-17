import json
import datetime
import re
import urllib.request
from pathlib import Path

OUTPUT = Path("articles.json")
MAX_ARTICLES = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9",
}

FEED_URLS = [
    "https://www.nachrichtenleicht.de/api/partnerfeeds/nachrichtenleicht/nachrichten?format=rss",
    "https://www.nachrichtenleicht.de/nachrichtenleicht-100.rss",
    "https://www.nachrichtenleicht.de/rss",
]

def fetch_url(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")

def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()

def parse_rss(xml):
    items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
    articles = []
    colors = ["1", "2", "3"]
    heights = ["tall", "mid", "short", "mid", "tall", "short"]
    for i, item in enumerate(items[:MAX_ARTICLES]):
        def tag(name):
            m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", item, re.DOTALL)
            return clean(m.group(1)) if m else ""
        title = tag("title")
        link  = tag("link") or tag("guid")
        desc  = tag("description") or tag("content:encoded")
        date  = tag("pubDate") or str(datetime.date.today())
        if not title:
            continue
        chunks = re.split(r"\n\n+", desc)
        paragraphs = [p for p in (clean(c) for c in chunks) if len(p) > 40]
        if not paragraphs:
            paragraphs = [clean(desc)] if clean(desc) else [title]
        articles.append({
            "id": re.sub(r"[^a-z0-9]", "-", title.lower())[:40],
            "title": title,
            "date": date[:16],
            "url": link,
            "desc": paragraphs[0][:180] + ("…" if len(paragraphs[0]) > 180 else ""),
            "paragraphs": [{"de": p, "en": ""} for p in paragraphs],
            "source": "nachrichtenleicht.de",
            "color": colors[i % 3],
            "height": heights[i % 6],
        })
    return articles

def fetch():
    articles = []
    for url in FEED_URLS:
        print(f"Trying: {url}")
        try:
            xml = fetch_url(url)
            if "<item>" in xml:
                articles = parse_rss(xml)
                print(f"✓ Got {len(articles)} articles from {url}")
                break
        except Exception as e:
            print(f"  Failed: {e}")
    if not articles:
        print("All feeds failed — writing empty list")
    OUTPUT.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved → {OUTPUT}")

if __name__ == "__main__":
    fetch()
