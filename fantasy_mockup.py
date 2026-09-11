"""Generate a visual-only contact sheet for the fantasy football card design.

The values in this file are intentional sample game lines.  They demonstrate
layout only and never call a sports API.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from models import DisplayCard, FantasyPlayer
from renderer import BLACK, WHITE, ScoreRenderer


CARD_SIZE = (64, 32)
SCALE = 6
COLUMNS = 4
GAP = 12
OUTPUT_PATH = Path("mockups/fantasy-football-cards.png")


def _player(
    player_id: str,
    first_name: str,
    last_name: str,
    position: str,
    team: str,
    **stats: int | str,
) -> FantasyPlayer:
    return FantasyPlayer(
        player_id=player_id,
        first_name=first_name,
        last_name=last_name,
        position=position,
        team=team,
        game_status="LIVE Q3 6:24",
        **stats,
    )


def sample_players() -> list[FantasyPlayer]:
    """Return the supplied roster with deliberately fictional sample stats."""
    qbs = dict(
        completions=19,
        pass_attempts=26,
        passing_yards=240,
        passing_touchdowns=2,
        interceptions=1,
        rush_attempts=8,
        rushing_yards=34,
        rushing_touchdowns=1,
        fumbles_lost=0,
    )
    rbs = dict(
        rush_attempts=18,
        rushing_yards=91,
        rushing_touchdowns=1,
        receptions=4,
        targets=5,
        receiving_yards=32,
        receiving_touchdowns=0,
        fumbles_lost=0,
    )
    receivers = dict(
        rush_attempts=1,
        rushing_yards=7,
        rushing_touchdowns=0,
        receptions=7,
        targets=10,
        receiving_yards=105,
        receiving_touchdowns=1,
        fumbles_lost=0,
    )
    tight_ends = dict(
        rush_attempts=0,
        rushing_yards=0,
        rushing_touchdowns=0,
        receptions=5,
        targets=7,
        receiving_yards=58,
        receiving_touchdowns=1,
        fumbles_lost=0,
    )
    return [
        _player("hurts", "Jalen", "Hurts", "QB", "PHI", **qbs),
        _player("dowdle", "Rico", "Dowdle", "RB", "PIT", **rbs),
        _player("gibbs", "Jahmyr", "Gibbs", "RB", "DET", **rbs),
        _player("collins", "Nico", "Collins", "WR", "HOU", **receivers),
        _player("flowers", "Zay", "Flowers", "WR", "BAL", **receivers),
        _player("london", "Drake", "London", "WR", "ATL", **receivers),
        _player("loveland", "Colston", "Loveland", "TE", "CHI", **tight_ends),
        _player("lloyd", "MarShawn", "Lloyd", "RB", "GB", **rbs),
        _player(
            "fairbairn",
            "Ka'imi",
            "Fairbairn",
            "K",
            "HOU",
            field_goals_made=2,
            field_goals_attempted=3,
            extra_points_made=3,
            extra_points_attempted=3,
            kicking_points=9,
        ),
        _player("allen", "Josh", "Allen", "QB", "BUF", **qbs),
        _player("taylor", "Jonathan", "Taylor", "RB", "IND", **rbs),
        _player("brown", "Chase", "Brown", "RB", "CIN", **rbs),
        _player("adams", "Davante", "Adams", "WR", "LAR", **receivers),
        _player("fannin", "Harold", "Fannin Jr", "TE", "CLE", **tight_ends),
        _player("montgomery", "David", "Montgomery", "RB", "HOU", **rbs),
        _player("bates", "John", "Bates", "TE", "WAS", **tight_ends),
    ]


def _scaled_card(frame: Image.Image) -> Image.Image:
    nearest = getattr(Image, "Resampling", Image).NEAREST
    return frame.resize((CARD_SIZE[0] * SCALE, CARD_SIZE[1] * SCALE), nearest)


def main() -> None:
    renderer = ScoreRenderer(*CARD_SIZE, ZoneInfo("America/New_York"))
    cards = [DisplayCard(type="fantasy_header")]
    cards.extend(DisplayCard(type="fantasy", fantasy_player=player) for player in sample_players())

    rows = (len(cards) + COLUMNS - 1) // COLUMNS
    card_width, card_height = CARD_SIZE[0] * SCALE, CARD_SIZE[1] * SCALE
    title_height = 32
    sheet = Image.new(
        "RGB",
        (
            COLUMNS * card_width + (COLUMNS + 1) * GAP,
            title_height + rows * card_height + (rows + 1) * GAP,
        ),
        BLACK,
    )
    title = ImageDraw.Draw(sheet)
    title.text((GAP, 8), "FANTASY FOOTBALL — SAMPLE STAT LAYOUT", fill=WHITE)

    for index, card in enumerate(cards):
        x = GAP + (index % COLUMNS) * (card_width + GAP)
        y = title_height + GAP + (index // COLUMNS) * (card_height + GAP)
        sheet.paste(_scaled_card(renderer.render(card)), (x, y))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
