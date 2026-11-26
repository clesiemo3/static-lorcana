"""Event cache: one gzipped JSON bundle per event, portable as a single tar file.

Bundles are normalized (profile-picture URLs and other bulky fields dropped) so the
cache stays small. Completed events never change, so they are only fetched once.
"""

from __future__ import annotations

import gzip
import json
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .api import Client
from .events import categorize

SCHEMA_VERSION = 1
DEFAULT_CACHE_DIR = Path(os.environ.get("LSA_CACHE_DIR", "cache"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- normalization -------------------------------------------------------


def _norm_event(ev: dict) -> dict:
    store = ev.get("store") or {}
    settings = ev.get("settings") or {}
    phases = []
    for p in sorted(ev.get("tournament_phases") or [], key=lambda p: p.get("order_in_phases") or 0):
        phases.append(
            {
                "id": p["id"],
                "name": p.get("phase_name"),
                "order": p.get("order_in_phases"),
                "round_type": p.get("round_type"),
                "status": p.get("status"),
                "rank_required_to_enter": p.get("rank_required_to_enter_phase"),
                "rounds": [
                    {
                        "id": r["id"],
                        "round_number": r.get("round_number"),
                        "status": r.get("status"),
                        "standings_status": r.get("standings_status"),
                    }
                    for r in sorted(p.get("rounds") or [], key=lambda r: r.get("round_number") or 0)
                ],
            }
        )
    return {
        "id": ev["id"],
        "name": ev.get("name"),
        "start_datetime": ev.get("start_datetime"),
        "end_datetime": ev.get("end_datetime"),
        "timezone": ev.get("timezone"),
        "display_status": ev.get("display_status"),
        "event_status": ev.get("event_status"),
        "lifecycle_status": settings.get("event_lifecycle_status"),
        "template_id": ev.get("event_configuration_template"),
        "gameplay_format": (ev.get("gameplay_format") or {}).get("name"),
        "is_online": ev.get("event_is_online"),
        "is_test_event": ev.get("is_test_event"),
        "full_address": ev.get("full_address"),
        "store": {
            "id": store.get("id"),
            "name": store.get("name"),
            "region": store.get("administrative_area_level_1_short"),
            "country": store.get("country"),
        },
        "starting_player_count": ev.get("starting_player_count"),
        "registered_user_count": ev.get("registered_user_count"),
        "tiebreakers": ev.get("tiebreakers"),
        "phases": phases,
    }


def _norm_standing(s: dict) -> dict:
    ues = s.get("user_event_status") or {}
    player = s.get("player") or {}
    return {
        "user_id": player.get("id") or (ues.get("user") or {}).get("id"),
        "display_name": player.get("best_identifier"),
        "username": ues.get("best_identifier"),
        "is_guest": ues.get("is_guest"),
        "registration_status": ues.get("registration_status"),
        "rank": s.get("rank"),
        "match_record": s.get("match_record"),
        "match_points": s.get("match_points"),
        "omw": s.get("opponent_match_win_percentage"),
        "gw": s.get("game_win_percentage"),
        "ogw": s.get("opponent_game_win_percentage"),
    }


def _norm_match(m: dict, round_id: int, round_number: int, phase_id: int) -> dict:
    players = []
    for rel in sorted(m.get("player_match_relationships") or [], key=lambda r: r.get("player_order") or 0):
        p = rel.get("player") or {}
        players.append(p.get("id"))
    return {
        "id": m["id"],
        "round_id": round_id,
        "round_number": round_number,
        "phase_id": phase_id,
        "table": m.get("table_number"),
        "status": m.get("status"),
        "players": players or m.get("players") or [],
        "winner": m.get("winning_player"),
        "games_won_by_winner": m.get("games_won_by_winner"),
        "games_won_by_loser": m.get("games_won_by_loser"),
        "games_drawn": m.get("games_drawn"),
        "is_bye": m.get("match_is_bye"),
        "is_intentional_draw": m.get("match_is_intentional_draw"),
        "is_double_loss": m.get("match_is_loss"),
    }


def is_complete(event: dict) -> bool:
    return event.get("display_status") == "complete" or event.get("lifecycle_status") == "EVENT_FINISHED"


def build_bundle(client: Client, event_id: int) -> dict:
    """Fetch an event's details, phase-end standings and all matches."""
    event = _norm_event(client.event(event_id))
    standings: dict[str, list[dict]] = {}
    matches: list[dict] = []
    for phase in event["phases"]:
        generated = [r for r in phase["rounds"] if r["standings_status"] == "GENERATED"]
        if generated:
            last = generated[-1]
            standings[str(last["id"])] = [_norm_standing(s) for s in client.round_standings(last["id"])]
        for r in phase["rounds"]:
            if r["status"] in ("COMPLETE", "IN_PROGRESS") or r["standings_status"] == "GENERATED":
                matches.extend(
                    _norm_match(m, r["id"], r["round_number"], phase["id"]) for m in client.round_matches(r["id"])
                )
    return {
        "schema": SCHEMA_VERSION,
        "fetched_at": _now(),
        "complete": is_complete(event),
        "event": event,
        "standings": standings,
        "matches": matches,
    }


# --- storage ---------------------------------------------------------------


class Cache:
    def __init__(self, root: Path | str = DEFAULT_CACHE_DIR):
        self.root = Path(root)
        self.events_dir = self.root / "events"

    def path(self, event_id: int) -> Path:
        return self.events_dir / f"{event_id}.json.gz"

    def has(self, event_id: int) -> bool:
        return self.path(event_id).exists()

    def load(self, event_id: int) -> dict | None:
        p = self.path(event_id)
        if not p.exists():
            return None
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)

    def save(self, bundle: dict) -> Path:
        self.events_dir.mkdir(parents=True, exist_ok=True)
        p = self.path(bundle["event"]["id"])
        tmp = p.with_suffix(".tmp")
        # mtime=0 keeps the gzip bytes deterministic for identical content.
        with open(tmp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(json.dumps(bundle, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        tmp.replace(p)
        return p

    def ids(self) -> list[int]:
        if not self.events_dir.exists():
            return []
        return sorted(int(p.name.split(".")[0]) for p in self.events_dir.glob("*.json.gz"))

    def category(self, event_id: int) -> str:
        e = (self.load(event_id) or {}).get("event") or {}
        return categorize(e.get("name"), e.get("template_id"))

    def iter_bundles(self, ids: list[int] | None = None) -> Iterator[dict]:
        for eid in ids if ids is not None else self.ids():
            b = self.load(eid)
            if b is not None:
                yield b

    def ensure(self, client: Client, event_id: int, refresh: bool = False) -> tuple[dict, bool]:
        """Return (bundle, fetched). Completed cached events are reused unless refresh=True."""
        existing = self.load(event_id)
        if existing and existing.get("complete") and existing.get("schema") == SCHEMA_VERSION and not refresh:
            return existing, False
        bundle = build_bundle(client, event_id)
        self.save(bundle)
        return bundle, True

    # --- portability -------------------------------------------------------

    def export(self, dest: Path | str, ids: list[int] | None = None) -> int:
        """Write cached bundles into a single tar (bundles are already gzipped)."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with tarfile.open(dest, "w") as tar:
            for eid in ids if ids is not None else self.ids():
                p = self.path(eid)
                if p.exists():
                    tar.add(p, arcname=f"events/{p.name}")
                    n += 1
        return n

    def import_(self, src: Path | str, overwrite: bool = False) -> tuple[int, int]:
        """Merge bundles from an exported tar. Keeps the newer/complete copy on conflict."""
        added = skipped = 0
        self.events_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(src, "r:*") as tar:
            for member in tar.getmembers():
                name = Path(member.name).name
                if not member.isfile() or not name.endswith(".json.gz") or not name.split(".")[0].isdigit():
                    continue
                data = tar.extractfile(member).read()
                incoming = json.loads(gzip.decompress(data))
                current = self.load(incoming["event"]["id"])
                if current and not overwrite and not _is_better(incoming, current):
                    skipped += 1
                    continue
                self.save(incoming)
                added += 1
        return added, skipped


def _is_better(a: dict, b: dict) -> bool:
    if a.get("complete") != b.get("complete"):
        return bool(a.get("complete"))
    return (a.get("fetched_at") or "") > (b.get("fetched_at") or "")

