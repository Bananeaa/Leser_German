import urllib.request
import json
import re
from datetime import datetime

FEED_URLS = [
    "https://rss.dw.com/xml/DKpodcast_lgn_de",   # DW Langsam gesprochene Nachrichten
    "https://feeds.feedburner.com/DWLangsamGesprochenNachrichten",  # backup
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LeserApp/1.0)"
}

def fetch_feed(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")

def parse_rss(xml):
    articles = []
    items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
    for item in items[:10]:
        def tag(name):
            m = re.search(rf"<{name}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", item, re.DOTALL)
            return m.group(1).strip() if m else ""
        title   = tag("title")
        desc    = tag("description")
        pubdate = tag("pubDate")
        link    = tag("link")
        if not title:
            continue
        # clean html tags from description
        desc = re.sub(r"<[^>]+>", "", desc).strip()
        # parse date
        try:
            dt = datetime.strptime(pubdate[:25].strip(), "%a, %d %b %Y %H:%M:%S")
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = pubdate[:10] if pubdate else ""
        # split description into paragraphs (sentences grouped by 2)
        sentences = re.split(r"(?<=[.!?])\s+", desc)
        paragraphs = []
        for i in range(0, len(sentences), 2):
            p = " ".join(sentences[i:i+2]).strip()
            if p:
                paragraphs.append(p)
        articles.append({
            "id":    re.sub(r"[^a-z0-9]", "-", title.lower())[:40],
            "title": title,
            "date":  date_str,
            "level": "A2",
            "paragraphs": paragraphs or [desc],
            "translations": []
        })
    return articles

articles = []
for url in FEED_URLS:
    print(f"Trying: {url}")
    try:
        xml = fetch_feed(url)
        if "<item>" not in xml:
            print("  No items in feed")
            continue
        articles = parse_rss(xml)
        print(f"  OK — {len(articles)} articles")
        break
    except Exception as e:
        print(f"  Failed: {e}")

if not articles:
    print("All feeds failed — writing empty list")

with open("articles.json", "w", encoding="utf-8") as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)
print("Saved → articles.json")
