"""Приемка — scan incoming boxes against expected weight and accept batches.

Batches come from a demo supplier list plus our own outgoing orders that are in
transit (status processing/received). List ⇄ detail and scan progress are kept
inside the page for the session.
"""
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from .. import devices, store, theme
from ..widgets.blueprint import BlueprintFrame
from ..widgets.common import Tag, button, h1, h4, icon_button
from ..widgets.dialog import confirm_dialog, weight_dialog
from ..widgets.flow import FlowRow
from ..widgets.table import TableSection
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
from .shipping import PANEL_PAGE_SIZE, _kicker_value, _within

_BATCH_DATA = {}   # per-session cache of the scan progress kept in the store


def _batches():
    """Supplier batches from the store plus our own orders that are in transit."""
    out = [dict(b) for b in store.receiving_batches()]
    for o in store.load_orders():
        if o["direction"] == "ours" and o["status"] in ("processing", "received"):
            out.append({
                "id": f"ord-{o['id']}", "number": o["number"],
                "supplier": o["counterpartyWarehouse"],
                "shipDateTime": o["shipDateTime"],
                "createdDateTime": o["createdDateTime"],
                # one box per position, weighing the whole line
                "positions": [{"article": p["article"], "boxes": 1,
                               "boxWeight": store.item_weight(p["article"]) * p["qty"]}
                              for p in o["positions"]],
                "orderId": o["id"],
            })
    return out


def _batch_by_id(bid):
    for b in _batches():
        if str(b["id"]) == str(bid):
            return b
    return None


def _batch_positions(b):
    return b["positions"]


def _total_boxes(b):
    return sum(p["boxes"] for p in b["positions"])


def _total_weight(b):
    return sum(p["boxes"] * p["boxWeight"] for p in b["positions"])


def _batch_boxes(batch):
    """Expand the positions of a batch into the individual boxes to scan."""
    boxes = []
    code = store.warehouse_code()
    for p in batch["positions"]:
        article, count, weight = p["article"], p["boxes"], p["boxWeight"]
        item = store.catalog_item(article) or {}
        base = f"WH{code}{batch['number']}{article}"
        for i in range(1, count + 1):
            boxes.append({
                "barcode": base + (f"-{i:02d}" if count > 1 else ""),
                "article": article, "code1c": item.get("code1c", "—"),
                "name": item.get("name", article),
                "boxLabel": (f"Коробка {i} из {count}" if count > 1 else "Коробка 1 из 1"),
                "expectedWeight": f"{weight:.1f}",
            })
    return boxes


# what a scanned box keeps in the file — the rest is looked up in the catalogue
_SCAN_KEYS = ("barcode", "article", "actualWeight", "diffKg", "diffPercent", "isMissing")


def _bdata(bid):
    """Scan progress for a batch, restored from the store on first use."""
    if bid not in _BATCH_DATA:
        saved = store.batch_progress(bid) or {}
        scanned = []
        for entry in saved.get("scanned", []):
            item = store.catalog_item(entry.get("article")) or {}
            scanned.append(dict(entry, code1c=item.get("code1c", "—"),
                                name=item.get("name", entry.get("article", ""))))
        done_codes = {e["barcode"] for e in scanned}
        batch = _batch_by_id(bid)
        pending = [b for b in _batch_boxes(batch) if b["barcode"] not in done_codes] if batch else []
        _BATCH_DATA[bid] = {"pending": pending, "scanned": scanned,
                            "done": saved.get("done", False),
                            "responsible": saved.get("responsible"),
                            "acceptedAt": saved.get("acceptedAt")}
    return _BATCH_DATA[bid]


def _save_bdata(bid):
    bd = _BATCH_DATA[bid]
    store.save_batch_progress(bid, {
        "scanned": [{k: e[k] for k in _SCAN_KEYS if k in e} for e in bd["scanned"]],
        "done": bd["done"], "responsible": bd["responsible"],
        "acceptedAt": bd["acceptedAt"],
    })


class ReceivingPage(Page):
    def build(self):
        self._active_id = None
        self._active_box = None
        self._scan_error = ""
        self._last_weight = None
        self._live = None               # текущее показание весов, (кг, устойчиво)
        self._scale_value = None        # ярлык панели «Весы», пока она на экране
        self._search = ""
        self._status = "all"
        self._pending_page = 1
        self._scanned_page = 1
        # filters keep their value in the page: the list is rebuilt from
        # scratch every time the user comes back from a batch
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
        self._clear_layout(self._container)
        self._container.reset_blocks()
        self._scale_value = None
        if self._active_id is None:
            self._build_list()
        else:
            self._build_detail()
        # поток нужен только на экране партии, где панель весов видна
        devices.live_weight(self._active_id is not None)

    def _on_live_weight(self, kg, stable):
        """Показание с весов — панель обновляется, не перерисовывая экран."""
        self._live = (kg, stable)
        if self._scale_value is None:
            return
        try:
            self._scale_value.setText(f"{kg:.1f} кг")
            self._scale_value.setStyleSheet(self._scale_style(stable))
        except RuntimeError:
            self._scale_value = None    # ярлык уже уничтожен перерисовкой

    @staticmethod
    def _scale_style(stable):
        color = theme.ACCENT_RAMP[700] if stable else theme.NEUTRAL[600]
        return f"font-family:{theme.font_heading()};font-size:36px;color:{color};"

    # ── list ──
    def _build_list(self):
        crumb = QLabel(f'<a href="#" style="color:{theme.NEUTRAL[600]};text-decoration:none;">ProЗапас</a> / Приемка')
        crumb.setObjectName("breadcrumb"); crumb.setTextFormat(Qt.TextFormat.RichText)
        self._container.add_block(crumb)

        title = QVBoxLayout(); title.setSpacing(4)
        title.addWidget(h1("Приемка"))
        sub = QLabel("Партии от поставщиков, которые нужно принять")
        sub.setObjectName("muted"); title.addWidget(sub)
        self._container.add_block(title)

        self._search_input = QLineEdit(); self._search_input.setPlaceholderText("Номер заказа")
        self._search_input.setText(self._search)
        self._search_input.textChanged.connect(self._on_search)
        self._status_input = QComboBox()
        for v, t in [("all", "Все статусы"), ("waiting", "Ожидает"), ("progress", "В работе"), ("done", "Принят")]:
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
            headers=["Заказ", "Статус", "Прогресс", "Вес, кг", "Ответственный", "Создан", "Принят"],
            widths=[72, 116, 96, 96, 0, 124, 124], rows=self._list_rows(),
            on_row_click=self._open, page_size=13, auto_rows=True,
        )
        self._container.add_block(self._table)

    def _list_rows(self):
        q = self._search.strip().lower()
        wmin = number_value(self._weight_min_input)
        wmax = number_value(self._weight_max_input)
        rows = []
        for b in _batches():
            number = b["number"]
            if q and q not in number.lower():
                continue
            weight = _total_weight(b)
            if wmin is not None and weight < wmin:
                continue
            if wmax is not None and weight > wmax:
                continue
            if not _within(b["createdDateTime"], self._created_from, self._created_to):
                continue
            if not _within(b["shipDateTime"], self._ship_from, self._ship_to):
                continue
            bd = _BATCH_DATA.get(b["id"]) or store.batch_progress(b["id"])
            scanned = len(bd["scanned"]) if bd else 0
            done = bd["done"] if bd else False
            if done:
                label, color, bg, key = "Принят", theme.ACCENT_RAMP[700], "transparent", "done"
            elif scanned > 0:
                label, color, bg, key = "В работе", theme.ACCENT2_RAMP[700], theme.ACCENT2_RAMP[100], "progress"
            else:
                label, color, bg, key = "Ожидает", theme.NEUTRAL[800], theme.NEUTRAL[200], "waiting"
            if self._status != "all" and key != self._status:
                continue
            total = _total_boxes(b)
            accepted = (bd["acceptedAt"].split(" ")[0] if (done and bd and bd["acceptedAt"]) else "—")
            responsible = (bd["responsible"] if bd and bd["responsible"] else "—")
            rows.append((
                [("h", "№" + number), ("tag", label, color, bg), f"{scanned} из {total}",
                 ("m", f"{_total_weight(b):.1f} кг"), ("m", responsible),
                 ("m", b["createdDateTime"].split(' ')[0]), ("m", accepted)],
                b["id"],
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

    def _open(self, bid):
        _bdata(bid)
        self._active_id = bid
        self._pending_page = 1
        self._scanned_page = 1
        self._active_box = None
        self._scan_error = ""
        self._last_weight = None
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
        b = _batch_by_id(self._active_id)
        bd = _bdata(self._active_id)
        scanned = len(bd["scanned"])
        total = _total_boxes(b)
        done = bd["done"]

        crumb = QLabel(
            f'<a href="#home" style="color:{theme.NEUTRAL[600]};text-decoration:none;">ProЗапас</a> / '
            f'<a href="#back" style="color:{theme.NEUTRAL[600]};text-decoration:none;">Приемка</a> / №{b["number"]}')
        crumb.setObjectName("breadcrumb"); crumb.setTextFormat(Qt.TextFormat.RichText)
        crumb.linkActivated.connect(lambda href: self._back() if href == "#back" else self.nav.go("home"))
        self._container.add_block(crumb)

        head = QHBoxLayout()
        left = QVBoxLayout(); left.setSpacing(4)
        left.addWidget(h1(f"Заказ №{b['number']}"))
        sub = QLabel("Приём товаров и материалов от поставщиков")
        sub.setObjectName("muted"); left.addWidget(sub)
        head.addLayout(left); head.addStretch(1)
        complete = button("Завершить приемку", "primary")
        complete.clicked.connect(lambda: self._request_complete(b))
        head.addWidget(complete, 0, Qt.AlignmentFlag.AlignTop)
        self._container.add_block(head)

        if done:
            label, color, bg = "Принят", theme.ACCENT_RAMP[700], "transparent"
        elif scanned > 0:
            label, color, bg = "В работе", theme.ACCENT2_RAMP[700], theme.ACCENT2_RAMP[100]
        else:
            label, color, bg = "Ожидает", theme.NEUTRAL[800], theme.NEUTRAL[200]
        info = BlueprintFrame(padding=theme.SP4)
        # `flex-wrap: wrap` in the mockup: the fields move to the next line
        # instead of being squeezed when the window narrows
        irow = FlowRow(h_spacing=theme.SP8, v_spacing=theme.SP4)
        stat = QWidget(); sv = QVBoxLayout(stat); sv.setContentsMargins(0, 0, 0, 0); sv.setSpacing(2)
        sk = QLabel("Статус"); sk.setObjectName("kicker"); sv.addWidget(sk); sv.addWidget(Tag(label, color, bg))
        irow.add(stat)
        irow.add(_kicker_value("Ответственный", bd["responsible"] or "—"))
        irow.add(_kicker_value("Дата отгрузки", b["shipDateTime"]))
        irow.add(_kicker_value("Дата принятия", bd["acceptedAt"] or "—"))
        irow.add(_kicker_value("Дата создания", b["createdDateTime"]))
        irow.add(_kicker_value("Позиций", len(_batch_positions(b))))
        irow.add(_kicker_value("Коробок", total))
        irow.add(_kicker_value("Общий вес", f"{_total_weight(b):.1f} кг"))
        irow.add(_kicker_value("Прогресс", f"{scanned} из {total}"))
        info.content_layout().addWidget(irow)
        self._container.add_block(info)

        # scan + scale
        scan_row = QHBoxLayout(); scan_row.setSpacing(theme.SP6)
        scan_row.addWidget(self._scan_panel(bd), 2)
        scan_row.addWidget(self._scale_panel(), 1)
        self._container.add_block(scan_row)

        two = QHBoxLayout(); two.setSpacing(theme.SP6)
        two.addWidget(self._pending_panel(bd), 1)
        two.addWidget(self._scanned_panel(bd), 1)
        self._container.add_block(two)

    def _scan_panel(self, bd):
        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        if self._active_box:
            ab = self._active_box
            top = QHBoxLayout()
            box = QVBoxLayout(); box.setSpacing(2)
            kick = QLabel("В работе"); kick.setStyleSheet(f"font-size:11px;color:{theme.ACCENT_RAMP[700]};text-transform:uppercase;")
            name = QLabel(f'{ab["name"]} · {ab["boxLabel"]} · {ab["expectedWeight"]} кг')
            name.setStyleSheet(f"font-family:{theme.font_heading()};font-size:18px;")
            meta = QLabel("Поставьте коробку на весы и отсканируйте штрихкод ещё раз для подтверждения")
            meta.setWordWrap(True); meta.setStyleSheet(f"font-size:13px;color:{theme.NEUTRAL[600]};")
            box.addWidget(kick); box.addWidget(name); box.addWidget(meta)
            top.addLayout(box); top.addStretch(1)
            cancel = button("Отменить", "ghost"); cancel.clicked.connect(self._cancel_active)
            top.addWidget(cancel, 0, Qt.AlignmentFlag.AlignTop)
            fl.addLayout(top)
        else:
            hint = QLabel("Отсканируйте штрихкод коробки или введите его вручную")
            hint.setStyleSheet(f"font-size:12px;color:{theme.NEUTRAL[600]};")
            fl.addWidget(hint)

        self._scan_input = QLineEdit()
        self._scan_input.setStyleSheet(f"font-family:{theme.font_heading()};")
        self._scan_input.returnPressed.connect(lambda: self._scan(self._scan_input.text()))
        self._scan_input.setPlaceholderText("Штрихкод коробки, например WH1281187201187-02")
        fl.addWidget(self._scan_input)
        if self._scan_error:
            err = QLabel(self._scan_error)
            err.setWordWrap(True); err.setStyleSheet(f"font-size:12px;color:{theme.ACCENT_RAMP[800]};")
            fl.addWidget(err)
        return frame

    def _scale_panel(self):
        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        fl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        k = QLabel("Весы"); k.setObjectName("kicker"); k.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # пока весы шлют показания, панель живёт ими; иначе остаётся последний
        # взвешенный результат
        live = self._live if devices.available("scale") and self._live else None
        stable = True
        if live is not None:
            reading, stable = f"{live[0]:.1f} кг", live[1]
        else:
            reading = f"{self._last_weight} кг" if self._last_weight else "—"
        r = QLabel(reading); r.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r.setStyleSheet(self._scale_style(stable))
        self._scale_value = r
        fl.addWidget(k); fl.addWidget(r)
        return frame

    def _pending_panel(self, bd):
        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        fl.addWidget(h4("К сканированию"))

        active = self._active_box["barcode"] if self._active_box else None
        # артикул не показываем: он уже внутри штрихкода, а панель узкая
        rows = [([("h", p["barcode"], theme.ACCENT_RAMP[700]),
                  p["name"],
                  f'{p["expectedWeight"]} кг'],
                 p["barcode"],
                 theme.ACCENT_RAMP[100] if p["barcode"] == active else None)
                for p in bd["pending"]]

        section = TableSection(
            headers=["Штрихкод", "Наименование", "Вес по заказу"],
            widths=[90, 80, 80], rows=rows, elastic={1},
            page_size=PANEL_PAGE_SIZE, auto_rows=True, framed=False,
            empty_text="Все коробки отсканированы",
            on_page_change=lambda n: setattr(self, "_pending_page", n),
        )
        section.set_page(self._pending_page)
        fl.addWidget(section)
        # the two panels are stretched to the same height; the spare space
        # belongs at the bottom, not between the heading and the table
        fl.addStretch(1)
        return frame

    def _scanned_panel(self, bd):
        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        fl.addWidget(h4("Отсканировано"))

        rows = []
        for s in bd["scanned"]:
            if s.get("isMissing"):
                weight, diff = "—", ("m", "Отсутствует")     # .diff-ok in the mockup
            else:
                sign = "+" if float(s["diffKg"]) >= 0 else "-"
                weight = f'{s["actualWeight"]} кг'
                diff = ("m", f'{sign}{s["diffPercent"]} %')
            cells = [("h", s["barcode"], theme.NEUTRAL[600]),
                     s["name"], weight, diff]
            # an accepted batch is a closed document — nothing is taken back
            cells.append("" if bd["done"]
                         else ("w", lambda bc=s["barcode"]: self._undo_cell(bc)))
            rows.append((cells, s["barcode"]))

        section = TableSection(
            # заголовки укорочены: панель занимает половину ширины, и с полными
            # подписями колонка с действием уезжала за край
            headers=["Штрихкод", "Наименование", "Вес", "Расхожд.", ""],
            widths=[80, 62, 56, 60, 34], rows=rows, elastic={1},
            page_size=PANEL_PAGE_SIZE, auto_rows=True, framed=False,
            empty_text="Пока ничего не отсканировано",
            on_page_change=lambda n: setattr(self, "_scanned_page", n),
        )
        section.set_page(self._scanned_page)
        fl.addWidget(section)
        # the two panels are stretched to the same height; the spare space
        # belongs at the bottom, not between the heading and the table
        fl.addStretch(1)
        return frame

    def _undo_cell(self, barcode):
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        btn = icon_button("trash", "Убрать из отсканированных", theme.ACCENT,
                          size=15, box=26, ghost=True)
        btn.clicked.connect(lambda _=False, bc=barcode: self._undo_scan(bc))
        lay.addWidget(btn)
        return wrap

    def _undo_scan(self, barcode):
        """Take a box back out of «Отсканировано» — it returns to the queue."""
        bd = _bdata(self._active_id)
        if bd["done"]:
            return
        bd["scanned"] = [e for e in bd["scanned"] if e["barcode"] != barcode]
        # rebuild the queue from the batch so the boxes keep their original order
        done_codes = {e["barcode"] for e in bd["scanned"]}
        batch = _batch_by_id(self._active_id)
        bd["pending"] = [b for b in _batch_boxes(batch) if b["barcode"] not in done_codes]
        if self._active_box and self._active_box["barcode"] == barcode:
            self._active_box = None
        self._scan_error = ""
        _save_bdata(self._active_id)
        self._render()

    # ── scanning ──
    def on_scan(self, code):
        """Штрихкод от сканера — принимаем только в открытой партии."""
        if self._active_id is not None:
            self._scan(code)

    def _scan(self, barcode):
        code = (barcode or "").strip().upper()
        if not code:
            return
        bd = _bdata(self._active_id)
        if not self._active_box:
            item = next((p for p in bd["pending"] if p["barcode"] == code), None)
            if not item:
                self._scan_error = "Штрихкод не найден в этой партии."
                self._render()
                return
            bd["responsible"] = bd["responsible"] or store.current_user_name()
            self._active_box = item
            self._scan_error = ""
            self._render()
            return
        if code != self._active_box["barcode"]:
            self._scan_error = "Это другая коробка. Поставьте на весы ту же коробку и отсканируйте ещё раз."
            self._render()
            return
        item = self._active_box
        expected = float(item["expectedWeight"])
        if devices.available("scale"):
            actual = devices.read_weight(expected)
            if actual is None:
                self._scan_error = "Вес на весах не устоялся — подтвердите вручную."
                actual = weight_dialog(self, hint=f"по заказу {expected:.1f} кг",
                                       value=devices.last_live_weight())
                if actual is None:
                    self._render()
                    return
        else:
            actual = weight_dialog(self, hint=f"по заказу {expected:.1f} кг")
            if actual is None:
                return
        diff_kg = actual - expected
        diff_percent = abs(diff_kg / expected * 100) if expected else 0.0
        bd["pending"] = [p for p in bd["pending"] if p["barcode"] != item["barcode"]]
        bd["scanned"].append(dict(item, actualWeight=f"{actual:.1f}",
                                  diffKg=f"{diff_kg:.1f}", diffPercent=f"{diff_percent:.1f}"))
        self._last_weight = f"{actual:.1f}"
        _save_bdata(self._active_id)
        self._active_box = None
        self._scan_error = ""
        self._render()

    def _cancel_active(self):
        self._active_box = None
        self._scan_error = ""
        self._render()

    # ── complete ──
    def _request_complete(self, b):
        bd = _bdata(self._active_id)
        if bd["pending"]:
            lines = "\n".join(f'· {p["barcode"]} — {p["name"]}' for p in bd["pending"])
            if confirm_dialog(self, "Не все коробки отсканированы",
                              f"Осталось не отсканировано: {len(bd['pending'])}. "
                              f"Эти позиции будут отмечены как отсутствующие.\n\n{lines}",
                              confirm_label="Завершить с недостачей"):
                self._complete(b)
        else:
            self._complete(b)

    def _complete(self, b):
        bd = _bdata(self._active_id)
        accepted = store.format_now()
        bd["done"] = True
        bd["acceptedAt"] = accepted
        bd["responsible"] = bd["responsible"] or store.current_user_name()
        for p in bd["pending"]:
            bd["scanned"].append(dict(p, isMissing=True))
        bd["pending"] = []
        _save_bdata(self._active_id)
        # if this batch is one of our orders, mark it received
        if isinstance(self._active_id, str) and self._active_id.startswith("ord-"):
            oid = int(self._active_id.split("-")[1])
            orders = store.load_orders()
            for o in orders:
                if o["id"] == oid:
                    o["status"] = "received"
                    o["acceptedAt"] = accepted
                    o["history"] = o.get("history", []) + [{"status": "received", "dateTime": accepted}]
                    break
            store.save_orders(orders)
        self._render()
