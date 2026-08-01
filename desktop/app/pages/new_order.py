"""Новый заказ — pick catalogue items from the warehouses that stock them.

Rows are grouped by article: the parent row offers the warehouse with the most
stock, and when an item is available elsewhere the row expands into child rows
for the remaining warehouses. Quantity is asked for only after «Добавить» is
pressed, and picked items are pinned to the top of the table.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QWidget, QSpinBox, QAbstractSpinBox
)

from .. import theme, store
from .base import Page
from ._ui import labeled_field
from ..widgets.common import h1, button, icon_button
from ..widgets.blueprint import BlueprintFrame
from ..widgets.combo import SearchableComboBox
from ..widgets.flow import FlowRow
from ..widgets.table import TableSection

SELECTED_BG = theme.ACCENT_RAMP[100]
CHILD_BG = "#ebebec"        # var(--color-text) at 3% over the page background


class NewOrderPage(Page):
    def build(self):
        self._warehouse = "all"
        self._search = ""
        self._comment = ""
        self._selections = {}       # article -> {"article", "warehouse", "qty"}
        self._expanded = set()      # articles whose extra warehouses are shown
        self._qty_row = None        # row key currently asking for a quantity
        self._stock = None          # {warehouse: {article: qty}}, read per rebuild
        self._drafts = {}           # row key -> quantity being typed

        crumb = QLabel(
            f'<a href="#" style="color:{theme.NEUTRAL[600]};text-decoration:none;">ProЗапас</a> / '
            f'<a href="#orders" style="color:{theme.NEUTRAL[600]};text-decoration:none;">Заказы</a> / Новый заказ'
        )
        crumb.setObjectName("breadcrumb")
        crumb.setTextFormat(Qt.TextFormat.RichText)
        crumb.linkActivated.connect(lambda _: self.nav.go("orders"))
        self.add_block(crumb)

        # ── header ──
        head = QHBoxLayout()
        head.setSpacing(theme.SP3)
        left = QVBoxLayout(); left.setSpacing(4)
        left.addWidget(h1("Новый заказ"))
        sub = QLabel("Запрос на перемещение товара с другого склада к нам")
        sub.setObjectName("muted")
        left.addWidget(sub)
        head.addLayout(left)
        head.addStretch(1)
        cancel = button("Отмена", "secondary")
        cancel.clicked.connect(lambda: self.nav.go("orders"))
        self._submit = button("Отправить заказ", "primary")
        self._submit.setEnabled(False)
        self._submit.clicked.connect(self._do_submit)
        head.addWidget(cancel, 0, Qt.AlignmentFlag.AlignTop)
        head.addWidget(self._submit, 0, Qt.AlignmentFlag.AlignTop)
        self.add_block(head)

        # ── filters ──
        frame = BlueprintFrame(padding=theme.SP4)
        row = FlowRow(h_spacing=theme.SP6, v_spacing=theme.SP3)
        self._wh_input = SearchableComboBox("Поиск склада")
        self._wh_input.addItem("Все склады — найти где есть", "all")
        for w in store.warehouses():
            self._wh_input.addItem(w, w)
        self._wh_input.currentIndexChanged.connect(self._on_warehouse)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Артикул или наименование")
        self._search_input.textChanged.connect(self._on_search)
        self._comment_input = QLineEdit()
        self._comment_input.textChanged.connect(lambda t: setattr(self, "_comment", t))
        row.add(labeled_field("Склад-отправитель", self._wh_input, 230))
        row.add(labeled_field("Поиск", self._search_input, 260))
        row.add(labeled_field("Комментарий к заказу (опционально)", self._comment_input, 280))
        frame.content_layout().addWidget(row)
        self.add_block(frame)

        self._notice = QLabel(
            "Склад определён по первой добавленной позиции. Смена склада очистит выбранные позиции.")
        self._notice.setStyleSheet(f"font-size:12px;color:{theme.NEUTRAL[600]};")
        self.add_block(self._notice, visible=False)

        self._table = TableSection(
            headers=self._headers(), widths=self._widths(), rows=[],
            page_size=12, auto_rows=True, elastic={2},
            empty_text="Ничего не найдено — попробуйте другой склад или запрос",
        )
        # this table carries controls; cell padding is trimmed to 3px (as in
        # the mockup) so the buttons are not squeezed by it
        self._table._table.setStyleSheet(
            "QTableWidget::item { padding: 3px 7px; }")
        self.add_block(self._table)
        self.col.addStretch(1)
        self._refresh()

    # ── columns: the warehouse column only makes sense when scanning all ──
    def _show_warehouse_col(self):
        return self._warehouse == "all"

    def _headers(self):
        base = ["Артикул", "Артикул 1С", "Наименование", "Ед. изм."]
        if self._show_warehouse_col():
            base.append("Склад")
        return base + ["Доступно", "", "Карточка"]

    def _widths(self):
        base = [90, 110, 0, 80]
        if self._show_warehouse_col():
            base.append(170)
        return base + [90, 170, 60]

    # ── data ──
    def _stock_entries(self, article):
        """Warehouses stocking this article, richest first."""
        stock = self._stock or store.warehouse_stock()
        scan = store.warehouses() if self._warehouse == "all" else [self._warehouse]
        entries = [(w, stock.get(w, {}).get(article, 0)) for w in scan]
        return sorted([e for e in entries if e[1] > 0], key=lambda e: -e[1])

    def _candidates(self):
        # one read of the balances per rebuild instead of one per article
        self._stock = store.warehouse_stock()
        query = self._search.strip().lower()
        out = []
        for item in store.catalog_dicts():
            if query and not any(query in item[f].lower()
                                 for f in ("name", "article", "code1c")):
                continue
            entries = self._stock_entries(item["article"])
            if entries:
                out.append((item, entries))
        out.sort(key=lambda pair: pair[0]["name"].lower())
        return out

    # ── row builders ──
    def _cells(self, item, warehouse, available, action, *, child=False, link=True,
               warehouse_widget=None):
        cells = [("m", "" if child else item["article"]),
                 ("m", "" if child else item["code1c"]),
                 "" if child else item["name"],
                 ("m", "" if child else item["unit"])]
        if self._show_warehouse_col():
            cells.append(warehouse_widget if warehouse_widget else ("m", warehouse))
        cells.append(("m", str(available)))
        cells.append(action)
        cells.append(("w", lambda a=item["article"]: self._link_cell(a)) if link else "")
        return cells

    def _link_cell(self, article):
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        btn = icon_button("book", "Карточка товара", theme.NEUTRAL[600],
                          size=16, box=28, ghost=True)
        btn.clicked.connect(lambda _=False, a=article: self.nav.go("product", article=a, from_="catalog"))
        # кнопка под своим заголовком: колонка теперь подписана «Карточка»
        lay.addWidget(btn)
        lay.addStretch(1)
        return wrap

    def _expand_cell(self, article, warehouse, others):
        # the widget must be built inside the factory: the table takes
        # ownership of cell widgets and destroys them on every re-render
        def factory():
            wrap = QWidget()
            lay = QHBoxLayout(wrap)
            lay.setContentsMargins(0, 0, 0, 0)
            arrow = "▾" if article in self._expanded else "▸"
            btn = button(f"{warehouse} ({others}) {arrow}", "ghost")
            btn.setStyleSheet(
                f"QPushButton{{border:none;background:transparent;text-align:left;padding:0;"
                f"font-family:{theme.font_body()};font-weight:400;font-size:13px;"
                f"color:{theme.ACCENT_RAMP[700]};}}"
            )
            btn.clicked.connect(lambda _=False, a=article: self._toggle_expand(a))
            lay.addWidget(btn)
            lay.addStretch(1)
            return wrap
        return ("w", factory)

    def _add_cell(self, key, article, warehouse, available):
        """«Добавить» — and, once pressed, the quantity field next to it."""
        def factory():
            wrap = QWidget()
            lay = QHBoxLayout(wrap)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            if self._qty_row == key:
                spin = QSpinBox()
                spin.setRange(1, max(1, available))
                spin.setValue(int(self._drafts.get(key, 1)))
                spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                spin.setProperty("compact", "true")
                spin.setFixedWidth(70)
                spin.setFixedHeight(28)
                spin.valueChanged.connect(lambda v, k=key: self._drafts.__setitem__(k, v))
                confirm = button("Добавить", "secondary")
                confirm.setProperty("compact", "true")
                confirm.clicked.connect(
                    lambda _=False: self._add(article, warehouse, int(spin.value())))
                lay.addWidget(spin)
                lay.addWidget(confirm)
            else:
                add = button("Добавить", "secondary")
                add.setProperty("compact", "true")
                add.clicked.connect(lambda _=False, k=key: self._start_add(k))
                lay.addWidget(add)
            lay.addStretch(1)
            return wrap
        return ("w", factory)

    def _selected_cell(self, article, available, qty):
        def factory():
            wrap = QWidget()
            lay = QHBoxLayout(wrap)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            spin = QSpinBox()
            spin.setRange(1, max(1, available))
            spin.setValue(min(qty, max(1, available)))
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.setProperty("compact", "true")
            spin.setFixedWidth(70); spin.setFixedHeight(28)
            spin.valueChanged.connect(lambda v, a=article: self._selections[a].update(qty=v))
            remove = button("✕", "ghost")
            remove.setProperty("compact", "true")
            remove.setFixedWidth(28)
            remove.setToolTip("Убрать из заказа")
            remove.clicked.connect(lambda _=False, a=article: self._remove(a))
            lay.addWidget(spin)
            lay.addWidget(remove)
            lay.addStretch(1)
            return wrap
        return ("w", factory)

    def _refresh(self):
        self._table._table.setHorizontalHeaderLabels(self._headers())
        self.set_block_visible(self._notice, bool(self._selections))
        self._submit.setEnabled(bool(self._selections))

        pinned = []
        for article, sel in self._selections.items():
            item = store.catalog_item(article)
            available = self._stock.get(sel["warehouse"], {}).get(article, 0)
            pinned.append((
                self._cells(item, sel["warehouse"], available,
                            self._selected_cell(article, available, sel["qty"])),
                article, SELECTED_BG,
            ))

        rows = []
        for item, entries in self._candidates():
            if item["article"] in self._selections:
                continue
            best_wh, best_qty = entries[0]
            others = entries[1:]
            key = item["article"]
            warehouse_widget = (self._expand_cell(key, best_wh, len(others))
                                if others and self._show_warehouse_col() else None)
            rows.append((
                self._cells(item, best_wh, best_qty,
                            self._add_cell(key, item["article"], best_wh, best_qty),
                            warehouse_widget=warehouse_widget),
                key,
            ))
            if others and key in self._expanded:
                for wh, qty in others:
                    sub_key = f"{key}::{wh}"
                    rows.append((
                        self._cells(item, wh, qty,
                                    self._add_cell(sub_key, item["article"], wh, qty),
                                    child=True, link=False),
                        sub_key, CHILD_BG,
                    ))
        self._table.set_rows(rows, pinned=pinned)

    # ── interactions ──
    def _toggle_expand(self, article):
        self._expanded.symmetric_difference_update({article})
        self._refresh()

    def _start_add(self, key):
        self._qty_row = key
        self._drafts.setdefault(key, 1)
        self._refresh()

    def _add(self, article, warehouse, qty):
        self._selections[article] = {"article": article, "warehouse": warehouse, "qty": qty}
        self._qty_row = None
        # the first pick locks the order to its warehouse
        self._set_warehouse(warehouse)

    def _remove(self, article):
        self._selections.pop(article, None)
        if not self._selections:
            self._set_warehouse("all")
        else:
            self._refresh()

    def _set_warehouse(self, value):
        self._warehouse = value
        self._wh_input.blockSignals(True)
        index = self._wh_input.findData(value)
        self._wh_input.setCurrentIndex(index if index >= 0 else 0)
        self._wh_input.blockSignals(False)
        self._refresh()

    def _on_warehouse(self, _):
        value = self._wh_input.currentData()
        if self._selections and value != self._warehouse:
            self._selections = {}       # a different warehouse invalidates the picks
        self._warehouse = value
        self._qty_row = None
        self._refresh()

    def _on_search(self, text):
        self._search = text
        self._refresh()

    # ── submit ──
    def _do_submit(self):
        if not self._selections:
            return
        warehouse = next(iter(self._selections.values()))["warehouse"]
        orders = store.load_orders()
        next_id = max((o["id"] for o in orders), default=0) + 1
        next_number = str(2000 + len([o for o in orders if o["direction"] == "ours"]) + 1)
        created = store.format_now()
        positions = []
        for sel in self._selections.values():
            positions.append({"article": sel["article"], "qty": sel["qty"]})
        orders.append({
            "id": next_id, "number": next_number, "direction": "ours", "status": "created",
            "counterpartyWarehouse": warehouse,
            "counterpartyResponsible": store.warehouse_responsible(warehouse),
            "createdDateTime": created, "shipDateTime": "—", "acceptedAt": None,
            "responsible": store.current_user_name(), "comment": self._comment.strip(),
            "positions": positions, "history": [{"status": "created", "dateTime": created}],
        })
        store.save_orders(orders)
        self.nav.go("order", id=next_id)
