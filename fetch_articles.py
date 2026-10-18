import feedparser
import requests
import json
import re
import os
import time
from bs4 import BeautifulSoup
from google import genai as genai_new

# ── Gemini setup ──────────────────────────────────────────────
gemini = genai_new.Client(api_key=os.environ["GEMINI_API_KEY"])
GEMINI_MODEL = "gemini-3.8-flash"

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
    """Call Gemini to rewrite the article in simple A2 German."""
    original_text = "\n\n".join(paragraphs)
    prompt = (
        "Du bist ein Deutschlehrer fuer Anfaenger (A2-Niveau).\n\n"
        "Schreibe diesen Nachrichtenartikel neu auf Deutsch fuer A2-Lerner:\n"
        "- Benutze einfache, kurze Saetze (max. 20 Woerter pro Satz)\n"
        "- Benutze haeufige Woerter (A1-A2 Niveau)\n"
        "- Schreibe 4-6 Absaetze mit je 2-3 Saetzen\n"
        "- Behalte die wichtigsten Fakten\n\n"
        "Titel: " + title + "\n\n"
        "Originaltext:\n" + original_text + "\n\n"
        'Antworte NUR mit einem JSON-Array in diesem Format (kein anderer Text):\n'
        '[\n'
        '  {"de": "Deutscher vereinfachter Absatz.", "en": "English translation."},\n'
        '  {"de": "Zweiter Absatz.", "en": "Second paragraph in English."}\n'
        ']'
    )
    try:
        response = gemini.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        paras = json.loads(raw)
        if isinstance(paras, list) and all("de" in p and "en" in p for p in paras):
            return paras
    except Exception as e:
        print(f"  Gemini error: {e}")
    return [{"de": p, "en": ""} for p in paragraphs[:6]]

def assign_level(paragraphs):
    return "A2"

def gemini_word_lookup(paragraphs):
    """Ask Gemini for vocabulary words from the article."""
    text = "\n".join(p.get("de", "") if isinstance(p, dict) else p for p in paragraphs)
    prompt = (
        "Du bist ein Deutschlehrer. Hier ist ein Artikel auf Deutsch:\n\n"
        + text +
        "\n\nWaehle 12-15 nuetzliche Vokabeln aus diesem Text fuer A2-Lerner.\n"
        "Fuer jedes Wort gib an:\n"
        '- "word": das Wort in Grundform\n'
        '- "article": "der", "die" oder "das" (nur fuer Nomen, sonst null)\n'
        '- "en": kurze englische Bedeutung (max. 6 Woerter)\n'
        '- "level": geschaetztes CEFR-Niveau ("A1", "A2", "B1", "B2")\n\n'
        "Antworte NUR mit einem JSON-Array (kein anderer Text):\n"
        '[\n'
        '  {"word": "protestieren", "article": null, "en": "to protest", "level": "B1"},\n'
        '  {"word": "Regierung", "article": "die", "en": "government", "level": "A2"}\n'
        ']'
    )
    try:
        response = gemini.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        entries = json.loads(raw)
        result = {}
        for e in entries:
            word = e.get("word", "").lower().strip()
            if not word:
                continue
            entry = {"en": e.get("en", "")}
            if e.get("article"):
                entry["article"] = e["article"].lower()
            if e.get("level"):
                entry["level"] = e["level"]
            if entry.get("en"):
                result[word] = entry
        return result
    except Exception as ex:
        print(f"  Gemini vocab error: {ex}")
        return {}

# ── Main ──────────────────────────────────────────────────────
def main():
    print("Fetching RSS...")
    feed = feedparser.parse(RSS_URL)
    articles = []

    for entry in feed.entries[:MAX_ART * 2]:
        if len(articles) >= MAX_ART:
            break

        url   = entry.get("link", "")
        title = entry.get("title", "").strip()
        desc  = entry.get("summary", "").strip()
        date  = entry.get("published", "")[:10] if entry.get("published") else ""

        try:
            from email.utils import parsedate_to_datetime
            date = parsedate_to_datetime(entry.get("published", "")).strftime("%Y-%m-%d")
        except Exception:
            pass

        print(f"\nProcessing: {title[:60]}")

        raw_paras = scrape_article(url)
        if not raw_paras:
            print("  No paragraphs found, skipping.")
            continue

        print("  Simplifying with Gemini...")
        paras = simplify_article(title, raw_paras)
        time.sleep(1)

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
        print(f"  checkmark {len(paras)} paragraphs, tag={article['tag']}")

    print("\nBuilding vocabulary with Gemini...")
    wikt_dict = {}
    for art in articles:
        print(f"  Vocab for: {art['title'][:50]}...")
        vocab = gemini_word_lookup(art["paragraphs"])
        wikt_dict.update(vocab)
        time.sleep(65)

    print(f"  Got {len(wikt_dict)} dictionary entries.")

    with open("articles.json", "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print("Saved articles.json")

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
