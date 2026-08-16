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

    def _live_nfl_game(self) -> Game:
        return Game(
            sport="NFL",
            game_id="3",
            start_time_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="live",
            away=Team("Away", "AWY"),
            home=Team("Home", "HOM"),
            away_score=21,
            home_score=17,
            period=3,
            clock="08:42",
            possession="away",
            down_distance="3rd & 4",
            field_position="AWY 42",
        )

    def test_renderer_uses_requested_resolution(self):
        renderer = ScoreRenderer(128, 64, ZoneInfo("America/New_York"))
        image = renderer.render(DisplayCard(type="game", game=self._live_game()))
        self.assertEqual(image.size, (128, 64))

    def test_header_visible_glyphs_are_centered_on_the_full_panel(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))

        image = renderer.render(DisplayCard(type="header", title="NFL"))
        bounds = image.getbbox()

        self.assertIsNotNone(bounds)
        self.assertLessEqual(abs((bounds[0] + bounds[2]) - image.width), 1)
        self.assertLessEqual(abs((bounds[1] + bounds[3]) - image.height), 1)

    def test_default_text_uses_only_fully_on_or_fully_off_pixels(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))

        image = renderer.render(DisplayCard(type="header", title="MLB"))

        colors = {
            image.getpixel((x, y))
            for y in range(image.height)
            for x in range(image.width)
        }
        self.assertEqual(colors, {(0, 0, 0), (255, 255, 255)})

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

    def test_logo_bounds_are_centered_in_the_logo_region(self):
        with TemporaryDirectory() as temp_dir:
            logo_dir = Path(temp_dir) / "MLB"
            logo_dir.mkdir(parents=True)
            Image.new("RGBA", (30, 20), (255, 0, 0, 255)).save(logo_dir / "AWY.png")
            renderer = ScoreRenderer(
                64,
                32,
                ZoneInfo("America/New_York"),
                logo_directory=temp_dir,
            )
            game = self._live_mlb_game()
            layout = renderer._layout_for(game)
            image = Image.new("RGB", (64, 32))
            bounds = renderer._draw_team_logo(
                image,
                ImageDraw.Draw(image),
                "MLB",
                "AWY",
                "away",
                layout.logos,
                layout.logo_max_width,
            )

            self.assertLessEqual(
                abs((bounds[1] + bounds[3]) - (layout.logos.top + layout.logos.bottom)),
                1,
            )
            self.assertEqual(bounds[2] - bounds[0], layout.logo_max_width)

    def test_logo_scaling_is_nearest_neighbor_with_binary_alpha(self):
        with TemporaryDirectory() as temp_dir:
            logo_dir = Path(temp_dir) / "NHL"
            logo_dir.mkdir(parents=True)
            source = Image.new("RGBA", (4, 2), (0, 0, 0, 0))
            source.putpixel((0, 0), (255, 0, 0, 64))
            source.putpixel((1, 0), (255, 0, 0, 192))
            source.putpixel((2, 0), (0, 0, 255, 255))
            source.putpixel((1, 1), (255, 0, 0, 192))
            source.putpixel((2, 1), (0, 0, 255, 255))
            source.save(logo_dir / "AWY.png")
            renderer = ScoreRenderer(
                64,
                32,
                ZoneInfo("America/New_York"),
                logo_directory=temp_dir,
            )

            logo = renderer._load_logo("NHL", "AWY", 12, 12)

            self.assertIsNotNone(logo)
            alpha = logo.getchannel("A")
            alpha_values = {
                alpha.getpixel((x, y))
                for y in range(alpha.height)
                for x in range(alpha.width)
            }
            self.assertLessEqual(alpha_values, {0, 255})
            opaque_colors = {
                logo.getpixel((x, y))[:3]
                for y in range(logo.height)
                for x in range(logo.width)
                if logo.getpixel((x, y))[3] == 255
            }
            self.assertLessEqual(opaque_colors, {(255, 0, 0), (0, 0, 255)})

    def test_live_layout_regions_end_at_row_31(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))

        for game in (self._live_nfl_game(), self._live_mlb_game()):
            with self.subTest(sport=game.sport):
                layout = renderer._layout_for(game)
                self.assertEqual(layout.header.top, 0)
                self.assertEqual(layout.footer.bottom, 32)
                self.assertLess(layout.header.bottom, layout.footer.top)
                self.assertEqual(layout.logos.bottom, 32)
                self.assertEqual(layout.scores.bottom, layout.footer.top)

    def test_live_header_text_fits_inside_header_region(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))
        game = self._live_game()
        layout = renderer._layout_for(game)
        status = renderer._header_status(game)
        font = renderer._fitted_font(
            status,
            layout.header.width - 2,
            layout.header.height,
            layout.header.height,
        )
        image = Image.new("RGB", (64, 32))

        bounds = renderer._draw_text_in_region(
            ImageDraw.Draw(image), status, layout.header, font
        )

        self.assertGreaterEqual(bounds[1], layout.header.top)
        self.assertLessEqual(bounds[3], layout.header.bottom)

    def test_league_specific_live_details_fit_inside_footer(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))
        mlb_game = self._live_mlb_game()
        mlb_game.balls = 2
        mlb_game.strikes = 1
        mlb_game.outs = 1

        for game, draw_details in (
            (self._live_nfl_game(), renderer._draw_nfl_details),
            (mlb_game, renderer._draw_mlb_details),
        ):
            with self.subTest(sport=game.sport):
                layout = renderer._layout_for(game)
                image = Image.new("RGB", (64, 32))
                draw_details(ImageDraw.Draw(image), game, layout.footer)
                bounds = image.getbbox()
                self.assertIsNotNone(bounds)
                self.assertGreaterEqual(bounds[1], layout.footer.top)
                self.assertLessEqual(bounds[3], layout.footer.bottom)

    def test_mlb_at_bat_marker_follows_inning_half(self):
        self.assertEqual(self._live_mlb_game("top").marker, "away")
        self.assertEqual(self._live_mlb_game("bottom").marker, "home")

    def test_hockey_and_football_live_details_include_clocks(self):
        self.assertEqual(ScoreRenderer._period_clock("P", 2, "08:12"), "P2 08:12")
        self.assertEqual(ScoreRenderer._period_clock("Q", 3, "4:21"), "Q3 4:21")


if __name__ == "__main__":
    unittest.main()
