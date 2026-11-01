"""MYHSAL team discovery and HTML normalization.

The league does not publish a documented API.  This module intentionally keeps
the small amount of HTML knowledge in one place and exposes ordinary ``Game``
objects to the rest of the application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from html.parser import HTMLParser
import logging
import re
import time as monotonic_time
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

from models import Game, Team


MYHSAL_BASE_URL = "https://myhsal.com"
LOGGER = logging.getLogger(__name__)
_TEAM_PATH = re.compile(r"^/Teams/([^/]+)/([^/]+)$", re.IGNORECASE)
_DIVISION_PATH = re.compile(r"^/Teams/([^/]+)$", re.IGNORECASE)
_SCHEDULE_DATE = re.compile(
    r"(?:[A-Za-z]{3}\s+)?(\d{1,2})/(\d{1,2}),\s*(\d{1,2}):(\d{2})\s*([AP]M)",
    re.IGNORECASE,
)
_MONTH_DAY = re.compile(r"(\d{1,2})/(\d{1,2})")


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["_Node"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    @property
    def text(self) -> str:
        parts = list(self.text_parts)
        for child in self.children:
            parts.append(child.text)
        return " ".join(" ".join(parts).split())

    def descendants(
        self,
        *,
        tag: str | None = None,
        class_name: str | None = None,
    ) -> Iterable["_Node"]:
        for child in self.children:
            if (tag is None or child.tag == tag) and (
                class_name is None or class_name in child.classes
            ):
                yield child
            yield from child.descendants(tag=tag, class_name=class_name)

    def first(
        self,
        *,
        tag: str | None = None,
        class_name: str | None = None,
    ) -> "_Node | None":
        return next(self.descendants(tag=tag, class_name=class_name), None)


class _TreeParser(HTMLParser):
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs) -> None:
        node = _Node(tag.lower(), {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if node.tag not in self._VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._VOID_TAGS:
            self.stack.pop()

    def handle_endtag(self, tag) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data) -> None:
        if data.strip():
            self.stack[-1].text_parts.append(data)


def _document(html: str) -> _Node:
    parser = _TreeParser()
    parser.feed(html)
    return parser.root


def _asset_key(slug: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", slug.upper()).strip("_")


def _team_from_node(node: _Node, base_url: str) -> Team | None:
    anchor = node.first(tag="a")
    if anchor is None:
        return None
    match = _TEAM_PATH.match(anchor.attrs.get("href", ""))
    if not match:
        return None
    slug = match.group(2).lower()
    image = node.first(tag="img")
    logo_url = None
    if image and image.attrs.get("src"):
        logo_url = urljoin(base_url, image.attrs["src"])
    return Team(
        name=anchor.text,
        abbreviation=anchor.text,
        logo_url=logo_url,
        logo_key=_asset_key(slug),
    )


def _score(value: str) -> int | str | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return value.upper()


def _closest_year_datetime(
    value: str,
    reference_date: date,
    zone: ZoneInfo,
) -> datetime:
    match = _SCHEDULE_DATE.search(value)
    if not match:
        raise ValueError(f"Unrecognized MYHSAL schedule date: {value!r}")
    month, day, hour, minute = (int(part) for part in match.groups()[:4])
    if match.group(5).upper() == "PM" and hour != 12:
        hour += 12
    elif match.group(5).upper() == "AM" and hour == 12:
        hour = 0

    candidates = [
        datetime(year, month, day, hour, minute, tzinfo=zone)
        for year in range(reference_date.year - 1, reference_date.year + 2)
    ]
    reference = datetime.combine(reference_date, time(12), tzinfo=zone)
    return min(candidates, key=lambda candidate: abs(candidate - reference))


def _schedule_datetime(
    value: str,
    reference_date: date,
    zone: ZoneInfo,
) -> tuple[datetime, str | None]:
    """Parse a scheduled time, retaining useful labels when no clock exists."""
    if _SCHEDULE_DATE.search(value):
        return (_closest_year_datetime(value, reference_date, zone), None)
    day_match = _MONTH_DAY.search(value)
    if not day_match:
        raise ValueError(f"Unrecognized MYHSAL schedule date: {value!r}")
    month, day = (int(part) for part in day_match.groups())
    candidates = [
        datetime(year, month, day, 12, 0, tzinfo=zone)
        for year in range(reference_date.year - 1, reference_date.year + 2)
    ]
    reference = datetime.combine(reference_date, time(12), tzinfo=zone)
    start = min(candidates, key=lambda candidate: abs(candidate - reference))
    doubleheader = re.search(r"DH\s*Game\s*(\d+)", value, re.IGNORECASE)
    prefix = f"DH{doubleheader.group(1)}" if doubleheader else "TBD"
    return (start, f"{prefix} {month:02d}/{day:02d}")


def _league_label(full_name: str) -> str:
    words = full_name.strip().split()
    words = [word for word in words if word.lower() not in {"boys", "girls"}]
    replacements = {"Hardball": "Baseball", "V": "Varsity"}
    words = [replacements.get(word, word) for word in words]
    if not any(word.lower().startswith(("varsity", "jv")) for word in words):
        words.insert(0, "Varsity")
    sport = words[-1]
    level = " ".join(words[:-1])
    return f"{level} {sport}".strip()


def parse_team_page(
    html: str,
    division: str,
    reference_date: date,
    zone: ZoneInfo,
    base_url: str = MYHSAL_BASE_URL,
) -> list[Game]:
    """Parse one school's current schedule and past results page."""
    root = _document(html)
    heading = next(
        (
            node.text
            for node in root.descendants(tag="h4")
            if any(
                sport in node.text.lower()
                for sport in (
                    "basketball",
                    "hockey",
                    "volleyball",
                    "soccer",
                    "tennis",
                    "softball",
                    "hardball",
                    "baseball",
                )
            )
        ),
        division.replace("-", " ").title(),
    )
    footer_label = _league_label(heading)
    games: list[Game] = []

    for item in root.descendants(tag="li", class_name="schedule_list"):
        team_nodes = list(item.descendants(class_name="schedule_name"))
        center = item.first(class_name="center_schedule")
        if len(team_nodes) < 2 or center is None:
            continue
        away = _team_from_node(team_nodes[0], base_url)
        home = _team_from_node(team_nodes[1], base_url)
        date_node = center.first(tag="h2")
        if away is None or home is None or date_node is None:
            continue
        try:
            start, scheduled_label = _schedule_datetime(
                date_node.text,
                reference_date,
                zone,
            )
        except ValueError:
            LOGGER.debug("Skipping undated MYHSAL game: %s", date_node.text)
            continue
        game_id = (
            f"{division}:{start:%Y%m%d%H%M}:"
            f"{away.logo_key}:{home.logo_key}"
        ).lower()
        games.append(
            Game(
                sport="MYHSAL",
                game_id=game_id,
                start_time_utc=start.astimezone(timezone.utc),
                status="scheduled",
                away=away,
                home=home,
                footer_label=footer_label,
                scheduled_label=scheduled_label,
            )
        )

    for item in root.descendants(tag="li", class_name="tournament_list"):
        team_nodes = list(item.descendants(class_name="name_tournament"))
        score_nodes = list(item.descendants(class_name="tournament_num"))
        overtime = item.first(class_name="overtime")
        if len(team_nodes) < 2 or len(score_nodes) < 2 or overtime is None:
            continue
        away = _team_from_node(team_nodes[0], base_url)
        home = _team_from_node(team_nodes[1], base_url)
        date_node = overtime.first(tag="p")
        if away is None or home is None or date_node is None:
            continue
        try:
            local_day = datetime.strptime(date_node.text, "%A, %B %d %Y").date()
        except ValueError:
            LOGGER.debug("Skipping undated MYHSAL result: %s", date_node.text)
            continue
        start = datetime.combine(local_day, time(12), tzinfo=zone)
        game_id = (
            f"{division}:{start:%Y%m%d}:"
            f"{away.logo_key}:{home.logo_key}"
        ).lower()
        games.append(
            Game(
                sport="MYHSAL",
                game_id=game_id,
                start_time_utc=start.astimezone(timezone.utc),
                status="final",
                away=away,
                home=home,
                away_score=_score(score_nodes[0].text),
                home_score=_score(score_nodes[1].text),
                footer_label=footer_label,
            )
        )
    return games


class MyhsalClient:
    """Discover a school's MYHSAL divisions and fetch its team pages."""

    def __init__(
        self,
        school_slug: str = "tabc",
        *,
        timezone_name: str = "America/New_York",
        timeout: float = 10.0,
        session: requests.Session | None = None,
        base_url: str = MYHSAL_BASE_URL,
    ) -> None:
        self.school_slug = school_slug.lower()
        self.zone = ZoneInfo(timezone_name)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self._divisions: tuple[str, ...] | None = None
        self._division_html: dict[str, str] = {}
        self._games_cache: list[Game] | None = None
        self._games_cached_at = 0.0
        self.games_cache_seconds = 300.0

    def _get_text(self, path: str) -> str:
        response = self.session.get(
            urljoin(self.base_url + "/", path.lstrip("/")),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    def discover_divisions(self) -> tuple[str, ...]:
        if self._divisions is not None:
            return self._divisions
        root = _document(self._get_text("/"))
        candidates: list[str] = []
        for anchor in root.descendants(tag="a"):
            match = _DIVISION_PATH.match(anchor.attrs.get("href", ""))
            if match and match.group(1) not in candidates:
                candidates.append(match.group(1))

        found: list[str] = []
        expected_suffix = f"/{self.school_slug}".lower()
        for division in candidates:
            html = self._get_text(f"/Teams/{division}")
            self._division_html[division] = html
            page = _document(html)
            if any(
                anchor.attrs.get("href", "").lower().endswith(expected_suffix)
                for anchor in page.descendants(tag="a")
            ):
                found.append(division)
        self._divisions = tuple(found)
        return self._divisions

    def get_games(self, reference_date: date | None = None) -> list[Game]:
        reference_date = reference_date or datetime.now(self.zone).date()
        now = monotonic_time.monotonic()
        if (
            self._games_cache is not None
            and now - self._games_cached_at < self.games_cache_seconds
        ):
            return list(self._games_cache)
        games: dict[str, Game] = {}
        for division in self.discover_divisions():
            html = self._get_text(f"/Teams/{division}/{self.school_slug}")
            for game in parse_team_page(
                html,
                division,
                reference_date,
                self.zone,
                self.base_url,
            ):
                games[game.game_id] = game
        self._games_cache = list(games.values())
        self._games_cached_at = now
        return list(self._games_cache)

    def discover_team_logos(self) -> dict[str, str]:
        """Return every logo used by teams in the school's divisions."""
        logos: dict[str, str] = {}
        for division in self.discover_divisions():
            html = self._division_html.get(division) or self._get_text(
                f"/Teams/{division}"
            )
            root = _document(html)
            for image in root.descendants(tag="img", class_name="team_logo"):
                parent_url = image.attrs.get("src")
                if not parent_url:
                    continue
                # The logo image is wrapped by the team-page link.
                team_link = next(
                    (
                        anchor.attrs.get("href", "")
                        for anchor in root.descendants(tag="a")
                        if any(child is image for child in anchor.children)
                    ),
                    "",
                )
                match = _TEAM_PATH.match(team_link)
                if match:
                    logos.setdefault(
                        _asset_key(match.group(2)),
                        urljoin(self.base_url, parent_url),
                    )
        return logos
