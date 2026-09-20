"""Pixel-sharp Pillow renderer for sports score display cards."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from display_utils import format_status
from models import DisplayCard, Game, RichTextCard, RichTextLine, RichTextSpan


WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
TEAM_LABEL_COLOR = (255, 196, 0)

# These values are deliberately expressed against the physical 64x32 panel.
# The layout scales them for larger canvases while keeping all coordinates integral.
REFERENCE_WIDTH = 64
REFERENCE_HEIGHT = 32
HEADER_ROWS = 7
LOGO_MAX_WIDTH = 36
LOGO_CENTER_GAP = 12
MAX_LOGO_OUTER_CROP_DENOMINATOR = 3
SCORE_SLOT_WIDTH = 15
SCORE_CENTER_OFFSET = 11
SCORE_MAX_HEIGHT = 10
LOGO_ALPHA_THRESHOLD = 128
TEXT_MASK_THRESHOLD = 128
LEAGUE_LOGO_MAX_WIDTH = 60
LEAGUE_LOGO_MAX_HEIGHT = 28


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
    game_type: Region | None
    logos: Region
    scores: Region
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

        if card.type == "header":
            self._render_league_header(image, draw, card.title)
        elif card.type == "message":
            self._render_title(draw, card.title)
        elif card.type == "rich_text" and card.rich_text is not None:
            self._render_rich_text_card(draw, card.rich_text)
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
        game_type = None
        scores = logos
        if game.game_type_label:
            game_type_height = min(logos.height, self._scaled_rows(6))
            game_type = Region(0, logos.top, self.width, logos.top + game_type_height)
            scores = Region(0, game_type.bottom, self.width, self.height)
        logo_max_width = max(
            1,
            (self.width * LOGO_MAX_WIDTH + REFERENCE_WIDTH // 2) // REFERENCE_WIDTH,
        )
        return FrameLayout(header, game_type, logos, scores, logo_max_width)

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

    def _render_rich_text_card(
        self,
        draw: ImageDraw.ImageDraw,
        card: RichTextCard,
    ) -> None:
        """Render a compact title and up to four independently colored lines."""
        horizontal_inset = max(1, self.width // REFERENCE_WIDTH)
        title_bottom = min(self.height, self._scaled_rows(6))
        title_region = Region(
            horizontal_inset,
            0,
            self.width - horizontal_inset,
            title_bottom,
        )
        title = card.title.upper()
        title_font = self._fitted_font(
            title,
            max_width=title_region.width,
            preferred_size=max(5, self._scaled_rows(5)),
            max_height=title_region.height,
        )
        title_mask = self._rasterize_text(title, title_font)
        self._draw_mask(
            draw,
            title_region.centered_origin(title_mask.size),
            title_mask,
            fill=card.title_color,
        )

        divider_y = min(self.height - 1, self._scaled_rows(6))
        draw.line(
            (
                horizontal_inset,
                divider_y,
                self.width - horizontal_inset - 1,
                divider_y,
            ),
            fill=card.title_color,
        )

        lines = card.lines[:4]
        if not lines:
            return
        body_top = min(self.height, self._scaled_rows(8))
        body_height = max(0, self.height - body_top)
        for index, line in enumerate(lines):
            region = Region(
                horizontal_inset,
                body_top + body_height * index // len(lines),
                self.width - horizontal_inset,
                body_top + body_height * (index + 1) // len(lines),
            )
            self._draw_rich_text_line(draw, line, region)

    def _draw_rich_text_line(
        self,
        draw: ImageDraw.ImageDraw,
        line: RichTextLine,
        region: Region,
    ) -> None:
        preferred_size = min(region.height, max(5, self._scaled_rows(5)))
        font = self._font(preferred_size)
        if line.column_starts:
            self._draw_rich_text_columns(draw, line, region, font)
            return

        gap = max(1, self.width // REFERENCE_WIDTH)
        spans = self._fit_rich_text_spans(line.spans, font, region.width, gap)
        masks = [self._rasterize_text(span.text, font) for span in spans]
        width = sum(mask.width for mask in masks) + gap * max(0, len(masks) - 1)
        if line.alignment == "left":
            x = region.left
        elif line.alignment == "right":
            x = region.right - width
        else:
            x = region.left + (region.width - width) // 2

        for span, mask in zip(spans, masks):
            y = region.top + (region.height - mask.height) // 2
            self._draw_mask(draw, (x, y), mask, fill=span.color)
            x += mask.width + gap

    def _draw_rich_text_columns(
        self,
        draw: ImageDraw.ImageDraw,
        line: RichTextLine,
        region: Region,
        font,
    ) -> None:
        if len(line.column_starts) != len(line.spans):
            raise ValueError("column_starts must contain one position per span")
        alignments = line.column_alignments or ("left",) * len(line.spans)
        if len(alignments) != len(line.spans):
            raise ValueError("column_alignments must contain one value per span")

        starts = [
            region.left + self.width * start // REFERENCE_WIDTH
            for start in line.column_starts
        ]
        for index, (span, alignment) in enumerate(zip(line.spans, alignments)):
            cell = Region(
                starts[index],
                region.top,
                starts[index + 1] if index + 1 < len(starts) else region.right,
                region.bottom,
            )
            fitted = self._fit_rich_text_spans((span,), font, cell.width, 0)
            if not fitted:
                continue
            fitted_span = fitted[0]
            mask = self._rasterize_text(fitted_span.text, font)
            if alignment == "right":
                x = cell.right - mask.width
            elif alignment == "center":
                x = cell.left + (cell.width - mask.width) // 2
            else:
                x = cell.left
            y = cell.top + (cell.height - mask.height) // 2
            self._draw_mask(draw, (x, y), mask, fill=fitted_span.color)

    def _fit_rich_text_spans(
        self,
        spans: tuple[RichTextSpan, ...],
        font,
        max_width: int,
        gap: int,
    ) -> list[RichTextSpan]:
        fitted = [
            RichTextSpan(span.text.strip(), span.color, span.shrink)
            for span in spans
            if span.text.strip()
        ]

        def line_width() -> int:
            return sum(
                self._text_size(None, span.text, font)[0] for span in fitted
            ) + gap * max(0, len(fitted) - 1)

        while line_width() > max_width:
            candidates = [
                index
                for index, span in enumerate(fitted)
                if span.shrink and len(span.text.rstrip(".")) > 1
            ]
            if not candidates:
                break
            index = max(candidates, key=lambda item: len(fitted[item].text))
            span = fitted[index]
            shortened = span.text.rstrip(".")[:-1].rstrip()
            if len(shortened) > 1:
                shortened += "."
            fitted[index] = RichTextSpan(shortened, span.color, span.shrink)
        return fitted

    def _render_league_header(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        title: str,
    ) -> None:
        league = title.upper()
        max_width = max(
            1,
            (self.width * LEAGUE_LOGO_MAX_WIDTH + REFERENCE_WIDTH // 2)
            // REFERENCE_WIDTH,
        )
        max_height = self._scaled_rows(LEAGUE_LOGO_MAX_HEIGHT)
        logo = self._load_logo(
            "LEAGUES",
            league,
            max_width,
            max_height,
        )
        if logo is None:
            self._render_title(draw, title)
            return

        region = Region(0, 0, self.width, self.height)
        image.paste(logo, region.centered_origin(logo.size), logo)

    def _render_game(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        game: Game,
    ) -> None:
        layout = self._layout_for(game)

        # Size each mark independently, then make room between the two visible
        # marks.  The only allowed crop is on the panel's outside edges.
        away_logo = self._load_logo(
            game.sport,
            game.away.abbreviation,
            layout.logo_max_width,
            layout.logos.height,
        )
        home_logo = self._load_logo(
            game.sport,
            game.home.abbreviation,
            layout.logo_max_width,
            layout.logos.height,
        )
        away_crop, home_crop = self._paired_logo_outer_crops(away_logo, home_logo)

        self._draw_team_logo(
            image,
            draw,
            game.sport,
            game.away.abbreviation,
            "away",
            layout.logos,
            layout.logo_max_width,
            logo=away_logo,
            outer_crop=away_crop,
        )
        self._draw_team_logo(
            image,
            draw,
            game.sport,
            game.home.abbreviation,
            "home",
            layout.logos,
            layout.logo_max_width,
            logo=home_logo,
            outer_crop=home_crop,
        )

        if game.status == "live" and game.sport == "MLB":
            self._draw_bases(draw, *self._mlb_bases_center(layout), game.bases)

        if game.status in {"live", "final"}:
            self._draw_scores(draw, game, layout.scores)
            separator_font = self._font(max(5, self.height // 6))
            self._draw_text_at_center(
                draw,
                "-",
                (
                    self.width // 2,
                    layout.scores.top + layout.scores.height // 2,
                ),
                separator_font,
                backplate=True,
            )
        elif game.status == "scheduled":
            self._draw_upcoming_marker(draw, layout.scores)

        if layout.game_type is not None:
            self._draw_game_type(draw, game.game_type_label or "", layout.game_type)

        # The header is always drawn last and never overlaps the logo region.
        self._draw_game_header(draw, game, layout.header)

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

    def _draw_game_type(
        self,
        draw: ImageDraw.ImageDraw,
        label: str,
        region: Region,
    ) -> None:
        """Draw the compact non-regular-season marker above scores or @."""
        text = label.upper()
        font = self._fitted_font(
            text,
            max_width=max(1, self.width - 8),
            preferred_size=region.height,
            max_height=region.height,
        )
        self._draw_text_in_region(draw, text, region, font, backplate=True)

    def _draw_team_logo(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        sport: str,
        abbreviation: str,
        side: str,
        region: Region,
        max_width: int,
        *,
        logo: Image.Image | None = None,
        outer_crop: int = 0,
    ) -> tuple[int, int, int, int]:
        if logo is None:
            logo = self._load_logo(sport, abbreviation, max_width, region.height)
        if logo is not None:
            logo_width, logo_height = logo.size
            if side == "away":
                x = -max(0, outer_crop)
            else:
                x = self.width - logo_width + max(0, outer_crop)
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
            x = 0
        else:
            x = self.width - text_width
        self._draw_readable_text(draw, (x, y), label, font)
        return (x, y, x + text_width, y + text_height)

    def _paired_logo_outer_crops(
        self,
        away_logo: Image.Image | None,
        home_logo: Image.Image | None,
    ) -> tuple[int, int]:
        """Return outside-edge crops which reserve an intentional center gap."""
        if away_logo is None or home_logo is None:
            return (0, 0)

        away_width = away_logo.width
        home_width = home_logo.width
        center_gap = min(
            self.width,
            max(1, (self.width * LOGO_CENTER_GAP) // REFERENCE_WIDTH),
        )
        overflow = max(0, away_width + home_width - (self.width - center_gap))
        if not overflow:
            return (0, 0)

        maximum_away_crop = away_width // MAX_LOGO_OUTER_CROP_DENOMINATOR
        maximum_home_crop = home_width // MAX_LOGO_OUTER_CROP_DENOMINATOR
        total_width = away_width + home_width
        away_crop = min(
            maximum_away_crop,
            (overflow * away_width + total_width // 2) // total_width,
        )
        home_crop = min(maximum_home_crop, overflow - away_crop)

        # A rounding or per-logo crop limit can leave a few columns unassigned.
        # Allocate those columns where capacity remains before reducing the gap.
        remaining = overflow - away_crop - home_crop
        if remaining:
            extra_away = min(remaining, maximum_away_crop - away_crop)
            away_crop += extra_away
            remaining -= extra_away
        if remaining:
            home_crop += min(remaining, maximum_home_crop - home_crop)

        return (away_crop, home_crop)

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
        away_center, home_center = self._score_centers(center_offset)
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
            dot_x = max(radius, away_box[0] - radius - 1)
            dot_y = (away_box[1] + away_box[3]) // 2
            draw.rectangle(
                (
                    dot_x - radius - 1,
                    dot_y - radius - 1,
                    dot_x + radius + 1,
                    dot_y + radius + 1,
                ),
                fill=BLACK,
            )
            draw.ellipse(
                (dot_x - radius, dot_y - radius, dot_x + radius, dot_y + radius),
                fill=WHITE,
            )
        elif marker == "home":
            dot_x = min(self.width - radius - 1, home_box[2] + radius + 1)
            dot_y = (home_box[1] + home_box[3]) // 2
            draw.rectangle(
                (
                    dot_x - radius - 1,
                    dot_y - radius - 1,
                    dot_x + radius + 1,
                    dot_y + radius + 1,
                ),
                fill=BLACK,
            )
            draw.ellipse(
                (dot_x - radius, dot_y - radius, dot_x + radius, dot_y + radius),
                fill=WHITE,
            )

    def _score_centers(self, center_offset: int | None = None) -> tuple[int, int]:
        """Use one score geometry for every sport, including football."""
        if center_offset is None:
            center_offset = max(
                5,
                (self.width * SCORE_CENTER_OFFSET) // REFERENCE_WIDTH,
            )
        return (self.width // 2 - center_offset, self.width // 2 + center_offset)

    @staticmethod
    def _period_clock(prefix: str, period: int | None, clock: str | None) -> str:
        period_text = f"{prefix}{period}" if period is not None else prefix
        return " ".join(part for part in (period_text, clock or "") if part).upper()

    def _draw_game_header(
        self,
        draw: ImageDraw.ImageDraw,
        game: Game,
        region: Region,
    ) -> None:
        label_font = self._font(max(5, self._scaled_rows(5)))
        away_label = self._rasterize_text("A", label_font)
        home_label = self._rasterize_text("H", label_font)
        label_y = region.top + (region.height - away_label.height) // 2
        self._draw_mask(
            draw,
            (region.left + 1, label_y),
            away_label,
            fill=TEAM_LABEL_COLOR,
        )
        self._draw_mask(
            draw,
            (region.right - home_label.width - 1, label_y),
            home_label,
            fill=TEAM_LABEL_COLOR,
        )

        label_inset = max(5, (self.width * 5) // REFERENCE_WIDTH)
        content_region = Region(
            region.left + label_inset,
            region.top,
            region.right - label_inset,
            region.bottom,
        )
        if game.status == "live" and game.sport == "MLB":
            self._draw_mlb_header(draw, game, content_region)
            return

        if game.status == "live" and game.sport == "NFL":
            status = self._nfl_header_text(game)
        else:
            status = self._header_status(game)
        font = self._fitted_font(
            status,
            max_width=content_region.width,
            preferred_size=content_region.height,
            max_height=content_region.height,
        )
        status = self._trim_to_width(draw, status, font, content_region.width)
        self._draw_text_in_region(draw, status, content_region, font)

    def _nfl_header_text(self, game: Game) -> str:
        clock = (game.clock or "").upper()
        if clock.startswith("0"):
            clock = clock[1:]
        status = self._period_clock("Q", game.period, clock)

        down_distance = (game.down_distance or "").upper().replace(" ", "")
        for ordinal in ("ST", "ND", "RD", "TH"):
            down_distance = down_distance.replace(ordinal, "")

        compact_field = (game.field_position or "").upper().replace(" ", "")
        letters = "".join(character for character in compact_field if character.isalpha())
        digits = "".join(character for character in compact_field if character.isdigit())
        if len(letters) > 1 and digits:
            compact_field = letters[0] + digits

        return " ".join(
            part for part in (status, down_distance, compact_field) if part
        )

    def _draw_mlb_header(
        self,
        draw: ImageDraw.ImageDraw,
        game: Game,
        region: Region,
    ) -> None:
        inning = self._header_status(game)
        balls = f"B{game.balls}" if game.balls is not None else ""
        strikes = f"S{game.strikes}" if game.strikes is not None else ""
        outs = f"O{game.outs}" if game.outs is not None else ""
        status = " ".join(
            part for part in (inning, balls, strikes, outs) if part
        )
        font = self._fitted_font(
            status,
            max_width=region.width,
            preferred_size=region.height,
            max_height=region.height,
        )
        # Keep the order stable while centering the complete status as one unit.
        self._draw_text_in_region(draw, status, region, font)

    def _mlb_bases_center(self, layout: FrameLayout) -> tuple[int, int]:
        """Put the diamond below the header but above the score baseline."""
        offset = max(self._scaled_rows(4), layout.logos.height // 6)
        if layout.game_type is not None:
            return (
                self.width // 2,
                min(layout.scores.bottom - 1, layout.scores.top + offset // 2),
            )
        return (self.width // 2, min(layout.logos.bottom - 1, layout.logos.top + offset))

    def _draw_upcoming_marker(
        self,
        draw: ImageDraw.ImageDraw,
        region: Region,
    ) -> None:
        pattern = (
            "0111110",
            "1000001",
            "1011101",
            "1010101",
            "1011111",
            "1000000",
            "0111110",
        )
        scale = max(1, self.height // REFERENCE_HEIGHT)
        mask = self._pattern_mask(pattern, scale)
        self._draw_mask(
            draw,
            region.centered_origin(mask.size),
            mask,
            backplate=True,
        )

    @staticmethod
    def _pattern_mask(pattern: tuple[str, ...], scale: int = 1) -> Image.Image:
        width = len(pattern[0]) * scale
        height = len(pattern) * scale
        mask = Image.new("1", (width, height))
        mask_draw = ImageDraw.Draw(mask)
        for row, bits in enumerate(pattern):
            for column, bit in enumerate(bits):
                if bit == "1":
                    x = column * scale
                    y = row * scale
                    mask_draw.rectangle(
                        (x, y, x + scale - 1, y + scale - 1),
                        fill=1,
                    )
        return mask

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
        horizontal: str = "center",
    ) -> tuple[int, int, int, int]:
        mask = self._rasterize_text(text, font)
        x, y = region.centered_origin(mask.size)
        if horizontal == "left":
            x = region.left
        elif horizontal == "right":
            x = region.right - mask.width
        elif horizontal != "center":
            raise ValueError("horizontal must be 'left', 'center', or 'right'")
        xy = (x, y)
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
