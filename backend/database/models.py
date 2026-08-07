"""Модели ProЗапас — источник правды для схемы.

Миграции генерируются отсюда: `alembic revision --autogenerate`.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Sequence,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}

QTY = Numeric(12, 3)
WEIGHT = Numeric(10, 3)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# --- Перечисления ---------------------------------------------------------
class OrderDirection(StrEnum):
    OURS = "ours"
    THEIRS = "theirs"


class OrderStatus(StrEnum):
    CREATED = "created"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    RECEIVED = "received"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class DocStatus(StrEnum):
    """Общий жизненный цикл отгрузки и партии приёмки."""
    WAITING = "waiting"
    PROGRESS = "progress"
    DONE = "done"


class MovementType(StrEnum):
    RECEIPT = "receipt"
    SHIPMENT = "shipment"
    WRITEOFF = "writeoff"
    RECOUNT = "recount"
    RESERVE = "reserve"
    UNRESERVE = "unreserve"


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class Section(StrEnum):
    ORDERS = "orders"
    SHIPPING = "shipping"
    RECEIVING = "receiving"
    CATALOG = "catalog"
    STOCK = "stock"
    USERS = "users"


def check_enum(column: str, enum: type[StrEnum], name: str) -> CheckConstraint:
    values = ", ".join(f"'{m.value}'" for m in enum)
    return CheckConstraint(f"{column} IN ({values})", name=name)


# --- Миксины --------------------------------------------------------------
class PkMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SoftDeleteMixin:
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)


class VersionMixin:
    """Оптимистичная блокировка."""
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)


# --- Справочники ----------------------------------------------------------
class Warehouse(PkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "warehouse"

    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    responsible_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL", use_alter=True), nullable=True)
    is_own: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class Supplier(PkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "supplier"

    name: Mapped[str] = mapped_column(Text, unique=True)
    inn: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class CatalogItem(PkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "catalog_item"

    article: Mapped[str] = mapped_column(Text, unique=True)
    code1c: Mapped[Optional[str]] = mapped_column(Text, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)
    unit_weight: Mapped[float] = mapped_column(WEIGHT, server_default="0")
    is_archived: Mapped[bool] = mapped_column(Boolean, server_default="false")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('russian', name || ' ' || article || ' ' "
                 "|| coalesce(code1c, ''))", persisted=True),
    )

    __table_args__ = (
        CheckConstraint("unit_weight >= 0", name="unit_weight"),
        Index("ix_catalog_item_search", "search_vector", postgresql_using="gin"),
    )


# --- Учётные записи и права ----------------------------------------------
class Role(PkMixin, Base):
    __tablename__ = "role"

    code: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[str] = mapped_column(Text)


class UserAccount(PkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "user_account"

    full_name: Mapped[str] = mapped_column(Text)
    login: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("warehouse.id", ondelete="SET NULL"), nullable=True)
    position: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default=UserStatus.ACTIVE)
    hire_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        check_enum("status", UserStatus, "status"),
        Index("ix_user_account_role", "role_id"),
    )


class RolePermission(Base):
    __tablename__ = "role_permission"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE"), primary_key=True)
    section: Mapped[str] = mapped_column(Text, primary_key=True)
    can_view: Mapped[bool] = mapped_column(Boolean, server_default="false")
    can_edit: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        check_enum("section", Section, "section"),
        CheckConstraint("can_view OR NOT can_edit", name="edit_needs_view"),
    )


class RefreshToken(PkMixin, Base):
    __tablename__ = "refresh_token"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_refresh_token_user", "user_id"),)


class LoginAttempt(PkMixin, Base):
    """Журнал попыток входа — по нему тормозится перебор пароля."""
    __tablename__ = "login_attempt"

    ip_address: Mapped[str] = mapped_column(Text)
    login: Mapped[str] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_login_attempt_ip", "ip_address", "created_at"),)


# --- Остатки и движения ---------------------------------------------------
class StockBalance(VersionMixin, Base):
    __tablename__ = "stock_balance"

    item_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_item.id", ondelete="RESTRICT"), primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse.id", ondelete="RESTRICT"), primary_key=True)
    qty: Mapped[float] = mapped_column(QTY, server_default="0")
    reserved: Mapped[float] = mapped_column(QTY, server_default="0")
    min_qty: Mapped[float] = mapped_column(QTY, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("qty >= 0", name="qty"),
        CheckConstraint("reserved >= 0", name="reserved"),
        CheckConstraint("min_qty >= 0", name="min_qty"),
        CheckConstraint("reserved <= qty", name="reserved_le_qty"),
        Index("ix_stock_balance_warehouse", "warehouse_id"),
    )


class StockMovement(PkMixin, Base):
    """Журнал движений: append-only, баланс всегда можно пересчитать по нему."""
    __tablename__ = "stock_movement"

    item_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_item.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse.id", ondelete="RESTRICT"))
    type: Mapped[str] = mapped_column(Text)
    delta: Mapped[float] = mapped_column(QTY)
    balance_after: Mapped[float] = mapped_column(QTY)
    doc_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    doc_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        check_enum("type", MovementType, "type"),
        Index("ix_stock_movement_item", "item_id", "created_at"),
        Index("ix_stock_movement_warehouse", "warehouse_id", "created_at"),
        Index("ix_stock_movement_doc", "doc_type", "doc_id"),
    )


# --- Заказы ---------------------------------------------------------------
order_number_ours_seq = Sequence("order_number_ours_seq", start=2001)
order_number_theirs_seq = Sequence("order_number_theirs_seq", start=3001)


class Order(PkMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "order"        # зарезервированное слово, SQLAlchemy экранирует

    number: Mapped[str] = mapped_column(Text, unique=True)
    direction: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=OrderStatus.CREATED)
    counterparty_warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse.id", ondelete="RESTRICT"))
    responsible_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decline_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shipped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        check_enum("direction", OrderDirection, "direction"),
        check_enum("status", OrderStatus, "status"),
        Index("ix_order_list", "direction", "status", "created_at"),
        Index("ix_order_warehouse", "counterparty_warehouse_id"),
        Index("ix_order_number_prefix", "number", postgresql_ops={"number": "text_pattern_ops"}),
    )


class OrderPosition(PkMixin, Base):
    __tablename__ = "order_position"

    order_id: Mapped[int] = mapped_column(ForeignKey("order.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_item.id", ondelete="RESTRICT"))
    qty: Mapped[float] = mapped_column(QTY)

    __table_args__ = (
        UniqueConstraint("order_id", "item_id"),
        CheckConstraint("qty > 0", name="qty"),
    )


class OrderStatusEvent(PkMixin, Base):
    """История статусов заказа — то, что экран показывает лентой."""
    __tablename__ = "order_status_event"

    order_id: Mapped[int] = mapped_column(ForeignKey("order.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        check_enum("status", OrderStatus, "status"),
        Index("ix_order_status_event_order", "order_id", "occurred_at"),
    )


# --- Отгрузка -------------------------------------------------------------
class Shipment(PkMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "shipment"

    order_id: Mapped[int] = mapped_column(
        ForeignKey("order.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(Text, server_default=DocStatus.WAITING)
    responsible_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True)
    shipped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        check_enum("status", DocStatus, "status"),
        Index("ix_shipment_list", "status", "created_at"),
    )


class ShipmentBox(PkMixin, Base):
    """Коробка создаётся до печати: зажевало ленту — этикетка перепечатывается,
    а данные на месте. Штрихкод выдаёт сервер."""
    __tablename__ = "shipment_box"

    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipment.id", ondelete="CASCADE"))
    barcode: Mapped[str] = mapped_column(Text, unique=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_item.id", ondelete="RESTRICT"))
    qty: Mapped[float] = mapped_column(QTY)
    weight: Mapped[float] = mapped_column(WEIGHT)
    printed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("qty > 0", name="qty"),
        CheckConstraint("weight > 0", name="weight"),
        Index("ix_shipment_box_shipment", "shipment_id"),
        Index("ix_shipment_box_item", "item_id"),
    )


# --- Приёмка --------------------------------------------------------------
class ReceiptBatch(PkMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "receipt_batch"

    number: Mapped[str] = mapped_column(Text, unique=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("supplier.id", ondelete="RESTRICT"), nullable=True)
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("order.id", ondelete="SET NULL"), nullable=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(Text, server_default=DocStatus.WAITING)
    responsible_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True)
    ship_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)

    __table_args__ = (
        check_enum("status", DocStatus, "status"),
        CheckConstraint("supplier_id IS NOT NULL OR order_id IS NOT NULL",
                        name="supplier_or_order"),
        Index("ix_receipt_batch_list", "status", "created_at"),
    )


class ReceiptBatchPosition(PkMixin, Base):
    """Ожидание и факт по позиции. Итог приёмки переживает партию, сканы нет."""
    __tablename__ = "receipt_batch_position"

    batch_id: Mapped[int] = mapped_column(
        ForeignKey("receipt_batch.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_item.id", ondelete="RESTRICT"))
    boxes: Mapped[int] = mapped_column(Integer)
    box_weight: Mapped[float] = mapped_column(WEIGHT)
    accepted_boxes: Mapped[int] = mapped_column(Integer, server_default="0")
    missing_boxes: Mapped[int] = mapped_column(Integer, server_default="0")
    actual_weight: Mapped[Optional[float]] = mapped_column(WEIGHT, nullable=True)

    __table_args__ = (
        UniqueConstraint("batch_id", "item_id"),
        CheckConstraint("boxes > 0", name="boxes"),
        CheckConstraint("box_weight > 0", name="box_weight"),
        CheckConstraint("accepted_boxes >= 0", name="accepted_boxes"),
        CheckConstraint("missing_boxes >= 0", name="missing_boxes"),
    )


class ReceiptScan(PkMixin, Base):
    """Рабочая таблица: живёт, пока партия в работе, при завершении сворачивается."""
    __tablename__ = "receipt_scan"

    batch_id: Mapped[int] = mapped_column(
        ForeignKey("receipt_batch.id", ondelete="CASCADE"))
    barcode: Mapped[str] = mapped_column(Text)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_item.id", ondelete="RESTRICT"))
    actual_weight: Mapped[Optional[float]] = mapped_column(WEIGHT, nullable=True)
    is_missing: Mapped[bool] = mapped_column(Boolean, server_default="false")
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("batch_id", "barcode"),
    )


# --- Служебные ------------------------------------------------------------
class AuditLog(PkMixin, Base):
    __tablename__ = "audit_log"

    entity: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(Text)
    before: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_audit_log_entity", "entity", "entity_id", "created_at"),
        Index("ix_audit_log_user", "user_id", "created_at"),
    )


class IdempotencyKey(Base):
    """Нужен только созданию заказа: у скана и коробки есть естественный ключ."""
    __tablename__ = "idempotency_key"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text)
    response: Mapped[dict] = mapped_column(JSONB)
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_idempotency_key_created", "created_at"),)


Index("ix_user_account_login", func.lower(UserAccount.login), unique=True,
      postgresql_where=UserAccount.deleted_at.is_(None))
Index("ix_user_account_email", func.lower(UserAccount.email), unique=True,
      postgresql_where=UserAccount.deleted_at.is_(None))

Index("ix_catalog_item_active", CatalogItem.id,
      postgresql_where=CatalogItem.is_archived.is_(False))

Index("ix_stock_balance_below_min", StockBalance.item_id,
      postgresql_where=StockBalance.qty - StockBalance.reserved < StockBalance.min_qty)

Index("ix_refresh_token_active", RefreshToken.user_id,
      postgresql_where=RefreshToken.revoked_at.is_(None))
