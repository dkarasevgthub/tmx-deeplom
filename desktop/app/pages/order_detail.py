"""Заказ — order detail with status, parties, positions, history, actions."""
import random

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QLabel, QWidget, QLineEdit

from .. import theme, store
from .base import Page
from ..widgets.common import h1, h4, button, Tag
from ..widgets.blueprint import BlueprintFrame
from ..widgets.flow import FlowRow
from ..widgets.table import TableSection
from ..widgets.dialog import form_dialog

OUR_WAREHOUSE = "Склад №2"
OUR_RESPONSIBLE = "Кузнецов И.А."
PICKERS = ["Смирнов А.П.", "Ковалёв Д.С.", "Егорова Н.И."]


def _info_cell(kicker, value):
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    k = QLabel(kicker)
    k.setObjectName("kicker")
    val = QLabel(str(value))
    val.setStyleSheet(f"font-family:{theme.font_heading()};font-size:18px;")
    v.addWidget(k)
    v.addWidget(val)
    return box


def _info_panel(cells):
    """`display:flex; gap:var(--space-8); flex-wrap:wrap` — cells keep their
    natural width and move to the next line instead of squeezing the text."""
    frame = BlueprintFrame(padding=theme.SP4)
    row = FlowRow(h_spacing=theme.SP8, v_spacing=theme.SP4)
    for kicker, value in cells:
        row.add(_info_cell(kicker, value))
    frame.content_layout().addWidget(row)
    return frame


class OrderDetailPage(Page):
    def build(self):
        oid = self.params.get("id")
        order = store.order_by_id(oid)

        crumb = QLabel(
            f'<a href="#home" style="color:{theme.NEUTRAL[600]};text-decoration:none;">ProЗапас</a> / '
            f'<a href="#orders" style="color:{theme.NEUTRAL[600]};text-decoration:none;">Заказы</a> / '
            + (f'№{order["number"]}' if order else "—")
        )
        crumb.setObjectName("breadcrumb")
        crumb.setTextFormat(Qt.TextFormat.RichText)
        crumb.linkActivated.connect(lambda href: self.nav.go("orders" if "orders" in href else "home"))
        self.add_block(crumb)

        if not order:
            self._not_found()
            return

        self._render(order)

    def _not_found(self):
        frame = BlueprintFrame(padding=theme.SP8)
        fl = frame.content_layout()
        fl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = QLabel("Заказ не найден")
        t.setStyleSheet(f"font-family:{theme.font_heading()};font-size:25px;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d = QLabel("Проверьте ссылку или вернитесь к списку заказов.")
        d.setStyleSheet(f"font-size:13px;color:{theme.NEUTRAL[600]};")
        d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fl.addWidget(t)
        fl.addWidget(d)
        self.add_block(frame)
        self.col.addStretch(1)

    def _render(self, order):
        is_ours = order["direction"] == "ours"
        is_theirs = not is_ours
        status = order["status"]

        # ── header + actions ──
        head = QHBoxLayout()
        # self.col has spacing 0 and nested layouts inherit it, so the gap
        # between the action buttons has to be set here
        head.setSpacing(theme.SP3)
        left = QVBoxLayout(); left.setSpacing(4)
        left.addWidget(h1(f'Заказ №{order["number"]}'))
        sub = QLabel("Перемещение товара со склада-отправителя")
        sub.setObjectName("muted")
        left.addWidget(sub)
        head.addLayout(left)
        head.addStretch(1)

        if status == "created" and is_theirs:
            decline = button("Отклонить", "secondary")
            decline.clicked.connect(lambda: self._decline(order))
            accept = button("Принять заказ", "primary")
            accept.clicked.connect(lambda: self._transition(order, "processing", {
                "packedIndexes": [], "pickStartedAt": store.format_now(),
                "pickResponsible": random.choice(PICKERS)}))
            head.addWidget(decline, 0, Qt.AlignmentFlag.AlignTop)
            head.addWidget(accept, 0, Qt.AlignmentFlag.AlignTop)
        elif is_ours and status in ("created", "processing"):
            cancel = button("Отменить заказ", "secondary")
            cancel.clicked.connect(lambda: self._cancel(order))
            head.addWidget(cancel, 0, Qt.AlignmentFlag.AlignTop)
        self.add_block(head)

        # ── status panel: the status cell holds a tag, the rest plain text ──
        label, color, bg = theme.status_meta(status)
        status_frame = BlueprintFrame(padding=theme.SP4)
        srow = FlowRow(h_spacing=theme.SP8, v_spacing=theme.SP4)
        stat_box = QWidget(); sv = QVBoxLayout(stat_box); sv.setContentsMargins(0, 0, 0, 0); sv.setSpacing(2)
        sk = QLabel("Статус"); sk.setObjectName("kicker")
        sv.addWidget(sk); sv.addWidget(Tag(label, color, bg))
        srow.add(stat_box)
        srow.add(_info_cell("Позиций", len(order["positions"])))
        srow.add(_info_cell("Дата создания", order["createdDateTime"]))
        srow.add(_info_cell("Дата отгрузки", order["shipDateTime"]))
        srow.add(_info_cell("Дата приёмки", order.get("acceptedAt") or "—"))
        status_frame.content_layout().addWidget(srow)
        self.add_block(status_frame)

        # ── parties panel ──
        sender_wh = order["counterpartyWarehouse"] if is_ours else OUR_WAREHOUSE
        sender_resp = order["counterpartyResponsible"] if is_ours else order["responsible"]
        receiver_wh = OUR_WAREHOUSE if is_ours else order["counterpartyWarehouse"]
        receiver_resp = order["responsible"] if is_ours else order["counterpartyResponsible"]
        self.add_block(_info_panel([
            ("Получатель", receiver_wh),
            ("Ответственный-получатель", receiver_resp),
            ("Отправитель", sender_wh),
            ("Ответственный-отправитель", sender_resp),
        ]))

        # ── picking progress (theirs + processing) or a contextual note ──
        if status == "processing" and is_theirs:
            self.add_block(self._progress_panel(order))
        else:
            note = self._context_note(order, is_ours, is_theirs)
            if note:
                self.add_block(note)

        # ── positions + history: grid-template-columns 1.5fr 1fr, align start ──
        two = QHBoxLayout()
        two.setSpacing(theme.SP6)
        two.addWidget(self._positions_panel(order), 3, Qt.AlignmentFlag.AlignTop)
        two.addWidget(self._history_panel(order), 2, Qt.AlignmentFlag.AlignTop)
        self.add_block(two)
        self.col.addStretch(1)

    def _progress_panel(self, order):
        """Shown while our warehouse is picking an incoming order."""
        packed = len(order.get("packedIndexes") or [])
        total = len(order["positions"])
        if packed == 0:
            shipment = "Ожидает"
        elif packed < total:
            shipment = "В работе"
        else:
            shipment = "Отгружен"
        return _info_panel([
            ("Статус отгрузки", shipment),
            ("Начало сборки", order.get("pickStartedAt") or "—"),
            ("Ответственный", order.get("pickResponsible") or "—"),
            ("Прогресс сборки", f"{packed} из {total} позиций"),
        ])

    def _outcome_note(self, title, reason):
        """Declined / cancelled: a muted headline with the reason under it."""
        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        fl.setSpacing(2)
        head = QLabel(title)
        head.setStyleSheet(f"font-size:13px;color:{theme.NEUTRAL[600]};")
        fl.addWidget(head)
        if reason:
            body = QLabel(reason)
            body.setWordWrap(True)
            body.setStyleSheet("font-size:13px;")
            fl.addWidget(body)
        return frame

    def _context_note(self, order, is_ours, is_theirs):
        status = order["status"]
        if status == "declined":
            return self._outcome_note("Заказ отклонён", order.get("declineReason"))
        if status == "cancelled":
            return self._outcome_note("Заказ отменён", order.get("cancelReason"))

        text = None
        if status == "shipped" and is_theirs:
            text = f'Заказ отгружен получателю — {order["counterpartyWarehouse"]}. Ожидает подтверждения приёмки на их стороне.'
        elif status == "created" and is_ours:
            text = "Заявка отправлена и ожидает обработки на складе-отправителе."
        elif status == "processing" and is_ours:
            text = "Заказ в обработке — ожидает отгрузки со склада-отправителя."
        if not text:
            return None
        frame = BlueprintFrame(padding=theme.SP4)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"font-size:13px;color:{theme.NEUTRAL[600]};")
        frame.content_layout().addWidget(lbl)
        return frame

    def _positions_panel(self, order):
        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        fl.setSpacing(theme.SP3)            # h4 margin-bottom

        head = QHBoxLayout()
        head.addWidget(h4("Состав заказа"), 0, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        self._pos_search = QLineEdit()
        self._pos_search.setPlaceholderText("Поиск по артикулу")
        self._pos_search.setFixedWidth(190)
        self._pos_search.textChanged.connect(self._filter_positions)
        head.addWidget(self._pos_search, 0, Qt.AlignmentFlag.AlignBottom)
        fl.addLayout(head)

        # positions store an article; name and unit come from the catalogue
        self._positions = store.order_positions(order)
        # framed=False: this panel is already a blueprint frame
        self._pos_table = TableSection(
            headers=["Артикул", "Наименование", "Ед. изм.", "Кол-во"],
            widths=[110, 0, 90, 90], rows=self._position_rows(),
            page_size=10, auto_rows=True, framed=False,
            empty_text="Позиции с таким артикулом не найдены",
        )
        fl.addWidget(self._pos_table)
        return frame

    def _position_rows(self):
        query = self._pos_search.text().strip().lower()
        return [([("m", p["article"]), p["name"], ("m", p["unit"]), str(p["qty"])], None)
                for p in self._positions
                if not query or query in p["article"].lower()]

    def _filter_positions(self, _text):
        self._pos_table.set_rows(self._position_rows())

    def _history_panel(self, order):
        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        fl.setSpacing(theme.SP3)            # h4 margin-bottom
        fl.addWidget(h4("История"))

        # rows sit flush against each other; the divider is the row's own
        # bottom border, exactly like .eventrow in the mockup
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        for h in order["history"]:
            label, color, bg = theme.status_meta(h["status"])
            row = QWidget()
            row.setObjectName("histrow")
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row.setStyleSheet(
                f"QWidget#histrow{{background:transparent;"
                f"border-bottom:1px solid {theme.DIVIDER};}}"
                f"QWidget#histrow QLabel{{background:transparent;border:none;}}"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, theme.SP2, 0, theme.SP2)
            rl.setSpacing(theme.SP3)
            rl.addWidget(Tag(label, color, bg))
            rl.addStretch(1)
            dt = QLabel(h["dateTime"])
            dt.setStyleSheet(f"font-size:12px;color:{theme.NEUTRAL[600]};")
            rl.addWidget(dt)
            rows.addWidget(row)
        fl.addLayout(rows)
        return frame

    # ── transitions ──
    def _transition(self, order, new_status, extra):
        orders = store.load_orders()
        for o in orders:
            if o["id"] == order["id"]:
                o["status"] = new_status
                o.update(extra)
                o["history"] = o.get("history", []) + [{"status": new_status, "dateTime": store.format_now()}]
                break
        store.save_orders(orders)
        self.nav.go("order", id=order["id"])

    def _decline(self, order):
        def on_save(v):
            self._transition(order, "declined", {"declineReason": v["reason"].strip()})
            return None
        form_dialog(self, "Отклонить заказ",
                    [("reason", "Причина отказа (опционально)", "text", "")],
                    on_save, submit_label="Отклонить заказ")

    def _cancel(self, order):
        def on_save(v):
            self._transition(order, "cancelled", {"cancelReason": v["reason"].strip()})
            return None
        form_dialog(self, "Отменить заказ",
                    [("reason", "Причина отмены (опционально)", "text", "")],
                    on_save, submit_label="Отменить заказ")
