"""Зависимости: кто пришёл и что ему можно."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Role, RolePermission, Section, UserAccount, UserStatus

from .db import get_session
from .errors import AccountBlocked, Forbidden, Unauthorized
from .security import read_access

SessionDep = Annotated[Session, Depends(get_session)]


def current_user(request: Request, session: SessionDep) -> UserAccount:
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Нет заголовка Authorization: Bearer")

    claims = read_access(token)
    user = session.get(UserAccount, int(claims["sub"]))
    if user is None or user.deleted_at is not None:
        raise Unauthorized("Учётная запись недоступна")
    if user.status == UserStatus.BLOCKED:
        # Блокировка действует сразу, не дожидаясь истечения access-токена.
        raise AccountBlocked()
    return user


UserDep = Annotated[UserAccount, Depends(current_user)]


def permissions_of(session: Session, role_id: int) -> list[RolePermission]:
    return list(session.scalars(
        select(RolePermission).where(RolePermission.role_id == role_id)))


def role_code(session: Session, role_id: int) -> str:
    role = session.get(Role, role_id)
    return role.code if role else ""


def require(section: Section, *, edit: bool = False):
    """Проверка прав по матрице роли.

    Права не в токене: администратор снимает галочку, и это должно действовать
    на следующем запросе, а не через пятнадцать минут.
    """
    def guard(user: UserDep, session: SessionDep) -> UserAccount:
        row = session.get(RolePermission, (user.role_id, section.value))
        allowed = row is not None and (row.can_edit if edit else row.can_view)
        if not allowed:
            raise Forbidden(
                f"Роль не имеет доступа к разделу «{section.value}»"
                + (" на изменение" if edit else ""))
        return user
    return Depends(guard)
