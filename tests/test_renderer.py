from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from models import DisplayCard, Game, Team
from renderer import ScoreRenderer


class RendererTests(unittest.TestCase):
    def _live_game(self) -> Game:
        return Game(
            sport="NHL",
            game_id="1",
            start_time_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="live",
            away=Team("Away", "AWY"),
            home=Team("Home", "HOM"),
            away_score=2,
            home_score=1,
            period=2,
            clock="08:12",
        )

    def _live_mlb_game(self, inning_half="top") -> Game:
        return Game(
            sport="MLB",
            game_id="2",
            start_time_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="live",
            away=Team("Away", "AWY"),
            home=Team("Home", "HOM"),
            away_score=3,
            home_score=2,
            inning=5,
            inning_half=inning_half,
            bases={"first": True, "second": False, "third": True},
            pitcher="Pitcher",
            batter="Batter",
        )

    def test_renderer_uses_requested_resolution(self):
        renderer = ScoreRenderer(128, 64, ZoneInfo("America/New_York"))
        image = renderer.render(DisplayCard(type="game", game=self._live_game()))
        self.assertEqual(image.size, (128, 64))

    def test_logos_are_clipped_at_opposite_edges(self):
        with TemporaryDirectory() as temp_dir:
            logo_dir = Path(temp_dir) / "NHL"
            logo_dir.mkdir(parents=True)
            Image.new("RGBA", (30, 30), (255, 0, 0, 255)).save(logo_dir / "AWY.png")
            Image.new("RGBA", (30, 30), (0, 0, 255, 255)).save(logo_dir / "HOM.png")
            renderer = ScoreRenderer(
                64,
                32,
                ZoneInfo("America/New_York"),
                logo_directory=temp_dir,
            )

            image = renderer.render(DisplayCard(type="game", game=self._live_game()))

            left_edge = [image.getpixel((0, y)) for y in range(image.height)]
            right_edge = [image.getpixel((63, y)) for y in range(image.height)]
            self.assertTrue(any(r > 200 and g < 20 and b < 20 for r, g, b in left_edge))
            self.assertTrue(any(b > 200 and r < 20 and g < 20 for r, g, b in right_edge))

    def test_compact_mlb_details_do_not_cover_team_logos(self):
        with TemporaryDirectory() as temp_dir:
            logo_dir = Path(temp_dir) / "MLB"
            logo_dir.mkdir(parents=True)
            Image.new("RGBA", (30, 30), (255, 0, 0, 255)).save(logo_dir / "AWY.png")
            Image.new("RGBA", (30, 30), (0, 0, 255, 255)).save(logo_dir / "HOM.png")
            renderer = ScoreRenderer(
                64,
                32,
                ZoneInfo("America/New_York"),
                logo_directory=temp_dir,
            )

            image = renderer.render(
                DisplayCard(type="game", game=self._live_mlb_game())
            )

            # Probe the lower logo area that used to be erased by MLB's
            # full-width pitcher/batter information strip.
            status = "IN PROGRESS"
            status_font = renderer._fitted_font(status, renderer.width - 2, 6)
            status_height = renderer._text_size(
                ImageDraw.Draw(image), status, status_font
            )[1]
            logo_size = max(12, int(renderer.height * 0.66))
            logo_y = min(renderer.height - logo_size, status_height + 1)
            probe_y = logo_y + logo_size - 2

            red = image.getpixel((0, probe_y))
            blue = image.getpixel((63, probe_y))
            self.assertGreater(red[0], 200)
            self.assertLess(red[1], 20)
            self.assertGreater(blue[2], 200)
            self.assertLess(blue[0], 20)

    def test_mlb_at_bat_marker_follows_inning_half(self):
        self.assertEqual(self._live_mlb_game("top").marker, "away")
        self.assertEqual(self._live_mlb_game("bottom").marker, "home")

    def test_hockey_and_football_live_details_include_clocks(self):
        self.assertEqual(ScoreRenderer._period_clock("P", 2, "08:12"), "P2 08:12")
        self.assertEqual(ScoreRenderer._period_clock("Q", 3, "4:21"), "Q3 4:21")


if __name__ == "__main__":
    unittest.main()
