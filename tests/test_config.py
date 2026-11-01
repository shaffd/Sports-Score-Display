from pathlib import Path
import unittest

from config import load_config


class ConfigTests(unittest.TestCase):
    def test_project_config_uses_uniform_seven_second_cards(self):
        project_config = Path(__file__).resolve().parents[1] / "config.json"

        config = load_config(project_config)

        self.assertEqual(config.matrix.hardware_mapping, "adafruit-hat")
        self.assertEqual(config.card_seconds, 7)
        self.assertEqual(config.favorite_live_card_seconds, 7)
        self.assertEqual(config.favorite_teams, ())
        self.assertIn("MYHSAL", config.sports)
        self.assertEqual(config.myhsal.school_slug, "tabc")
        self.assertEqual(config.myhsal.title, "MYHSAL - TABC")
        self.assertEqual(
            (config.myhsal.past_days, config.myhsal.upcoming_days),
            (3, 7),
        )


if __name__ == "__main__":
    unittest.main()
