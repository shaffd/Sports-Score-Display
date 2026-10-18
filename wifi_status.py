"""Translate the Wi-Fi setup service state into LED display cards."""

from __future__ import annotations

import json
import os
from pathlib import Path

from models import DisplayCard


DEFAULT_WIFI_STATUS_PATH = Path("/run/gameblink-wifi/status.json")


def status_path() -> Path:
    """Return the runtime path, allowing tests and custom installs to override it."""
    return Path(os.environ.get("GAMEBLINK_WIFI_STATUS", DEFAULT_WIFI_STATUS_PATH))


def wifi_setup_cards(path: str | Path | None = None) -> list[DisplayCard] | None:
    """Return setup cards while Wi-Fi interaction needs the owner's attention."""
    target = Path(path) if path is not None else status_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None

    state = str(payload.get("state", ""))
    if state == "checking":
        return _message_cards("WIFI", "STARTING")
    if state == "connecting":
        return _message_cards("WIFI", "CONNECTING")
    if state != "setup":
        return None

    ssid = str(payload.get("ssid", "GameBlink-SETUP"))
    password = str(payload.get("password", "GAMEBLINK"))
    cards = [
        "WIFI SETUP",
        "JOIN",
        ssid,
        "PASSWORD",
        password,
        "OPEN",
        "10.42.0.1",
    ]
    if payload.get("error"):
        cards[:0] = ["WIFI FAILED", "TRY AGAIN"]
    return _message_cards(*cards)


def _message_cards(*titles: str) -> list[DisplayCard]:
    return [DisplayCard(type="message", title=title) for title in titles]
