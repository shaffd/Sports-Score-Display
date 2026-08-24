from pathlib import Path
import unittest

from config import load_config


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
        self.assertTrue(config.camp_dovid.enabled)
        self.assertEqual(config.camp_dovid.season_id, 15433)
        self.assertEqual(config.camp_dovid.division_id, 83615)
        self.assertEqual(config.camp_dovid.refresh_seconds, 1800)
        self.assertEqual(config.camp_dovid.active_through.isoformat(), "2026-08-27")


if __name__ == "__main__":
    unittest.main()
