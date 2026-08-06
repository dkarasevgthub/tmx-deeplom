from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, BigInteger, Boolean, Numeric, DateTime, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase

# Базовый класс для всех моделей
class Base(DeclarativeBase):
    pass

# --- СПРАВОЧНИКИ ---
class Role(Base):
    __tablename__ = "role"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    label: Mapped[str] = mapped_column(String)

class Warehouse(Base):
    __tablename__ = "warehouse"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    is_own: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    responsible_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True)

class CatalogItem(Base):
    __tablename__ = "catalog_item"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    unit: Mapped[str] = mapped_column(String)
    unit_weight: Mapped[float] = mapped_column(Numeric(10, 3), server_default="0")
    is_archived: Mapped[bool] = mapped_column(Boolean, server_default="false")

class Supplier(Base):
    __tablename__ = "supplier"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    inn: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

# --- ПОЛЬЗОВАТЕЛИ ---
class UserAccount(Base):
    __tablename__ = "user_account"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[Optional[int]] = mapped_column(ForeignKey("warehouse.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String, server_default="active")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class RolePermission(Base):
    __tablename__ = "role_permission"
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"), primary_key=True)
    section: Mapped[str] = mapped_column(String, primary_key=True)
    can_view: Mapped[bool] = mapped_column(Boolean, server_default="false")
    can_edit: Mapped[bool] = mapped_column(Boolean, server_default="false")

class RefreshToken(Base):
    __tablename__ = "refresh_token"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

# --- ОСТАТКИ ---
class StockBalance(Base):
    __tablename__ = "stock_balance"
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_item.id", ondelete="RESTRICT"), primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouse.id", ondelete="RESTRICT"), primary_key=True)
    qty: Mapped[int] = mapped_column(Integer, server_default="0")
    reserved: Mapped[int] = mapped_column(Integer, server_default="0")
    min_qty: Mapped[int] = mapped_column(Integer, server_default="0")
    version: Mapped[int] = mapped_column(Integer, server_default="1")

class StockMovement(Base):
    __tablename__ = "stock_movement"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_item.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouse.id", ondelete="RESTRICT"))
    type: Mapped[str] = mapped_column(String)
    delta: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    doc_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    doc_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True)

# --- ЗАКАЗЫ ---
class Order(Base):
    __tablename__ = "order"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String, unique=True)
    direction: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, server_default="created")
    counterparty_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouse.id", ondelete="RESTRICT"))
    responsible_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, server_default="1")

class OrderPosition(Base):
    __tablename__ = "order_position"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("order.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_item.id", ondelete="RESTRICT"))
    qty: Mapped[int] = mapped_column(Integer)

# --- ЛОГИ ВХОДА (Новое из бэкенд-ТЗ) ---
class LoginAttempt(Base):
    __tablename__ = "login_attempt"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ip_address: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    success: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))