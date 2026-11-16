#!/usr/bin/env python3
"""
Fight Ledger data updater.

Downloads each fighter's official UFC.com athlete page plus the UFC Record Book
(statleaders.ufc.com), saves the raw HTML in ../data-sources/, and generates
../fighters-data.js, the only data file the website reads.

Rules this script follows:
  * Only values printed on the source pages are used. Nothing is estimated.
  * A value that cannot be found is written as null, and the site shows "N/A".
  * Career totals (record, KO/SUB/DEC wins) are kept separate from UFC-only
    statistics (per-minute striking/grappling numbers and Record Book ranks).

Usage (from the project root):
    python -I tools/update_fighters.py            # download fresh pages and rebuild
    python -I tools/update_fighters.py --offline  # rebuild from the saved HTML only

Standard library only; no packages to install.
"""

import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "data-sources"
ATHLETE_DIR = SRC_DIR / "athletes"
RECORD_BOOK_FILE = SRC_DIR / "statleaders.html"
JSON_OUT = SRC_DIR / "fighters.json"
JS_OUT = ROOT / "fighters-data.js"

ATHLETE_URL = "https://www.ufc.com/athlete/{slug}"
RECORD_BOOK_URL = "https://statleaders.ufc.com/"
# Only these hosts may be contacted, and only over HTTPS (including redirects).
ALLOWED_HOSTS = {"www.ufc.com", "statleaders.ufc.com"}
USER_AGENT = "Mozilla/5.0 (compatible; FightLedgerDataUpdater/1.0)"
REQUEST_DELAY_SECONDS = 1.5

# ---------------------------------------------------------------------------
# ROSTER: the ufc.com athlete slug (the part after /athlete/ in the URL).
# featured=True shows the fighter in the homepage spotlight.
# To add a fighter, add a line here and rerun the script.
# ---------------------------------------------------------------------------
ROSTER = [
    # Active and recent champions / contenders
    ("islam-makhachev", True),
    ("ilia-topuria", True),
    ("alex-pereira", True),
    ("tom-aspinall", False),
    ("dricus-du-plessis", False),
    ("khamzat-chimaev", False),
    ("belal-muhammad", False),
    ("jack-della-maddalena", False),
    ("merab-dvalishvili", True),
    ("alexander-volkanovski", False),
    ("alexandre-pantoja", False),
    ("max-holloway", False),
    ("charles-oliveira", False),
    ("israel-adesanya", False),
    ("sean-omalley", False),
    ("leon-edwards", False),
    ("zhang-weili", True),
    ("valentina-shevchenko", False),
    ("kayla-harrison", False),
    ("jon-jones", True),
    # Retired legends
    ("anderson-silva", False),
    ("georges-st-pierre", True),
    ("khabib-nurmagomedov", True),
    ("amanda-nunes", True),
    ("daniel-cormier", False),
    ("demetrious-johnson", False),
    ("jose-aldo", False),
    ("ronda-rousey", False),
    ("stipe-miocic", False),
    ("chuck-liddell", False),
    ("randy-couture", False),
    ("conor-mcgregor", False),
]

# Country name (as printed in UFC.com "Place of Birth") -> 3-letter code used on badges.
COUNTRY_CODES = {
    "United States": "USA", "Russia": "RUS", "Georgia": "GEO", "Germany": "GER",
    "Spain": "ESP", "Brazil": "BRA", "England": "ENG", "United Kingdom": "GBR",
    "South Africa": "RSA", "Sweden": "SWE", "Kuwait": "KUW", "Australia": "AUS",
    "Mexico": "MEX", "Nigeria": "NGA", "New Zealand": "NZL", "China": "CHN",
    "Kyrgyzstan": "KGZ", "Jamaica": "JAM", "Canada": "CAN", "Ireland": "IRL",
    "Republic of Ireland": "IRL", "France": "FRA", "Cameroon": "CMR",
    "Poland": "POL", "Netherlands": "NED", "Japan": "JPN", "Peru": "PER",
}

FETCHED_AT = dt.date.today().isoformat()


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------
class UnapprovedURLError(Exception):
    pass


def check_url(url: str) -> None:
    """Raise unless url is HTTPS on an approved UFC host."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise UnapprovedURLError(f"blocked URL (HTTPS + approved UFC host required): {url}")


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if its target passes check_url()."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(SafeRedirectHandler)


def fetch(url: str) -> str:
    check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _OPENER.open(req, timeout=30) as resp:
        check_url(resp.geturl())  # final URL after any redirects
        return resp.read().decode("utf-8", errors="replace")


def safe_output(path: Path) -> Path:
    """Refuse to write anywhere outside the project directory."""
    resolved = path.resolve()
    if ROOT != resolved and ROOT not in resolved.parents:
        raise RuntimeError(f"refusing to write outside project: {resolved}")
    return resolved


def download_all():
    """Download everything. Returns (record_book_ok, set_of_slugs_downloaded_this_run).
    Failures are reported; older saved copies are NOT reused for failed downloads."""
    safe_output(ATHLETE_DIR).mkdir(parents=True, exist_ok=True)
    print(f"Record Book  <- {RECORD_BOOK_URL}")
    record_book_ok = True
    try:
        safe_output(RECORD_BOOK_FILE).write_text(fetch(RECORD_BOOK_URL), encoding="utf-8")
    except Exception as exc:  # no HTTP fallback
        print(f"  FAILED Record Book: {exc}")
        record_book_ok = False

    fresh = set()
    for slug, _ in ROSTER:
        time.sleep(REQUEST_DELAY_SECONDS)
        url = ATHLETE_URL.format(slug=slug)
        try:
            page = fetch(url)
        except Exception as exc:  # keep going; the fighter is reported as missing
            print(f"  FAILED {slug}: {exc}")
            continue
        safe_output(ATHLETE_DIR / f"{slug}.html").write_text(page, encoding="utf-8")
        fresh.add(slug)
        print(f"  saved  {slug}")
    return record_book_ok, fresh


# ---------------------------------------------------------------------------
# Parsing helpers (all return None when the value is not on the page)
# ---------------------------------------------------------------------------
def clean(text):
    if text is None:
        return None
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def first(pattern, page, flags=re.S):
    m = re.search(pattern, page, flags)
    return clean(m.group(1)) if m else None


def to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def to_float(v):
    try:
        return float(str(v).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def parse_bio(page):
    bio = {}
    for label, text in re.findall(
        r'class="c-bio__label">(.*?)</div>\s*<div class="c-bio__text">(.*?)</div>', page, re.S
    ):
        bio[clean(label)] = clean(text)
    return bio


def parse_compare_stats(page):
    """Pair every c-stat-compare__label with the number that precedes it."""
    tokens = []
    for m in re.finditer(r'class="c-stat-compare__number">(.*?)</div>', page, re.S):
        tokens.append((m.start(), "num", clean(m.group(1))))
    for m in re.finditer(r'class="c-stat-compare__label">(.*?)</div>', page, re.S):
        tokens.append((m.start(), "label", clean(m.group(1))))
    tokens.sort()
    stats, last_num = {}, None
    for _, kind, value in tokens:
        if kind == "num":
            last_num = value
        elif last_num is not None:
            stats[value] = last_num
            last_num = None
    return stats


def parse_three_bar(page):
    bars = {}
    for label, value in re.findall(
        r'class="c-stat-3bar__label">(.*?)</div>\s*<div class="c-stat-3bar__value">(.*?)</div>', page, re.S
    ):
        bars[clean(label)] = clean(value)
    return bars


def bar_count(bars, key):
    v = bars.get(key)
    m = re.match(r"(\d+)", v or "")
    return int(m.group(1)) if m else None


def parse_circle(page, title):
    m = re.search(r"<title>\s*" + re.escape(title) + r"\s*(\d+(?:\.\d+)?)%\s*</title>", page, re.I)
    return float(m.group(1)) if m else None


def parse_athlete(slug, featured):
    path = ATHLETE_DIR / f"{slug}.html"
    if not path.exists():
        return None
    page = path.read_text(encoding="utf-8")

    name = first(r'class="hero-profile__name">(.*?)</h1>', page)
    if not name:
        return None
    nickname = first(r'class="hero-profile__nickname">(.*?)</p>', page)
    if nickname:
        nickname = nickname.strip('"“” ')

    division = first(r'class="hero-profile__division-title">(.*?)</p>', page)
    if division:
        division = re.sub(r"\s*Division$", "", division).strip()

    record = first(r'class="hero-profile__division-body">(.*?)</p>', page)
    wins = losses = draws = None
    if record:
        m = re.match(r"(\d+)-(\d+)-(\d+)", record)
        if m:
            wins, losses, draws = map(int, m.groups())

    bars = parse_three_bar(page)
    ko = bar_count(bars, "KO/TKO")
    sub = bar_count(bars, "SUB")
    dec = bar_count(bars, "DEC")
    # Fall back to the hero counters for KO / SUB if the method chart is missing.
    hero_stats = {
        clean(t): to_int(clean(n))
        for n, t in re.findall(
            r'class="hero-profile__stat-numb">(.*?)</p>\s*<p class="hero-profile__stat-text">(.*?)</p>', page, re.S
        )
    }
    if ko is None:
        ko = hero_stats.get("Wins by Knockout")
    if sub is None:
        sub = hero_stats.get("Wins by Submission")

    methods_complete = None not in (wins, ko, sub, dec) and ko + sub + dec == wins

    bio = parse_bio(page)
    birthplace = bio.get("Place of Birth")
    country = birthplace.split(",")[-1].strip() if birthplace else None
    birth_date = first(r'"birthDate"\s*:\s*"([^"]+)"', page)
    status = bio.get("Status") or None

    cmp_stats = parse_compare_stats(page)
    ufc = {
        "slpm": to_float(cmp_stats.get("Sig. Str. Landed")),
        "sapm": to_float(cmp_stats.get("Sig. Str. Absorbed")),
        "strAcc": parse_circle(page, "Striking accuracy"),
        "strDef": to_float(cmp_stats.get("Sig. Str. Defense")),
        "tdAvg": to_float(cmp_stats.get("Takedown avg")),
        "tdAcc": parse_circle(page, "Takedown Accuracy"),
        "tdDef": to_float(cmp_stats.get("Takedown Defense")),
        "subAvg": to_float(cmp_stats.get("Submission avg")),
        "kdAvg": to_float(cmp_stats.get("Knockdown Avg")),
        "avgFightTime": cmp_stats.get("Average fight time"),
    }

    return {
        "id": slug,
        "name": name,
        "nickname": nickname,
        "status": status,
        "birthplace": birthplace,
        "nationality": country,          # country of birth as listed by UFC.com
        "countryCode": COUNTRY_CODES.get(country or "", None),
        "division": division,
        "featured": featured,
        # ---- Overall professional MMA record (all promotions) ----
        "wins": wins, "losses": losses, "draws": draws,
        "koWins": ko, "subWins": sub, "decWins": dec,
        "methodsComplete": methods_complete,
        # ---- Bio ----
        "birthDate": birth_date,
        "height": to_float(bio.get("Height")),     # inches
        "reach": to_float(bio.get("Reach")),       # inches
        "fightingStyle": bio.get("Fighting style"),
        "trainsAt": bio.get("Trains at"),
        "octagonDebut": bio.get("Octagon Debut"),
        # ---- UFC-only statistics ----
        "ufc": ufc,
        "recordBook": [],
        "sourceUrl": ATHLETE_URL.format(slug=slug),
        "fetchedAt": FETCHED_AT,
    }


def parse_record_book():
    if not RECORD_BOOK_FILE.exists():
        return {}, None
    page = RECORD_BOOK_FILE.read_text(encoding="utf-8")
    updated = first(r"Last Update:\s*([^<]+)", page)
    entries = {}
    for title, body in re.findall(
        r'<article class="results-group[^"]*"[^>]*>\s*<header>\s*<h3>(.*?)</h3>(.*?)</article>', page, re.S
    ):
        category = clean(title)
        for rank, href, fname, value in re.findall(
            # [^<]* keeps the rank from spanning the header row into row 1.
            r'<div class="results-table--tr[^"]*">\s*<span>([^<]*)</span>\s*<span><a href=([^ >]+)>(.*?)</a></span>\s*<span>(.*?)</span>',
            body, re.S,
        ):
            slug = href.rstrip("/").split("/")[-1].lower()
            entries.setdefault(slug, []).append(
                {"category": category, "rank": to_int(clean(rank)), "value": clean(value), "name": clean(fname)}
            )
    return entries, updated


# ---------------------------------------------------------------------------
def main():
    offline = "--offline" in sys.argv
    record_book_ok, fresh = True, {slug for slug, _ in ROSTER}
    if not offline:
        record_book_ok, fresh = download_all()

    record_book, rb_updated = parse_record_book() if record_book_ok else ({}, None)
    fighters, missing = [], []
    for slug, featured in ROSTER:
        f = parse_athlete(slug, featured) if slug in fresh else None
        if f is None:
            missing.append(slug)
            continue
        f["recordBook"] = record_book.get(slug, [])
        fighters.append(f)

    if not fighters:
        sys.exit("No fighter pages parsed; leaving existing fighters-data.js untouched.")

    data = {
        "meta": {
            "lastVerified": FETCHED_AT,
            "recordBookLastUpdate": rb_updated,
            "sources": [
                {"name": "UFC.com athlete profiles", "url": "https://www.ufc.com/athletes/all"},
                {"name": "UFC Record Book", "url": "https://statleaders.ufc.com/"},
            ],
        },
        "fighters": fighters,
    }

    safe_output(JSON_OUT).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    safe_output(JS_OUT).write_text(
        "/* AUTO-GENERATED by tools/update_fighters.py. Do not edit by hand.\n"
        "   Source: UFC.com athlete profiles + UFC Record Book (statleaders.ufc.com). */\n"
        "window.FIGHTER_DATA = " + json.dumps(data, indent=2, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    print(f"\nWrote {len(fighters)} fighters to {JS_OUT.name}")
    if missing:
        print("MISSING (page not downloaded or unrecognised):", ", ".join(missing))
    for f in fighters:
        issues = [k for k in ("nickname", "division", "wins", "koWins", "subWins", "decWins", "nationality", "countryCode") if f[k] in (None, "")]
        nulls = [k for k, v in f["ufc"].items() if v is None]
        flag = "" if f["methodsComplete"] else "  [win methods do not sum to wins]"
        if issues or nulls or flag:
            print(f"  {f['id']}: missing {issues + ['ufc.' + n for n in nulls]}{flag}")


if __name__ == "__main__":
    main()
