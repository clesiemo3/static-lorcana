"""Fetch the Rules of Villainy team's tournament results and write results.json.

Play Hub can't be searched by player, so this searches events and checks each
one's registrations for the team's Play Hub ids:

- worldwide: every DLC, LCQ and championship (Play Hub tags them by template),
  and every CCQ with at least `min_players` players (found by name);
- locally: every set championship within `radius_miles` of the search center,
  whatever its size, and every other event there with at least `min_players`
  players (CCQs, 1Ks, box tournaments).

Events the team played in are cached in rov_roster/cache/ (gitignored) using the
standings-aggregator's cache format, so its cache can be copied in to skip
downloads. Elo comes from eLorcana, which also fills in majors that Play Hub's
search misses (some aren't public there). The page is built by build.py.

    uv run python3 rov_roster/update.py [--refresh]
"""

import json
import re
import sys
import tomllib
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from rov_roster.lsa.api import Client, event_url  # noqa: E402
from rov_roster.lsa.cache import Cache  # noqa: E402
from rov_roster.lsa.events import NAME_SEARCHES, SIDE_EVENT_RE, TEMPLATE_CATEGORIES, categorize  # noqa: E402
from rov_roster.lsa.report import EventView, _local_date, _parse_record  # noqa: E402

TEAM = HERE / "team.toml"
RESULTS = HERE / "results.json"
CACHE = Cache(HERE / "cache")
CHECKED = HERE / "cache" / "checked.json"
ELORCANA_API = "https://api.elorcana.com/players/"
USER_AGENT = "static-lorcana-rov-roster/0.1"
# Local events that aren't constructed tournaments.
NOT_A_TOURNAMENT = re.compile(r"pre[ -]?release|sealed|draft|learn to play|casual", re.I)
ELORCANA_TYPES = {"dlc": "DLC", "ccq": "CCQ", "lcq": "LCQ", "championship": "CHAMPIONSHIP"}


def load_team() -> dict:
    with open(TEAM, "rb") as f:
        return tomllib.load(f)


def candidates(client: Client, search: dict) -> dict[int, dict]:
    """Events worth checking for team members, keyed by id."""
    found: dict[int, dict] = {}
    base = {"display_statuses": "past", "start_date_after": search["since"]}
    min_players = search["min_players"]

    def add(ev: dict, why: str) -> None:
        if not ev.get("is_test_event"):
            found.setdefault(ev["id"], {**ev, "_why": why})

    for template, cat in TEMPLATE_CATEGORIES.items():
        for ev in client.search_events(**base, event_configuration_template_id=template):
            add(ev, cat)
    for name in NAME_SEARCHES:
        for ev in client.search_events(**base, name=name):
            cat = categorize(ev.get("name"), ev.get("event_configuration_template"))
            big = (ev.get("starting_player_count") or 0) >= min_players
            if cat != "OTHER" and big and not SIDE_EVENT_RE.search(ev.get("name") or ""):
                add(ev, cat)
    local = {"latitude": search["latitude"], "longitude": search["longitude"], "num_miles": search["radius_miles"]}
    for ev in client.search_events(**base, **local):
        # Set championships count at any size; other events (1Ks, box
        # tournaments) need min_players.
        name = ev.get("name") or ""
        if NOT_A_TOURNAMENT.search(name):
            continue
        if "set champ" in name.lower() or (ev.get("starting_player_count") or 0) >= min_players:
            add(ev, "local")
    return found


def team_members_in(client: Client, event_id: int, team_ids: set[int]) -> list[int]:
    regs = client.registrations(event_id)
    return sorted(team_ids & {(r.get("user") or {}).get("id") for r in regs})


def category(ev: dict) -> str:
    """CHAMPIONSHIP, DLC, LCQ, CCQ, SET (set championship) or LOCAL."""
    cat = categorize(ev.get("name"), ev.get("template_id"))
    if cat != "OTHER":
        return cat
    if "set champ" in (ev.get("name") or "").lower():
        return "SET"
    return "LOCAL"


def result_row(view: EventView, uid: int) -> dict | None:
    """One player's result; falls back to Swiss standings for players who missed the cut."""
    if uid not in view.participants:
        return None
    r = view.row(uid, "")
    final, swiss = view.final.get(uid), view.swiss.get(uid)
    src = final or swiss or {}
    w, l, d = _parse_record(src.get("match_record"))
    return {
        "rank": src.get("rank"),
        "wins": w,
        "losses": l,
        "draws": d,
        "games_won": r["games_won"],
        "games_lost": r["games_lost"],
        "byes": r["byes"],
        "swiss_rank": (swiss or {}).get("rank"),
        "swiss_record": (swiss or {}).get("match_record"),
        "made_top_cut": r["made_top_cut"],
        "top_cut_record": r["top_cut_record"],
        "last_phase": r["last_phase"],
    }


def elorcana(player_id: str) -> tuple[dict | None, list[dict]]:
    """A player's Elo and their eLorcana tournament history (majors only)."""
    req = urllib.request.Request(ELORCANA_API + player_id, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception as e:  # eLorcana is a nice-to-have; keep going without it.
        print(f"  eLorcana {player_id}: {e}")
        return None, []
    stats = data["stats"]
    elo = {
        "elo": round(stats["elo"]),
        "rank": stats.get("eloRank"),
        "peak": round(stats["peakElo"]) if stats.get("peakElo") else None,
    }
    return elo, data.get("tournamentHistory") or []


def fill_from_elorcana(player: dict, history: list[dict], events: dict, results: list[dict]) -> None:
    """Add majors eLorcana has but Play Hub's search doesn't (some aren't public there)."""
    mine = [(events[r["event"]], r) for r in results if r["player"] == player["id"]]
    for t in history:
        m = t["tournamentMetadata"]
        cat = ELORCANA_TYPES.get(m.get("type"))
        if not cat:
            continue
        day = date.fromisoformat(m["date"][:10])
        if any(ev["category"] == cat and abs(date.fromisoformat(ev["date"]) - day) <= timedelta(days=3) for ev, _ in mine):
            continue
        key = f"elorcana-{m['code']}"
        events.setdefault(key, {
            "name": m["name"],
            "date": day.isoformat(),
            "category": cat,
            "players": m.get("nbPlayers"),
            "store": "Results from eLorcana",
            "location": "",
            "url": f"https://elorcana.com/profile/{player['elorcana']}",
        })
        rr, gr = t.get("roundRecord") or {}, t.get("gameRecord") or {}
        made_cut = bool(m.get("topCut")) and (t.get("rank") or 1e9) <= m["topCut"]
        results.append({
            "player": player["id"], "event": key, "rank": t.get("rank"),
            "wins": rr.get("nbWins", 0), "losses": rr.get("nbLosses", 0), "draws": rr.get("nbDraws", 0),
            "games_won": gr.get("nbWins", 0), "games_lost": gr.get("nbLosses", 0), "byes": 0,
            "swiss_rank": None, "swiss_record": None, "made_top_cut": made_cut,
            "top_cut_record": "", "last_phase": f"Top {m['topCut']}" if made_cut else "",
        })
        print(f"  added from eLorcana: {player['name']} at {m['name']}")


def main() -> None:
    refresh = "--refresh" in sys.argv[1:]
    team = load_team()
    search, players = team["search"], team["player"]
    team_ids = {p["playhub_id"] for p in players}
    client = Client()

    # Which team members played each event. Completed events never change, so
    # they're only checked again when the team list changes.
    checked = json.loads(CHECKED.read_text()) if CHECKED.exists() and not refresh else {}
    if checked.get("team") != sorted(team_ids):
        checked = {"team": sorted(team_ids), "events": {}}

    print(f"Searching Play Hub (since {search['since']}, {search['radius_miles']} mi of {search['name']})…")
    found = candidates(client, search)
    todo = [eid for eid in found if str(eid) not in checked["events"]]
    print(f"  {len(found)} candidate events, {len(todo)} not checked yet")
    for i, eid in enumerate(todo, 1):
        members = team_members_in(client, eid, team_ids)
        if found[eid].get("display_status") == "complete":
            checked["events"][str(eid)] = members
        if members:
            print(f"  [{i}/{len(todo)}] {found[eid]['name']}: {len(members)} team member(s)")
    CHECKED.parent.mkdir(parents=True, exist_ok=True)
    CHECKED.write_text(json.dumps(checked))

    played = sorted(int(e) for e, m in checked["events"].items() if m)
    events, results = {}, []
    for eid in played:
        bundle, fetched = CACHE.ensure(client, eid, refresh=refresh)
        if fetched:
            print(f"  fetched {bundle['event']['name']}")
        view = EventView(bundle)
        ev = bundle["event"]
        events[str(eid)] = {
            "name": (ev.get("name") or "").strip(),
            "date": _local_date(ev),
            "category": category(ev),
            "players": ev.get("starting_player_count"),
            "store": (ev.get("store") or {}).get("name"),
            "location": ev.get("full_address") or "",
            "url": event_url(eid),
        }
        for p in players:
            row = result_row(view, p["playhub_id"])
            if row:
                results.append({"player": p["id"], "event": str(eid), **row})

    print("Fetching Elo and majors from eLorcana…")
    out_players = []
    for p in players:
        elo, history = elorcana(p["elorcana"])
        fill_from_elorcana(p, history, events, results)
        out_players.append(
            {k: p[k] for k in ("id", "name", "role", "elorcana") if k in p}
            | ({"photo": p["photo"]} if p.get("photo") else {})
            | {"elo": elo}
        )
    data = {
        "updated": date.today().isoformat(),
        "search": search,
        "players": out_players,
        "events": dict(sorted(events.items(), key=lambda kv: kv[1]["date"])),
        "results": results,
    }
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {len(results)} results from {len(events)} events to {RESULTS.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
