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


def test_popup_repaints_when_only_the_colour_changes(qapp, app):
    """Trocar só a cor (lâmpada já acesa, mesmo brilho) precisa repintar o painel inteiro: o brilho do
    vidro muda de cor, e antes só os filhos (lâmpada, número) eram repintados, deixando retângulos."""
    from PySide6.QtCore import QRect

    svc, popup = app.service, app.popup
    ids = svc.ids("*")
    popup.show_at(QRect(600, 580, 20, 20))
    svc.set_power(ids, True)
    svc.set_color(ids, (255, 0, 0))
    assert wait(qapp, lambda: svc.state(ids[0]).color == (255, 0, 0))
    wait(qapp, lambda: False, 0.6)  # deixa as animações terminarem
    popup._set_mode("hue")

    calls = []
    popup.update = lambda *a: calls.append(a)  # offscreen não gera eventos de pintura: observa o pedido
    try:
        svc.set_color(ids, (0, 0, 255))
        assert wait(qapp, lambda: svc.state(ids[0]).color == (0, 0, 255))
        wait(qapp, lambda: False, 0.3)
    finally:
        del popup.update
    assert popup._glow.blue() == 255
    assert calls  # o painel inteiro foi marcado para repintura


def test_tile_value_fits_inside_the_card(qapp):
    """"Desligado" no card Timer não pode encostar na borda direita (margem de 13 px dos dois lados)."""
    from PySide6.QtGui import QFont, QFontMetrics
    from lampdesk.ui.widgets import fit_font

    avail = 88 - 26  # largura típica do card no painel
    font = fit_font("Desligado", avail, QFont.Weight.DemiBold)
    assert QFontMetrics(font).horizontalAdvance("Desligado") <= avail
    assert fit_font("100%", avail, QFont.Weight.DemiBold).pixelSize() == 14  # texto curto mantém o tamanho


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
