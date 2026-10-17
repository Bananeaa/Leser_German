import feedparser
import requests
import json
import re
import os
import time
from bs4 import BeautifulSoup
import google.generativeai as genai

# ── Gemini setup ──────────────────────────────────────────────
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
gemini = genai.GenerativeModel("gemini-1.5-flash")

# ── Config ────────────────────────────────────────────────────
RSS_URL   = "https://www.tagesschau.de/xml/rss2/"
MAX_ART   = 6
HTML_FILE = "index.html"

TAG_MAP = {
    "inland":       "Inland",
    "ausland":      "Ausland",
    "wirtschaft":   "Wirtschaft",
    "sport":        "Sport",
    "wissenschaft": "Wissenschaft",
    "technologie":  "Technologie",
    "kultur":       "Kultur",
    "regional":     "Regional",
}

# ── Helpers ───────────────────────────────────────────────────
def detect_tag(url):
    for key, label in TAG_MAP.items():
        if f"/{key}/" in url:
            return label
    return "Nachrichten"

def scrape_article(url):
    """Return list of paragraph strings from a Tagesschau article."""
    try:
        r = requests.get(url, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        paras = []
        for p in soup.select("p.textabsatz, div.text p, article p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 40:
                paras.append(t)
        return paras[:12]
    except Exception as e:
        print(f"  scrape error: {e}")
        return []

def simplify_article(title, paragraphs):
    """
    Call Gemini to rewrite the article in simple A2 German.
    Returns list of {de, en} paragraph dicts.
    """
    original_text = "\n\n".join(paragraphs)
    prompt = f"""Du bist ein Deutschlehrer für Anfänger (A2-Niveau).

Schreibe diesen Nachrichtenartikel neu auf Deutsch für A2-Lerner:
- Benutze einfache, kurze Sätze (max. 20 Wörter pro Satz)
- Benutze häufige Wörter (A1-A2 Niveau)
- Schreibe 4-6 Absätze mit je 2-3 Sätzen
- Behalte die wichtigsten Fakten

Titel: {title}

Originaltext:
{original_text}

Antworte NUR mit einem JSON-Array in diesem Format (kein anderer Text):
[
  {{"de": "Deutscher vereinfachter Absatz.", "en": "English translation of the paragraph."}},
  {{"de": "Zweiter Absatz.", "en": "Second paragraph in English."}}
]"""

    try:
        response = gemini.generate_content(prompt)
        raw = response.text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        paras = json.loads(raw)
        # Validate structure
        if isinstance(paras, list) and all("de" in p and "en" in p for p in paras):
            return paras
    except Exception as e:
        print(f"  Gemini error: {e}")

    # Fallback: return original paragraphs with empty translation
    return [{"de": p, "en": ""} for p in paragraphs[:6]]

def assign_level(paragraphs):
    """Assign A2 since we simplified with Gemini."""
    return "A2"

def wiktionary_lookup(word):
    """Look up a word on Wiktionary for article, level, and English meaning."""
    try:
        url = f"https://en.wiktionary.org/api/rest_v1/page/summary/{word}"
        r = requests.get(url, timeout=6)
        if r.status_code != 200:
            return None
        data = r.json()
        extract = data.get("extract", "")
        if not extract or "German" not in extract:
            return None

        entry = {}

        # Extract grammatical article (der/die/das)
        desc = data.get("description", "")
        art_match = re.search(r'\b(der|die|das)\b', desc, re.IGNORECASE)
        if art_match:
            entry["article"] = art_match.group(1).lower()

        # Extract CEFR level
        level_match = re.search(r'\b([ABC][12])\b', extract)
        if level_match:
            entry["level"] = level_match.group(1)

        # Extract English meaning: first sentence up to 60 chars
        sentences = extract.split(".")
        for s in sentences:
            s = s.strip()
            if s and "German" not in s and len(s) > 5:
                entry["en"] = s[:80]
                break

        return entry if entry.get("en") else None
    except Exception:
        return None

def extract_words(paras):
    """Return unique lowercase words ≥3 chars from all paragraphs."""
    words = set()
    for p in paras:
        text = p.get("de", "") if isinstance(p, dict) else p
        for w in re.findall(r'[a-zA-ZäöüÄÖÜß]{3,}', text):
            words.add(w.lower())
    return words

# ── Main ──────────────────────────────────────────────────────
def main():
    print("Fetching RSS…")
    feed = feedparser.parse(RSS_URL)
    articles = []
    all_words = set()

    for entry in feed.entries[:MAX_ART * 2]:  # fetch extra in case some fail
        if len(articles) >= MAX_ART:
            break

        url   = entry.get("link", "")
        title = entry.get("title", "").strip()
        desc  = entry.get("summary", "").strip()
        date  = entry.get("published", "")[:10] if entry.get("published") else ""

        # Normalise date to YYYY-MM-DD
        try:
            from email.utils import parsedate_to_datetime
            date = parsedate_to_datetime(entry.get("published","")).strftime("%Y-%m-%d")
        except Exception:
            pass

        print(f"\nProcessing: {title[:60]}")

        raw_paras = scrape_article(url)
        if not raw_paras:
            print("  No paragraphs found, skipping.")
            continue

        print(f"  Simplifying with Gemini…")
        paras = simplify_article(title, raw_paras)
        time.sleep(1)  # be polite to Gemini

        art_id = re.sub(r'[^a-z0-9]+', '-', title.lower())[:50]

        article = {
            "id":         art_id,
            "title":      title,
            "date":       date,
            "level":      assign_level(paras),
            "tag":        detect_tag(url),
            "desc":       desc[:120] if desc else (paras[0]["de"][:100] if paras else ""),
            "source":     "tagesschau.de",
            "url":        url,
            "paragraphs": paras,
        }
        articles.append(article)
        all_words.update(extract_words(paras))
        print(f"  ✓ {len(paras)} paragraphs, tag={article['tag']}")

    print(f"\nLooking up {len(all_words)} words on Wiktionary…")
    wikt_dict = {}
    for i, word in enumerate(sorted(all_words)):
        entry = wiktionary_lookup(word)
        if entry:
            wikt_dict[word] = entry
        if i % 20 == 0:
            print(f"  {i}/{len(all_words)}…")
        time.sleep(0.15)

    print(f"  Got {len(wikt_dict)} dictionary entries.")

    # ── Save articles.json ────────────────────────────────────
    with open("articles.json", "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print("Saved articles.json")

    # ── Inject into index.html ────────────────────────────────
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    articles_json = json.dumps(articles, ensure_ascii=False)
    dict_json     = json.dumps(wikt_dict, ensure_ascii=False)

    new_html = re.sub(
        r'const FALLBACK_ARTICLES = \[.*?\];',
        f'const FALLBACK_ARTICLES = {articles_json};',
        html, flags=re.DOTALL
    )
    new_html = re.sub(
        r'const WIKT_DICT = \{.*?\};',
        f'const WIKT_DICT = {dict_json};',
        new_html, flags=re.DOTALL
    )

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(new_html)
    print(f"Injected into {HTML_FILE}")

if __name__ == "__main__":
    main()
