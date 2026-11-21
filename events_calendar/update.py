"""Weekly update: research Lorcana events with Claude Code and rewrite events.json.

Runs the Claude Code CLI headless with only web search and fetch, so it uses
your Claude subscription (log in by running `claude` once). Claude returns the
full updated event list as JSON; this script only writes it when it passes:

- the checks in build.validate (types, dates, regions, sources);
- source checking: every source URL must have come up in this run's searches
  or fetches, or already be in events.json. A new event with no checkable
  source is dropped, and a changed event falls back to its previous version;
- a removal guard: if too many upcoming events would disappear at once, the
  run is rejected and events.json is left alone.

    python3 events_calendar/update.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from events_calendar import build  # noqa: E402

TIMEOUT_SECONDS = 30 * 60
TOOLS = ["WebSearch", "WebFetch"]
URL = re.compile(r"https?://[^\s\"'<>\\)\]]+")
# Reject the run if more upcoming events than this would vanish (renames count).
MAX_REMOVED = 6

SYSTEM = """You maintain a calendar of upcoming Disney Lorcana TCG events for players.
You research with web search and fetch, then return the complete, corrected event list as JSON.
Accuracy matters more than coverage: never invent an event, date or source. Every source URL
you return must be a page you actually saw in a search result or fetched in this session."""

PROMPT = """Today is {today}. Update the Lorcana events calendar for {today} through {end}.

Event types:
- "dlc": Disney Lorcana Challenge weekends (all regions).
- "ccq": Challenge Championship Qualifiers (Core Constructed CCQs at stores and conventions).
- "champ": continental championships and the World Championship.
- "set": set releases (prerelease and general release as separate events when both are known).

Certainty ("cert"):
- "official": the date is on disneylorcana.com or another official Ravensburger/Disney page.
- "reported": an exact date only from fan trackers, retailers or organizer pages.
- "window": only a range is known, like "Q2 2027" or "September or October 2027". Set start/end
  to the whole range (Q2 2027 = 2027-04-01 to 2027-06-30) and put the original wording in "when".

Check at least these pages for changes, then search for anything new:
- https://www.disneylorcana.com/en-US/play/lorcana-challenge
- https://lorcanaplayer.com/disney-lorcana-challenge-26-27-tracker/
- https://lorcanaplayer.com/lorcana-release-event-calendar/
- disneylorcana.com news posts about new sets, championships and season announcements

Rules:
- Start from the current data below and return the COMPLETE list, not just changes.
- Keep each existing event's "name" exactly as it is unless the name itself is wrong, so changes
  can be tracked from week to week.
- Remove events that were cancelled. Keep events that already happened this month; drop older ones.
- Upgrade "reported" to "official" (or a window to exact dates) when an official page confirms it,
  and update "sources" to the confirming page.
- When sources disagree, prefer the official site and say so briefly in "note".
- Regions: "North America", "Europe", "Asia", "Oceania", "South America", or "Worldwide"
  (worldwide set releases and the World Championship).
- "note": one short sentence of useful detail (venue, player cap, moved dates), or omit it.
- "tba": championships and series announced with no date or window yet. Remove an entry once it
  has a date or window (it then belongs in events).
- "changes": short plain-English lines describing what you changed and why, e.g.
  "Added Denver CCQ (Jan 9, 2027) from disneylorcana.com". Empty if nothing changed.

Current data:
{current}"""

EVENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "cert", "name", "start", "region", "sources"],
    "properties": {
        "type": {"enum": sorted(build.TYPES)},
        "cert": {"enum": sorted(build.CERTS)},
        "name": {"type": "string"},
        "city": {"type": "string"},
        "country": {"type": "string"},
        "start": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "end": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "when": {"type": "string"},
        "region": {"enum": sorted(build.REGIONS)},
        "note": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    },
}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["events", "tba", "changes"],
    "properties": {
        "events": {"type": "array", "items": EVENT_SCHEMA},
        "tba": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False, "required": ["name", "region"],
                "properties": {"name": {"type": "string"}, "region": {"enum": sorted(build.REGIONS)}},
            },
        },
        "changes": {"type": "array", "items": {"type": "string"}},
    },
}


def run_claude(prompt: str) -> tuple[dict, set[str]]:
    """Run Claude Code headless; return its structured output and every URL it saw."""
    binary = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
    if not binary:
        raise SystemExit("Claude Code CLI not found. Install it and log in by running `claude` once.")
    cmd = [
        binary, "-p",
        "--output-format", "stream-json", "--verbose",
        "--system-prompt", SYSTEM,
        # Only web tools, no MCP servers, nothing that needs a human to approve.
        "--tools", ",".join(TOOLS), "--allowedTools", ",".join(TOOLS),
        "--strict-mcp-config", "--permission-mode", "dontAsk", "--no-session-persistence",
        "--json-schema", json.dumps(SCHEMA),
    ]
    # An API key in the environment would take precedence over the subscription login.
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    # Run from an empty folder so no project CLAUDE.md, hooks or settings get loaded.
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=env, cwd=cwd, timeout=TIMEOUT_SECONDS)

    result, seen = None, set()
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") in ("assistant", "user"):
            # URLs from fetch requests and from search/fetch results both count as seen.
            seen.update(URL.findall(json.dumps((event.get("message") or {}).get("content"))))
        elif event.get("type") == "result":
            result = event
    if result is None:
        raise SystemExit(f"Claude Code exited with {proc.returncode} and no result: {proc.stderr.strip()[:500]}")
    if result.get("is_error") or not result.get("structured_output"):
        raise SystemExit(f"Claude Code failed ({result.get('subtype')}): {str(result.get('result'))[:500]}")
    cost = result.get("total_cost_usd")
    print(f"Claude Code finished; saw {len(seen)} URLs" + (f"; usage equivalent ${cost:.2f}" if cost else ""))
    return result["structured_output"], {norm(u) for u in seen}


def norm(url: str) -> str:
    return url.rstrip(".,;").rstrip("/").lower()


def main() -> None:
    today = date.today()
    current = build.load()
    known = {norm(u) for e in current["events"] for u in e["sources"]}
    old_by_name = {e["name"]: e for e in current["events"]}

    prompt = PROMPT.format(
        today=today.isoformat(), end=(today + timedelta(days=366)).isoformat(),
        current=json.dumps({"events": current["events"], "tba": current.get("tba", [])}, ensure_ascii=False, indent=1))
    out, seen = run_claude(prompt)
    trusted = seen | known

    events, notes = [], []
    for e in out["events"]:
        e = {k: v for k, v in e.items() if v not in ("", None)}
        sources = [s for s in e.get("sources", []) if norm(s) in trusted]
        if sources:
            events.append({**e, "sources": sources})
        elif e["name"] in old_by_name:
            events.append(old_by_name[e["name"]])
            notes.append(f"Kept the previous version of {e['name']}: its new sources weren't seen in this run.")
        else:
            notes.append(f"Dropped new event {e['name']}: none of its sources were seen in this run.")

    # Upcoming events that vanished (by name) since last week.
    new_names = {e["name"] for e in events}
    removed = [e["name"] for e in current["events"]
               if date.fromisoformat(e.get("end", e["start"])) >= today and e["name"] not in new_names]
    if len(removed) > MAX_REMOVED:
        raise SystemExit(f"Rejected: {len(removed)} upcoming events would be removed at once "
                         f"(limit {MAX_REMOVED}): {removed}. events.json unchanged.")

    data = {"checked": today.isoformat(), "events": events, "tba": out.get("tba", [])}
    if problems := build.validate(data):
        raise SystemExit("Rejected: the update has problems:\n  " + "\n  ".join(problems))
    build.dump(data)

    added = sorted(new_names - set(old_by_name))
    print(f"Wrote {len(events)} events ({len(added)} new, {len(removed)} removed).")
    for line in out.get("changes", []) + notes + [f"Removed: {n}" for n in removed]:
        print(f"- {line}")


if __name__ == "__main__":
    main()
