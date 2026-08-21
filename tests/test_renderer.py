from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from models import DisplayCard, Game, Team
from renderer import Region, ScoreRenderer, TEAM_LABEL_COLOR, WHITE


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

    def test_large_logo_pair_keeps_a_center_gap_with_bounded_outer_crop(self):
        with TemporaryDirectory() as temp_dir:
            logo_dir = Path(temp_dir) / "NHL"
            logo_dir.mkdir(parents=True)
            Image.new("RGBA", (36, 25), (255, 0, 0, 255)).save(logo_dir / "AWY.png")
            Image.new("RGBA", (36, 25), (0, 0, 255, 255)).save(logo_dir / "HOM.png")
            renderer = ScoreRenderer(
                64,
                32,
                ZoneInfo("America/New_York"),
                logo_directory=temp_dir,
            )

            game = self._live_game()
            layout = renderer._layout_for(game)
            away_logo = renderer._load_logo("NHL", "AWY", layout.logo_max_width, layout.logos.height)
            home_logo = renderer._load_logo("NHL", "HOM", layout.logo_max_width, layout.logos.height)
            away_crop, home_crop = renderer._paired_logo_outer_crops(
                away_logo, home_logo
            )

            self.assertIsNotNone(away_logo)
            self.assertIsNotNone(home_logo)
            self.assertLessEqual(away_crop, away_logo.width // 3)
            self.assertLessEqual(home_crop, home_logo.width // 3)
            away_visible_right = away_logo.width - away_crop
            home_visible_left = 64 - home_logo.width + home_crop
            self.assertGreaterEqual(home_visible_left - away_visible_right, 12)

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
                self.assertEqual(layout.header.bottom, 7)
                self.assertEqual(layout.logos.top, layout.header.bottom)
                self.assertEqual(layout.logos.bottom, 32)
                self.assertEqual(layout.scores, layout.logos)

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

    def test_league_specific_live_details_fit_inside_header(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))
        mlb_game = self._live_mlb_game()
        mlb_game.balls = 2
        mlb_game.strikes = 1
        mlb_game.outs = 1

        for game in (self._live_nfl_game(), mlb_game):
            with self.subTest(sport=game.sport):
                layout = renderer._layout_for(game)
                image = Image.new("RGB", (64, 32))
                renderer._draw_game_header(
                    ImageDraw.Draw(image),
                    game,
                    layout.header,
                )
                bounds = image.getbbox()
                self.assertIsNotNone(bounds)
                self.assertGreaterEqual(bounds[1], layout.header.top)
                self.assertLessEqual(bounds[3], layout.header.bottom)
                for y in range(layout.header.bottom, image.height):
                    self.assertTrue(
                        all(image.getpixel((x, y)) == (0, 0, 0) for x in range(64))
                    )

    def test_game_cards_label_away_and_home_in_header(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))

        image = renderer.render(DisplayCard(type="game", game=self._live_game()))

        header_colors = {
            image.getpixel((x, y))
            for y in range(7)
            for x in range(64)
        }
        self.assertIn(TEAM_LABEL_COLOR, header_colors)

    def test_finished_scores_have_center_dash(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))
        game = self._live_game()
        game.status = "final"
        layout = renderer._layout_for(game)

        image = renderer.render(DisplayCard(type="game", game=game))
        center_y = layout.scores.top + layout.scores.height // 2

        self.assertEqual(
            [image.getpixel((x, center_y)) for x in range(31, 34)],
            [WHITE, WHITE, WHITE],
        )

    def test_upcoming_games_have_center_at_marker(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))
        game = self._live_game()
        game.status = "scheduled"
        layout = renderer._layout_for(game)

        image = renderer.render(DisplayCard(type="game", game=game))
        marker_bounds = renderer._pattern_mask(
            (
                "0111110",
                "1000001",
                "1011101",
                "1010101",
                "1011111",
                "1000000",
                "0111110",
            )
        ).getbbox()
        center_y = layout.scores.top + layout.scores.height // 2

        self.assertIsNotNone(marker_bounds)
        self.assertEqual(image.getpixel((32, center_y)), WHITE)

    def test_mlb_outs_uses_the_compact_rounded_o_distinct_from_zero(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))
        font = renderer._font(5)

        outs_mask = renderer._rasterize_text("O", font)
        zero_mask = renderer._rasterize_text("0", font)

        self.assertEqual(outs_mask.size, (3, 5))
        self.assertEqual(zero_mask.size, (3, 5))
        self.assertEqual(outs_mask.getpixel((0, 0)), 0)
        self.assertEqual(outs_mask.getpixel((1, 0)), 1)
        self.assertEqual(zero_mask.getpixel((0, 0)), 1)
        self.assertEqual(zero_mask.getpixel((1, 0)), 1)

    def test_mlb_live_status_is_centered_as_one_header_unit(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))
        game = self._live_mlb_game()
        game.balls = 2
        game.strikes = 1
        game.outs = 1
        layout = renderer._layout_for(game)
        content = Region(5, 0, 59, layout.header.bottom)
        image = Image.new("RGB", (64, 32))

        renderer._draw_mlb_header(ImageDraw.Draw(image), game, content)

        bounds = image.getbbox()
        self.assertIsNotNone(bounds)
        self.assertLessEqual(abs((bounds[0] + bounds[2]) - (content.left + content.right)), 1)

    def test_mlb_diamond_sits_between_the_header_and_score_boxes(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))
        game = self._live_mlb_game()
        layout = renderer._layout_for(game)
        _, diamond_y = renderer._mlb_bases_center(layout)
        radius = 1
        gap = radius * 3
        score_font = renderer._fitted_font("88", 15, 10, 10)
        score_top = (
            layout.scores.top + layout.scores.height // 2 - score_font.scale * 5 // 2
        )

        self.assertGreater(diamond_y - gap // 2 - radius, layout.header.bottom)
        self.assertLess(diamond_y + gap // 2 + radius, score_top)

    def test_score_centers_are_shared_and_widely_separated_for_all_sports(self):
        renderer = ScoreRenderer(64, 32, ZoneInfo("America/New_York"))

        mlb_centers = renderer._score_centers()
        nfl_centers = renderer._score_centers()

        self.assertEqual(mlb_centers, nfl_centers)
        self.assertEqual(mlb_centers, (21, 43))
        self.assertGreaterEqual(nfl_centers[1] - nfl_centers[0], 22)

    def test_mlb_at_bat_marker_follows_inning_half(self):
        self.assertEqual(self._live_mlb_game("top").marker, "away")
        self.assertEqual(self._live_mlb_game("bottom").marker, "home")

    def test_hockey_and_football_live_details_include_clocks(self):
        self.assertEqual(ScoreRenderer._period_clock("P", 2, "08:12"), "P2 08:12")
        self.assertEqual(ScoreRenderer._period_clock("Q", 3, "4:21"), "Q3 4:21")


if __name__ == "__main__":
    unittest.main()
