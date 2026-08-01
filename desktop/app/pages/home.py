"""Home dashboard."""
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel

from .. import theme, store
from .base import Page
from ..widgets.blueprint import BlueprintFrame
from ..widgets.common import h1, h4, breadcrumb, svg_pixmap

_MONTHS = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
           "июля", "августа", "сентября", "октября", "ноября", "декабря"]

EVENT_META = {
    "created":    (lambda n: f"Создан заказ №{n}", "Заказ", "tag-outline", "orders"),
    "processing": (lambda n: f"Заказ №{n} взят в обработку", "Заказ", "tag-outline", "orders"),
    "shipped":    (lambda n: f"Заказ №{n} отгружен", "Отгрузка", "tag-accent", "shipping"),
    "received":   (lambda n: f"Заказ №{n} принят", "Приёмка", "tag-neutral", "receiving"),
    "declined":   (lambda n: f"Заказ №{n} отклонён", "Заказ", "tag-outline", "orders"),
    "cancelled":  (lambda n: f"Заказ №{n} отменён", "Заказ", "tag-outline", "orders"),
}


def _fmt_short(s):
    if not s or s == "—":
        return ""
    d, *t = s.split(" ")
    dd, mm = d.split(".")[0], d.split(".")[1]
    return f"{dd}.{mm}" + (" " + t[0] if t else "")


class HomePage(Page):
    def build(self):
        orders = store.load_orders()
        me = store.current_user()
        role = me["role"] if me else "admin"
        first_name = "коллега"
        if me:
            parts = me["fullName"].split()
            first_name = parts[1] if len(parts) > 1 else parts[0]
        role_label = store.role_label(role)
        now = datetime.now()
        today = f"{now.day} {_MONTHS[now.month]} {now.year}"

        ours = [o for o in orders if o["direction"] == "ours"]
        theirs = [o for o in orders if o["direction"] == "theirs"]
        in_work = len([o for o in orders if o["status"] in ("created", "processing")])
        ours_in_work = len([o for o in ours if o["status"] in ("created", "processing")])
        theirs_in_work = len([o for o in theirs if o["status"] in ("created", "processing")])
        to_ship = theirs_in_work
        ship_waiting = len([o for o in theirs if o["status"] == "created"])
        to_receive = len([o for o in ours if o["status"] == "processing"])

        # ── breadcrumb + greeting ──
        self.add_block(breadcrumb("ProЗапас / Главная"))
        greet = QVBoxLayout()
        greet.setSpacing(4)
        greet.addWidget(h1(f"Здравствуйте, {first_name}"))
        sub = QLabel(f"{today} · {role_label} · ООО «Сталкер Групп»")
        sub.setObjectName("muted")
        greet.addWidget(sub)
        self.add_block(greet)

        # ── stat cards ──
        stats = [
            ("Заказы в работе", str(in_work), f"{ours_in_work} исходящих · {theirs_in_work} входящих", "orders"),
            ("К отгрузке", str(to_ship), f"{ship_waiting} ожидают сборки", "shipping"),
            ("К приёмке", str(to_receive), "наши заказы в пути", "receiving"),
        ]
        grid = QGridLayout()
        grid.setSpacing(theme.SP6)
        for i, (lbl, val, hint, dest) in enumerate(stats):
            grid.addWidget(self._stat_card(lbl, val, hint, dest), 0, i)
            grid.setColumnStretch(i, 1)     # repeat(3, 1fr)
        self.add_block(grid)

        # ── two panels ──
        # grid-template-columns:1.4fr 1fr; align-items:start — each panel is
        # only as tall as its own rows, so AlignTop must be per-widget
        panels = QHBoxLayout()
        panels.setSpacing(theme.SP6)
        panels.addWidget(self._tasks_panel(orders, role), 14, Qt.AlignmentFlag.AlignTop)
        panels.addWidget(self._events_panel(orders), 10, Qt.AlignmentFlag.AlignTop)
        self.add_block(panels)
        self.col.addStretch(1)

    # ── components ─────────────────────────────────────────────
    def _stat_card(self, lbl, val, hint, dest):
        card = BlueprintFrame(padding=theme.SP4, clickable=True, hover_accent=True)
        card.clicked.connect(lambda: self.nav.go(dest))
        cl = card.content_layout()
        # label ─SP2─ num ─SP1─ hint, per the mockup's margin-bottom/-top
        cl.setSpacing(0)
        k = QLabel(lbl); k.setObjectName("kicker")
        num = QLabel(val); num.setObjectName("statnum")
        h = QLabel(hint); h.setStyleSheet(f"font-size:12px;color:{theme.NEUTRAL[600]};")
        cl.addWidget(k)
        cl.addSpacing(theme.SP2)
        cl.addWidget(num)
        cl.addSpacing(theme.SP1)
        cl.addWidget(h)
        return card

    def _panel(self, title, right_widget=None):
        panel = BlueprintFrame(padding=theme.SP6)
        cl = panel.content_layout()
        cl.setSpacing(theme.SP4)      # head has margin-bottom: var(--space-4)
        head = QHBoxLayout()
        t = h4(title)
        head.addWidget(t, 0, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        if right_widget is not None:
            head.addWidget(right_widget, 0, Qt.AlignmentFlag.AlignBottom)
        cl.addLayout(head)
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        cl.addLayout(rows)
        return panel, cl, rows

    def _tag(self, text, cls):
        colors = {
            "tag-outline": ("transparent", theme.ACCENT, theme.ACCENT),
            "tag-accent": (theme.ACCENT_RAMP[100], theme.ACCENT_RAMP[800], None),
            "tag-neutral": (theme.NEUTRAL[100], theme.NEUTRAL[800], None),
        }[cls]
        bg, fg, border = colors
        style = f"background:{bg};color:{fg};font-size:11px;padding:3px 10px;"
        if border:
            style += f"border:1px solid {border};"
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFixedWidth(88)
        lbl.setStyleSheet(style)
        return lbl

    def _row(self, tag_widget, text, sub, on_click, chevron=True):
        row = QWidget()
        row.setObjectName("hrow")
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setStyleSheet(
            f"QWidget#hrow{{border-bottom:1px solid {theme.DIVIDER};background:transparent;}}"
            f"QWidget#hrow:hover{{background:{theme.ACCENT_RAMP[100]};}}"
        )
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(theme.SP2, theme.SP3, theme.SP2, theme.SP3)
        rl.setSpacing(theme.SP3)
        rl.addWidget(tag_widget)
        txt = QLabel(text)
        txt.setStyleSheet("font-size:14px;background:transparent;")
        rl.addWidget(txt, 1)
        s = QLabel(sub)
        s.setStyleSheet(f"font-size:12px;color:{theme.NEUTRAL[600]};background:transparent;")
        rl.addWidget(s)
        if chevron:
            chev = QLabel()
            chev.setPixmap(svg_pixmap("chevron", theme.NEUTRAL[500], 16))
            chev.setStyleSheet("background:transparent;")
            rl.addWidget(chev)
        row.mouseReleaseEvent = lambda e: on_click()
        return row

    def _tasks_panel(self, orders, role):
        def order_sub(o):
            return f"{len(o.get('positions', []))} поз. · {o.get('counterpartyWarehouse', '—')}"

        to_process = [o for o in orders if o["status"] == "created"]
        ship_queue = [o for o in orders if o["direction"] == "theirs" and o["status"] in ("created", "processing")]
        receive_queue = [o for o in orders if o["direction"] == "ours" and o["status"] in ("processing", "shipped")]

        tasks = []  # (tag, cls, text, sub, dest, params)
        if role == "manager":
            tasks = [("Заказ", "tag-outline", f"Обработать заказ {o['number']}", order_sub(o), "order", {"id": o["id"]}) for o in to_process]
        elif role == "stockman":
            tasks = ([("Отгрузка", "tag-accent", f"Собрать и отгрузить {o['number']}", order_sub(o), "shipping", {}) for o in ship_queue]
                     + [("Приёмка", "tag-neutral", f"Принять поставку {o['number']}", order_sub(o), "receiving", {}) for o in receive_queue])
        else:
            seen = set()
            for tag, cls, txt, sub, dest, params in (
                [("Заказ", "tag-outline", f"Обработать заказ {o['number']}", order_sub(o), "order", {"id": o["id"]}) for o in to_process]
                + [("Отгрузка", "tag-accent", f"Собрать и отгрузить {o['number']}", order_sub(o), "shipping", {}) for o in ship_queue]
                + [("Приёмка", "tag-neutral", f"Принять поставку {o['number']}", order_sub(o), "receiving", {}) for o in receive_queue]
            ):
                key = tag + str(params.get("id", txt))
                if key not in seen:
                    seen.add(key)
                    tasks.append((tag, cls, txt, sub, dest, params))
        tasks = tasks[:8]

        count = QLabel(str(len(tasks)))
        count.setStyleSheet(f"font-family:{theme.font_heading()};font-size:16px;color:{theme.ACCENT_RAMP[800]};")
        panel, cl, rows = self._panel("Текущие задачи", count)

        if not tasks:
            empty = QLabel("Активных задач нет.")
            empty.setStyleSheet(f"font-size:13px;color:{theme.NEUTRAL[600]};padding:{theme.SP3}px 0;")
            rows.addWidget(empty)
        for tag, cls, txt, sub, dest, params in tasks:
            rows.addWidget(self._row(self._tag(tag, cls), txt, sub, lambda d=dest, p=params: self.nav.go(d, **p)))
        return panel

    def _events_panel(self, orders):
        ev_all = []
        for o in orders:
            for h in o.get("history", []):
                meta = EVENT_META.get(h["status"])
                if not meta:
                    continue
                ev_all.append((store.parse_ru_datetime(h["dateTime"]), h["dateTime"], o["number"], meta))
        ev_all.sort(key=lambda e: e[0].timestamp() if e[0] else 0, reverse=True)
        events = ev_all[:6]

        link = QLabel(f'<a href="#" style="color:{theme.ACCENT_RAMP[700]};font-size:13px;text-decoration:none;">Все заказы</a>')
        link.setTextFormat(Qt.TextFormat.RichText)
        link.linkActivated.connect(lambda _: self.nav.go("orders"))
        panel, cl, rows = self._panel("Последние действия", link)

        if not events:
            empty = QLabel("Пока нет зафиксированных действий.")
            empty.setStyleSheet(f"font-size:13px;color:{theme.NEUTRAL[600]};padding:{theme.SP3}px 0;")
            rows.addWidget(empty)
        for _, raw, number, meta in events:
            text_fn, tag, cls, dest = meta
            row = self._row(self._tag(tag, cls), text_fn(number), _fmt_short(raw),
                            lambda d=dest: self.nav.go(d), chevron=False)
            rows.addWidget(row)
        return panel
