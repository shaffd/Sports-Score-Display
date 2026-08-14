# Sports Score Display

A configurable Python scoreboard for NHL, NFL, and MLB games. The application
fetches recent and upcoming games, renders small Pillow images, and sends those
images either to a Tkinter development preview or an HZeller HUB75 LED matrix.

## What it displays

- Games whose scheduled start was within the previous 24 hours.
- Games scheduled later in the current Eastern calendar day.
- Live scores refreshed independently from the card rotation interval.
- Live Yankees, Rangers, and Lions games dwell for three minutes on each pass;
  every other card uses the normal five-second dwell.
- Final scores with `FINAL MM/DD`.
- Scheduled games with Eastern time and `MM/DD`.
- Away logo on the left and home logo on the right.
- Final and live scores beside the respective logos.
- NFL quarter, clock, and possession marker.
- NHL period and clock.
- MLB inning half, at-bat marker, and occupied bases. Pitcher and batter are
  also shown when the configured display height has room for them.

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
- `renderer.py`: resolution-independent Pillow layout.
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

## Team logos

Add transparent PNGs using uppercase team abbreviations:

```text
Logos/MLB/NYY.png
Logos/NFL/DET.png
Logos/NHL/NYR.png
```

The renderer places the away logo with its left third outside the canvas. The
home logo is placed symmetrically with its right third outside the canvas. If a
PNG is missing, the team abbreviation is shown instead.

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
