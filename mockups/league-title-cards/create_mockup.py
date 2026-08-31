"""Build exact 64x32 league title-card previews and a Windows mockup."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "sources"
CARD_SIZE = (64, 32)
PREVIEW_SCALE = 8
LOGO_MAX_SIZE = (60, 28)


def _font(size: int):
    for path in (
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ):
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_card(league: str) -> Image.Image:
    with Image.open(SOURCES / f"{league}.png") as source:
        logo = source.convert("RGBA")

    # Match the renderer's LED-safe treatment: crop transparent padding,
    # threshold alpha, resize with nearest-neighbor, and use integer centering.
    alpha = logo.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    visible_box = alpha.getbbox()
    if visible_box is None:
        raise ValueError(f"{league} logo has no visible pixels")
    logo.putalpha(alpha)
    logo = logo.crop(visible_box)

    max_width, max_height = LOGO_MAX_SIZE
    scale = min(max_width / logo.width, max_height / logo.height)
    target_size = (
        max(1, min(max_width, round(logo.width * scale))),
        max(1, min(max_height, round(logo.height * scale))),
    )
    logo = logo.resize(target_size, Image.Resampling.NEAREST)
    logo.putalpha(
        logo.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    )

    card = Image.new("RGB", CARD_SIZE, "black")
    origin = (
        (CARD_SIZE[0] - logo.width) // 2,
        (CARD_SIZE[1] - logo.height) // 2,
    )
    card.paste(logo, origin, logo)
    return card


def windows_mockup(previews: dict[str, Image.Image]) -> Image.Image:
    window_width = CARD_SIZE[0] * PREVIEW_SCALE + 24
    title_height = 44
    window_height = CARD_SIZE[1] * PREVIEW_SCALE + title_height + 24
    gap = 28
    margin = 34
    width = margin * 2 + window_width * 3 + gap * 2
    height = window_height + margin * 2

    mockup = Image.new("RGB", (width, height))
    pixels = mockup.load()
    for y in range(height):
        for x in range(width):
            # Restrained blue-black Windows desktop backdrop.
            distance = ((x - width * 0.55) ** 2 + (y - height * 0.44) ** 2) ** 0.5
            glow = max(0.0, 1.0 - distance / (width * 0.65))
            pixels[x, y] = (
                int(8 + 6 * glow),
                int(15 + 22 * glow),
                int(26 + 45 * glow),
            )

    draw = ImageDraw.Draw(mockup)
    title_font = _font(16)
    for index, league in enumerate(("NHL", "NFL", "MLB")):
        left = margin + index * (window_width + gap)
        top = margin
        right = left + window_width
        bottom = top + window_height

        draw.rounded_rectangle(
            (left, top, right, bottom),
            radius=9,
            fill=(31, 34, 39),
            outline=(93, 99, 108),
            width=1,
        )
        draw.rectangle(
            (left + 1, top + title_height, right - 1, bottom - 1),
            fill=(12, 12, 12),
        )
        draw.text(
            (left + 15, top + 11),
            "Sports Score Display Preview",
            font=title_font,
            fill=(245, 245, 245),
        )

        controls_y = top + title_height // 2
        draw.line((right - 104, controls_y, right - 91, controls_y), fill=(225, 225, 225))
        draw.rectangle(
            (right - 65, controls_y - 6, right - 53, controls_y + 6),
            outline=(225, 225, 225),
            width=1,
        )
        draw.line((right - 27, controls_y - 6, right - 15, controls_y + 6), fill=(225, 225, 225))
        draw.line((right - 15, controls_y - 6, right - 27, controls_y + 6), fill=(225, 225, 225))

        preview = previews[league]
        preview_left = left + 12
        preview_top = top + title_height + 12
        mockup.paste(preview, (preview_left, preview_top))

    return mockup


def main() -> None:
    previews: dict[str, Image.Image] = {}
    for league in ("NHL", "NFL", "MLB"):
        card = render_card(league)
        card.save(ROOT / f"{league}-title-card-64x32.png")
        preview = card.resize(
            (CARD_SIZE[0] * PREVIEW_SCALE, CARD_SIZE[1] * PREVIEW_SCALE),
            Image.Resampling.NEAREST,
        )
        preview.save(ROOT / f"{league}-windows-preview.png")
        previews[league] = preview

    windows_mockup(previews).save(ROOT / "league-title-cards-windows-mockup.png")


if __name__ == "__main__":
    main()
