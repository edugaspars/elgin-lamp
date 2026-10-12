"""Ícone da bandeja e seu menu de clique direito."""

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..i18n import tr
from . import icons, theme


@lru_cache(maxsize=2)
def tray_icon(on: bool) -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = size / 24
        if on:
            glass = QPainterPath()
            glass.addEllipse(QPointF(12 * s, 9.2 * s), 6.2 * s, 6.2 * s)
            glass.addRect(QRectF(9.3 * s, 13 * s, 5.4 * s, 3.2 * s))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 196, 107))
            p.drawPath(glass.simplified())
            icons.paint(p, "bulb", QRectF(0, 0, size, size), QColor(255, 214, 150), 1.9)
        else:
            icons.paint(p, "bulb", QRectF(0, 0, size, size), QColor(170, 170, 170), 1.9)
        p.end()
        icon.addPixmap(pm)
    return icon


def style_menu(menu: QMenu) -> None:
    """Menu arredondado no tema atual (o fundo translúcido deixa os cantos redondos)."""
    menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint |
                        Qt.WindowType.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    menu.setStyleSheet(theme.dialog_qss())


class Tray(QSystemTrayIcon):
    def __init__(self, app):
        super().__init__(tray_icon(False))
        self.app = app
        self.setToolTip(tr("app.tooltip"))
        self.menu = QMenu()
        style_menu(self.menu)
        self.menu.aboutToShow.connect(self.rebuild)
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)
        self.rebuild()

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.app.popup.toggle_at(self.geometry())
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.app.service.toggle(self.app.service.ids("*"))

    def restyle(self):
        style_menu(self.menu)

    def update_state(self):
        svc = self.app.service
        on = svc.any_on()
        self.setIcon(tray_icon(on))
        lamps = self.app.store.config.lamps
        n_on = sum(1 for l in lamps if svc.state(l.id).is_on and svc.state(l.id).online)
        self.setToolTip(f"{tr('app.tooltip')} — {n_on}/{len(lamps)}" if lamps else tr("app.tooltip"))

    def rebuild(self):
        m = self.menu
        m.clear()
        svc = self.app.service
        cfg = self.app.store.config
        m.addAction(tr("tray.open")).triggered.connect(lambda: self.app.popup.show_at(self.geometry()))
        if cfg.lamps:
            m.addSeparator()
            for lamp in cfg.lamps:
                st = svc.state(lamp.id)
                a = QAction(lamp.name if st.online else f"{lamp.name}  ⚠", m, checkable=True,
                            checked=st.is_on and st.online)
                a.triggered.connect(lambda checked, lid=lamp.id: svc.set_power([lid], checked))
                m.addAction(a)
            m.addSeparator()
            m.addAction(tr("tray.all_on")).triggered.connect(lambda: svc.set_power(svc.ids("*"), True))
            m.addAction(tr("tray.all_off")).triggered.connect(lambda: svc.set_power(svc.ids("*"), False))
            if cfg.scenes:
                sub = m.addMenu(tr("scenes"))
                style_menu(sub)
                for sc in cfg.scenes:
                    sub.addAction(sc.name).triggered.connect(
                        lambda _=False, s=sc: svc.apply_scene(svc.ids("*"), s))
        m.addSeparator()
        m.addAction(tr("routines")).triggered.connect(lambda: self.app.open_settings("routines"))
        m.addAction(tr("settings")).triggered.connect(lambda: self.app.open_settings("lamps"))
        m.addSeparator()
        m.addAction(tr("tray.quit")).triggered.connect(self.app.quit)
