"""
Simulator GUI для ручного тестирования службы devices.
Использует PyQt6 и QLocalSocket для связи через именованный канал.
"""

import datetime
import json
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Симулятор запускают и модулем (python -m devices.simulator), и просто
# файлом из редактора — во втором случае пакета нет, и его нужно найти самому.
try:
    from . import protocol
except ImportError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from devices import protocol  # noqa: F401


class SimulatorWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.socket = None
        self.next_id = 1
        self.device_states = {
            "scanner": None,   # None, "online", "offline", "error"
            "scale": None,
            "printer": None,
        }
        self.init_ui()
        self.setWindowTitle("Devices Service Simulator")
        self.resize(900, 850)

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # Панель подключения
        conn_group = QGroupBox("Подключение")
        conn_layout = QHBoxLayout()
        self.pipe_edit = QLineEdit("prozapas-devices")
        self.connect_btn = QPushButton("Подключиться")
        self.disconnect_btn = QPushButton("Отключиться")
        self.status_label = QLabel("Отключено")
        self.status_label.setStyleSheet("font-weight: bold; color: gray;")
        conn_layout.addWidget(QLabel("Канал:"))
        conn_layout.addWidget(self.pipe_edit)
        conn_layout.addWidget(self.connect_btn)
        conn_layout.addWidget(self.disconnect_btn)
        conn_layout.addWidget(self.status_label)
        conn_layout.addStretch()
        conn_group.setLayout(conn_layout)
        main_layout.addWidget(conn_group)

        # Панель подключения ролей (Attach / Detach)
        roles_group = QGroupBox("Подключение ролей (Эмуляция)")
        roles_layout = QGridLayout()

        self.attach_scanner_btn = QPushButton("Подкл. Сканер")
        self.detach_scanner_btn = QPushButton("Откл. Сканер")
        self.attach_scale_btn = QPushButton("Подкл. Весы")
        self.detach_scale_btn = QPushButton("Откл. Весы")
        self.attach_printer_btn = QPushButton("Подкл. Принтер")
        self.detach_printer_btn = QPushButton("Откл. Принтер")

        roles_layout.addWidget(self.attach_scanner_btn, 0, 0)
        roles_layout.addWidget(self.detach_scanner_btn, 0, 1)
        roles_layout.addWidget(self.attach_scale_btn, 0, 2)
        roles_layout.addWidget(self.detach_scale_btn, 0, 3)
        roles_layout.addWidget(self.attach_printer_btn, 1, 0)
        roles_layout.addWidget(self.detach_printer_btn, 1, 1)
        roles_group.setLayout(roles_layout)
        main_layout.addWidget(roles_group)

        # Панель быстрых команд (эмуляция событий)
        events_group = QGroupBox("Эмуляция событий")
        events_layout = QGridLayout()

        # Сканирование
        events_layout.addWidget(QLabel("Код скана:"), 0, 0)
        self.scan_code_edit = QLineEdit()
        events_layout.addWidget(self.scan_code_edit, 0, 1)
        self.scan_btn = QPushButton("Сканировать")
        events_layout.addWidget(self.scan_btn, 0, 2)

        # Вес
        events_layout.addWidget(QLabel("Вес:"), 1, 0)
        self.weight_edit = QLineEdit()
        events_layout.addWidget(self.weight_edit, 1, 1)
        self.stable_cb = QCheckBox("Стабильно")
        self.stable_cb.setChecked(True)
        events_layout.addWidget(self.stable_cb, 1, 2)
        self.weight_btn = QPushButton("Взвесить")
        events_layout.addWidget(self.weight_btn, 1, 3)

        # Состояние устройства
        events_layout.addWidget(QLabel("Устройство:"), 2, 0)
        self.device_combo = QComboBox()
        self.device_combo.addItems(["scanner", "scale", "printer"])
        events_layout.addWidget(self.device_combo, 2, 1)

        events_layout.addWidget(QLabel("Состояние:"), 2, 2)
        self.state_combo = QComboBox()
        self.state_combo.addItems(["online", "offline", "error"])
        events_layout.addWidget(self.state_combo, 2, 3)

        events_layout.addWidget(QLabel("Причина:"), 3, 0)
        self.reason_edit = QLineEdit()
        events_layout.addWidget(self.reason_edit, 3, 1, 1, 2)
        self.device_state_btn = QPushButton("Сменить состояние")
        events_layout.addWidget(self.device_state_btn, 3, 3)

        events_group.setLayout(events_layout)
        main_layout.addWidget(events_group)

        # Панель команд протокола
        proto_group = QGroupBox("Команды протокола")
        proto_layout = QHBoxLayout()
        self.hello_btn = QPushButton("Hello")
        self.devices_btn = QPushButton("Devices")
        self.subscribe_btn = QPushButton("Подписаться на все")
        self.unsubscribe_btn = QPushButton("Отписаться от всего")
        proto_layout.addWidget(self.hello_btn)
        proto_layout.addWidget(self.devices_btn)
        proto_layout.addWidget(self.subscribe_btn)
        proto_layout.addWidget(self.unsubscribe_btn)
        proto_layout.addStretch()
        proto_group.setLayout(proto_layout)
        main_layout.addWidget(proto_group)

        # Панель печати
        print_group = QGroupBox("Печать")
        print_layout = QGridLayout()

        print_layout.addWidget(QLabel("Ключ:"), 0, 0)
        self.print_key_edit = QLineEdit()
        print_layout.addWidget(self.print_key_edit, 0, 1)

        print_layout.addWidget(QLabel("Формат:"), 0, 2)
        self.print_format_edit = QLineEdit("zpl")
        print_layout.addWidget(self.print_format_edit, 0, 3)

        print_layout.addWidget(QLabel("Payload:"), 1, 0)
        self.print_payload_edit = QTextEdit()
        self.print_payload_edit.setMaximumHeight(80)
        print_layout.addWidget(self.print_payload_edit, 1, 1, 2, 3)

        print_layout.addWidget(QLabel("Копии:"), 3, 0)
        self.print_copies_edit = QLineEdit("1")
        print_layout.addWidget(self.print_copies_edit, 3, 1)

        self.print_btn = QPushButton("Напечатать")
        print_layout.addWidget(self.print_btn, 3, 2)
        self.print_queue_btn = QPushButton("Очередь")
        print_layout.addWidget(self.print_queue_btn, 3, 3)

        print_layout.addWidget(QLabel("Job ID:"), 4, 0)
        self.job_id_edit = QLineEdit()
        print_layout.addWidget(self.job_id_edit, 4, 1)
        self.print_status_btn = QPushButton("Статус")
        print_layout.addWidget(self.print_status_btn, 4, 2)
        self.print_retry_btn = QPushButton("Повторить")
        print_layout.addWidget(self.print_retry_btn, 4, 3)

        print_group.setLayout(print_layout)
        main_layout.addWidget(print_group)

        # Панель весов
        scale_group = QGroupBox("Весы")
        scale_layout = QHBoxLayout()
        self.scale_read_btn = QPushButton("Прочитать вес")
        self.scale_tare_btn = QPushButton("Тара")
        scale_layout.addWidget(self.scale_read_btn)
        scale_layout.addWidget(self.scale_tare_btn)
        scale_layout.addStretch()
        scale_group.setLayout(scale_layout)
        main_layout.addWidget(scale_group)

        # Панель управления
        ctrl_group = QGroupBox("Управление")
        ctrl_layout = QHBoxLayout()
        self.shutdown_btn = QPushButton("Shutdown")
        ctrl_layout.addWidget(self.shutdown_btn)
        ctrl_layout.addStretch()
        ctrl_group.setLayout(ctrl_layout)
        main_layout.addWidget(ctrl_group)

        # Индикаторы состояний устройств
        status_group = QGroupBox("Состояния устройств")
        status_layout = QHBoxLayout()
        self.ind_scan = QLabel("scanner: неизвестно")
        self.ind_weight = QLabel("scale: неизвестно")
        self.ind_printer = QLabel("printer: неизвестно")
        for lbl in (self.ind_scan, self.ind_weight, self.ind_printer):
            lbl.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setMinimumWidth(100)
            lbl.setStyleSheet("background-color: lightgray;")
            status_layout.addWidget(lbl)
        status_layout.addStretch()
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)

        # Окно ZPL (входящие задания)
        zpl_group = QGroupBox("Входящие задания печати (Print Jobs)")
        zpl_layout = QVBoxLayout()
        self.zpl_text = QTextEdit()
        self.zpl_text.setFontFamily("monospace")
        self.zpl_text.setReadOnly(True)
        zpl_layout.addWidget(self.zpl_text)
        zpl_group.setLayout(zpl_layout)
        main_layout.addWidget(zpl_group)

        # Лог-окно
        log_group = QGroupBox("Лог")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setFontFamily("monospace")
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

        # Подключение сигналов
        self.connect_btn.clicked.connect(self.connect_to_server)
        self.disconnect_btn.clicked.connect(self.disconnect_from_server)

        self.scan_btn.clicked.connect(self.send_scan)
        self.weight_btn.clicked.connect(self.send_weight)
        self.device_state_btn.clicked.connect(self.send_device_state)

        self.hello_btn.clicked.connect(self.send_hello)
        self.devices_btn.clicked.connect(self.send_devices)
        self.subscribe_btn.clicked.connect(self.send_subscribe)
        self.unsubscribe_btn.clicked.connect(self.send_unsubscribe)

        self.print_btn.clicked.connect(self.send_print)
        self.print_queue_btn.clicked.connect(self.send_print_queue)
        self.print_status_btn.clicked.connect(self.send_print_status)
        self.print_retry_btn.clicked.connect(self.send_print_retry)

        self.scale_read_btn.clicked.connect(self.send_scale_read)
        self.scale_tare_btn.clicked.connect(self.send_scale_tare)

        self.shutdown_btn.clicked.connect(self.send_shutdown)

        self.attach_scanner_btn.clicked.connect(lambda: self.send_attach(["scanner"]))
        self.detach_scanner_btn.clicked.connect(lambda: self.send_detach(["scanner"]))
        self.attach_scale_btn.clicked.connect(lambda: self.send_attach(["scale"]))
        self.detach_scale_btn.clicked.connect(lambda: self.send_detach(["scale"]))
        self.attach_printer_btn.clicked.connect(lambda: self.send_attach(["printer"]))
        self.detach_printer_btn.clicked.connect(lambda: self.send_detach(["printer"]))

    # ---------- Сокет и отправка ----------
    def connect_to_server(self):
        if self.socket and self.socket.state() == QLocalSocket.LocalSocketState.ConnectedState:
            self.log("Уже подключено", "info")
            return
        pipe_name = self.pipe_edit.text().strip()
        if not pipe_name:
            pipe_name = "prozapas-devices"
        self.socket = QLocalSocket()
        self.socket.connected.connect(self.on_connected)
        self.socket.disconnected.connect(self.on_disconnected)
        self.socket.errorOccurred.connect(self.on_error)
        self.socket.readyRead.connect(self.on_ready_read)
        self.socket.connectToServer(pipe_name)
        self.status_label.setText("Подключение...")
        self.status_label.setStyleSheet("color: orange;")

    def disconnect_from_server(self):
        if self.socket:
            self.socket.disconnectFromServer()
        else:
            self.status_label.setText("Отключено")
            self.status_label.setStyleSheet("color: gray;")

    def on_connected(self):
        self.status_label.setText("Подключено")
        self.status_label.setStyleSheet("color: green;")
        self.log("Подключено к каналу", "info")
        self.send_devices()
        self.send_subscribe()

    def on_disconnected(self):
        self.status_label.setText("Отключено")
        self.status_label.setStyleSheet("color: gray;")
        self.log("Отключено от канала", "info")
        if self.socket:
            self.socket.deleteLater()
            self.socket = None

    def on_error(self, error):
        if error == QLocalSocket.LocalSocketError.ServerNotFoundError:
            msg = "канал не найден — служба не запущена (python -m devices)"
        else:
            msg = self.socket.errorString() if self.socket else str(error)
        self.status_label.setText("Ошибка")
        self.status_label.setStyleSheet("color: red;")
        self.log(f"Ошибка сокета: {msg}", "error")

    def on_ready_read(self):
        if not self.socket:
            return
        data = self.socket.readAll().data().decode('utf-8', errors='ignore')
        lines = data.split('\n')
        for line in lines:
            line = line.strip()
            if line:
                self.process_response(line)

    def send_request(self, cmd, **kwargs):
        if not self.socket or self.socket.state() != QLocalSocket.LocalSocketState.ConnectedState:
            self.log("Не подключено к серверу", "error")
            return
        req = {"id": self.next_id, "cmd": cmd}
        req.update(kwargs)
        self.next_id += 1
        payload = json.dumps(req, ensure_ascii=False, separators=(',', ':')) + '\n'
        try:
            self.socket.write(payload.encode('utf-8'))
            self.socket.flush()
            self.log(f"{json.dumps(req, ensure_ascii=False)}", "sent")
        except Exception as e:
            self.log(f"Ошибка отправки: {e}", "error")

    # ---------- Обработка ответов ----------
    def process_response(self, line):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            self.log(f"← [невалидный JSON] {line}", "error")
            return

        if "event" in data:
            event = data["event"]
            if event == "device":
                self.handle_device_event(data)
            elif event == "print.job":
                self.handle_print_job(data)
            self.log(f"{json.dumps(data, ensure_ascii=False)}", "received")
            return

        if "error" in data:
            self.log(f"{json.dumps(data, ensure_ascii=False)}", "error")
            return

        devices = data.get("devices")
        if isinstance(devices, dict):
            for dev, state in devices.items():
                if dev in self.device_states:
                    self.device_states[dev] = state
            self.update_device_indicators()

        self.log(f"{json.dumps(data, ensure_ascii=False)}", "received")

    def handle_device_event(self, data):
        device = data.get("device") or data.get("id")
        status = data.get("state") or data.get("status")
        reason = data.get("reason", "")
        if device not in self.device_states:
            return
        self.device_states[device] = status
        self.update_device_indicators()
        log_msg = f"событие device: {device} -> {status}"
        if reason:
            log_msg += f" (причина: {reason})"
        self.log(log_msg, "received")

    def handle_print_job(self, data):
        job_id = data.get("job", "")
        payload = data.get("payload", "")
        self.zpl_text.append(f"--- Job: {job_id} ---\n{payload}\n")
        # Авто-подтверждение задания (Auto-ack)
        self.send_request("emit", event="job", job=job_id, state="done")

    def update_device_indicators(self):
        mapping = {
            "scanner": self.ind_scan,
            "scale": self.ind_weight,
            "printer": self.ind_printer,
        }
        for dev, lbl in mapping.items():
            state = self.device_states.get(dev)
            if state is None:
                lbl.setText(f"{dev}: неизвестно")
                lbl.setStyleSheet("background-color: lightgray;")
            elif state == "online":
                lbl.setText(f"{dev}: online")
                lbl.setStyleSheet("background-color: lightgreen;")
            elif state == "offline":
                lbl.setText(f"{dev}: offline")
                lbl.setStyleSheet("background-color: lightcoral;")
            elif state == "error":
                lbl.setText(f"{dev}: error")
                lbl.setStyleSheet("background-color: yellow;")
            else:
                lbl.setText(f"{dev}: {state}")
                lbl.setStyleSheet("background-color: lightgray;")

    # ---------- Логирование ----------
    def log(self, message, msg_type="info"):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        prefix = ""
        if msg_type == "sent":
            prefix = "→"
        elif msg_type == "received":
            prefix = "←"
        elif msg_type == "error":
            prefix = "!"
        elif msg_type == "info":
            prefix = "i"
        full = f"[{timestamp}] {prefix} {message}"
        if msg_type == "error":
            full = f'<font color="red">{full}</font>'
        self.log_text.append(full)
        cursor = self.log_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)

    # ---------- Команды ----------
    def send_hello(self):
        self.send_request("hello", protocol=1, client="simulator")

    def send_devices(self):
        self.send_request("devices")

    def send_subscribe(self):
        events = ["scan", "weight", "device", "job", "print.job"]
        self.send_request("subscribe", events=events)

    def send_unsubscribe(self):
        events = ["scan", "weight", "device", "job", "print.job"]
        self.send_request("unsubscribe", events=events)

    def send_attach(self, devices):
        self.send_request("attach", devices=devices)

    def send_detach(self, devices):
        self.send_request("detach", devices=devices)

    def send_scan(self):
        code = self.scan_code_edit.text().strip()
        if not code:
            self.log("Введите код скана", "error")
            return
        self.send_request("emit", event="scan", code=code)

    def send_weight(self):
        val_text = self.weight_edit.text().strip()
        if not val_text:
            self.log("Введите вес", "error")
            return
        try:
            value = float(val_text)
        except ValueError:
            self.log("Вес должен быть числом", "error")
            return
        stable = self.stable_cb.isChecked()
        self.send_request("emit", event="weight", value=value, unit="g", stable=stable)

    def send_device_state(self):
        device = self.device_combo.currentText()
        state = self.state_combo.currentText()
        reason = self.reason_edit.text().strip()
        kwargs = {"event": "device", "device": device, "state": state}
        if reason:
            kwargs["reason"] = reason
        self.send_request("emit", **kwargs)

    def send_print(self):
        key = self.print_key_edit.text().strip()
        fmt = self.print_format_edit.text().strip() or "zpl"
        payload = self.print_payload_edit.toPlainText().strip()
        copies_text = self.print_copies_edit.text().strip()
        if not key:
            self.log("Введите ключ", "error")
            return
        if not payload:
            self.log("Введите payload", "error")
            return
        try:
            copies = int(copies_text) if copies_text else 1
        except ValueError:
            self.log("Копии должны быть целым числом", "error")
            return
        self.send_request("print", key=key, format=fmt, payload=payload, copies=copies)

    def send_print_queue(self):
        self.send_request("print.queue")

    def send_print_status(self):
        job_id = self.job_id_edit.text().strip()
        if not job_id:
            self.log("Введите Job ID", "error")
            return
        self.send_request("print.status", job=job_id)

    def send_print_retry(self):
        job_id = self.job_id_edit.text().strip()
        if not job_id:
            self.log("Введите Job ID", "error")
            return
        self.send_request("print.retry", job=job_id)

    def send_scale_read(self):
        self.send_request("scale.read", stable=True, timeout_ms=5000)

    def send_scale_tare(self):
        self.send_request("scale.tare")

    def send_shutdown(self):
        self.send_request("shutdown")

    def closeEvent(self, event):
        self.disconnect_from_server()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = SimulatorWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()