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
        if "getDivisionStandings" in url:
            return _Response(self.standings)
        if "getSeasonSchedule" in url:
            return _Response(self.schedule)
        raise AssertionError(f"Unexpected URL: {url}")


class _Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def _standings_payload():
    return [
        {
            "id": 83615,
            "title": "JR",
            "tableData": {
                "teamTitles": [
                    {"id": 1, "title": "Spartans"},
                    {"id": 2, "title": "Michigan"},
                    {"id": 3, "title": "Wolverines"},
                    {"id": 4, "title": "Lions"},
                    {"id": 5, "title": "Canadiens"},
                ],
                "ranks": [1, 2, 3, 4, 5],
                "gp": [2, 2, 2, 2, 2],
                "w": [2, 1, 1, 0, 0],
                "l": [0, 1, 1, 2, 2],
                "t": [0, 0, 0, 0, 0],
                "pts": [4, 2, 2, 0, 0],
            },
        }
    ]


def _schedule_payload():
    return {
        "100_0": [
            {
                "date": "Mon, Aug 24, 2026 - 2 Games",
                "games": [
                    {
                        "id": "final-1",
                        "scheduleStartTime": "2026-08-24T14:00:00-04:00",
                        "status": "final",
                        "location": "Rink 1",
                        "visitorTeam": {"id": 1, "name": "Spartans", "score": 4},
                        "homeTeam": {"id": 2, "name": "Michigan", "score": 2},
                    },
                    {
                        "id": "next-1",
                        "scheduleStartTime": "2026-08-25T10:30:00-04:00",
                        "status": "scheduled",
                        "location": "Rink 2",
                        "visitorTeam": {"id": 3, "name": "Wolverines"},
                        "homeTeam": {"id": 1, "name": "Spartans"},
                    },
                ],
            }
        ]
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

    def test_parses_parallel_standings_arrays(self):
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
