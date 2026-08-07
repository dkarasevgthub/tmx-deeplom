"""Начальные данные: роли, права, склад, администратор.

Не миграция: миграции меняют структуру, этот скрипт — данные. Идемпотентен —
повторный запуск ничего не дублирует, поэтому его безопасно звать из `make up`.

    docker compose run --rm seed
"""
import os
import sys

from argon2 import PasswordHasher
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models import Role, RolePermission, Section, UserAccount, UserStatus, Warehouse

DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_LOGIN = os.environ.get("ADMIN_LOGIN", "admin")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@prozapas.ru")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

ROLES = [
    ("manager", "Менеджер"),
    ("stockman", "Кладовщик"),
    ("admin", "Администратор"),
]

#: Права по умолчанию — то же, что сейчас зашито в приложении.
#: (раздел, роль) -> (просмотр, изменение)
PERMISSIONS = {
    Section.ORDERS:    {"manager": (True, True),   "stockman": (True, False),  "admin": (True, True)},
    Section.SHIPPING:  {"manager": (True, False),  "stockman": (True, True),   "admin": (True, True)},
    Section.RECEIVING: {"manager": (True, False),  "stockman": (True, True),   "admin": (True, True)},
    Section.CATALOG:   {"manager": (True, True),   "stockman": (True, False),  "admin": (True, True)},
    Section.STOCK:     {"manager": (True, False),  "stockman": (True, True),   "admin": (True, True)},
    Section.USERS:     {"manager": (False, False), "stockman": (False, False), "admin": (True, True)},
}

WAREHOUSES = [
    ("128", "Склад №1", True),
    ("129", "Склад №3", False),
    ("130", "Склад №4", False),
    ("131", "Центральный склад", False),
]


def seed(session: Session) -> None:
    roles = {r.code: r for r in session.scalars(select(Role))}
    for code, label in ROLES:
        if code not in roles:
            roles[code] = Role(code=code, label=label)
            session.add(roles[code])
    session.flush()
    print(f"роли: {len(roles)}")

    existing = {
        (rp.role_id, rp.section)
        for rp in session.scalars(select(RolePermission))
    }
    added = 0
    for section, by_role in PERMISSIONS.items():
        for role_code, (can_view, can_edit) in by_role.items():
            role = roles[role_code]
            if (role.id, section.value) in existing:
                continue
            session.add(RolePermission(role_id=role.id, section=section.value,
                                       can_view=can_view, can_edit=can_edit))
            added += 1
    print(f"права: добавлено {added}")

    known = {w.code for w in session.scalars(select(Warehouse))}
    new_warehouses = 0
    for code, name, is_own in WAREHOUSES:
        if code not in known:
            session.add(Warehouse(code=code, name=name, is_own=is_own))
            new_warehouses += 1
    session.flush()
    print(f"склады: добавлено {new_warehouses}")

    admin = session.scalar(
        select(UserAccount).where(UserAccount.login == ADMIN_LOGIN))
    if admin is None:
        own = session.scalar(select(Warehouse).where(Warehouse.is_own.is_(True)))
        session.add(UserAccount(
            full_name="Администратор системы",
            login=ADMIN_LOGIN,
            email=ADMIN_EMAIL,
            # Настоящий argon2id, а не заглушка: иначе войти нельзя.
            password_hash=PasswordHasher().hash(ADMIN_PASSWORD),
            role_id=roles["admin"].id,
            warehouse_id=own.id if own else None,
            status=UserStatus.ACTIVE,
        ))
        print(f"администратор: {ADMIN_LOGIN} заведён")
    else:
        print(f"администратор: {ADMIN_LOGIN} уже есть, пароль не трогаем")


def main() -> int:
    if not DATABASE_URL:
        print("нет DATABASE_URL", file=sys.stderr)
        return 2
    if not ADMIN_PASSWORD:
        print("нет ADMIN_PASSWORD — администратора не завести", file=sys.stderr)
        return 2

    engine = create_engine(DATABASE_URL)
    with Session(engine) as session, session.begin():
        seed(session)
    print("готово")
    return 0


if __name__ == "__main__":
    sys.exit(main())
