"""Build the site: copy every page in tools/ into _site/ and write the index.

Each tool is one standalone HTML file. The index lists them using each page's
<title> and <meta name="description">, so adding a tool means dropping a file
into tools/ and nothing else. Standard library only, so CI needs no installs.

Pages in draft_tools/ are kept out of the deployed site. Pass --drafts to
include them in a local build for previewing; CI never does.

Some tools are generated from data instead (see GENERATORS): each has a
build(out_dir) function that writes its page and returns the path.

    python3 scripts/build.py [--drafts]
"""

import html
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from events_calendar import build as events_calendar  # noqa: E402
from for_sale import build as for_sale  # noqa: E402

GENERATORS = [events_calendar, for_sale]
TOOLS = ROOT / "tools"
DRAFTS = ROOT / "draft_tools"
OUT = ROOT / "_site"
DRAFT_TAG = ' <span class="draft">Draft</span>'


def meta(page: str, name: str) -> str:
    m = re.search(rf'<meta\s+name="{name}"\s+content="([^"]*)"', page, re.I)
    return html.unescape(m.group(1)) if m else ""


def title(page: str) -> str:
    m = re.search(r"<title>(.*?)</title>", page, re.I | re.S)
    return html.unescape(m.group(1).strip()) if m else ""


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "tools").mkdir(parents=True)

    sources = [(p, False) for p in sorted(TOOLS.glob("*.html"))]
    if "--drafts" in sys.argv[1:]:
        sources += [(p, True) for p in sorted(DRAFTS.glob("*.html"))]
    for path, _ in sources:
        shutil.copy2(path, OUT / "tools" / path.name)
    # Generated tools build their page from data, straight into _site/tools/.
    sources += [(gen.build(OUT / "tools"), False) for gen in GENERATORS]

    entries = []
    for path, draft in sorted(sources, key=lambda s: s[0].name):
        page = path.read_text(encoding="utf-8")
        entries.append({
            "href": f"tools/{path.name}",
            "title": title(page) or path.stem,
            "description": meta(page, "description"),
            "draft": draft,
        })

    cards = "\n".join(
        f'  <a class="card" href="{html.escape(e["href"])}">\n'
        f'    <h3>{html.escape(e["title"])}{DRAFT_TAG if e["draft"] else ""}</h3>\n'
        f'    <p class="muted">{html.escape(e["description"])}</p>\n'
        f"  </a>"
        for e in entries
    ) or '  <p class="muted">No tools published yet.</p>'
    (OUT / "index.html").write_text(INDEX.replace("{{cards}}", cards), encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    print(f"Built {len(entries)} tool(s) into {OUT.relative_to(ROOT)}/")


INDEX = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Static Lorcana</title>
  <meta name="description" content="Small standalone Disney Lorcana tools and ideas.">
<style>
  :root {
    --bg: #faf8f4; --surface: #ffffff; --text: #1f1d1a; --muted: #6b665e;
    --border: #e6e1d8; --accent: #6a3fa0; --accent-soft: #f1ebf8;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #15131a; --surface: #1e1b24; --text: #ece8f1; --muted: #a29cab;
      --border: #332e3b; --accent: #c3a3ec; --accent-soft: #2a2236;
    }
  }
  :root[data-theme="dark"] {
    --bg: #15131a; --surface: #1e1b24; --text: #ece8f1; --muted: #a29cab;
    --border: #332e3b; --accent: #c3a3ec; --accent-soft: #2a2236;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  main { max-width: 760px; margin: 0 auto; padding: 32px 16px 64px; }
  h1 { font-size: 1.9rem; line-height: 1.25; margin: 0.2em 0 0.3em; }
  h3 { font-size: 1.05rem; margin: 0 0 2px; color: var(--accent); }
  .kicker { color: var(--muted); font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.06em; }
  .muted { color: var(--muted); font-size: 0.9rem; margin: 0; }
  a.card {
    display: block; text-decoration: none; color: inherit;
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 16px; margin: 10px 0;
  }
  a.card:hover, a.card:focus-visible { border-color: var(--accent); }
  .draft { font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; background: var(--accent-soft); border-radius: 4px; padding: 1px 6px; margin-left: 6px; vertical-align: middle; }
</style>
</head>
<body>
<main>
  <div class="kicker">Disney Lorcana</div>
  <h1>Static Lorcana</h1>
  <p class="muted">Small standalone tools and ideas. Each one is a single page.</p>
{{cards}}
</main>
</body>
</html>
"""

if __name__ == "__main__":
    main()
