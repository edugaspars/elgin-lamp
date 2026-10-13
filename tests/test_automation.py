"""Motor das automações com lâmpadas simuladas (modo demo, sem rede nem Windows)."""

import datetime as dt
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
def env(qapp, monkeypatch):
    from lampdesk import automation
    from lampdesk.service import LampService
    from lampdesk.storage import Lamp, Store

    monkeypatch.setattr(automation, "BLINK_MS", 20)
    monkeypatch.setattr(automation, "FULLSCREEN_DEBOUNCE_S", 0)
    store = Store()
    store.config.lamps = [Lamp("Escritório", "demo-1", "192.0.2.10", "0" * 16, id="a"),
                          Lamp("Sala", "demo-2", "192.0.2.11", "0" * 16, id="b")]
    svc = LampService(store, demo=True)
    auto = automation.Automation(store, svc, demo=True, watch=False)
    assert wait(qapp, lambda: all(svc.state(i).online for i in ("a", "b")))
    with svc.automated():
        svc.apply_scene(["a", "b"], automation.Scene("", "white", 40, 20))
    assert wait(qapp, lambda: svc.state("a").brightness == 40 and svc.state("b").is_on)
    yield qapp, store, svc, auto
    auto.shutdown()
    svc.shutdown()


def add_rule(store, auto, **kw):
    from lampdesk.storage import Rule
    r = Rule(kw.pop("name", "teste"), **kw)
    store.config.rules.append(r)
    auto.reload()
    return r


def test_away_turns_off_and_restores(env):
    qapp, store, svc, auto = env
    add_rule(store, auto, trigger="away", delay_min=0, action="off", targets=["a"])
    auto.locked = True
    auto.evaluate_states()
    assert wait(qapp, lambda: not svc.state("a").is_on)
    assert svc.state("b").is_on  # só o alvo
    auto.locked = False
    auto.evaluate_states()
    assert wait(qapp, lambda: svc.state("a").is_on and svc.state("a").brightness == 40)


def test_away_waits_for_the_delay(env):
    qapp, store, svc, auto = env
    add_rule(store, auto, trigger="away", delay_min=1, action="off")
    auto.locked = True
    auto.evaluate_states()
    wait(qapp, lambda: False, 0.2)
    assert svc.state("a").is_on
    auto._since[store.config.rules[-1].id] -= 61  # passou 1 minuto
    auto.evaluate_states()
    assert wait(qapp, lambda: not svc.state("a").is_on)


def test_manual_change_wins_over_automation(env):
    qapp, store, svc, auto = env
    add_rule(store, auto, trigger="away", delay_min=0, action="off", targets=["a"])
    auto.locked = True
    auto.evaluate_states()
    assert wait(qapp, lambda: not svc.state("a").is_on)
    svc.set_brightness(["a"], 90)  # usuário mexeu (não está em automated())
    assert wait(qapp, lambda: svc.state("a").brightness == 90)
    auto.locked = False
    auto.evaluate_states()
    wait(qapp, lambda: False, 0.2)
    assert svc.state("a").brightness == 90  # não voltou para os 40% de antes


def test_blink_returns_to_previous_light(env):
    qapp, store, svc, auto = env
    auto.blink(["a"], [40, 110, 255], [0, 0, 0], 2)
    assert wait(qapp, lambda: svc.state("a").mode == "colour")
    assert wait(qapp, lambda: not auto.stack.keys())
    assert wait(qapp, lambda: svc.state("a").mode == "white" and svc.state("a").brightness == 40
                and svc.state("a").is_on)


def test_blink_over_fullscreen_layer(env):
    qapp, store, svc, auto = env
    sc = store.config.scenes
    from lampdesk.storage import Scene
    sc.append(Scene("Cinema", "colour", 25, 0, [90, 60, 255], id="movie"))
    add_rule(store, auto, trigger="fullscreen", any_fullscreen=False, apps=["valorant"], action="scene",
             scene_id="movie", targets=["a"])
    auto.fg_exe = "valorant.exe"
    auto.evaluate_states()
    assert wait(qapp, lambda: svc.state("a").color == (90, 60, 255))
    auto.blink(["a"], [0, 255, 0], [0, 0, 0], 1)
    assert wait(qapp, lambda: not any(k.startswith("blink") for k in auto.stack.keys()))
    assert wait(qapp, lambda: svc.state("a").color == (90, 60, 255))  # volta para o modo jogo
    auto.fg_exe = "explorer.exe"
    auto.evaluate_states()
    assert wait(qapp, lambda: svc.state("a").mode == "white" and svc.state("a").brightness == 40)


def test_fade_out_then_off(env):
    qapp, store, svc, auto = env
    auto.fade(["a"], None, 1)
    f = auto._fades[0]
    for _ in range(f.steps):
        auto._fade_step(f)
    assert not auto._fades
    assert wait(qapp, lambda: not svc.state("a").is_on)


def test_fade_in_from_off(env):
    qapp, store, svc, auto = env
    from lampdesk.storage import Scene
    svc.set_power(["a"], False)
    assert wait(qapp, lambda: not svc.state("a").is_on)
    auto.fade(["a"], Scene("", "white", 80, 30), 1)
    assert wait(qapp, lambda: svc.state("a").is_on and svc.state("a").brightness == 1)
    f = auto._fades[0]
    for _ in range(f.steps):
        auto._fade_step(f)
    assert wait(qapp, lambda: svc.state("a").brightness == 80)


def test_discord_rules_need_discord_mode(env):
    qapp, store, svc, auto = env
    from lampdesk.automation import default_rules
    from lampdesk.i18n import tr
    store.config.rules = default_rules(tr, store.config)
    auto.reload()
    calls = []
    auto.blink = lambda ids, c1, c2, times: calls.append((tuple(c1), tuple(c2), times))
    auto.on_notification("com.squirrel.Discord.Discord", "Ana · oi")
    assert calls == []
    auto.set_discord(True)
    auto.on_notification("com.squirrel.Discord.Discord", "Ana · oi")
    auto.on_notification("com.squirrel.Discord.Discord", "Ana está te ligando")
    assert calls == [((40, 110, 255), (0, 0, 0), 2), ((40, 230, 90), (255, 255, 255), 5)]
    assert auto.wants_notifications()


def test_shutdown_sets_lamp_timer_and_startup_cancels_it(env):
    qapp, store, svc, auto = env
    add_rule(store, auto, trigger="shutdown", action="off_later", minutes=2)
    auto.on_shutdown()
    assert wait(qapp, lambda: all(svc._bulbs[i].bulb.countdown == 120 for i in ("a", "b")))
    assert store.config.settings.countdown_pending
    auto.startup()
    assert wait(qapp, lambda: all(svc._bulbs[i].bulb.countdown == 0 for i in ("a", "b")))
    assert not store.config.settings.countdown_pending


def test_suspend_respects_option(env):
    qapp, store, svc, auto = env
    add_rule(store, auto, trigger="shutdown", action="off", suspend=False)
    auto.on_shutdown(suspend=True)
    wait(qapp, lambda: False, 0.2)
    assert svc.state("a").is_on


def test_time_rules_pause_during_vacation(env):
    qapp, store, svc, auto = env
    now = dt.datetime.now().astimezone()
    add_rule(store, auto, trigger="time", time=now.strftime("%H:%M"), action="off")
    auto.set_pause(now.date().isoformat())
    auto.run_time_rules()
    wait(qapp, lambda: False, 0.2)
    assert svc.state("a").is_on
    auto.set_pause("")
    auto._fired.clear()
    auto.run_time_rules()
    assert wait(qapp, lambda: not svc.state("a").is_on)


def test_circadian_adjusts_and_pauses_on_manual_change(env):
    qapp, store, svc, auto = env
    from lampdesk import rules as R
    store.config.settings.circadian.enabled = True
    noon = dt.datetime.now().astimezone().replace(hour=12, minute=30)
    temp, bright = R.circadian_look(noon, store.config.settings.location, 40)
    auto.circadian_tick(noon)
    assert wait(qapp, lambda: svc.state("a").temperature == temp and svc.state("a").brightness == bright)
    svc.set_temperature(["a"], 5)  # à mão
    assert wait(qapp, lambda: svc.state("a").temperature == 5)
    auto.circadian_tick(noon)
    wait(qapp, lambda: False, 0.2)
    assert svc.state("a").temperature == 5


def test_hotkey_runs_rule_as_user(env):
    qapp, store, svc, auto = env
    r = add_rule(store, auto, trigger="hotkey", hotkey="Ctrl+Alt+L", action="toggle")
    hid = next(h for h, rid in auto._hotkey_map.items() if rid == r.id)
    seen = []
    svc.userCommand.connect(lambda ids, kind: seen.append(kind))
    auto._on_hotkey(hid)
    assert wait(qapp, lambda: not svc.state("a").is_on)
    assert seen == ["power"]


def test_music_layer_and_restore(env):
    qapp, store, svc, auto = env
    store.config.settings.music.enabled = True
    auto.set_music_color((255, 0, 0))
    assert wait(qapp, lambda: svc.state("a").color == (255, 0, 0) and svc.state("a").brightness == 80)
    auto.set_music_color(None)
    assert wait(qapp, lambda: svc.state("a").mode == "white" and svc.state("a").brightness == 40)


def test_pomodoro_cycle(env):
    qapp, store, svc, auto = env
    calls = []
    auto.blink = lambda ids, c1, c2, times: calls.append(tuple(c1))
    p = auto.pomodoro
    p.start()
    assert p.phase == "focus" and 24 * 60 < p.remaining() <= 25 * 60
    p.advance()
    assert p.phase == "short" and calls[-1] == tuple(store.config.settings.pomodoro.break_color)
    p.advance()
    assert p.phase == "focus"
    for _ in range(5):
        p.advance()
    assert p.phase == "long"  # quarto foco concluído
    p.stop()
    assert not p.running() and p.remaining() is None


def test_image_color(qapp):
    from PySide6.QtGui import QColor, QImage
    from lampdesk.automation import image_color
    img = QImage(40, 40, QImage.Format.Format_RGB32)
    img.fill(QColor(20, 40, 200))
    r, g, b = image_color(img)
    assert b == 255 and r < 80
    assert image_color(b"nao e imagem") is None

