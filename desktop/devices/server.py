"""Device server for devices.

Runs a :class:`QLocalServer` listening on a Windows named pipe, accepts
client connections, wires driver signals to event broadcasts, and
forwards events only to subscribed sessions.

Driver signals are connected to plain Python slots on the server.
Because Qt already delivers cross-thread signals through the event
queue, a broadcast that touches many sockets still returns quickly —
each session's socket ``write`` is non-blocking.
"""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from .drivers.base import DeviceDriver
from .drivers.printer import PrinterDriver
from .drivers.scale import ScaleDriver
from .drivers.scanner import ScannerDriver
from .protocol import EVENT_DEVICE, EVENT_JOB, EVENT_SCAN, EVENT_WEIGHT
from .session import ClientSession

logger = logging.getLogger(__name__)


class DeviceServer(QObject):
    """Named-pipe server managing sessions and driver event wiring.

    Signals
    -------
    client_connected()
        A new client connected.
    client_disconnected()
        A client disconnected.
    """

    client_connected = pyqtSignal()
    client_disconnected = pyqtSignal()
    #: Emitted when any session requests a service shutdown.
    shutdown_requested = pyqtSignal()

    def __init__(
        self,
        scanner: DeviceDriver | None = None,
        scale: DeviceDriver | None = None,
        printer: DeviceDriver | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._sessions: list[ClientSession] = []
        self._scanner = scanner
        self._scale = scale
        self._printer = printer

        self._server.newConnection.connect(self._on_new_connection)
        self._wire_drivers()

    # --- Public API ------------------------------------------------------

    @property
    def sessions(self) -> list[ClientSession]:
        """A snapshot of the active client sessions."""
        return list(self._sessions)

    @property
    def has_clients(self) -> bool:
        """``True`` if at least one client is connected."""
        return len(self._sessions) > 0

    def start(self, pipe_name: str) -> bool:
        """Start listening on the named pipe *pipe_name*.

        The **short** name is what Qt wants: QLocalServer and QLocalSocket add
        the ``\\\\.\\pipe\\`` prefix themselves, and handing them the full path
        leaves a Qt client unable to find the server.

        A busy name is not taken over blindly. If something answers on the
        pipe, another instance is alive and we refuse to start (exit code 2);
        only a stale, unanswered pipe is removed and reused.
        """
        # Проверять занятость через listen() нельзя: Windows разрешает несколько
        # экземпляров канала с одним именем, и listen() у второго процесса тоже
        # вернёт True — соединения начнут доставаться то одному, то другому.
        if self._pipe_answers(pipe_name):
            logger.error(
                "DeviceServer: pipe %s is already served by another instance", pipe_name
            )
            return False

        if self._server.listen(pipe_name):
            logger.info("DeviceServer: listening on %s", self._server.fullServerName())
            return True

        logger.warning("DeviceServer: removing stale pipe %s", pipe_name)
        QLocalServer.removeServer(pipe_name)
        ok = self._server.listen(pipe_name)
        if ok:
            logger.info("DeviceServer: listening on %s", self._server.fullServerName())
        else:
            logger.error(
                "DeviceServer: failed to listen on %s – %s",
                pipe_name,
                self._server.serverError(),
            )
        return ok

    @staticmethod
    def _pipe_answers(pipe_name: str, timeout_ms: int = 300) -> bool:
        """Is a live server accepting connections on this pipe?"""
        probe = QLocalSocket()
        probe.connectToServer(pipe_name)
        alive = probe.waitForConnected(timeout_ms)
        probe.abort()
        return alive

    def stop(self) -> None:
        """Close the server and drop all client connections."""
        logger.info("DeviceServer: stopping")
        for session in self._sessions:
            self._close_session(session)
        self._sessions.clear()
        self._server.close()

    def broadcast(self, event_name: str, data: dict[str, Any]) -> None:
        """Send an event to every session subscribed to *event_name*."""
        for session in self._sessions:
            session.send_event(event_name, data)

    # --- Driver wiring ---------------------------------------------------

    def _wire_drivers(self) -> None:
        """Connect driver signals to broadcast slots."""
        scanner = self._scanner
        if isinstance(scanner, ScannerDriver) and hasattr(scanner, "scanned"):
            scanner.scanned.connect(self._on_scan)

        scale = self._scale
        if isinstance(scale, ScaleDriver) and hasattr(scale, "weight"):
            scale.weight.connect(self._on_weight)

        printer = self._printer
        if isinstance(printer, PrinterDriver) and hasattr(printer, "job_status_changed"):
            printer.job_status_changed.connect(self._on_job)

        for driver in (self._scanner, self._scale, self._printer):
            if driver is not None:
                driver.state_changed.connect(
                    lambda state, reason, d=driver: self._on_device_state(d, state, reason)
                )

    # --- Driver event slots ---------------------------------------------

    def _on_scan(self, code: str) -> None:
        """Broadcast a ``scan`` event from the scanner."""
        device = self._scanner.device_id if self._scanner else "scanner"
        logger.debug("DeviceServer: scan code=%s", code)
        self.broadcast(EVENT_SCAN, {"code": code, "device": device})

    def _on_weight(self, value: float, unit: str, stable: bool) -> None:
        """Broadcast a ``weight`` event from the scale."""
        logger.debug("DeviceServer: weight value=%.2f unit=%s stable=%s", value, unit, stable)
        self.broadcast(EVENT_WEIGHT, {"value": value, "unit": unit, "stable": stable})

    def _on_job(self, job_id: str, state: str, error: str) -> None:
        """Broadcast a ``job`` event from the printer."""
        logger.debug("DeviceServer: job %s -> %s", job_id, state)
        self.broadcast(EVENT_JOB, {"job": job_id, "state": state, "error": error})

    def _on_device_state(
        self, driver: DeviceDriver, state: str, reason: str
    ) -> None:
        """Broadcast a ``device`` event on a state change."""
        logger.debug("DeviceServer: device %s -> %s", driver.device_id, state)
        self.broadcast(
            EVENT_DEVICE,
            {"id": driver.device_id, "state": state, "reason": reason},
        )

    # --- Connection handling --------------------------------------------

    def _on_new_connection(self) -> None:
        """Accept the next pending connection."""
        socket: QLocalSocket | None = self._server.nextPendingConnection()
        if socket is None:
            return

        session = ClientSession(
            socket=socket,
            scanner=self._scanner,
            scale=self._scale,
            printer=self._printer,
            parent=self,
        )
        session.shutdown_requested.connect(self.shutdown_requested.emit)
        self._sessions.append(session)
        logger.info("DeviceServer: client connected (total=%d)", len(self._sessions))
        self.client_connected.emit()

        socket.disconnected.connect(lambda: self._on_client_disconnected(session))

    def _on_client_disconnected(self, session: ClientSession) -> None:
        """Remove a session after its client disconnects."""
        if session in self._sessions:
            self._sessions.remove(session)
            logger.info(
                "DeviceServer: client disconnected (total=%d)", len(self._sessions)
            )
        self._close_session(session)
        self.client_disconnected.emit()

    # --- Protected helpers ----------------------------------------------

    def _close_session(self, session: ClientSession) -> None:
        """Close the socket of *session* and schedule deletion."""
        try:
            sock = session.socket
            if hasattr(sock, "close"):
                sock.close()
        except Exception:  # noqa: BLE001
            pass
        session.deleteLater()
