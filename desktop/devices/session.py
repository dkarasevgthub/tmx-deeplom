"""Client session handling for devices.

Each connected client is a :class:`ClientSession`. It does line-based
framing over the socket, parses JSON requests, dispatches them to the
relevant driver, and writes flat JSON responses back. It also filters
outgoing events by the client's subscriptions.

The protocol is flat (see devices-service.md, section 4)::

    request  {"id": 17, "cmd": "print", ...}
    response {"id": 17, "ok": true, "job": "j-1", "state": "queued"}
    event    {"event": "scan", "code": "..."}
"""

from __future__ import annotations

import logging
from typing import Any
from .protocol import make_event

from PyQt6.QtCore import QObject, pyqtSignal

from .drivers.base import DeviceDriver
from .drivers.printer import PrinterDriver
from .drivers.scale import ScaleDriver, ScaleTimeoutError
from .drivers.scanner import ScannerDriver
from .protocol import (
    ALL_EVENTS,
    CMD_DEBUG_EMIT,
    CMD_DEVICES,
    CMD_HELLO,
    CMD_PRINT,
    CMD_PRINT_QUEUE,
    CMD_PRINT_RETRY,
    CMD_PRINT_STATUS,
    CMD_SCALE_READ,
    CMD_SCALE_TARE,
    CMD_SHUTDOWN,
    CMD_SUBSCRIBE,
    CMD_UNSUBSCRIBE,
    DEVICE_STATES,
    ERR_BAD_REQUEST,
    ERR_BUSY,
    ERR_INTERNAL,
    ERR_INCOMPATIBLE,
    ERR_NO_DEVICE,
    ERR_PRINTER_OFFLINE,
    ERR_SCALE_TIMEOUT,
    ERR_UNKNOWN_COMMAND,
    PRINT_FORMATS,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    make_error,
    make_response,
    parse_frame,
)

logger = logging.getLogger(__name__)


class ClientSession(QObject):
    """One connected client: framing, dispatch, subscription filtering.

    Parameters
    ----------
    socket:
        The ``QLocalSocket`` for this connection.
    scanner, scale, printer:
        Driver instances (any may be ``None``).
    """

    #: Emitted when the client asks the service to shut down.
    shutdown_requested = pyqtSignal()

    def __init__(
        self,
        socket: Any,
        scanner: DeviceDriver | None = None,
        scale: DeviceDriver | None = None,
        printer: DeviceDriver | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._socket = socket
        self._scanner = scanner
        self._scale = scale
        self._printer = printer
        self._subscriptions: set[str] = set()
        self._buffer = bytearray()

        self._connect_socket()

    # --- Socket wiring ---------------------------------------------------

    def _connect_socket(self) -> None:
        """Hook the socket's ``readyRead`` / ``disconnected`` signals."""
        try:
            self._socket.readyRead.connect(self._on_ready_read)
        except AttributeError:
            logger.warning("Socket has no readyRead signal")
        try:
            self._socket.disconnected.connect(self._on_disconnected)
        except AttributeError:
            pass

    @property
    def socket(self) -> Any:
        """The underlying socket object."""
        return self._socket

    @property
    def subscriptions(self) -> set[str]:
        """A copy of the event names this client is subscribed to."""
        return set(self._subscriptions)

    # --- Inbound framing -------------------------------------------------

    def _on_ready_read(self) -> None:
        """Read available bytes, split into complete lines, dispatch."""
        try:
            data = bytes(self._socket.readAll())
        except Exception:  # noqa: BLE001
            logger.error("Session: error reading socket", exc_info=True)
            return
        self._buffer.extend(data)
        while True:
            idx_lf = self._buffer.find(0x0A)
            idx_cr = self._buffer.find(0x0D)
            candidates = [i for i in (idx_lf, idx_cr) if i >= 0]
            if not candidates:
                break
            idx = min(candidates)
            line = bytes(self._buffer[:idx])
            del self._buffer[: idx + 1]
            self._dispatch_line(line)

    def _dispatch_line(self, line: bytes) -> None:
        """Parse one line and route it to the command handler."""
        request = parse_frame(line)
        if request is None:
            # Malformed JSON — there is no id to reply to.
            logger.debug("Session: ignored malformed frame: %r", line)
            return

        req_id = request.get("id", 0)
        cmd = request.get("cmd", "")
        logger.debug("Session: <- %s", request)
        if not cmd:
            self._reply(req_id, make_error(req_id, ERR_BAD_REQUEST, "missing 'cmd'"))
            return
        self.handle_request(request)

    def handle_request(self, request: dict[str, Any]) -> None:
        """Dispatch a parsed request to its command handler.

        Any handler exception is turned into an ``internal`` error so a
        driver bug never drops the client.
        """
        req_id = request.get("id", 0)
        cmd = request.get("cmd", "")
        try:
            handler = self._handlers().get(cmd)
            if handler is None:
                self._reply(
                    req_id,
                    make_error(req_id, ERR_UNKNOWN_COMMAND, f"unknown command: {cmd}"),
                )
                return
            handler(req_id, request)
        except ScaleTimeoutError:
            self._reply(
                req_id, make_error(req_id, ERR_SCALE_TIMEOUT, "scale did not stabilise")
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Session: handler for %r failed", cmd, exc_info=True)
            self._reply(req_id, make_error(req_id, ERR_INTERNAL, str(exc)))

    # --- Command handlers ------------------------------------------------

    def _handlers(self) -> dict[str, Any]:
        """Return the command→handler dispatch table (rebuilt per call)."""
        return {
            CMD_HELLO: self._cmd_hello,
            CMD_DEVICES: self._cmd_devices,
            CMD_SUBSCRIBE: self._cmd_subscribe,
            CMD_UNSUBSCRIBE: self._cmd_unsubscribe,
            CMD_PRINT: self._cmd_print,
            CMD_PRINT_STATUS: self._cmd_print_status,
            CMD_PRINT_QUEUE: self._cmd_print_queue,
            CMD_PRINT_RETRY: self._cmd_print_retry,
            CMD_SCALE_READ: self._cmd_scale_read,
            CMD_SCALE_TARE: self._cmd_scale_tare,
            CMD_SHUTDOWN: self._cmd_shutdown,
            CMD_DEBUG_EMIT: self._cmd_debug_emit,
        }

    def _cmd_hello(self, req_id: Any, request: dict[str, Any]) -> None:
        client_proto = request.get("protocol", PROTOCOL_VERSION)
        if client_proto not in SUPPORTED_PROTOCOL_VERSIONS:
            self._reply(
                req_id,
                make_error(
                    req_id,
                    ERR_INCOMPATIBLE,
                    f"protocol {client_proto} not supported",
                ),
            )
            return
        self._reply(
            req_id,
            make_response(
                req_id,
                True,
                service="devices",
                protocol=SUPPORTED_PROTOCOL_VERSIONS,
            ),
        )

    def _cmd_devices(self, req_id: Any, request: dict[str, Any]) -> None:
        states = {
            "scanner": self._device_state(self._scanner),
            "scale": self._device_state(self._scale),
            "printer": self._device_state(self._printer),
        }
        self._reply(req_id, make_response(req_id, True, devices=states))

    def _cmd_subscribe(self, req_id: Any, request: dict[str, Any]) -> None:
        events = request.get("events", []) or []
        if not isinstance(events, list):
            self._reply(req_id, make_error(req_id, ERR_BAD_REQUEST, "'events' must be a list"))
            return
        for evt in events:
            if evt in ALL_EVENTS:
                self._subscriptions.add(evt)
        logger.info("Session: subscribed -> %s", sorted(self._subscriptions))
        self._reply(req_id, make_response(req_id, True, subscribed=sorted(self._subscriptions)))

    def _cmd_unsubscribe(self, req_id: Any, request: dict[str, Any]) -> None:
        events = request.get("events", []) or []
        if isinstance(events, list):
            for evt in events:
                self._subscriptions.discard(evt)
        logger.info("Session: subscribed -> %s", sorted(self._subscriptions))
        self._reply(req_id, make_response(req_id, True, subscribed=sorted(self._subscriptions)))

    def _cmd_print(self, req_id: Any, request: dict[str, Any]) -> None:
        printer = self._printer
        if not isinstance(printer, PrinterDriver):
            self._reply(req_id, make_error(req_id, ERR_PRINTER_OFFLINE, "no printer driver"))
            return
        try:
            key = str(request.get("key", ""))
            fmt = str(request.get("format", ""))
            payload = str(request.get("payload", ""))
            copies = int(request.get("copies", 1))
        except (TypeError, ValueError):
            self._reply(req_id, make_error(req_id, ERR_BAD_REQUEST, "invalid print arguments"))
            return
        if fmt not in PRINT_FORMATS:
            self._reply(req_id, make_error(req_id, ERR_BAD_REQUEST, f"unknown format: {fmt}"))
            return
        job_id, state = printer.submit(key, fmt, payload, copies)
        # ВАЖНО: отправляем ответ клиенту
        self._reply(req_id, make_response(req_id, True, job=job_id, state=state))

    def _cmd_print_status(self, req_id: Any, request: dict[str, Any]) -> None:
        printer = self._printer
        if not isinstance(printer, PrinterDriver):
            self._reply(req_id, make_error(req_id, ERR_NO_DEVICE, "no printer driver"))
            return
        job_id = str(request.get("job", ""))  # или "job_id"
        if not job_id:
            self._reply(req_id, make_error(req_id, ERR_BAD_REQUEST, "missing job id"))
            return
        state = printer.get_status(job_id)
        if state is None:
            self._reply(req_id, make_error(req_id, ERR_BAD_REQUEST, f"unknown job: {job_id}"))
            return
        # ВАЖНО: отправляем ответ клиенту
        self._reply(req_id, make_response(req_id, True, job=job_id, state=state))

    def _cmd_print_queue(self, req_id: Any, request: dict[str, Any]) -> None:
        printer = self._printer
        if not isinstance(printer, PrinterDriver):
            self._reply(req_id, make_error(req_id, ERR_NO_DEVICE, "no printer driver"))
            return
        jobs = printer.get_queue()
        # ВАЖНО: отправляем ответ клиенту
        self._reply(req_id, make_response(req_id, True, jobs=jobs))

    def _cmd_print_retry(self, req_id: Any, request: dict[str, Any]) -> None:
        printer = self._printer
        if not isinstance(printer, PrinterDriver):
            self._reply(req_id, make_error(req_id, ERR_NO_DEVICE, "no printer driver"))
            return
        job_id = str(request.get("job", ""))  # или "job_id"
        if not job_id:
            self._reply(req_id, make_error(req_id, ERR_BAD_REQUEST, "missing job id"))
            return
        state = printer.retry(job_id)
        if state is None:
            self._reply(req_id, make_error(req_id, ERR_BAD_REQUEST, f"unknown job: {job_id}"))
            return
        # ВАЖНО: отправляем ответ клиенту
        self._reply(req_id, make_response(req_id, True, job=job_id, state=state))

    def _cmd_scale_read(self, req_id: Any, request: dict[str, Any]) -> None:
        scale = self._scale
        if not isinstance(scale, ScaleDriver):
            self._reply(req_id, make_error(req_id, ERR_NO_DEVICE, "no scale driver"))
            return
        timeout_ms = int(request.get("timeout_ms", 3000))
        want_stable = bool(request.get("stable", True))
        try:
            value = scale.read_stable(timeout_ms)
        except ScaleTimeoutError:
            self._reply(req_id, make_error(req_id, ERR_SCALE_TIMEOUT, "scale did not stabilise"))
            return
        # ВАЖНО: отправляем ответ клиенту
        self._reply(
            req_id,
            # значение получено методом read_stable, поэтому оно устойчиво;
            # эхо want_stable вводило клиента в заблуждение
            make_response(req_id, True, value=value, unit="g", stable=True),
        )

    def _cmd_scale_tare(self, req_id: Any, request: dict[str, Any]) -> None:
        scale = self._scale
        if not isinstance(scale, ScaleDriver):
            self._reply(req_id, make_error(req_id, ERR_NO_DEVICE, "no scale driver"))
            return
        if not scale.is_open:
            self._reply(req_id, make_error(req_id, ERR_NO_DEVICE, "scale is not online"))
            return
        if not scale.tare():
            self._reply(req_id, make_error(req_id, ERR_INTERNAL, "tare command failed"))
            return
        self._reply(req_id, make_response(req_id, True))

    def _cmd_shutdown(self, req_id: Any, request: dict[str, Any]) -> None:
        logger.info("Session: shutdown requested")
        self._reply(req_id, make_response(req_id, True))
        self.shutdown_requested.emit()

    def _cmd_debug_emit(self, req_id: Any, request: dict[str, Any]) -> None:
        """Inject an event via the corresponding driver (debug console)."""
        event = str(request.get("event", ""))
        if event == "scan":
            scanner = self._scanner
            if not isinstance(scanner, ScannerDriver) or not hasattr(scanner, "emit_scan"):
                self._reply(req_id, make_error(req_id, ERR_NO_DEVICE, "no scanner to emit"))
                return
            code = str(request.get("code", ""))
            scanner.emit_scan(code)
            self._reply(req_id, make_response(req_id, True))
        elif event == "weight":
            scale = self._scale
            if not hasattr(scale, "emit_weight"):
                self._reply(req_id, make_error(req_id, ERR_NO_DEVICE, "no scale to emit"))
                return
            value = float(request.get("value", 0.0))
            stable = bool(request.get("stable", True))
            scale.emit_weight(value, "g", stable)
            self._reply(req_id, make_response(req_id, True))
        elif event == "device":
            # устройство берём из `device`: поле `id` занято номером запроса.
            # `status` понимаем наравне со `state` — так шлют старые консоли.
            dev = str(request.get("device") or "")
            state = str(request.get("state") or request.get("status") or "")
            reason = str(request.get("reason", ""))
            driver = self._driver_by_id(dev)
            if driver is None:
                self._reply(req_id, make_error(req_id, ERR_NO_DEVICE, f"no device: {dev}"))
                return
            if state not in DEVICE_STATES:
                self._reply(req_id, make_error(req_id, ERR_BAD_REQUEST, f"bad state: {state}"))
                return
            self._set_driver_state(driver, state, reason)
            self._reply(req_id, make_response(req_id, True))
        else:
            self._reply(
                req_id, make_error(req_id, ERR_BAD_REQUEST, f"unknown emit event: {event}")
            )

    # --- Outbound --------------------------------------------------------

    def send_event(self, event_name: str, data: dict[str, Any]) -> None:
        """Send an event to the client, but only if subscribed."""
        if event_name not in self._subscriptions:
            return
        frame = make_event(event_name, **data)
        logger.debug("Session: -> event %s", frame)
        self._write(frame)

    def _reply(self, req_id: Any, frame: dict[str, Any]) -> None:
        """Write a response frame."""
        logger.info(f"Session: replying to {req_id} with {frame}")  # <-- добавить
        self._write(frame)

    def _write(self, frame: dict[str, Any]) -> None:
        """Serialize *frame* and write it to the socket."""
        from .protocol import encode_frame
        try:
            data = encode_frame(frame)
            logger.info(f"Session: writing {len(data)} bytes")  # <-- добавить
            self._socket.write(data)
            self._socket.flush()
        except Exception as e:
            logger.error(f"Session: failed to write to socket: {e}", exc_info=True)  # <-- уже есть
    # --- Disconnect ------------------------------------------------------

    def _on_disconnected(self) -> None:
        """Clear subscriptions on disconnect."""
        logger.info("Session: client disconnected")
        self._subscriptions.clear()
        self._buffer.clear()

    # --- Helpers ---------------------------------------------------------

    @staticmethod
    def _device_state(driver: DeviceDriver | None) -> str:
        """Return the driver's state, or ``offline`` if no driver."""
        return driver.state if driver is not None else "offline"

    def _driver_by_id(self, device_id: str) -> DeviceDriver | None:
        """Find a driver by its ``device_id``."""
        for driver in (self._scanner, self._scale, self._printer):
            if driver is not None and driver.device_id == device_id:
                return driver
        return None

    def _set_driver_state(self, driver: DeviceDriver, state: str, reason: str) -> None:
        """Force a driver's state (debug console / tests)."""
        if hasattr(driver, "set_state_for_test"):
            driver.set_state_for_test(state, reason)  # type: ignore[attr-defined]
        else:
            # Base driver exposes the protected setter; use it as a fallback.
            driver._set_state(state, reason)  # noqa: SLF001
