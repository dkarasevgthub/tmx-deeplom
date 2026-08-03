"""Пользователь — user detail with info grid, activity log and edit actions."""
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import store, theme
from ..widgets.blueprint import BlueprintFrame
from ..widgets.common import Tag, button, h1, h4
from ..widgets.dialog import confirm_dialog, form_dialog
from ..widgets.flow import FlowRow
from ..widgets.table import TableSection
from ._ui import SplitRow
from .base import Page

ARTICLES = ["100421", "100433", "201187", "201204", "100458", "100477", "100512", "300098"]
_ACTIVITY_BY_ROLE = {
    "manager": [("Создал заказ №{n}", "Заказы"), ("Отклонил заказ №{n}", "Заказы"),
                ("Отменил заказ №{n}", "Заказы"), ("Изменил позиции заказа №{n}", "Заказы"),
                ("Отредактировал товар {a}", "Справочник")],
    "stockman": [("Отгрузил заказ №{n}", "Отгрузка"), ("Собрал коробку по заказу №{n}", "Отгрузка"),
                 ("Принял партию №{n}", "Приёмка"), ("Завершил приёмку №{n}", "Приёмка"),
                 ("Скорректировал остаток {a}", "Остатки"), ("Списал товар {a}", "Справочник")],
    "admin": [("Изменил права роли", "Пользователи"), ("Добавил пользователя", "Пользователи"),
              ("Заблокировал пользователя", "Пользователи"), ("Отредактировал товар {a}", "Справочник"),
              ("Скорректировал остаток {a}", "Остатки")],
}


def _gen_activity(user):
    seed = user["id"] * 7919 + len(user["fullName"])

    def rnd():
        nonlocal seed
        seed = (seed * 1103515245 + 12345) & 0x7fffffff
        return seed / 0x7fffffff

    pool = _ACTIVITY_BY_ROLE.get(user["role"], _ACTIVITY_BY_ROLE["manager"])
    count = 16 + (user["id"] % 14)
    dt = datetime(2026, 7, 24, 9, 30)
    rows = [("Вход в систему", "—", dt)]
    for _ in range(count):
        dt = dt - timedelta(hours=1 + int(rnd() * 9), minutes=int(rnd() * 60))
        action, section = pool[int(rnd() * len(pool))]
        action = action.replace("{n}", str(3000 + int(rnd() * 999))).replace("{a}", ARTICLES[int(rnd() * len(ARTICLES))])
        rows.append((action, section, dt))
        if rnd() < 0.18:
            dt = dt - timedelta(hours=int(rnd() * 6))
            rows.append(("Выход из системы", "—", dt))
    return [(a, s, f"{d.day:02d}.{d.month:02d}.{d.year} {d.hour:02d}:{d.minute:02d}") for a, s, d in rows]


class UserDetailPage(Page):
    def build(self):
        uid = self.params.get("id")
        user = store.user_by_id(uid)

        crumb = QLabel(
            f'<a href="#" style="color:{theme.NEUTRAL[600]};text-decoration:none;">Пользователи</a>'
            + (f' / {user["fullName"]}' if user else "")
        )
        crumb.setObjectName("breadcrumb")
        crumb.setTextFormat(Qt.TextFormat.RichText)
        crumb.linkActivated.connect(lambda _: self.nav.go("users"))
        self.add_block(crumb)

        if not user:
            self._not_found()
            return
        self._render(user)

    def _not_found(self):
        frame = BlueprintFrame(padding=theme.SP8)
        fl = frame.content_layout()
        fl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = QLabel("Пользователь не найден")
        t.setStyleSheet(f"font-family:{theme.font_heading()};font-size:25px;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        back = button("К списку пользователей", "secondary")
        back.clicked.connect(lambda: self.nav.go("users"))
        fl.addWidget(t)
        fl.addWidget(back, 0, Qt.AlignmentFlag.AlignCenter)
        self.add_block(frame)
        self.col.addStretch(1)

    def _render(self, user):
        rl, rc, rb = theme.role_meta(user["role"])
        sl, sc, sb = theme.user_status_meta(user["status"])

        # header: кнопки справа, при нехватке ширины — под именем
        who = QWidget()
        left = QHBoxLayout(who); left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(theme.SP4)
        avatar = QLabel(store.initials(user["fullName"]))
        avatar.setFixedSize(72, 72)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"border:1px solid {theme.DIVIDER};font-family:{theme.font_heading()};"
            f"font-size:28px;color:{theme.ACCENT_RAMP[700]};"
        )
        left.addWidget(avatar)
        namebox = QVBoxLayout(); namebox.setSpacing(6)
        name = h1(user["fullName"])
        # ФИО целиком длиннее любого другого заголовка в приложении: на 44px
        # строка с кнопками не помещается в окно даже стандартной ширины
        name.setStyleSheet("font-size:36px;")
        namebox.addWidget(name)
        tags = QHBoxLayout(); tags.setSpacing(theme.SP2)
        tags.addWidget(Tag(rl, rc, rb)); tags.addWidget(Tag(sl, sc, sb)); tags.addStretch(1)
        namebox.addLayout(tags)
        left.addLayout(namebox)

        edit = button("Редактировать", "secondary")
        edit.clicked.connect(lambda: self._edit(user))
        passwd = button("Сменить пароль", "secondary")
        passwd.clicked.connect(lambda: self._change_password(user))
        block = button("Разблокировать" if user["status"] == "blocked" else "Заблокировать", "secondary")
        block.clicked.connect(lambda: self._toggle_block(user))
        delete = button("Удалить", "ghost")
        delete.clicked.connect(lambda: self._delete(user))
        actions = QWidget()
        arow = QHBoxLayout(actions); arow.setContentsMargins(0, 0, 0, 0)
        arow.setSpacing(theme.SP3)
        for b in (edit, passwd, block, delete):
            arow.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        self.add_block(SplitRow(who, actions))

        # info grid
        info = BlueprintFrame(padding=theme.SP6)
        cells = [
            ("Должность", user["position"]), ("Роль", rl), ("Склад", user["warehouse"]), ("Статус", sl),
            ("Телефон", user["phone"]), ("Email", user["email"]),
            ("Логин", user.get("login", "—")), ("Дата приёма", user["hireDate"]),
            ("Последний вход", user["lastLogin"]),
        ]
        # те же реквизиты, что в карточках заказа и партии: строка с переносом
        grid = FlowRow(h_spacing=theme.SP8, v_spacing=theme.SP4)
        for k, val in cells:
            grid.add(self._info_cell(k, val))
        info.content_layout().addWidget(grid)
        self.add_block(info)

        # activity
        act = BlueprintFrame(padding=theme.SP4)
        act.content_layout().addWidget(h4("История действий"))
        rows = [([("m", dt), action, ("m", section)], None) for action, section, dt in _gen_activity(user)]
        table = TableSection(
            headers=["Дата и время", "Действие", "Раздел"],
            widths=[160, 0, 140], rows=rows, page_size=8, auto_rows=True, framed=False,
        )
        act.content_layout().addWidget(table)
        self.add_block(act)
        self.col.addStretch(1)

    def _info_cell(self, k, v):
        box = QWidget()
        lay = QVBoxLayout(box); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(2)
        kk = QLabel(k); kk.setObjectName("kicker")
        vv = QLabel(str(v)); vv.setStyleSheet(f"font-family:{theme.font_heading()};font-size:18px;")
        # без переноса: в строке с обтеканием ячейка получает ширину по своему
        # содержимому, и «Центральный склад» ломался на две строки
        lay.addWidget(kk); lay.addWidget(vv)
        return box

    # ── actions ──
    def _edit(self, user):
        fields = [
            ("fullName", "ФИО", "text", user["fullName"]),
            ("position", "Должность", "text", user["position"]),
            ("role", "Роль", "select", user["role"], [("manager", "Менеджер"), ("stockman", "Кладовщик"), ("admin", "Администратор")]),
            ("warehouse", "Склад", "search-select", user["warehouse"], [(w, w) for w in store.warehouses()]),
            ("status", "Статус", "select", user["status"], [("active", "Активен"), ("blocked", "Заблокирован")]),
            ("phone", "Телефон", "text", user["phone"]),
            ("email", "Email", "text", user["email"]),
        ]

        def on_save(v):
            if not v["fullName"].strip():
                return "Укажите как минимум ФИО."
            users = store.load_users()
            for u in users:
                if u["id"] == user["id"]:
                    u.update({"fullName": v["fullName"].strip(), "position": v["position"].strip(),
                              "role": v["role"], "warehouse": v["warehouse"], "status": v["status"],
                              "phone": v["phone"].strip(), "email": v["email"].strip()})
                    break
            store.save_users(users)
            return None

        if form_dialog(self, "Редактировать пользователя", fields, on_save, columns=2, width=560):
            self.nav.go("user", id=user["id"])

    def _change_password(self, user):
        def on_save(v):
            if len(v["password"]) < 6:
                return "Пароль должен быть не короче 6 символов."
            if v["password"] != v["repeat"]:
                return "Пароли не совпадают."
            store.set_password(user["id"], v["password"])
            return None

        if form_dialog(self, f'Пароль — {store.short_name(user["fullName"])}',
                       [("password", "Новый пароль", "text", ""),
                        ("repeat", "Повторите пароль", "text", "")],
                       on_save, submit_label="Сохранить"):
            self.nav.go("user", id=user["id"])

    def _toggle_block(self, user):
        users = store.load_users()
        for u in users:
            if u["id"] == user["id"]:
                u["status"] = "blocked" if u["status"] == "active" else "active"
                break
        store.save_users(users)
        self.nav.go("user", id=user["id"])

    def _delete(self, user):
        if confirm_dialog(self, "Удалить пользователя?",
                          f'Пользователь «{user["fullName"]}» будет удалён без возможности восстановления.',
                          confirm_label="Удалить"):
            store.save_users([u for u in store.load_users() if u["id"] != user["id"]])
            self.nav.go("users")
