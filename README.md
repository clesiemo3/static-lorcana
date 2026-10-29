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

```bash
python3 scripts/build.py
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
