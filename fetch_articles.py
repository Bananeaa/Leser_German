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
        response = gemini.models.generate_content(model=GEMINI_MODEL, contents=prompt)
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

def gemini_word_lookup(paragraphs):
    """
    Ask Gemini to identify ~15 useful vocabulary words from the article paragraphs
    and return their article (der/die/das), English meaning, and CEFR level.
    Returns a dict: { "word": {"article": "der", "en": "meaning", "level": "A2"}, ... }
    """
    text = "\n".join(p.get("de", "") if isinstance(p, dict) else p for p in paragraphs)
    prompt = f"""Du bist ein Deutschlehrer. Hier ist ein Artikel auf Deutsch:

{text}

Wähle 12-15 nützliche Vokabeln aus diesem Text für A2-Lerner.
Für jedes Wort gib an:
- "word": das Wort in Grundform (Infinitiv für Verben, Nominativ Singular für Nomen)
- "article": "der", "die" oder "das" (nur für Nomen, sonst null)
- "en": kurze 
