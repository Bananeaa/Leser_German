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
        if "/" + key + "/" in url:
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
        print("  scrape error: " + str(e))
        return []

def simplify_article(title, paragraphs):
    """
    Call Gemini to rewrite the article in simple A2 German.
    Returns list of {de, en} paragraph dicts.
    """
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
        "Antworte NUR mit einem JSON-Array in diesem Format (kein anderer Text):\n"
        "[\n"
        "  {\"de\": \"Deutscher vereinfachter Absatz.\", \"en\": \"English translation.\"},\n"
        "  {\"de\": \"Zweiter Absatz.\", \"en\": \"Second paragraph in English.\"}\n"
        "]"
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
        print("  Gemini error: " + str(e))

    return [{"de": p, "en": ""} for p in paragraphs[:6]]

def assign_level(paragraphs):
    """Assign A2 since we simplified with Gemini."""
    return "A2"

# ── Vocab from local vocab_dict.json (built from verbformen.de) ───────────────
_VOCAB_DICT = None

def load_vocab_dict():
    global _VOCAB_DICT
    if _VOCAB_DICT is None:
        vocab_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vocab_dict.json")
        if os.path.exists(vocab_path):
            with open(vocab_path, "r", encoding="utf-8") as f:
                _VOCAB_DICT = json.load(f)
            print("  Loaded " + str(len(_VOCAB_DICT)) + " entries from vocab_dict.json")
        else:
            print("  vocab_dict.json not found — vocabulary will be empty.")
            _VOCAB_DICT = {}
    return _VOCAB_DICT

def local_word_lookup(paragraphs):
    """
    Extract words from the article paragraphs and look them up in vocab_dict.json.
    Returns a dict: { "word": {"article": "der", "en": "meaning", "level": "A2"}, ... }
    """
    vocab = load_vocab_dict()
    if not vocab:
        return {}

    text = " ".join(p.get("de", "") if isinstance(p, dict) else p for p in paragraphs)
    words = re.findall(r"\b[a-zA-Z\xc4\xd6\xdc\xe4\xf6\xfc\xdf]{3,}\b", text)

    result = {}
    for word in words:
        key = word.lower()
        if key in vocab and key not in result:
            result[key] = vocab[key]

    return result

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

        print("\nProcessing: " + title[:60])

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
        print("  OK " + str(len(paras)) + " paragraphs, tag=" + article["tag"])

    print("\nBuilding vocabulary from vocab_dict.json...")
    wikt_dict = {}
    for art in articles:
        print("  Vocab for: " + art["title"][:50] + "...")
        vocab = local_word_lookup(art["paragraphs"])
        wikt_dict.update(vocab)

    print("  Got " + str(len(wikt_dict)) + " dictionary entries.")

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
        'const FALLBACK_ARTICLES = ' + articles_json + ';',
        html, flags=re.DOTALL
    )
    new_html = re.sub(
        r'const WIKT_DICT = \{.*?\};',
        'const WIKT_DICT = ' + dict_json + ';',
        new_html, flags=re.DOTALL
    )

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(new_html)
    print("Injected into " + HTML_FILE)

if __name__ == "__main__":
    main()
