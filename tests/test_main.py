from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from camp_dovid import CampSnapshot, CampStanding
from config import AppConfig, CampDovidConfig
from main import ScoreDisplayApp
from models import FetchBatch, Game, Team


class _Clock:
    now = 0.0

    def monotonic(self):
        return self.now


class _Output:
    def __init__(self, clock):
        self.clock = clock
        self.shown = []
        self.closed = False

    def show(self, frame, duration):
        self.shown.append((frame, duration))
        self.clock.now += duration

    def close(self):
        self.closed = True


class _Renderer:
    @staticmethod
    def render(card):
        return card.key


class _Fetcher:
    def __init__(self, games):
        self.games = games

    def fetch_games(self, *_args):
        return FetchBatch(games=self.games)


class _CampFetcher:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def fetch(self, *_args):
        return self.snapshot


def _live_game(game_id, away):
    return Game(
        sport="MLB",
        game_id=game_id,
        start_time_utc=datetime(2026, 8, 14, tzinfo=timezone.utc),
        status="live",
        away=Team(away, away),
        home=Team("Opponent", "OPP"),
    )


class ScoreDisplayAppTests(unittest.TestCase):
    def test_refresh_replaces_no_games_message_with_camp_cards(self):
        app = ScoreDisplayApp.__new__(ScoreDisplayApp)
        app.config = AppConfig(
            sports=("MLB",),
            show_sport_headers=False,
            camp_dovid=CampDovidConfig(enabled=True),
        )
        app.fetcher = _Fetcher([])
        app.camp_dovid_fetcher = _CampFetcher(
            CampSnapshot(
                standings=(CampStanding(1, "Spartans", 2, 2, 0, 0, 4),)
            )
        )
        app.cards = []
        app.index = 0

        app.refresh()

        self.assertNotIn("message:NO GAMES", [card.key for card in app.cards])
        self.assertEqual(
            [card.key for card in app.cards],
            ["header:CAMP DOVID", "rich_text:camp-standings-1"],
        )

    def test_favorite_dwell_survives_refreshes_before_normal_rotation_resumes(self):
        clock = _Clock()
        app = ScoreDisplayApp.__new__(ScoreDisplayApp)
        app.config = AppConfig(
            refresh_seconds=30,
            card_seconds=5,
            favorite_live_card_seconds=180,
            favorite_teams=(("MLB", "NYY"),),
            sports=("MLB",),
            show_sport_headers=False,
        )
        app.fetcher = _Fetcher([_live_game("favorite", "NYY"), _live_game("other", "BOS")])
        app.output = _Output(clock)
        app.renderer = _Renderer()
        app.cards = []
        app.index = 0

        with patch("main.time.monotonic", side_effect=clock.monotonic):
            app.run(once=True)

        favorite_segments = [
            duration
            for key, duration in app.output.shown
            if key == "MLB:favorite"
        ]
        other_segments = [
            duration for key, duration in app.output.shown if key == "MLB:other"
        ]
        self.assertEqual(sum(favorite_segments), 180)
        self.assertEqual(favorite_segments, [30] * 6)
        self.assertEqual(other_segments, [5])
        self.assertTrue(app.output.closed)


if __name__ == "__main__":
    unittest.main()
