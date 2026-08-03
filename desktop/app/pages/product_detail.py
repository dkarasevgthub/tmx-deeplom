"""Товар — product card: details, stock, movement history, operations."""
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme
from ..widgets.blueprint import BlueprintFrame
from ..widgets.common import button, h1, h4, icon_button
from ..widgets.dialog import form_dialog
from ..widgets.table import TableSection
from ._ui import stat_grid
from .base import Page

# Product master data (article, code1c, name, unit, unitWeight, qty, free, reserved)
PRODUCTS = {p[0]: p for p in [
    ("100421", "ТМЦ-00421", "Болт М8×40 ГОСТ 7798", "шт.", 0.02, 2400, 2100, 300),
    ("100433", "ТМЦ-00433", "Гайка М8 ГОСТ 5915", "шт.", 0.01, 410, 410, 0),
    ("201187", "ТМЦ-01187", "Подшипник 6205-2RS", "шт.", 0.08, 54, 34, 20),
    ("201204", "ТМЦ-01204", "Ремень приводной А-1250", "шт.", 0.45, 96, 84, 12),
    ("300087", "ТМЦ-00087", "Редуктор РЦД-350 в сборе", "шт.", 42.0, 3, 0, 3),
    ("300091", "ТМЦ-00091", "Насос центробежный НЦ-40", "шт.", 18.5, 11, 7, 4),
    ("100458", "ТМЦ-00458", "Лист стальной 2×1250×2500", "лист", 72.5, 128, 128, 0),
    ("100477", "ТМЦ-00477", "Уголок стальной 50×50×5", "шт.", 4.5, 210, 180, 30),
    ("100512", "ТМЦ-00512", "Труба стальная 32×2", "м", 1.6, 640, 640, 0),
    ("300098", "ТМЦ-00098", "Электродвигатель АИР90", "шт.", 24.0, 6, 4, 2),
    ("201340", "ТМЦ-01340", "Ремень клиновой Б-1400", "шт.", 0.35, 54, 54, 0),
    ("100655", "ТМЦ-00655", "Шайба М8 ГОСТ 6402", "шт.", 0.005, 5200, 5200, 0),
    ("100701", "ТМЦ-00701", "Винт М6×20 ГОСТ 17475", "шт.", 0.008, 1800, 1600, 200),
    ("201412", "ТМЦ-01412", "Подшипник 6208-2RS", "шт.", 0.15, 40, 28, 12),
    ("300133", "ТМЦ-00133", "Насос шестерённый НШ-10", "шт.", 6.2, 9, 6, 3),
    ("100812", "ТМЦ-00812", "Швеллер 10П ГОСТ 8240", "м", 8.5, 96, 96, 0),
    ("300159", "ТМЦ-00159", "Редуктор червячный РЧУ-125", "шт.", 18.7, 4, 2, 2),
    ("100933", "ТМЦ-00933", "Гайка М10 ГОСТ 5915", "шт.", 0.015, 3100, 3100, 0),
    ("201055", "ТМЦ-01055", "Муфта соединительная МУВП-40", "шт.", 2.1, 14, 10, 4),
]}

OPS = [("Приемка", 1, "Приемка №"), ("Отгрузка", -1, "Отгрузка №"),
       ("Списание", -1, "Списание №"), ("Корректировка", 1, "Инвентаризация №")]
TYPE_META = {"Приемка": (1, "signed"), "Отгрузка": (-1, "signed"),
             "Списание": (-1, "signed"), "Корректировка": (0, "balance")}

# session state
_ADJ = {}       # article -> net delta applied by manual operations
_MANUAL = {}    # article -> list of manual history rows (dicts)
_OVERRIDE = {}  # article -> {name, code1c, unit, unitWeight}


def _seed_hash(s):
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) % 100000
    return h


def _build_history(base):
    article, _c1c, _name, unit, _uw, qty, _free, _res = base
    seed = _seed_hash(article)
    balance = qty
    rows = []
    today = datetime(2026, 7, 22)
    for i in range(24):
        s = (seed + i * 37) % 1000
        op_type, sign, doc_prefix = OPS[s % len(OPS)]
        amount = max(1, round((s % 40) + (20 if i == 5 else 5)))
        delta = sign * amount
        balance_after = balance
        balance = balance - delta
        d = today - timedelta(days=i * 4 + (s % 3))
        hh = 8 + (s % 9)
        mm = (s * 7) % 60
        rows.append({
            "date": f"{d.day:02d}.{d.month:02d}.{d.year} {hh:02d}:{mm:02d}",
            "type": op_type,
            "doc": f"{doc_prefix}{1100 + ((seed + i * 13) % 200)}",
            "qtyText": ("+" if delta >= 0 else "") + f"{delta} {unit}",
            "balance": f"{balance_after} {unit}",
        })
    return rows


class ProductDetailPage(Page):
    def build(self):
        self._article = self.params.get("article", "")
        self._from = self.params.get("from_", "catalog")
        self._op_filter = "all"

        base = PRODUCTS.get(self._article)
        back = "Остатки" if self._from == "stock" else "Справочник"
        crumb = QLabel(
            f'<a href="#home" style="color:{theme.NEUTRAL[600]};text-decoration:none;">ProЗапас</a> / '
            f'<a href="#back" style="color:{theme.NEUTRAL[600]};text-decoration:none;">{back}</a> / '
            + (base[0] if base else "—"))
        crumb.setObjectName("breadcrumb"); crumb.setTextFormat(Qt.TextFormat.RichText)
        crumb.linkActivated.connect(
            lambda href: self.nav.go(self._from) if href == "#back" else self.nav.go("home"))
        self.add_block(crumb)

        if not base:
            self._not_found()
            return
        self._render(base)

    def _not_found(self):
        frame = BlueprintFrame(padding=theme.SP8)
        fl = frame.content_layout(); fl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = QLabel("Товар не найден"); t.setStyleSheet(f"font-family:{theme.font_heading()};font-size:25px;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d = QLabel("Проверьте ссылку или вернитесь в справочник.")
        d.setStyleSheet(f"font-size:13px;color:{theme.NEUTRAL[600]};"); d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fl.addWidget(t); fl.addWidget(d)
        self.add_block(frame); self.col.addStretch(1)

    def _product(self, base):
        ov = _OVERRIDE.get(self._article, {})
        adj = _ADJ.get(self._article, 0)
        return {
            "article": base[0], "code1c": ov.get("code1c", base[1]), "name": ov.get("name", base[2]),
            "unit": ov.get("unit", base[3]), "unitWeight": ov.get("unitWeight", base[4]),
            "qty": base[5] + adj, "free": base[6] + adj, "reserved": base[7],
        }

    def _render(self, base):
        p = self._product(base)

        head = QHBoxLayout()
        left = QVBoxLayout(); left.setSpacing(4)
        left.addWidget(h1(p["name"]))
        sub = QLabel("Карточка товара"); sub.setObjectName("muted")
        left.addWidget(sub)
        head.addLayout(left); head.addStretch(1)
        edit = button("Редактировать товар", "secondary"); edit.clicked.connect(lambda: self._edit_product(base))
        op = button("Провести операцию", "primary"); op.clicked.connect(lambda: self._operation(base))
        head.addWidget(edit, 0, Qt.AlignmentFlag.AlignTop)
        head.addWidget(op, 0, Qt.AlignmentFlag.AlignTop)
        self.add_block(head)

        # details panel
        info = BlueprintFrame(padding=theme.SP6)
        irow = QHBoxLayout(); irow.setSpacing(theme.SP8)
        for k, v in [("Артикул", p["article"]), ("Артикул 1С", p["code1c"]),
                     ("Единица измерения", p["unit"]), ("Вес единицы", f'{p["unitWeight"]} кг')]:
            irow.addWidget(self._cell(k, v))
        irow.addStretch(1)
        info.content_layout().addLayout(irow)
        self.add_block(info)

        # stock stats
        self.add_block(h4("Остатки на складе"))
        self.add_block(stat_grid([
            ("В наличии", str(p["qty"]), p["unit"]),
            ("Свободно", str(p["free"]), "доступно к отгрузке"),
            ("Резерв", str(p["reserved"]), "под заказы клиентов"),
        ], columns=3))

        # history
        hist_frame = BlueprintFrame(padding=theme.SP4)
        hl = hist_frame.content_layout()
        hl.addWidget(h4("История движения"))
        filters = QHBoxLayout(); filters.setSpacing(theme.SP4)
        self._op_input = QComboBox()
        for v in ["all", "Приемка", "Отгрузка", "Списание", "Корректировка"]:
            self._op_input.addItem("Все операции" if v == "all" else v, v)
        self._op_input.currentIndexChanged.connect(self._on_op_filter)
        fbox = QWidget(); fb = QVBoxLayout(fbox); fb.setContentsMargins(0, 0, 0, 0); fb.setSpacing(5)
        flabel = QLabel("Операция"); flabel.setStyleSheet(f"font-size:12px;color:{theme.NEUTRAL[700]};")
        fb.addWidget(flabel); fb.addWidget(self._op_input)
        fbox.setFixedWidth(200)
        filters.addWidget(fbox)
        reset = icon_button("reset", "Сбросить фильтры"); reset.clicked.connect(self._reset)
        filters.addWidget(reset, 0, Qt.AlignmentFlag.AlignBottom)
        filters.addStretch(1)
        hl.addLayout(filters)

        self._table = TableSection(
            headers=["Дата", "Операция", "Комментарий", "Количество", "Остаток после"],
            widths=[160, 130, 0, 120, 130], rows=self._history_rows(base), page_size=10,
            auto_rows=True, framed=False,
        )
        hl.addWidget(self._table)
        self.add_block(hist_frame)
        self.col.addStretch(1)

    def _cell(self, k, v):
        box = QWidget(); lay = QVBoxLayout(box); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(2)
        kk = QLabel(k); kk.setObjectName("kicker")
        vv = QLabel(str(v)); vv.setStyleSheet(f"font-family:{theme.font_heading()};font-size:18px;")
        lay.addWidget(kk); lay.addWidget(vv)
        return box

    def _history_rows(self, base):
        rows = _MANUAL.get(self._article, []) + _build_history(base)
        out = []
        for h in rows:
            if self._op_filter != "all" and h["type"] != self._op_filter:
                continue
            out.append(([("m", h["date"]), h["type"], ("m", h["doc"]), h["qtyText"], h["balance"]], None))
        return out

    def _on_op_filter(self, _):
        self._op_filter = self._op_input.currentData()
        self._table.set_rows(self._history_rows(PRODUCTS[self._article]))

    def _reset(self):
        self._op_filter = "all"
        self._op_input.blockSignals(True); self._op_input.setCurrentIndex(0); self._op_input.blockSignals(False)
        self._table.set_rows(self._history_rows(PRODUCTS[self._article]))

    # ── operations ──
    def _operation(self, base):
        fields = [
            ("type", "Тип операции", "select", "Списание",
             [("Приемка", "Приемка"), ("Отгрузка", "Отгрузка"), ("Списание", "Списание"),
              ("Корректировка", "Корректировка (пересчёт остатка)")]),
            ("qty", "Количество", "text", ""),
            ("comment", "Комментарий", "text", ""),
        ]
        p = self._product(base)

        def on_save(v):
            try:
                qty = float(v["qty"])
                if qty < 0:
                    raise ValueError
            except ValueError:
                return "Введите корректное количество."
            sign, mode = TYPE_META[v["type"]]
            delta = (qty - p["qty"]) if mode == "balance" else sign * qty
            if delta < 0 and -delta > p["qty"]:
                return "Нельзя списать/отгрузить больше, чем есть в наличии."
            _ADJ[self._article] = _ADJ.get(self._article, 0) + delta
            new_balance = p["qty"] + delta
            now = datetime.now()
            unit = p["unit"]
            qi = 0 if unit == "шт." else 2
            entry = {
                "date": f"{now.day:02d}.{now.month:02d}.{now.year} {now.hour:02d}:{now.minute:02d}",
                "type": v["type"], "doc": v["comment"].strip() or f'{v["type"]} (ручная)',
                "qtyText": ("+" if delta >= 0 else "") + f"{delta:.{qi}f} {unit}",
                "balance": f"{new_balance:.{qi}f} {unit}",
            }
            _MANUAL.setdefault(self._article, []).insert(0, entry)
            return None

        if form_dialog(self, "Провести операцию", fields, on_save, submit_label="Провести"):
            self.nav.go("product", article=self._article, from_=self._from)

    def _edit_product(self, base):
        p = self._product(base)
        fields = [
            ("name", "Наименование", "text", p["name"]),
            ("article", "Артикул", "text", p["article"]),
            ("code1c", "Артикул 1С", "text", p["code1c"]),
            ("unit", "Единица измерения", "text", p["unit"]),
            ("unitWeight", "Вес единицы, кг", "text", str(p["unitWeight"])),
        ]

        def on_save(v):
            if not v["name"].strip() or not v["article"].strip():
                return "Заполните наименование и артикул."
            try:
                w = float(v["unitWeight"])
                if w < 0:
                    raise ValueError
            except ValueError:
                return "Введите корректный вес единицы."
            _OVERRIDE[self._article] = {"name": v["name"].strip(), "code1c": v["code1c"].strip(),
                                        "unit": v["unit"].strip(), "unitWeight": w}
            return None

        if form_dialog(self, "Редактировать товар", fields, on_save):
            self.nav.go("product", article=self._article, from_=self._from)
