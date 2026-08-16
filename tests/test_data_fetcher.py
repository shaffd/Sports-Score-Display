from datetime import timezone
import unittest

from data_fetcher import DataFetcher


class DataFetcherTests(unittest.TestCase):
    def test_mlb_schedule_preserves_start_time_and_team_abbreviations(self):
        raw = {
            "gamePk": 123,
            "gameDate": "2026-08-08T00:05:00Z",
            "status": {"abstractGameState": "Preview"},
            "teams": {
                "away": {
                    "team": {"name": "New York Yankees", "abbreviation": "NYY"}
                },
                "home": {
                    "team": {"name": "Boston Red Sox", "abbreviation": "BOS"}
                },
            },
        }

        game = DataFetcher.parse_mlb_game(raw)

        self.assertEqual(game.status, "scheduled")
        self.assertEqual(game.away.abbreviation, "NYY")
        self.assertEqual(game.home.abbreviation, "BOS")
        self.assertEqual(game.start_time_utc.tzinfo, timezone.utc)
        self.assertEqual(game.start_time_utc.hour, 0)

    def test_mlb_live_feed_adds_score_matchup_and_bases(self):
        game = DataFetcher.parse_mlb_game(
            {
                "gamePk": 321,
                "gameDate": "2026-08-07T23:00:00Z",
                "status": {"abstractGameState": "Live"},
                "teams": {
                    "away": {"team": {"name": "Away", "abbreviation": "AWY"}},
                    "home": {"team": {"name": "Home", "abbreviation": "HOM"}},
                },
            }
        )
        live = {
            "gameData": {
                "players": {
                    "ID10": {"lastName": "Pitcher"},
                    "ID20": {"lastName": "Batter"},
                }
            },
            "liveData": {
                "linescore": {
                    "currentInning": 6,
                    "inningState": "Top",
                    "balls": 2,
                    "strikes": 1,
                    "outs": 1,
                    "offense": {"first": {"id": 1}, "third": {"id": 2}},
                    "teams": {"away": {"runs": 4}, "home": {"runs": 2}},
                },
                "plays": {
                    "currentPlay": {
                        "matchup": {
                            "pitcher": {"id": 10, "fullName": "Pat Pitcher"},
                            "batter": {"id": 20, "fullName": "Bill Batter"},
                        }
                    }
                },
            },
        }

        DataFetcher.apply_mlb_live_details(game, live)

        self.assertEqual(game.inning, 6)
        self.assertEqual(game.inning_half, "top")
        self.assertEqual(game.away_score, 4)
        self.assertEqual(game.home_score, 2)
        self.assertEqual(game.pitcher, "Pitcher")
        self.assertEqual(game.batter, "Batter")
        self.assertEqual((game.balls, game.strikes, game.outs), (2, 1, 1))
        self.assertEqual(
            game.bases, {"first": True, "second": False, "third": True}
        )
        self.assertEqual(game.marker, "away")

    def test_nfl_parser_resolves_possession(self):
        event = {
            "id": "nfl-1",
            "date": "2026-09-10T00:20:00Z",
            "competitions": [
                {
                    "competitors": [
                        {
                            "homeAway": "away",
                            "score": "17",
                            "team": {
                                "id": "8",
                                "displayName": "Detroit Lions",
                                "abbreviation": "DET",
                            },
                        },
                        {
                            "homeAway": "home",
                            "score": "14",
                            "team": {
                                "id": "9",
                                "displayName": "Home Team",
                                "abbreviation": "HOM",
                            },
                        },
                    ],
                    "status": {
                        "period": 3,
                        "displayClock": "4:21",
                        "type": {"state": "in", "description": "In Progress"},
                    },
                    "situation": {
                        "possession": "8",
                        "shortDownDistanceText": "3rd & 4",
                        "possessionText": "DET 42",
                    },
                }
            ],
        }

        game = DataFetcher.parse_nfl_event(event)

        self.assertIsNotNone(game)
        self.assertEqual(game.status, "live")
        self.assertEqual(game.possession, "away")
        self.assertEqual(game.period, 3)
        self.assertEqual(game.clock, "4:21")
        self.assertEqual(game.down_distance, "3rd & 4")
        self.assertEqual(game.field_position, "DET 42")

    def test_nhl_parser_uses_current_score_and_period(self):
        raw = {
            "id": 456,
            "startTimeUTC": "2026-01-16T00:00:00Z",
            "gameState": "LIVE",
            "periodDescriptor": {"number": 2},
            "clock": {"timeRemaining": "08:12"},
            "awayTeam": {
                "name": {"default": "Rangers"},
                "abbrev": "NYR",
                "score": 2,
            },
            "homeTeam": {
                "name": {"default": "Bruins"},
                "abbrev": "BOS",
                "score": 1,
            },
        }

        game = DataFetcher.parse_nhl_game(raw)

        self.assertEqual(game.status, "live")
        self.assertEqual((game.away_score, game.home_score), (2, 1))
        self.assertEqual((game.period, game.clock), (2, "08:12"))


if __name__ == "__main__":
    unittest.main()
