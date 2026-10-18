import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from wifi_setup import (
    WifiSetupController,
    WifiNetwork,
    hotspot_name,
    render_setup_page,
    split_nmcli_fields,
    validate_wifi_credentials,
)
from wifi_status import wifi_setup_cards


class _Controller:
    address = "10.42.0.1"
    last_error = ""


class _FakeNetworkManager:
    interface = "wlan0"

    def __init__(self, saved_connections):
        self._saved_connections = saved_connections

    def saved_wifi_connections(self):
        return list(self._saved_connections)


class WifiSetupTests(unittest.TestCase):
    def test_connection_grace_depends_on_saved_wifi_profiles(self):
        first_time = WifiSetupController(_FakeNetworkManager([]))
        returning = WifiSetupController(_FakeNetworkManager(["Home Wi-Fi"]))

        self.assertEqual(first_time._connection_grace_seconds(), 30)
        self.assertEqual(returning._connection_grace_seconds(), 180)
        self.assertEqual(returning.retry_saved_seconds, 60)

    def test_nmcli_parser_preserves_escaped_colons_and_backslashes(self):
        self.assertEqual(
            split_nmcli_fields(r"Home\: Upstairs:82:WPA2"),
            ["Home: Upstairs", "82", "WPA2"],
        )
        self.assertEqual(
            split_nmcli_fields(r"Back\\Slash:50:WPA2"),
            [r"Back\Slash", "50", "WPA2"],
        )

    def test_hotspot_name_uses_last_four_mac_characters(self):
        with patch.object(Path, "read_text", return_value="b8:27:eb:12:ab:cd\n"):
            self.assertEqual(hotspot_name("wlan0"), "GameBlink-ABCD")

    def test_credentials_are_validated_before_nmcli(self):
        validate_wifi_credentials("Home", "correcthorsebattery")
        validate_wifi_credentials("Coffee Shop", "")
        with self.assertRaises(ValueError):
            validate_wifi_credentials("", "password")
        with self.assertRaises(ValueError):
            validate_wifi_credentials("Home", "short")

    def test_setup_page_is_self_contained_and_escapes_network_names(self):
        page = render_setup_page(
            _Controller(),
            [WifiNetwork('<Home & "Office">', 88, "WPA2")],
        )
        self.assertIn("GameBlink", page)
        self.assertIn("&lt;Home &amp; &quot;Office&quot;&gt;", page)
        self.assertNotIn("https://", page)

    def test_status_file_becomes_led_setup_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / "status.json"
            status.write_text(
                '{"state":"setup","ssid":"GameBlink-ABCD",'
                '"password":"GAMEBLINK","error":""}',
                encoding="utf-8",
            )
            titles = [card.title for card in wifi_setup_cards(status) or []]
        self.assertEqual(
            titles,
            [
                "WIFI SETUP",
                "JOIN",
                "GameBlink-ABCD",
                "PASSWORD",
                "GAMEBLINK",
                "OPEN",
                "10.42.0.1",
            ],
        )

    def test_connected_status_does_not_replace_score_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / "status.json"
            status.write_text('{"state":"connected"}', encoding="utf-8")
            self.assertIsNone(wifi_setup_cards(status))


if __name__ == "__main__":
    unittest.main()
