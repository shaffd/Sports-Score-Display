from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from config import MatrixConfig, load_config


class ConfigTests(unittest.TestCase):
    def test_project_config_matches_bonnet_and_favorite_team_setup(self):
        project_config = Path(__file__).resolve().parents[1] / "config.json"

        config = load_config(project_config)

        self.assertEqual(config.matrix.hardware_mapping, "adafruit-hat")
        self.assertEqual(config.favorite_live_card_seconds, 180)
        self.assertEqual(
            set(config.favorite_teams),
            {("MLB", "NYY"), ("NHL", "NYR"), ("NFL", "DET")},
        )
        self.assertTrue(config.fantasy_football.enabled)
        self.assertEqual(len(config.fantasy_football.players), 16)
        self.assertEqual(config.fantasy_football.players[0].player_id, "hurts")
        self.assertEqual(config.matrix.led_rgb_sequence, "RBG")

    def test_matrix_color_order_defaults_to_rbg(self):
        self.assertEqual(MatrixConfig().led_rgb_sequence, "RBG")

        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("{}", encoding="utf-8")

            config = load_config(config_path)

        self.assertEqual(config.matrix.led_rgb_sequence, "RBG")

    def test_nhl_logo_assets_cover_feed_abbreviation_and_standard_rangers_mark(self):
        project_root = Path(__file__).resolve().parents[1]
        logos = project_root / "Logos"

        self.assertTrue((logos / "NHL" / "TBL.png").is_file())
        self.assertEqual(
            (logos / "NHL" / "NYR.png").read_bytes(),
            (logos / "_sources" / "NHL" / "NYR.legacy.png").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
