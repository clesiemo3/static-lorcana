"""Build per-player, per-event performance rows from cached event bundles."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from .api import event_url
from .events import categorize

HISTORY_FIELDS = [
    "event_date",
    "category",
    "event_name",
    "event_id",
    "location",
    "players",
    "user_id",
    "display_name",
    "username",
    "final_rank",
    "record",
    "wins",
    "losses",
    "draws",
    "match_points",
    "match_win_pct",
    "byes",
    "games_won",
    "games_lost",
    "games_drawn",
    "game_win_pct",
    "opp_match_win_pct",
    "opp_game_win_pct",
    "swiss_rank",
    "swiss_record",
    "made_top_cut",
    "top_cut_record",
    "last_phase",
    "event_url",
]

SUMMARY_FIELDS = [
    "user_id",
    "display_name",
    "username",
    "events",
    "wins",
    "losses",
    "draws",
    "match_win_pct",
    "games_won",
    "games_lost",
    "game_win_pct",
    "top_cuts",
    "best_finish",
    "best_finish_event",
]


def _parse_record(rec: str | None) -> tuple[int, int, int]:
    """Play Hub records are 'W-L-D'."""
    try:
        w, l, d = (int(x) for x in (rec or "").split("-"))
        return w, l, d
    except ValueError:
        return 0, 0, 0


def _local_date(ev: dict) -> str:
    start = ev.get("start_datetime")
    if not start:
        return ""
    dt = datetime.fromisoformat(start)
    try:
        if ev.get("timezone"):
            dt = dt.astimezone(ZoneInfo(ev["timezone"]))
    except Exception:
        pass
    return dt.date().isoformat()


def _pct(num: float, den: float) -> float | str:
    return round(num / den, 4) if den else ""


class EventView:
    """Derived per-player stats for one cached event bundle."""

    def __init__(self, bundle: dict):
        self.bundle = bundle
        self.event = ev = bundle["event"]
        phases = ev["phases"]
        self.phase_by_id = {p["id"]: p for p in phases}
        round_to_phase = {r["id"]: p for p in phases for r in p["rounds"]}
        # A top cut is an elimination phase entered from an earlier phase; events that are
        # single elimination from round 1 (e.g. LCQs) have no cut.
        first_order = min((p.get("order") or 0 for p in phases), default=0)
        self.cut_phase_ids = {
            p["id"] for p in phases if p["round_type"] != "SWISS" and (p.get("order") or 0) > first_order
        }

        # Phase-end standings, keyed by phase.
        standings_by_phase = {}
        for round_id, rows in bundle["standings"].items():
            p = round_to_phase.get(int(round_id))
            if p is not None:
                standings_by_phase[p["id"]] = {r["user_id"]: r for r in rows if r.get("user_id")}
        ordered = [p for p in phases if p["id"] in standings_by_phase]
        self.final = standings_by_phase[ordered[-1]["id"]] if ordered else {}
        swiss = [p for p in ordered if p["round_type"] == "SWISS"]
        self.swiss = standings_by_phase[swiss[-1]["id"]] if swiss else {}

        # Game counts, byes and top-cut results from individual matches.
        self.stats: dict[int, dict] = defaultdict(
            lambda: {"byes": 0, "gw": 0, "gl": 0, "gd": 0, "cut_w": 0, "cut_l": 0, "cut_d": 0, "phases": set()}
        )
        for m in bundle["matches"]:
            players = [p for p in m["players"] if p]
            elim = m["phase_id"] in self.cut_phase_ids
            for pid in players:
                s = self.stats[pid]
                s["phases"].add(m["phase_id"])
                if m.get("is_bye") or len(players) < 2:
                    s["byes"] += 1
                    continue
                ww, wl, gd = m.get("games_won_by_winner") or 0, m.get("games_won_by_loser") or 0, m.get("games_drawn") or 0
                s["gd"] += gd
                if m.get("winner") is None:
                    s["gw"] += ww
                    s["gl"] += wl
                    if elim:
                        s["cut_d"] += 1
                elif m["winner"] == pid:
                    s["gw"] += ww
                    s["gl"] += wl
                    if elim:
                        s["cut_w"] += 1
                else:
                    s["gw"] += wl
                    s["gl"] += ww
                    if elim:
                        s["cut_l"] += 1

        self.participants = set(self.final) | set(self.stats)

    def row(self, user_id: int, category: str) -> dict | None:
        if user_id not in self.participants:
            return None
        ev = self.event
        f = self.final.get(user_id, {})
        sw = self.swiss.get(user_id, {})
        st = self.stats.get(user_id) or {"byes": 0, "gw": 0, "gl": 0, "gd": 0, "cut_w": 0, "cut_l": 0, "cut_d": 0, "phases": set()}
        w, l, d = _parse_record(f.get("match_record"))
        played = [self.phase_by_id[p] for p in st["phases"] if p in self.phase_by_id]
        played.sort(key=lambda p: p.get("order") or 0)
        made_cut = any(p["id"] in self.cut_phase_ids for p in played)
        return {
            "event_date": _local_date(ev),
            "category": category,
            "event_name": ev.get("name"),
            "event_id": ev["id"],
            "location": ev.get("full_address") or "",
            "players": ev.get("starting_player_count"),
            "user_id": user_id,
            "display_name": f.get("display_name") or sw.get("display_name") or "",
            "username": f.get("username") or sw.get("username") or "",
            "final_rank": f.get("rank", ""),
            "record": f.get("match_record", ""),
            "wins": w,
            "losses": l,
            "draws": d,
            "match_points": f.get("match_points", ""),
            "match_win_pct": _pct(w, w + l + d),
            "byes": st["byes"],
            "games_won": st["gw"],
            "games_lost": st["gl"],
            "games_drawn": st["gd"],
            "game_win_pct": f.get("gw", ""),
            "opp_match_win_pct": f.get("omw", ""),
            "opp_game_win_pct": f.get("ogw", ""),
            "swiss_rank": sw.get("rank", ""),
            "swiss_record": sw.get("match_record", ""),
            "made_top_cut": made_cut,
            "top_cut_record": f"{st['cut_w']}-{st['cut_l']}-{st['cut_d']}" if made_cut else "",
            "last_phase": played[-1]["name"] if played else "",
            "event_url": event_url(ev["id"]),
        }

    def identities(self) -> Iterable[tuple[int, str, str]]:
        for uid, r in self.final.items():
            yield uid, r.get("username") or "", r.get("display_name") or ""


def resolve_players(players: list[dict], views: list[EventView], log=print) -> list[dict]:
    """Fill in user_id for players given only by username / display name."""
    by_username: dict[str, set[int]] = defaultdict(set)
    by_name: dict[str, set[int]] = defaultdict(set)
    for v in views:
        for uid, uname, dname in v.identities():
            if uname:
                by_username[uname.lower()].add(uid)
            if dname:
                by_name[dname.lower()].add(uid)
    out = []
    for p in players:
        if p.get("user_id"):
            out.append(p)
            continue
        hits = by_username.get(p.get("username", "").lower()) or by_name.get(p.get("display_name", "").lower()) or set()
        label = p.get("username") or p.get("display_name")
        if len(hits) == 1:
            out.append({**p, "user_id": next(iter(hits))})
        elif not hits:
            log(f"  warning: no cached results for {label!r}")
        else:
            log(f"  warning: {label!r} is ambiguous ({len(hits)} Play Hub users: {sorted(hits)}); add a user_id column")
    return out


def build_history(
    bundles: Iterable[dict],
    players: list[dict],
    category_overrides: dict[int, str] | None = None,
    log=print,
) -> list[dict]:
    views = [EventView(b) for b in bundles if b["standings"] or b["matches"]]
    players = resolve_players(players, views, log=log)
    wanted = {int(p["user_id"]) for p in players}
    overrides = category_overrides or {}
    rows = []
    for v in views:
        cat = overrides.get(v.event["id"]) or categorize(v.event.get("name"), v.event.get("template_id"))
        for uid in wanted & v.participants:
            r = v.row(uid, cat)
            if r:
                rows.append(r)
    rows.sort(key=lambda r: (r["display_name"].lower(), r["user_id"], r["event_date"], r["event_id"]))
    return rows


def build_summary(history: list[dict]) -> list[dict]:
    agg: dict[int, dict] = {}
    for r in history:
        a = agg.setdefault(
            r["user_id"],
            {k: 0 for k in ("events", "wins", "losses", "draws", "games_won", "games_lost", "top_cuts")}
            | {"user_id": r["user_id"], "display_name": r["display_name"], "username": r["username"], "_best": None},
        )
        a["events"] += 1
        for k in ("wins", "losses", "draws", "games_won", "games_lost"):
            a[k] += r[k] or 0
        a["top_cuts"] += 1 if r["made_top_cut"] else 0
        if r["final_rank"] != "" and (a["_best"] is None or r["final_rank"] < a["_best"][0]):
            a["_best"] = (r["final_rank"], f"{r['event_name']} ({r['event_date']}, {r['players']} players)")
    out = []
    for a in agg.values():
        best = a.pop("_best")
        a["match_win_pct"] = _pct(a["wins"], a["wins"] + a["losses"] + a["draws"])
        a["game_win_pct"] = _pct(a["games_won"], a["games_won"] + a["games_lost"])
        a["best_finish"], a["best_finish_event"] = best if best else ("", "")
        out.append(a)
    return sorted(out, key=lambda a: (-a["events"], a["display_name"].lower()))


def write_csv(path: Path | str, rows: list[dict], fields: list[str]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
