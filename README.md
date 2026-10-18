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
- MLB and NHL playoff cards flank that round marker with the current away-team
  and home-team series wins. NFL playoff cards keep the round marker alone.
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

## Raspberry Pi 3 Model A+, Zero 2 W, and HZeller

The current HZeller project supports both the Pi 3 Model A+ and Pi Zero 2 W and
provides Python bindings. `setup_pi.sh` installs its build dependencies and
installs the binding directly from the official repository. The Pi 3 Model A+
uses the same 40-pin GPIO interface for the matrix adapter and also adds 5 GHz
Wi-Fi support. Its larger board, full-size HDMI port, and 2.5 A power
recommendation may require different enclosure and cable planning.

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

## Friend-friendly Wi-Fi setup

`setup_pi.sh` also installs and starts a local GameBlink Wi-Fi setup service.
The setup page is stored and served by the Raspberry Pi itself; it does not use
paid hosting or require Internet access.

At boot, a new display with no saved home Wi-Fi profiles waits 30 seconds before
starting setup mode. If that fails, the display rotates these instructions:

```text
WIFI SETUP
JOIN
GameBlink-XXXX
PASSWORD
GAMEBLINK
OPEN
10.42.0.1
```

The four-character suffix comes from that Pi's Wi-Fi address, so nearby
GameBlink displays remain distinguishable. On a phone or laptop:

1. Join the displayed `GameBlink-XXXX` network using password `GAMEBLINK`.
2. Open `http://10.42.0.1` if the setup page does not appear automatically.
3. Select the home network, enter its password, and choose **Connect GameBlink**.

The phone disconnects from the temporary network while the Pi tries the new
credentials. A successful connection is saved by NetworkManager and reconnects
automatically on later boots. If the password is wrong or the network cannot be
reached, the temporary GameBlink network and setup page return automatically.
If at least one home Wi-Fi profile has previously been saved, GameBlink gives
NetworkManager three minutes to recover before returning to setup mode. While
setup mode is active it retries saved networks every minute, allowing it to
recover from a temporary router outage without user action. Before handing a
tested unit to a friend, remove your own saved Wi-Fi profile so their first boot
uses the shorter 30-second path.

The portal supports ordinary open and WPA/WPA2/WPA3 personal networks. It does
not configure enterprise Wi-Fi networks that require a username, certificate,
or browser sign-in. The Pi Zero 2 W also requires a 2.4 GHz-capable network.

Useful service commands on the Pi:

```bash
sudo systemctl status gameblink-wifi.service
sudo journalctl -u gameblink-wifi.service -f
sudo systemctl restart gameblink-wifi.service
```

To test setup mode from an existing SSH session, run:

```bash
sudo touch /run/gameblink-wifi/force-setup
```

Within ten seconds the SSH connection will close because the Pi's single Wi-Fi
radio has switched from the home network to `GameBlink-XXXX`. Join that network
with password `GAMEBLINK`, then open `http://10.42.0.1`. Selecting your normal
home network returns the Pi to it. If a test goes wrong, rebooting clears the
runtime trigger and NetworkManager gets another chance to use the previously
saved home connection before setup mode returns.

The setup-hotspot password can be changed by overriding
`GAMEBLINK_HOTSPOT_PASSWORD` in the systemd service. It must contain at least
eight characters. It is normalized to uppercase so the password shown by the
LED display exactly matches the case-sensitive hotspot password.

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
