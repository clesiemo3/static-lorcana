"""Event categorization, discovery of premier events, and the curated events.csv list."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable

from .api import Client, event_url

# Play Hub "event configuration templates" used by organized-play premier events.
# CCQs are run by stores on the generic "Weekly Play (Constructed)" template, so they
# are found by name instead.
TEMPLATE_CATEGORIES = {
    "a1b77361-c19e-4942-8741-f6b96bb24a80": "DLC",
    "4881658d-a6ef-4f98-9c2a-1baf9ef12b82": "LCQ",
    "b8c2e34b-2ff2-45b6-b725-18528c56a7cc": "CHAMPIONSHIP",
}

NAME_SEARCHES = ["CCQ", "Championship Qualifier", "LCQ", "Last Chance Qualifier", "Disney Lorcana Challenge"]

_NAME_RULES = [
    ("LCQ", re.compile(r"\bLCQ\b|last chance qualifier", re.I)),
    ("CCQ", re.compile(r"\bCCQ\b|championship qualifier", re.I)),
    ("DLC", re.compile(r"^(?!.*qualifier).*(\bDLC\b|disney lorcana challenge)", re.I)),
]

# Names that usually mean a side event riding on a premier event's name.
SIDE_EVENT_RE = re.compile(
    r"side[ -]?event|warm[ -]?up|trial|run[ -]?back|grinder|on[ -]?demand|win[ -]?a[ -]?box|"
    r"\bmini\b|junior|kids|draft|sealed|pre[ -]?release|learn|casual|2[ -]?headed|two[ -]?headed",
    re.I,
)

EVENTS_CSV_FIELDS = ["include", "event_id", "category", "start_date", "name", "players", "location", "url"]


def categorize(name: str | None, template_id: str | None) -> str:
    if template_id in TEMPLATE_CATEGORIES:
        return TEMPLATE_CATEGORIES[template_id]
    for cat, rx in _NAME_RULES:
        if name and rx.search(name):
            return cat
    return "OTHER"


def location_of(ev: dict) -> str:
    store = ev.get("store") if isinstance(ev.get("store"), dict) else {}
    if ev.get("event_is_online") or ev.get("is_online"):
        return "Online"
    return ev.get("event_address_override") or ev.get("full_address") or store.get("full_address") or ""


def discover(client: Client, since: str | None = None, min_players: int = 32, log=print) -> list[dict]:
    """Search Play Hub for completed CCQ / DLC / LCQ / Championship events."""
    found: dict[int, dict] = {}
    base = {"display_statuses": "past", "start_date_after": since}
    queries = [("template", {"event_configuration_template_id": t}) for t in TEMPLATE_CATEGORIES]
    queries += [("name", {"name": n}) for n in NAME_SEARCHES]
    for kind, q in queries:
        n = 0
        for ev in client.search_events(**base, **q):
            found.setdefault(ev["id"], ev)
            n += 1
        log(f"  {kind} {next(iter(q.values()))!r}: {n} events")

    rows = []
    for ev in found.values():
        cat = categorize(ev.get("name"), ev.get("event_configuration_template"))
        players = ev.get("starting_player_count") or 0
        include = (
            cat != "OTHER"
            and players >= min_players
            and not ev.get("is_test_event")
            and not (cat in ("CCQ", "DLC") and SIDE_EVENT_RE.search(ev.get("name") or ""))
        )
        rows.append(
            {
                "include": "1" if include else "0",
                "event_id": str(ev["id"]),
                "category": cat,
                "start_date": (ev.get("start_datetime") or "")[:10],
                "name": (ev.get("name") or "").strip(),
                "players": str(players),
                "location": location_of(ev),
                "url": event_url(ev["id"]),
            }
        )
    return rows


# --- events.csv ------------------------------------------------------------


def read_events_csv(path: Path | str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_events_csv(path: Path | str, rows: Iterable[dict]) -> None:
    rows = sorted(rows, key=lambda r: (r.get("start_date") or "", int(r["event_id"])))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EVENTS_CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def merge_events(existing: list[dict], discovered: list[dict]) -> tuple[list[dict], int]:
    """Add newly discovered events; never overwrite the user's include/category edits."""
    by_id = {r["event_id"]: r for r in existing}
    added = 0
    for r in discovered:
        if r["event_id"] in by_id:
            cur = by_id[r["event_id"]]
            for k in ("start_date", "name", "players", "location", "url"):
                cur[k] = cur.get(k) or r[k]
        else:
            by_id[r["event_id"]] = r
            added += 1
    return list(by_id.values()), added


def included_ids(rows: list[dict]) -> list[int]:
    return [int(r["event_id"]) for r in rows if str(r.get("include", "1")).strip().lower() in ("1", "y", "yes", "true", "x")]


def category_overrides(rows: list[dict]) -> dict[int, str]:
    return {int(r["event_id"]): r["category"] for r in rows if r.get("category")}
