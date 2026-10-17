import urllib.request
import urllib.parse
import json
import re
import time
from datetime import datetime

FEED_URL = "https://rss.dw.com/xml/DKpodcast_lgn_de"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

def fetch(url, is_xml=False):
    h = dict(HEADERS)
    if is_xml:
        h["Accept"] = "application/rss+xml,application/xml;q=0.9,*/*;q=0.8"
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")

def translate_mymemory(text, retries=2):
    if not text.strip():
        return ""
    encoded = urllib.parse.quote(text[:500])
    url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair=de|en"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read().decode())
            t = data.get("responseData", {}).get("translatedText", "")
            if t and t.upper() != text.upper():
                return t
        except Exception as e:
            print(f"    translate attempt {attempt+1} failed: {e}")
            time.sleep(1)
    return ""

def extract_article_text(html):
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    body = ""
    for pattern in [
        r'<div[^>]+class="[^"]*longText[^"]*"[^>]*>(.*?)</div>\s*</div>',
        r'<div[^>]+class="[^"]*richtext[^"]*"[^>]*>(.*?)</div>\s*</div>',
        r'<article[^>]*>(.*?)</article>',
        r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
    ]:
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m:
            body = m.group(1)
            break
    if not body:
        body = html
    paras = re.findall(r"<p[^>]*>(.*?)</p>", body, re.DOTALL)
    result = []
    for p in paras:
        text = re.sub(r"<[^>]+>", "", p).strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) > 60 and not text.startswith("©") and "Cookie" not in text:
            result.append(text)
    return result[:12]

def parse_feed(xml):
    items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
    result = []
    for item in items[:5]:
        def tag(name):
            m = re.search(rf"<{name}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", item, re.DOTALL)
            return m.group(1).strip() if m else ""
        title   = tag("title")
        pubdate = tag("pubDate")
        link    = tag("link") or tag("guid")
        if not title or not link:
            continue
        try:
            dt = datetime.strptime(pubdate[:25].strip(), "%a, %d %b %Y %H:%M:%S")
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = pubdate[:10] if pubdate else ""
        result.append({"title": title, "date": date_str, "link": link})
    return result

print(f"Fetching feed: {FEED_URL}")
try:
    xml = fetch(FEED_URL, is_xml=True)
except Exception as e:
    print(f"Feed fetch failed: {e}")
    xml = ""

feed_items = parse_feed(xml) if xml else []
print(f"Found {len(feed_items)} items in feed")

articles = []
for item in feed_items:
    print(f"\nArticle: {item['title'][:60]}")
    print(f"  URL: {item['link']}")
    try:
        html = fetch(item["link"])
        paragraphs_de = extract_article_text(html)
        print(f"  Extracted {len(paragraphs_de)} paragraphs")
    except Exception as e:
        print(f"  Fetch failed: {e}")
        paragraphs_de = []
    if not paragraphs_de:
        print("  Skipping — no text extracted")
        continue
    translations = []
    for i, p in enumerate(paragraphs_de):
        print(f"  Translating paragraph {i+1}/{len(paragraphs_de)}...")
        t = translate_mymemory(p)
        translations.append(t)
        time.sleep(0.3)
    art_id = re.sub(r"[^a-z0-9]", "-", item["title"].lower())[:40]
    articles.append({
        "id":           art_id,
        "title":        item["title"],
        "date":         item["date"],
        "level":        "B1",
        "paragraphs":   paragraphs_de,
        "translations": translations,
    })

print(f"\nTotal articles: {len(articles)}")
if not articles:
    print("No articles extracted — writing empty list")

with open("articles.json", "w", encoding="utf-8") as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)
print("Saved → articles.json")
