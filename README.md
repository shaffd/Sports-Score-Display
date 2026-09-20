# Sports Score Display

A configurable Python scoreboard for NHL, NFL, and MLB games. The application
fetches recent and upcoming games, renders small Pillow images, and sends those
images either to a Tkinter development preview or an HZeller HUB75 LED matrix.

## What it displays

- Games whose scheduled start was within the previous 24 hours.
- Games scheduled within the next 24 hours.
- Live scores refreshed independently from the card rotation interval.
- Centered NHL, NFL, and MLB league marks on the league title cards.
- Live Yankees, Rangers, and Lions games dwell for three minutes on each pass;
  every other card uses the normal five-second dwell.
- Final scores with `FINAL MM/DD`.
- Scheduled games with Eastern time and `MM/DD`.
- Compact non-regular-season markers: `PRE` for preseason and API-derived
  playoff rounds such as `ALDS`, `R2`, `SCF`, and `AFC WC`.
- Prominent away and home logos, labeled `A`/`H`, with a clear center gap.
  Only their outer edges may be cropped, never by more than one-third.
- Final and live scores separated by a short dash; upcoming matchups use `@`.
- NFL quarter, clock, and possession marker.
- NHL period and clock.
- MLB inning half, balls, strikes, and outs run left-to-right in the header;
  the occupied-base diamond sits below that line and above the scores.

Live league details share the top status row so they never cover the logo area.

The time window is measured from each game's scheduled start because the three
APIs do not expose a consistent game-finished timestamp.

## Architecture

```text
Sports APIs -> data_fetcher.py -> normalized Game objects
            -> display_utils.py -> rotating DisplayCard list
            -> renderer.py      -> Pillow RGB frame
            -> outputs.py       -> Tkinter preview or HZeller rgbmatrix
```

Important files:

- `config.py`: loads and validates `config.json`.
- `models.py`: shared `Team`, `Game`, and `DisplayCard` dataclasses.
- `data_fetcher.py`: league API clients and normalization.
- `display_utils.py`: 24-hour/current-day selection and status text.
- `renderer.py`: integer-region, pixel-sharp Pillow layout.
- `outputs.py`: optional preview and physical matrix adapters.
- `main.py`: refresh and card-rotation loop.

## Laptop development preview

Python 3.10 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

Tkinter is required only for `output: "preview"`. It is deliberately imported
only when preview mode starts, so it is not required by a headless matrix setup.
The preview enlarges the logical frame with nearest-neighbor scaling, so every
64x32 source pixel appears as a sharp square instead of being smoothed.

## Raspberry Pi Zero 2 W and HZeller

The current HZeller project supports the Pi Zero 2 W and provides Python
bindings. `setup_pi.sh` installs its build dependencies and installs the binding
directly from the official repository.

```bash
bash setup_pi.sh
sudo .venv/bin/python main.py --output matrix
```

The HZeller driver is C++ internally, but this project remains Python. Pillow
builds each complete frame and the binding's native `SetImage()` operation sends
it efficiently to the matrix.

The driver generally needs root privileges for accurate timing. Read HZeller's
wiring and safety documentation before connecting or powering a panel:
https://github.com/hzeller/rpi-rgb-led-matrix

## Configuration

Edit `config.json`. Preview dimensions and physical matrix parameters are kept
separate so a laptop preview can model any future display.

```json
{
  "timezone": "America/New_York",
  "lookback_hours": 24,
  "refresh_seconds": 30,
  "card_seconds": 5,
  "favorite_live_card_seconds": 180,
  "favorite_teams": {
    "MLB": ["NYY"],
    "NHL": ["NYR"],
    "NFL": ["DET"]
  },
  "output": "preview",
  "canvas": {"width": 64, "height": 32},
  "matrix": {
    "rows": 32,
    "cols": 64,
    "chain_length": 1,
    "parallel": 1,
    "hardware_mapping": "adafruit-hat",
    "gpio_slowdown": 1
  }
}
```

For a different panel, update `rows`, `cols`, `chain_length`, and `parallel`.
The matrix adapter reports the actual canvas dimensions from HZeller and the
renderer automatically uses them. Other exposed settings cover brightness,
color order, PWM, scan mode, multiplexing, row addressing, panel chipset, and
pixel mapping.

`hardware_mapping` is set to `adafruit-hat` for the Adafruit RGB Matrix HAT or
Bonnet's stock wiring. HZeller documents `adafruit-hat-pwm` only for boards with
the optional GPIO 4-to-18 anti-flicker hardware modification.

Favorite teams are configured by league and abbreviation so an abbreviation
used in another sport cannot accidentally receive the longer dwell. The live
favorite card is re-rendered after every data refresh while its three-minute
dwell remains active, keeping NHL and NFL clocks and scores current in both
preview and matrix output modes.

## Fantasy football cards

The `fantasy_football` configuration lists the players to follow. Each entry
uses a stable local `player_id`, first and last name (used to match the NFL
box score), position, and NFL team abbreviation. The same configured roster is
shown for either fantasy platform because this display presents official game
statistics rather than platform-specific fantasy points.

Fantasy cards automatically enter the rotation every Thursday at 12:00 PM
through Tuesday at 11:59 PM in the configured timezone. A `FANTASY FOOTBALL`
title card precedes the player cards. The app fetches ESPN's NFL scoreboard and
per-game box-score data during that window, retaining scheduled player cards
before kickoff and refreshing passing, rushing, receiving, fumble, and kicking
statistics as games progress.

On a 64x32 panel, each card uses a position-aware layout: quarterbacks show
passing and rushing; running backs, receivers, and tight ends show rushing,
receiving, and fumbles; kickers show field goals, extra points, and points.
Names display as a first initial plus full last name and are cropped only when
the panel requires it.

## Team logos

Add transparent PNGs using uppercase team abbreviations:

```text
Logos/MLB/NYY.png
Logos/NFL/DET.png
Logos/NHL/NYR.png
```

The renderer trims transparent source padding, scales with nearest-neighbor
sampling, and converts logo alpha to fully transparent or fully opaque pixels.
It reserves a center gap between each pair of scaled marks. When a large pair
needs more room, it crops only their outer edges, by no more than one-third. If
a PNG is missing, the team abbreviation is shown instead.

League title-card marks are stored in `Logos/LEAGUES/`. They are centered on the
full canvas, preserve their source proportions, and fit within 60x28 pixels at
the reference 64x32 resolution. If a league mark is missing, the original text
title is shown as a fallback.

## 64x32 pixel layout

The renderer treats the physical matrix as the source canvas; it does not draw a
large antialiased frame and shrink it afterward. Text uses a built-in 3x5 bitmap
alphabet by default. A configured TrueType font is still accepted, but its mask
is thresholded before compositing so edge LEDs remain fully on or off.

The main physical-panel tuning constants are near the top of `renderer.py`:

- `HEADER_ROWS`: height of the centered game-status region.
- `LOGO_MAX_WIDTH`: maximum logo width at 64 columns.
- `LOGO_CENTER_GAP`: minimum clear space between visible logo marks at 64 columns.
- `SCORE_SLOT_WIDTH`, `SCORE_CENTER_OFFSET`, and `SCORE_MAX_HEIGHT`: score anchors.
- `LOGO_ALPHA_THRESHOLD`: cutoff between transparent and fully opaque logo pixels.
- `TEXT_MASK_THRESHOLD`: cutoff used only when a custom TrueType font is configured.

## MLB data fix

MLB schedule records now retain `gameDate` as `start_time_utc`, so scheduled
cards no longer lose their start time. Live games are enriched from MLB's
current `/api/v1.1/game/{gamePk}/feed/live` endpoint, which supplies the inning,
bases, current matchup, and updated runs.

## Tests

Run the offline unit tests after installing `requirements.txt`:

```bash
python -m unittest discover -s tests -v
```

The tests use small fixture dictionaries and do not call the sports APIs.
