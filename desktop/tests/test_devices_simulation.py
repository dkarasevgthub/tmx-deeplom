"""Tests for device slots, attach/detach, auto-detach, and print routing."""

import json
from typing import Any

import pytest
from PyQt6.QtCore import QByteArray, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from devices.drivers.fake import FakePrinter, FakeScale, FakeScanner
from devices.protocol import (
    STATE_ONLINE,
    parse_frame,
)
from devices.server import DeviceServer
from devices.session import ClientSession
from devices.slot import DeviceSlot


# --- Mocks ---

class FakeSocket(QObject):
    """Имитация QLocalSocket для тестирования ClientSession."""
    readyRead = pyqtSignal()
    disconnected = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._incoming = QByteArray()
        self._outgoing = QByteArray()

    def readAll(self) -> QByteArray:
        data = self._incoming
        self._incoming = QByteArray()
        return data

    def write(self, data: bytes) -> int:
        self._outgoing.append(data)
        return len(data)

    def flush(self) -> bool:
        return True

    def inject_data(self, data: bytes) -> None:
        self._incoming.append(data)
        self.readyRead.emit()

    def get_outgoing(self) -> list[dict[str, Any]]:
        frames = []
        for line in bytes(self._outgoing).split(b'\n'):
            line = line.strip()
            if line:
                frame = parse_frame(line)
                if frame:
                    frames.append(frame)
        self._outgoing.clear()
        return frames

    def close(self) -> None:
        pass

    def disconnectFromServer(self) -> None:
        self.disconnected.emit()


# --- Fixtures ---

@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


@pytest.fixture
def server(app):
    """Создает сервер со слотами, где real-драйверами выступают фейки."""
    real_scanner = FakeScanner()
    real_scale = FakeScale()
    real_printer = FakePrinter()

    fake_scanner = FakeScanner()
    fake_scale = FakeScale()
    fake_printer = FakePrinter()

    scanner_slot = DeviceSlot("scanner", real_scanner, fake_scanner)
    scale_slot = DeviceSlot("scale", real_scale, fake_scale)
    printer_slot = DeviceSlot("printer", real_printer, fake_printer)

    real_scanner.open()
    real_scale.open()
    real_printer.open()

    server = DeviceServer(scanner_slot, scale_slot, printer_slot)
    yield server

    real_scanner.close()
    real_scale.close()
    real_printer.close()


@pytest.fixture
def client_factory(server):
    """Фабрика для создания тестовых клиентов."""
    sessions = []

    def _create():
        sock = FakeSocket()
        session = ClientSession(
            socket=sock,
            server=server,
            scanner_slot=server._scanner_slot,
            scale_slot=server._scale_slot,
            printer_slot=server._printer_slot,
        )
        # ВАЖНО: подключаем сигнал маршрутизации печати!
        session.print_routed.connect(server._on_print_routed)
        session._subscriptions = {"scan", "weight", "device", "job", "print.job"}
        server._sessions.append(session)
        sessions.append(session)
        return session, sock

    return _create


# --- Tests ---

def test_slot_attach_detach(qtbot):
    real = FakeScanner()
    fake = FakeScanner()
    slot = DeviceSlot("scanner", real, fake)

    real.open()
    assert slot.is_simulated() is False
    assert slot.active_driver() == real

    assert slot.attach() is True
    assert slot.is_simulated() is True
    assert slot.active_driver() == fake

    assert slot.attach() is False

    assert slot.detach() is True
    assert slot.is_simulated() is False
    assert slot.active_driver() == real

    assert slot.detach() is False


def test_session_attach_detach(qtbot, client_factory):
    session, sock = client_factory()

    sock.inject_data(b'{"id":1,"cmd":"attach","devices":["scanner"]}\n')

    outgoing = sock.get_outgoing()
    assert len(outgoing) == 2

    resp = next(f for f in outgoing if "ok" in f)
    assert resp["id"] == 1
    assert resp["ok"] is True
    assert resp["attached"] == ["scanner"]

    event = next(f for f in outgoing if "event" in f)
    assert event["event"] == "device"
    assert event["device"] == "scanner"
    assert event["state"] == STATE_ONLINE
    assert event["reason"] == "simulated"

    sock.inject_data(b'{"id":2,"cmd":"detach","devices":["scanner"]}\n')

    outgoing = sock.get_outgoing()
    assert len(outgoing) == 2
    resp = next(f for f in outgoing if "ok" in f)
    assert resp["id"] == 2
    assert resp["ok"] is True
    assert resp["attached"] == []

    event = next(f for f in outgoing if "event" in f)
    assert event["event"] == "device"
    assert event["device"] == "scanner"
    assert event["reason"] == "real"


def test_busy_role(qtbot, client_factory):
    session1, sock1 = client_factory()
    session2, sock2 = client_factory()

    sock1.inject_data(b'{"id":1,"cmd":"attach","devices":["scanner"]}\n')
    sock1.get_outgoing()
    sock2.get_outgoing()

    sock2.inject_data(b'{"id":1,"cmd":"attach","devices":["scanner"]}\n')

    responses = sock2.get_outgoing()
    assert len(responses) == 1
    assert responses[0]["ok"] is False
    assert responses[0]["error"]["code"] == "busy"


def test_auto_detach_on_disconnect(qtbot, client_factory):
    session, sock = client_factory()

    sock.inject_data(b'{"id":1,"cmd":"attach","devices":["scanner"]}\n')
    sock.get_outgoing()

    assert "scanner" in session.owned_devices

    sock.disconnected.emit()

    assert len(session.owned_devices) == 0
    assert session._scanner_slot.is_simulated() is False


def test_print_routing_and_auto_ack(qtbot, client_factory):
    sim_session, sim_sock = client_factory()
    app_session, app_sock = client_factory()

    sim_sock.inject_data(b'{"id":1,"cmd":"attach","devices":["printer"]}\n')
    sim_sock.get_outgoing()
    app_sock.get_outgoing()

    payload = "^XA^FO50,50^ADN,36,20^FDTest^FS^XZ"
    req = json.dumps({"id": 10, "cmd": "print", "key": "box-1", "payload": payload})
    app_sock.inject_data((req + "\n").encode("utf-8"))

    app_responses = app_sock.get_outgoing()
    assert len(app_responses) == 1
    resp = app_responses[0]
    assert resp["ok"] is True
    job_id = resp["job"]
    assert resp["state"] == "queued"

    sim_events = sim_sock.get_outgoing()
    assert len(sim_events) == 1
    evt = sim_events[0]
    assert evt["event"] == "print.job"
    assert evt["job"] == job_id
    assert evt["payload"] == payload

    ack_req = json.dumps({"id": 2, "cmd": "emit", "event": "job", "job": job_id, "state": "done"})
    sim_sock.inject_data((ack_req + "\n").encode("utf-8"))

    app_events = app_sock.get_outgoing()
    assert len(app_events) == 1
    job_evt = app_events[0]
    assert job_evt["event"] == "job"
    assert job_evt["job"] == job_id
    assert job_evt["state"] == "done"


def test_emit_not_attached(qtbot, client_factory):
    session, sock = client_factory()

    req = json.dumps({"id": 1, "cmd": "emit", "event": "scan", "code": "123"})
    sock.inject_data((req + "\n").encode("utf-8"))

    responses = sock.get_outgoing()
    assert len(responses) == 1
    assert responses[0]["ok"] is False
    assert responses[0]["error"]["code"] == "not_attached"