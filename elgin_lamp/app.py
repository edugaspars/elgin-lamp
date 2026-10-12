"""Ponto de entrada do aplicativo de bandeja."""

import argparse
import datetime as dt
import getpass
import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import APP_ID, APP_NAME, __version__, scheduler
from .i18n import set_language, tr
from .paths import data_dir, log_file
from .service import LampService
from .storage import Lamp, Store, default_scenes

log = logging.getLogger("elgin_lamp")


def setup_logging(verbose: bool) -> None:
    handler = RotatingFileHandler(log_file(), maxBytes=512_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    # o tinytuya registra pacotes com IP/chaves em DEBUG: nunca gravar isso
    logging.getLogger("tinytuya").setLevel(logging.WARNING)


class ElginLampApp:
    def __init__(self, qapp: QApplication, demo: bool = False):
        self.qapp = qapp
        self.demo = demo
        self.settings_window = None

        if demo:
            self.store = Store(data_dir() / "demo.dat")
            self.store.load()
        else:
            self.store = Store()
            self.store.load()
        cfg = self.store.config
        set_language(cfg.settings.language)
        if demo and not cfg.lamps:
            cfg.lamps = [Lamp("Sala", "demo-1", "192.0.2.10", "0" * 16),
                         Lamp("Quarto", "demo-2", "192.0.2.11", "0" * 16),
                         Lamp("Escritório", "demo-3", "192.0.2.12", "0" * 16)]
        if not cfg.scenes:
            cfg.scenes = default_scenes(tr)
            self.store.save()

        self.service = LampService(self.store, demo=demo)
        self.service.versionDetected.connect(self._version_detected)
        self.service.stateChanged.connect(self._state_changed)
        self._fired = {}
        self._build_ui()

        self._routine_timer = QTimer(interval=20_000)
        self._routine_timer.timeout.connect(self.run_routines)
        self._routine_timer.start()

        if self.store.load_error:
            QTimer.singleShot(800, lambda: self.tray.showMessage(APP_NAME, tr("load_error"),
                                                                 QSystemTrayIcon.MessageIcon.Warning))

    # ------------------------------------------------------------ interface ---
    def _build_ui(self):
        from .ui.popup import Popup
        from .ui.tray import Tray

        self.popup = Popup(self.store, self.service)
        self.popup.openSettings.connect(self.open_settings)
        self.tray = Tray(self)
        self.tray.show()
        if not self.store.config.lamps:  # primeiro uso: mostra o painel vazio
            QTimer.singleShot(600, lambda: self.popup.show_at(self.tray.geometry()))

    def _state_changed(self, *_):
        self.tray.update_state()

    def rebuild_ui(self):
        """Recria as janelas (troca de idioma)."""
        set_language(self.store.config.settings.language)
        reopen = self.settings_window is not None and self.settings_window.isVisible()
        if self.settings_window:
            self.settings_window.close()
            self.settings_window.deleteLater()
            self.settings_window = None
        self.popup.hide()
        self.popup.deleteLater()
        self.tray.hide()
        self.tray.deleteLater()
        self._build_ui()
        if reopen:
            self.open_settings("general")

    def open_settings(self, tab: str = "lamps"):
        from .ui.settings import SettingsWindow

        self.popup.hide()
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self.store, self.service)
            self.settings_window.configChanged.connect(self._config_changed)
            self.settings_window.languageChanged.connect(lambda: QTimer.singleShot(0, self.rebuild_ui))
        self.settings_window.show_tab(tab)

    def _config_changed(self):
        self.service.reload()
        self.tray.update_state()
        if self.popup.isVisible():
            self.popup.update_view()

    def _version_detected(self, lamp_id: str, version: str):
        lamp = self.store.config.lamp(lamp_id)
        if lamp and lamp.version == "auto":
            lamp.version = version
            self.store.save()
            self.service.reload()

    # ------------------------------------------------------------ rotinas ---
    def run_routines(self):
        cfg = self.store.config
        now = dt.datetime.now().astimezone()
        for r in scheduler.due(cfg.routines, now, cfg.settings.location, self._fired):
            ids = [l.id for l in cfg.resolve_targets(r.targets)]
            log.info("Rotina '%s' executada (%s)", r.name, r.action)
            if r.action == "on":
                self.service.set_power(ids, True)
            elif r.action == "off":
                self.service.set_power(ids, False)
            elif r.action == "scene" and cfg.scene(r.scene_id):
                self.service.apply_scene(ids, cfg.scene(r.scene_id))

    def quit(self):
        self.service.shutdown()
        self.tray.hide()
        self.qapp.quit()


def _single_instance(name: str):
    """Retorna um QLocalServer se esta for a primeira instância; senão avisa a outra e retorna None."""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return None
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.listen(name)
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="elgin-lamp", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--demo", action="store_true", help="usa lâmpadas simuladas (sem rede)")
    parser.add_argument("--verbose", action="store_true", help="log detalhado")
    args = parser.parse_args(argv)

    if sys.platform == "win32":  # ícone próprio na barra de tarefas / notificações
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.Tray")
        except Exception:
            pass

    qapp = QApplication(sys.argv[:1])
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    setup_logging(args.verbose)

    server = _single_instance(f"{APP_ID}-{getpass.getuser()}{'-demo' if args.demo else ''}")
    if server is None:
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, tr("no_tray"))
        return 1

    from .ui.tray import tray_icon
    qapp.setWindowIcon(tray_icon(True))
    app = ElginLampApp(qapp, demo=args.demo)

    def on_connection():
        conn = server.nextPendingConnection()
        conn.readyRead.connect(lambda: (conn.readAll(), app.popup.show_at(app.tray.geometry())))

    server.newConnection.connect(on_connection)
    log.info("%s %s iniciado%s", APP_NAME, __version__, " (demo)" if args.demo else "")
    return qapp.exec()
