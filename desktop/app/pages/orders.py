"""Заказы — order list with incoming/outgoing tabs and filters."""
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit

from .. import store, theme
from ..widgets.combo import SearchableComboBox
from ..widgets.common import breadcrumb, button, icon_button
from ..widgets.flow import FlowRow
from ..widgets.table import TableSection
from ._ui import (
    clear_date,
    date_value,
    empty_date_edit,
    filter_action,
    header_row,
    labeled_field,
)
from .base import Page

STATUS_OPTIONS = [
    ("all", "Все статусы"), ("created", "Создан"), ("processing", "В обработке"),
    ("shipped", "Отгружен"), ("received", "Завершен"), ("declined", "Отклонён"),
    ("cancelled", "Отменён"),
]


class OrdersPage(Page):
    def build(self):
        self._tab = "theirs"
        self._search = ""
        self._status = "all"
        self._warehouse = "all"
        self._responsible = "all"

        self.add_block(breadcrumb("ProЗапас / Заказы"))

        action = button("+ Создать заказ", "primary")
        action.clicked.connect(lambda: self.nav.go("new_order"))
        # only outgoing orders can be created from here
        action.setVisible(self._tab == "ours")
        self._action = action
        self.add_block(header_row("Заказы", "Заказы на перемещение товара между складами", action))

        # tabs
        tabs = QHBoxLayout()
        tabs.setSpacing(0)          # вкладки стоят вплотную
        self._tab_in = button("Входящие", "primary")
        self._tab_out = button("Исходящие", "secondary")
        self._tab_in.clicked.connect(lambda: self._set_tab("theirs"))
        self._tab_out.clicked.connect(lambda: self._set_tab("ours"))
        tabs.addWidget(self._tab_in)
        tabs.addWidget(self._tab_out)
        tabs.addStretch(1)
        self.add_block(tabs)

        # filters
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Номер заказа")
        self._search_input.textChanged.connect(self._on_search)
        self._status_input = QComboBox()
        for v, t in STATUS_OPTIONS:
            self._status_input.addItem(t, v)
        self._status_input.currentIndexChanged.connect(self._on_filter)
        # these two grow with the data, so their popups get a search field
        self._warehouse_input = SearchableComboBox("Поиск склада")
        self._warehouse_input.currentIndexChanged.connect(self._on_warehouse)
        self._responsible_input = SearchableComboBox("Поиск сотрудника")
        self._responsible_input.currentIndexChanged.connect(self._on_filter)
        self._date_from = empty_date_edit()
        self._date_from.dateChanged.connect(self._on_filter)
        self._date_to = empty_date_edit()
        self._date_to.dateChanged.connect(self._on_filter)

        filters = FlowRow(h_spacing=theme.SP4, v_spacing=theme.SP3)
        # widths are tuned so the whole row — reset button included — still
        # fits on one line at the default 1280px window
        filters.add(labeled_field("Поиск", self._search_input, 150))
        filters.add(labeled_field("Статус", self._status_input, 140))
        filters.add(labeled_field("Склад", self._warehouse_input, 165))
        filters.add(labeled_field("Ответственный", self._responsible_input, 150))
        filters.add(labeled_field("Дата создания от", self._date_from, 130))
        filters.add(labeled_field("Дата создания до", self._date_to, 130))
        reset = icon_button("reset", "Сбросить фильтры")
        reset.clicked.connect(self._reset)
        filters.add(filter_action(reset))
        self.add_block(filters)

        self._table = TableSection(
            headers=self._headers(), widths=[72, 116, 0, 84, 0, 128, 128],
            rows=[], on_row_click=self._open_order, page_size=13, auto_rows=True,
        )
        self.add_block(self._table)
        self.col.addStretch(1)

        self._refresh_warehouse_options()
        self._refresh_responsible_options()
        self._refresh()

    # ── headers ──
    def _headers(self):
        last = "Отгружен" if self._tab == "theirs" else "Принят"
        wh = "Склад-получатель" if self._tab == "theirs" else "Склад-отправитель"
        return ["Номер", "Статус", wh, "Позиций", "Ответственный", "Создан", last]

    # ── tab / filters ──
    def _set_tab(self, tab):
        if tab == self._tab:
            return
        self._tab = tab
        self._clear_filter_widgets()
        self._tab_in.setProperty("variant", "primary" if tab == "theirs" else "secondary")
        self._tab_out.setProperty("variant", "primary" if tab == "ours" else "secondary")
        for b in (self._tab_in, self._tab_out):
            b.style().unpolish(b); b.style().polish(b)
        self._action.setVisible(tab == "ours")
        self._table._table.setHorizontalHeaderLabels(self._headers())
        self._refresh_warehouse_options()
        self._refresh_responsible_options()
        self._refresh()

    def _tab_orders(self):
        return [o for o in store.load_orders() if o["direction"] == self._tab]

    def _refresh_warehouse_options(self):
        self._warehouse_input.blockSignals(True)
        self._warehouse_input.clear()
        self._warehouse_input.addItem("Все склады", "all")
        seen = []
        for o in self._tab_orders():
            if o["counterpartyWarehouse"] not in seen:
                seen.append(o["counterpartyWarehouse"])
        for w in seen:
            self._warehouse_input.addItem(w, w)
        self._warehouse_input.blockSignals(False)

    def _refresh_responsible_options(self):
        """Responsible list narrows to the selected warehouse, as in the mockup."""
        self._responsible_input.blockSignals(True)
        self._responsible_input.clear()
        self._responsible_input.addItem("Все", "all")
        pool = self._tab_orders()
        if self._warehouse != "all":
            pool = [o for o in pool if o["counterpartyWarehouse"] == self._warehouse]
        seen = []
        for o in pool:
            if o["responsible"] not in seen:
                seen.append(o["responsible"])
        for r in seen:
            self._responsible_input.addItem(r, r)
        self._responsible_input.blockSignals(False)
        self._responsible = "all"

    def _clear_filter_widgets(self):
        self._search = ""
        self._status = "all"
        self._warehouse = "all"
        self._responsible = "all"
        self._search_input.blockSignals(True); self._search_input.clear(); self._search_input.blockSignals(False)
        for combo in (self._status_input, self._warehouse_input, self._responsible_input):
            combo.blockSignals(True); combo.setCurrentIndex(0); combo.blockSignals(False)
        clear_date(self._date_from)
        clear_date(self._date_to)

    def _on_search(self, text):
        self._search = text
        self._refresh()

    def _on_warehouse(self, _):
        self._warehouse = self._warehouse_input.currentData()
        self._refresh_responsible_options()
        self._refresh()

    def _on_filter(self, _=None):
        self._status = self._status_input.currentData()
        self._responsible = self._responsible_input.currentData()
        self._refresh()

    def _reset(self):
        self._clear_filter_widgets()
        self._refresh_responsible_options()
        self._refresh()

    def _open_order(self, oid):
        self.nav.go("order", id=oid)

    def _refresh(self):
        q = self._search.strip().lower()
        date_from = date_value(self._date_from)
        date_to = date_value(self._date_to)
        rows = []
        orders = self._tab_orders()
        orders.sort(key=lambda o: o["id"], reverse=True)
        for o in orders:
            if q and q not in o["number"].lower():
                continue
            if self._status != "all" and o["status"] != self._status:
                continue
            if self._warehouse != "all" and o["counterpartyWarehouse"] != self._warehouse:
                continue
            if self._responsible != "all" and o["responsible"] != self._responsible:
                continue
            if date_from or date_to:
                created = store.parse_ru_datetime(o["createdDateTime"])
                created = created.date() if created else None
                if created is None:
                    continue
                if date_from and created < date_from:
                    continue
                if date_to and created > date_to:
                    continue
            label, color, bg = theme.status_meta(o["status"])
            last = o["shipDateTime"] if self._tab == "theirs" else (o.get("acceptedAt") or "—")
            rows.append((
                [("h", "№" + o["number"]),
                 ("tag", label, color, bg),
                 ("m", o["counterpartyWarehouse"]),
                 ("m", str(len(o["positions"]))),
                 ("m", o["responsible"]),
                 ("m", o["createdDateTime"]),
                 ("m", last)],
                o["id"],
            ))
        self._table.set_rows(rows)
