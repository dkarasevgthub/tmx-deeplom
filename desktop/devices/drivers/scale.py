"""Scale driver for ESP32-based scales over a virtual COM port (USB CDC).

The ESP32 streams lines of the form ``"59.23 S\\n"`` / ``"58.68 U\\n"``
at roughly 10 Hz: a floating-point weight, a space, and a stability flag
(``S`` = stable, ``U`` = unstable), terminated by ``\\n``.

The driver reads these lines asynchronously via ``QSerialPort`` signals
and emits a :pyattr:`weight` signal whenever the value or the stability
flag changes (the application only sees these through a ``weight``
event while subscribed).

It also supports two control commands sent *to* the scale:

* :meth:`tare` — send ``TARE\\n``, wait for ``OK``.
* :meth:`calibrate` — send ``CALIB <weight>\\n``, wait for ``OK``.

And a blocking-style read of one stable weight:

* :meth:`read_stable` — returns immediately if the latest reading is
  stable, otherwise waits (within the Qt event loop) for the next
  stable reading, raising :class:`ScaleTimeoutError` on timeout.

Both streaming and request/response scale firmwares are supported: in
polling mode the scale simply answers each line; outwardly the events
look the same.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEventLoop, QObject, QTimer, pyqtSignal
from PyQt6.QtSerialPort import QSerialPort

from ..protocol import STATE_ERROR, STATE_OFFLINE, STATE_ONLINE
from .base import DeviceDriver

logger = logging.getLogger(__name__)

#: Default step (grams) used to judge stability when the scale lacks a flag.
DEFAULT_STEP_G: float = 10.0

#: Default ``TARE`` command string.
DEFAULT_TARE_CMD: str = "TARE"
#: Default ``CALIB`` command string.
DEFAULT_CALIB_CMD: str = "CALIB"

#: How long to wait for an ``OK`` acknowledgement from the scale (ms).
ACK_TIMEOUT_MS: int = 2000


class ScaleTimeoutError(TimeoutError):
    """Raised when the scale does not return a stable reading in time."""


class ScaleDriver(DeviceDriver):
    """Driver for an ESP32-based scale on a virtual COM port.

    Signals
    -------
    weight(float, str, bool)
        ``(value, unit, stable)`` — emitted on change of value or flag.
    """

    weight = pyqtSignal(float, str, bool)

    def __init__(
        self,
        port: str = "",
        baud: int = 115200,
        step_g: float = DEFAULT_STEP_G,
        command_tare: str = DEFAULT_TARE_CMD,
        command_calib: str = DEFAULT_CALIB_CMD,
        unit: str = "g",
        fake: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(device_id="scale", parent=parent)
        self._port_name: str = port or ""
        # Эмуляция, как у сканера: без порта весы остаются online и принимают
        # показания снаружи (debug_emit weight) — так их гоняют без железа.
        self._fake: bool = fake or not bool(self._port_name)
        self._baud: int = baud
        self._step_g: float = step_g
        self._command_tare: str = command_tare
        self._command_calib: str = command_calib
        self._unit: str = unit

        self._serial = QSerialPort(self)
        self._last_value: float | None = None
        self._last_stable: bool = False

        # Pending single-line reply (used by tare/calibrate handshake).
        self._pending_ack: QEventLoop | None = None
        self._ack_timer = QTimer(self)
        self._ack_timer.setSingleShot(True)
        self._ack_timer.timeout.connect(self._on_ack_timeout)

    # --- Lifecycle -------------------------------------------------------

    def _do_open(self) -> None:
        """Open the serial port and start reading weight data."""
        if self._fake:
            logger.info("ScaleDriver: emulation mode (no real port)")
            self._set_state(STATE_ONLINE, "emulation")
            return
        logger.info("ScaleDriver: opening %s @ %d baud", self._port_name, self._baud)

        self._close_serial()
        serial = self._serial
        serial.setPortName(self._port_name)
        serial.setBaudRate(self._baud)
        serial.setDataBits(QSerialPort.DataBits.Data8)
        serial.setParity(QSerialPort.Parity.NoParity)
        serial.setStopBits(QSerialPort.StopBits.OneStop)
        serial.setFlowControl(QSerialPort.FlowControl.NoFlowControl)

        # ReadWrite: we also need to send tare/calibrate commands.
        if not serial.open(QSerialPort.OpenModeFlag.ReadWrite):
            error = serial.errorString()
            logger.error("ScaleDriver: failed to open %s – %s", self._port_name, error)
            self._set_state(STATE_ERROR, error)
            return

        serial.readyRead.connect(self._on_ready_read)
        serial.errorOccurred.connect(self._on_error_occurred)
        self._set_state(STATE_ONLINE, "port opened")

    def _do_close(self) -> None:
        """Close the serial port and reset cached readings."""
        self._abort_pending_ack()
        self._close_serial()
        self._last_value = None
        self._last_stable = False

    def _close_serial(self) -> None:
        """Disconnect signals and close the current port."""
        serial = self._serial
        try:
            serial.readyRead.disconnect(self._on_ready_read)
        except (TypeError, RuntimeError):
            pass
        try:
            serial.errorOccurred.disconnect(self._on_error_occurred)
        except (TypeError, RuntimeError):
            pass
        if serial.isOpen():
            serial.close()

    # --- Slots -----------------------------------------------------------

    def _on_ready_read(self) -> None:
        """Read all complete lines and hand them to the parser."""
        try:
            while self._serial.bytesAvailable() > 0:
                raw: bytes = self._serial.readLine().data()
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                self._handle_line(line)
        except Exception:
            logger.error("ScaleDriver: error reading port", exc_info=True)

    def _on_error_occurred(self, error: QSerialPort.SerialPortError) -> None:
        """Handle a serial-port error (e.g. scale unplugged)."""
        if error == QSerialPort.SerialPortError.NoError:
            return
        msg = self._serial.errorString()
        logger.warning("ScaleDriver: port error (%s): %s", error, msg)
        if (
            error == QSerialPort.SerialPortError.ResourceError
            or error == QSerialPort.SerialPortError.DeviceNotFoundError
        ):
            self._abort_pending_ack()
            if self._serial.isOpen():
                self._serial.close()
            self._set_state(STATE_OFFLINE, f"port error: {msg}")

    # --- Parsing ---------------------------------------------------------

    def _handle_line(self, line: str) -> None:
        """Parse one line from the scale.

        A bare ``OK`` is an acknowledgement for a tare/calibrate command
        and resolves any pending handshake. Otherwise the line is
        ``"<value> <S|U>"``.
        """
        if line.upper() == "OK":
            self._resolve_pending_ack()
            return

        parts = line.split()
        if len(parts) != 2:
            logger.debug("Scale: unexpected line format: %r", line)
            return
        try:
            value = float(parts[0])
        except ValueError:
            logger.debug("Scale: non-numeric value in line: %r", line)
            return
        stable = parts[1].upper() == "S"
        self._emit_if_changed(value, self._unit, stable)

    def _emit_if_changed(self, value: float, unit: str, stable: bool) -> None:
        """Emit :pyattr:`weight` only when value or flag changed."""
        if value == self._last_value and stable == self._last_stable:
            return
        self._last_value = value
        self._last_stable = stable
        logger.debug("Scale: value=%.2f unit=%s stable=%s", value, unit, stable)
        self.weight.emit(value, unit, stable)

    # --- Control commands ------------------------------------------------

    def _send_command(self, command: str) -> bool:
        """Write *command* + ``\\n`` to the port. Returns success."""
        if not self.is_open():
            logger.warning("ScaleDriver: cannot send %r, port not open", command)
            return False
        if self._fake:
            logger.info("ScaleDriver: emulation, command %r accepted", command)
            return True
        try:
            payload = (command + "\n").encode("utf-8")
            written = self._serial.write(payload)
            self._serial.flush()
            return written == len(payload)
        except Exception:
            logger.error("ScaleDriver: failed to send %r", command, exc_info=True)
            return False

    def _wait_for_ack(self, timeout_ms: int = ACK_TIMEOUT_MS) -> bool:
        """Block (inside the Qt event loop) until ``OK`` or timeout.

        Returns ``True`` on acknowledgement, ``False`` on timeout.
        """
        if not self.is_open():
            return False
        loop = QEventLoop()
        self._pending_ack = loop
        self._ack_timer.start(timeout_ms)
        loop.exec()
        self._ack_timer.stop()
        self._pending_ack = None
        # Distinguish timeout from ack via a flag set on the loop.
        return loop.property("ack_ok") is True

    def _resolve_pending_ack(self) -> None:
        """Signal a waiting handshake that ``OK`` arrived."""
        loop = self._pending_ack
        if loop is None:
            return
        loop.setProperty("ack_ok", True)
        loop.quit()

    def _on_ack_timeout(self) -> None:
        """Give up waiting for an acknowledgement."""
        loop = self._pending_ack
        if loop is None:
            return
        logger.warning("ScaleDriver: ack timeout")
        loop.quit()

    def _abort_pending_ack(self) -> None:
        """Abort any in-flight handshake (e.g. on close / port error)."""
        loop = self._pending_ack
        if loop is None:
            return
        self._ack_timer.stop()
        self._pending_ack = None
        loop.quit()

    def tare(self, timeout_ms: int = ACK_TIMEOUT_MS) -> bool:
        """Tare the scale. Returns ``True`` if acknowledged."""
        logger.info("ScaleDriver: tare")
        if not self._send_command(self._command_tare):
            return False
        if self._fake:
            self._emit_if_changed(0.0, self._unit, True)   # обнулили — 0 и стабильно
            return True
        return self._wait_for_ack(timeout_ms)

    def calibrate(self, weight: float, timeout_ms: int = ACK_TIMEOUT_MS) -> bool:
        """Calibrate the scale to *weight* grams. Returns ``True`` on ack."""
        command = f"{self._command_calib} {weight}"
        logger.info("ScaleDriver: calibrate %s", command)
        if not self._send_command(command):
            return False
        return self._wait_for_ack(timeout_ms)

    def read_stable(self, timeout_ms: int = 3000) -> float:
        """Return a stable weight reading.

        If the latest reading is already stable it is returned at once.
        Otherwise the method waits (within the Qt event loop) for the
        next stable reading. Raises :class:`ScaleTimeoutError` if none
        arrives within *timeout_ms*.
        """
        if self._last_value is not None and self._last_stable:
            return self._last_value

        if not self.is_open():
            raise ScaleTimeoutError("scale not open")

        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def _on_weight(_value: float, _unit: str, stable: bool) -> None:
            if stable:
                loop.setProperty("got_value", _value)
                loop.quit()

        self.weight.connect(_on_weight)
        timer.start(timeout_ms)
        loop.exec()
        timer.stop()
        try:
            self.weight.disconnect(_on_weight)
        except (TypeError, RuntimeError):
            pass

        value = loop.property("got_value")
        if value is None:
            raise ScaleTimeoutError("no stable reading within timeout")
        return float(value)

    # --- Public emulation API --------------------------------------------

    def emit_weight(
        self, value: float, unit: str | None = None, stable: bool = True
    ) -> None:
        """Inject a weight reading for emulation / tests."""
        self._emit_if_changed(value, unit or self._unit, stable)
