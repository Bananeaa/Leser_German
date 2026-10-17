import urllib.request
import urllib.parse
import json
import re
import time
from datetime import datetime

# Tagesschau has a public RSS and allows scraping from cloud IPs
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
    """Extract article paragraphs from a tagesschau.de page."""
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)

    # Tagesschau article body is in <div class="seitenkopf__title"> and
    # paragraphs inside <p class="textabsatz"> or <div class="m-ten-teaser__...">
    # Most reliably: find all <p class="textabsatz ..."> tags
    paras = re.findall(r'<p[^>]+class="[^"]*textabsatz[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)

    # Fallback: any <p> inside article tag
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
        # Only keep German-language article links
        if "tagesschau.de" not in link:
            continue
        try:
            dt = datetime.strptime(pubdate[:25].strip(), "%a, %d %b %Y %H:%M:%S")
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = pubdate[:10] if pubdate else ""
        result.append({"title": title, "link": link, "date": date_str, "desc": desc})
    return result

# ── Main ──────────────────────────────────────────────────────────────────────

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
        # Use RSS description as fallback
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
    # Build paragraphs as [{de, en}] pairs — matches renderArticle in leser.html
    para_pairs = [{"de": p, "en": translations[i] if i < len(translations) else ""} for i, p in enumerate(paras)]
    # Use first paragraph (truncated) as description for shelf card
    desc = paras[0][:120].rsplit(" ", 1)[0] + "…" if paras else ""
    articles.append({
        "id":         art_id,
        "title":      item["title"],
        "date":       item["date"],
        "level":      "B1",
        "desc":       desc,
        "source":     "tagesschau.de",
        "url":        item["link"],
        "paragraphs": para_pairs,
    })

print(f"\nDone — {len(articles)} articles")
with open("articles.json", "w", encoding="utf-8") as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)
print("Saved → articles.json")

# ── Inject into leser.html ────────────────────────────────────────────────────
if articles:
    try:
        with open("leser.html", "r", encoding="utf-8") as f:
            html = f.read()
        articles_json = json.dumps(articles, ensure_ascii=False, indent=2)
        new_html = re.sub(
            r'const FALLBACK_ARTICLES = \[.*?\];',
            f'const FALLBACK_ARTICLES = {articles_json};',
            html,
            flags=re.DOTALL
        )
        if new_html != html:
            with open("leser.html", "w", encoding="utf-8") as f:
                f.write(new_html)
            print("Injected articles into leser.html")
        else:
            print("WARNING: FALLBACK_ARTICLES pattern not found in leser.html")
    except FileNotFoundError:
        print("leser.html not found — skipping inject")
