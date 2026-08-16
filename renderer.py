"""Pixel-sharp Pillow renderer for sports score display cards."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from display_utils import format_status
from models import DisplayCard, Game


WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# These values are deliberately expressed against the physical 64x32 panel.
# The layout scales them for larger canvases while keeping all coordinates integral.
REFERENCE_WIDTH = 64
REFERENCE_HEIGHT = 32
HEADER_ROWS = 7
LIVE_FOOTER_ROWS = 6
LOGO_MAX_WIDTH = 36
LOGO_OUTER_CROP_NUMERATOR = 1
LOGO_OUTER_CROP_DENOMINATOR = 3
SCORE_SLOT_WIDTH = 15
SCORE_CENTER_OFFSET = 9
SCORE_MAX_HEIGHT = 10
LOGO_ALPHA_THRESHOLD = 128
TEXT_MASK_THRESHOLD = 128


@dataclass(frozen=True, slots=True)
class Region:
    """A half-open, integer pixel region."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def centered_origin(self, size: tuple[int, int]) -> tuple[int, int]:
        width, height = size
        return (
            self.left + (self.width - width) // 2,
            self.top + (self.height - height) // 2,
        )


@dataclass(frozen=True, slots=True)
class FrameLayout:
    """Vertical regions used by a single game card."""

    header: Region
    logos: Region
    scores: Region
    footer: Region | None
    logo_max_width: int


@dataclass(frozen=True, slots=True)
class _PixelFont:
    """Small deterministic bitmap font; every source bit maps to whole LEDs."""

    scale: int = 1
    letter_spacing: int = 1


# A compact variable-width 3x5 alphabet. M, N, and W are wider where necessary.
# It is intentionally code-owned so rendering is identical on Windows and the Pi.
_PIXEL_GLYPHS: dict[str, tuple[str, ...]] = {
    " ": ("0", "0", "0", "0", "0"),
    "A": ("010", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("10001", "11011", "10101", "10001", "10001"),
    "N": ("1001", "1101", "1011", "1001", "1001"),
    "O": ("010", "101", "101", "101", "010"),
    "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "111", "011"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("10001", "10001", "10101", "11011", "10001"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("110", "001", "010", "100", "111"),
    "3": ("110", "001", "010", "001", "110"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "110", "001", "110"),
    "6": ("011", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "110"),
    ":": ("0", "1", "0", "1", "0"),
    "/": ("001", "001", "010", "100", "100"),
    ".": ("0", "0", "0", "0", "1"),
    "-": ("000", "000", "111", "000", "000"),
    "&": ("0100", "1010", "0100", "1010", "0101"),
    "'": ("1", "1", "0", "0", "0"),
    "?": ("110", "001", "010", "000", "010"),
}


class ScoreRenderer:
    """Render frames with integer coordinates and LED-safe hard edges."""

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
        self._logo_cache: dict[tuple[str, str, int, int], Image.Image | None] = {}

    def render(self, card: DisplayCard) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), BLACK)
        draw = ImageDraw.Draw(image)

        if card.type in {"header", "message"}:
            self._render_title(draw, card.title)
        elif card.game is not None:
            self._render_game(image, draw, card.game)
        return image

    def _scaled_rows(self, reference_rows: int) -> int:
        return max(
            1,
            (self.height * reference_rows + REFERENCE_HEIGHT // 2)
            // REFERENCE_HEIGHT,
        )

    def _layout_for(self, game: Game) -> FrameLayout:
        header_height = min(self.height, self._scaled_rows(HEADER_ROWS))
        header = Region(0, 0, self.width, header_height)
        logos = Region(0, header.bottom, self.width, self.height)

        has_footer = game.status == "live" and (
            game.sport == "MLB" or game.sport == "NFL"
        )
        footer = None
        score_bottom = self.height
        if has_footer:
            footer_height = min(logos.height, self._scaled_rows(LIVE_FOOTER_ROWS))
            footer = Region(0, self.height - footer_height, self.width, self.height)
            score_bottom = footer.top

        scores = Region(0, header.bottom, self.width, max(header.bottom, score_bottom))
        logo_max_width = max(
            1,
            (self.width * LOGO_MAX_WIDTH + REFERENCE_WIDTH // 2) // REFERENCE_WIDTH,
        )
        return FrameLayout(header, logos, scores, footer, logo_max_width)

    def _render_title(self, draw: ImageDraw.ImageDraw, title: str) -> None:
        text = title.upper()
        region = Region(0, 0, self.width, self.height)
        font = self._fitted_font(
            text,
            max_width=max(1, self.width - 4),
            preferred_size=max(5, self.height // 2),
            max_height=max(1, self.height - 2),
        )
        self._draw_text_in_region(draw, text, region, font)

    def _render_game(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        game: Game,
    ) -> None:
        layout = self._layout_for(game)
        status = self._header_status(game)
        status_font = self._fitted_font(
            status,
            max_width=max(1, layout.header.width - 2),
            preferred_size=layout.header.height,
            max_height=layout.header.height,
        )

        self._draw_team_logo(
            image,
            draw,
            game.sport,
            game.away.abbreviation,
            "away",
            layout.logos,
            layout.logo_max_width,
        )
        self._draw_team_logo(
            image,
            draw,
            game.sport,
            game.home.abbreviation,
            "home",
            layout.logos,
            layout.logo_max_width,
        )

        # Text is drawn last and receives only a tight one-pixel black backplate.
        self._draw_text_in_region(draw, status, layout.header, status_font)

        if game.status in {"live", "final"}:
            self._draw_scores(draw, game, layout.scores)

        if game.status == "live" and layout.footer is not None:
            if game.sport == "NFL":
                self._draw_nfl_details(draw, game, layout.footer)
            elif game.sport == "MLB":
                self._draw_mlb_details(draw, game, layout.footer)

    def _header_status(self, game: Game) -> str:
        if game.status != "live":
            return format_status(game, self.timezone).upper()
        if game.sport == "NFL":
            return self._period_clock("Q", game.period, game.clock) or "LIVE"
        if game.sport == "NHL":
            return self._period_clock("P", game.period, game.clock) or "LIVE"
        if game.sport == "MLB":
            if game.inning_half == "top":
                half = "T"
            elif game.inning_half == "bottom":
                half = "B"
            else:
                half = ""
            return f"{half}{game.inning or ''}" or "LIVE"
        return "LIVE"

    def _draw_team_logo(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        sport: str,
        abbreviation: str,
        side: str,
        region: Region,
        max_width: int,
    ) -> tuple[int, int, int, int]:
        logo = self._load_logo(sport, abbreviation, max_width, region.height)
        if logo is not None:
            logo_width, logo_height = logo.size
            offscreen = max(
                1,
                (
                    logo_width * LOGO_OUTER_CROP_NUMERATOR
                    + LOGO_OUTER_CROP_DENOMINATOR // 2
                )
                // LOGO_OUTER_CROP_DENOMINATOR,
            )
            if side == "away":
                x = -offscreen
            else:
                x = self.width - (logo_width - offscreen)
            y = region.top + (region.height - logo_height) // 2
            image.paste(logo, (x, y), logo.getchannel("A"))
            return (x, y, x + logo_width, y + logo_height)

        # Keep the card useful if a local PNG is missing.
        label = abbreviation[:3].upper() or "???"
        font = self._fitted_font(
            label,
            max_width,
            max(5, region.height // 3),
            region.height,
        )
        text_width, text_height = self._text_size(draw, label, font)
        y = region.top + (region.height - text_height) // 2
        if side == "away":
            x = -1
        else:
            x = self.width - text_width + 1
        self._draw_readable_text(draw, (x, y), label, font)
        return (x, y, x + text_width, y + text_height)

    def _draw_scores(
        self,
        draw: ImageDraw.ImageDraw,
        game: Game,
        region: Region,
    ) -> None:
        away_score = "-" if game.away_score is None else str(game.away_score)
        home_score = "-" if game.home_score is None else str(game.home_score)

        slot_width = max(7, (self.width * SCORE_SLOT_WIDTH) // REFERENCE_WIDTH)
        center_offset = max(
            5,
            (self.width * SCORE_CENTER_OFFSET) // REFERENCE_WIDTH,
        )
        away_center = self.width // 2 - center_offset
        home_center = self.width // 2 + center_offset
        score_max_height = max(
            5,
            (self.height * SCORE_MAX_HEIGHT) // REFERENCE_HEIGHT,
        )

        score_font = self._fitted_font(
            max(away_score, home_score, key=len),
            max_width=slot_width,
            preferred_size=score_max_height,
            max_height=min(region.height, score_max_height),
        )
        away_box = self._draw_text_at_center(
            draw,
            away_score,
            (away_center, region.top + region.height // 2),
            score_font,
            backplate=True,
        )
        home_box = self._draw_text_at_center(
            draw,
            home_score,
            (home_center, region.top + region.height // 2),
            score_font,
            backplate=True,
        )

        marker = game.marker
        radius = max(1, self.height // 32)
        if marker == "away":
            dot_x = min(self.width - radius - 1, away_box[2] + radius + 1)
            dot_y = (away_box[1] + away_box[3]) // 2
            draw.ellipse(
                (dot_x - radius, dot_y - radius, dot_x + radius, dot_y + radius),
                fill=WHITE,
            )
        elif marker == "home":
            dot_x = max(radius, home_box[0] - radius - 1)
            dot_y = (home_box[1] + home_box[3]) // 2
            draw.ellipse(
                (dot_x - radius, dot_y - radius, dot_x + radius, dot_y + radius),
                fill=WHITE,
            )

    @staticmethod
    def _period_clock(prefix: str, period: int | None, clock: str | None) -> str:
        period_text = f"{prefix}{period}" if period is not None else prefix
        return " ".join(part for part in (period_text, clock or "") if part).upper()

    def _draw_nfl_details(
        self,
        draw: ImageDraw.ImageDraw,
        game: Game,
        region: Region,
    ) -> None:
        possession_team = None
        if game.possession == "away":
            possession_team = game.away.abbreviation
        elif game.possession == "home":
            possession_team = game.home.abbreviation

        down_distance = (game.down_distance or "").upper().replace(" ", "")
        field_position = (game.field_position or "").upper().replace(" ", "")
        parts = [part for part in (possession_team, down_distance, field_position) if part]
        detail = " ".join(parts)
        if possession_team and len(parts) == 1:
            detail = f"POSS {possession_team}"
        if not detail:
            return

        font = self._fitted_font(detail, max(1, region.width - 2), region.height, region.height)
        detail = self._trim_to_width(draw, detail, font, max(1, region.width - 2))
        self._draw_text_in_region(draw, detail, region, font, backplate=True)

    def _draw_mlb_details(
        self,
        draw: ImageDraw.ImageDraw,
        game: Game,
        region: Region,
    ) -> None:
        counts = []
        if game.balls is not None:
            counts.append(f"B{game.balls}")
        if game.strikes is not None:
            counts.append(f"S{game.strikes}")
        if game.outs is not None:
            counts.append(f"O{game.outs}")

        bases_width = max(9, (self.width * 10) // REFERENCE_WIDTH)
        if counts:
            count_region = Region(
                region.left + 1,
                region.top,
                region.right - bases_width - 1,
                region.bottom,
            )
            count_text = " ".join(counts)
            font = self._fitted_font(count_text, count_region.width, region.height, region.height)
            self._draw_text_in_region(draw, count_text, count_region, font, backplate=True)
            bases_center_x = region.right - bases_width // 2 - 1
        else:
            bases_center_x = region.left + region.width // 2

        radius = max(1, self.height // 32)
        gap = radius * 3
        draw.rectangle(
            (
                bases_center_x - gap - radius - 1,
                region.top,
                bases_center_x + gap + radius + 1,
                region.bottom - 1,
            ),
            fill=BLACK,
        )
        self._draw_bases(
            draw,
            bases_center_x,
            region.top + region.height // 2,
            game.bases,
        )

    def _draw_bases(
        self,
        draw: ImageDraw.ImageDraw,
        center_x: int,
        center_y: int,
        occupied: dict[str, bool],
    ) -> None:
        radius = max(1, self.height // 32)
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
                draw.line(points + [points[0]], fill=WHITE, width=1)

    def _load_logo(
        self,
        sport: str,
        abbreviation: str,
        max_width: int,
        max_height: int | None = None,
    ) -> Image.Image | None:
        max_height = max_width if max_height is None else max_height
        key = (sport.upper(), abbreviation.upper(), max_width, max_height)
        if key in self._logo_cache:
            return self._logo_cache[key]

        path = self.logo_directory / sport.upper() / f"{abbreviation.upper()}.png"
        if not path.is_file():
            self._logo_cache[key] = None
            return None
        try:
            with Image.open(path) as source:
                logo = source.convert("RGBA")

            # Remove source-canvas padding before sizing the visible mark.
            alpha = logo.getchannel("A").point(
                lambda value: 255 if value >= LOGO_ALPHA_THRESHOLD else 0
            )
            visible_box = alpha.getbbox()
            if visible_box is None:
                self._logo_cache[key] = None
                return None
            logo.putalpha(alpha)
            logo = logo.crop(visible_box)

            scale = min(max_width / logo.width, max_height / logo.height)
            target_size = (
                max(1, min(max_width, int(round(logo.width * scale)))),
                max(1, min(max_height, int(round(logo.height * scale)))),
            )
            nearest = getattr(Image, "Resampling", Image).NEAREST
            logo = logo.resize(target_size, nearest)

            # NEAREST does not introduce alpha values, but threshold once more so
            # source antialiasing can never become dim edge LEDs during paste.
            logo.putalpha(
                logo.getchannel("A").point(
                    lambda value: 255 if value >= LOGO_ALPHA_THRESHOLD else 0
                )
            )
            self._logo_cache[key] = logo
            return logo
        except (OSError, ValueError):
            self._logo_cache[key] = None
            return None

    def _font(self, size: int):
        size = max(1, int(size))
        if size in self._font_cache:
            return self._font_cache[size]

        if self.font_path is not None:
            try:
                font = ImageFont.truetype(str(self.font_path), size)
                self._font_cache[size] = font
                return font
            except OSError:
                pass

        font = _PixelFont(scale=max(1, size // 5))
        self._font_cache[size] = font
        return font

    def _fitted_font(
        self,
        text: str,
        max_width: int,
        preferred_size: int,
        max_height: int | None = None,
    ):
        for size in range(max(1, int(preferred_size)), 0, -1):
            font = self._font(size)
            width, height = self._text_size(None, text, font)
            if width <= max_width and (max_height is None or height <= max_height):
                return font
        return self._font(1)

    @classmethod
    def _rasterize_text(cls, text: str, font) -> Image.Image:
        text = str(text).upper()
        if isinstance(font, _PixelFont):
            patterns = [
                _PIXEL_GLYPHS.get(character, _PIXEL_GLYPHS["?"])
                for character in text
            ]
            if not patterns:
                return Image.new("1", (0, 0))
            logical_width = sum(len(pattern[0]) for pattern in patterns)
            logical_width += font.letter_spacing * max(0, len(patterns) - 1)
            mask = Image.new("1", (logical_width * font.scale, 5 * font.scale))
            pixels = ImageDraw.Draw(mask)
            logical_x = 0
            for pattern in patterns:
                for row, bits in enumerate(pattern):
                    for column, bit in enumerate(bits):
                        if bit == "1":
                            x = (logical_x + column) * font.scale
                            y = row * font.scale
                            pixels.rectangle(
                                (x, y, x + font.scale - 1, y + font.scale - 1),
                                fill=1,
                            )
                logical_x += len(pattern[0]) + font.letter_spacing
            visible_box = mask.getbbox()
            return mask.crop(visible_box) if visible_box else Image.new("1", (0, 0))

        try:
            box = font.getbbox(text)
        except AttributeError:
            probe = ImageDraw.Draw(Image.new("L", (1, 1)))
            box = probe.textbbox((0, 0), text, font=font)
        width = max(1, box[2] - box[0])
        height = max(1, box[3] - box[1])
        gray = Image.new("L", (width + 4, height + 4))
        gray_draw = ImageDraw.Draw(gray)
        gray_draw.text((2 - box[0], 2 - box[1]), text, fill=255, font=font)
        mask = gray.point(
            lambda value: 255 if value >= TEXT_MASK_THRESHOLD else 0
        ).convert("1")
        visible_box = mask.getbbox()
        return mask.crop(visible_box) if visible_box else Image.new("1", (0, 0))

    @classmethod
    def _text_size(cls, draw, text: str, font) -> tuple[int, int]:
        del draw
        return cls._rasterize_text(text, font).size

    def _draw_centered(self, draw: ImageDraw.ImageDraw, text: str, y: int, font) -> None:
        mask = self._rasterize_text(text, font)
        self._draw_mask(draw, ((self.width - mask.width) // 2, int(y)), mask)

    def _draw_text_in_region(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        region: Region,
        font,
        backplate: bool = False,
    ) -> tuple[int, int, int, int]:
        mask = self._rasterize_text(text, font)
        xy = region.centered_origin(mask.size)
        return self._draw_mask(draw, xy, mask, backplate=backplate)

    def _draw_text_at_center(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        center: tuple[int, int],
        font,
        backplate: bool = False,
    ) -> tuple[int, int, int, int]:
        mask = self._rasterize_text(text, font)
        xy = (center[0] - mask.width // 2, center[1] - mask.height // 2)
        return self._draw_mask(draw, xy, mask, backplate=backplate)

    @staticmethod
    def _draw_mask(
        draw: ImageDraw.ImageDraw,
        xy: tuple[int, int],
        mask: Image.Image,
        fill: tuple[int, int, int] = WHITE,
        backplate: bool = False,
    ) -> tuple[int, int, int, int]:
        x, y = int(xy[0]), int(xy[1])
        right, bottom = x + mask.width, y + mask.height
        if backplate and mask.width and mask.height:
            draw.rectangle((x - 1, y - 1, right, bottom), fill=BLACK)
        if mask.width and mask.height:
            draw.bitmap((x, y), mask, fill=fill)
        return (x, y, right, bottom)

    @classmethod
    def _draw_readable_text(
        cls,
        draw: ImageDraw.ImageDraw,
        xy: tuple[int, int],
        text: str,
        font,
    ) -> None:
        cls._draw_mask(draw, xy, cls._rasterize_text(text, font))

    def _trim_to_width(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font,
        max_width: int,
    ) -> str:
        if self._text_size(draw, text, font)[0] <= max_width:
            return text
        trimmed = text.rstrip()
        while len(trimmed) > 1:
            trimmed = trimmed[:-1].rstrip()
            candidate = trimmed + "."
            if self._text_size(draw, candidate, font)[0] <= max_width:
                return candidate
        return trimmed
