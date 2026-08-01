"""RootWindow — switches between the login screen and the main application."""
from PyQt6.QtWidgets import QMainWindow, QStackedWidget

from . import store
from .pages.login import LoginPage
from .shell import MainView


class RootWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ProЗапас — учёт и логистика")
        self.resize(1280, 820)
        # 1200 — измеренная ширина, при которой самая широкая страница
        # (главная: три карточки и две панели) помещается без прокрутки
        self.setMinimumSize(1220, 700)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._login = LoginPage()
        self._login.logged_in.connect(self._enter_app)
        self._stack.addWidget(self._login)

        self._main = None
        auth = store.load_auth()
        if auth.get("id") and auth.get("remember") and store.current_user():
            self._enter_app()
        else:
            self._show_login()

    def _show_login(self):
        self._stack.setCurrentWidget(self._login)

    def _enter_app(self):
        if self._main is not None:
            self._stack.removeWidget(self._main)
            self._main.deleteLater()
        self._main = MainView()
        self._main.logout.connect(self._do_logout)
        self._stack.addWidget(self._main)
        self._stack.setCurrentWidget(self._main)

    def _do_logout(self):
        store.save_auth(None)
        self._login.reset()
        self._show_login()
