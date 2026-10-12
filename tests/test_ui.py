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
    from elgin_lamp.app import ElginLampApp
    a = ElginLampApp(qapp, demo=True)
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


def test_routine_runs(qapp, app):
    import datetime as dt
    from elgin_lamp.storage import Routine

    now = dt.datetime.now().astimezone()
    app.service.set_power(app.service.ids("*"), True)
    wait(qapp, lambda: app.service.any_on())
    app.store.config.routines = [Routine("Agora", time=now.strftime("%H:%M"), action="off")]
    app.run_routines()
    assert wait(qapp, lambda: not app.service.any_on())
