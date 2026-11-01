from datetime import date
import unittest
from zoneinfo import ZoneInfo

from myhsal import MyhsalClient, parse_team_page


TEAM_PAGE = """
<html><body>
  <h4>Boys Varsity Hockey</h4>
  <div id="tab2"><ul>
    <li class="schedule_list">
      <div class="schedule_name"><img src="/logos/jec.png"><h5><a href="/Teams/hockey-boys-v/jec">JEC</a></h5></div>
      <div class="schedule_name"><img src="/logos/tabc.png"><h5><a href="/Teams/hockey-boys-v/tabc">TABC</a></h5></div>
      <div class="center_schedule"><h2>Thu 11/05, 8:15 PM</h2></div>
    </li>
  </ul></div>
  <div id="tab3"><ul>
    <li class="tournament_list">
      <div class="name_tournament"><h4><a href="/Teams/hockey-boys-v/kushner">KUSHNER</a></h4><img src="/logos/kushner.png"></div>
      <div class="tournament_number"><div class="tournament_num">1</div><div class="tournament_num win">8</div></div>
      <div class="name_tournament"><h4><a href="/Teams/hockey-boys-v/tabc">TABC</a></h4><img src="/logos/tabc.png"></div>
      <div class="overtime"><p>Wednesday, October 28 2026</p><p></p></div>
    </li>
  </ul></div>
</body></html>
"""


class _Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class _Session:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        return _Response(self.pages[url])


class MyhsalTests(unittest.TestCase):
    def setUp(self):
        self.zone = ZoneInfo("America/New_York")

    def test_team_page_parses_schedule_results_logos_and_footer(self):
        games = parse_team_page(
            TEAM_PAGE,
            "hockey-boys-v",
            date(2026, 10, 31),
            self.zone,
        )

        self.assertEqual(len(games), 2)
        scheduled, final = games
        self.assertEqual(scheduled.status, "scheduled")
        self.assertEqual(scheduled.start_time_utc.year, 2026)
        self.assertEqual(scheduled.away.name, "JEC")
        self.assertEqual(scheduled.home.logo_key, "TABC")
        self.assertEqual(scheduled.footer_label, "Varsity Hockey")
        self.assertEqual(final.status, "final")
        self.assertEqual((final.away_score, final.home_score), (1, 8))

    def test_schedule_year_is_inferred_across_new_year(self):
        html = TEAM_PAGE.replace("11/05", "1/04")
        game = parse_team_page(
            html,
            "hockey-boys-v",
            date(2026, 12, 31),
            self.zone,
        )[0]
        self.assertEqual(game.start_time_utc.astimezone(self.zone).year, 2027)

    def test_doubleheader_without_time_gets_a_truthful_compact_label(self):
        html = TEAM_PAGE.replace("Thu 11/05, 8:15 PM", "Mon 11/16, DH Game 2")
        game = parse_team_page(
            html,
            "basketball-boys-v",
            date(2026, 11, 10),
            self.zone,
        )[0]
        self.assertEqual(game.scheduled_label, "DH2 11/16")

    def test_text_results_are_preserved(self):
        html = TEAM_PAGE.replace(
            '<div class="tournament_num">1</div><div class="tournament_num win">8</div>',
            '<div class="tournament_num">L</div><div class="tournament_num win">W</div>',
        )
        final = parse_team_page(
            html,
            "boys-volleyball",
            date(2026, 10, 31),
            self.zone,
        )[1]
        self.assertEqual((final.away_score, final.home_score), ("L", "W"))

    def test_division_discovery_is_cached_and_keeps_only_school(self):
        homepage = """
        <a href="/Teams/hockey-boys-v">Hockey</a>
        <a href="/Teams/girls-hockey">Girls Hockey</a>
        """
        pages = {
            "https://example.test/": homepage,
            "https://example.test/Teams/hockey-boys-v": (
                '<a href="/Teams/hockey-boys-v/tabc">TABC</a>'
            ),
            "https://example.test/Teams/girls-hockey": (
                '<a href="/Teams/girls-hockey/other">OTHER</a>'
            ),
        }
        session = _Session(pages)
        client = MyhsalClient(
            "tabc",
            session=session,
            base_url="https://example.test",
        )

        self.assertEqual(client.discover_divisions(), ("hockey-boys-v",))
        self.assertEqual(client.discover_divisions(), ("hockey-boys-v",))
        self.assertEqual(len(session.calls), 3)


if __name__ == "__main__":
    unittest.main()
