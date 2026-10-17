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

# Tagesschau URL path → German tag name
TAG_MAP = {
    "/inland/":      "Inland",
    "/ausland/":     "Ausland",
    "/wirtschaft/":  "Wirtschaft",
    "/sport/":       "Sport",
    "/wissen/":      "Wissen",
    "/kultur/":      "Kultur",
    "/faktenfinder/":"Fakten",
    "/investigativ/":"Investigativ",
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

def wiktionary_lookup(word):
    """Return {en, article, level} or None. Uses English Wiktionary REST API."""
    url = f"https://en.wiktionary.org/api/rest_v1/page/summary/{urllib.parse.quote(word)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Leser-German-App/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        desc = data.get("description", "") or ""
        extract = data.get("extract", "") or ""
        # extract article (der/die/das) from description e.g. "das Haus"
        article = None
        m = re.search(r'\b(der|die|das)\b', desc.lower())
        if m:
            article = m.group(1)
        # extract level if mentioned (A1-C2)
        level = None
        m2 = re.search(r'\b([ABC][12])\b', desc + extract)
        if m2:
            level = m2.group(1)
        # build short English meaning from extract (first sentence)
        meaning = extract.split(".")[0].strip() if extract else ""
        if not meaning:
            return None
        # trim to reasonable popup length
        if len(meaning) > 80:
            meaning = meaning[:77] + "…"
        result = {"en": meaning}
        if article:
            result["article"] = article
        if level:
            result["level"] = level
        return result
    except Exception:
        return None

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
        if not title or not link or "tagesschau.de" not in link:
            continue
        try:
            dt = datetime.strptime(pubdate[:25].strip(), "%a, %d %b %Y %H:%M:%S")
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = pubdate[:10] if pubdate else ""
        result.append({"title": title, "link": link, "date": date_str, "desc": desc})
    return result

def detect_tag(url):
    for path, label in TAG_MAP.items():
        if path in url:
            return label
    return "Aktuell"

def extract_words(paras):
    """Return unique lowercase words (letters only, length >= 3) from paragraph list."""
    words = set()
    for p in paras:
        for w in re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", p):
            words.add(w.lower())
    return words

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
all_words = set()   # collect all unique words across all articles

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

    para_pairs = [{"de": p, "en": translations[i] if i < len(translations) else ""} for i, p in enumerate(paras)]
    desc = paras[0][:120].rsplit(" ", 1)[0] + "…" if paras else ""
    art_id = re.sub(r"[^a-z0-9]", "-", item["title"].lower())[:40].strip("-")

    articles.append({
        "id":         art_id,
        "title":      item["title"],
        "date":       item["date"],
        "level":      "B1",
        "tag":        detect_tag(item["link"]),
        "desc":       desc,
        "source":     "tagesschau.de",
        "url":        item["link"],
        "paragraphs": para_pairs,
    })

    all_words.update(extract_words(paras))

print(f"\nDone — {len(articles)} articles, {len(all_words)} unique words")

# ── Wiktionary dictionary lookup ──────────────────────────────────────────────
print("\nBuilding dictionary from Wiktionary…")
dictionary = {}
words_list = sorted(all_words)
for i, word in enumerate(words_list):
    entry = wiktionary_lookup(word)
    if entry:
        dictionary[word] = entry
        print(f"  [{i+1}/{len(words_list)}] {word} → {entry['en'][:40]}")
    else:
        print(f"  [{i+1}/{len(words_list)}] {word} → (not found)")
    time.sleep(0.15)   # be polite to Wiktionary

print(f"Dictionary: {len(dictionary)} entries")

# ── Save articles.json ────────────────────────────────────────────────────────
with open("articles.json", "w", encoding="utf-8") as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)
print("Saved → articles.json")

# ── Inject into index.html ────────────────────────────────────────────────────
if articles:
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()

        articles_json = json.dumps(articles, ensure_ascii=False, indent=2)
        new_html = re.sub(
            r'const FALLBACK_ARTICLES = \[.*?\];',
            f'const FALLBACK_ARTICLES = {articles_json};',
            html,
            flags=re.DOTALL
        )

        dict_json = json.dumps(dictionary, ensure_ascii=False)
        new_html = re.sub(
            r'const WIKT_DICT = \{.*?\};',
            f'const WIKT_DICT = {dict_json};',
            new_html,
            flags=re.DOTALL
        )

        if new_html != html:
            with open("index.html", "w", encoding="utf-8") as f:
                f.write(new_html)
            print("Injected articles + dictionary into index.html")
        else:
            print("WARNING: injection patterns not found in index.html")
    except FileNotFoundError:
        print("index.html not found — skipping inject")
