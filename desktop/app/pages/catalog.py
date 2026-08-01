"""Справочник — item catalogue."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout

from .. import theme, store
from .base import Page
from ._ui import header_row, labeled_field, search_field
from ..widgets.common import breadcrumb, button
from ..widgets.table import TableSection
from ..widgets.dialog import form_dialog


class CatalogPage(Page):
    def build(self):
        self.add_block(breadcrumb("ProЗапас / Справочник"))

        add = button("+ Добавить позицию", "primary")
        add.clicked.connect(self._open_add)
        self.add_block(header_row(
            "Справочник",
            "Номенклатура завода · материалы, комплектующие, готовая продукция",
            add))

        self._search = ""
        row = QHBoxLayout()
        row.setSpacing(theme.SP4)
        field = search_field("Код, артикул или наименование", self._on_search)
        row.addWidget(labeled_field("Поиск", field, 360), 1)
        row.addStretch(1)
        self.add_block(row)

        self._table = TableSection(
            headers=["Наименование", "Артикул", "Артикул 1С", "Ед. изм.", "Вес единицы"],
            widths=[0, 150, 160, 120, 150],
            rows=self._rows(),
            on_row_click=lambda art: self.nav.go("product", article=art, from_="catalog"),
            page_size=14, auto_rows=True,
        )
        self.add_block(self._table)
        self.col.addStretch(1)

    def _all_items(self):
        return store.catalog_dicts()

    def _rows(self):
        q = self._search.strip().lower()
        rows = []
        for c in self._all_items():
            if q and q not in c["name"].lower() and q not in c["article"].lower() and q not in c.get("code1c", "").lower():
                continue
            rows.append((
                [c["name"], ("m", c["article"]), ("m", c.get("code1c", "")), c["unit"], f'{c["unitWeight"]} кг'],
                c["article"],
            ))
        return rows

    def _on_search(self, text):
        self._search = text
        self._table.set_rows(self._rows())

    def _open_add(self):
        fields = [
            ("name", "Наименование", "text", ""),
            ("article", "Артикул", "text", ""),
            ("code1c", "Артикул 1С", "text", ""),
            ("unit", "Единица измерения", "text", "шт."),
            ("unitWeight", "Вес единицы, кг", "text", ""),
        ]

        def on_save(values):
            if not values["name"].strip() or not values["article"].strip():
                return "Заполните наименование и артикул."
            try:
                weight = float(values["unitWeight"])
                if weight < 0:
                    raise ValueError
            except ValueError:
                return "Введите корректный вес единицы."
            store.add_catalog_item({
                "name": values["name"].strip(), "article": values["article"].strip(),
                "code1c": values["code1c"].strip(), "unit": values["unit"].strip() or "шт.",
                "unitWeight": weight,
            })
            self._table.set_rows(self._rows())
            return None

        form_dialog(self, "Добавить позицию", fields, on_save, submit_label="Добавить")
