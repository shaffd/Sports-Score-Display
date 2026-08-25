from datetime import date, datetime, timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from camp_dovid import (
    CAMP_BLUE,
    CampDovidFetcher,
    CampGame,
    CampSnapshot,
    CampStanding,
    build_camp_dovid_cards,
    team_color,
)
from config import CampDovidConfig
from renderer import ScoreRenderer


ZONE = ZoneInfo("America/New_York")


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Session:
    def __init__(self, standings, schedule):
        self.headers = {}
        self.standings = standings
        self.schedule = schedule
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        if "/standings/" in url:
            return _Response(self.standings)
        if "/unified-games/" in url:
            return _Response(self.schedule)
        raise AssertionError(f"Unexpected URL: {url}")


class _Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def _standings_payload():
    teams = [
        (1, "Spartans", 2, 2, 0, 0, 4),
        (2, "Michigan", 2, 1, 1, 0, 2),
        (3, "Wolverines", 2, 1, 1, 0, 2),
        (4, "Lions", 2, 0, 2, 0, 0),
        (5, "Canadiens", 2, 0, 2, 0, 0),
    ]
    return {
        "status": "success",
        "data": [
            {
                "divisionId": 83615,
                "standings": [
                    {
                        "rank": rank,
                        "team": {"id": rank, "title": team},
                        "stats": {
                            "GP": gp,
                            "W": wins,
                            "L": losses,
                            "T": ties,
                            "PTS": points,
                        },
                    }
                    for rank, team, gp, wins, losses, ties, points in teams
                ],
            }
        ],
    }


def _schedule_payload():
    return {
        "data": [
            {
                "gameId": "final-1",
                "timeStampZulu": "2026-08-24T18:00:00Z",
                "status": "final",
                "location": "Rink 1",
                "visitor": {"id": 1, "title": "Spartans", "goals": 4},
                "home": {"id": 2, "title": "Michigan", "goals": 2},
            },
            {
                "gameId": "next-1",
                "timeStampZulu": "2026-08-25T14:30:00Z",
                "status": "scheduled",
                "location": "Rink 2",
                "visitor": {"id": 3, "title": "Wolverines"},
                "home": {"id": 1, "title": "Spartans"},
            },
        ],
        "meta": {"total": 2, "filtered": 2},
    }


class CampDovidTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 24, 18, 0, tzinfo=ZONE)
        self.config = CampDovidConfig(
            enabled=True,
            season_id=15433,
            division_id=83615,
            refresh_seconds=1800,
            active_through=date(2026, 8, 27),
        )

    def test_parses_current_standings_rows(self):
        standings = CampDovidFetcher.parse_standings(
            _standings_payload(), 83615
        )

        self.assertEqual(len(standings), 5)
        self.assertEqual(standings[0].team, "Spartans")
        self.assertEqual(
            (standings[0].rank, standings[0].wins, standings[0].points),
            (1, 2, 4),
        )

    def test_parses_schedule_teams_times_status_and_scores(self):
        games = CampDovidFetcher.parse_schedule(_schedule_payload(), ZONE)

        self.assertEqual([game.game_id for game in games], ["final-1", "next-1"])
        self.assertEqual(games[0].status, "final")
        self.assertEqual((games[0].away_score, games[0].home_score), (4, 2))
        self.assertEqual(games[1].away_team, "Wolverines")
        self.assertEqual(games[1].start_time_utc.tzinfo, timezone.utc)

    def test_fetcher_uses_thirty_minute_cache(self):
        clock = _Clock()
        session = _Session(_standings_payload(), _schedule_payload())
        fetcher = CampDovidFetcher(
            self.config,
            ZONE,
            session=session,
            monotonic=clock,
        )

        first = fetcher.fetch(self.now)
        clock.value = 1799
        second = fetcher.fetch(self.now + timedelta(minutes=10))
        self.assertIs(first, second)
        self.assertEqual(len(session.calls), 2)

        clock.value = 1800
        fetcher.fetch(self.now + timedelta(minutes=30))
        self.assertEqual(len(session.calls), 4)

        standings_url, standings_params, _ = session.calls[0]
        games_url, games_params, _ = session.calls[1]
        self.assertTrue(standings_url.endswith("/standings/15433"))
        self.assertEqual(
            standings_params, {"type": "tournament", "division": "83615"}
        )
        self.assertTrue(games_url.endswith("/unified-games/15433"))
        self.assertEqual(games_params["gameType"], "tournament")
        self.assertEqual(games_params["division"], "83615")

    def test_cards_page_standings_and_include_upcoming_and_results(self):
        snapshot = CampSnapshot(
            standings=tuple(
                CampDovidFetcher.parse_standings(_standings_payload(), 83615)
            ),
            games=tuple(CampDovidFetcher.parse_schedule(_schedule_payload(), ZONE)),
        )

        cards = build_camp_dovid_cards(snapshot, self.now, self.config, ZONE)

        self.assertEqual(cards[0].title, "CAMP DOVID")
        rich_ids = [card.rich_text.card_id for card in cards if card.rich_text]
        self.assertEqual(
            rich_ids,
            [
                "camp-standings-1",
                "camp-standings-2",
                "camp-upcoming-next-1",
                "camp-result-final-1",
            ],
        )

    def test_team_color_is_stable_across_every_card(self):
        color = team_color("Spartans")
        self.assertEqual(color, team_color("SPARTANS"))
        self.assertNotEqual(color, CAMP_BLUE)

        snapshot = CampSnapshot(
            standings=(CampStanding(1, "Spartans", 1, 1, 0, 0, 2),),
            games=(
                CampGame(
                    "next",
                    self.now.astimezone(timezone.utc) + timedelta(hours=1),
                    "scheduled",
                    "Spartans",
                    "Michigan",
                ),
            ),
        )
        cards = build_camp_dovid_cards(snapshot, self.now, self.config, ZONE)
        span_colors = [
            span.color
            for card in cards
            if card.rich_text
            for line in card.rich_text.lines
            for span in line.spans
            if "Spartans" in span.text
        ]
        self.assertEqual(span_colors, [color, color])

    def test_standings_and_finals_use_columns_but_upcoming_stays_centered(self):
        snapshot = CampSnapshot(
            standings=tuple(
                CampDovidFetcher.parse_standings(_standings_payload(), 83615)
            ),
            games=tuple(CampDovidFetcher.parse_schedule(_schedule_payload(), ZONE)),
        )
        cards = build_camp_dovid_cards(snapshot, self.now, self.config, ZONE)
        rich_cards = {
            card.rich_text.card_id: card.rich_text
            for card in cards
            if card.rich_text is not None
        }

        standing_line = rich_cards["camp-standings-1"].lines[0]
        self.assertEqual(standing_line.column_starts, (0, 8, 38))
        self.assertEqual(
            standing_line.column_alignments, ("left", "left", "right")
        )

        upcoming = rich_cards["camp-upcoming-next-1"]
        self.assertTrue(all(not line.column_starts for line in upcoming.lines))
        self.assertTrue(all(line.alignment == "center" for line in upcoming.lines))

        final = rich_cards["camp-result-final-1"]
        for team_line in final.lines[1:3]:
            self.assertEqual(team_line.column_starts, (0, 54))
            self.assertEqual(team_line.column_alignments, ("left", "right"))
        self.assertEqual(final.lines[-1].alignment, "center")
        self.assertFalse(final.lines[-1].column_starts)

    def test_rich_text_renderer_uses_team_colors_without_logos(self):
        snapshot = CampSnapshot(
            standings=(
                CampStanding(
                    1,
                    "A Very Long Spartans Hockey Team",
                    2,
                    2,
                    0,
                    0,
                    4,
                ),
            )
        )
        card = build_camp_dovid_cards(snapshot, self.now, self.config, ZONE)[1]
        image = ScoreRenderer(64, 32, ZONE).render(card)

        colors = {
            image.getpixel((x, y))
            for y in range(image.height)
            for x in range(image.width)
        }
        self.assertEqual(image.size, (64, 32))
        self.assertIn(team_color("A Very Long Spartans Hockey Team"), colors)
        self.assertIn(CAMP_BLUE, colors)

    def test_cards_expire_after_thursday(self):
        snapshot = CampSnapshot(
            standings=(CampStanding(1, "Spartans", 1, 1, 0, 0, 2),)
        )
        friday = datetime(2026, 8, 28, 0, 1, tzinfo=ZONE)

        self.assertEqual(
            build_camp_dovid_cards(snapshot, friday, self.config, ZONE), []
        )


if __name__ == "__main__":
    unittest.main()
