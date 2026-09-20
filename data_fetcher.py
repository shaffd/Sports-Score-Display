"""Fetch and normalize NHL, NFL, and MLB game data."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import requests

from models import FetchBatch, Game, Team


LOGGER = logging.getLogger(__name__)


class DataFetcher:
    """Small API client that converts every league into the shared Game model."""

    NHL_BASE = "https://api-web.nhle.com/v1"
    NFL_SCOREBOARD = (
        "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    )
    MLB_BASE = "https://statsapi.mlb.com/api/v1"
    MLB_LIVE_BASE = "https://statsapi.mlb.com/api/v1.1"

    def __init__(
        self,
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "Sports-Score-Display/1.0",
            }
        )

    def fetch_games(
        self,
        start_date: date,
        end_date: date,
        sports: Iterable[str] = ("NHL", "NFL", "MLB"),
    ) -> FetchBatch:
        """Fetch each selected league without allowing one failure to hide the others."""
        batch = FetchBatch()
        fetchers = {
            "NHL": self.get_nhl_games,
            "NFL": self.get_nfl_games,
            "MLB": self.get_mlb_games,
        }

        for sport in sports:
            try:
                batch.games.extend(fetchers[sport](start_date, end_date))
            except Exception as exc:  # API shape/network failures are isolated per league.
                LOGGER.warning("%s refresh failed: %s", sport, exc)
                batch.errors[sport] = str(exc)

        return batch

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict:
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _dates(start_date: date, end_date: date) -> list[date]:
        if end_date < start_date:
            raise ValueError("end_date must not be before start_date")
        return [
            start_date + timedelta(days=offset)
            for offset in range((end_date - start_date).days + 1)
        ]

    @staticmethod
    def _parse_utc(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _score(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------ NHL

    def get_nhl_games(self, start_date: date, end_date: date) -> list[Game]:
        games_by_id: dict[str, Game] = {}
        for game_date in self._dates(start_date, end_date):
            payload = self._get_json(f"{self.NHL_BASE}/score/{game_date.isoformat()}")
            for raw_game in payload.get("games", []):
                game = self.parse_nhl_game(raw_game)
                games_by_id[game.game_id] = game
        return list(games_by_id.values())

    @classmethod
    def parse_nhl_game(cls, raw_game: dict[str, Any]) -> Game:
        state = str(raw_game.get("gameState", "")).upper()
        if state in {"FINAL", "OFF"}:
            status = "final"
        elif state in {"LIVE", "CRIT"}:
            status = "live"
        else:
            status = "scheduled"

        away_raw = raw_game.get("awayTeam", {})
        home_raw = raw_game.get("homeTeam", {})
        period = raw_game.get("periodDescriptor", {}).get("number")
        clock = raw_game.get("clock", {}).get("timeRemaining")

        return Game(
            sport="NHL",
            game_id=str(raw_game.get("id", "")),
            start_time_utc=cls._parse_utc(raw_game["startTimeUTC"]),
            status=status,
            away=cls._nhl_team(away_raw),
            home=cls._nhl_team(home_raw),
            away_score=cls._score(away_raw.get("score")),
            home_score=cls._score(home_raw.get("score")),
            period=int(period) if period is not None else None,
            clock=str(clock) if clock else None,
            game_type_label=cls._nhl_game_type_label(raw_game),
        )

    @staticmethod
    def _nhl_game_type_label(raw_game: dict[str, Any]) -> str | None:
        """Return NHL's own compact playoff series abbreviation when present."""
        game_type = str(raw_game.get("gameType", ""))
        if game_type == "1":
            return "PRE"
        if game_type != "3":
            return None
        series = raw_game.get("seriesStatus") or {}
        return str(series.get("seriesAbbrev") or "PO").upper()

    @staticmethod
    def _nhl_team(raw_team: dict[str, Any]) -> Team:
        name_obj = raw_team.get("name") or raw_team.get("commonName") or {}
        if isinstance(name_obj, dict):
            name = name_obj.get("default", "")
        else:
            name = str(name_obj)
        abbreviation = str(raw_team.get("abbrev", "")).upper()
        return Team(
            name=name or abbreviation,
            abbreviation=abbreviation,
            logo_url=raw_team.get("logo"),
        )

    # ------------------------------------------------------------------ NFL

    def get_nfl_games(self, start_date: date, end_date: date) -> list[Game]:
        games_by_id: dict[str, Game] = {}
        for game_date in self._dates(start_date, end_date):
            payload = self._get_json(
                self.NFL_SCOREBOARD,
                params={"dates": game_date.strftime("%Y%m%d"), "limit": 100},
            )
            for event in payload.get("events", []):
                game = self.parse_nfl_event(event)
                if game is not None:
                    games_by_id[game.game_id] = game
        return list(games_by_id.values())

    @classmethod
    def parse_nfl_event(cls, event: dict[str, Any]) -> Game | None:
        competitions = event.get("competitions", [])
        if not competitions:
            return None
        competition = competitions[0]

        home_raw: dict[str, Any] | None = None
        away_raw: dict[str, Any] | None = None
        for competitor in competition.get("competitors", []):
            if competitor.get("homeAway") == "home":
                home_raw = competitor
            elif competitor.get("homeAway") == "away":
                away_raw = competitor
        if home_raw is None or away_raw is None:
            return None

        status_raw = competition.get("status", {})
        status_type = status_raw.get("type", {})
        state = str(status_type.get("state", "")).lower()
        description = str(status_type.get("description", "")).lower()
        if status_type.get("completed") or state == "post" or "final" in description:
            status = "final"
        elif state == "in" or description in {"in progress", "halftime"}:
            status = "live"
        else:
            status = "scheduled"

        away = cls._nfl_team(away_raw.get("team", {}))
        home = cls._nfl_team(home_raw.get("team", {}))
        situation = competition.get("situation") or {}
        possession_id = str(situation.get("possession", ""))
        away_id = str(away_raw.get("team", {}).get("id", ""))
        home_id = str(home_raw.get("team", {}).get("id", ""))
        possession = None
        if possession_id and possession_id == away_id:
            possession = "away"
        elif possession_id and possession_id == home_id:
            possession = "home"

        period = status_raw.get("period")
        return Game(
            sport="NFL",
            game_id=str(event.get("id", "")),
            start_time_utc=cls._parse_utc(event["date"]),
            status=status,
            away=away,
            home=home,
            away_score=cls._score(away_raw.get("score")),
            home_score=cls._score(home_raw.get("score")),
            period=int(period) if period not in (None, "") else None,
            clock=status_raw.get("displayClock") or None,
            possession=possession,
            down_distance=(
                situation.get("shortDownDistanceText")
                or situation.get("downDistanceText")
                or None
            ),
            field_position=situation.get("possessionText") or None,
            game_type_label=cls._nfl_game_type_label(event, competition),
        )

    @staticmethod
    def _nfl_game_type_label(
        event: dict[str, Any], competition: dict[str, Any]
    ) -> str | None:
        """Map ESPN's season type and playoff headline to a short card label."""
        season_type = str((event.get("season") or {}).get("type", ""))
        if season_type == "1":
            return "PRE"
        if season_type != "3":
            return None

        notes = [
            str(note.get("headline") or "")
            for note in (
                *(event.get("notes") or []),
                *(competition.get("notes") or []),
            )
        ]
        headline = " ".join(notes).upper()
        conference = next(
            (name for name in ("AFC", "NFC") if name in headline), ""
        )
        if "WILD CARD" in headline:
            return f"{conference} WC".strip()
        if "DIVISIONAL" in headline:
            return f"{conference} DIV".strip()
        if "CHAMPIONSHIP" in headline:
            return f"{conference} CH".strip()
        if "SUPER BOWL" in headline:
            return "SB"
        if "PRO BOWL" in headline:
            return "PB"
        return "PO"

    @staticmethod
    def _nfl_team(raw_team: dict[str, Any]) -> Team:
        abbreviation = str(raw_team.get("abbreviation", "")).upper()
        logo = raw_team.get("logo")
        if not logo:
            logos = raw_team.get("logos", [])
            logo = logos[0].get("href") if logos else None
        return Team(
            name=str(raw_team.get("displayName") or raw_team.get("name") or abbreviation),
            abbreviation=abbreviation,
            logo_url=logo,
        )

    # ------------------------------------------------------------------ MLB

    def get_mlb_games(self, start_date: date, end_date: date) -> list[Game]:
        payload = self._get_json(
            f"{self.MLB_BASE}/schedule",
            params={
                "sportId": 1,
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "hydrate": "team,linescore",
            },
        )

        games: list[Game] = []
        for day in payload.get("dates", []):
            for raw_game in day.get("games", []):
                game = self.parse_mlb_game(raw_game)
                if game.status == "live":
                    try:
                        live = self._get_json(
                            f"{self.MLB_LIVE_BASE}/game/{game.game_id}/feed/live"
                        )
                        self.apply_mlb_live_details(game, live)
                    except Exception as exc:
                        LOGGER.warning(
                            "MLB live details unavailable for game %s: %s",
                            game.game_id,
                            exc,
                        )
                games.append(game)
        return games

    @classmethod
    def parse_mlb_game(cls, raw_game: dict[str, Any]) -> Game:
        state = str(
            raw_game.get("status", {}).get("abstractGameState", "Preview")
        ).lower()
        if state == "final":
            status = "final"
        elif state == "live":
            status = "live"
        else:
            status = "scheduled"

        away_raw = raw_game.get("teams", {}).get("away", {})
        home_raw = raw_game.get("teams", {}).get("home", {})
        linescore = raw_game.get("linescore", {})
        inning = linescore.get("currentInning")
        half = cls._inning_half(linescore.get("inningState") or linescore.get("inningHalf"))

        game = Game(
            sport="MLB",
            game_id=str(raw_game.get("gamePk", "")),
            start_time_utc=cls._parse_utc(raw_game["gameDate"]),
            status=status,
            away=cls._mlb_team(away_raw.get("team", {})),
            home=cls._mlb_team(home_raw.get("team", {})),
            away_score=cls._score(away_raw.get("score")),
            home_score=cls._score(home_raw.get("score")),
            inning=int(inning) if inning is not None else None,
            inning_half=half,
            game_type_label=cls._mlb_game_type_label(raw_game),
        )
        cls._apply_mlb_linescore(game, linescore)
        return game

    @staticmethod
    def _mlb_game_type_label(raw_game: dict[str, Any]) -> str | None:
        """Use MLB's series description to distinguish its playoff rounds."""
        game_type = str(raw_game.get("gameType", "")).upper()
        if game_type in {"S", "E"}:
            return "PRE"
        if game_type not in {"F", "D", "L", "W"}:
            return None

        description = " ".join(
            str(raw_game.get(key) or "")
            for key in ("description", "seriesDescription")
        ).upper()
        if (
            description.startswith("AL")
            or " AL " in description
            or "AMERICAN" in description
        ):
            league = "AL"
        elif (
            description.startswith("NL")
            or " NL " in description
            or "NATIONAL" in description
        ):
            league = "NL"
        else:
            league = ""
        suffix = {"F": "WC", "D": "DS", "L": "CS"}.get(game_type)
        if suffix:
            return f"{league}{suffix}" if league else suffix
        return "WS"

    @staticmethod
    def _mlb_team(raw_team: dict[str, Any]) -> Team:
        abbreviation = str(
            raw_team.get("abbreviation")
            or raw_team.get("fileCode")
            or raw_team.get("teamCode")
            or ""
        ).upper()
        return Team(
            name=str(raw_team.get("name") or raw_team.get("teamName") or abbreviation),
            abbreviation=abbreviation,
        )

    @staticmethod
    def _inning_half(value: Any) -> str | None:
        normalized = str(value or "").lower()
        if normalized.startswith("top"):
            return "top"
        if normalized.startswith("bottom") or normalized.startswith("bot"):
            return "bottom"
        return None

    @classmethod
    def _apply_mlb_linescore(cls, game: Game, linescore: dict[str, Any]) -> None:
        inning = linescore.get("currentInning")
        if inning is not None:
            game.inning = int(inning)
        game.inning_half = cls._inning_half(
            linescore.get("inningState") or linescore.get("inningHalf")
        )

        offense = linescore.get("offense", {})
        game.bases = {
            "first": bool(offense.get("first")),
            "second": bool(offense.get("second")),
            "third": bool(offense.get("third")),
        }
        game.balls = cls._score(linescore.get("balls"))
        game.strikes = cls._score(linescore.get("strikes"))
        game.outs = cls._score(linescore.get("outs"))

    @classmethod
    def apply_mlb_live_details(cls, game: Game, payload: dict[str, Any]) -> None:
        """Add inning, bases, pitcher, and batter from MLB's v1.1 live feed."""
        game_data = payload.get("gameData", {})
        live_data = payload.get("liveData", {})
        linescore = live_data.get("linescore", {})
        cls._apply_mlb_linescore(game, linescore)

        teams = linescore.get("teams", {})
        if teams:
            game.away_score = cls._score(teams.get("away", {}).get("runs"))
            game.home_score = cls._score(teams.get("home", {}).get("runs"))

        current_play = live_data.get("plays", {}).get("currentPlay", {})
        matchup = current_play.get("matchup", {})
        players = game_data.get("players", {})
        offense = linescore.get("offense", {})
        defense = linescore.get("defense", {})

        batter = matchup.get("batter") or offense.get("batter") or {}
        pitcher = matchup.get("pitcher") or defense.get("pitcher") or {}
        game.batter = cls._player_last_name(batter, players)
        game.pitcher = cls._player_last_name(pitcher, players)

    @staticmethod
    def _player_last_name(
        player_ref: dict[str, Any], players: dict[str, Any]
    ) -> str | None:
        player_id = player_ref.get("id")
        player = players.get(f"ID{player_id}", {}) if player_id else {}
        last_name = player.get("lastName")
        if last_name:
            return str(last_name)

        full_name = str(player_ref.get("fullName", "")).strip()
        if not full_name:
            return None
        parts = full_name.split()
        suffixes = {"JR.", "SR.", "II", "III", "IV"}
        if len(parts) > 1 and parts[-1].upper() in suffixes:
            return parts[-2]
        return parts[-1]
