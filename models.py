"""Shared data structures used by the API, formatting, and rendering layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


GameStatus = Literal["scheduled", "live", "final"]
CardType = Literal["header", "game", "message", "fantasy_header", "fantasy"]


@dataclass(slots=True)
class Team:
    """A team as it should be identified throughout the application."""

    name: str
    abbreviation: str
    logo_url: str | None = None


@dataclass(slots=True)
class Game:
    """Normalized game data shared by MLB, NHL, and NFL."""

    sport: str
    game_id: str
    start_time_utc: datetime
    status: GameStatus
    away: Team
    home: Team
    away_score: int | None = None
    home_score: int | None = None

    # NFL/NHL live fields
    period: int | None = None
    clock: str | None = None
    possession: Literal["away", "home"] | None = None
    down_distance: str | None = None
    field_position: str | None = None

    # MLB live fields
    inning: int | None = None
    inning_half: Literal["top", "bottom"] | None = None
    bases: dict[str, bool] = field(
        default_factory=lambda: {"first": False, "second": False, "third": False}
    )
    pitcher: str | None = None
    batter: str | None = None
    balls: int | None = None
    strikes: int | None = None
    outs: int | None = None

    @property
    def marker(self) -> Literal["away", "home"] | None:
        """Return the team marker used for possession or the team at bat."""
        if self.sport == "MLB" and self.status == "live":
            if self.inning_half == "top":
                return "away"
            if self.inning_half == "bottom":
                return "home"
        return self.possession


@dataclass(slots=True)
class FantasyPlayer:
    """A compact, normalized line of in-game NFL fantasy statistics.

    The optional fields deliberately preserve a distinction between no recorded
    value and a statistic that does not apply to a player's position.
    """

    player_id: str
    first_name: str
    last_name: str
    position: str
    team: str
    game_status: str = "SUNDAY 1:00"
    completions: int | None = None
    pass_attempts: int | None = None
    passing_yards: int | None = None
    passing_touchdowns: int | None = None
    interceptions: int | None = None
    rush_attempts: int | None = None
    rushing_yards: int | None = None
    rushing_touchdowns: int | None = None
    receptions: int | None = None
    targets: int | None = None
    receiving_yards: int | None = None
    receiving_touchdowns: int | None = None
    fumbles_lost: int | None = None
    field_goals_made: int | None = None
    field_goals_attempted: int | None = None
    extra_points_made: int | None = None
    extra_points_attempted: int | None = None
    kicking_points: int | None = None

    @property
    def display_name(self) -> str:
        """Use a first initial plus last name, as required by the panel layout."""
        initial = self.first_name.strip()[:1].upper()
        last_name = self.last_name.strip().upper()
        return f"{initial}. {last_name}".strip()


@dataclass(slots=True)
class DisplayCard:
    """One item in the rotating display."""

    type: CardType
    title: str = ""
    game: Game | None = None
    fantasy_player: FantasyPlayer | None = None

    @property
    def key(self) -> str:
        if self.game:
            return f"{self.game.sport}:{self.game.game_id}"
        if self.fantasy_player:
            return f"fantasy:{self.fantasy_player.player_id}"
        return f"{self.type}:{self.title}"


@dataclass(slots=True)
class FetchBatch:
    """Games plus per-league errors from one refresh attempt."""

    games: list[Game] = field(default_factory=list)
    fantasy_players: list[FantasyPlayer] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
