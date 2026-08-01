"""Data layer for ProЗапас.

Everything the application shows or changes lives in one JSON document,
``mock_data.json``. The file is versioned and has four kinds of content:

    reference   catalogue, warehouses, roles, sections — rarely edited
    stock       one row per article, quantities broken down by warehouse
    documents   orders, receiving batches and their progress, packing
    accounts    users, permissions, the signed-in session

Nothing is duplicated between sections: a stock row and an order position carry
an article number, and the name, unit and weight are looked up in the catalogue.
Seed data is only used when the file does not exist yet; from then on the file
is the single source of truth and every mutation writes it back.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta

SCHEMA_VERSION = 2

_DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_FILE = os.path.join(_DATA_DIR, "mock_data.json")


# ── date helpers ───────────────────────────────────────────────────────────
def _ru_date(d: datetime) -> str:
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def format_now() -> str:
    d = datetime.now()
    return f"{_ru_date(d)} {d.hour:02d}:{d.minute:02d}"


def parse_ru_datetime(s: str):
    if not s or s == "—":
        return None
    date_part = s.split(" ")[0]
    try:
        d, m, y = (int(x) for x in date_part.split("."))
        return datetime(y, m, d)
    except (ValueError, TypeError):
        return None


# ── passwords ──────────────────────────────────────────────────────────────
# PBKDF2-HMAC-SHA256 from the standard library: no extra dependency, and the
# file never holds a password in clear text.
_PBKDF2_ITERATIONS = 120_000
DEFAULT_PASSWORD = "prozapas"       # выдаётся сотруднику при заведении учётной записи


def hash_password(password: str) -> str:
    """`pbkdf2_sha256$<итераций>$<соль>$<хеш>` — всё нужное для проверки."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                 _PBKDF2_ITERATIONS)
    return "$".join(("pbkdf2_sha256", str(_PBKDF2_ITERATIONS),
                     base64.b64encode(salt).decode(), base64.b64encode(digest).decode()))


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = (stored or "").split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     base64.b64decode(salt_b64), int(iterations))
    except (ValueError, TypeError):
        return False
    # сравнение за постоянное время: иначе по задержке можно подбирать хеш
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def initials(fio: str) -> str:
    parts = fio.strip().split()
    a = parts[0][0] if len(parts) > 0 and parts[0] else ""
    b = parts[1][0] if len(parts) > 1 and parts[1] else ""
    return (a + b).upper()


def short_name(fio: str) -> str:
    """«Кузнецов Игорь Александрович» → «Кузнецов И.А.»"""
    parts = fio.strip().split()
    if not parts:
        return ""
    tail = "".join(f"{p[0]}." for p in parts[1:3] if p)
    return f"{parts[0]} {tail}".strip()


# ── seed data ──────────────────────────────────────────────────────────────
_SEED_WAREHOUSES = [
    ("Склад №1", "Соколов П.Н."),
    ("Склад №3", "Морозова Е.В."),
    ("Склад №4", "Титов Р.А."),
    ("Центральный склад", "Волкова М.С."),
]

_SEED_ROLES = [
    ("manager", "Менеджер"),
    ("stockman", "Кладовщик"),
    ("admin", "Администратор"),
]

_SEED_SECTIONS = [
    ("orders", "Заказы"), ("shipping", "Отгрузка"), ("receiving", "Приёмка"),
    ("catalog", "Справочник"), ("stock", "Остатки"), ("users", "Пользователи"),
]

# (code1c, article, name, unit, unitWeight)
_SEED_CATALOG = [
    ("ТМЦ-00421", "100421", "Болт М8×40 ГОСТ 7798", "шт.", 0.02),
    ("ТМЦ-00433", "100433", "Гайка М8 ГОСТ 5915", "шт.", 0.01),
    ("ТМЦ-01187", "201187", "Подшипник 6205-2RS", "шт.", 0.08),
    ("ТМЦ-01204", "201204", "Ремень приводной А-1250", "шт.", 0.45),
    ("ТМЦ-00087", "300087", "Редуктор РЦД-350 в сборе", "шт.", 42.0),
    ("ТМЦ-00091", "300091", "Насос центробежный НЦ-40", "шт.", 18.5),
    ("ТМЦ-00458", "100458", "Лист стальной 2×1250×2500", "лист", 72.5),
    ("ТМЦ-00477", "100477", "Уголок стальной 50×50×5", "шт.", 4.5),
    ("ТМЦ-00512", "100512", "Труба стальная 32×2", "м", 1.6),
    ("ТМЦ-00098", "300098", "Электродвигатель АИР90", "шт.", 24.0),
    ("ТМЦ-01340", "201340", "Ремень клиновой Б-1400", "шт.", 0.35),
    ("ТМЦ-00655", "100655", "Шайба М8 ГОСТ 6402", "шт.", 0.005),
    ("ТМЦ-00701", "100701", "Винт М6×20 ГОСТ 17475", "шт.", 0.008),
    ("ТМЦ-01412", "201412", "Подшипник 6208-2RS", "шт.", 0.15),
    ("ТМЦ-00133", "300133", "Насос шестерённый НШ-10", "шт.", 6.2),
    ("ТМЦ-00812", "100812", "Швеллер 10П ГОСТ 8240", "м", 8.5),
    ("ТМЦ-00159", "300159", "Редуктор червячный РЧУ-125", "шт.", 18.7),
    ("ТМЦ-00933", "100933", "Гайка М10 ГОСТ 5915", "шт.", 0.015),
    ("ТМЦ-01055", "201055", "Муфта соединительная МУВП-40", "шт.", 2.1),
    ("ТМЦ-00950", "100950", "Шпонка 8×7×40", "шт.", 0.03),
    ("ТМЦ-01600", "201600", "Цепь приводная ПР-19.05", "м", 1.9),
    ("ТМЦ-00210", "300210", "Компрессор поршневой К-25", "шт.", 55.0),
]

# article -> {warehouse: quantity}; zero balances are simply absent
_SEED_STOCK = {
    "100421": {"Склад №1": 800, "Склад №4": 150},
    "100433": {"Склад №3": 600},
    "201187": {"Склад №1": 12, "Склад №4": 30},
    "201204": {"Склад №3": 25, "Склад №4": 8},
    "300087": {"Центральный склад": 3},
    "300091": {"Центральный склад": 11},
    "100458": {"Склад №3": 6, "Центральный склад": 10},
    "100477": {"Склад №1": 40, "Центральный склад": 60},
    "100512": {"Склад №3": 120, "Центральный склад": 200},
    "300098": {"Склад №1": 3, "Склад №4": 2, "Центральный склад": 6},
    "201340": {"Склад №1": 54, "Склад №4": 12},
    "100655": {"Склад №3": 3200, "Центральный склад": 1800},
    "100701": {"Склад №1": 900, "Склад №4": 400},
    "201412": {"Склад №3": 18, "Склад №4": 10},
    "300133": {"Склад №1": 4, "Склад №4": 3, "Центральный склад": 5},
    "100812": {"Склад №3": 40, "Центральный склад": 60},
    "300159": {"Склад №1": 2, "Склад №4": 1, "Центральный склад": 3},
    "100933": {"Склад №3": 1500, "Центральный склад": 900},
    "201055": {"Склад №1": 6, "Склад №4": 4, "Центральный склад": 8},
    "100950": {"Склад №3": 220, "Центральный склад": 150},
    "201600": {"Склад №3": 30, "Склад №4": 20},
    "300210": {"Склад №1": 1, "Центральный склад": 2},
}

# quantity held for customer orders, by article
_SEED_RESERVED = {
    "100421": 300, "201187": 20, "201204": 12, "300087": 3, "300091": 4,
    "100477": 30, "300098": 2, "100701": 200, "201412": 12, "300133": 3,
    "300159": 2, "201055": 4,
}


def _min_qty(total: int) -> int:
    """Reorder point: sparse equipment is watched closer than bulk hardware."""
    if total < 100:
        return 5
    if total < 1000:
        return 50
    return 500


def _seed_stock():
    rows = []
    for _code, article, *_rest in _SEED_CATALOG:
        by_warehouse = _SEED_STOCK.get(article, {})
        total = sum(by_warehouse.values())
        rows.append({
            "article": article,
            "byWarehouse": dict(by_warehouse),
            "reserved": _SEED_RESERVED.get(article, 0),
            "minQty": _min_qty(total),
        })
    return rows


def _seed_orders():
    responsible = {w: r for w, r in _SEED_WAREHOUSES}
    author = short_name(_SEED_USERS[0][0])

    def mk(oid, number, direction, status, wh, days_ago, positions):
        created = datetime(2026, 7, 22 - days_ago, 9, 0)
        created_str = _ru_date(created) + " 09:00"
        history = [{"status": "created", "dateTime": created_str}]
        ship_dt, accepted = "—", None
        if status != "created":
            history.append({"status": "processing", "dateTime": created_str})
        if status in ("shipped", "received"):
            ship = created + timedelta(days=1)
            ship_dt = _ru_date(ship) + " 12:00"
            history.append({"status": "shipped", "dateTime": ship_dt})
        if status == "received":
            acc = created + timedelta(days=2)
            accepted = _ru_date(acc) + " 10:30"
            history.append({"status": "received", "dateTime": accepted})
        return {
            "id": oid, "number": number, "direction": direction, "status": status,
            "counterpartyWarehouse": wh,
            "counterpartyResponsible": responsible.get(wh, "—"),
            "createdDateTime": created_str, "shipDateTime": ship_dt, "acceptedAt": accepted,
            "responsible": author, "positions": positions, "history": history,
        }

    def pos(article, qty):
        return {"article": article, "qty": qty}

    return [
        mk(1, "2001", "ours", "created", "Склад №1", 1, [pos("100421", 500)]),
        mk(2, "2002", "ours", "processing", "Склад №3", 3, [pos("201187", 20), pos("201204", 15)]),
        mk(3, "2003", "ours", "processing", "Центральный склад", 5, [pos("100458", 4)]),
        mk(4, "2004", "ours", "received", "Склад №4", 8, [pos("100477", 30)]),
        mk(5, "2005", "ours", "created", "Центральный склад", 0, [pos("201412", 25)]),
        mk(11, "2006", "ours", "processing", "Склад №1", 2, [pos("100433", 300)]),
        mk(12, "2007", "ours", "received", "Склад №3", 10, [pos("100512", 60)]),
        mk(13, "2008", "ours", "created", "Склад №4", 0, [pos("300098", 2)]),
        mk(14, "2009", "ours", "declined", "Центральный склад", 6, [pos("100421", 200)]),
        mk(15, "2010", "ours", "cancelled", "Склад №1", 4, [pos("201204", 12)]),
        mk(16, "2011", "ours", "processing", "Склад №3", 1, [pos("100477", 25)]),
        mk(17, "2012", "ours", "received", "Склад №4", 12, [pos("201187", 8)]),
        mk(18, "2013", "ours", "created", "Склад №1", 0, [pos("100458", 3)]),
        mk(19, "2014", "ours", "processing", "Центральный склад", 3, [pos("100433", 150)]),
        mk(20, "2015", "ours", "received", "Склад №3", 9, [pos("300098", 1)]),
        mk(6, "3001", "theirs", "created", "Склад №3", 0, [pos("100433", 200)]),
        mk(7, "3002", "theirs", "processing", "Склад №1", 2, [pos("100512", 40)]),
        mk(8, "3003", "theirs", "shipped", "Центральный склад", 4, [pos("300098", 2)]),
        mk(9, "3004", "theirs", "received", "Склад №4", 6, [pos("100655", 800)]),
        mk(10, "3005", "theirs", "created", "Склад №1", 0, [pos("201204", 10)]),
        mk(21, "3006", "theirs", "processing", "Склад №3", 1, [pos("100421", 400)]),
        mk(22, "3007", "theirs", "shipped", "Склад №4", 3, [pos("201187", 15)]),
        mk(23, "3008", "theirs", "received", "Центральный склад", 8, [pos("100477", 20)]),
        mk(24, "3009", "theirs", "created", "Склад №1", 0, [pos("100458", 5)]),
        mk(25, "3010", "theirs", "declined", "Склад №3", 5, [pos("201412", 30)]),
        mk(26, "3011", "theirs", "processing", "Склад №4", 2, [pos("100512", 90)]),
        mk(27, "3012", "theirs", "shipped", "Центральный склад", 4, [pos("100433", 500)]),
        mk(28, "3013", "theirs", "received", "Склад №1", 11, [pos("300098", 3)]),
        mk(29, "3014", "theirs", "created", "Склад №3", 0, [pos("201204", 18)]),
        mk(30, "3015", "theirs", "processing", "Склад №4", 1, [pos("100421", 250)]),
        mk(60, "3026", "theirs", "processing", "Склад №1", 1, [
            pos("100421", 800), pos("100458", 5), pos("100477", 12), pos("201187", 30)]),
        mk(63, "3029", "theirs", "created", "Центральный склад", 0, [
            pos("201204", 18), pos("201187", 24), pos("100421", 600), pos("100433", 600)]),
    ]


_SEED_USERS = [
    ("Кузнецов Игорь Александрович", "admin", "Центральный склад", "Начальник склада", "active", "+7 916 204-11-87", "i.kuznetsov@stalker.ru", "12.03.2019", "24.07.2026 08:42"),
    ("Соколов Пётр Николаевич", "stockman", "Склад №1", "Кладовщик", "active", "+7 903 551-22-14", "p.sokolov@stalker.ru", "05.06.2020", "24.07.2026 07:58"),
    ("Морозова Елена Викторовна", "manager", "Склад №3", "Менеджер по логистике", "active", "+7 925 118-77-03", "e.morozova@stalker.ru", "18.09.2021", "23.07.2026 17:20"),
    ("Титов Роман Андреевич", "stockman", "Склад №4", "Кладовщик", "active", "+7 909 330-45-61", "r.titov@stalker.ru", "02.02.2022", "24.07.2026 09:05"),
    ("Волкова Мария Сергеевна", "manager", "Центральный склад", "Менеджер по закупкам", "active", "+7 917 442-90-08", "m.volkova@stalker.ru", "27.11.2020", "24.07.2026 08:15"),
    ("Новиков Дмитрий Олегович", "stockman", "Склад №1", "Комплектовщик", "active", "+7 985 220-14-30", "d.novikov@stalker.ru", "14.04.2023", "23.07.2026 16:40"),
    ("Козлова Анна Павловна", "manager", "Склад №3", "Менеджер заказов", "active", "+7 926 771-08-52", "a.kozlova@stalker.ru", "09.07.2021", "24.07.2026 08:33"),
    ("Лебедев Сергей Иванович", "stockman", "Склад №4", "Кладовщик", "blocked", "+7 903 118-64-27", "s.lebedev@stalker.ru", "21.10.2019", "11.05.2026 14:02"),
    ("Егорова Ольга Дмитриевна", "manager", "Склад №1", "Менеджер по логистике", "active", "+7 916 905-33-71", "o.egorova@stalker.ru", "30.01.2022", "24.07.2026 09:12"),
    ("Павлов Артём Викторович", "admin", "Склад №3", "Администратор системы", "active", "+7 925 604-77-19", "a.pavlov@stalker.ru", "15.08.2018", "24.07.2026 08:01"),
    ("Семёнов Никита Андреевич", "stockman", "Центральный склад", "Приёмщик", "active", "+7 909 442-11-06", "n.semenov@stalker.ru", "03.03.2024", "23.07.2026 18:47"),
    ("Фёдорова Татьяна Юрьевна", "manager", "Склад №4", "Менеджер по закупкам", "active", "+7 917 330-88-52", "t.fedorova@stalker.ru", "22.05.2021", "24.07.2026 07:44"),
    ("Михайлов Владимир Петрович", "stockman", "Склад №1", "Кладовщик", "active", "+7 985 771-20-63", "v.mihaylov@stalker.ru", "19.12.2020", "24.07.2026 08:50"),
    ("Виноградова Ирина Олеговна", "manager", "Склад №3", "Менеджер заказов", "active", "+7 926 118-45-90", "i.vinogradova@stalker.ru", "07.06.2023", "23.07.2026 15:33"),
    ("Богданов Алексей Сергеевич", "stockman", "Склад №4", "Комплектовщик", "blocked", "+7 903 905-14-08", "a.bogdanov@stalker.ru", "11.09.2019", "02.03.2026 10:21"),
    ("Орлова Наталья Игоревна", "manager", "Центральный склад", "Менеджер по логистике", "active", "+7 916 442-77-31", "n.orlova@stalker.ru", "26.02.2022", "24.07.2026 09:00"),
    ("Киселёв Максим Дмитриевич", "stockman", "Склад №1", "Приёмщик", "active", "+7 925 220-63-14", "m.kiselev@stalker.ru", "13.11.2023", "24.07.2026 08:22"),
    ("Макарова Светлана Андреевна", "admin", "Центральный склад", "Администратор", "active", "+7 917 604-11-90", "s.makarova@stalker.ru", "04.04.2019", "24.07.2026 08:37"),
    ("Никитин Павел Романович", "stockman", "Склад №3", "Кладовщик", "active", "+7 909 771-33-27", "p.nikitin@stalker.ru", "28.07.2022", "23.07.2026 17:05"),
    ("Захарова Юлия Владимировна", "manager", "Склад №4", "Менеджер по закупкам", "active", "+7 985 330-45-08", "y.zaharova@stalker.ru", "16.01.2024", "24.07.2026 08:19"),
]


def _seed_users():
    keys = ["fullName", "role", "warehouse", "position", "status",
            "phone", "email", "hireDate", "lastLogin"]
    users = []
    for i, row in enumerate(_SEED_USERS):
        user = dict({"id": i + 1}, **dict(zip(keys, row)))
        user["login"] = user["email"].split("@")[0].lower()
        user["passwordHash"] = hash_password(DEFAULT_PASSWORD)
        users.append(user)
    return users


def _seed_permissions():
    p = {role: {} for role, _ in _SEED_ROLES}
    for sid, _ in _SEED_SECTIONS:
        p["admin"][sid] = {"view": True, "edit": True}
        p["manager"][sid] = {"view": True, "edit": False}
        p["stockman"][sid] = {"view": True, "edit": False}
    p["manager"]["orders"] = {"view": True, "edit": True}
    p["manager"]["catalog"] = {"view": True, "edit": True}
    p["manager"]["users"] = {"view": False, "edit": False}
    p["stockman"]["shipping"] = {"view": True, "edit": True}
    p["stockman"]["receiving"] = {"view": True, "edit": True}
    p["stockman"]["stock"] = {"view": True, "edit": True}
    p["stockman"]["users"] = {"view": False, "edit": False}
    return p


# (id, number, supplier, shipDateTime, createdDateTime, [(article, boxes, boxWeight)])
_SEED_BATCHES = [
    (1, "1187", "«Метизпром»", "21.07.2026 09:40", "18.07.2026 14:05",
     [("100421", 1, 22.4), ("100433", 1, 18.0), ("201187", 3, 8.2), ("100458", 2, 145.0)]),
    (2, "1192", "«Металлторг»", "21.07.2026 11:15", "19.07.2026 10:22",
     [("100458", 3, 145.0), ("100477", 2, 60.0)]),
    (3, "1175", "ООО «ПодшипникСнаб»", "20.07.2026 16:30", "16.07.2026 09:50",
     [("201187", 2, 8.2), ("201204", 1, 4.5)]),
    (4, "1201", "«Стальресурс»", "22.07.2026 08:15", "19.07.2026 12:40",
     [("100477", 2, 60.0)]),
    (5, "1204", "«Метизпром»", "22.07.2026 10:00", "20.07.2026 09:15",
     [("100421", 2, 22.4)]),
    (6, "1206", "ООО «ПодшипникСнаб»", "22.07.2026 13:20", "20.07.2026 15:30",
     [("201187", 1, 8.2)]),
    (7, "1209", "«Металлторг»", "23.07.2026 09:00", "21.07.2026 11:05",
     [("100458", 1, 145.0)]),
    (8, "1211", "«Стальресурс»", "23.07.2026 14:45", "21.07.2026 16:10",
     [("100477", 1, 60.0)]),
    (9, "1213", "«Метизпром»", "24.07.2026 08:30", "22.07.2026 10:50",
     [("100433", 1, 18.0)]),
    (10, "1216", "«Металлторг»", "24.07.2026 09:50", "22.07.2026 12:15",
     [("201204", 2, 4.5)]),
    (11, "1218", "ООО «ПодшипникСнаб»", "24.07.2026 11:30", "22.07.2026 14:40",
     [("201187", 2, 8.2)]),
    (12, "1221", "«Стальресурс»", "24.07.2026 14:05", "23.07.2026 08:20",
     [("100458", 3, 145.0)]),
    (13, "1223", "«Метизпром»", "25.07.2026 08:00", "23.07.2026 10:05",
     [("100421", 1, 22.4), ("100433", 1, 18.0)]),
]


def _seed_batches():
    return [
        {"id": bid, "number": number, "supplier": supplier,
         "shipDateTime": ship, "createdDateTime": created,
         "positions": [{"article": a, "boxes": n, "boxWeight": w}
                       for a, n, w in positions]}
        for bid, number, supplier, ship, created, positions in _SEED_BATCHES
    ]


def _default_store():
    return {
        "version": SCHEMA_VERSION,
        "reference": {
            "warehouseCode": "128",
            "warehouses": [{"name": n, "responsible": r} for n, r in _SEED_WAREHOUSES],
            "roles": [{"id": r, "label": l} for r, l in _SEED_ROLES],
            "sections": [{"id": s, "label": l} for s, l in _SEED_SECTIONS],
            "catalog": [{"code1c": c, "article": a, "name": n, "unit": u, "unitWeight": w}
                        for c, a, n, u, w in _SEED_CATALOG],
        },
        "stock": _seed_stock(),
        "orders": _seed_orders(),
        "users": _seed_users(),
        "permissions": _seed_permissions(),
        "receiving": {"batches": _seed_batches(), "progress": {}},
        "shipping": {"packing": {}},
        "session": {"currentUserId": None, "remember": False},
    }


# ── load / save ────────────────────────────────────────────────────────────
_cache = None


def _migrate(data):
    """Carry an older file over into the current layout so saved work is not
    lost. Handles both the pre-versioned shape and version 1."""
    fresh = _default_store()
    for key in ("orders", "users"):
        if data.get(key):
            fresh[key] = data[key]
    # версия 1 не знала про учётные данные: логин из почты, пароль по умолчанию
    for user in fresh["users"]:
        user.setdefault("login", (user.get("email") or "").split("@")[0].lower())
        if not user.get("passwordHash"):
            user["passwordHash"] = hash_password(DEFAULT_PASSWORD)
    if data.get("perms"):
        fresh["permissions"] = data["perms"]
    auth = data.get("auth") or {}
    if auth.get("id"):
        fresh["session"]["currentUserId"] = auth["id"]
    for section in ("reference", "stock", "permissions", "receiving", "shipping"):
        if data.get(section):
            fresh[section] = data[section]
    if data.get("session"):
        fresh["session"].update(data["session"])
    for item in reversed(data.get("catalog_extra") or []):
        fresh["reference"]["catalog"].insert(0, item)
    # positions used to repeat the name and unit of their article
    for order in fresh["orders"]:
        for p in order.get("positions", []):
            p.pop("name", None)
            p.pop("unit", None)
    return fresh


def _read():
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        _cache = _default_store()
        _write()
        return _cache
    if data.get("version") != SCHEMA_VERSION:
        _cache = _migrate(data)
        _write()
        return _cache
    # a partially written file must not crash the app
    defaults = _default_store()
    for key, value in defaults.items():
        data.setdefault(key, value)
    for key, value in defaults["reference"].items():
        data["reference"].setdefault(key, value)
    _cache = data
    return _cache


def _write():
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)


def save():
    """Persist the in-memory document."""
    _write()


def reset():
    """Wipe persisted data back to the seed (handy during development)."""
    global _cache
    _cache = _default_store()
    _write()


# ── reference ──────────────────────────────────────────────────────────────
def warehouses():
    return [w["name"] for w in _read()["reference"]["warehouses"]]


def warehouse_responsible(name):
    for w in _read()["reference"]["warehouses"]:
        if w["name"] == name:
            return w.get("responsible", "—")
    return "—"


def warehouse_code():
    return _read()["reference"].get("warehouseCode", "128")


def roles():
    return [(r["id"], r["label"]) for r in _read()["reference"]["roles"]]


def role_label(role_id):
    for r in _read()["reference"]["roles"]:
        if r["id"] == role_id:
            return r["label"]
    return "Сотрудник"


def sections():
    return [(s["id"], s["label"]) for s in _read()["reference"]["sections"]]


# ── catalogue ──────────────────────────────────────────────────────────────
def catalog_dicts():
    return _read()["reference"]["catalog"]


def catalog_item(article):
    for c in catalog_dicts():
        if c["article"] == str(article):
            return c
    return None


def item_name(article):
    c = catalog_item(article)
    return c["name"] if c else str(article)


def item_unit(article):
    c = catalog_item(article)
    return c["unit"] if c else "шт."


def item_weight(article):
    c = catalog_item(article)
    return c["unitWeight"] if c else 1.0


def add_catalog_item(item):
    _read()["reference"]["catalog"].insert(0, item)
    # a new article starts with no balances anywhere
    _read()["stock"].append({"article": item["article"], "byWarehouse": {},
                             "reserved": 0, "minQty": _min_qty(0)})
    _write()


# ── stock ──────────────────────────────────────────────────────────────────
def stock_rows():
    """One row per article with the totals the «Остатки» screen shows."""
    rows = []
    for row in _read()["stock"]:
        item = catalog_item(row["article"])
        if item is None:
            continue
        qty = sum(row.get("byWarehouse", {}).values())
        reserved = row.get("reserved", 0)
        rows.append({
            "article": row["article"], "code1c": item["code1c"], "name": item["name"],
            "unit": item["unit"], "qty": qty, "reserved": reserved,
            "free": max(0, qty - reserved), "minQty": row.get("minQty", 0),
            "byWarehouse": row.get("byWarehouse", {}),
        })
    return rows


def warehouse_stock():
    """{warehouse: {article: quantity}} — what «Новый заказ» scans."""
    out = {name: {} for name in warehouses()}
    for row in _read()["stock"]:
        for wh, qty in row.get("byWarehouse", {}).items():
            out.setdefault(wh, {})[row["article"]] = qty
    return out


def stock_stats():
    rows = stock_rows()
    stocked = [r for r in rows if r["qty"] > 0]
    below = [r for r in stocked if r["free"] < r["minQty"]]
    reserved = sum(r["reserved"] for r in rows)
    free = sum(r["free"] for r in rows)
    return [
        ("Всего позиций", f"{len(stocked)}", "на складе"),
        ("Ниже минимума", f"{len(below)}", "требуют дозаказа"),
        ("В резерве", f"{reserved:,}".replace(",", " "), "под заказы клиентов"),
        ("Свободный остаток", f"{free:,}".replace(",", " "), "доступно к отгрузке"),
    ]


# ── orders ─────────────────────────────────────────────────────────────────
def load_orders():
    return _read()["orders"]


def save_orders(orders):
    _read()["orders"] = orders
    _write()


def order_by_id(oid):
    for o in load_orders():
        if str(o["id"]) == str(oid):
            return o
    return None


def order_positions(order):
    """Positions with the catalogue fields filled in."""
    out = []
    for p in order.get("positions", []):
        out.append(dict(p, name=item_name(p["article"]), unit=item_unit(p["article"])))
    return out


# ── receiving ──────────────────────────────────────────────────────────────
def receiving_batches():
    return _read()["receiving"]["batches"]


def batch_progress(batch_id):
    """Persisted scan progress; missing batches start empty."""
    progress = _read()["receiving"].setdefault("progress", {})
    return progress.get(str(batch_id))


def save_batch_progress(batch_id, data):
    _read()["receiving"].setdefault("progress", {})[str(batch_id)] = data
    _write()


# ── shipping ───────────────────────────────────────────────────────────────
def packing(order_id):
    return _read()["shipping"].setdefault("packing", {}).get(str(order_id))


def save_packing(order_id, data):
    _read()["shipping"].setdefault("packing", {})[str(order_id)] = data
    _write()


# ── accounts ───────────────────────────────────────────────────────────────
def load_users():
    return _read()["users"]


def save_users(users):
    _read()["users"] = users
    _write()


def user_by_id(uid):
    for u in load_users():
        if str(u["id"]) == str(uid):
            return u
    return None


def load_perms():
    return _read()["permissions"]


def save_perms(perms):
    _read()["permissions"] = perms
    _write()


def load_auth():
    session = _read()["session"]
    return {"id": session.get("currentUserId"), "remember": session.get("remember", False)}


def save_auth(auth):
    session = _read()["session"]
    session["currentUserId"] = (auth or {}).get("id")
    session["remember"] = bool((auth or {}).get("remember"))
    _write()


def user_by_login(login):
    login = (login or "").strip().lower()
    if not login:
        return None
    for u in load_users():
        if u.get("login", "").lower() == login:
            return u
        # почту целиком тоже принимаем — так удобнее диктовать по телефону
        if (u.get("email") or "").lower() == login:
            return u
    return None


def authenticate(login, password):
    """(пользователь, код ошибки). Код: not_found · blocked · wrong_password."""
    user = user_by_login(login)
    if user is None:
        return None, "not_found"
    if not verify_password(password or "", user.get("passwordHash", "")):
        return None, "wrong_password"
    if user.get("status") == "blocked":
        return None, "blocked"
    return user, None


def set_password(user_id, password):
    users = load_users()
    for u in users:
        if u["id"] == user_id:
            u["passwordHash"] = hash_password(password)
            break
    save_users(users)


def record_login(user_id):
    """Отметить время входа — оно показывается в карточке сотрудника."""
    users = load_users()
    for u in users:
        if u["id"] == user_id:
            u["lastLogin"] = format_now()
            break
    save_users(users)


def current_user():
    uid = _read()["session"].get("currentUserId")
    for u in load_users():
        if u["id"] == uid:
            return u
    return None


def current_user_name():
    """Short form used as the author of orders, packings and receipts."""
    u = current_user()
    return short_name(u["fullName"]) if u else "—"
