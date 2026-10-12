"""Fumaça da interface em modo demo (sem rede, sem bandeja real)."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait(qapp, cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def app(qapp):
    from lampdesk.app import LampDeskApp
    a = LampDeskApp(qapp, demo=True)
    yield a
    a.service.shutdown()
    a.popup.hide()
    a.tray.hide()


def test_popup_controls(qapp, app):
    from PySide6.QtCore import QRect

    svc, popup = app.service, app.popup
    ids = svc.ids("*")
    assert len(ids) == 3
    popup.show_at(QRect(600, 580, 20, 20))

    svc.set_power(ids, False)
    assert wait(qapp, lambda: not svc.any_on())
    popup._toggle_power()
    assert wait(qapp, lambda: all(svc.state(i).is_on for i in ids))

    popup._set_mode("brightness")
    popup.slider.valueCommitted.emit(30)
    popup.slider.value = 30
    popup._send_slider()
    assert wait(qapp, lambda: all(svc.state(i).brightness == 30 for i in ids))

    popup._set_mode("hue")
    popup.slider.value = 120
    popup._send_slider()
    assert wait(qapp, lambda: svc.state(ids[0]).color == (0, 255, 0))
    assert popup.big.text() == "120°"

    popup._apply_scene(app.store.config.scenes[0])
    assert wait(qapp, lambda: svc.state(ids[0]).mode == "white")
    assert popup.scene_pill.text() == app.store.config.scenes[0].name


def test_popup_glass_paints_in_every_mode(qapp, app):
    """Vidro líquido nos botões e repintura parcial do painel (aba de cores) sem erros."""
    from PySide6.QtCore import QRect

    popup = app.popup
    popup.show_at(QRect(600, 580, 20, 20))
    for mode in ("brightness", "temperature", "hue"):
        popup._set_mode(mode)
        qapp.processEvents()
        assert not popup.grab().isNull()
    popup.bulb.update()  # repintura só da lâmpada: o painel limpa a área antes de pintar
    qapp.processEvents()
    key = popup.bulb._key
    popup.bulb.set_state(*key[:1], popup.bulb.color, key[2])  # mesmo estado: não repinta nem reanima
    assert popup.bulb._key == key


def test_sleep_timer(qapp, app):
    svc = app.service
    svc.start_timer("*", svc.ids("*"), 30)
    assert 1790 <= svc.timer_remaining("*") <= 1800
    svc.cancel_timer("*")
    assert svc.timer_remaining("*") is None


def test_settings_and_language_switch(qapp, app):
    app.open_settings("routines")
    assert app.settings_window.tabs.currentIndex() == 2
    app.store.config.settings.language = "en"
    app.rebuild_ui()
    # depois de recriar as janelas, mudanças de estado não podem tocar no painel antigo
    svc = app.service
    svc.set_power(svc.ids("*"), True)
    assert wait(qapp, lambda: svc.any_on())
    assert app.tray.contextMenu().actions()


def test_theme_switch(qapp, app):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QLabel
    from lampdesk.ui import theme

    app.open_settings("general")
    win = app.settings_window
    old_popup = app.popup
    win.general.appearance.setCurrentIndex(1)  # Claro
    assert theme.MODE == "light" and not theme.DARK
    assert app.store.config.settings.theme == "light"
    assert app.popup is not old_popup  # painel recriado com o tema novo
    assert win.isVisible()  # configurações continuam abertas
    # a foto usada na transição some ao fim da animação
    assert wait(qapp, lambda: not [w for w in win.findChildren(QLabel) if w.graphicsEffect() and w.isVisible()])

    win.general.reduce.setChecked(True)
    assert not theme.TRANSPARENCY
    app.popup.show_at(QRect(600, 580, 20, 20))
    assert not app.popup.grab().isNull()  # pinta sem erro no tema claro, sem desfoque

    win.general.appearance.setCurrentIndex(0)
    win.general.reduce.setChecked(False)
    assert theme.MODE == "dark" and theme.TRANSPARENCY


def test_glass_veil_adapts_to_backdrop(qapp):
    from PySide6.QtGui import QColor, QImage
    from lampdesk.ui import glass, theme

    def backdrop(color):
        img = QImage(20, 20, QImage.Format.Format_RGB32)
        img.fill(QColor(color))
        return glass.with_luma(img)

    theme.apply("dark")
    assert glass.veil(backdrop("white")).alpha() > glass.veil(backdrop("black")).alpha()
    theme.apply("light")
    assert glass.veil(backdrop("black")).alpha() > glass.veil(backdrop("white")).alpha()
    theme.apply("dark")
    assert glass.grab_backdrop(QImage(1, 1, QImage.Format.Format_RGB32).rect()) is None  # offscreen: sem captura


def test_routine_runs(qapp, app):
    import datetime as dt
    from lampdesk.storage import Routine

    now = dt.datetime.now().astimezone()
    app.service.set_power(app.service.ids("*"), True)
    wait(qapp, lambda: app.service.any_on())
    app.store.config.routines = [Routine("Agora", time=now.strftime("%H:%M"), action="off")]
    app.run_routines()
    assert wait(qapp, lambda: not app.service.any_on())
