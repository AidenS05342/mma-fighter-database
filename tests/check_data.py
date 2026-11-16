"""
One-shot data audit for data-sources/fighters.json against the saved UFC.com pages.

For each gap the updater reported, says whether the raw page contains the markup
(=> parser problem to fix) or not (=> genuinely absent, shown as N/A on the site).

Run from the project root:  python -I tests/check_data.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATH = ROOT / "data-sources" / "athletes"
data = json.loads((ROOT / "data-sources" / "fighters.json").read_text(encoding="utf-8"))
fighters = data["fighters"]

print(f"fighters: {len(fighters)}   record book updated: {data['meta']['recordBookLastUpdate']}")
print("divisions:", sorted({f['division'] or 'None' for f in fighters}))
print("statuses:", sorted({f['status'] or 'None' for f in fighters}))

for f in fighters:
    page = (ATH / f"{f['id']}.html").read_text(encoding="utf-8")
    notes = []
    if not f["nickname"]:
        notes.append("nickname: " + ("MARKUP PRESENT" if "hero-profile__nickname" in page else "absent on page"))
    if not f["nationality"]:
        m = re.search(r'Place of Birth</div>\s*<div class="c-bio__text">(.*?)</div>', page, re.S)
        notes.append("birthplace: " + (f"PRESENT -> {m.group(1).strip()!r}" if m else "absent on page"))
    elif not f["countryCode"]:
        notes.append(f"countryCode: no mapping for {f['nationality']!r}")
    if f["ufc"]["slpm"] is None:
        notes.append("ufc stats: " + ("MARKUP PRESENT" if "c-stat-compare__number" in page else "absent on page"))
    if not f["methodsComplete"]:
        bars = re.findall(r'c-stat-3bar__label">(.*?)</div>\s*<div class="c-stat-3bar__value">(.*?)</div>', page, re.S)
        notes.append(f"methods: record {f['wins']}-{f['losses']}-{f['draws']}, "
                     f"KO {f['koWins']} SUB {f['subWins']} DEC {f['decWins']}, page bars {bars}")
    for k in ("division", "wins", "losses", "draws", "height", "reach"):
        if f[k] is None:
            notes.append(f"{k}: null")
    if notes:
        print(f"\n{f['id']}")
        for n in notes:
            print("   ", n)

print("\nRecord Book entries per fighter:", {f["id"]: len(f["recordBook"]) for f in fighters if f["recordBook"]})
