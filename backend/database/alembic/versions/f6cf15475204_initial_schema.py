"""initial_schema

Revision ID: f6cf15475204
Revises: 
Create Date: 2026-08-03 18:51:58.071579

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6cf15475204'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # --- 1. Триггерная функция для updated_at (п. 1 ТЗ) ---
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$         BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    # --- 2. Справочники ---
    op.create_table(
        'warehouse',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('code', sa.Text, nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('responsible_user_id', sa.BigInteger, nullable=True),
        sa.Column('is_own', sa.Boolean, server_default='false', nullable=False),
        sa.Column('is_active', sa.Boolean, server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.UniqueConstraint('name')
    )
    op.execute("CREATE TRIGGER update_warehouse_modtime BEFORE UPDATE ON warehouse FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();")

    op.create_table(
        'supplier',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('inn', sa.Text, nullable=True),
        sa.Column('is_active', sa.Boolean, server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.execute("CREATE TRIGGER update_supplier_modtime BEFORE UPDATE ON supplier FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();")

    op.create_table(
        'catalog_item',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('article', sa.Text, nullable=False),
        sa.Column('code1c', sa.Text, nullable=True),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('unit', sa.Text, nullable=False),
        sa.Column('unit_weight', sa.Numeric(precision=10, scale=3), server_default='0', nullable=False),
        sa.Column('is_archived', sa.Boolean, server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('article'),
        sa.UniqueConstraint('code1c'),
        sa.CheckConstraint('unit_weight >= 0', name='ck_catalog_item_unit_weight')
    )
    op.execute("""
        CREATE INDEX catalog_item_search_idx ON catalog_item
            USING gin (to_tsvector('russian', name || ' ' || article || ' ' || coalesce(code1c, '')));
    """)
    op.execute("CREATE INDEX catalog_item_active_idx ON catalog_item (is_archived) WHERE NOT is_archived;")
    op.execute("CREATE TRIGGER update_catalog_item_modtime BEFORE UPDATE ON catalog_item FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();")

    # --- 3. Учётные записи и права ---
    op.create_table(
        'role',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('code', sa.Text, nullable=False),
        sa.Column('label', sa.Text, nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.CheckConstraint("code IN ('manager','stockman','admin')", name='ck_role_code')
    )

    op.create_table(
        'user_account',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('full_name', sa.Text, nullable=False),
        sa.Column('email', sa.Text, nullable=False),
        sa.Column('password_hash', sa.Text, nullable=False),
        sa.Column('role_id', sa.BigInteger, nullable=False),
        sa.Column('warehouse_id', sa.BigInteger, nullable=True),
        sa.Column('position', sa.Text, nullable=True),
        sa.Column('phone', sa.Text, nullable=True),
        sa.Column('status', sa.Text, server_default='active', nullable=False),
        sa.Column('hire_date', sa.Date, nullable=True),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['role_id'], ['role.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouse.id'], ondelete='SET NULL'),
        sa.CheckConstraint("status IN ('active','blocked')", name='ck_user_account_status')
    )
    op.execute("CREATE UNIQUE INDEX user_account_email_idx ON user_account (lower(email)) WHERE deleted_at IS NULL;")
    op.execute("CREATE INDEX user_account_role_idx ON user_account (role_id) WHERE deleted_at IS NULL;")
    op.execute("CREATE TRIGGER update_user_account_modtime BEFORE UPDATE ON user_account FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();")

    # Внешний ключ для warehouse.responsible_user_id (создается после user_account)
    op.create_foreign_key('fk_warehouse_responsible_user', 'warehouse', 'user_account', ['responsible_user_id'], ['id'], ondelete='SET NULL')

    op.create_table(
        'role_permission',
        sa.Column('role_id', sa.BigInteger, nullable=False),
        sa.Column('section', sa.Text, nullable=False),
        sa.Column('can_view', sa.Boolean, server_default='false', nullable=False),
        sa.Column('can_edit', sa.Boolean, server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('role_id', 'section'),
        sa.ForeignKeyConstraint(['role_id'], ['role.id'], ondelete='CASCADE'),
        sa.CheckConstraint("section IN ('orders','shipping','receiving','catalog','stock','users')", name='ck_role_permission_section'),
        sa.CheckConstraint('can_view OR NOT can_edit', name='ck_role_permission_view_to_edit')
    )

    op.create_table(
        'refresh_token',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger, nullable=False),
        sa.Column('token_hash', sa.Text, nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('token_hash')
    )
    op.execute("CREATE INDEX refresh_token_user_idx ON refresh_token (user_id) WHERE revoked_at IS NULL;")

    # --- 4. Остатки и движения ---
    op.create_table(
        'stock_balance',
        sa.Column('item_id', sa.BigInteger, nullable=False),
        sa.Column('warehouse_id', sa.BigInteger, nullable=False),
        sa.Column('qty', sa.Integer, server_default='0', nullable=False),
        sa.Column('reserved', sa.Integer, server_default='0', nullable=False),
        sa.Column('min_qty', sa.Integer, server_default='0', nullable=False),
        sa.Column('version', sa.Integer, server_default='1', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('item_id', 'warehouse_id'),
        sa.ForeignKeyConstraint(['item_id'], ['catalog_item.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouse.id'], ondelete='RESTRICT'),
        sa.CheckConstraint('qty >= 0', name='ck_stock_balance_qty'),
        sa.CheckConstraint('reserved >= 0', name='ck_stock_balance_reserved'),
        sa.CheckConstraint('min_qty >= 0', name='ck_stock_balance_min_qty'),
        sa.CheckConstraint('reserved <= qty', name='ck_stock_balance_reserved_le_qty')
    )
    op.execute("CREATE INDEX stock_balance_warehouse_idx ON stock_balance (warehouse_id);")
    op.execute("CREATE INDEX stock_balance_below_min_idx ON stock_balance (item_id) WHERE qty - reserved < min_qty;")
    op.execute("CREATE TRIGGER update_stock_balance_modtime BEFORE UPDATE ON stock_balance FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();")

    op.create_table(
        'stock_movement',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('item_id', sa.BigInteger, nullable=False),
        sa.Column('warehouse_id', sa.BigInteger, nullable=False),
        sa.Column('type', sa.Text, nullable=False),
        sa.Column('delta', sa.Integer, nullable=False),
        sa.Column('balance_after', sa.Integer, nullable=False),
        sa.Column('doc_type', sa.Text, nullable=True),
        sa.Column('doc_id', sa.BigInteger, nullable=True),
        sa.Column('comment', sa.Text, nullable=True),
        sa.Column('user_id', sa.BigInteger, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['item_id'], ['catalog_item.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouse.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='SET NULL'),
        sa.CheckConstraint("type IN ('receipt','shipment','writeoff','recount','reserve','unreserve')", name='ck_stock_movement_type')
    )
    op.execute("CREATE INDEX stock_movement_item_idx ON stock_movement (item_id, created_at DESC);")
    op.execute("CREATE INDEX stock_movement_doc_idx ON stock_movement (doc_type, doc_id);")

    # --- 5. Заказы ---
    op.create_table(
        'order',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('number', sa.Text, nullable=False),
        sa.Column('direction', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('counterparty_warehouse_id', sa.BigInteger, nullable=False),
        sa.Column('responsible_user_id', sa.BigInteger, nullable=True),
        sa.Column('comment', sa.Text, nullable=True),
        sa.Column('decline_reason', sa.Text, nullable=True),
        sa.Column('cancel_reason', sa.Text, nullable=True),
        sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('number'),
        sa.ForeignKeyConstraint(['counterparty_warehouse_id'], ['warehouse.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['responsible_user_id'], ['user_account.id'], ondelete='SET NULL'),
        sa.CheckConstraint("direction IN ('ours','theirs')", name='ck_order_direction'),
        sa.CheckConstraint("status IN ('created','processing','shipped','received','declined','cancelled')", name='ck_order_status')
    )
    op.execute('CREATE INDEX order_list_idx ON "order" (direction, status, created_at DESC);')
    op.execute('CREATE INDEX order_warehouse_idx ON "order" (counterparty_warehouse_id);')
    op.execute('CREATE INDEX order_number_idx ON "order" (number text_pattern_ops);')
    op.execute('CREATE TRIGGER update_order_modtime BEFORE UPDATE ON "order" FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();')

    op.create_table(
        'order_position',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('order_id', sa.BigInteger, nullable=False),
        sa.Column('item_id', sa.BigInteger, nullable=False),
        sa.Column('qty', sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['order_id'], ['order.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['catalog_item.id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('order_id', 'item_id'),
        sa.CheckConstraint('qty > 0', name='ck_order_position_qty')
    )
    op.execute("CREATE INDEX order_position_order_idx ON order_position (order_id);")

    op.create_table(
        'order_status_event',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('order_id', sa.BigInteger, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('reason', sa.Text, nullable=True),
        sa.Column('user_id', sa.BigInteger, nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['order_id'], ['order.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='SET NULL')
    )
    op.execute("CREATE INDEX order_status_event_order_idx ON order_status_event (order_id, occurred_at);")

    op.execute("CREATE SEQUENCE order_number_ours_seq START 2001;")
    op.execute("CREATE SEQUENCE order_number_theirs_seq START 3001;")

    # --- 6. Отгрузка ---
    op.create_table(
        'shipment',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('order_id', sa.BigInteger, nullable=False),
        sa.Column('status', sa.Text, server_default='waiting', nullable=False),
        sa.Column('responsible_user_id', sa.BigInteger, nullable=True),
        sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('order_id'),
        sa.ForeignKeyConstraint(['order_id'], ['order.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['responsible_user_id'], ['user_account.id'], ondelete='SET NULL'),
        sa.CheckConstraint("status IN ('waiting','progress','done')", name='ck_shipment_status')
    )
    op.execute("CREATE TRIGGER update_shipment_modtime BEFORE UPDATE ON shipment FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();")

    op.create_table(
        'shipment_box',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('shipment_id', sa.BigInteger, nullable=False),
        sa.Column('barcode', sa.Text, nullable=False),
        sa.Column('item_id', sa.BigInteger, nullable=False),
        sa.Column('qty', sa.Integer, nullable=False),
        sa.Column('weight', sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column('printed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('user_id', sa.BigInteger, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipment.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['catalog_item.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('barcode'),
        sa.CheckConstraint('qty > 0', name='ck_shipment_box_qty'),
        sa.CheckConstraint('weight > 0', name='ck_shipment_box_weight')
    )
    op.execute("CREATE INDEX shipment_box_shipment_idx ON shipment_box (shipment_id);")
    op.execute("CREATE INDEX shipment_box_item_idx ON shipment_box (item_id);")

    # --- 7. Приёмка ---
    op.create_table(
        'receipt_batch',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('number', sa.Text, nullable=False),
        sa.Column('supplier_id', sa.BigInteger, nullable=True),
        sa.Column('order_id', sa.BigInteger, nullable=True),
        sa.Column('status', sa.Text, server_default='waiting', nullable=False),
        sa.Column('warehouse_id', sa.BigInteger, nullable=False),
        sa.Column('responsible_user_id', sa.BigInteger, nullable=True),
        sa.Column('ship_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('number'),
        sa.ForeignKeyConstraint(['supplier_id'], ['supplier.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['order_id'], ['order.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouse.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['responsible_user_id'], ['user_account.id'], ondelete='SET NULL'),
        sa.CheckConstraint("status IN ('waiting','progress','done')", name='ck_receipt_batch_status'),
        sa.CheckConstraint('supplier_id IS NOT NULL OR order_id IS NOT NULL', name='ck_receipt_batch_supplier_or_order')
    )
    op.execute("CREATE INDEX receipt_batch_list_idx ON receipt_batch (status, created_at DESC);")
    op.execute("CREATE TRIGGER update_receipt_batch_modtime BEFORE UPDATE ON receipt_batch FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();")

    op.create_table(
        'receipt_batch_position',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('batch_id', sa.BigInteger, nullable=False),
        sa.Column('item_id', sa.BigInteger, nullable=False),
        sa.Column('boxes', sa.Integer, nullable=False),
        sa.Column('box_weight', sa.Numeric(precision=10, scale=3), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['batch_id'], ['receipt_batch.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['catalog_item.id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('batch_id', 'item_id'),
        sa.CheckConstraint('boxes > 0', name='ck_receipt_batch_position_boxes'),
        sa.CheckConstraint('box_weight > 0', name='ck_receipt_batch_position_box_weight')
    )

    op.create_table(
        'receipt_scan',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('batch_id', sa.BigInteger, nullable=False),
        sa.Column('barcode', sa.Text, nullable=False),
        sa.Column('item_id', sa.BigInteger, nullable=False),
        sa.Column('expected_weight', sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column('actual_weight', sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column('diff_kg', sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column('diff_percent', sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column('is_missing', sa.Boolean, server_default='false', nullable=False),
        sa.Column('user_id', sa.BigInteger, nullable=True),
        sa.Column('scanned_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['batch_id'], ['receipt_batch.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['catalog_item.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('batch_id', 'barcode')
    )
    op.execute("CREATE INDEX receipt_scan_batch_idx ON receipt_scan (batch_id);")

    # --- 8. Этикетки и печать ---
    op.create_table(
        'label_template',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('code', sa.Text, nullable=False),
        sa.Column('format', sa.Text, nullable=False),
        sa.Column('width_mm', sa.Integer, nullable=False),
        sa.Column('height_mm', sa.Integer, nullable=False),
        sa.Column('dpi', sa.Integer, server_default='203', nullable=False),
        sa.Column('body', sa.Text, nullable=False),
        sa.Column('version', sa.Integer, server_default='1', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.CheckConstraint("format IN ('zpl','tspl')", name='ck_label_template_format')
    )
    op.execute("CREATE TRIGGER update_label_template_modtime BEFORE UPDATE ON label_template FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();")

    op.create_table(
        'print_job',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('barcode', sa.Text, nullable=False),
        sa.Column('template_id', sa.BigInteger, nullable=True),
        sa.Column('template_version', sa.Integer, nullable=True),
        sa.Column('is_reprint', sa.Boolean, server_default='false', nullable=False),
        sa.Column('status', sa.Text, server_default='queued', nullable=False),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('user_id', sa.BigInteger, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['template_id'], ['label_template.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='SET NULL'),
        sa.CheckConstraint("status IN ('queued','printing','done','failed')", name='ck_print_job_status')
    )
    op.execute("CREATE INDEX print_job_barcode_idx ON print_job (barcode, created_at DESC);")

    # --- 9. Служебные таблицы ---
    op.create_table(
        'audit_log',
        sa.Column('id', sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column('entity', sa.Text, nullable=False),
        sa.Column('entity_id', sa.BigInteger, nullable=False),
        sa.Column('action', sa.Text, nullable=False),
        sa.Column('before', sa.JSON, nullable=True),
        sa.Column('after', sa.JSON, nullable=True),
        sa.Column('user_id', sa.BigInteger, nullable=True),
        sa.Column('request_id', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['user_account.id'], ondelete='SET NULL')
    )
    op.execute("CREATE INDEX audit_log_entity_idx ON audit_log (entity, entity_id, created_at DESC);")
    op.execute("CREATE INDEX audit_log_user_idx ON audit_log (user_id, created_at DESC);")

    op.create_table(
        'idempotency_key',
        sa.Column('key', sa.Text, nullable=False),
        sa.Column('request_hash', sa.Text, nullable=False),
        sa.Column('response', sa.JSON, nullable=False),
        sa.Column('status_code', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )
    op.execute("CREATE INDEX idempotency_key_created_idx ON idempotency_key (created_at);")


def downgrade() -> None:
    """Downgrade schema."""
    # Удаляем в обратном порядке зависимостей
    op.drop_table('idempotency_key')
    op.drop_table('audit_log')
    op.drop_table('print_job')
    op.drop_table('label_template')
    op.drop_table('receipt_scan')
    op.drop_table('receipt_batch_position')
    op.drop_table('receipt_batch')
    op.drop_table('shipment_box')
    op.drop_table('shipment')
    op.execute("DROP SEQUENCE IF EXISTS order_number_theirs_seq;")
    op.execute("DROP SEQUENCE IF EXISTS order_number_ours_seq;")
    op.drop_table('order_status_event')
    op.drop_table('order_position')
    op.drop_table('order')
    op.drop_table('stock_movement')
    op.drop_table('stock_balance')
    op.drop_table('refresh_token')
    op.drop_table('role_permission')
    op.drop_table('user_account')
    op.drop_table('role')
    op.drop_table('catalog_item')
    op.drop_table('supplier')
    op.drop_table('warehouse')
    
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")