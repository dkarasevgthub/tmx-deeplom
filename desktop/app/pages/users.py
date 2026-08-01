"""Пользователи — user list, add dialog, and the roles/permissions matrix."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLineEdit, QComboBox, QLabel, QWidget, QCheckBox, QGridLayout
)

from .. import theme, store
from .base import Page
from ._ui import header_row, labeled_field, filter_action
from ..widgets.common import breadcrumb, button, icon_button
from ..widgets.blueprint import BlueprintFrame
from ..widgets.combo import SearchableComboBox
from ..widgets.flow import FlowRow
from ..widgets.table import TableSection, transparent_cell
from ..widgets.dialog import form_dialog

ROLE_OPTIONS = [("all", "Все роли"), ("manager", "Менеджер"), ("stockman", "Кладовщик"), ("admin", "Администратор")]
STATUS_OPTIONS = [("all", "Все статусы"), ("active", "Активен"), ("blocked", "Заблокирован")]


def _avatar(text, size=32, font=13):
    a = QLabel(text)
    a.setFixedSize(size, size)
    a.setAlignment(Qt.AlignmentFlag.AlignCenter)
    # background must stay transparent, otherwise it blanks out the row hover
    a.setStyleSheet(
        f"border:1px solid {theme.DIVIDER};background:transparent;"
        f"font-family:{theme.font_heading()};"
        f"font-size:{font}px;color:{theme.ACCENT_RAMP[700]};"
    )
    return a


def _employee_cell(full_name, email):
    w = transparent_cell()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(4, 4, 4, 4)
    lay.setSpacing(theme.SP3)
    lay.addWidget(_avatar(store.initials(full_name)))
    box = QVBoxLayout()
    box.setSpacing(0)
    n = QLabel(full_name)
    n.setStyleSheet("font-size:14px;background:transparent;")
    e = QLabel(email)
    e.setStyleSheet(f"font-size:12px;color:{theme.NEUTRAL[600]};background:transparent;")
    box.addWidget(n)
    box.addWidget(e)
    lay.addLayout(box)
    lay.addStretch(1)
    return w


class UsersPage(Page):
    def build(self):
        self._tab = "users"
        self._search = ""
        self._role = "all"
        self._status = "all"
        self._warehouse = "all"

        self.add_block(breadcrumb("ProЗапас / Пользователи"))
        self._add_btn = button("+ Добавить пользователя", "primary")
        self._add_btn.clicked.connect(self._open_add)
        self.add_block(header_row("Пользователи", "Сотрудники, их роли и права доступа", self._add_btn))

        tabs = QHBoxLayout()
        tabs.setSpacing(theme.SP2)
        self._tab_users = button("Пользователи", "primary")
        self._tab_roles = button("Роли и права", "secondary")
        self._tab_users.clicked.connect(lambda: self._set_tab("users"))
        self._tab_roles.clicked.connect(lambda: self._set_tab("roles"))
        tabs.addWidget(self._tab_users)
        tabs.addWidget(self._tab_roles)
        tabs.addStretch(1)
        self.add_block(tabs)

        self._body = QVBoxLayout()
        self._body.setSpacing(theme.SP6)
        self.add_block(self._body)
        self.col.addStretch(1)
        self._render_body()

    # ── tabs ──
    def _set_tab(self, tab):
        if tab == self._tab:
            return
        self._tab = tab
        self._tab_users.setProperty("variant", "primary" if tab == "users" else "secondary")
        self._tab_roles.setProperty("variant", "primary" if tab == "roles" else "secondary")
        for b in (self._tab_users, self._tab_roles):
            b.style().unpolish(b); b.style().polish(b)
        self._add_btn.setVisible(tab == "users")
        self._render_body()

    def _clear_body(self):
        while self._body.count():
            item = self._body.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _clear_layout(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _render_body(self):
        self._clear_body()
        if self._tab == "users":
            self._render_users()
        else:
            self._render_roles()

    # ── users tab ──
    def _render_users(self):
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("ФИО, телефон или email")
        self._search_input.textChanged.connect(self._on_search)
        self._role_input = self._combo(ROLE_OPTIONS)
        self._status_input = self._combo(STATUS_OPTIONS)
        self._warehouse_input = self._combo(
            [("all", "Все склады")] + [(w, w) for w in store.warehouses()],
            searchable="Поиск склада")

        filters = FlowRow(h_spacing=theme.SP4, v_spacing=theme.SP3)
        filters.add(labeled_field("Поиск", self._search_input, 200))
        filters.add(labeled_field("Роль", self._role_input, 150))
        filters.add(labeled_field("Статус", self._status_input, 150))
        filters.add(labeled_field("Склад", self._warehouse_input, 160))
        reset = icon_button("reset", "Сбросить фильтры")
        reset.clicked.connect(self._reset)
        filters.add(filter_action(reset))
        self._body.addWidget(filters)

        self._table = TableSection(
            headers=["Сотрудник", "Роль", "Должность", "Склад", "Телефон", "Статус", "Последний вход"],
            widths=[260, 120, 0, 150, 150, 116, 150],
            rows=self._user_rows(), on_row_click=lambda uid: self.nav.go("user", id=uid),
            page_size=12, auto_rows=True,
        )
        self._table._table.verticalHeader().setDefaultSectionSize(46)
        self._body.addWidget(self._table)

    def _combo(self, options, searchable=None):
        c = SearchableComboBox(searchable) if searchable else QComboBox()
        for v, t in options:
            c.addItem(t, v)
        c.currentIndexChanged.connect(self._on_filter)
        return c

    def _user_rows(self):
        q = self._search.strip().lower()
        rows = []
        for u in store.load_users():
            if q and not (q in u["fullName"].lower() or q in u["email"].lower() or q in u["phone"].lower()):
                continue
            if self._role != "all" and u["role"] != self._role:
                continue
            if self._status != "all" and u["status"] != self._status:
                continue
            if self._warehouse != "all" and u["warehouse"] != self._warehouse:
                continue
            rl, rc, rb = theme.role_meta(u["role"])
            sl, sc, sb = theme.user_status_meta(u["status"])
            fn, em = u["fullName"], u["email"]
            rows.append((
                [("w", lambda fn=fn, em=em: _employee_cell(fn, em)),
                 ("tag", rl, rc, rb),
                 ("m", u["position"]),
                 ("m", u["warehouse"]),
                 ("m", u["phone"]),
                 ("tag", sl, sc, sb),
                 ("m", u["lastLogin"])],
                u["id"],
            ))
        return rows

    def _on_search(self, text):
        self._search = text
        self._table.set_rows(self._user_rows())

    def _on_filter(self, _):
        self._role = self._role_input.currentData()
        self._status = self._status_input.currentData()
        self._warehouse = self._warehouse_input.currentData()
        self._table.set_rows(self._user_rows())

    def _reset(self):
        self._search = ""; self._role = "all"; self._status = "all"; self._warehouse = "all"
        for c in (self._role_input, self._status_input, self._warehouse_input):
            c.blockSignals(True); c.setCurrentIndex(0); c.blockSignals(False)
        self._search_input.blockSignals(True); self._search_input.clear(); self._search_input.blockSignals(False)
        self._table.set_rows(self._user_rows())

    def _open_add(self):
        fields = [
            ("fullName", "ФИО", "text", ""),
            ("position", "Должность", "text", ""),
            ("role", "Роль", "select", "manager", [("manager", "Менеджер"), ("stockman", "Кладовщик"), ("admin", "Администратор")]),
            ("warehouse", "Склад", "search-select", "Склад №1", [(w, w) for w in store.warehouses()]),
            ("status", "Статус", "select", "active", [("active", "Активен"), ("blocked", "Заблокирован")]),
            ("phone", "Телефон", "text", ""),
            ("email", "Email", "text", ""),
            ("login", "Логин", "text", ""),
            ("password", "Пароль", "text", ""),
        ]

        def on_save(v):
            if not v["fullName"].strip():
                return "Укажите как минимум ФИО."
            login = v["login"].strip().lower() or v["email"].split("@")[0].strip().lower()
            if not login:
                return "Укажите логин или почту — по ним сотрудник входит в систему."
            if store.user_by_login(login):
                return f"Логин «{login}» уже занят."
            password = v["password"]
            if len(password) < 6:
                return "Пароль должен быть не короче 6 символов."
            users = store.load_users()
            next_id = max((u["id"] for u in users), default=0) + 1
            from datetime import datetime
            today = datetime.now().strftime("%d.%m.%Y")
            users.append({
                "id": next_id, "fullName": v["fullName"].strip(), "role": v["role"],
                "warehouse": v["warehouse"], "position": v["position"].strip(), "status": v["status"],
                "phone": v["phone"].strip(), "email": v["email"].strip(),
                "login": login, "passwordHash": store.hash_password(password),
                "hireDate": today, "lastLogin": "—",
            })
            store.save_users(users)
            self._table.set_rows(self._user_rows())
            return None

        form_dialog(self, "Новый пользователь", fields, on_save, submit_label="Добавить", columns=2, width=560)

    # ── roles tab ──
    def _render_roles(self):
        note = QLabel("Отметьте, что каждая роль может видеть и редактировать по разделам. Изменения сохраняются автоматически.")
        note.setStyleSheet(f"font-size:13px;color:{theme.NEUTRAL[600]};")
        note.setWordWrap(True)
        self._body.addWidget(note)

        frame = BlueprintFrame(padding=theme.SP4)
        fl = frame.content_layout()
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SP6)
        grid.setVerticalSpacing(theme.SP3)

        role_titles = [("manager", "Менеджер"), ("stockman", "Кладовщик"), ("admin", "Администратор")]
        headers = ["Раздел"] + [t for _, t in role_titles]
        for c, htext in enumerate(headers):
            h = QLabel(htext)
            h.setStyleSheet(f"font-size:11px;color:{theme.NEUTRAL[600]};text-transform:uppercase;font-weight:600;")
            grid.addWidget(h, 0, c)

        perms = store.load_perms()
        for r, (sid, slabel) in enumerate(store.sections(), start=1):
            sl = QLabel(slabel)
            sl.setStyleSheet("font-weight:600;")
            grid.addWidget(sl, r, 0)
            for c, (role, _t) in enumerate(role_titles, start=1):
                grid.addWidget(self._perm_cell(perms, role, sid), r, c)
        fl.addLayout(grid)
        self._body.addWidget(frame)

    def _perm_cell(self, perms, role, sid):
        cell = QWidget()
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP4)
        view = QCheckBox("Просмотр")
        edit = QCheckBox("Ред.")
        view.setChecked(perms[role][sid]["view"])
        edit.setChecked(perms[role][sid]["edit"])

        def toggle(_=None):
            p = store.load_perms()
            p[role][sid]["view"] = view.isChecked()
            p[role][sid]["edit"] = edit.isChecked()
            if edit.isChecked() and not view.isChecked():
                view.setChecked(True); p[role][sid]["view"] = True
            if not view.isChecked() and edit.isChecked():
                edit.setChecked(False); p[role][sid]["edit"] = False
            store.save_perms(p)

        view.toggled.connect(toggle)
        edit.toggled.connect(toggle)
        lay.addWidget(view)
        lay.addWidget(edit)
        lay.addStretch(1)
        return cell
