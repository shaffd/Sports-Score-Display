"""Download and normalize logos for every team in the configured school leagues."""

from __future__ import annotations

from collections import deque
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config import load_config  # noqa: E402
from myhsal import MyhsalClient  # noqa: E402


def _clear_edge_white(source: Image.Image) -> Image.Image:
    """Remove only near-white background pixels connected to an image edge."""
    image = source.convert("RGBA")
    pixels = image.load()
    width, height = image.size
    pending = deque(
        [(x, 0) for x in range(width)]
        + [(x, height - 1) for x in range(width)]
        + [(0, y) for y in range(height)]
        + [(width - 1, y) for y in range(height)]
    )
    visited: set[tuple[int, int]] = set()
    while pending:
        x, y = pending.popleft()
        if (x, y) in visited:
            continue
        visited.add((x, y))
        red, green, blue, alpha = pixels[x, y]
        if alpha == 0:
            continue
        if min(red, green, blue) < 235:
            continue
        pixels[x, y] = (red, green, blue, 0)
        if x:
            pending.append((x - 1, y))
        if x + 1 < width:
            pending.append((x + 1, y))
        if y:
            pending.append((x, y - 1))
        if y + 1 < height:
            pending.append((x, y + 1))
    return image


def main() -> int:
    config = load_config(PROJECT_ROOT / "config.json")
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "text/html,image/*",
            "User-Agent": "Sports-Score-Display/1.0",
        }
    )
    client = MyhsalClient(
        config.myhsal.school_slug,
        timezone_name=config.timezone,
        timeout=config.api_timeout_seconds,
        session=session,
    )
    output_dir = config.assets.logo_directory / "MYHSAL"
    output_dir.mkdir(parents=True, exist_ok=True)

    logos = client.discover_team_logos()
    failures: list[str] = []
    for key, url in sorted(logos.items()):
        try:
            response = session.get(url, timeout=config.api_timeout_seconds)
            response.raise_for_status()
            with Image.open(BytesIO(response.content)) as source:
                _clear_edge_white(source).save(output_dir / f"{key}.png")
            print(f"{key}: {url}")
        except (OSError, requests.RequestException) as exc:
            failures.append(f"{key}: {exc}")

    print(f"Downloaded {len(logos) - len(failures)} of {len(logos)} logos")
    if failures:
        print("Failures:")
        print("\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
