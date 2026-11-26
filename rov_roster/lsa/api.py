"""Minimal client for the public Ravensburger Play Hub API (api.ravensburgerplay.com)."""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator

API_BASE = "https://api.ravensburgerplay.com/api/v2"
SITE_BASE = "https://tcg.ravensburgerplay.com"
GAME_SLUG = "disney-lorcana"
USER_AGENT = "lorcana-standings-aggregator/0.1 (+local analysis tool)"


class ApiError(RuntimeError):
    pass


class Client:
    """Thread-safe, politely rate-limited JSON client with retries."""

    def __init__(self, min_interval: float = 0.15, max_retries: int = 5, timeout: float = 60):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self._lock = threading.Lock()
        self._next_at = 0.0
        self.request_count = 0

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            self._next_at = max(now, self._next_at) + self.min_interval
            self.request_count += 1
        if wait > 0:
            time.sleep(wait)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = path if path.startswith("http") else f"{API_BASE}/{path.lstrip('/')}"
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}, doseq=True
            )
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    retry_after = e.headers.get("Retry-After")
                    time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else delay)
                    delay *= 2
                    continue
                body = e.read()[:300].decode("utf-8", "replace")
                raise ApiError(f"GET {url} -> HTTP {e.code}: {body}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise ApiError(f"GET {url} failed: {e}") from e
        raise ApiError(f"GET {url} failed after retries")

    def paginate(self, path: str, params: dict[str, Any] | None = None, page_size: int = 500) -> Iterator[dict]:
        """Iterate over results of a page-number paginated endpoint."""
        page = 1
        while True:
            data = self.get(path, {**(params or {}), "page": page, "page_size": page_size})
            yield from data.get("results", [])
            nxt = data.get("next_page_number") or data.get("next")
            if not nxt or not data.get("results"):
                return
            page = int(nxt)

    # --- typed helpers -------------------------------------------------

    def event(self, event_id: int) -> dict:
        return self.get(f"events/{event_id}/")

    def registrations(self, event_id: int) -> list[dict]:
        return list(self.paginate(f"events/{event_id}/registrations/"))

    def round_standings(self, round_id: int) -> list[dict]:
        return list(self.paginate(f"tournament-rounds/{round_id}/standings/paginated/", page_size=1000))

    def round_matches(self, round_id: int) -> list[dict]:
        return list(self.paginate(f"tournament-rounds/{round_id}/matches/paginated/", page_size=1000))

    def search_events(self, **params: Any) -> Iterator[dict]:
        return self.paginate("events/", {"game_slug": GAME_SLUG, **params}, page_size=250)


_EVENT_ID_RE = re.compile(r"(?:/events/)?(\d+)/?(?:[?#].*)?$")


def parse_event_id(value: str | int) -> int:
    """Accept '770995', 770995 or 'https://tcg.ravensburgerplay.com/events/770995'."""
    if isinstance(value, int):
        return value
    m = _EVENT_ID_RE.search(value.strip())
    if not m:
        raise ValueError(f"Can't find an event id in {value!r}")
    return int(m.group(1))


def event_url(event_id: int) -> str:
    return f"{SITE_BASE}/events/{event_id}"
