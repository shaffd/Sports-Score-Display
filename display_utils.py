"""Select games for the requested time window and build display cards."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import AppConfig
from models import DisplayCard, Game


def format_start_time(start_time_utc: datetime, zone: ZoneInfo) -> str:
    """Format a UTC start time as Eastern/local time plus MM/DD."""
    local = start_time_utc.astimezone(zone)
    clock = local.strftime("%I:%M %p").lstrip("0")
    return f"{clock} {local:%m/%d}"


def format_status(game: Game, zone: ZoneInfo) -> str:
    """Create the common top line for every game card."""
    local_date = game.start_time_utc.astimezone(zone).strftime("%m/%d")
    if game.status == "final":
        return f"FINAL {local_date}"
    if game.status == "live":
        return "IN PROGRESS"
    if game.scheduled_label:
        return game.scheduled_label
    return format_start_time(game.start_time_utc, zone)


def card_display_seconds(card: DisplayCard, config: AppConfig) -> float:
    """Return the dwell time for a card, extending live favorite-team games."""
    game = card.game
    if game is None or game.status != "live":
        return config.card_seconds

    teams = {
        (game.sport, game.away.abbreviation.upper()),
        (game.sport, game.home.abbreviation.upper()),
    }
    if teams.intersection(config.favorite_teams):
        return config.favorite_live_card_seconds
    return config.card_seconds


def display_window(now: datetime, lookback_hours: int) -> tuple[datetime, datetime]:
    """Return the recent-games lookback plus the next 24 hours."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    start = now - timedelta(hours=lookback_hours)
    end = now + timedelta(hours=24)
    return start, end


def select_games(
    games: list[Game],
    now: datetime,
    lookback_hours: int = 24,
    myhsal_past_days: int = 3,
    myhsal_upcoming_days: int = 7,
) -> list[Game]:
    """Keep recent/upcoming games; always retain a currently live game."""
    start, end = display_window(now, lookback_hours)
    selected: list[Game] = []
    for game in games:
        local_start = game.start_time_utc.astimezone(now.tzinfo)
        if game.sport == "MYHSAL":
            today = now.date()
            game_day = local_start.date()
            if game.status == "final":
                keep = today - timedelta(days=myhsal_past_days) <= game_day <= today
            else:
                keep = today <= game_day <= today + timedelta(
                    days=myhsal_upcoming_days
                )
        else:
            keep = start <= local_start < end
        if game.status == "live" or keep:
            selected.append(game)
    return selected


def build_cards(
    games: list[Game],
    config: AppConfig,
    now: datetime | None = None,
    had_errors: bool = False,
) -> list[DisplayCard]:
    """Group selected games by configured sport order and add optional headers."""
    current = now or datetime.now(config.zone)
    selected = select_games(
        games,
        current,
        config.lookback_hours,
        config.myhsal.past_days,
        config.myhsal.upcoming_days,
    )
    cards: list[DisplayCard] = []

    for sport in config.sports:
        sport_games = sorted(
            (game for game in selected if game.sport == sport),
            key=(
                (lambda game: (game.status != "final", game.start_time_utc))
                if sport == "MYHSAL"
                else (lambda game: game.start_time_utc)
            ),
        )
        if not sport_games:
            continue
        if config.show_sport_headers:
            title = config.myhsal.title if sport == "MYHSAL" else sport
            cards.append(DisplayCard(type="header", title=title))
        cards.extend(DisplayCard(type="game", game=game) for game in sport_games)

    if not cards:
        title = "DATA ERROR" if had_errors else "NO GAMES"
        cards.append(DisplayCard(type="message", title=title))
    return cards
