"""Остатки — stock balances."""
from ..widgets.common import breadcrumb
from ..widgets.table import TableSection
from ._ui import header_row, search_field, stat_grid
from .base import Page


class StockPage(Page):
    def build(self):
        from .. import store
        self._store = store
        self.add_block(breadcrumb("ProЗапас / Остатки"))
        self.add_block(header_row("Остатки", "Складские остатки по номенклатуре"))
        self.add_block(stat_grid(store.stock_stats(), columns=4))

        self._search = ""
        self.add_block(search_field("Поиск по артикулу или наименованию", self._on_search))

        self._table = TableSection(
            headers=["Наименование", "Артикул", "Артикул 1С", "Ед. изм.", "В наличии", "Свободно", "Резерв"],
            widths=[0, 110, 120, 90, 110, 110, 100],
            rows=self._rows(),
            on_row_click=lambda art: self.nav.go("product", article=art, from_="stock"),
            page_size=14, auto_rows=True,
        )
        self.add_block(self._table)
        self.col.addStretch(1)

    def _rows(self):
        q = self._search.strip().lower()
        rows = []
        for r in self._store.stock_rows():
            if r["qty"] <= 0:
                continue
            if q and not any(q in str(r[f]).lower() for f in ("name", "article", "code1c")):
                continue
            rows.append((
                [r["name"], ("m", r["article"]), ("m", r["code1c"]), r["unit"],
                 str(r["qty"]), str(r["free"]), ("m", str(r["reserved"]))],
                r["article"],
            ))
        return rows

    def _on_search(self, text):
        self._search = text
        self._table.set_rows(self._rows())
