# devices — служба работы с оборудованием

Сканер, принтер этикеток и весы держит отдельный процесс; приложение говорит
с ним по именованному каналу. Ниже — запуск, конфигурация и протокол.

## Что это

`devices` — отдельный процесс, который управляет складским оборудованием
(сканер штрихкодов, весы, принтер этикеток) и предоставляет доступ к нему другим
приложениям через **именованный канал** (named pipe).

Приложению не нужно знать о моделях устройств, COM-портах или протоколах весов —
оно отправляет JSON-команды и получает JSON-события.

---

## Требования

| Компонент | Версия |
|---|---|
| ОС | Windows 10+ |
| Python (для запуска из исходников) | 3.13 |
| PyQt6 | 6.11+ |
| pyserial | 3.5 |
| pywin32 | 312 |

Зависимости общие с приложением, ставятся из корня проекта:

```bash
pip install -r ../../requirements.txt
```

Либо собранный `devices.exe` (PyInstaller, Python не нужен).

---

## Запуск службы

### Вместе с приложением (обычный режим)

Запускать руками ничего не нужно: ProЗапас поднимает службу при старте и гасит
при закрытии окна (`desktop/app/service_host.py`). Приложение запускает её
как `python -m devices --idle-timeout 30`: пока приложение подключено,
отсчёт простоя не идёт, а если приложение упадёт, служба не переживёт его
дольше полуминуты.

Если канал уже кто-то обслуживает — служба запущена вручную или работает вторая
копия приложения, — ProЗапас просто подключается к ней и при выходе **не**
останавливает: чужой процесс не наш.

Служба лежит рядом с приложением, в каталоге `desktop`; задать
другой путь можно переменной окружения `PROZAPAS_DEVICES_SERVICE`.

### Из исходников

```bash
python -m devices
```

Служба:
1. Создаёт конфиг `%ProgramData%\ProZapas\devices.toml` (при первом запуске).
2. Открывает устройства из конфига (недоступные остаются в состоянии `offline`).
3. Поднимает named pipe `\\.\pipe\prozapas-devices`.
4. Печатает `ready` в stderr — по этому сигналу можно подключаться.

### Полезные флаги CLI

```bash
python -m devices --version           # версия службы
python -m devices --list-ports       # COM-порты с описанием и VID:PID
python -m devices --list-printers    # список принтеров
python -m devices --idle-timeout 60  # свой таймаут простоя (0 — без него)
```

`--idle-timeout` перекрывает `idle_timeout_sec` из конфига; `0` отключает выход
по простою.

### Остановка

- **Ctrl+C** в консоли — корректное завершение с закрытием портов.
- Команда `shutdown` по каналу (см. ниже).
- Таймаут холостого хода — если ни один клиент не подключён дольше
  `idle_timeout_sec` (по умолчанию 30 с), служба завершается автоматически.

### Коды возврата

| Код | Значение |
|---|---|
| 0 | Штатное завершение |
| 2 | Канал занят (другой экземпляр уже запущен) |
| 3 | Ошибка конфигурации |

---

## Конфигурация

Файл: `%ProgramData%\ProZapas\devices.toml`

```toml
[pipe]
name = "prozapas-devices"      # имя именованного канала
idle_timeout_sec = 30           # 0 — не завершаться без клиентов

[scanner]
port = ""                       # пусто — устройство отключено (эмуляция)
baud = 115200
fake = true                     # true — подставной драйвер без реального порта

[scale]
port = "COM3"
baud = 115200
fake = true                     # true — эмуляция без порта, как у сканера
step_g = 10                     # шаг весов (г) для оценки устойчивости
command_tare = "TARE"
command_calib = "CALIB"

[printer]
name = ""                       # пусто — stub пишет в output_file
encoding = "utf-8"              # приложение шлёт ZPL с ^CI28, то есть UTF-8
output_file = ""                # пусто — %TEMP%

[log]
level = "info"                  # info | debug | warning | error
path = ""                       # пусто — %ProgramData%\ProZapas\devices.log
```

---

### Проверка без железа

Сканер, весы и принтер держат режим эмуляции: `fake = true` у сканера и весов,
пустое `name` у принтера. Все трое при этом `online`, а показания подаются
снаружи — из симулятора или консоли:

```bash
python -m devices.cli scan WH1281187100421   # событие сканера
python -m devices.cli weight 16200 --stable  # весы показали 16.2 кг
python -m devices.cli scale read             # столько отдадут приложению
```

Весы в эмуляции сами ничего не выдумывают: `scale.read` возвращает последнее
поданное значение, а без него отвечает `scale_timeout` — приложение тогда
просит ввести вес вручную. `scale.tare` обнуляет показание.

Для реального оборудования: у весов `fake = false` и настоящий `port`, у
сканера то же самое, у принтера — точное имя из `--list-printers`.

---

## Протокол (как общаться со службой)

### Транспорт

Именованный канал Windows: `\\.\pipe\prozapas-devices` (имя настраивается).

**Как указывать адрес.** Qt-клиент (`QLocalSocket.connectToServer`) ждёт
**короткое** имя — `prozapas-devices`: префикс `\\.\pipe\` Qt подставляет сам, и
полный путь даёт `ServerNotFoundError`. Клиенты на win32 API или Node открывают
файл напрямую и, наоборот, требуют полный путь `\\.\pipe\prozapas-devices`.

Формат: **один JSON-объект в строке**, UTF-8, разделитель `\n`.

Три типа сообщений:

```
Запрос   → {"id": 17, "cmd": "print", ...}       от клиента, всегда с id
Ответ    ← {"id": 17, "ok": true, ...}           от службы, тот же id
Событие  ← {"event": "scan", ...}                от службы, без id
```

- `id` — целое число, счётчик в пределах соединения.
- Ответы могут приходить не по порядку.
- Неизвестные команды не игнорируются — на них приходит ошибка `unknown_command`.

---

### 1. Приветствие (hello)

Первое сообщение после подключения. Проверяет совместимость версий протокола.

```json
→ {"id": 1, "cmd": "hello", "protocol": 1}
← {"id": 1, "ok": true, "service": "devices", "protocol": [1]}
```

Если версия несовместима:

```json
← {"id": 1, "ok": false, "error": {"code": "incompatible", "message": "protocol 2 not supported"}}
```

---

### 2. Состояние устройств (devices)

```json
→ {"id": 2, "cmd": "devices"}
← {"id": 2, "ok": true, "devices": {"scanner": "online", "scale": "offline", "printer": "online"}}
```

Состояния: `online`, `offline`, `error`.

---

### 3. Подписка на события (subscribe / unsubscribe)

События доставляются только подписчикам. Без подписки драйвер продолжает работать,
но в канал ничего не отправляется.

Доступные события: `scan`, `weight`, `device`, `job`.

```json
→ {"id": 3, "cmd": "subscribe", "events": ["scan", "weight", "device"]}
← {"id": 3, "ok": true, "subscribed": ["device", "scan", "weight"]}

→ {"id": 4, "cmd": "unsubscribe", "events": ["scan"]}
← {"id": 4, "ok": true, "subscribed": ["device", "weight"]}
```

Подписки накапливаются — повторный `subscribe` добавляет к текущему набору.

---

### 4. Печать (print)

```json
→ {"id": 10, "cmd": "print", "key": "box-SH3029201204-01", "format": "zpl",
   "payload": "^XA^FO40,40^A0N,30,30^FDSH3029201204-01^FS^XZ", "copies": 1}
← {"id": 10, "ok": true, "job": "j-104", "state": "queued"}
```

| Поле | Тип | Описание |
|---|---|---|
| `key` | str | Ключ идемпотентности — повторный `print` с тем же ключом возвращает текущее задание, а не создаёт новое |
| `format` | str | `"zpl"`, `"tspl"` или `"raw"` |
| `payload` | str | Данные для принтера (ZPL-команды, TSPL и т.д.) |
| `copies` | int | Количество копий (по умолчанию 1) |

#### Статус задания печати

```json
→ {"id": 11, "cmd": "print.status", "job": "j-104"}
← {"id": 11, "ok": true, "job": "j-104", "state": "done"}
```

#### Очередь печати

```json
→ {"id": 12, "cmd": "print.queue"}
← {"id": 12, "ok": true, "jobs": [{"job": "j-104", "state": "done"}]}
```

#### Повтор печати

```json
→ {"id": 13, "cmd": "print.retry", "job": "j-104"}
← {"id": 13, "ok": true, "job": "j-104", "state": "queued"}
```

Состояния задания: `queued` → `printing` → `done` / `failed`.
При ошибке — 3 повтора с паузами 2, 5, 10 с, затем `failed`.

---

### 5. Весы (scale)

#### Чтение веса

```json
→ {"id": 20, "cmd": "scale.read", "stable": true, "timeout_ms": 3000}
← {"id": 20, "ok": true, "value": 152.30, "unit": "g", "stable": true}
```

Если устойчивое показание не получено в течение таймаута:

```json
← {"id": 20, "ok": false, "error": {"code": "scale_timeout", "message": "no stable reading within timeout"}}
```

#### Тарировка

```json
→ {"id": 21, "cmd": "scale.tare"}
← {"id": 21, "ok": true}
```

---

### 6. Остановка службы (shutdown)

```json
→ {"id": 99, "cmd": "shutdown"}
← {"id": 99, "ok": true}
```

---

### События

События приходят без `id` — это асинхронные уведомления от службы.

#### Сканирование штрихкода

```json
← {"event": "scan", "code": "4607025398002", "device": "scanner"}
```

#### Показания весов

```json
← {"event": "weight", "value": 152.30, "unit": "g", "stable": true}
```

Только при активной подписке `subscribe events=["weight"]`.

#### Изменение состояния устройства

```json
← {"event": "device", "id": "printer", "state": "offline", "reason": "port error: ..."}
```

#### Изменение состояния задания печати

```json
← {"event": "job", "job": "j-104", "state": "printing"}
← {"event": "job", "job": "j-104", "state": "done"}
← {"event": "job", "job": "j-105", "state": "failed", "error": "printer not found"}
```

---

### Коды ошибок

| Код | Когда |
|---|---|
| `bad_request` | Некорректный JSON или отсутствуют обязательные поля |
| `unknown_command` | Неизвестная команда |
| `no_device` | Запрошенное устройство не существует |
| `printer_offline` | Принтер не подключён |
| `scale_timeout` | Весы не выдали устойчивое показание за таймаут |
| `busy` | Устройство занято другим запросом |
| `internal` | Внутренняя ошибка службы |
| `incompatible` | Несовместимая версия протокола |

Формат ошибки:

```json
{"id": 17, "ok": false, "error": {"code": "printer_offline", "message": "Принтер не отвечает"}}
```

---

## Пример интеграции (Python)

```python
import json
import win32file
import win32pipe

PIPE_NAME = r"\\.\pipe\prozapas-devices"


def connect():
    """Подключиться к каналу службы."""
    handle = win32file.CreateFile(
        PIPE_NAME,
        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
        0,
        None,
        win32file.OPEN_EXISTING,
        0,
        None,
    )
    return handle


def send(handle: int, frame: dict) -> None:
    """Отправить JSON-кадр в канал."""
    data = (json.dumps(frame, separators=(",", ":")) + "\n").encode("utf-8")
    win32file.WriteFile(handle, data)


def recv(handle: int) -> dict | None:
    """Прочитать один JSON-кадр из канала."""
    _, data = win32file.ReadFile(handle, 4096)
    line = data.decode("utf-8").strip()
    if not line:
        return None
    return json.loads(line)


def main():
    handle = connect()

    # 1. Приветствие
    send(handle, {"id": 1, "cmd": "hello", "protocol": 1})
    resp = recv(handle)
    print("Hello:", resp)

    # 2. Состояние устройств
    send(handle, {"id": 2, "cmd": "devices"})
    resp = recv(handle)
    print("Devices:", resp)

    # 3. Подписка на все события
    send(handle, {"id": 3, "cmd": "subscribe", "events": ["scan", "weight", "device", "job"]})
    resp = recv(handle)
    print("Subscribed:", resp)

    # 4. Чтение событий в цикле
    while True:
        msg = recv(handle)
        if msg is None:
            break
        if "event" in msg:
            print(f"Event: {msg['event']}: {msg}")
        else:
            print(f"Response: {msg}")


if __name__ == "__main__":
    main()
```

---

## Пример интеграции (Node.js)

```javascript
const net = require('net');

const PIPE_PATH = '\\\\.\\pipe\\prozapas-devices';

const client = net.connect(PIPE_PATH, () => {
    let id = 0;
    const nextId = () => ++id;

    // Приветствие
    client.write(JSON.stringify({ id: nextId(), cmd: 'hello', protocol: 1 }) + '\n');

    // Подписка на события
    client.write(JSON.stringify({
        id: nextId(),
        cmd: 'subscribe',
        events: ['scan', 'weight', 'device', 'job'],
    }) + '\n');

    // Запрос состояния устройств
    client.write(JSON.stringify({ id: nextId(), cmd: 'devices' }) + '\n');
});

let buffer = '';

client.on('data', (data) => {
    buffer += data.toString('utf-8');
    const lines = buffer.split('\n');
    buffer = lines.pop(); // неполная строка остаётся в буфере

    for (const line of lines) {
        if (!line.trim()) continue;
        const msg = JSON.parse(line);

        if (msg.event) {
            console.log(`[EVENT] ${msg.event}:`, msg);
        } else {
            console.log(`[RESP] id=${msg.id} ok=${msg.ok}:`, msg);
        }
    }
});

client.on('end', () => {
    console.log('Disconnected from device service');
});
```

---

## Отладочная консоль

Входит в состав службы. Позволяет эмулировать устройства без реального железа:

```bash
python -m devices.cli scan WH1281187100421
python -m devices.cli weight 22.4 --stable
python -m devices.cli device printer offline --reason unplugged
python -m devices.cli print-queue
```

---

## Логирование

Файл: `%ProgramData%\ProZapas\devices.log` (ротация: 5 файлов × 2 МБ).

| Уровень | Что логируется |
|---|---|
| `info` | Старт службы, состояния устройств, задания печати |
| `debug` | Каждое сообщение канала целиком, показания весов |

Для отладки проблем с оборудованием установите `level = "debug"` в конфиге.

---

## Типичный сценарий работы бэкенда

```
1. Запустить devices.exe (или python -m devices).
2. Дождаться "ready" в stderr.
3. Подключиться к \\.\pipe\prozapas-devices.
4. Отправить hello для проверки версии.
5. Отправить subscribe на нужные события (scan, weight, job).
6. В цикле читать сообщения из канала:
   - Ответы на команды — по полю "id".
   - События — по полю "event".
7. Для печати — отправить print с ключом, форматом и ZPL-данными.
8. Для чтения веса — отправить scale.read.
9. При остановке — отправить shutdown или просто закрыть соединение.
```
