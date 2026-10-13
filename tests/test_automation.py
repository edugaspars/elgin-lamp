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
    store.config.settings.focus.schedule = False  # o horário de trabalho não interfere nos testes
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
    auto.blink = lambda ids, c1, c2, times, bypass=False: calls.append(tuple(c1))
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



def test_cover_tracker_waits_for_the_new_cover():
    """O Windows às vezes troca o nome da música antes da capa: continua lendo até a imagem mudar."""
    from lampdesk.automation import CoverTracker
    t = CoverTracker()
    assert t.want_cover("A - x")
    assert t.update("playing", "A - x", "capa-a") == "color"
    assert t.want_cover("A - x")                        # logo depois da troca ainda confere a capa
    for _ in range(CoverTracker.SETTLE):
        assert t.update("playing", "A - x", "capa-a") == "keep"
    assert not t.want_cover("A - x")                    # mesma música, capa já lida
    assert t.want_cover("B - y")                        # trocou: lê de novo
    assert t.update("playing", "B - y", "capa-a") == "keep"  # capa ainda é a antiga
    assert t.want_cover("B - y")                        # então continua conferindo
    assert t.update("playing", "B - y", "capa-b") == "color"
    for _ in range(CoverTracker.SETTLE):
        t.update("playing", "B - y", None)
    assert not t.want_cover("B - y")                    # depois de alguns segundos, para de reler


def test_cover_tracker_pause_and_track_skip():
    from lampdesk.automation import CoverTracker
    t = CoverTracker()
    t.update("playing", "A - x", "capa-a")
    assert t.update("busy") == "keep"                   # pulando de faixa: não é pausa
    assert t.update("paused") == "keep"                 # pausa rápida: espera um pouco
    assert t.update("playing", "A - x", None) == "keep"
    assert t.update("paused") == "keep"
    assert t.update("paused") == "stop"                 # pausou de verdade: luz volta ao que era
    assert t.update("paused") == "keep"                 # só uma vez
    assert t.want_cover("A - x")
    assert t.update("playing", "A - x", "capa-a") == "color"  # deu play: a cor volta


def test_cover_events_drive_the_music_layer(env):
    qapp, store, svc, auto = env
    store.config.settings.music.enabled = True
    auto._on_cover(("playing", "A - x", "capa-a", (255, 0, 0)))
    assert wait(qapp, lambda: svc.state("a").color == (255, 0, 0))
    for _ in range(2):
        auto._on_cover(("paused", "", None, None))
    assert wait(qapp, lambda: svc.state("a").mode == "white" and svc.state("a").brightness == 40)


def test_screen_light_uses_only_the_primary_monitor(qapp):
    """Com dois monitores, a captura pode vir com a área inteira: a cor sai só do principal."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter
    from lampdesk.automation import image_color, primary_area

    primary, virtual = QRect(1920, 0, 1920, 1080), QRect(0, 0, 3840, 1080)  # principal à direita
    whole = QImage(384, 108, QImage.Format.Format_RGB32)  # captura reduzida dos dois monitores
    p = QPainter(whole)
    p.fillRect(0, 0, 192, 108, QColor(255, 0, 0))      # monitor da esquerda: vermelho
    p.fillRect(192, 0, 192, 108, QColor(0, 0, 255))    # principal: azul
    p.end()
    r, g, b = image_color(primary_area(whole, primary, virtual))
    assert b == 255 and r < 60
    only = whole.copy(192, 0, 192, 108)  # quando o Qt já entrega só o principal, não recorta de novo
    assert primary_area(only, primary, virtual).size() == only.size()
    assert primary_area(only, primary, primary) is only


def _image(rgb):
    from PySide6.QtGui import QColor, QImage
    img = QImage(64, 36, QImage.Format.Format_RGB32)
    img.fill(QColor(*rgb))
    return img


def test_screen_look_levels_and_hysteresis(env):
    qapp, store, svc, auto = env
    red, white, dark = [(230, 20, 20)] * 50, [(250, 250, 250)] * 50, [(5, 5, 5)] * 50
    look = auto.screen_look(fresh=True, pixels=red)
    assert look.mode == "colour" and look.brightness == 100
    assert auto.screen_look(pixels=dark) is look          # um quadro escuro só: mantém
    dim = auto.screen_look(pixels=dark)                    # confirmou: quente a 1%
    assert dim.mode == "white" and dim.brightness == 1 and dim.temperature == 0
    auto.screen_look(pixels=white)
    soft = auto.screen_look(pixels=white)
    assert soft.mode == "white" and soft.brightness == 25
    auto.screen_look(pixels=red)
    back = auto.screen_look(pixels=red)
    assert back.mode == "colour" and back.brightness == 100  # voltou ao colorido: 100% de novo


def test_fullscreen_screen_color_rule(env, monkeypatch):
    qapp, store, svc, auto = env
    from lampdesk import automation
    frame = {"img": _image((5, 5, 5))}
    monkeypatch.setattr(automation, "grab_primary", lambda: frame["img"])
    add_rule(store, auto, trigger="fullscreen", action="screen", targets=["a"])
    auto.fullscreen = True
    auto.evaluate_states()
    assert wait(qapp, lambda: svc.state("a").brightness == 1 and svc.state("a").temperature == 0)
    frame["img"] = _image((20, 40, 230))
    auto._ambi_tick()
    auto._ambi_tick()
    assert wait(qapp, lambda: svc.state("a").mode == "colour" and svc.state("a").brightness == 100)
    auto.fullscreen = False
    auto.evaluate_states()
    assert wait(qapp, lambda: svc.state("a").mode == "white" and svc.state("a").brightness == 40)
    assert not auto._ambi_timer.isActive()


def test_upgrade_movie_example_to_screen_color(qapp):
    from lampdesk.automation import RULES_VERSION, upgrade_rules
    from lampdesk.i18n import tr
    from lampdesk.storage import Config, Rule, Scene, default_scenes
    cfg = Config(scenes=default_scenes(tr))
    movie = Scene(tr("scene.movie"), "colour", 25, 0, [90, 60, 255])  # cena padrão das versões anteriores
    cfg.scenes.append(movie)
    old = Rule(tr("rule.ex.fullscreen"), trigger="fullscreen", action="scene", scene_id=movie.id)
    mine = Rule("Meu modo", trigger="fullscreen", action="scene", scene_id=movie.id)  # do usuário: não mexe
    cfg.rules = [old, mine]
    assert upgrade_rules(cfg)
    assert old.action == "screen" and mine.action == "scene"
    assert cfg.settings.rules_version == RULES_VERSION
    assert not upgrade_rules(cfg)  # só uma vez


def test_focus_mode_locks_automations_but_not_pomodoro_or_hands(env):
    qapp, store, svc, auto = env
    from lampdesk.storage import Scene
    store.config.scenes.append(Scene("Foco", "white", 100, 100))
    store.config.settings.focus.targets = ["a"]
    auto.set_focus(True)
    assert wait(qapp, lambda: svc.state("a").brightness == 100 and svc.state("a").temperature == 100)
    assert svc.state("b").brightness == 40  # só as lâmpadas do foco

    add_rule(store, auto, trigger="away", delay_min=0, action="off")
    auto.locked = True
    auto.evaluate_states()
    assert wait(qapp, lambda: not svc.state("b").is_on)  # fora do foco: automação normal
    wait(qapp, lambda: False, 0.2)
    assert svc.state("a").is_on                          # no foco: não apaga
    auto.locked = False
    auto.evaluate_states()

    auto.blink(["a"], [40, 110, 255], [0, 0, 0], 1)     # Discord / lembrete: não pisca
    wait(qapp, lambda: not auto.stack.keys() or auto.stack.keys() == ["focus"], 1)
    assert svc.state("a").mode == "white"
    seen = []
    svc.stateChanged.connect(lambda lid, st: seen.append((lid, st.mode)))
    auto.blink(["a"], [255, 60, 40], [0, 0, 0], 1, bypass=True)  # pomodoro: pisca
    assert wait(qapp, lambda: ("a", "colour") in seen)
    assert wait(qapp, lambda: auto.stack.keys() == ["focus"] and svc.state("a").mode == "white"
                and svc.state("a").brightness == 100)  # volta para a luz do foco

    svc.set_color(["a"], (255, 0, 0))                    # à mão: pode
    with svc.automated():
        svc.set_color(["a"], (0, 255, 0))                # automação: não pode
    bulb = svc._bulbs["a"]
    assert wait(qapp, lambda: not bulb.pending() and bulb.bulb.state.color == (255, 0, 0))
    wait(qapp, lambda: False, 0.3)
    assert bulb.bulb.state.color == (255, 0, 0)

    auto.set_focus(False)
    assert not svc.locked
    with svc.automated():
        svc.set_power(["a"], False)
    assert wait(qapp, lambda: not svc.state("a").is_on)  # destravou


def test_focus_restores_previous_light(env):
    qapp, store, svc, auto = env
    store.config.settings.focus.targets = ["a"]
    auto.set_focus(True)
    assert wait(qapp, lambda: svc.state("a").brightness == 100)
    auto.set_focus(False)
    assert wait(qapp, lambda: svc.state("a").brightness == 40 and svc.state("a").temperature == 20)


def test_focus_work_hours(env):
    qapp, store, svc, auto = env
    f = store.config.settings.focus
    f.schedule = True
    monday = dt.datetime(2026, 10, 12, 7, 59).astimezone()
    auto.focus_schedule(monday)
    assert not f.active
    auto.focus_schedule(monday.replace(hour=8, minute=0))
    assert f.active                                       # 8h: liga
    auto.set_focus(False)                                 # desligou à mão no meio do dia
    auto.focus_schedule(monday.replace(hour=12))
    assert not f.active                                   # respeita
    auto.set_focus(True)
    auto.focus_schedule(monday.replace(hour=17, minute=50))
    assert not f.active                                   # 17h50: desliga
    saturday = dt.datetime(2026, 10, 17, 10, 0).astimezone()
    auto.focus_schedule(saturday)
    assert not f.active                                   # fim de semana: não liga


def test_ambilight_scene_follows_screen_until_manual_change(env, monkeypatch):
    qapp, store, svc, auto = env
    from lampdesk import automation
    from lampdesk.storage import Scene
    frame = {"img": _image((20, 40, 230))}
    monkeypatch.setattr(automation, "grab_primary", lambda: frame["img"])
    ambi = Scene("Ambilight", "screen", 100, 50)
    svc.apply_scene(["a"], ambi)                       # escolhida no painel
    assert wait(qapp, lambda: svc.state("a").mode == "colour" and svc.state("a").brightness == 100)
    frame["img"] = _image((5, 5, 5))
    auto._ambi_tick()
    auto._ambi_tick()
    assert wait(qapp, lambda: svc.state("a").mode == "white" and svc.state("a").brightness == 1)
    svc.apply_scene(["a"], Scene("Leitura", "white", 90, 55))  # outra cena: a tela para de mandar
    assert automation.SCREEN_SCENE not in auto._screen_rules
    frame["img"] = _image((230, 20, 20))
    auto._ambi_tick()
    auto._ambi_tick()
    bulb = svc._bulbs["a"].bulb
    assert wait(qapp, lambda: not svc._bulbs["a"].pending() and bulb.state.brightness == 90)
    wait(qapp, lambda: False, 0.3)
    assert bulb.state.mode == "white" and bulb.state.brightness == 90


def test_ambilight_scene_never_reaches_the_bulb(qapp):
    from lampdesk.lamp import LampError, TuyaBulb
    from lampdesk.storage import Lamp, Scene

    class Dev:
        dpset = {"switch": "20", "mode": "21", "brightness": "22", "colourtemp": "23", "colour": "24",
                 "value_min": 10, "value_max": 1000, "value_hexformat": "hsv16", "timer": "26"}
    bulb = TuyaBulb(Lamp("x", "id", "192.0.2.1", "k" * 16))
    bulb._dev = Dev()
    with pytest.raises(LampError):
        bulb.values("scene", Scene("Ambilight", "screen"), None)


def test_upgrade_movie_scene_to_ambilight(qapp):
    from lampdesk.automation import upgrade_rules
    from lampdesk.i18n import tr
    from lampdesk.storage import Config, Scene
    cfg = Config(scenes=[Scene(tr("scene.movie"), "colour", 25, 0, [90, 60, 255]),
                         Scene(tr("scene.movie"), "colour", 60, 0, [255, 0, 0])])  # a segunda foi mudada
    cfg.settings.rules_version = 2
    assert upgrade_rules(cfg)
    assert cfg.scenes[0].mode == "screen" and cfg.scenes[0].name == tr("scene.ambilight")
    assert cfg.scenes[1].mode == "colour"
    assert sum(sc.mode == "cover" for sc in cfg.scenes) == 1  # cena Música adicionada uma vez
    assert not upgrade_rules(cfg)


def test_music_scene_follows_the_album_cover(env):
    qapp, store, svc, auto = env
    from lampdesk.automation import COVER_SCENE
    from lampdesk.storage import Scene
    music = Scene("Música", "cover", 70, 50)
    svc.apply_scene(["a"], music)                         # escolhida no painel, nada tocando ainda
    assert COVER_SCENE in auto._cover_layers and auto._cover_timer.isActive()
    wait(qapp, lambda: False, 0.1)
    assert svc.state("a").mode == "white" and svc.state("a").brightness == 40
    auto._on_cover(("playing", "A - x", "capa-a", (255, 0, 120)))
    assert wait(qapp, lambda: svc.state("a").mode == "colour" and svc.state("a").brightness == 70)
    for _ in range(2):
        auto._on_cover(("paused", "", None, None))         # pausou: volta ao que era
    assert wait(qapp, lambda: svc.state("a").mode == "white" and svc.state("a").brightness == 40)
    auto._on_cover(("playing", "A - x", "capa-b", (0, 200, 255)))  # play: a cor volta, cena continua
    assert wait(qapp, lambda: svc.state("a").mode == "colour")
    svc.set_brightness(["a"], 30)                        # mexeu à mão: a cena para
    assert COVER_SCENE not in auto._cover_layers and not auto._cover_timer.isActive()


def test_music_scene_uses_current_track_immediately(env):
    qapp, store, svc, auto = env
    from lampdesk.storage import Scene
    auto._cover_rgb = (255, 140, 0)                      # já estava tocando
    svc.apply_scene(["b"], Scene("Música", "cover", 100, 50))
    assert wait(qapp, lambda: svc.state("b").mode == "colour" and svc.state("b").brightness == 100)


def test_upgrade_moves_all_lamps_automations_to_the_room(qapp):
    from lampdesk.automation import upgrade_rules
    from lampdesk.storage import ROOM, Config, Rule, Routine, Scene
    cfg = Config(rules=[Rule("a", targets=["*"]), Rule("b", targets=["g1"])], routines=[Routine("r")],
                 scenes=[Scene("Música", "cover")])
    cfg.settings.circadian.targets = ["*"]
    cfg.settings.rules_version = 4
    assert upgrade_rules(cfg)
    assert cfg.rules[0].targets == [ROOM] and cfg.rules[1].targets == ["g1"]  # escolha específica fica
    assert cfg.settings.circadian.targets == [ROOM]
    assert cfg.routines[0].targets == ["*"]  # rotinas continuam na casa toda
