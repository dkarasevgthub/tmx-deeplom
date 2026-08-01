"""Отгрузка — pick, weigh, box and ship outgoing (theirs) orders.

List ⇄ detail is handled inside the page so packing progress survives the
toggle. Boxes are kept in a module-level store for the session.
"""
import time

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import devices, store, theme
from ..widgets.blueprint import BlueprintFrame
from ..widgets.common import Tag, button, h1, h4, icon_button
from ..widgets.dialog import confirm_dialog, weight_dialog
from ..widgets.flow import FlowRow
from ..widgets.table import (
    TableSection,
    style_table,
)
from ._ui import (
    clear_date,
    date_value,
    empty_date_edit,
    filter_action,
    labeled_field,
    number_field,
    number_value,
)
from .base import BlockColumn, Page

MAX_BOX_WEIGHT = 25.0
PANEL_PAGE_SIZE = 8      # rows per page in the two detail panels
# packing progress lives in the store; this is a per-session cache of it
_PACK = {}


def _uw(article):
    return store.item_weight(article)


def _order_weight(o):
    return sum(_uw(p["article"]) * p["qty"] for p in o["positions"])


def _positions(o):
    """Order positions with the catalogue name and unit filled in."""
    return store.order_positions(o)


def _pack(oid):
    if oid not in _PACK:
        saved = store.packing(oid) or {}
        _PACK[oid] = {"boxes": saved.get("boxes", []), "done": saved.get("done", False),
                      "responsible": saved.get("responsible"),
                      "shippedAt": saved.get("shippedAt")}
    return _PACK[oid]


def _save_pack(oid):
    store.save_packing(oid, _PACK[oid])


NO_PRINTER = "Принтер недоступен — упаковка и отгрузка заблокированы"


def _packed_qty(pd, article):
    return sum(b["qty"] for b in pd["boxes"] if b["article"] == article)


def _kicker_value(kicker, value):
    box = QWidget()
    v = QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)
    k = QLabel(kicker); k.setObjectName("kicker")
    val = QLabel(str(value)); val.setStyleSheet(f"font-family:{theme.font_heading()};font-size:18px;")
    v.addWidget(k); v.addWidget(val)
    return box


def config_table(table, widths):
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    style_table(table)
    hdr = table.horizontalHeader()
    for i in range(table.columnCount()):
        hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
    # widths act as per-column minimums; the rest follows the table's width
    table._width_floors = list(widths)


def _within(value, start, end):
    """Is a "dd.MM.yyyy HH:mm" stamp inside the bounds? A row with no date is
    filtered out as soon as either bound is set, as in the mockup."""
    if start is None and end is None:
        return True
    parsed = store.parse_ru_datetime(value)
    if parsed is None:
        return False
    day = parsed.date()
    return not ((start and day < start) or (end and day > end))


def cell(table, r, c, text, color=None, heading=False):
    it = QTableWidgetItem(str(text))
    if color:
        it.setForeground(QColor(color))
    if heading:
        f = QFont(theme.HEADING_FAMILY); f.setPixelSize(14); it.setFont(f)
    table.setItem(r, c, it)


class ShippingPage(Page):
    def build(self):
        self._active_id = None
        self._active_article = None
        self._weighed = None
        self._live = None               # текущее показание весов, (кг, устойчиво)
        self._scale_value = None        # ярлык панели «Весы», пока она на экране
        self._print_msg = ""
        self._search = ""
        self._status = "all"
        self._topack_page = 1
        self._boxes_page = 1
        # filters keep their value in the page: the list is rebuilt from
        # scratch every time the user comes back from a shipment
        self._weight_min = ""
        self._weight_max = ""
        self._created_from = None
        self._created_to = None
        self._ship_from = None
        self._ship_to = None

        self._container = BlockColumn(page=self)
        self.col.addLayout(self._container)
        self.col.addStretch(1)
        # подключение и отвал оборудования меняют то, что экран может делать
        devices.bus.changed.connect(self._render)
        devices.client.weight_read.connect(self._on_live_weight)
        # экран уходит — поток веса службе больше не нужен
        self.destroyed.connect(lambda: devices.live_weight(False))
        self._render()

    def _clear(self):
        self._clear_layout(self._container)
        self._container.reset_blocks()

    def _clear_layout(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _render(self):
        self._clear()
        self._scale_value = None
        if self._active_id is None:
            self._build_list()
        else:
            self._build_detail()
        # поток нужен только на экране заказа, где панель весов видна
        devices.live_weight(self._active_id is not None)

    def _on_live_weight(self, kg, stable):
        """Показание с весов — панель обновляется, не перерисовывая экран."""
        self._live = (kg, stable)
        if self._scale_value is None or self._weighed is not None:
            return                      # взвешенное значение живой поток не трёт
        try:
            self._scale_value.setText(f"{kg:.2f} кг")
            self._scale_value.setStyleSheet(self._scale_style(stable))
        except RuntimeError:
            self._scale_value = None    # ярлык уже уничтожен перерисовкой

    @staticmethod
    def _scale_style(stable):
        color = theme.ACCENT_RAMP[700] if stable else theme.NEUTRAL[600]
        return f"font-family:{theme.font_heading()};font-size:36px;color:{color};"

    def _shipments(self):
        return [o for o in store.load_orders()
                if o["direction"] == "theirs" and o["status"] in ("created", "processing", "shipped")]

    # ── list ──
    def _build_list(self):
        crumb = QLabel(f'<a href="#" style="color:{theme.NEUTRAL[600]};text-decoration:none;">ProЗапас</a> / Отгрузка')
        crumb.setObjectName("breadcrumb"); crumb.setTextFormat(Qt.TextFormat.RichText)
        self._container.add_block(crumb)

        title = QVBoxLayout(); title.setSpacing(4)
        title.addWidget(h1("Отгрузка"))
        sub = QLabel("Заявки других складов, которые нужно собрать и отгрузить")
        sub.setObjectName("muted"); title.addWidget(sub)
        self._container.add_block(title)

        self._search_input = QLineEdit(); self._search_input.setPlaceholderText("Номер заказа")
        self._search_input.setText(self._search)
        self._search_input.textChanged.connect(self._on_search)
        self._status_input = QComboBox()
        for v, t in [("all", "Все статусы"), ("waiting", "Ожидает"), ("progress", "В сборке"), ("done", "Отгружен")]:
            self._status_input.addItem(t, v)
        idx = self._status_input.findData(self._status)
        self._status_input.setCurrentIndex(max(idx, 0))
        self._status_input.currentIndexChanged.connect(self._on_status)
        self._weight_min_input = number_field(self._on_weight)
        self._weight_min_input.setText(self._weight_min)
        self._weight_max_input = number_field(self._on_weight)
        self._weight_max_input.setText(self._weight_max)
        self._created_from_input = empty_date_edit()
        self._created_to_input = empty_date_edit()
        self._ship_from_input = empty_date_edit()
        self._ship_to_input = empty_date_edit()
        for edit, value in ((self._created_from_input, self._created_from),
                            (self._created_to_input, self._created_to),
                            (self._ship_from_input, self._ship_from),
                            (self._ship_to_input, self._ship_to)):
            if value is not None:
                edit.setDate(QDate(value.year, value.month, value.day))
            edit.dateChanged.connect(self._on_dates)

        filters = FlowRow(h_spacing=theme.SP4, v_spacing=theme.SP3)
        filters.add(labeled_field("Поиск", self._search_input, 150))
        filters.add(labeled_field("Статус", self._status_input, 140))
        filters.add(labeled_field("Вес от, кг", self._weight_min_input, 90))
        filters.add(labeled_field("Вес до, кг", self._weight_max_input, 90))
        filters.add(labeled_field("Дата создания от", self._created_from_input, 130))
        filters.add(labeled_field("Дата создания до", self._created_to_input, 130))
        filters.add(labeled_field("Дата отгрузки от", self._ship_from_input, 130))
        filters.add(labeled_field("Дата отгрузки до", self._ship_to_input, 130))
        reset = icon_button("reset", "Сбросить фильтры"); reset.clicked.connect(self._reset)
        filters.add(filter_action(reset))
        self._container.add_block(filters)

        self._table = TableSection(
            headers=["Заказ", "Статус", "Прогресс", "Вес, кг", "Ответственный", "Создан", "Отгружен"],
            widths=[72, 116, 96, 96, 0, 128, 128], rows=self._list_rows(),
            on_row_click=self._open, page_size=13, auto_rows=True,
        )
        self._container.add_block(self._table)

    def _list_rows(self):
        q = self._search.strip().lower()
        wmin = number_value(self._weight_min_input)
        wmax = number_value(self._weight_max_input)
        rows = []
        for o in sorted(self._shipments(), key=lambda o: o["id"], reverse=True):
            if q and q not in o["number"].lower():
                continue
            weight = _order_weight(o)
            if wmin is not None and weight < wmin:
                continue
            if wmax is not None and weight > wmax:
                continue
            if not _within(o["createdDateTime"], self._created_from, self._created_to):
                continue
            if not _within(o["shipDateTime"], self._ship_from, self._ship_to):
                continue
            pd = _PACK.get(o["id"])
            done = (pd and pd["done"]) or o["status"] == "shipped"
            has_boxes = bool(pd and pd["boxes"])
            if done:
                label, color, bg, key = "Отгружен", theme.ACCENT_RAMP[700], "transparent", "done"
            elif has_boxes:
                label, color, bg, key = "В сборке", theme.ACCENT2_RAMP[700], theme.ACCENT2_RAMP[100], "progress"
            else:
                label, color, bg, key = "Ожидает", theme.NEUTRAL[800], theme.NEUTRAL[200], "waiting"
            if self._status != "all" and key != self._status:
                continue
            total = len(o["positions"])
            assembled = (len([p for p in o["positions"] if p["qty"] - _packed_qty(pd, p["article"]) <= 0])
                         if pd else (total if o["status"] == "shipped" else 0))
            responsible = (pd and pd["responsible"]) or (o["responsible"] if o["status"] == "shipped" else "—")
            ship_date = o["shipDateTime"] if o["shipDateTime"] not in (None, "—") else "—"
            rows.append((
                [("h", "№" + o["number"]), ("tag", label, color, bg), f"{assembled} из {total}",
                 ("m", f"{_order_weight(o):.1f} кг"), ("m", responsible),
                 ("m", o["createdDateTime"]), ("m", ship_date)],
                o["id"],
            ))
        return rows

    def _on_search(self, text):
        self._search = text
        self._table.set_rows(self._list_rows())

    def _on_status(self, _):
        self._status = self._status_input.currentData()
        self._table.set_rows(self._list_rows())

    def _on_weight(self, _=None):
        self._weight_min = self._weight_min_input.text()
        self._weight_max = self._weight_max_input.text()
        self._table.set_rows(self._list_rows())

    def _on_dates(self, _=None):
        self._created_from = date_value(self._created_from_input)
        self._created_to = date_value(self._created_to_input)
        self._ship_from = date_value(self._ship_from_input)
        self._ship_to = date_value(self._ship_to_input)
        self._table.set_rows(self._list_rows())

    def _reset(self):
        self._search = ""; self._status = "all"
        self._weight_min = ""; self._weight_max = ""
        self._created_from = self._created_to = None
        self._ship_from = self._ship_to = None
        for edit in (self._search_input, self._weight_min_input, self._weight_max_input):
            edit.blockSignals(True); edit.clear(); edit.blockSignals(False)
        self._status_input.blockSignals(True); self._status_input.setCurrentIndex(0); self._status_input.blockSignals(False)
        for edit in (self._created_from_input, self._created_to_input,
                     self._ship_from_input, self._ship_to_input):
            clear_date(edit)
        self._table.set_rows(self._list_rows())

    def _open(self, oid):
        _pack(oid)
        self._active_id = oid
        self._topack_page = 1
        self._boxes_page = 1
        self._active_article = None
        self._weighed = None
        self._live = None               # текущее показание весов, (кг, устойчиво)
        self._scale_value = None        # ярлык панели «Весы», пока она на экране
        self._print_msg = ""
        self._render()

    def _back(self):
        self._active_id = None
        self._render()

    # the arrow first steps out of the open card, and only then leaves the page
    def can_go_back(self):
        return self._active_id is not None or self.nav.can_back()

    def go_back(self):
        if self._active_id is not None:
            self._back()
        else:
            self.nav.back()

    # ── detail ──
    def _build_detail(self):
        o = store.order_by_id(self._active_id)
        pd = _pack(self._active_id)
        done = pd["done"] or o["status"] == "shipped"

        crumb = QLabel(
            f'<a href="#home" style="color:{theme.NEUTRAL[600]};text-decoration:none;">ProЗапас</a> / '
            f'<a href="#back" style="color:{theme.NEUTRAL[600]};text-decoration:none;">Отгрузка</a> / №{o["number"]}')
        crumb.setObjectName("breadcrumb"); crumb.setTextFormat(Qt.TextFormat.RichText)
        crumb.linkActivated.connect(lambda href: self._back() if href == "#back" else self.nav.go("home"))
        self._container.add_block(crumb)

        head = QHBoxLayout()
        left = QVBoxLayout(); left.setSpacing(4)
        left.addWidget(h1(f'Заказ №{o["number"]}'))
        sub = QLabel("Упаковка позиций и отгрузка на склад-получатель")
        sub.setObjectName("muted"); left.addWidget(sub)
        head.addLayout(left); head.addStretch(1)
        if not done:
            ship = button("Отгрузить", "primary"); ship.clicked.connect(lambda: self._request_ship(o))
            if not devices.available("printer"):
                ship.setEnabled(False)
                ship.setToolTip(NO_PRINTER)
            head.addWidget(ship, 0, Qt.AlignmentFlag.AlignTop)
        self._container.add_block(head)

        if done:
            label, color, bg = "Отгружен", theme.ACCENT_RAMP[700], "transparent"
        elif pd["boxes"]:
            label, color, bg = "В сборке", theme.ACCENT2_RAMP[700], theme.ACCENT2_RAMP[100]
        else:
            label, color, bg = "Ожидает", theme.NEUTRAL[800], theme.NEUTRAL[200]
        packed_weight = sum(float(b["weight"]) for b in pd["boxes"])
        fully = len([p for p in o["positions"] if p["qty"] - _packed_qty(pd, p["article"]) <= 0])
        info = BlueprintFrame(padding=theme.SP4)
        # `flex-wrap: wrap` in the mockup: the fields move to the next line
        # instead of being squeezed when the window narrows
        irow = FlowRow(h_spacing=theme.SP8, v_spacing=theme.SP4)
        stat = QWidget(); sv = QVBoxLayout(stat); sv.setContentsMargins(0, 0, 0, 0); sv.setSpacing(2)
        sk = QLabel("Статус"); sk.setObjectName("kicker"); sv.addWidget(sk); sv.addWidget(Tag(label, color, bg))
        irow.add(stat)
        irow.add(_kicker_value("Ответственный", pd["responsible"] or (o["responsible"] if done else "—")))
        irow.add(_kicker_value("Дата создания", o["createdDateTime"]))
        irow.add(_kicker_value("Дата отгрузки", pd["shippedAt"] or (o["shipDateTime"] if done else "—")))
        irow.add(_kicker_value("Позиций", len(o["positions"])))
        irow.add(_kicker_value("Коробок", len(pd["boxes"])))
        irow.add(_kicker_value("Упаковано, вес", f"{packed_weight:.1f} кг"))
        irow.add(_kicker_value("Прогресс", f"{fully} из {len(o['positions'])}"))
        info.content_layout().addWidget(irow)
        self._container.add_block(info)

        if not done:
            pack_row = QHBoxLayout(); pack_row.setSpacing(theme.SP6)
            pack_row.addWidget(self._packing_panel(o, pd), 2)
            pack_row.addWidget(self._scale_panel(), 1)
            self._container.add_block(pack_row)

        two = QHBoxLayout(); two.setSpacing(theme.SP6)
        two.addWidget(self._topack_panel(o, pd, done), 1)
        two.addWidget(self._boxes_panel(o, pd, done), 1)
        self._container.add_block(two)

    def _packing_panel(self, o, pd):
        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        if not devices.available("printer"):
            note = QLabel(
                "Каждая коробка маркируется этикеткой, поэтому без принтера "
                "упаковать позицию и отгрузить заказ нельзя. Подключите принтер "
                "или включите симуляцию.")
            note.setWordWrap(True)
            note.setStyleSheet(f"font-size:13px;color:{theme.DANGER};")
            fl.addWidget(note)
            return frame

        if self._active_article:
            pos = next(p for p in _positions(o) if p["article"] == self._active_article)
            remaining = pos["qty"] - _packed_qty(pd, pos["article"])
            top = QHBoxLayout()
            box = QVBoxLayout(); box.setSpacing(2)
            kick = QLabel("Упаковка позиции")
            kick.setStyleSheet(f"font-size:11px;color:{theme.ACCENT_RAMP[700]};text-transform:uppercase;")
            name = QLabel(pos["name"]); name.setStyleSheet(f"font-family:{theme.font_heading()};font-size:18px;")
            meta = QLabel(f'Артикул {pos["article"]} · осталось упаковать {remaining} {pos["unit"]}')
            meta.setStyleSheet(f"font-size:13px;color:{theme.NEUTRAL[600]};")
            box.addWidget(kick); box.addWidget(name); box.addWidget(meta)
            top.addLayout(box); top.addStretch(1)
            cancel = button("Отменить", "ghost"); cancel.clicked.connect(self._cancel_active)
            top.addWidget(cancel, 0, Qt.AlignmentFlag.AlignTop)
            fl.addLayout(top)

            if self._weighed is None:
                hint = QLabel("Упакуйте позицию в коробку, поставьте её на весы и нажмите «Считать вес».")
                hint.setWordWrap(True); hint.setStyleSheet(f"font-size:13px;color:{theme.NEUTRAL[600]};")
                fl.addWidget(hint)
                label = "Считать вес" if devices.available("scale") else "Ввести вес"
                read = button(label, "secondary"); read.clicked.connect(lambda: self._read_scale(o, pd))
                fl.addWidget(read, 0, Qt.AlignmentFlag.AlignLeft)
            else:
                res = QHBoxLayout(); res.setSpacing(theme.SP6)
                res.addWidget(self._big_metric("Вес коробки", f'{self._weighed["weight"]} кг', theme.ACCENT_RAMP[700]))
                res.addWidget(self._big_metric("Количество (расчёт по весу)", f'{self._weighed["qty"]} {pos["unit"]}', theme.TEXT))
                res.addStretch(1)
                fl.addLayout(res)
                btns = QHBoxLayout()
                pr = button("Напечатать этикетку", "primary")
                pr.clicked.connect(lambda: self._print_label(o, pd))
                rw = button("Взвесить заново", "secondary"); rw.clicked.connect(self._reweigh)
                btns.addWidget(pr); btns.addWidget(rw); btns.addStretch(1)
                fl.addLayout(btns)
        else:
            hint = QLabel("Выберите позицию в списке «К упаковке», чтобы начать упаковку коробки.")
            hint.setWordWrap(True); hint.setStyleSheet(f"font-size:13px;color:{theme.NEUTRAL[600]};")
            fl.addWidget(hint)

        if self._print_msg:
            pm = QLabel(self._print_msg)
            pm.setStyleSheet(f"font-size:12px;color:{theme.ACCENT_RAMP[800]};")
            fl.addWidget(pm)
        return frame

    def _big_metric(self, kicker, value, color):
        box = QWidget()
        v = QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)
        k = QLabel(kicker); k.setObjectName("kicker")
        val = QLabel(str(value)); val.setStyleSheet(f"font-family:{theme.font_heading()};font-size:22px;color:{color};")
        v.addWidget(k); v.addWidget(val)
        return box

    def _scale_panel(self):
        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        fl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        k = QLabel("Весы"); k.setObjectName("kicker"); k.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # взвешенная коробка держит своё значение; до этого панель живёт
        # потоком с весов
        stable = True
        if self._weighed:
            reading = self._weighed["weight"] + " кг"
        elif devices.available("scale") and self._live:
            reading, stable = f"{self._live[0]:.2f} кг", self._live[1]
        else:
            reading = "—"
        r = QLabel(reading); r.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r.setStyleSheet(self._scale_style(stable))
        self._scale_value = r
        fl.addWidget(k); fl.addWidget(r)
        return frame

    def _topack_panel(self, o, pd, done):
        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        fl.addWidget(h4("К упаковке"))

        # fully packed positions sink to the bottom, as in the mockup
        positions = sorted(_positions(o),
                           key=lambda p: 1 if p["qty"] - _packed_qty(pd, p["article"]) <= 0 else 0)
        rows = []
        for p in positions:
            packed = _packed_qty(pd, p["article"])
            remaining = p["qty"] - packed
            spent = remaining <= 0
            # a finished position is greyed out whole; the one being packed is
            # tinted through the row background
            muted = theme.NEUTRAL[500] if spent else None
            rows.append((
                [("c", p["article"], muted or theme.NEUTRAL[600]),
                 ("c", p["name"], muted),
                 ("c", f'{p["qty"]} {p["unit"]}', muted),
                 ("c", f'{packed} {p["unit"]}', muted),
                 ("c", "0" if spent else str(remaining),
                  muted or (theme.ACCENT_RAMP[700] if spent else theme.TEXT))],
                p["article"],
                theme.ACCENT_RAMP[100] if (not spent and self._active_article == p["article"]) else None,
            ))

        def on_click(article):
            pos = next((p for p in _positions(o) if p["article"] == article), None)
            if pos is not None and pos["qty"] - _packed_qty(pd, pos["article"]) > 0:
                self._select_position(article)

        section = TableSection(
            headers=["Артикул", "Наименование", "Заказано", "Упаковано", "Осталось"],
            widths=[70, 80, 62, 62, 62], rows=rows, elastic={1},
            on_row_click=None if done else on_click,
            page_size=PANEL_PAGE_SIZE, auto_rows=True, framed=False,
            empty_text="В заказе нет позиций",
            on_page_change=lambda n: setattr(self, "_topack_page", n),
        )
        section.set_page(self._topack_page)
        fl.addWidget(section)
        # the two panels are stretched to the same height; the spare space
        # belongs at the bottom, not between the heading and the table
        fl.addStretch(1)
        return frame

    def _boxes_panel(self, o, pd, done):
        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        fl.addWidget(h4(f"Упаковано ({len(pd['boxes'])})"))

        rows = []
        for b in pd["boxes"]:
            # артикул не показываем: он внутри штрихкода, а панель узкая —
            # иначе колонка с кнопками уезжает за край при небольшом окне
            cells = [("h", b["barcode"], theme.ACCENT_RAMP[700]),
                     f'{b["qty"]} {store.item_unit(b["article"])}',
                     f'{b["weight"]} кг']
            cells.append("" if done else ("w", lambda bc=b["barcode"]: self._box_actions(bc)))
            rows.append((cells, b["barcode"]))

        section = TableSection(
            headers=["Штрихкод", "Кол-во", "Вес", ""],
            widths=[90, 60, 60, 62], rows=rows,
            page_size=PANEL_PAGE_SIZE, auto_rows=True, framed=False,
            empty_text="Ещё нет упакованных коробок",
            on_page_change=lambda n: setattr(self, "_boxes_page", n),
        )
        section.set_page(self._boxes_page)
        fl.addWidget(section)
        # the two panels are stretched to the same height; the spare space
        # belongs at the bottom, not between the heading and the table
        fl.addStretch(1)
        return frame

    def _box_actions(self, barcode):
        """Reprint / delete — the mockup's last column."""
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addStretch(1)               # действия прижаты к правому краю строки
        has_printer = devices.available("printer")
        reprint = icon_button("printer",
                              "Перепечатать этикетку" if has_printer else NO_PRINTER,
                              theme.ACCENT, size=15, box=26, ghost=True)
        reprint.setEnabled(has_printer)
        reprint.clicked.connect(lambda _=False, bc=barcode: self._reprint_box(bc))
        remove = icon_button("trash", "Удалить коробку", theme.ACCENT,
                             size=15, box=26, ghost=True)
        remove.clicked.connect(lambda _=False, bc=barcode: self._delete_box(bc))
        lay.addWidget(reprint)
        lay.addWidget(remove)
        return wrap

    def _reprint_box(self, barcode):
        if not devices.available("printer"):
            return
        pd = _pack(self._active_id)
        box = next((b for b in pd["boxes"] if b["barcode"] == barcode), None)
        if box is not None:
            # Ключ обязан быть новым: по совпадающему служба считает задание
            # повтором и возвращает старое, ничего не печатая. Идемпотентность
            # нужна первой печати (защита от двойного клика), а перепечатка —
            # это осознанная просьба выдать ещё одну этикетку.
            devices.print_label(
                key=f"box-{barcode}#{time.time_ns()}",
                payload=self._label_zpl(barcode, store.item_name(box["article"]),
                                        box["qty"], store.item_unit(box["article"]),
                                        box["weight"]),
            )
        self._print_msg = f"Этикетка {barcode} отправлена на печать"
        self._render()

    def _select_position(self, article):
        self._active_article = article
        self._weighed = None
        self._render()

    def _cancel_active(self):
        self._active_article = None
        self._weighed = None
        self._render()

    def _read_scale(self, o, pd):
        pos = next(p for p in _positions(o) if p["article"] == self._active_article)
        remaining = pos["qty"] - _packed_qty(pd, pos["article"])
        if remaining <= 0:
            return
        uw = _uw(pos["article"])
        per_box = max(1, int(MAX_BOX_WEIGHT // uw))
        qty = min(remaining, per_box)
        expected = qty * uw
        if devices.available("scale"):
            weight = devices.read_weight(expected)
            if weight is None:      # весы молчат — не блокируем работу
                weight = weight_dialog(self, hint="весы не ответили, введите вес")
                if weight is None:
                    return
        else:
            # no scales: the operator reads the display and types the weight in
            weight = weight_dialog(self, hint=f"не более {MAX_BOX_WEIGHT:.0f} кг на коробку")
            if weight is None:
                return
        computed = max(1, round(weight / uw))
        self._weighed = {"weight": f"{weight:.2f}", "qty": min(computed, remaining)}
        self._render()

    def _reweigh(self):
        self._weighed = None
        self._render()

    @staticmethod
    def _label_zpl(barcode, name, qty, unit, weight):
        """Этикетка коробки 58×40 мм при 203 dpi.

        Макет живёт здесь только до появления сервера: по плану шаблон хранится
        на нём, чтобы правка не требовала пересборки приложения.
        """
        title = name[:28]
        return (
            "^XA"
            "^CI28"                       # UTF-8, иначе кириллица уедет
            "^PW464^LL320"
            f"^FO24,24^A0N,28,28^FD{title}^FS"
            f"^FO24,64^A0N,24,24^FD{qty} {unit} / {weight} кг^FS"
            f"^FO24,110^BY2^BCN,90,Y,N,N^FD{barcode}^FS"
            "^XZ"
        )

    def _print_label(self, o, pd):
        if not devices.available("printer"):
            return
        pos = next(p for p in _positions(o) if p["article"] == self._active_article)
        seq = len(pd["boxes"]) + 1
        barcode = f'SH{o["number"]}{pos["article"]}-{seq:02d}'
        pd["boxes"].append({"barcode": barcode, "article": pos["article"],
                            "qty": self._weighed["qty"], "weight": self._weighed["weight"]})
        pd["responsible"] = pd["responsible"] or store.current_user_name()
        devices.print_label(
            key=f"box-{barcode}",
            payload=self._label_zpl(barcode, pos["name"], self._weighed["qty"],
                                    pos["unit"], self._weighed["weight"]),
        )
        remaining_after = pos["qty"] - _packed_qty(pd, pos["article"])
        self._weighed = None
        if remaining_after <= 0:
            self._active_article = None
        self._print_msg = f"Этикетка {barcode} отправлена на печать"
        _save_pack(self._active_id)
        self._render()

    def _delete_box(self, barcode):
        pd = _pack(self._active_id)
        pd["boxes"] = [b for b in pd["boxes"] if b["barcode"] != barcode]
        self._print_msg = ""
        _save_pack(self._active_id)
        self._render()

    def _request_ship(self, o):
        pd = _pack(self._active_id)
        shortage = [(p["name"], p["unit"], p["qty"] - _packed_qty(pd, p["article"]))
                    for p in _positions(o) if p["qty"] - _packed_qty(pd, p["article"]) > 0]
        if shortage:
            lines = "\n".join(f'· {n} — осталось {rem} {u}' for n, u, rem in shortage)
            if confirm_dialog(self, "Упакованы не все позиции",
                              f"Осталось упаковать позиций: {len(shortage)}. Заказ будет отгружен с недостачей.\n\n{lines}",
                              confirm_label="Отгрузить с недостачей"):
                self._ship_now(o)
        else:
            self._ship_now(o)

    def _ship_now(self, o):
        shipped_at = store.format_now()
        pd = _pack(self._active_id)
        pd["done"] = True
        pd["shippedAt"] = shipped_at
        pd["responsible"] = pd["responsible"] or store.current_user_name()
        _save_pack(self._active_id)
        orders = store.load_orders()
        for x in orders:
            if x["id"] == o["id"]:
                x["status"] = "shipped"
                x["shipDateTime"] = shipped_at
                x["history"] = x.get("history", []) + [{"status": "shipped", "dateTime": shipped_at}]
                break
        store.save_orders(orders)
        self._active_article = None
        self._weighed = None
        self._render()
