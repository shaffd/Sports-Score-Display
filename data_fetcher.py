"""Fetch and normalize NHL, NFL, and MLB game data."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import requests

from config import FantasyPlayerConfig
from models import FantasyPlayer, FetchBatch, Game, Team


LOGGER = logging.getLogger(__name__)


class DataFetcher:
    """Small API client that converts every league into the shared Game model."""

    NHL_BASE = "https://api-web.nhle.com/v1"
    NFL_SCOREBOARD = (
        "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    )
    NFL_SUMMARY = (
        "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/summary"
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

    # ---------------------------------------------------------- Fantasy NFL

    @staticmethod
    def fantasy_templates(
        players: Iterable[FantasyPlayerConfig],
    ) -> list[FantasyPlayer]:
        """Create stable, no-stat placeholders from the configured roster."""
        return [
            FantasyPlayer(
                player_id=player.player_id,
                first_name=player.first_name,
                last_name=player.last_name,
                position=player.position,
                team=player.team,
            )
            for player in players
        ]

    @staticmethod
    def _normalized_player_name(value: str) -> str:
        return "".join(character for character in value.lower() if character.isalnum())

    @staticmethod
    def _stat_int(value: Any) -> int | None:
        if value in (None, "", "-"):
            return None
        match = re.search(r"-?\d+", str(value))
        return int(match.group()) if match else None

    @classmethod
    def _split_stat(cls, value: Any) -> tuple[int | None, int | None]:
        pieces = str(value).split("/", maxsplit=1)
        if len(pieces) != 2:
            return (None, None)
        return (cls._stat_int(pieces[0]), cls._stat_int(pieces[1]))

    @staticmethod
    def _fantasy_game_status(event: dict[str, Any]) -> str:
        competition = (event.get("competitions") or [{}])[0]
        status = competition.get("status") or event.get("status") or {}
        status_type = status.get("type") or {}
        if status_type.get("completed") or str(status_type.get("state", "")).lower() == "post":
            return "FINAL"
        if str(status_type.get("state", "")).lower() == "in":
            period = status.get("period")
            clock = status.get("displayClock")
            return " ".join(
                part for part in (f"Q{period}" if period else "LIVE", clock) if part
            )
        return "SCHEDULED"

    @classmethod
    def _apply_fantasy_stat(
        cls,
        updates: dict[str, int],
        raw_name: Any,
        raw_value: Any,
    ) -> None:
        name = "".join(character for character in str(raw_name).lower() if character.isalnum())
        if name in {"completionspassingattempts", "catt", "passingcatt"}:
            completions, attempts = cls._split_stat(raw_value)
            if completions is not None:
                updates["completions"] = completions
            if attempts is not None:
                updates["pass_attempts"] = attempts
            return
        if name in {"fieldgoalsmadefieldgoalsattempted", "fg", "kickingfg"}:
            made, attempts = cls._split_stat(raw_value)
            if made is not None:
                updates["field_goals_made"] = made
            if attempts is not None:
                updates["field_goals_attempted"] = attempts
            return
        if name in {"extrapointsmadeextrapointsattempted", "xp", "kickingxp"}:
            made, attempts = cls._split_stat(raw_value)
            if made is not None:
                updates["extra_points_made"] = made
            if attempts is not None:
                updates["extra_points_attempted"] = attempts
            return

        fields = {
            "passingyards": "passing_yards",
            "passingyds": "passing_yards",
            "passingtouchdowns": "passing_touchdowns",
            "passingtd": "passing_touchdowns",
            "interceptions": "interceptions",
            "passingint": "interceptions",
            "rushingattempts": "rush_attempts",
            "rushingcar": "rush_attempts",
            "rushingyards": "rushing_yards",
            "rushingyds": "rushing_yards",
            "rushingtouchdowns": "rushing_touchdowns",
            "rushingtd": "rushing_touchdowns",
            "receptions": "receptions",
            "receivingrec": "receptions",
            "receivingtargets": "targets",
            "receivingtgts": "targets",
            "targets": "targets",
            "receivingyards": "receiving_yards",
            "receivingyds": "receiving_yards",
            "receivingtouchdowns": "receiving_touchdowns",
            "receivingtd": "receiving_touchdowns",
            "fumbleslost": "fumbles_lost",
            "kickingpoints": "kicking_points",
            "kickingpts": "kicking_points",
            "totalkickingpoints": "kicking_points",
        }
        field = fields.get(name)
        value = cls._stat_int(raw_value)
        if field is not None and value is not None:
            updates[field] = value

    @classmethod
    def parse_nfl_fantasy_summary(
        cls,
        payload: dict[str, Any],
        players: Iterable[FantasyPlayer],
        game_status: str,
    ) -> dict[str, FantasyPlayer]:
        """Extract configured player lines from ESPN's per-event box score."""
        templates = {
            cls._normalized_player_name(
                f"{player.first_name} {player.last_name}"
            ): player
            for player in players
        }
        resolved: dict[str, FantasyPlayer] = {}
        for team_box in (payload.get("boxscore") or {}).get("players", []):
            for category in team_box.get("statistics", []):
                category_name = str(category.get("name") or "")
                names = category.get("names") or []
                labels = category.get("labels") or []
                for athlete_stats in category.get("athletes", []):
                    athlete = athlete_stats.get("athlete") or {}
                    player = templates.get(
                        cls._normalized_player_name(
                            str(athlete.get("displayName") or athlete.get("fullName") or "")
                        )
                    )
                    if player is None:
                        continue
                    updates: dict[str, int] = {}
                    for index, value in enumerate(athlete_stats.get("stats") or []):
                        if index < len(names):
                            cls._apply_fantasy_stat(updates, names[index], value)
                        if index < len(labels):
                            cls._apply_fantasy_stat(
                                updates, f"{category_name}.{labels[index]}", value
                            )
                    current = resolved.get(player.player_id, player)
                    resolved[player.player_id] = replace(
                        current, game_status=game_status, **updates
                    )
        return resolved

    def fetch_nfl_fantasy_players(
        self,
        start_date: date,
        end_date: date,
        players: Iterable[FantasyPlayerConfig],
    ) -> list[FantasyPlayer]:
        """Resolve player box-score stats over the active fantasy display window."""
        result = self.fantasy_templates(players)
        by_id = {player.player_id: player for player in result}
        events: dict[str, dict[str, Any]] = {}
        for game_date in self._dates(start_date, end_date):
            payload = self._get_json(
                self.NFL_SCOREBOARD,
                params={"dates": game_date.strftime("%Y%m%d"), "limit": 100},
            )
            for event in payload.get("events", []):
                if event.get("id"):
                    events[str(event["id"])] = event

        for event in events.values():
            status = self._fantasy_game_status(event)
            competition = (event.get("competitions") or [{}])[0]
            teams = {
                str(competitor.get("team", {}).get("abbreviation", "")).upper()
                for competitor in competition.get("competitors", [])
            }
            for player_id, player in by_id.items():
                if player.team.upper() in teams:
                    by_id[player_id] = replace(player, game_status=status)
            if status == "SCHEDULED":
                continue
            try:
                summary = self._get_json(self.NFL_SUMMARY, params={"event": event["id"]})
                by_id.update(
                    self.parse_nfl_fantasy_summary(summary, by_id.values(), status)
                )
            except Exception as exc:
                LOGGER.warning("Fantasy stats unavailable for NFL event %s: %s", event["id"], exc)

        return [by_id[player.player_id] for player in result]

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
        )

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
        )

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
        )
        cls._apply_mlb_linescore(game, linescore)
        return game

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
