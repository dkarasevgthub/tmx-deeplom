"""Entry point for devices.

Creates the Qt application, loads configuration, initialises drivers,
starts the named-pipe server, and runs the event loop.

Usage::

    python -m devices [--list-ports] [--list-printers] [--version]
                              [--idle-timeout SEC]

Exit codes: ``0`` normal, ``2`` pipe busy, ``3`` configuration broken.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from PyQt6.QtCore import QCoreApplication, QTimer

from .config import list_ports, list_printers, load_config
from .drivers.base import DeviceDriver
from .drivers.printer import PrinterDriver
from .drivers.scale import ScaleDriver
from .drivers.scanner import ScannerDriver
from .logging_setup import setup_logging
from .server import DeviceServer

logger = logging.getLogger(__name__)

SERVICE_NAME = "devices"
SERVICE_VERSION = "0.1.0"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(prog=SERVICE_NAME)
    parser.add_argument(
        "--list-ports", action="store_true", help="List serial ports and exit."
    )
    parser.add_argument(
        "--list-printers", action="store_true", help="List printers and exit."
    )
    parser.add_argument(
        "--version", action="store_true", help="Print version and exit."
    )
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=None,
        metavar="SEC",
        help="Override [pipe] idle_timeout_sec; 0 disables the timeout. "
             "Used when a parent process owns the service lifetime.",
    )
    return parser.parse_args()


def _build_drivers(
    config: dict, app: QCoreApplication
) -> tuple[DeviceDriver, DeviceDriver, DeviceDriver]:
    """Create scanner/scale/printer drivers from *config*.

    Devices with no port/name are created as emulation stubs (offline
    is not forced — a stub simply has no real hardware).
    """
    scanner_cfg = config.get("scanner", {})
    scanner = ScannerDriver(
        port_name=scanner_cfg.get("port", ""),
        baud=int(scanner_cfg.get("baud", 115200)),
        fake=bool(scanner_cfg.get("fake", False)),
        parent=app,
    )

    scale_cfg = config.get("scale", {})
    scale = ScaleDriver(
        port=scale_cfg.get("port", ""),
        baud=int(scale_cfg.get("baud", 115200)),
        step_g=float(scale_cfg.get("step_g", 10)),
        command_tare=scale_cfg.get("command_tare", "TARE"),
        command_calib=scale_cfg.get("command_calib", "CALIB"),
        fake=bool(scale_cfg.get("fake", False)),
        parent=app,
    )

    printer_cfg = config.get("printer", {})
    printer = PrinterDriver(
        name=printer_cfg.get("name", ""),
        encoding=printer_cfg.get("encoding", "cp866"),
        output_file=printer_cfg.get("output_file", ""),
        parent=app,
    )
    return scanner, scale, printer


def main() -> None:
    """Main entry point."""
    args = parse_args()

    if args.version:
        print(f"{SERVICE_NAME} v{SERVICE_VERSION}", file=sys.stderr)
        return

    if args.list_ports:
        for port in list_ports():
            print(port)
        return

    if args.list_printers:
        for printer_name in list_printers():
            print(printer_name)
        return

    # --- Full service startup ------------------------------------------

    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001
        # Configuration is unreadable — exit code 3 per the lifecycle spec.
        print(f"configuration broken: {exc}", file=sys.stderr)
        sys.exit(3)

    setup_logging(config)

    app = QCoreApplication(sys.argv)
    app.setApplicationName(SERVICE_NAME)
    app.setApplicationVersion(SERVICE_VERSION)

    scanner, scale, printer = _build_drivers(config, app)

    # Open each driver; a failure is logged but never fatal.
    for driver, label in (
        (scanner, "scanner"),
        (scale, "scale"),
        (printer, "printer"),
    ):
        try:
            driver.open()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to open %s: %s", label, exc)

    server = DeviceServer(
        scanner=scanner, scale=scale, printer=printer, parent=app
    )

    pipe_cfg = config.get("pipe", {})
    pipe_name = pipe_cfg.get("name", "prozapas-devices")
    idle_timeout = float(pipe_cfg.get("idle_timeout_sec", 30))
    if args.idle_timeout is not None:
        idle_timeout = args.idle_timeout

    if not server.start(pipe_name):
        # Pipe already in use — another instance is running.
        logger.error("Pipe %s already in use, exiting", pipe_name)
        sys.exit(2)

    # Idle timeout: exit when no client is connected for idle_timeout_sec.
    idle_timer = QTimer(app)
    idle_timer.setSingleShot(True)
    idle_timer.setInterval(int(idle_timeout * 1000))
    idle_timer.timeout.connect(app.quit)
    if idle_timeout > 0:
        idle_timer.start()

    def _reset_idle() -> None:
        """Restart or stop the idle timer based on client count."""
        if server.has_clients:
            idle_timer.stop()
        elif idle_timeout > 0:
            idle_timer.start()

    server.client_connected.connect(_reset_idle)
    server.client_disconnected.connect(_reset_idle)
    server.shutdown_requested.connect(app.quit)

    def _on_about_to_quit() -> None:
        """Clean shutdown: flush drivers, stop server."""
        logger.info("devices shutting down")
        idle_timer.stop()
        scanner.close()
        scale.close()
        printer.close()
        server.stop()

    app.aboutToQuit.connect(_on_about_to_quit)

    # Graceful shutdown on Ctrl+C / SIGINT.
    def sigint_handler(signum, frame):
        print("\n⏹ Получен сигнал остановки (Ctrl+C). Завершаем работу...")
        app.quit()

    signal.signal(signal.SIGINT, sigint_handler)

    # Signal readiness to the parent process.
    print("ready", file=sys.stderr)
    logger.info("devices ready (pipe=%s, version=%s)", pipe_name, SERVICE_VERSION)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
