# Static Lorcana

Small standalone Disney Lorcana tools and ideas, published to GitHub Pages.
Each tool is a single self-contained HTML file in `tools/`, and the site's
index is a table of contents built from those files.

## Adding a tool

1. Drop an HTML file into `tools/`. Keep it self-contained: inline CSS and JS,
   and only fetch from public APIs that allow cross-origin requests.
2. Give it a `<title>` and a `<meta name="description" content="…">`. The
   index uses these for the tool's card.
3. Link back to the index with `<a href="../">← All tools</a>`.
4. Push to `main`. The workflow builds and deploys the site.

Tools that aren't ready to publish (for example, ones waiting on permission
from a site they read from) go in `draft_tools/` instead. They're committed
but never deployed. To publish one, move it into `tools/`.

## Building locally

The build fetches TCGplayer prices over HTTPS. If your Python is a python.org
install on macOS that hasn't run its "Install Certificates" step, use `uv run`:

```bash
uv run python3 scripts/build.py
```

To include drafts in a local build (marked "Draft" on the index):

```bash
python3 scripts/build.py --drafts
```

```bash
python3 -m http.server -d _site 8000
```

## GitHub Pages setup

Create the repository on GitHub, then in **Settings → Pages** set **Source** to
**GitHub Actions**. Every push to `main` runs `.github/workflows/deploy.yml`.

## Tools

Published tools are in `tools/`; drafts are in `draft_tools/`.

- **For Sale** (`for_sale/`, generated): the cards, sealed product and
  playmats I'm selling locally. Visitors add items to a list (saved in their
  browser), copy it as a message, and send it to me on Discord; payment is in
  person with cash or Venmo, with a QR code for my Venmo profile.
  - Edit `for_sale/inventory.toml`: usually just a TCGplayer link and a
    quantity per item. Set `qty = 0` when something sells. The file's comments
    cover asking prices, printings, conditions and non-TCGplayer items.
  - The build fills in names, images, sets and market prices from
    [tcgcsv.com](https://tcgcsv.com), a free daily mirror of TCGplayer's
    data. Images are loaded from TCGplayer's CDN. `tcgplayer_lookup.json`
    caches which TCGplayer set each product is in; commit it.
  - The deploy workflow runs daily as well as on push, so prices stay current.
  - `venmo-qr.svg` is generated from the Venmo handle and committed. After
    changing the handle, regenerate it with
    `uv run --with segno python3 scripts/build.py`.

- **Lorcana Events Calendar** (`events_calendar/`, generated): Challenges,
  CCQs, championships and set releases for the next 12 months, plus US
  holidays (calculated in the page). Events are marked official, reported, or
  a window ("Q2 2027", shaded across every day it could fall on).
  - The events live in `events_calendar/events.json`, one per line. Edit it by
    hand any time; the build refuses to publish data that fails its checks.
  - **Weekly update:** `scripts/update-events.sh` runs
    `events_calendar/update.py`, which asks Claude Code (web search and fetch
    only, billed to your Claude subscription) for the updated list. It's only
    written if it passes the checks, every source URL came up in that run's
    searches (or was already in the file), and no more than 6 upcoming events
    vanish at once. The script then checks the site builds, commits with a
    summary of the changes, and pushes. `NO_PUSH=1` commits without pushing.
  - Install the Monday 9:30 schedule (after the Illumineers Digest's 9:00 run)
    with `scripts/install-schedule.sh`, remove it with
    `scripts/install-schedule.sh --uninstall`. The log is
    `~/Library/Logs/static-lorcana-events.log`. If the Mac is asleep at 9:30,
    it runs on wake.

- **Lore Watcher** (`draft_tools/lore-watcher.html`, draft until LoreBot's
  maintainer OKs it): a read-only view of a
  [LoreBot](https://lorebot.ink/lore_tracker) lore tracker room, for watching
  teammates' games without being able to change the score. Accepts a room link
  or name, and puts the room in the page URL (`?room=…`) so the link can be
  shared. It polls LoreBot's public room API
  (`https://lorebot.ink/api/lore_tracker/<room>`), which allows cross-origin
  requests. As of October 2026 that API returns player names and colors but not
  lore, and returns "room not found" for named rooms; the page will show lore as
  soon as the API includes a `lore` (or `score`) field per player. LoreBot's
  live page can't be used instead: it refuses connections from other sites and
  can't be embedded in a frame.
