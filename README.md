# Fight Ledger: MMA Fighter Database

An interactive MMA fighter database built with **HTML, CSS, and vanilla JavaScript**. It has a dark interface in the style of modern combat sports analytics sites, with searchable fighter profiles, weight class filters, and side-by-side fighter comparisons.

> **Data notice:** Fighter data comes from official **UFC.com athlete profiles** and the **UFC Record Book** (statleaders.ufc.com), collected by `tools/update_fighters.py`. Nothing is estimated: any value the source pages do not list is shown as **N/A**. Records and win methods cover each fighter's full professional career; striking and grappling stats cover UFC bouts only. This is a fan project and is not affiliated with or endorsed by the UFC.

## Features

- **Homepage**: a large title, summary numbers for the roster, the data source with its last-verified date, an introduction to the site's features, and a set of featured fighters.
- **Fighter directory**:
  - Live search by name, nickname, nationality, country code, birthplace, division, fighting style, or status
  - Weight class filter buttons that show how many fighters are in each division
  - Sorting by most wins, win percentage, most finishes, or name (fighters with N/A values sort last)
  - A message and a reset button when nothing matches
- **Fighter cards**: name, nickname, nationality, weight class, record (W-L-D), win percentage, and a bar plus counts showing how the fighter's wins split across KO/TKO, submission, and decision.
- **Profile pop-up**: the full record, how the fighter wins, UFC performance stats (strikes landed and absorbed, accuracy, defense, takedowns, submissions, knockdowns, average fight time), physical stats (age, height, reach, Octagon debut), the fighter's UFC Record Book rankings, and a link to the source page.
- **Head-to-head comparison**:
  - Choose two fighters from drop-down lists grouped by division, or press **Compare** on any card
  - Mirrored stat bars, with the leader in each category highlighted in red
  - Categories where either fighter has N/A are shown but never scored
  - A count of categories each fighter leads, plus a one-line verdict
  - A button to swap the two fighters
- **Responsive design**: a menu button on mobile, filter buttons that scroll sideways, and comparison rows that stack on small screens.
- **Accessibility**: keyboard-operable cards, a pop-up that keeps keyboard focus inside it and closes with Esc, a skip link, live result counts for screen readers, and support for reduced motion.

## Project structure

```
mma-fighter-database/
├── index.html              # Page layout: nav, hero, intro, featured, directory, compare, about, modal
├── style.css               # Dark theme, layout, hover effects, responsive breakpoints
├── script.js               # Rendering, search, filters, modal, and comparison logic
├── fighters-data.js        # AUTO-GENERATED fighter data (window.FIGHTER_DATA)
├── tools/
│   └── update_fighters.py  # Downloads UFC.com pages and rebuilds fighters-data.js
├── data-sources/           # Saved source HTML (athletes/, statleaders.html) and fighters.json
├── tests/
│   ├── test_update_fighters.py  # Offline safety + parsing tests for the updater
│   ├── check_data.py            # Audit: explains every gap in the generated data
│   └── site_test.html           # Browser tests for search, filters, profiles, comparison
└── README.md
```

## How to run

There is no build step and nothing to install. Open `index.html` in any modern browser, or serve the folder:

```bash
python -m http.server 8000
# then visit http://localhost:8000
```

## Updating the data

Requires Python 3 (standard library only).

```bash
python -I tests/test_update_fighters.py     # offline safety tests (no network)
python -I tools/update_fighters.py          # download fresh pages and rebuild fighters-data.js
python -I tools/update_fighters.py --offline  # rebuild from the saved HTML only
python -I tests/check_data.py               # report every missing or unverifiable value
```

Safety rules built into the updater (covered by the tests):

- Only HTTPS requests to `www.ufc.com` and `statleaders.ufc.com`, including redirects.
- Files are only written inside the project folder.
- If no fighter pages can be parsed, the existing `fighters-data.js` is left untouched.
- A missing value is written as `null`, never guessed. Win-method counts that do not add up to the listed wins are shown as N/A.

To add a fighter, add their UFC.com slug (the part after `/athlete/` in the profile URL) to `ROSTER` in `tools/update_fighters.py` and rerun the updater. New weight classes are added to the filters automatically; add them to `DIVISION_ORDER` in `script.js` to control their position.

## Testing the website

Open `tests/site_test.html` in a browser. It loads the real `fighters-data.js` and `script.js` and prints a PASS/FAIL list. It can also run headless:

```bash
msedge --headless --disable-gpu --virtual-time-budget=10000 --dump-dom tests/site_test.html
```

## Deploy to GitHub Pages

1. Push these files to a GitHub repository, with `index.html` at the top level of the repository.
2. In the repository, go to **Settings → Pages**.
3. Under **Source**, choose **Deploy from a branch**, select `main` and `/ (root)`, then click **Save**.
4. After a minute, the site is live at `https://<your-username>.github.io/<repo-name>/`.

## Tech notes

- No frameworks, dependencies, APIs, or API keys in the website itself.
- Fonts (Oswald and Inter) load from Google Fonts. If they can't load, the page uses system fonts.
- Fighter avatars are generated from initials, so the site needs no image files.
