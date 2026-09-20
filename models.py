"""Shared data structures used by the API, formatting, and rendering layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


GameStatus = Literal["scheduled", "live", "final"]
CardType = Literal["header", "game", "message"]


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
    # Blank during the regular season; otherwise a compact API-derived label
    # such as PRE, ALDS, R2, or AFC WC.
    game_type_label: str | None = None

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
class DisplayCard:
    """One item in the rotating display."""

    type: CardType
    title: str = ""
    game: Game | None = None

    @property
    def key(self) -> str:
        if self.game:
            return f"{self.game.sport}:{self.game.game_id}"
        return f"{self.type}:{self.title}"


@dataclass(slots=True)
class FetchBatch:
    """Games plus per-league errors from one refresh attempt."""

    games: list[Game] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
