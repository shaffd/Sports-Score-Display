"""Shared data structures used by the API, formatting, and rendering layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


GameStatus = Literal["scheduled", "live", "final"]
CardType = Literal["header", "game", "message", "rich_text"]
TextAlignment = Literal["left", "center", "right"]
TextColor = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class RichTextSpan:
    """A colored portion of one compact list-card line."""

    text: str
    color: TextColor = (255, 255, 255)
    shrink: bool = False


@dataclass(frozen=True, slots=True)
class RichTextLine:
    """One line on a list-style card, composed of independently colored spans."""

    spans: tuple[RichTextSpan, ...]
    alignment: TextAlignment = "center"
    # Optional fixed column starts, expressed in pixels on the reference 64-wide
    # panel. Each span occupies the cell from its start to the next start.
    column_starts: tuple[int, ...] = ()
    column_alignments: tuple[TextAlignment, ...] = ()


@dataclass(frozen=True, slots=True)
class RichTextCard:
    """Pixel-display content for standings, schedules, and other compact lists."""

    card_id: str
    title: str
    lines: tuple[RichTextLine, ...]
    title_color: TextColor = (102, 153, 204)


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
class DisplayCard:
    """One item in the rotating display."""

    type: CardType
    title: str = ""
    game: Game | None = None
    rich_text: RichTextCard | None = None

    @property
    def key(self) -> str:
        if self.game:
            return f"{self.game.sport}:{self.game.game_id}"
        if self.rich_text:
            return f"rich_text:{self.rich_text.card_id}"
        return f"{self.type}:{self.title}"


@dataclass(slots=True)
class FetchBatch:
    """Games plus per-league errors from one refresh attempt."""

    games: list[Game] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
