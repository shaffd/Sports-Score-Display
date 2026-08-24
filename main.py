"""Sports Score Display application entry point."""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import replace
from datetime import datetime, timedelta

from camp_dovid import CampDovidFetcher, build_camp_dovid_cards
from config import AppConfig, ConfigError, load_config
from data_fetcher import DataFetcher
from display_utils import build_cards, card_display_seconds, display_window
from models import DisplayCard
from outputs import DisplayClosed, create_output
from renderer import ScoreRenderer


LOGGER = logging.getLogger(__name__)


class ScoreDisplayApp:
    """Refresh API data independently from the rotating card interval."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.fetcher = DataFetcher(timeout=config.api_timeout_seconds)
        self.camp_dovid_fetcher = CampDovidFetcher(
            config.camp_dovid,
            config.zone,
            timeout=config.api_timeout_seconds,
        )
        self.output = create_output(config)
        self.renderer = ScoreRenderer(
            width=self.output.width,
            height=self.output.height,
            timezone=config.zone,
            logo_directory=config.assets.logo_directory,
            font_path=config.assets.font_path,
        )
        self.cards: list[DisplayCard] = []
        self.index = 0

    def refresh(self, preferred_card_key: str | None = None) -> bool:
        """Refresh cards and retain a requested card when it is still available."""
        if preferred_card_key is None and self.cards:
            preferred_card_key = self.cards[self.index].key

        now = datetime.now(self.config.zone)
        start, end = display_window(now, self.config.lookback_hours)
        query_end = (end - timedelta(microseconds=1)).date()
        batch = self.fetcher.fetch_games(start.date(), query_end, self.config.sports)
        refreshed_cards = build_cards(
            batch.games,
            self.config,
            now=now,
            had_errors=bool(batch.errors),
        )
        if self.config.camp_dovid.enabled:
            camp_snapshot = self.camp_dovid_fetcher.fetch(now)
            camp_cards = build_camp_dovid_cards(
                camp_snapshot,
                now,
                self.config.camp_dovid,
                self.config.zone,
            )
            if camp_cards:
                refreshed_cards = [
                    card
                    for card in refreshed_cards
                    if not (card.type == "message" and card.title == "NO GAMES")
                ]
                refreshed_cards.extend(camp_cards)
        self.cards = refreshed_cards

        retained = False
        if preferred_card_key is not None:
            for index, card in enumerate(self.cards):
                if card.key == preferred_card_key:
                    self.index = index
                    retained = True
                    break
        if not retained:
            self.index %= len(self.cards)

        LOGGER.info(
            "Refresh complete: %d games, %d cards, errors=%s",
            len(batch.games),
            len(self.cards),
            ",".join(batch.errors) or "none",
        )
        return retained

    def run(self, once: bool = False) -> None:
        next_refresh = 0.0
        cards_shown = 0
        try:
            while True:
                current_time = time.monotonic()
                if not self.cards or current_time >= next_refresh:
                    self.refresh()
                    next_refresh = time.monotonic() + self.config.refresh_seconds

                card_key = self.cards[self.index].key
                card_started = time.monotonic()
                card_retained = True

                while True:
                    current_time = time.monotonic()
                    if current_time >= next_refresh:
                        card_retained = self.refresh(card_key)
                        next_refresh = time.monotonic() + self.config.refresh_seconds
                        if not card_retained:
                            break
                        current_time = time.monotonic()

                    card = self.cards[self.index]
                    remaining = (
                        card_display_seconds(card, self.config)
                        - (current_time - card_started)
                    )
                    if remaining <= 0:
                        break

                    frame = self.renderer.render(card)
                    until_refresh = max(0.1, next_refresh - time.monotonic())
                    self.output.show(frame, min(remaining, until_refresh))

                if card_retained and self.cards[self.index].key == card_key:
                    self.index = (self.index + 1) % len(self.cards)
                cards_shown += 1
                if once and cards_shown >= len(self.cards):
                    return
        except (KeyboardInterrupt, DisplayClosed):
            LOGGER.info("Display stopped")
        finally:
            self.output.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NHL/NFL/MLB LED score display")
    parser.add_argument("--config", default="config.json", help="Path to JSON config")
    parser.add_argument(
        "--output",
        choices=("preview", "matrix"),
        help="Override the output selected in config.json",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Show each current card once, then exit",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = load_config(args.config)
        if args.output:
            config = replace(config, output=args.output)
        ScoreDisplayApp(config).run(once=args.once)
        return 0
    except (ConfigError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
