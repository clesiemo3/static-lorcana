"""Build the Lorcana Events Calendar page from events.json.

events.json holds the Challenges, CCQs, championships and set releases. US
holidays are calculated in the page itself. The weekly update
(events_calendar/update.py) rewrites events.json; this module also holds the
checks it uses, so a bad update can never reach the page.
"""

import json
import re
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "events.json"
TEMPLATE = HERE / "template.html"
OUT_NAME = "events-calendar.html"

TYPES = {"set", "dlc", "ccq", "champ"}
CERTS = {"official", "reported", "window"}
REGIONS = {"North America", "Europe", "Asia", "Oceania", "South America", "Worldwide"}
EVENT_FIELDS = {"type", "cert", "name", "city", "country", "start", "end", "when", "region", "note", "sources"}
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def validate(data: dict) -> list[str]:
    """Return a list of problems; empty means the data is fine to publish."""
    problems = []
    if not ISO_DATE.fullmatch(str(data.get("checked", ""))):
        problems.append("`checked` must be a YYYY-MM-DD date")
    events = data.get("events")
    if not isinstance(events, list) or not events:
        return problems + ["`events` must be a non-empty list"]
    for i, e in enumerate(events):
        where = f"event {i} ({e.get('name', '?')})"
        if extra := set(e) - EVENT_FIELDS:
            problems.append(f"{where}: unknown fields {sorted(extra)}")
        if e.get("type") not in TYPES:
            problems.append(f"{where}: type must be one of {sorted(TYPES)}")
        if e.get("cert") not in CERTS:
            problems.append(f"{where}: cert must be one of {sorted(CERTS)}")
        if e.get("region") not in REGIONS:
            problems.append(f"{where}: region must be one of {sorted(REGIONS)}")
        if not str(e.get("name", "")).strip():
            problems.append(f"{where}: missing name")
        try:
            start = date.fromisoformat(e["start"])
            end = date.fromisoformat(e.get("end", e["start"]))
            if end < start:
                problems.append(f"{where}: end is before start")
            if (end - start).days > 200:
                problems.append(f"{where}: spans more than 200 days")
        except (KeyError, TypeError, ValueError):
            problems.append(f"{where}: start/end must be YYYY-MM-DD dates")
        if e.get("cert") == "window" and not e.get("when"):
            problems.append(f"{where}: window events need `when`, e.g. \"Q2 2027\"")
        sources = e.get("sources")
        if not isinstance(sources, list) or not sources or not all(str(s).startswith(("https://", "http://")) for s in sources):
            problems.append(f"{where}: needs at least one http(s) source URL")
    for t in data.get("tba", []):
        if not t.get("name") or t.get("region") not in REGIONS:
            problems.append(f"tba entry {t}: needs a name and a valid region")
    return problems


def dump(data: dict) -> None:
    """Write events.json with one event per line, so weekly changes diff cleanly."""
    events = sorted(data["events"], key=lambda e: (e["start"], e["type"], e["name"]))
    lines = ",\n".join("    " + json.dumps(e, ensure_ascii=False) for e in events)
    tba = ",\n".join("    " + json.dumps(t, ensure_ascii=False) for t in data.get("tba", []))
    DATA.write_text(
        "{\n"
        f'  "checked": {json.dumps(data["checked"])},\n'
        f'  "events": [\n{lines}\n  ],\n'
        f'  "tba": [\n{tba}\n  ]\n'
        "}\n",
        encoding="utf-8",
    )


def build(out_dir: Path) -> Path:
    data = load()
    if problems := validate(data):
        raise SystemExit("events.json has problems:\n  " + "\n  ".join(problems))
    page = TEMPLATE.read_text(encoding="utf-8").replace(
        "__EVENTS_JSON__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))
    out = out_dir / OUT_NAME
    out.write_text(page, encoding="utf-8")
    print(f"Events Calendar: {len(data['events'])} event(s), checked {data['checked']}")
    return out
