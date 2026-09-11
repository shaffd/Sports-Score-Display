"""JSON configuration loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SUPPORTED_SPORTS = ("NHL", "NFL", "MLB")
DEFAULT_FAVORITE_TEAMS = (
    ("MLB", "NYY"),
    ("NHL", "NYR"),
    ("NFL", "DET"),
)


class ConfigError(ValueError):
    """Raised when the configuration cannot be used safely."""


@dataclass(frozen=True, slots=True)
class CanvasConfig:
    width: int = 64
    height: int = 32


@dataclass(frozen=True, slots=True)
class AssetConfig:
    logo_directory: Path = Path("Logos")
    font_path: Path | None = None


@dataclass(frozen=True, slots=True)
class FantasyPlayerConfig:
    """One fantasy player to resolve in the NFL box score feed."""

    player_id: str
    first_name: str
    last_name: str
    position: str
    team: str


@dataclass(frozen=True, slots=True)
class FantasyFootballConfig:
    enabled: bool = False
    players: tuple[FantasyPlayerConfig, ...] = ()


@dataclass(frozen=True, slots=True)
class MatrixConfig:
    rows: int = 32
    cols: int = 64
    chain_length: int = 1
    parallel: int = 1
    brightness: int = 60
    hardware_mapping: str = "adafruit-hat"
    gpio_slowdown: int = 1
    pwm_bits: int = 11
    pwm_lsb_nanoseconds: int = 130
    pwm_dither_bits: int = 0
    scan_mode: int = 0
    multiplexing: int = 0
    row_address_type: int = 0
    pixel_mapper_config: str = ""
    panel_type: str = ""
    led_rgb_sequence: str = "RGB"
    show_refresh_rate: bool = False
    drop_privileges: bool = True


@dataclass(frozen=True, slots=True)
class AppConfig:
    timezone: str = "America/New_York"
    lookback_hours: int = 24
    refresh_seconds: int = 30
    card_seconds: float = 5.0
    favorite_live_card_seconds: float = 180.0
    favorite_teams: tuple[tuple[str, str], ...] = DEFAULT_FAVORITE_TEAMS
    api_timeout_seconds: float = 10.0
    sports: tuple[str, ...] = SUPPORTED_SPORTS
    show_sport_headers: bool = True
    output: str = "preview"
    preview_scale: int = 8
    canvas: CanvasConfig = CanvasConfig()
    assets: AssetConfig = AssetConfig()
    fantasy_football: FantasyFootballConfig = FantasyFootballConfig()
    matrix: MatrixConfig = MatrixConfig()

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _positive(name: str, value: int | float) -> None:
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero")


def _resolve_optional_path(value: str | None, base_dir: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else (base_dir / path).resolve()


def _favorite_teams(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        raise ConfigError("favorite_teams must be an object keyed by sport")

    favorites: list[tuple[str, str]] = []
    for raw_sport, raw_teams in value.items():
        sport = str(raw_sport).upper()
        if sport not in SUPPORTED_SPORTS:
            raise ConfigError(f"Unsupported favorite team sport: {sport}")
        if not isinstance(raw_teams, list):
            raise ConfigError(f"favorite_teams.{sport} must be a list")
        for raw_team in raw_teams:
            abbreviation = str(raw_team).strip().upper()
            if not abbreviation:
                raise ConfigError(f"favorite_teams.{sport} contains an empty team")
            favorites.append((sport, abbreviation))
    return tuple(favorites)


def _fantasy_players(value: object) -> tuple[FantasyPlayerConfig, ...]:
    if not isinstance(value, list):
        raise ConfigError("fantasy_football.players must be a list")

    players: list[FantasyPlayerConfig] = []
    seen_ids: set[str] = set()
    for raw_player in value:
        if not isinstance(raw_player, dict):
            raise ConfigError("Each fantasy_football player must be an object")
        fields = {
            name: str(raw_player.get(name, "")).strip()
            for name in ("player_id", "first_name", "last_name", "position", "team")
        }
        missing = [name for name, field in fields.items() if not field]
        if missing:
            raise ConfigError(
                "fantasy_football player is missing " + ", ".join(missing)
            )
        player_id = fields["player_id"].lower()
        if player_id in seen_ids:
            raise ConfigError(f"Duplicate fantasy player_id: {player_id}")
        seen_ids.add(player_id)
        players.append(
            FantasyPlayerConfig(
                player_id=player_id,
                first_name=fields["first_name"],
                last_name=fields["last_name"],
                position=fields["position"].upper(),
                team=fields["team"].upper(),
            )
        )
    return tuple(players)


def load_config(path: str | Path = "config.json") -> AppConfig:
    """Load an AppConfig, resolving asset paths relative to the JSON file."""
    config_path = Path(path).resolve()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {config_path}: {exc}") from exc

    base_dir = config_path.parent
    canvas_raw = raw.get("canvas", {})
    assets_raw = raw.get("assets", {})
    matrix_raw = raw.get("matrix", {})
    fantasy_raw = raw.get("fantasy_football", {})
    if not isinstance(fantasy_raw, dict):
        raise ConfigError("fantasy_football must be an object")

    canvas = CanvasConfig(
        width=int(canvas_raw.get("width", 64)),
        height=int(canvas_raw.get("height", 32)),
    )
    assets = AssetConfig(
        logo_directory=_resolve_optional_path(
            assets_raw.get("logo_directory", "Logos"), base_dir
        )
        or (base_dir / "Logos"),
        font_path=_resolve_optional_path(assets_raw.get("font_path"), base_dir),
    )
    matrix = MatrixConfig(
        rows=int(matrix_raw.get("rows", 32)),
        cols=int(matrix_raw.get("cols", 64)),
        chain_length=int(matrix_raw.get("chain_length", 1)),
        parallel=int(matrix_raw.get("parallel", 1)),
        brightness=int(matrix_raw.get("brightness", 60)),
        hardware_mapping=str(matrix_raw.get("hardware_mapping", "adafruit-hat")),
        gpio_slowdown=int(matrix_raw.get("gpio_slowdown", 1)),
        pwm_bits=int(matrix_raw.get("pwm_bits", 11)),
        pwm_lsb_nanoseconds=int(matrix_raw.get("pwm_lsb_nanoseconds", 130)),
        pwm_dither_bits=int(matrix_raw.get("pwm_dither_bits", 0)),
        scan_mode=int(matrix_raw.get("scan_mode", 0)),
        multiplexing=int(matrix_raw.get("multiplexing", 0)),
        row_address_type=int(matrix_raw.get("row_address_type", 0)),
        pixel_mapper_config=str(matrix_raw.get("pixel_mapper_config", "")),
        panel_type=str(matrix_raw.get("panel_type", "")),
        led_rgb_sequence=str(matrix_raw.get("led_rgb_sequence", "RGB")),
        show_refresh_rate=bool(matrix_raw.get("show_refresh_rate", False)),
        drop_privileges=bool(matrix_raw.get("drop_privileges", True)),
    )

    sports = tuple(str(sport).upper() for sport in raw.get("sports", SUPPORTED_SPORTS))
    unsupported = sorted(set(sports) - set(SUPPORTED_SPORTS))
    if unsupported:
        raise ConfigError(f"Unsupported sports: {', '.join(unsupported)}")

    favorite_teams_raw = raw.get(
        "favorite_teams",
        {
            sport: [team]
            for sport, team in DEFAULT_FAVORITE_TEAMS
        },
    )
    fantasy_football = FantasyFootballConfig(
        enabled=bool(fantasy_raw.get("enabled", False)),
        players=_fantasy_players(fantasy_raw.get("players", [])),
    )

    config = AppConfig(
        timezone=str(raw.get("timezone", "America/New_York")),
        lookback_hours=int(raw.get("lookback_hours", 24)),
        refresh_seconds=int(raw.get("refresh_seconds", 30)),
        card_seconds=float(raw.get("card_seconds", 5.0)),
        favorite_live_card_seconds=float(
            raw.get("favorite_live_card_seconds", 180.0)
        ),
        favorite_teams=_favorite_teams(favorite_teams_raw),
        api_timeout_seconds=float(raw.get("api_timeout_seconds", 10.0)),
        sports=sports,
        show_sport_headers=bool(raw.get("show_sport_headers", True)),
        output=str(raw.get("output", "preview")).lower(),
        preview_scale=int(raw.get("preview_scale", 8)),
        canvas=canvas,
        assets=assets,
        fantasy_football=fantasy_football,
        matrix=matrix,
    )

    try:
        ZoneInfo(config.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Unknown timezone: {config.timezone}") from exc

    if config.output not in {"preview", "matrix"}:
        raise ConfigError("output must be either 'preview' or 'matrix'")
    if not config.sports:
        raise ConfigError("sports must contain at least one league")
    if config.fantasy_football.enabled and not config.fantasy_football.players:
        raise ConfigError("fantasy_football.players must not be empty when enabled")

    for name, value in (
        ("lookback_hours", config.lookback_hours),
        ("refresh_seconds", config.refresh_seconds),
        ("card_seconds", config.card_seconds),
        ("favorite_live_card_seconds", config.favorite_live_card_seconds),
        ("api_timeout_seconds", config.api_timeout_seconds),
        ("preview_scale", config.preview_scale),
        ("canvas.width", config.canvas.width),
        ("canvas.height", config.canvas.height),
        ("matrix.rows", config.matrix.rows),
        ("matrix.cols", config.matrix.cols),
        ("matrix.chain_length", config.matrix.chain_length),
        ("matrix.parallel", config.matrix.parallel),
    ):
        _positive(name, value)

    if not 1 <= config.matrix.brightness <= 100:
        raise ConfigError("matrix.brightness must be between 1 and 100")

    return config
