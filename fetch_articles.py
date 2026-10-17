import urllib.request
import urllib.parse
import json
import re
import time
from datetime import datetime

FEED_URL = "https://www.tagesschau.de/xml/rss2/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")

def translate_mymemory(text):
    if not text.strip():
        return ""
    encoded = urllib.parse.quote(text[:500])
    url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair=de|en"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode())
        t = data.get("responseData", {}).get("translatedText", "")
        if t and t.upper() != text.upper():
            return t
    except Exception as e:
        print(f"    translate failed: {e}")
    return ""

def extract_tagesschau(html):
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    paras = re.findall(r'<p[^>]+class="[^"]*textabsatz[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
    if not paras:
        m = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)
        if m:
            paras = re.findall(r'<p[^>]*>(.*?)</p>', m.group(1), re.DOTALL)
    result = []
    for p in paras:
        text = re.sub(r"<[^>]+>", "", p).strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) > 60 and "Cookie" not in text and not text.startswith("©"):
            result.append(text)
    return result[:10]

def parse_rss(xml):
    items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
    result = []
    for item in items[:6]:
        def tag(name):
            m = re.search(rf"<{name}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", item, re.DOTALL)
            return m.group(1).strip() if m else ""
        title   = tag("title")
        link    = tag("link")
        pubdate = tag("pubDate")
        desc    = tag("description")
        if not title or not link:
            continue
        if "tagesschau.de" not in link:
            continue
        try:
            dt = datetime.strptime(pubdate[:25].strip(), "%a, %d %b %Y %H:%M:%S")
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = pubdate[:10] if pubdate else ""
        result.append({"title": title, "link": link, "date": date_str, "desc": desc})
    return result

print(f"Fetching feed: {FEED_URL}")
try:
    xml = fetch(FEED_URL)
    feed_items = parse_rss(xml)
    print(f"Found {len(feed_items)} items")
except Exception as e:
    print(f"Feed failed: {e}")
    feed_items = []

articles = []
for item in feed_items:
    print(f"\nArticle: {item['title'][:60]}")
    try:
        html = fetch(item["link"])
        paras = extract_tagesschau(html)
        print(f"  Extracted {len(paras)} paragraphs")
    except Exception as e:
        print(f"  Fetch failed: {e}")
        desc = re.sub(r"<[^>]+>", "", item["desc"]).strip()
        paras = [desc] if len(desc) > 60 else []
    if not paras:
        print("  Skipping — no text")
        continue
    translations = []
    for i, p in enumerate(paras):
        print(f"  Translating {i+1}/{len(paras)}...")
        t = translate_mymemory(p)
        translations.append(t)
        time.sleep(0.4)
    art_id = re.sub(r"[^a-z0-9]", "-", item["title"].lower())[:40].strip("-")
    articles.append({
        "id":           art_id,
        "title":        item["title"],
        "date":         item["date"],
        "level":        "B1",
        "paragraphs":   paras,
        "translations": translations,
    })

print(f"\nDone — {len(articles)} articles")
with open("articles.json", "w", encoding="utf-8") as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)
print("Saved → articles.json")

# Also inject articles into leser.html
try:
    with open("leser.html", "r", encoding="utf-8") as f:
        html = f.read()
    articles_json = json.dumps(articles, ensure_ascii=False)
    # Replace the FALLBACK_ARTICLES array in the HTML
    html = re.sub(
        r'const FALLBACK_ARTICLES = \[.*?\];',
        f'const FALLBACK_ARTICLES = {articles_json};',
        html, flags=re.DOTALL
    )
    with open("leser.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Injected articles into leser.html")
except Exception as e:
    print(f"HTML inject failed: {e}")
