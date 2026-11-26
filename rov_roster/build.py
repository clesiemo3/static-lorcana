"""Build the Rules of Villainy roster page from results.json.

results.json is written by update.py (Play Hub results plus eLorcana Elo).
This module decides which finishes are highlighted, so the thresholds can be
recalibrated here without fetching anything. Player photos are optional files
in photos/ named after the player id (jimmy.jpg) or given as `photo` in
team.toml, plus favorite card images (jimmy-card1.jpg, …); players without a
photo show their initials. Profile text (title, bio, inks, favorite cards)
comes from team.toml.
"""

import json
import math
import shutil
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "results.json"
TEAM = HERE / "team.toml"
PROFILE_FIELDS = ("title", "started", "inks", "favorite_cards", "bio", "outside")
TEMPLATE = HERE / "template.html"
PHOTOS = HERE / "photos"
OUT_NAME = "rov-roster.html"
PHOTO_DIR = "rov-roster-photos"
PHOTO_TYPES = (".jpg", ".jpeg", ".png", ".webp")

# Events smaller than this never count as highlights, except set
# championships, which count at any size. (DLCs, LCQs and championships are
# always far bigger.) Keep in step with min_players in team.toml.
MIN_PLAYERS = 30
# Set championship top 4 / top 8 finishes count from these field sizes.
SET_TOP4_MIN = 12
SET_TOP8_MIN = 24


def highlight(category: str, players: int, r: dict) -> dict | None:
    """Return {"label", "tier"} for a highlighted finish, or None.

    tier: "win" (1st), "final" (2nd), "top" (top 8 at a set championship or
    local event, or a top cut at a CCQ, DLC or championship), "good" (strong
    finish short of that).
    """
    rank, wins = r.get("rank"), r.get("wins") or 0
    if not rank or (category != "SET" and (players or 0) < MIN_PLAYERS):
        return None
    if rank == 1:
        return {"label": "1st", "tier": "win"}
    if rank == 2:
        return {"label": "2nd", "tier": "final"}
    if category == "SET":
        # 1st and 2nd always count; top 4 and top 8 only in fields big enough
        # that they mean something (small set championships are common).
        if rank <= 4 and players >= SET_TOP4_MIN:
            return {"label": "Top 4", "tier": "top"}
        if rank <= 8 and players >= SET_TOP8_MIN:
            return {"label": "Top 8", "tier": "top"}
        return None
    if category == "LOCAL":
        return {"label": "Top 4" if rank <= 4 else "Top 8", "tier": "top"} if rank <= 8 else None
    if category == "CCQ":
        for n in (4, 8, 16, 32):
            if rank <= n:
                return {"label": f"Top {n}", "tier": "top" if r.get("made_top_cut") else "good"}
        return None
    if category == "DLC":
        if r.get("made_top_cut"):
            return {"label": f"Top {_bucket(rank)}", "tier": "top"}
        return {"label": f"{wins} wins", "tier": "good"} if wins >= 6 else None
    if category == "LCQ":
        return {"label": f"{wins} wins", "tier": "good"} if wins >= 4 else None
    if category == "CHAMPIONSHIP":
        if rank <= 64:
            return {"label": f"Top {_bucket(rank)}", "tier": "top" if r.get("made_top_cut") else "good"}
        return None
    return None


# How impressive a finish is, for ordering "best finishes": log2(field size /
# rank), so each halving of the field you finish ahead of is worth a point
# (1st of 32 = 5, 21st of 1,747 = 6.4), plus a bonus for premier events.
PREMIER_BONUS = {"DLC": 1.0, "CHAMPIONSHIP": 1.0, "CCQ": 0.5, "LCQ": 0.5}


def score(category: str, players: int, r: dict) -> float | None:
    rank = r.get("rank")
    if not rank or not players:
        return None
    return round(math.log2(max(players, rank) / rank) + PREMIER_BONUS.get(category, 0), 3)


def _bucket(rank: int) -> int:
    n = 4
    while n < rank:
        n *= 2
    return n


def photo_for(player: dict) -> Path | None:
    if player.get("photo"):
        p = PHOTOS / player["photo"]
        return p if p.exists() else None
    for ext in PHOTO_TYPES:
        p = PHOTOS / f"{player['id']}{ext}"
        if p.exists():
            return p
    return None


def build(out_dir: Path) -> Path:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    for r in data["results"]:
        ev = data["events"][r["event"]]
        r["highlight"] = highlight(ev["category"], ev["players"], r)
        r["score"] = score(ev["category"], ev["players"], r)

    # Profiles come straight from team.toml, so editing them needs no refetch.
    with open(TEAM, "rb") as f:
        profiles = {p["id"]: p for p in tomllib.load(f)["player"]}
    photo_out = out_dir / PHOTO_DIR

    def publish(src: Path) -> str:
        photo_out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, photo_out / src.name)
        return f"{PHOTO_DIR}/{src.name}"

    for p in data["players"]:
        prof = profiles.get(p["id"], {})
        p.update({k: prof[k] for k in PROFILE_FIELDS if k in prof})
        src = photo_for(prof or p)
        p.pop("photo", None)
        if src:
            p["photo"] = publish(src)
        cards = sorted(PHOTOS.glob(f"{p['id']}-card*.jpg"))
        if cards:
            p["card_images"] = [publish(c) for c in cards]

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("__ROSTER_JSON__", payload)
    out = out_dir / OUT_NAME
    out.write_text(page, encoding="utf-8")
    return out
