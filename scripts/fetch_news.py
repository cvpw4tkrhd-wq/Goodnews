#!/usr/bin/env python3
"""Hämtar positiva nyheter från RSS/Atom-flöden och skriver news.json.

Körs av GitHub Actions några gånger per dag. Använder bara Pythons
standardbibliotek, så inget behöver installeras.

Lägg till eller ta bort källor i listan SOURCES nedan.
"""
import gzip
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "news.json"
MAX_PER_SOURCE = 12
MAX_TOTAL = 120
UA = "Mozilla/5.0 (compatible; LjusglimtarBot/1.0; +https://github.com)"

# feeds = adresser som provas i tur och ordning. Fungerar ingen letar
# skriptet själv efter ett flöde på "site" (RSS-autodiscovery).
# days = hur gamla nyheter som får visas från källan.
SOURCES = [
    # --- Svenska ---
    {"name": "Bra nyheter", "lang": "sv", "site": "http://www.branyheter.se/", "days": 30,
     "feeds": ["http://www.branyheter.se/feed/", "https://www.branyheter.se/feed/"]},
    {"name": "Klimatnytt", "lang": "sv", "site": "https://www.klimatnytt.se/goda-nyheter/", "days": 30,
     "feeds": ["https://www.klimatnytt.se/goda-nyheter/feed/",
               "https://www.klimatnytt.se/category/goda-nyheter/feed/"]},
    {"name": "Good News Magazine", "lang": "sv", "site": "https://www.goodnewsmagazine.se/", "days": 30,
     "feeds": ["https://www.goodnewsmagazine.se/blog-feed.xml",
               "https://www.goodnewsmagazine.se/feed/"]},
    # --- Engelska ---
    {"name": "Good News Network", "lang": "en", "site": "https://www.goodnewsnetwork.org/", "days": 5,
     "feeds": ["https://www.goodnewsnetwork.org/feed/"]},
    {"name": "Positive News", "lang": "en", "site": "https://www.positive.news/", "days": 10,
     "feeds": ["https://www.positive.news/feed/"]},
    {"name": "Good Good Good", "lang": "en", "site": "https://www.goodgoodgood.co/", "days": 7,
     "feeds": ["https://www.goodgoodgood.co/articles/rss.xml"]},
    {"name": "Reasons to be Cheerful", "lang": "en", "site": "https://reasonstobecheerful.world/", "days": 14,
     "feeds": ["https://reasonstobecheerful.world/feed/"]},
    {"name": "The Optimist Daily", "lang": "en", "site": "https://www.optimistdaily.com/", "days": 5,
     "feeds": ["https://www.optimistdaily.com/feed/"]},
    {"name": "Only Good News Daily", "lang": "en", "site": "https://www.onlygoodnewsdaily.com/", "days": 5,
     "feeds": ["https://www.onlygoodnewsdaily.com/blog-feed.xml"]},
    {"name": "Good News EU", "lang": "en", "site": "https://goodnews.eu/en/", "days": 10,
     "feeds": ["https://goodnews.eu/en/feed"]},
    {"name": "Warp News", "lang": "en", "site": "https://www.warpnews.org/", "days": 10,
     "feeds": ["https://www.warpnews.org/news/rss/"]},
]

# Sådant som inte är nyheter (horoskop, nyhetsbrev, betalinnehåll m.m.)
SKIP_TITLE = re.compile(
    r"horoscope|horoskop|good news in history|quote of the day|newsletter|nyhetsbrev|"
    r"premium supporter|warp news #\d+|podcast|giveaway|sponsored|annons",
    re.I,
)

CATEGORIES = [
    ("djur", r"animal|wildlife|species|bird|whale|dog|cat|rescue[ds]? (?:a |an )?\w*(?:pup|kitten|cub)|"
             r"djur|fågl|fågel|val(?:ar|en)\b|hund|katt|art(?:er|en)\b|utrotningshot"),
    ("klimat", r"climate|solar|wind power|renewable|emission|carbon|forest|rewild|ocean|coral|recycl|"
               r"plastic|nature|conservation|biodivers|klimat|solcell|solenergi|vindkraft|förnybar|"
               r"utsläpp|skog|hav(?:et|en)?\b|återvinn|natur|miljö|biologisk mångfald"),
    ("halsa", r"health|cancer|vaccine|disease|medical|medicine|therapy|treatment|drug|patient|hospital|"
              r"alzheimer|malaria|hälsa|vaccin|sjukdom|medicin|behandling|läkemedel|sjukhus|vård"),
    ("vetenskap", r"scien|research|study|discover|space|nasa|telescope|robot|\bai\b|technolog|engineer|"
                  r"battery|innovation|invent|forskar|forskning|studie|upptäck|rymd|teknik|batteri|"
                  r"uppfinn"),
    ("manniskor", r"community|volunteer|kindness|donat|charity|teacher|student|neighbo|hero|"
                  r"gemenskap|volontär|ideell|donera|välgörenhet|lärare|elev|granne|hjälte"),
]
CATEGORIES = [(k, re.compile(r"(?<![a-zåäö])(?:%s)" % p, re.I)) for k, p in CATEGORIES]


def fetch(url, limit=3_000_000):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.8, */*;q=0.5",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        data = r.read(limit)
        if r.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data


def local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def clean(text, maxlen=None):
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style|figure|figcaption)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(html.unescape(text))
    text = re.sub(r"\[(?:&hellip;|…|\.\.\.)\]|\[\s*…\s*\]", "…", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*(The post .* appeared first on .*|Continue reading.*|Read more\W*|Läs mer\W*)$", "", text)
    if maxlen and len(text) > maxlen:
        text = text[:maxlen].rsplit(" ", 1)[0].rstrip(",;:.–- ") + "…"
    return text


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def http_url(u, base=None):
    if not u:
        return ""
    u = html.unescape(u.strip())
    if base:
        u = urllib.parse.urljoin(base, u)
    return u if u.startswith(("http://", "https://")) else ""


def parse_feed(data, base=None):
    """Returnerar en lista med dictar: title, url, summary, image, date."""
    root = ET.fromstring(data)
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        title = link = summary = body = image = ""
        date = None
        for c in el:
            t = local(c.tag)
            txt = (c.text or "").strip()
            if t == "title":
                title = clean("".join(c.itertext()))
            elif t == "link":
                href = c.get("href")
                if href:
                    if c.get("rel", "alternate") == "alternate" and not link:
                        link = href
                elif txt and not link:
                    link = txt
            elif t in ("description", "summary"):
                summary = "".join(c.itertext())
            elif t in ("encoded", "content") and (txt or len(c)):
                body = "".join(c.itertext())
            elif t in ("pubdate", "published", "date") or (t == "updated" and not date):
                date = parse_date(txt) or date
            elif t in ("content", "thumbnail") and c.get("url") and not image:
                typ = (c.get("type") or c.get("medium") or "image").lower()
                if "image" in typ:
                    image = c.get("url")
            elif t == "enclosure" and not image and "image" in (c.get("type") or "").lower():
                image = c.get("url") or ""
            elif t == "group" and not image:
                for g in c:
                    if local(g.tag) in ("content", "thumbnail") and g.get("url"):
                        image = g.get("url")
                        break
        if not image:
            m = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", (body or "") + (summary or ""), re.I)
            if m:
                image = m.group(1)
        link = http_url(link, base)
        if not title or not link:
            continue
        items.append({
            "title": title,
            "url": link,
            "summary": clean(summary or body, 240),
            "image": http_url(image, base),
            "date": date,
        })
    return items


def discover(site):
    """Letar efter <link rel="alternate" type="application/rss+xml"> på sajten."""
    page = fetch(site, 600_000).decode("utf-8", "replace")
    found = []
    for tag in re.findall(r"<link\b[^>]*>", page, re.I):
        if re.search(r"application/(rss|atom)\+xml", tag, re.I) and "comments" not in tag.lower():
            m = re.search(r"href=[\"']([^\"']+)[\"']", tag, re.I)
            if m:
                found.append(urllib.parse.urljoin(site, html.unescape(m.group(1))))
    return found


def categorize(text):
    for key, rx in CATEGORIES:
        if rx.search(text):
            return key
    return "ovrigt"


def load_source(src):
    """Provar källans flödesadresser. Returnerar (poster, använd adress, felmeddelande)."""
    err = "inget flöde hittades"
    tried = []
    candidates = list(src["feeds"])
    discovered = False
    while candidates or not discovered:
        if not candidates:
            discovered = True
            try:
                candidates = [u for u in discover(src["site"]) if u not in tried]
            except Exception as e:  # noqa: BLE001
                err = f"{err}; sajten: {type(e).__name__}"
            continue
        url = candidates.pop(0)
        tried.append(url)
        try:
            items = parse_feed(fetch(url), url)
            if items:
                return items, url, ""
            err = "flödet var tomt"
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:80]}"
    return [], "", err


def build(now=None):
    now = now or datetime.now(timezone.utc)
    all_items, status, seen = [], [], set()
    for src in SOURCES:
        raw, used, err = load_source(src)
        cutoff = now - timedelta(days=src.get("days", 7))
        kept = []
        for it in sorted(raw, key=lambda x: x["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
            d = it["date"]
            if d is None or d < cutoff or d > now + timedelta(hours=6):
                continue
            if SKIP_TITLE.search(it["title"]):
                continue
            key = re.sub(r"\W+", "", it["title"].lower())[:60]
            if key in seen or it["url"] in seen:
                continue
            seen.update((key, it["url"]))
            kept.append({
                "id": hashlib.sha1(it["url"].encode()).hexdigest()[:12],
                "title": it["title"],
                "summary": it["summary"],
                "url": it["url"],
                "image": it["image"],
                "source": src["name"],
                "lang": src["lang"],
                "cat": categorize(it["title"] + " " + it["summary"]),
                "date": d.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            if len(kept) >= MAX_PER_SOURCE:
                break
        all_items += kept
        status.append({"name": src["name"], "site": src["site"], "lang": src["lang"],
                       "ok": bool(raw), "count": len(kept), "error": err})
        print(f"{'OK ' if raw else 'FEL'} {src['name']:<24} {len(kept):>2} nyheter  {used or err}")
    all_items.sort(key=lambda x: x["date"], reverse=True)
    return {
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": all_items[:MAX_TOTAL],
        "sources": status,
    }


def main():
    result = build()
    if not result["items"] and OUT.exists():
        print("Inga nyheter hämtades – behåller befintlig news.json.")
        return 0
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Skrev {len(result['items'])} nyheter till {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
