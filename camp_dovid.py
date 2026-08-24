"""Camp Dovid JR tournament fetching, caching, and display-card construction."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

from config import CampDovidConfig
from models import DisplayCard, RichTextCard, RichTextLine, RichTextSpan


LOGGER = logging.getLogger(__name__)

WHITE = (255, 255, 255)
CAMP_BLUE = (102, 153, 204)
TEAM_COLORS = (
    (0, 220, 255),
    (255, 196, 0),
    (255, 80, 120),
    (120, 255, 90),
    (255, 130, 40),
    (185, 120, 255),
    (255, 70, 70),
    (40, 230, 180),
    (255, 235, 90),
    (100, 160, 255),
)


@dataclass(frozen=True, slots=True)
class CampStanding:
    rank: int
    team: str
    games_played: int
    wins: int
    losses: int
    ties: int
    points: int


@dataclass(frozen=True, slots=True)
class CampGame:
    game_id: str
    start_time_utc: datetime
    status: str
    away_team: str
    home_team: str
    away_score: int | None = None
    home_score: int | None = None
    location: str = ""


@dataclass(frozen=True, slots=True)
class CampSnapshot:
    standings: tuple[CampStanding, ...] = ()
    games: tuple[CampGame, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def has_data(self) -> bool:
        return bool(self.standings or self.games)


class CampDovidFetcher:
    """Fetch GameSheet's public JSON data no more than once per configured TTL."""

    def __init__(
        self,
        config: CampDovidConfig,
        zone: ZoneInfo,
        timeout: float = 10.0,
        session: requests.Session | None = None,
        monotonic=time.monotonic,
    ) -> None:
        self.config = config
        self.zone = zone
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "Sports-Score-Display/1.0 Camp-Dovid",
            }
        )
        self._monotonic = monotonic
        self._last_attempt: float | None = None
        self._snapshot = CampSnapshot()

    def fetch(self, now: datetime) -> CampSnapshot:
        """Return cached data, refreshing each section independently every 30 minutes."""
        if not self.config.enabled or not self._is_active(now):
            return CampSnapshot()

        current = self._monotonic()
        if (
            self._last_attempt is not None
            and current - self._last_attempt < self.config.refresh_seconds
        ):
            return self._snapshot
        self._last_attempt = current

        standings = self._snapshot.standings
        games = self._snapshot.games
        errors: list[str] = []

        try:
            payload = self._get_json(
                f"useStandings/getDivisionStandings/{self.config.season_id}",
                {
                    "filter[divisions]": str(self.config.division_id),
                    "filter[limit]": 100,
                    "filter[offset]": 0,
                    "filter[timeZoneOffset]": self._timezone_offset(now),
                },
            )
            standings = tuple(
                self.parse_standings(payload, self.config.division_id)
            )
        except Exception as exc:
            LOGGER.warning("Camp Dovid standings refresh failed: %s", exc)
            errors.append("standings")

        try:
            payload = self._get_json(
                f"useSchedule/getSeasonSchedule/{self.config.season_id}",
                {
                    "filter[divisions]": str(self.config.division_id),
                    "filter[gametype]": "overall",
                    "filter[limit]": 100,
                    "filter[offset]": 0,
                    "filter[timeZoneOffset]": self._timezone_offset(now),
                },
            )
            parsed_games = self.parse_schedule(payload, self.zone)
            games = tuple(self._enrich_recent_finals(parsed_games))
        except Exception as exc:
            LOGGER.warning("Camp Dovid schedule refresh failed: %s", exc)
            errors.append("schedule")

        self._snapshot = CampSnapshot(
            standings=standings,
            games=games,
            errors=tuple(errors),
        )
        return self._snapshot

    def _is_active(self, now: datetime) -> bool:
        local_date = now.astimezone(self.zone).date()
        return (
            self.config.active_through is None
            or local_date <= self.config.active_through
        )

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        response = self.session.get(
            f"{self.config.api_base_url}/{path}",
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _enrich_recent_finals(self, games: list[CampGame]) -> list[CampGame]:
        final_ids = {
            game.game_id
            for game in sorted(
                (game for game in games if game.status == "final"),
                key=lambda item: item.start_time_utc,
                reverse=True,
            )[: self.config.recent_results]
            if game.away_score is None or game.home_score is None
        }
        if not final_ids:
            return games

        enriched: list[CampGame] = []
        for game in games:
            if game.game_id not in final_ids:
                enriched.append(game)
                continue
            try:
                payload = self._get_json(
                    (
                        f"useBoxScore/getGameStats/{self.config.season_id}"
                        f"/games/{game.game_id}"
                    ),
                    {},
                )
                enriched.append(self.apply_box_score(game, payload))
            except Exception as exc:
                LOGGER.warning(
                    "Camp Dovid score unavailable for game %s: %s",
                    game.game_id,
                    exc,
                )
                enriched.append(game)
        return enriched

    @staticmethod
    def _timezone_offset(now: datetime) -> int:
        offset = now.utcoffset()
        return int(offset.total_seconds() // 60) if offset is not None else 0

    @classmethod
    def parse_standings(
        cls, payload: Any, division_id: int
    ) -> list[CampStanding]:
        divisions = payload if isinstance(payload, list) else payload.get("data", [])
        if not isinstance(divisions, list):
            raise ValueError("GameSheet standings response is not a division list")

        selected: dict[str, Any] | None = None
        for division in divisions:
            if not isinstance(division, dict):
                continue
            if str(division.get("id")) == str(division_id):
                selected = division
                break
        if selected is None and len(divisions) == 1 and isinstance(divisions[0], dict):
            selected = divisions[0]
        if selected is None:
            raise ValueError(f"Division {division_id} is missing from standings")

        table = selected.get("tableData", {})
        if not isinstance(table, dict):
            raise ValueError("GameSheet standings tableData is missing")
        team_titles = cls._array(table, "teamTitles")
        ranks = cls._array(table, "ranks")

        standings: list[CampStanding] = []
        for index, raw_team in enumerate(team_titles):
            if isinstance(raw_team, dict):
                team = str(raw_team.get("title") or raw_team.get("name") or "")
            else:
                team = str(raw_team or "")
            team = team.strip()
            if not team:
                continue
            standings.append(
                CampStanding(
                    rank=cls._integer_at(ranks, index, index + 1),
                    team=team,
                    games_played=cls._integer_at(cls._array(table, "gp"), index),
                    wins=cls._integer_at(cls._array(table, "w"), index),
                    losses=cls._integer_at(cls._array(table, "l"), index),
                    ties=cls._integer_at(cls._array(table, "t"), index),
                    points=cls._integer_at(cls._array(table, "pts"), index),
                )
            )
        return sorted(standings, key=lambda item: (item.rank, item.team.casefold()))

    @classmethod
    def parse_schedule(cls, payload: Any, zone: ZoneInfo) -> list[CampGame]:
        games_by_id: dict[str, CampGame] = {}
        for raw in cls._schedule_games(payload):
            game_id = str(raw.get("id") or raw.get("gameId") or "").strip()
            if not game_id:
                continue
            home = raw.get("homeTeam") or raw.get("home") or {}
            away = raw.get("visitorTeam") or raw.get("awayTeam") or raw.get("visitor") or {}
            home_name = cls._team_name(home)
            away_name = cls._team_name(away)
            if not home_name or not away_name:
                continue
            try:
                start = cls._start_time(raw, zone)
            except ValueError as exc:
                LOGGER.warning("Skipping Camp Dovid game %s: %s", game_id, exc)
                continue
            games_by_id[game_id] = CampGame(
                game_id=game_id,
                start_time_utc=start,
                status=cls._status(raw.get("status")),
                away_team=away_name,
                home_team=home_name,
                away_score=cls._first_score(
                    away.get("score"),
                    away.get("finalScore"),
                    raw.get("visitorScore"),
                    raw.get("awayScore"),
                ),
                home_score=cls._first_score(
                    home.get("score"),
                    home.get("finalScore"),
                    raw.get("homeScore"),
                ),
                location=str(raw.get("location") or "").strip(),
            )
        return sorted(games_by_id.values(), key=lambda item: item.start_time_utc)

    @classmethod
    def apply_box_score(cls, game: CampGame, payload: Any) -> CampGame:
        if not isinstance(payload, dict):
            return game
        home = payload.get("home") or payload.get("homeTeam") or {}
        away = payload.get("visitor") or payload.get("visitorTeam") or {}
        return replace(
            game,
            away_score=cls._first_score(
                away.get("finalScore"), away.get("score"), game.away_score
            ),
            home_score=cls._first_score(
                home.get("finalScore"), home.get("score"), game.home_score
            ),
        )

    @staticmethod
    def _array(table: dict[str, Any], name: str) -> list[Any]:
        value = table.get(name, table.get(f"{name}[]", []))
        return value if isinstance(value, list) else []

    @staticmethod
    def _integer_at(values: list[Any], index: int, default: int = 0) -> int:
        try:
            return int(values[index])
        except (IndexError, TypeError, ValueError):
            return default

    @classmethod
    def _schedule_games(cls, payload: Any) -> Iterable[dict[str, Any]]:
        if isinstance(payload, list):
            groups: Iterable[Any] = payload
        elif isinstance(payload, dict):
            if isinstance(payload.get("games"), list):
                groups = [payload]
            else:
                groups = payload.values()
        else:
            raise ValueError("GameSheet schedule response has an unknown shape")

        for group in groups:
            items = group if isinstance(group, list) else [group]
            for item in items:
                if not isinstance(item, dict):
                    continue
                games = item.get("games")
                if isinstance(games, list):
                    for game in games:
                        if isinstance(game, dict):
                            yield game
                elif item.get("id") or item.get("gameId"):
                    yield item

    @staticmethod
    def _team_name(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("name") or value.get("title") or "").strip()
        return str(value or "").strip()

    @classmethod
    def _start_time(cls, raw: dict[str, Any], zone: ZoneInfo) -> datetime:
        iso_value = raw.get("scheduleStartTime") or raw.get("startTime")
        if iso_value:
            parsed = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=zone)
            return parsed.astimezone(timezone.utc)

        date_text = str(raw.get("date") or "").strip()
        time_text = str(raw.get("time") or "").strip()
        combined = " ".join(part for part in (date_text, time_text) if part)
        for pattern in (
            "%b %d, %Y %I:%M %p",
            "%a, %b %d, %Y %I:%M %p",
            "%m/%d/%Y %I:%M %p",
            "%Y-%m-%d %I:%M %p",
        ):
            try:
                return datetime.strptime(combined, pattern).replace(
                    tzinfo=zone
                ).astimezone(timezone.utc)
            except ValueError:
                continue
        raise ValueError(f"unrecognized start time {combined!r}")

    @staticmethod
    def _status(value: Any) -> str:
        normalized = str(value or "scheduled").strip().lower().replace(" ", "_")
        if normalized in {"final", "completed", "complete"}:
            return "final"
        if normalized in {"in_progress", "live", "inprogress"}:
            return "in_progress"
        return "scheduled"

    @staticmethod
    def _first_score(*values: Any) -> int | None:
        for value in values:
            if value in (None, ""):
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None


def team_color(team_name: str) -> tuple[int, int, int]:
    """Return the same bright LED-safe color for a team on every card."""
    digest = hashlib.sha256(team_name.strip().casefold().encode("utf-8")).digest()
    return TEAM_COLORS[int.from_bytes(digest[:2], "big") % len(TEAM_COLORS)]


def build_camp_dovid_cards(
    snapshot: CampSnapshot,
    now: datetime,
    config: CampDovidConfig,
    zone: ZoneInfo,
) -> list[DisplayCard]:
    """Build paginated standings plus one readable card per game/result."""
    if not config.enabled:
        return []
    local_date = now.astimezone(zone).date()
    if config.active_through is not None and local_date > config.active_through:
        return []
    if not snapshot.has_data:
        if snapshot.errors:
            return [DisplayCard(type="message", title="DOVID DATA ERROR")]
        return []

    cards = [DisplayCard(type="header", title="CAMP DOVID")]
    division_label = config.division_name.upper()
    cards.extend(_standings_cards(snapshot.standings, division_label=division_label))

    now_utc = now.astimezone(timezone.utc)
    upcoming = sorted(
        (
            game
            for game in snapshot.games
            if game.status in {"scheduled", "in_progress"}
            and (game.status == "in_progress" or game.start_time_utc >= now_utc)
        ),
        key=lambda item: item.start_time_utc,
    )[: config.upcoming_games]
    for index, game in enumerate(upcoming, start=1):
        cards.append(
            _upcoming_card(game, index, len(upcoming), zone, division_label)
        )

    results = sorted(
        (game for game in snapshot.games if game.status == "final"),
        key=lambda item: item.start_time_utc,
        reverse=True,
    )[: config.recent_results]
    for index, game in enumerate(results, start=1):
        cards.append(_result_card(game, index, len(results), zone, division_label))
    return cards


def _standings_cards(
    standings: tuple[CampStanding, ...],
    division_label: str = "JR",
    rows_per_card: int = 4,
) -> list[DisplayCard]:
    pages = [
        standings[index : index + rows_per_card]
        for index in range(0, len(standings), rows_per_card)
    ]
    cards: list[DisplayCard] = []
    for page_number, page in enumerate(pages, start=1):
        title = f"{division_label} STANDINGS"
        if len(pages) > 1:
            title = f"{division_label} TABLE {page_number}/{len(pages)}"
        lines = []
        for standing in page:
            record = f"{standing.wins}-{standing.losses}"
            if standing.ties:
                record += f"-{standing.ties}"
            lines.append(
                RichTextLine(
                    (
                        RichTextSpan(f"{standing.rank} "),
                        RichTextSpan(
                            standing.team,
                            team_color(standing.team),
                            shrink=True,
                        ),
                        RichTextSpan(f" {record} {standing.points}P"),
                    )
                )
            )
        cards.append(
            DisplayCard(
                type="rich_text",
                rich_text=RichTextCard(
                    card_id=f"camp-standings-{page_number}",
                    title=title,
                    lines=tuple(lines),
                ),
            )
        )
    return cards


def _upcoming_card(
    game: CampGame,
    index: int,
    total: int,
    zone: ZoneInfo,
    division_label: str = "JR",
) -> DisplayCard:
    local = game.start_time_utc.astimezone(zone)
    title = (
        f"{division_label} NEXT"
        if total == 1
        else f"{division_label} NEXT {index}/{total}"
    )
    status = "IN PROGRESS" if game.status == "in_progress" else _compact_time(local)
    return DisplayCard(
        type="rich_text",
        rich_text=RichTextCard(
            card_id=f"camp-upcoming-{game.game_id}",
            title=title,
            lines=(
                RichTextLine((RichTextSpan(status, CAMP_BLUE),)),
                _team_line(game.away_team),
                RichTextLine((RichTextSpan("AT"),)),
                _team_line(game.home_team),
            ),
        ),
    )


def _result_card(
    game: CampGame,
    index: int,
    total: int,
    zone: ZoneInfo,
    division_label: str = "JR",
) -> DisplayCard:
    local = game.start_time_utc.astimezone(zone)
    title = (
        f"{division_label} FINAL"
        if total == 1
        else f"{division_label} FINAL {index}/{total}"
    )
    away_score = "-" if game.away_score is None else str(game.away_score)
    home_score = "-" if game.home_score is None else str(game.home_score)
    return DisplayCard(
        type="rich_text",
        rich_text=RichTextCard(
            card_id=f"camp-result-{game.game_id}",
            title=title,
            lines=(
                RichTextLine(
                    (RichTextSpan(f"{local:%a} {local.month}/{local.day}", CAMP_BLUE),)
                ),
                _scored_team_line(game.away_team, away_score),
                _scored_team_line(game.home_team, home_score),
                RichTextLine((RichTextSpan("FINAL"),)),
            ),
        ),
    )


def _team_line(team: str) -> RichTextLine:
    return RichTextLine(
        (RichTextSpan(team, team_color(team), shrink=True),)
    )


def _scored_team_line(team: str, score: str) -> RichTextLine:
    return RichTextLine(
        (
            RichTextSpan(team, team_color(team), shrink=True),
            RichTextSpan(f" {score}"),
        )
    )


def _compact_time(value: datetime) -> str:
    clock = value.strftime("%I:%M%p").lstrip("0").replace("AM", "A").replace("PM", "P")
    return f"{value:%a} {value.month}/{value.day} {clock}"
