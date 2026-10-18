"""Local Wi-Fi setup portal for headless GameBlink displays.

The service waits for NetworkManager to connect to a saved Wi-Fi network.  If
that does not happen, it creates a temporary WPA2 hotspot and serves a small
setup page directly from the Pi.  No Internet-hosted page is involved.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


LOGGER = logging.getLogger(__name__)
HOTSPOT_CONNECTION = "GameBlink Setup"
DEFAULT_INTERFACE = "wlan0"
DEFAULT_ADDRESS = "10.42.0.1"
DEFAULT_PASSWORD = "GAMEBLINK"
DEFAULT_STATUS_FILE = Path("/run/gameblink-wifi/status.json")
DEFAULT_FORCE_FILE = Path("/run/gameblink-wifi/force-setup")
CAPTIVE_PORTAL_PATHS = {
    "/generate_204",
    "/gen_204",
    "/hotspot-detect.html",
    "/library/test/success.html",
    "/connecttest.txt",
    "/ncsi.txt",
    "/redirect",
}


class NetworkManagerError(RuntimeError):
    """Raised when an nmcli operation cannot be completed."""


def split_nmcli_fields(line: str) -> list[str]:
    """Split nmcli terse output while honoring its backslash escaping."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line.rstrip("\n"):
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


def validate_wifi_credentials(ssid: str, password: str) -> None:
    """Validate values before passing them to NetworkManager."""
    if not ssid or len(ssid.encode("utf-8")) > 32:
        raise ValueError("The Wi-Fi name must contain between 1 and 32 bytes.")
    if "\x00" in ssid or "\x00" in password:
        raise ValueError("The Wi-Fi name and password cannot contain null bytes.")
    if password and not 8 <= len(password) <= 63:
        raise ValueError("A Wi-Fi password must contain between 8 and 63 characters.")


def hotspot_name(interface: str = DEFAULT_INTERFACE) -> str:
    """Return a recognizable, device-specific GameBlink hotspot name."""
    address_path = Path("/sys/class/net") / interface / "address"
    try:
        compact = address_path.read_text(encoding="ascii").strip().replace(":", "")
    except OSError:
        compact = ""
    suffix = compact[-4:].upper() if len(compact) >= 4 else "SETUP"
    return f"GameBlink-{suffix}"


@dataclass(frozen=True, slots=True)
class WifiNetwork:
    ssid: str
    signal: int
    security: str

    @property
    def is_open(self) -> bool:
        return not self.security or self.security == "--"


class NetworkManager:
    """Small, argument-safe wrapper around NetworkManager's nmcli command."""

    def __init__(self, interface: str = DEFAULT_INTERFACE) -> None:
        self.interface = interface

    @staticmethod
    def _run(
        arguments: list[str],
        *,
        check: bool = True,
        timeout: float = 45,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["LC_ALL"] = "C"
        try:
            completed = subprocess.run(
                ["nmcli", *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NetworkManagerError(f"Unable to run nmcli: {exc}") from exc
        if check and completed.returncode:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise NetworkManagerError(message or "NetworkManager command failed")
        return completed

    def connection_name(self) -> str:
        result = self._run(
            ["-g", "GENERAL.CONNECTION", "device", "show", self.interface],
            check=False,
        )
        return result.stdout.strip()

    def is_client_connected(self) -> bool:
        state = self._run(
            ["-g", "GENERAL.STATE", "device", "show", self.interface],
            check=False,
        ).stdout.strip()
        connection = self.connection_name()
        return state.startswith("100") and connection not in {"", "--", HOTSPOT_CONNECTION}

    def is_hotspot_active(self) -> bool:
        return self.connection_name() == HOTSPOT_CONNECTION

    def scan(self) -> list[WifiNetwork]:
        result = self._run(
            [
                "-t",
                "--escape",
                "yes",
                "-f",
                "SSID,SIGNAL,SECURITY",
                "device",
                "wifi",
                "list",
                "--rescan",
                "yes",
                "ifname",
                self.interface,
            ],
            timeout=20,
        )
        networks: dict[str, WifiNetwork] = {}
        for line in result.stdout.splitlines():
            fields = split_nmcli_fields(line)
            if len(fields) < 3 or not fields[0]:
                continue
            try:
                signal = max(0, min(100, int(fields[1])))
            except ValueError:
                signal = 0
            network = WifiNetwork(fields[0], signal, fields[2])
            previous = networks.get(network.ssid)
            if previous is None or network.signal > previous.signal:
                networks[network.ssid] = network
        return sorted(networks.values(), key=lambda item: (-item.signal, item.ssid.lower()))

    def _connection_exists(self, name: str) -> bool:
        result = self._run(["-g", "NAME", "connection", "show"], check=False)
        return name in result.stdout.splitlines()

    def saved_wifi_connections(self) -> list[str]:
        result = self._run(
            ["-t", "--escape", "yes", "-f", "NAME,TYPE", "connection", "show"],
            check=False,
        )
        names: list[str] = []
        for line in result.stdout.splitlines():
            fields = split_nmcli_fields(line)
            if len(fields) >= 2 and fields[0] != HOTSPOT_CONNECTION:
                if fields[1] in {"802-11-wireless", "wifi"}:
                    names.append(fields[0])
        return names

    def start_hotspot(self, ssid: str, password: str, address: str) -> None:
        self._run(["radio", "wifi", "on"])
        if self._connection_exists(HOTSPOT_CONNECTION):
            self._run(["connection", "delete", HOTSPOT_CONNECTION], check=False)
        self._run(
            [
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                self.interface,
                "con-name",
                HOTSPOT_CONNECTION,
                "ssid",
                ssid,
            ]
        )
        self._run(
            [
                "connection",
                "modify",
                HOTSPOT_CONNECTION,
                "connection.autoconnect",
                "no",
                "802-11-wireless.mode",
                "ap",
                "802-11-wireless.band",
                "bg",
                "ipv4.method",
                "shared",
                "ipv4.addresses",
                f"{address}/24",
                "ipv6.method",
                "disabled",
                "802-11-wireless-security.key-mgmt",
                "wpa-psk",
                "802-11-wireless-security.proto",
                "rsn",
                "802-11-wireless-security.psk",
                password,
            ]
        )
        self._run(["--wait", "30", "connection", "up", HOTSPOT_CONNECTION])

    def stop_hotspot(self) -> None:
        if self.is_hotspot_active():
            self._run(["connection", "down", HOTSPOT_CONNECTION], check=False)

    @staticmethod
    def _home_connection_name(ssid: str) -> str:
        digest = hashlib.sha256(ssid.encode("utf-8")).hexdigest()[:8]
        return f"GameBlink Home {digest}"

    def connect(self, ssid: str, password: str, *, hidden: bool = False) -> None:
        validate_wifi_credentials(ssid, password)
        self.stop_hotspot()
        profile_name = self._home_connection_name(ssid)
        if self._connection_exists(profile_name):
            self._run(["connection", "delete", profile_name], check=False)

        arguments = [
            "--wait",
            "35",
            "device",
            "wifi",
            "connect",
            ssid,
            "ifname",
            self.interface,
            "name",
            profile_name,
        ]
        if password:
            arguments.extend(["password", password])
        if hidden:
            arguments.extend(["hidden", "yes"])
        self._run(arguments, timeout=45)
        self._run(
            [
                "connection",
                "modify",
                profile_name,
                "connection.autoconnect",
                "yes",
                "connection.autoconnect-priority",
                "100",
            ]
        )
        if not self.is_client_connected():
            raise NetworkManagerError("The Pi did not remain connected to that network.")

    def try_saved_connections(self) -> bool:
        if not self.saved_wifi_connections():
            return False
        self.stop_hotspot()
        self._run(["--wait", "30", "device", "up", self.interface], check=False)
        return self.is_client_connected()


class WifiSetupController:
    """Coordinate hotspot lifecycle, the local portal, and connection attempts."""

    def __init__(
        self,
        network_manager: NetworkManager,
        *,
        address: str = DEFAULT_ADDRESS,
        port: int = 80,
        password: str = DEFAULT_PASSWORD,
        status_file: Path = DEFAULT_STATUS_FILE,
        force_file: Path = DEFAULT_FORCE_FILE,
        first_setup_seconds: float = 30,
        known_network_seconds: float = 180,
        poll_seconds: float = 10,
        retry_saved_seconds: float = 60,
    ) -> None:
        password = password.upper()
        if len(password) < 8:
            raise ValueError("The setup-hotspot password must contain at least 8 characters.")
        self.network_manager = network_manager
        self.address = address
        self.port = port
        self.password = password
        self.status_file = status_file
        self.force_file = force_file
        self.first_setup_seconds = first_setup_seconds
        self.known_network_seconds = known_network_seconds
        self.poll_seconds = poll_seconds
        self.retry_saved_seconds = retry_saved_seconds
        self.ssid = hotspot_name(network_manager.interface)
        self.last_error = ""
        self._network_cache: list[WifiNetwork] = []
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._attempt_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._attempt_pending = threading.Event()
        self._stop = threading.Event()
        self._setup_started_at = 0.0

    def _connection_grace_seconds(self) -> float:
        """Use a short first-time delay and a longer saved-network outage delay."""
        if self.network_manager.saved_wifi_connections():
            return self.known_network_seconds
        return self.first_setup_seconds

    def _write_status(self, state: str, *, error: str = "") -> None:
        payload = {
            "state": state,
            "ssid": self.ssid,
            "password": self.password,
            "url": f"http://{self.address}",
            "error": error,
        }
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(self.status_file)

    def scan(self) -> list[WifiNetwork]:
        try:
            scanned = [
                network
                for network in self.network_manager.scan()
                if network.ssid != self.ssid
            ]
        except NetworkManagerError:
            if self._network_cache:
                return list(self._network_cache)
            raise
        if scanned:
            self._network_cache = scanned
        return list(self._network_cache)

    @property
    def setup_active(self) -> bool:
        return self.network_manager.is_hotspot_active()

    def start_portal(self, error: str = "") -> None:
        with self._attempt_lock:
            if not self.network_manager.is_hotspot_active():
                LOGGER.info("Starting setup hotspot %s", self.ssid)
                try:
                    self._network_cache = [
                        network
                        for network in self.network_manager.scan()
                        if network.ssid != self.ssid
                    ]
                except NetworkManagerError:
                    LOGGER.warning("Could not scan before starting setup mode")
                self.network_manager.start_hotspot(self.ssid, self.password, self.address)
            self.last_error = error
            self._write_status("setup", error=error)
            self._setup_started_at = time.monotonic()
            if self._server is None:
                server = ThreadingHTTPServer(("0.0.0.0", self.port), PortalHandler)
                server.daemon_threads = True
                server.controller = self  # type: ignore[attr-defined]
                self._server = server
                self._server_thread = threading.Thread(
                    target=server.serve_forever,
                    name="gameblink-portal",
                    daemon=True,
                )
                self._server_thread.start()
                LOGGER.info("Wi-Fi setup page available at http://%s", self.address)

    def _stop_server(self) -> None:
        server = self._server
        thread = self._server_thread
        self._server = None
        self._server_thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def begin_connection(self, ssid: str, password: str, hidden: bool) -> None:
        validate_wifi_credentials(ssid, password)
        with self._pending_lock:
            if self._attempt_pending.is_set():
                raise RuntimeError("A connection attempt is already in progress.")
            self._attempt_pending.set()
        worker = threading.Thread(
            target=self._connect_worker,
            args=(ssid, password, hidden),
            name="gameblink-connect",
            daemon=True,
        )
        worker.start()

    def _connect_worker(self, ssid: str, password: str, hidden: bool) -> None:
        # Give the HTTP response time to reach the phone before the hotspot drops.
        time.sleep(1.5)
        try:
            with self._attempt_lock:
                self._write_status("connecting")
                try:
                    LOGGER.info("Attempting connection to Wi-Fi network %r", ssid)
                    self.network_manager.connect(ssid, password, hidden=hidden)
                except (NetworkManagerError, ValueError) as exc:
                    LOGGER.warning("Wi-Fi connection failed: %s", exc)
                    friendly = "Could not connect. Check the Wi-Fi password and try again."
                    try:
                        self.network_manager.start_hotspot(
                            self.ssid, self.password, self.address
                        )
                        self.last_error = friendly
                        self._write_status("setup", error=friendly)
                        self._setup_started_at = time.monotonic()
                    except NetworkManagerError:
                        LOGGER.exception("Could not restore the GameBlink setup hotspot")
                    return

                LOGGER.info("GameBlink connected to %r", ssid)
                self.last_error = ""
                self._write_status("connected")
            self._stop_server()
        finally:
            self._attempt_pending.clear()

    def run(self) -> None:
        disconnected_since: float | None = time.monotonic()
        connection_grace = self._connection_grace_seconds()
        LOGGER.info("Waiting for a saved Wi-Fi connection on %s", self.network_manager.interface)
        self._write_status("checking")
        try:
            while not self._stop.wait(self.poll_seconds):
                if self._attempt_lock.locked():
                    continue
                if self.force_file.exists():
                    try:
                        self.force_file.unlink()
                    except OSError:
                        LOGGER.exception("Could not clear the force-setup request")
                    self.start_portal()
                    disconnected_since = None
                    continue
                if self.network_manager.is_client_connected():
                    disconnected_since = None
                    connection_grace = self.known_network_seconds
                    self.last_error = ""
                    self._write_status("connected")
                    if self._server is not None:
                        self._stop_server()
                    continue

                if self.network_manager.is_hotspot_active():
                    if self._server is None:
                        self.start_portal(self.last_error)
                    elapsed = time.monotonic() - self._setup_started_at
                    if (
                        elapsed >= self.retry_saved_seconds
                        and self.network_manager.saved_wifi_connections()
                    ):
                        with self._attempt_lock:
                            if self.network_manager.try_saved_connections():
                                self._write_status("connected")
                                self._stop_server()
                                disconnected_since = None
                            else:
                                self.network_manager.start_hotspot(
                                    self.ssid, self.password, self.address
                                )
                                self._write_status("setup", error=self.last_error)
                                self._setup_started_at = time.monotonic()
                    continue

                now = time.monotonic()
                if disconnected_since is None:
                    disconnected_since = now
                    connection_grace = self._connection_grace_seconds()
                if now - disconnected_since >= connection_grace:
                    self.start_portal(self.last_error)
        finally:
            self._stop_server()


class PortalHandler(BaseHTTPRequestHandler):
    """Serve the self-contained, mobile-friendly Wi-Fi setup page."""

    server_version = "GameBlink/1.0"

    @property
    def controller(self) -> WifiSetupController:
        return self.server.controller  # type: ignore[attr-defined, no-any-return]

    def log_message(self, fmt: str, *args: object) -> None:
        LOGGER.debug("Portal request: " + fmt, *args)

    def _send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def _redirect_home(self) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", f"http://{self.controller.address}/")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = urlsplit(self.path).path
        if path in CAPTIVE_PORTAL_PATHS:
            self._redirect_home()
            return
        if path != "/":
            self._redirect_home()
            return
        try:
            networks = self.controller.scan()
            self._send_html(render_setup_page(self.controller, networks))
        except NetworkManagerError as exc:
            LOGGER.warning("Wi-Fi scan failed: %s", exc)
            self._send_html(render_setup_page(self.controller, []))

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if urlsplit(self.path).path != "/connect":
            self._redirect_home()
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 4096:
            self._send_html(
                render_message_page("Invalid request", "Return to Wi-Fi setup and try again."),
                HTTPStatus.BAD_REQUEST,
            )
            return
        values = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        ssid = values.get("ssid", [""])[0]
        manual_ssid = values.get("manual_ssid", [""])[0]
        if ssid == "__manual__":
            ssid = manual_ssid
        password = values.get("password", [""])[0]
        hidden = values.get("hidden", [""])[0] == "yes" or bool(manual_ssid)
        try:
            self.controller.begin_connection(ssid, password, hidden)
        except (ValueError, RuntimeError) as exc:
            self._send_html(
                render_message_page("Unable to connect", str(exc), back_link=True),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._send_html(
            render_message_page(
                "Connecting…",
                "Your phone will disconnect from GameBlink while the display joins your home Wi-Fi. "
                "If it cannot connect, the GameBlink setup network will return automatically.",
            )
        )


def render_message_page(title: str, message: str, *, back_link: bool = False) -> str:
    link = '<p><a class="button secondary" href="/">Back to setup</a></p>' if back_link else ""
    return _page_shell(
        html.escape(title),
        f"<section><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>{link}</section>",
    )


def render_setup_page(
    controller: WifiSetupController,
    networks: list[WifiNetwork],
) -> str:
    rows: list[str] = []
    for index, network in enumerate(networks):
        checked = " checked" if index == 0 else ""
        security = "Open" if network.is_open else network.security
        rows.append(
            '<label class="network">'
            f'<input type="radio" name="ssid" value="{html.escape(network.ssid, quote=True)}"{checked}>'
            '<span class="network-name">'
            f"{html.escape(network.ssid)}"
            f'<small>{network.signal}% · {html.escape(security)}</small>'
            "</span></label>"
        )
    network_rows = "".join(rows) or "<p>No networks were found. Refresh or enter the name manually.</p>"
    error = ""
    if controller.last_error:
        error = f'<p class="error">{html.escape(controller.last_error)}</p>'
    body = f"""
    <section>
      <div class="brand">GameBlink</div>
      <h1>Connect your display</h1>
      <p>Select the home Wi-Fi network this display should use.</p>
      {error}
      <form method="post" action="/connect">
        <div class="networks">{network_rows}</div>
        <label class="network manual">
          <input type="radio" name="ssid" value="__manual__">
          <span class="network-name">Hidden or unlisted network</span>
        </label>
        <label for="manual_ssid">Network name, if entered manually</label>
        <input id="manual_ssid" name="manual_ssid" maxlength="32" autocomplete="off">
        <label for="password">Wi-Fi password</label>
        <input id="password" name="password" type="password" maxlength="63" autocomplete="off">
        <label class="check"><input type="checkbox" name="hidden" value="yes"> This is a hidden network</label>
        <button type="submit">Connect GameBlink</button>
      </form>
      <p class="privacy">This page is stored on your GameBlink display. The Wi-Fi password is sent only to this device and is saved by Raspberry Pi OS.</p>
      <p><a class="button secondary" href="/">Refresh network list</a></p>
    </section>
    """
    return _page_shell("GameBlink Wi-Fi Setup", body)


def _page_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: dark; font-family: system-ui, -apple-system, sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; padding: 24px 14px; background: #080d18; color: #eef4ff; }}
    section {{ width: min(100%, 520px); margin: auto; padding: 24px; border: 1px solid #253555; border-radius: 18px; background: #111a2b; box-shadow: 0 16px 50px #0008; }}
    .brand {{ color: #50e3ff; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    h1 {{ margin: 8px 0; font-size: 1.7rem; }}
    p {{ color: #bfcae0; line-height: 1.45; }}
    label:not(.network):not(.check) {{ display: block; margin: 18px 0 7px; font-weight: 700; }}
    input[type=text], input[type=password], input:not([type]) {{ width: 100%; padding: 13px; border: 1px solid #405174; border-radius: 10px; background: #0a1120; color: white; font-size: 1rem; }}
    .networks {{ max-height: 260px; overflow: auto; border: 1px solid #2b3a59; border-radius: 10px; }}
    .network {{ display: flex; gap: 12px; align-items: center; padding: 12px; border-bottom: 1px solid #263552; cursor: pointer; }}
    .network:last-child {{ border-bottom: 0; }}
    .network.manual {{ margin-top: 12px; border: 1px solid #2b3a59; border-radius: 10px; }}
    .network-name {{ overflow-wrap: anywhere; }}
    small {{ display: block; margin-top: 2px; color: #8fa0bd; }}
    .check {{ display: flex; gap: 8px; margin: 16px 0; color: #bfcae0; }}
    button, .button {{ display: block; width: 100%; padding: 13px 16px; border: 0; border-radius: 10px; background: #50e3ff; color: #03121a; font-weight: 800; font-size: 1rem; text-align: center; text-decoration: none; cursor: pointer; }}
    .button.secondary {{ background: #253555; color: #eef4ff; }}
    .privacy {{ font-size: .82rem; }}
    .error {{ padding: 10px; border-radius: 8px; background: #5d2130; color: #ffe8ee; }}
  </style>
</head>
<body>{body}</body>
</html>"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GameBlink local Wi-Fi setup portal")
    parser.add_argument("--interface", default=DEFAULT_INTERFACE)
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument(
        "--hotspot-password",
        default=os.environ.get("GAMEBLINK_HOTSPOT_PASSWORD", DEFAULT_PASSWORD),
    )
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS_FILE)
    parser.add_argument("--force-file", type=Path, default=DEFAULT_FORCE_FILE)
    parser.add_argument("--first-setup-seconds", type=float, default=30)
    parser.add_argument("--known-network-seconds", type=float, default=180)
    parser.add_argument("--poll-seconds", type=float, default=10)
    parser.add_argument("--retry-saved-seconds", type=float, default=60)
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
    controller = WifiSetupController(
        NetworkManager(args.interface),
        address=args.address,
        port=args.port,
        password=args.hotspot_password,
        status_file=args.status_file,
        force_file=args.force_file,
        first_setup_seconds=args.first_setup_seconds,
        known_network_seconds=args.known_network_seconds,
        poll_seconds=args.poll_seconds,
        retry_saved_seconds=args.retry_saved_seconds,
    )
    try:
        controller.run()
    except NetworkManagerError as exc:
        LOGGER.error("%s", exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
