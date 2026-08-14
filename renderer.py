"""Responsive Pillow renderer for score-display cards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from display_utils import format_status
from models import DisplayCard, Game


WHITE = (255, 255, 255)
DIM = (175, 175, 175)
BLACK = (0, 0, 0)


class ScoreRenderer:
    """Render cards at any configured pixel dimensions."""

    def __init__(
        self,
        width: int,
        height: int,
        timezone,
        logo_directory: str | Path = "Logos",
        font_path: str | Path | None = None,
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")
        self.width = width
        self.height = height
        self.timezone = timezone
        self.logo_directory = Path(logo_directory)
        self.font_path = Path(font_path) if font_path else None
        self._font_cache: dict[int, Any] = {}
        self._logo_cache: dict[tuple[str, str, int], Image.Image | None] = {}

    def render(self, card: DisplayCard) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), BLACK)
        draw = ImageDraw.Draw(image)

        if card.type in {"header", "message"}:
            self._render_title(draw, card.title)
        elif card.game is not None:
            self._render_game(image, draw, card.game)
        return image

    def _render_title(self, draw: ImageDraw.ImageDraw, title: str) -> None:
        font = self._fitted_font(title.upper(), self.width - 4, max(7, self.height // 2))
        self._draw_centered(draw, title.upper(), (self.height - self._text_size(draw, title, font)[1]) // 2, font)

    def _render_game(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        game: Game,
    ) -> None:
        status = format_status(game, self.timezone)
        status_font = self._fitted_font(status, self.width - 2, max(6, self.height // 5))
        status_height = self._text_size(draw, status, status_font)[1]

        logo_size = max(12, int(self.height * 0.66))
        logo_y = min(self.height - logo_size, status_height + 1)
        away_bounds = self._draw_team_logo(
            image, draw, game.sport, game.away.abbreviation, "away", logo_size, logo_y
        )
        home_bounds = self._draw_team_logo(
            image, draw, game.sport, game.home.abbreviation, "home", logo_size, logo_y
        )

        # Text is drawn after logos so that it remains readable.
        self._draw_centered(draw, status, 0, status_font)

        if game.status in {"live", "final"}:
            self._draw_scores(draw, game, away_bounds, home_bounds)

        if game.status == "live":
            if game.sport == "NFL":
                detail = self._period_clock("Q", game.period, game.clock)
                self._draw_live_detail(draw, detail)
            elif game.sport == "NHL":
                detail = self._period_clock("P", game.period, game.clock)
                self._draw_live_detail(draw, detail)
            elif game.sport == "MLB":
                self._draw_mlb_details(draw, game)

    def _draw_team_logo(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        sport: str,
        abbreviation: str,
        side: str,
        max_size: int,
        y: int,
    ) -> tuple[int, int, int, int]:
        logo = self._load_logo(sport, abbreviation, max_size)
        if logo is not None:
            logo_width, logo_height = logo.size
            if side == "away":
                # The left third is outside the canvas; the right two thirds remain.
                x = -(logo_width // 3)
            else:
                # The right third is outside the canvas; the left two thirds remain.
                x = self.width - ((2 * logo_width + 2) // 3)
            image.paste(logo, (x, y), logo)
            return (x, y, x + logo_width, y + logo_height)

        # A text abbreviation keeps a card useful until a local PNG is added.
        label = abbreviation[:3].upper() or "???"
        font = self._font(max(6, self.height // 5))
        text_width, text_height = self._text_size(draw, label, font)
        text_y = y + max(0, (max_size - text_height) // 2)
        if side == "away":
            x = -1
        else:
            x = self.width - text_width + 1
        draw.text((x, text_y), label, fill=DIM, font=font)
        return (x, text_y, x + text_width, text_y + text_height)

    def _draw_scores(
        self,
        draw: ImageDraw.ImageDraw,
        game: Game,
        away_bounds: tuple[int, int, int, int],
        home_bounds: tuple[int, int, int, int],
    ) -> None:
        away_score = "-" if game.away_score is None else str(game.away_score)
        home_score = "-" if game.home_score is None else str(game.home_score)
        max_score_width = max(8, self.width // 6)
        score_font = self._fitted_font(
            max(away_score, home_score, key=len), max_score_width, max(8, self.height // 3)
        )
        away_width, score_height = self._text_size(draw, away_score, score_font)
        home_width, _ = self._text_size(draw, home_score, score_font)
        score_y = max(1, (self.height - score_height) // 2)

        away_visible_right = min(self.width, away_bounds[2])
        home_visible_left = max(0, home_bounds[0])
        away_x = min(away_visible_right + 1, self.width // 2 - away_width - 2)
        home_x = max(self.width // 2 + 2, home_visible_left - home_width - 1)

        self._draw_readable_text(draw, (away_x, score_y), away_score, score_font)
        self._draw_readable_text(draw, (home_x, score_y), home_score, score_font)

        marker = game.marker
        radius = max(1, self.height // 24)
        if marker == "away":
            dot_x = away_x + away_width + radius + 1
            dot_y = score_y + score_height // 2
            draw.ellipse(
                (dot_x - radius, dot_y - radius, dot_x + radius, dot_y + radius),
                fill=WHITE,
            )
        elif marker == "home":
            dot_x = home_x - radius - 2
            dot_y = score_y + score_height // 2
            draw.ellipse(
                (dot_x - radius, dot_y - radius, dot_x + radius, dot_y + radius),
                fill=WHITE,
            )

    @staticmethod
    def _period_clock(prefix: str, period: int | None, clock: str | None) -> str:
        period_text = f"{prefix}{period}" if period is not None else prefix
        return " ".join(part for part in (period_text, clock or "") if part)

    def _draw_live_detail(self, draw: ImageDraw.ImageDraw, detail: str) -> None:
        if not detail:
            return
        font = self._fitted_font(detail, self.width - 4, max(6, self.height // 5))
        _, height = self._text_size(draw, detail, font)
        self._draw_centered(draw, detail, self.height - height, font)

    def _draw_mlb_details(self, draw: ImageDraw.ImageDraw, game: Game) -> None:
        if game.inning_half == "top":
            half = "T"
        elif game.inning_half == "bottom":
            half = "B"
        else:
            half = ""
        inning = f"{half}{game.inning or ''}"
        inning_font = self._font(max(6, self.height // 6))
        detail_height = self._text_size(draw, "Ag", inning_font)[1]

        # A 64x32 card has room for the inning and bases, but not another full
        # matchup row without covering the teams. Only show pitcher/batter on
        # taller displays, and keep that text smaller than the game details.
        show_matchup = self.height >= 48 and bool(game.pitcher or game.batter)
        matchup_font = self._font(max(5, min(8, self.height // 8)))
        matchup_height = self._text_size(draw, "Ag", matchup_font)[1]
        names_y = self.height - matchup_height if show_matchup else self.height
        detail_y = max(0, names_y - detail_height - (1 if show_matchup else 0))

        inning_width, _ = self._text_size(draw, inning, inning_font)
        center_gap = max(2, self.height // 16)
        inning_x = max(0, self.width // 2 - inning_width - center_gap)
        bases_center_x = self.width // 2 + max(5, self.height // 9)
        bases_center_y = detail_y + detail_height // 2

        # Black out only the compact center detail area. The previous full-width
        # strip erased the lower portion of both team logos on a 64x32 matrix.
        base_radius = max(1, self.height // 20)
        base_gap = base_radius * 3
        detail_left = max(0, inning_x - 1)
        detail_right = min(
            self.width,
            bases_center_x + base_gap + base_radius + 1,
        )
        draw.rectangle(
            (detail_left, max(0, detail_y - 1), detail_right, names_y),
            fill=BLACK,
        )
        self._draw_readable_text(draw, (inning_x, detail_y), inning, inning_font)
        self._draw_bases(draw, bases_center_x, bases_center_y, game.bases)

        if show_matchup:
            half_width = max(10, (self.width - 8) // 2)
            pitcher = self._trim_to_width(
                draw, f"P:{(game.pitcher or '?').upper()}", matchup_font, half_width
            )
            batter = self._trim_to_width(
                draw, f"B:{(game.batter or '?').upper()}", matchup_font, half_width
            )
            pitcher_width, _ = self._text_size(draw, pitcher, matchup_font)
            batter_width, _ = self._text_size(draw, batter, matchup_font)

            # Use small, local backplates rather than another full-width strip.
            draw.rectangle(
                (
                    0,
                    max(0, names_y - 1),
                    min(self.width, pitcher_width + 1),
                    self.height,
                ),
                fill=BLACK,
            )
            draw.rectangle(
                (
                    max(0, self.width - batter_width - 1),
                    max(0, names_y - 1),
                    self.width,
                    self.height,
                ),
                fill=BLACK,
            )
            self._draw_readable_text(draw, (0, names_y), pitcher, matchup_font)
            self._draw_readable_text(
                draw, (self.width - batter_width, names_y), batter, matchup_font
            )

    def _draw_bases(
        self,
        draw: ImageDraw.ImageDraw,
        center_x: int,
        center_y: int,
        occupied: dict[str, bool],
    ) -> None:
        radius = max(1, self.height // 20)
        gap = radius * 3
        positions = {
            "second": (center_x, center_y - gap // 2),
            "third": (center_x - gap, center_y + gap // 2),
            "first": (center_x + gap, center_y + gap // 2),
        }
        for base, (x, y) in positions.items():
            points = [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)]
            if occupied.get(base, False):
                draw.polygon(points, fill=WHITE)
            else:
                draw.line(points + [points[0]], fill=DIM, width=1)

    def _load_logo(self, sport: str, abbreviation: str, max_size: int) -> Image.Image | None:
        key = (sport.upper(), abbreviation.upper(), max_size)
        if key in self._logo_cache:
            return self._logo_cache[key]

        path = self.logo_directory / sport.upper() / f"{abbreviation.upper()}.png"
        if not path.is_file():
            self._logo_cache[key] = None
            return None
        try:
            logo = Image.open(path).convert("RGBA")
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            logo.thumbnail((max_size, max_size), resampling)
            self._logo_cache[key] = logo
            return logo
        except OSError:
            self._logo_cache[key] = None
            return None

    def _font(self, size: int):
        size = max(5, int(size))
        if size in self._font_cache:
            return self._font_cache[size]

        candidates = [self.font_path] if self.font_path else []
        candidates.append(Path("DejaVuSans.ttf"))
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                font = ImageFont.truetype(str(candidate), size)
                self._font_cache[size] = font
                return font
            except OSError:
                continue
        font = ImageFont.load_default()
        self._font_cache[size] = font
        return font

    def _fitted_font(self, text: str, max_width: int, preferred_size: int):
        draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        for size in range(max(5, preferred_size), 4, -1):
            font = self._font(size)
            if self._text_size(draw, text, font)[0] <= max_width:
                return font
        return self._font(5)

    @staticmethod
    def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
        try:
            box = draw.textbbox((0, 0), text, font=font)
            return box[2] - box[0], box[3] - box[1]
        except AttributeError:
            return draw.textsize(text, font=font)

    def _draw_centered(self, draw: ImageDraw.ImageDraw, text: str, y: int, font) -> None:
        width, _ = self._text_size(draw, text, font)
        self._draw_readable_text(draw, ((self.width - width) // 2, y), text, font)

    @staticmethod
    def _draw_readable_text(
        draw: ImageDraw.ImageDraw,
        xy: tuple[int, int],
        text: str,
        font,
    ) -> None:
        try:
            draw.text(xy, text, fill=WHITE, font=font, stroke_width=1, stroke_fill=BLACK)
        except TypeError:
            draw.text(xy, text, fill=WHITE, font=font)

    def _trim_to_width(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font,
        max_width: int,
    ) -> str:
        if self._text_size(draw, text, font)[0] <= max_width:
            return text
        trimmed = text
        while len(trimmed) > 2:
            trimmed = trimmed[:-1]
            candidate = trimmed + "."
            if self._text_size(draw, candidate, font)[0] <= max_width:
                return candidate
        return trimmed
