from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

from config import AppConfig, AssetConfig
from display_utils import (
    build_cards,
    card_display_seconds,
    format_status,
    select_games,
)
from models import Game, Team


def make_game(game_id: str, start: datetime, status: str = "scheduled") -> Game:
    return Game(
        sport="MLB",
        game_id=game_id,
        start_time_utc=start.astimezone(timezone.utc),
        status=status,
        away=Team("Away", "AWY"),
        home=Team("Home", "HOM"),
    )


class DisplayUtilsTests(unittest.TestCase):
    def setUp(self):
        self.zone = ZoneInfo("America/New_York")
        self.now = datetime(2026, 8, 7, 18, 0, tzinfo=self.zone)

    def test_window_keeps_previous_24_hours_and_next_24_hours(self):
        games = [
            make_game("too-old", self.now - timedelta(hours=25), "final"),
            make_game("recent", self.now - timedelta(hours=23), "final"),
            make_game("later", self.now + timedelta(hours=3)),
            make_game("tomorrow", self.now + timedelta(hours=7)),
            make_game("too-far", self.now + timedelta(hours=24, minutes=1)),
            make_game("live", self.now - timedelta(hours=30), "live"),
        ]

        selected = select_games(games, self.now, 24)

        self.assertEqual(
            {game.game_id for game in selected}, {"recent", "later", "tomorrow", "live"}
        )

    def test_scheduled_mlb_status_has_eastern_time_and_date(self):
        game = make_game(
            "scheduled", datetime(2026, 8, 8, 0, 5, tzinfo=timezone.utc)
        )
        self.assertEqual(format_status(game, self.zone), "8:05 PM 08/07")

    def test_cards_follow_configured_sport_order(self):
        nhl = make_game("nhl", self.now)
        nhl.sport = "NHL"
        mlb = make_game("mlb", self.now)
        config = AppConfig(
            sports=("NHL", "MLB"),
            assets=AssetConfig(logo_directory=Path("Logos")),
        )

        cards = build_cards([mlb, nhl], config, self.now)

        self.assertEqual(
            [card.key for card in cards],
            ["header:NHL", "NHL:nhl", "header:MLB", "MLB:mlb"],
        )

    def test_live_favorite_games_use_extended_dwell(self):
        config = AppConfig(
            card_seconds=5,
            favorite_live_card_seconds=180,
            favorite_teams=(("MLB", "NYY"), ("NHL", "NYR"), ("NFL", "DET")),
        )
        cases = (
            ("MLB", "NYY", "BOS"),
            ("NHL", "BOS", "NYR"),
            ("NFL", "DET", "GB"),
        )

        for sport, away, home in cases:
            with self.subTest(sport=sport):
                game = make_game(sport.lower(), self.now, "live")
                game.sport = sport
                game.away.abbreviation = away
                game.home.abbreviation = home
                self.assertEqual(
                    card_display_seconds(
                        build_cards(
                            [game],
                            AppConfig(
                                sports=(sport,),
                                show_sport_headers=False,
                                favorite_live_card_seconds=180,
                                favorite_teams=config.favorite_teams,
                            ),
                            self.now,
                        )[0],
                        config,
                    ),
                    180,
                )

    def test_extended_dwell_requires_live_status_and_matching_sport(self):
        config = AppConfig(
            card_seconds=5,
            favorite_live_card_seconds=180,
            favorite_teams=(("NFL", "DET"),),
        )
        final_lions = make_game("final", self.now, "final")
        final_lions.sport = "NFL"
        final_lions.away.abbreviation = "DET"
        live_tigers = make_game("other-sport", self.now, "live")
        live_tigers.away.abbreviation = "DET"

        from models import DisplayCard

        self.assertEqual(
            card_display_seconds(DisplayCard(type="game", game=final_lions), config),
            5,
        )
        self.assertEqual(
            card_display_seconds(DisplayCard(type="game", game=live_tigers), config),
            5,
        )


if __name__ == "__main__":
    unittest.main()
