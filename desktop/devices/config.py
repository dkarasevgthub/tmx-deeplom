"""Configuration management for devices.

Handles loading/saving TOML configuration, enumerating serial ports
and printers, and providing defaults.
"""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# --- Default configuration values ---

DEFAULT_CONFIG_TOML: str = """\
[pipe]
name = "prozapas-devices"
idle_timeout_sec = 30        # 0 — never exit for lack of clients

[scanner]
port = ""                    # empty — device disabled (emulation mode)
baud = 115200
fake = true                  # true — stub driver, no real port

[scale]
port = "COM3"
baud = 115200
fake = true                  # true — эмуляция без порта, как у сканера
model = "esp32"
step_g = 10                  # grams, used to judge stability
command_tare = "TARE"
command_calib = "CALIB"

[printer]
name = ""                    # empty — stub writes to output_file instead
encoding = "cp866"
output_file = ""             # empty — %TEMP%, used by the stub

[log]
level = "info"
path = ""                    # empty — %ProgramData%\\ProZapas\\devices.log
"""


def get_config_path() -> Path:
    """Return the path to the TOML config file.

    Uses %ProgramData%\\ProZapas\\devices.toml.
    """
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    config_dir = Path(program_data) / "ProZapas"
    return config_dir / "devices.toml"


def load_config() -> dict[str, Any]:
    """Load configuration from TOML file.

    If the file does not exist, creates it with default values.
    Uses tomllib (Python 3.11+) for reading, tomli_w for writing.
    """
    config_path = get_config_path()

    if config_path.exists():
        logger.info("Loading config from %s", config_path)
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            logger.debug("Config loaded: %s", config)
            return config
        except Exception as exc:
            logger.error("Failed to parse config file %s: %s", config_path, exc)
            # Fall through to return defaults
    else:
        logger.info("Config file not found at %s, creating with defaults", config_path)

    # Create config with defaults
    _write_default_config(config_path)
    return _parse_default_config()


def _write_default_config(path: Path) -> None:
    """Write the default TOML configuration to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import tomli_w  # type: ignore[import-untyped]

        with open(path, "wb") as f:
            tomli_w.dump(_parse_default_config(), f)
        logger.info("Default config written to %s", path)
    except ImportError:
        # tomli_w not available – write raw text
        logger.warning("tomli_w not installed, writing raw TOML text")
        with open(path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_CONFIG_TOML)


def _parse_default_config() -> dict[str, Any]:
    """Parse the default TOML text into a dict."""
    return tomllib.loads(DEFAULT_CONFIG_TOML)


def list_ports() -> list[str]:
    """Serial ports with enough detail to tell one device from another.

    ``COM4 — USB-SERIAL CH340 (1A86:7523)`` says which port is the scanner and
    which is the scale; the bare name does not. Returns an empty list when
    pyserial is missing.
    """
    try:
        import serial.tools.list_ports  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("serial.tools.list_ports not available")
        return []

    ports = []
    for port in sorted(serial.tools.list_ports.comports(), key=lambda p: p.device):
        line = port.device
        if port.description and port.description != "n/a":
            line += f" — {port.description}"
        if port.vid is not None:
            line += f" ({port.vid:04X}:{port.pid:04X})"
        ports.append(line)
    return ports


def list_printers() -> list[str]:
    """Return a list of printer names using ``win32print.EnumPrinters``.

    Returns an empty list on non-Windows platforms or if win32print
    is unavailable.
    """
    try:
        import win32print  # type: ignore[import-untyped]

        printers = [
            p[2]  # p[2] is the printer name
            for p in win32print.EnumPrinters(
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
            )
        ]
        return printers
    except Exception:  # noqa: BLE001
        logger.debug("win32print not available")
        return []
