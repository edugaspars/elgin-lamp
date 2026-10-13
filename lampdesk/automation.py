"""Motor das automações: regras "Quando/Se/Então", efeitos de luz, ciclo do dia, música e pomodoro.

Prioridade de quem manda na luz (camadas da `LightStack`):
avisos (piscar) > ausência (PC bloqueado) > modos (tela cheia) > música > ciclo do dia/rotinas.
Quando uma camada termina, a lâmpada volta ao que estava antes dela. Mexer na luz à mão
(painel, bandeja, atalho) tira a lâmpada das camadas: nada é "desfeito" por cima do usuário.
"""

import contextlib
import datetime as dt
import hashlib
import logging
import threading
import time
from typing import Dict, List, Optional

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, QTimer, Signal

from . import rules as R
from . import scheduler, winsys
from .lamp import LampState
from .storage import REACTIVE_MODES, ROOM, Rule, Scene

log = logging.getLogger(__name__)

PRIO_ALERT, PRIO_FOCUS, PRIO_AWAY, PRIO_MODE, PRIO_MUSIC, PRIO_SCENE = 100, 90, 60, 40, 30, 20
SCREEN_SCENE = "scene:screen"  # camada da cena reativa Ambilight escolhida no painel
COVER_SCENE = "scene:cover"    # camada da cena reativa Música (capa do álbum)

BOOT_WINDOW_S = 15 * 60       # "ao ligar o PC": só se o PC ligou há pouco (não a cada abertura do app)
FULLSCREEN_DEBOUNCE_S = 2     # alt-tab rápido não troca a luz
BLINK_MS = 650
NOTIFY_GAP_S = 4              # mensagens em sequência não emendam piscadas
CALL_WORDS = "chamada|ligação|ligando|chamando|call|calling|ringing"

# Um "visual": None = desligada, "on" = só ligar, ("brightness", n), ou uma Scene.
ON = "on"


def look_of(st: LampState):
    """Visual atual de uma lâmpada (para voltar a ele depois)."""
    if not st.is_on:
        return None
    if st.mode == "colour":
        return Scene("", "colour", st.brightness, st.temperature, list(st.color))
    return Scene("", "white", st.brightness, st.temperature)


def colour_look(rgb, brightness: int = 100):
    if not any(rgb):
        return None  # [0, 0, 0]: fase apagada do piscar
    return Scene("", "colour", brightness, 50, list(rgb))


def _sig(look):
    if isinstance(look, Scene):
        return (look.mode, look.brightness, look.temperature, tuple(look.color) if look.mode == "colour" else ())
    return look


def default_rules(tr, cfg) -> List[Rule]:
    """Exemplos prontos (desligados, menos os do modo Discord, que dependem do próprio modo)."""
    def scene_id(key):
        name = tr(key)
        return next((s.id for s in cfg.scenes if s.name == name), cfg.scenes[0].id if cfg.scenes else "")

    return [
        Rule(tr("rule.ex.away"), trigger="away", delay_min=1, action="off", enabled=False),
        Rule(tr("rule.ex.fullscreen"), trigger="fullscreen", action="screen", enabled=False),
        Rule(tr("rule.ex.dawn"), trigger="startup", window_from="05:00", window_to="11:00", action="fade_in",
             scene_id=scene_id("scene.reading"), minutes=10, enabled=False),
        Rule(tr("rule.ex.bedtime"), trigger="time", time="23:00", action="fade_out", minutes=15, enabled=False),
        Rule(tr("rule.ex.shutdown"), trigger="shutdown", action="off_later", minutes=2, enabled=False),
        Rule(tr("rule.ex.water"), trigger="time", time="15:00", days=[0, 1, 2, 3, 4], action="blink",
             color=[0, 200, 255], color2=[0, 0, 0], times=3, enabled=False),
        Rule(tr("rule.ex.discord_msg"), trigger="notification", apps=["discord"], exclude=CALL_WORDS,
             mode="discord", action="blink", color=[40, 110, 255], color2=[0, 0, 0], times=2),
        Rule(tr("rule.ex.discord_call"), trigger="notification", apps=["discord"], text=CALL_WORDS,
             mode="discord", action="blink", color=[40, 230, 90], color2=[255, 255, 255], times=5),
        Rule(tr("rule.ex.hotkey"), trigger="hotkey", hotkey="Ctrl+Alt+L", action="toggle", enabled=False),
    ]


RULES_VERSION = 5


def upgrade_rules(cfg) -> bool:
    """Atualiza exemplos de versões anteriores que o usuário não mexeu. True se mudou algo."""
    from .i18n import STRINGS
    changed = False
    if cfg.settings.rules_version < 2:
        # modo jogo/filme: da cena "Cinema" (roxo fixo) para a cor da tela
        names = {STRINGS[lang]["rule.ex.fullscreen"] for lang in STRINGS}
        movie = {STRINGS[lang]["scene.movie"] for lang in STRINGS}
        for r in cfg.rules:
            sc = cfg.scene(r.scene_id)
            if r.trigger == "fullscreen" and r.name in names and r.action == "scene" and sc and sc.name in movie:
                r.action = "screen"
                changed = True
    if cfg.settings.rules_version < 3:
        # cena Cinema (roxo fixo) vira a cena reativa Ambilight, se o usuário não a mudou
        from .i18n import tr
        movie = {STRINGS[lang]["scene.movie"] for lang in STRINGS}
        for sc in cfg.scenes:
            if sc.name in movie and sc.mode == "colour" and list(sc.color) == [90, 60, 255] and sc.brightness == 25:
                sc.name, sc.mode = tr("scene.ambilight"), "screen"
                changed = True
    if cfg.settings.rules_version < 4 and not any(sc.mode == "cover" for sc in cfg.scenes):
        from .i18n import tr
        cfg.scenes.append(Scene(tr("scene.music"), "cover", 100, 50))  # cena Música (capa do álbum)
        changed = True
    if cfg.settings.rules_version < 5:
        # automações e recursos em "Todas" passam a valer só no ambiente deste PC
        s = cfg.settings
        for holder in [*cfg.rules, s.circadian, s.music, s.pomodoro, s.focus]:
            if holder.targets == ["*"]:
                holder.targets = [ROOM]
                changed = True
    if cfg.settings.rules_version != RULES_VERSION:
        cfg.settings.rules_version = RULES_VERSION
        changed = True
    return changed


# ---------------------------------------------------------------- camadas ---
class LightStack:
    """Camadas temporárias sobre a luz "de base" de cada lâmpada."""

    def __init__(self, service):
        self.service = service
        self._layers: Dict[str, list] = {}   # chave -> [prioridade, ordem, ids, visual, passa a trava]
        self._base: Dict[str, object] = {}   # lid -> visual de antes da primeira camada
        self._base_scene: Dict[str, Optional[str]] = {}  # lid -> cena que o painel mostrava antes
        self._shown: Dict[str, object] = {}  # lid -> assinatura do visual aplicado
        self._order = 0

    def controls(self, lid: str) -> bool:
        return lid in self._base

    def active(self, key: str) -> bool:
        return key in self._layers

    def keys(self) -> List[str]:
        return list(self._layers)

    def base(self, lid: str):
        return self._base.get(lid)

    def set_base(self, lid: str, look) -> None:
        if lid in self._base:
            self._base[lid] = look

    def _top(self, lid):
        best = None
        for key, (prio, order, ids, look, bypass) in self._layers.items():
            if lid in ids and (best is None or (prio, order) > best[0]):
                best = ((prio, order), key, look, bypass)
        return best

    def push(self, key: str, priority: int, ids, look, bypass: bool = False) -> None:
        """Cria ou atualiza uma camada (o visual pode mudar a cada chamada, ex.: piscar, música).

        `bypass`: a camada passa pela trava do modo foco (o próprio foco e o pomodoro).
        """
        layer = self._layers.get(key)
        if layer is None:
            self._order += 1
            layer = self._layers[key] = [priority, self._order, set(), look, bypass]
        layer[3] = look
        for lid in ids:
            if lid in layer[2]:
                continue
            if lid not in self._base:
                st = self.service.state(lid)
                if not st.online:
                    continue  # sem estado conhecido não há para onde voltar
                self._base[lid] = look_of(st)
                self._base_scene[lid] = self.service.scene_mark(lid)
            layer[2].add(lid)
        self._refresh(layer[2])

    def pop(self, key: str, restore: bool = True) -> None:
        layer = self._layers.pop(key, None)
        if layer is None:
            return
        back, scenes = {}, {}
        for lid in layer[2]:
            if lid not in self._base:
                continue
            if self._top(lid) is not None:
                self._refresh([lid])
                continue
            base = self._base.pop(lid)
            scene = self._base_scene.pop(lid, None)
            self._shown.pop(lid, None)
            if restore:
                back.setdefault(repr(_sig(base)), (base, []))[1].append(lid)
                scenes[lid] = scene
        for look, ids in back.values():
            self._apply(ids, look, bypass=layer[4])  # quem passou pela trava também volta por ela
        for lid, scene in scenes.items():
            self.service.set_scene_mark(lid, scene)  # e o painel volta a mostrar a cena de antes

    def release(self, ids) -> None:
        """Mexeram à mão: as camadas param de mandar nessas lâmpadas e não as "desfazem" depois."""
        for lid in ids:
            self._base.pop(lid, None)
            self._base_scene.pop(lid, None)
            self._shown.pop(lid, None)
            for layer in self._layers.values():
                layer[2].discard(lid)

    def refresh(self, ids, force: bool = False) -> None:
        """Reaplica a camada de cima (`force`: mesmo que já tenha sido aplicada, ex.: fim do foco)."""
        if force:
            for lid in ids:
                self._shown.pop(lid, None)
        self._refresh(ids)

    def _refresh(self, ids) -> None:
        todo = {}
        for lid in ids:
            top = self._top(lid)
            if top is None:
                continue
            sig = _sig(top[2])
            if lid in self._shown and self._shown[lid] == sig:
                continue
            self._shown[lid] = sig
            todo.setdefault((repr(sig), top[3]), (top[2], []))[1].append(lid)
        for (_sig_key, bypass), (look, lids) in todo.items():
            self._apply(lids, look, bypass)

    def _apply(self, ids, look, bypass: bool = False) -> None:
        with self.service.automated(bypass_lock=bypass):
            paint(self.service, ids, look)


def paint(svc, ids, look) -> None:
    if not ids:
        return
    if look is None:
        svc.set_power(ids, False)
    elif look == ON:
        svc.set_power(ids, True)
    elif isinstance(look, tuple) and look[0] == "brightness":
        svc.set_brightness(ids, look[1])
    else:
        svc.apply_scene(ids, look)


class CoverTracker:
    """Decide quando ler a capa de novo e quando a música parou (sem Windows: testável).

    O Windows às vezes troca o nome da música antes da capa; por isso, depois de cada troca,
    a capa é relida por alguns segundos até a imagem mudar. Pular de faixa passa por "busy"
    e uma pausa curta não devolve a luz na hora.
    """

    SETTLE = 4       # leituras extras da capa depois de trocar de música (~4 s)
    PAUSE_GRACE = 2  # leituras pausado antes de a luz voltar ao que era (~2 s)

    def __init__(self):
        self.key = ""
        self.digest = None
        self.settle = 0
        self.idle = 0

    def want_cover(self, key: str) -> bool:
        return key != self.key or self.settle > 0 or self.digest is None

    def update(self, status: str, key: str = "", digest: Optional[str] = None) -> str:
        """"color" (capa nova), "stop" (parou: devolver a luz) ou "keep"."""
        if status == "busy":
            return "keep"
        if status != "playing":
            self.idle += 1
            if self.idle >= self.PAUSE_GRACE and (self.key or self.digest):
                self.key, self.digest, self.settle = "", None, 0
                return "stop"
            return "keep"
        self.idle = 0
        if key != self.key:
            self.key, self.settle = key, self.SETTLE
        elif self.settle > 0:
            self.settle -= 1
        if digest is not None and digest != self.digest:
            self.digest = digest
            return "color"
        return "keep"


class _Fade:
    def __init__(self, begin: Dict[str, int], end: int, steps: int, then_off: bool, timer: QTimer):
        self.begin, self.end, self.steps, self.then_off, self.timer = begin, end, steps, then_off, timer
        self.i = 0


# ---------------------------------------------------------------- pomodoro ---
class PomodoroTimer(QObject):
    changed = Signal()

    def __init__(self, auto):
        super().__init__(auto)
        self.auto = auto
        self.phase = "idle"   # "idle" | "focus" | "short" | "long"
        self.done = 0         # focos concluídos
        self._ends = 0.0
        self._timer = QTimer(self, interval=1000)
        self._timer.timeout.connect(self._tick)

    @property
    def cfg(self):
        return self.auto.store.config.settings.pomodoro

    def running(self) -> bool:
        return self.phase != "idle"

    def remaining(self) -> Optional[int]:
        return max(0, int(self._ends - time.monotonic())) if self.running() else None

    def start(self) -> None:
        self.done = 0
        self._begin("focus")
        self._timer.start()

    def stop(self) -> None:
        self.phase = "idle"
        self._timer.stop()
        self.changed.emit()

    def toggle(self) -> None:
        self.stop() if self.running() else self.start()

    def _begin(self, phase: str) -> None:
        minutes = {"focus": self.cfg.focus_min, "short": self.cfg.short_min, "long": self.cfg.long_min}[phase]
        self.phase = phase
        self._ends = time.monotonic() + max(1, minutes) * 60
        self.changed.emit()

    def advance(self) -> None:
        ids = self.auto.ids(self.cfg.targets)
        if self.phase == "focus":
            self.done += 1
            self.auto.blink(ids, self.cfg.break_color, [0, 0, 0], 3, bypass=True)
            self._begin("long" if self.done % max(1, self.cfg.every) == 0 else "short")
        else:
            self.auto.blink(ids, self.cfg.focus_color, [0, 0, 0], 3, bypass=True)
            self._begin("focus")

    def _tick(self) -> None:
        if self.running() and time.monotonic() >= self._ends:
            self.advance()
        self.changed.emit()


# ---------------------------------------------------- eventos do Windows ---
class _NativeFilter(QAbstractNativeEventFilter):
    """Desligar/suspender/voltar e tela apagada chegam como mensagens do Windows."""

    def __init__(self, auto):
        super().__init__()
        self.auto = auto

    def nativeEventFilter(self, event_type, message):
        try:
            if bytes(event_type) not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                return False, 0
            from ctypes import c_ubyte, wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0011:            # WM_QUERYENDSESSION
                self.auto.on_shutdown()
            elif msg.message == 0x0218:          # WM_POWERBROADCAST
                if msg.wParam == 0x4:            # PBT_APMSUSPEND
                    self.auto.on_shutdown(suspend=True)
                elif msg.wParam in (0x7, 0x12):  # PBT_APMRESUMESUSPEND / RESUMEAUTOMATIC
                    self.auto.on_resume()
                elif msg.wParam == 0x8013 and msg.lParam:  # PBT_POWERSETTINGCHANGE (estado da tela)
                    value = c_ubyte.from_address(int(msg.lParam) + 20).value
                    self.auto.display_off = value == 0
        except Exception:  # noqa: BLE001
            log.debug("Evento nativo ignorado", exc_info=True)
        return False, 0


class SystemWatcher(QObject):
    """Lê o estado do PC (bloqueio, uso, tela cheia, notificações) e repassa às automações."""

    def __init__(self, auto):
        super().__init__(auto)
        self.auto = auto
        self.reader = winsys.NotificationReader()
        self._filter = None
        self._power_window = None
        self._timer = QTimer(self, interval=1000)
        self._timer.timeout.connect(self.poll)
        self._notif = QTimer(self, interval=1500)
        self._notif.timeout.connect(self.poll_notifications)
        if winsys.WINDOWS:
            self._timer.start()
            self._notif.start()
            self._install_native()

    def poll(self):
        a = self.auto
        a.locked = winsys.is_locked()
        a.idle = winsys.idle_seconds()
        a.fg_exe, a.fullscreen = winsys.foreground()
        a.evaluate_states()

    def poll_notifications(self):
        if not self.auto.wants_notifications():
            self.reader.last_id = None  # ao religar, não dispara pelo que chegou nesse meio-tempo
            return
        for app, payload in self.reader.poll():
            self.auto.on_notification(app, R.toast_text(payload))

    def _install_native(self):
        try:
            from PySide6.QtWidgets import QApplication, QWidget
            app = QApplication.instance()
            self._filter = _NativeFilter(self.auto)
            app.installNativeEventFilter(self._filter)
            app.commitDataRequest.connect(lambda *_: self.auto.on_shutdown())
            self._power_window = QWidget()  # janela oculta: recebe o aviso de tela apagada/acesa
            hwnd = int(self._power_window.winId())
            import ctypes
            import uuid

            class GUID(ctypes.Structure):
                _fields_ = [("data", ctypes.c_ubyte * 16)]

            guid = GUID()
            guid.data[:] = uuid.UUID("6fe69556-704a-47a0-8f24-c28d936fda47").bytes_le  # CONSOLE_DISPLAY_STATE
            self._guid = guid
            ctypes.windll.user32.RegisterPowerSettingNotification.restype = ctypes.c_void_p
            ctypes.windll.user32.RegisterPowerSettingNotification(ctypes.c_void_p(hwnd), ctypes.byref(guid), 0)
        except Exception:  # noqa: BLE001
            log.warning("Eventos de energia do Windows indisponíveis", exc_info=True)

    def stop(self):
        self._timer.stop()
        self._notif.stop()


# ------------------------------------------------------------------ motor ---
class Automation(QObject):
    changed = Signal()            # modos/pomodoro/música mudaram: menus e rótulos se atualizam
    _hotkey = Signal(int)
    _cover = Signal(object)

    def __init__(self, store, service, demo: bool = False, watch: bool = True, parent=None):
        super().__init__(parent)
        self.store, self.service, self.demo = store, service, demo
        self.stack = LightStack(service)
        self.pomodoro = PomodoroTimer(self)
        self.pomodoro.changed.connect(self.changed)

        # estado do sistema (o SystemWatcher preenche; os testes podem preencher à mão)
        self.locked = False
        self.display_off = False
        self.idle = 0.0
        self.fg_exe = ""
        self.fullscreen = False
        self.last_notification = ("", "")
        self.last_track = ""

        self._since: Dict[str, float] = {}       # regra de estado -> desde quando o estado vale
        self._active: Dict[str, str] = {}         # regra de estado ativa -> chave da camada
        self._fired: Dict[str, str] = {}          # regras de horário já disparadas hoje
        self._notified: Dict[str, float] = {}     # regra de notificação -> quando piscou
        self._fades: List[_Fade] = []
        self._circ_paused: Dict[str, dt.date] = {}  # lid -> dia em que mexeram à mão
        self._shutdown_at = 0.0
        self._resumed_at = 0.0
        self._seq = 0
        self._hotkeys = None
        self._hotkey_map: Dict[int, str] = {}
        self._hotkey_sig = None
        self._music_color = None
        self._cover_busy = False
        self.cover = CoverTracker()
        self._screen_rules: Dict[str, tuple] = {}  # camada que segue a tela -> (prioridade, [lâmpadas])
        self._cover_layers: Dict[str, tuple] = {}  # camada que segue a capa -> (prioridade, [lâmpadas], brilho)
        self._cover_rgb = None        # cor da capa que está tocando (None = nada tocando)
        self._mood = None             # último visual da tela aplicado
        self._mood_pending = (None, 0)  # troca de tipo (cor/branco/escuro) esperando confirmar
        self._focus_window = None     # dentro do horário de trabalho na última conferida

        service.userCommand.connect(self._on_user)
        service.reactiveScene.connect(self._on_reactive_scene)
        self._hotkey.connect(self._on_hotkey, Qt.ConnectionType.QueuedConnection)
        self._cover.connect(self._on_cover, Qt.ConnectionType.QueuedConnection)

        self._clock = QTimer(self, interval=20_000)
        self._clock.timeout.connect(self.run_time_rules)
        self._circ_timer = QTimer(self, interval=60_000)
        self._circ_timer.timeout.connect(self.circadian_tick)
        self._cover_timer = QTimer(self, interval=1000)
        self._cover_timer.timeout.connect(self._poll_cover)
        self._screen_timer = QTimer(self, interval=500)
        self._screen_timer.timeout.connect(self._poll_screen)
        self._ambi_timer = QTimer(self, interval=500)
        self._ambi_timer.timeout.connect(self._ambi_tick)
        self._clock.start()
        self._circ_timer.start()

        self.watcher = SystemWatcher(self) if watch else None
        self.reload()

    # ------------------------------------------------------------ apoio ---
    @property
    def cfg(self):
        return self.store.config

    def ids(self, targets) -> List[str]:
        return [l.id for l in self.cfg.resolve_targets(list(targets))]

    def modes(self) -> set:
        return {"discord"} if self.cfg.settings.discord_mode else set()

    def _now(self) -> dt.datetime:
        return dt.datetime.now().astimezone()

    def _rules(self, trigger: str) -> List[Rule]:
        return [r for r in self.cfg.rules if r.trigger == trigger and r.enabled]

    def wants_notifications(self) -> bool:
        return any(R.conditions_ok(r, self._now(), self.cfg.settings.location, self.modes())
                   for r in self._rules("notification"))

    def shutdown(self) -> None:
        if self._hotkeys:
            self._hotkeys.stop()
        if self.watcher:
            self.watcher.stop()
        for t in (self._clock, self._circ_timer, self._cover_timer, self._screen_timer, self._ambi_timer):
            t.stop()
        self.pomodoro.stop()
        for f in list(self._fades):
            f.timer.stop()
        self._fades.clear()

    def reload(self) -> None:
        """Configuração mudou: reavalia regras ativas, atalhos e recursos."""
        valid = {r.id for r in self.cfg.rules if r.enabled and r.trigger in R.STATE_TRIGGERS}
        for rid in [rid for rid in self._active if rid not in valid]:
            key = self._active.pop(rid)
            self._screen_rules.pop(key, None)
            self.stack.pop(key)
            self._since.pop(rid, None)
        if not self._screen_rules:
            self._ambi_timer.stop()
        self._setup_hotkeys()
        self._setup_music()
        self._apply_focus_lock()
        self.evaluate_states()
        self.changed.emit()

    # --------------------------------------------------------- mão do usuário ---
    def _on_user(self, ids, kind=""):
        self.stack.release(ids)
        for key, (prio, lids) in list(self._screen_rules.items()):  # a cor da tela para de mandar nelas
            rest = [lid for lid in lids if lid not in ids]
            if key == SCREEN_SCENE and not rest:
                self._stop_screen(key, restore=False)
            else:
                self._screen_rules[key] = (prio, rest)
        for key, (prio, lids, bright) in list(self._cover_layers.items()):
            rest = [lid for lid in lids if lid not in ids]
            if key == COVER_SCENE and not rest:
                self._stop_cover(key, restore=False)
            else:
                self._cover_layers[key] = (prio, rest, bright)
        today = self._now().date()
        for f in self._fades:
            for lid in ids:
                f.begin.pop(lid, None)
        if kind != "power":
            for lid in ids:
                self._circ_paused[lid] = today
        elif self.cfg.settings.circadian.enabled:
            QTimer.singleShot(1500, self.circadian_tick)  # acabou de acender: já no tom da hora

    # ------------------------------------------------------------- efeitos ---
    def blink(self, ids, color, color2, times: int, bypass: bool = False) -> None:
        self._seq += 1
        key = f"blink:{self._seq}"
        steps = [colour_look(color if i % 2 == 0 else color2) for i in range(max(1, times) * 2)]
        timer = QTimer(self, interval=BLINK_MS)
        state = {"i": 0}

        def step():
            if state["i"] >= len(steps):
                timer.stop()
                timer.deleteLater()
                self.stack.pop(key)
                return
            self.stack.push(key, PRIO_ALERT, ids, steps[state["i"]], bypass)
            state["i"] += 1
        timer.timeout.connect(step)
        step()
        timer.start()

    def fade(self, ids, target: Optional[Scene], minutes: int) -> None:
        """Acende até `target` (ou apaga, se None) aos poucos ao longo de `minutes`."""
        svc = self.service
        for f in self._fades:  # um fade novo assume essas lâmpadas
            for lid in ids:
                f.begin.pop(lid, None)
        begin = {}
        if target is not None and target.mode in REACTIVE_MODES:  # reativa: não tem como "subir aos poucos"
            with svc.automated():
                svc.apply_scene(ids, target)
            return
        with svc.automated():
            for lid in ids:
                st = svc.state(lid)
                if not st.online:
                    continue
                if self.stack.controls(lid):  # ex.: PC bloqueado com a luz apagada: muda só o "depois"
                    self.stack.set_base(lid, target)
                    continue
                if target is None:
                    if st.is_on:
                        begin[lid] = st.brightness
                else:
                    start = st.brightness if st.is_on else 1
                    first = Scene("", target.mode, min(start, target.brightness), target.temperature,
                                  list(target.color))
                    svc.apply_scene([lid], first)
                    begin[lid] = first.brightness
        if not begin:
            return
        seconds = max(1, minutes) * 60
        steps = max(2, min(120, seconds // 5))
        end = 1 if target is None else target.brightness
        f = _Fade(begin, end, steps, target is None, QTimer(self, interval=int(seconds * 1000 / steps)))
        f.timer.timeout.connect(lambda: self._fade_step(f))
        self._fades.append(f)
        f.timer.start()

    def fading(self, lid: str) -> bool:
        return any(lid in f.begin for f in self._fades)

    def _fade_step(self, f: _Fade):
        svc = self.service
        f.i += 1
        t = min(1.0, f.i / f.steps)
        groups = {}
        for lid, b in f.begin.items():
            groups.setdefault(max(1, round(b + (f.end - b) * t)), []).append(lid)
        with svc.automated():
            for value, lids in groups.items():
                svc.set_brightness(lids, value)
            if t >= 1.0 and f.then_off and f.begin:
                svc.set_power(list(f.begin), False)
        if t >= 1.0 or not f.begin:
            f.timer.stop()
            f.timer.deleteLater()
            self._fades.remove(f)

    # -------------------------------------------------------------- ações ---
    def _look(self, rule: Rule):
        if rule.action == "off":
            return None
        if rule.action == "on":
            return ON
        if rule.action == "brightness":
            return ("brightness", max(1, min(100, rule.value)))
        if rule.action == "color":
            return colour_look(rule.color) or None
        sc = self.cfg.scene(rule.scene_id)
        return sc if sc else ON

    def run_action(self, rule: Rule, ids: Optional[List[str]] = None, manual: bool = False) -> None:
        ids = self.ids(rule.targets) if ids is None else ids
        svc = self.service
        a = rule.action
        log.info("Automação '%s' (%s)", rule.name, a)
        with (contextlib.nullcontext() if manual else svc.automated()):
            if a in R.LOOK_ACTIONS:
                paint(svc, ids, self._look(rule))
            elif a == "screen":
                paint(svc, ids, self.screen_look(fresh=True))
            elif a == "toggle":
                svc.toggle(ids)
            elif a == "brightness_step":
                for lid in ids:
                    st = svc.state(lid)
                    svc.set_brightness([lid], max(1, min(100, (st.brightness if st.is_on else 0) + rule.value)))
            elif a == "blink":
                self.blink(ids, rule.color, rule.color2, rule.times)
            elif a == "fade_in":
                sc = self.cfg.scene(rule.scene_id) or Scene("", "white", 100, 50)
                self.fade(ids, sc, rule.minutes)
            elif a == "fade_out":
                self.fade(ids, None, rule.minutes)
            elif a == "off_later":
                svc.countdown(ids, rule.minutes * 60)
                self.cfg.settings.countdown_pending = True
                self.store.save()
            elif a == "pomodoro":
                self.pomodoro.toggle()
            elif a == "focus":
                self.set_focus(not self.cfg.settings.focus.active)
            elif a == "discord_mode":
                self.set_discord(not self.cfg.settings.discord_mode)
            elif a == "circadian":
                self.set_circadian(not self.cfg.settings.circadian.enabled)
            elif a == "music":
                self.set_music(not self.cfg.settings.music.enabled)

    def fire(self, trigger: str, rules=None) -> int:
        now, loc, modes = self._now(), self.cfg.settings.location, self.modes()
        n = 0
        for r in rules if rules is not None else self._rules(trigger):
            if R.conditions_ok(r, now, loc, modes):
                self.run_action(r, manual=trigger == "hotkey")
                n += 1
        return n

    # ------------------------------------------------- gatilhos de estado ---
    def evaluate_states(self) -> None:
        now, wall = time.monotonic(), self._now()
        for r in self._rules("away"):
            active = self.locked or self.display_off or (r.idle_min > 0 and self.idle >= r.idle_min * 60)
            self._state_rule(r, active, r.delay_min * 60, now, wall, PRIO_AWAY)
        exe = self.fg_exe.casefold()
        for r in self._rules("fullscreen"):
            apps = {a.strip().casefold() for a in r.apps if a.strip()}
            active = (r.any_fullscreen and self.fullscreen) or bool(exe) and (
                exe in apps or exe.removesuffix(".exe") in apps)
            self._state_rule(r, active, FULLSCREEN_DEBOUNCE_S, now, wall, PRIO_MODE)

    def _state_rule(self, r: Rule, active: bool, delay: float, now: float, wall, prio: int) -> None:
        if active:
            since = self._since.setdefault(r.id, now)
            if r.id not in self._active and now - since >= delay and \
                    R.conditions_ok(r, wall, self.cfg.settings.location, self.modes()):
                self._enter(r, prio)
        else:
            self._since.pop(r.id, None)
            if r.id in self._active:
                self._exit(r)

    def _enter(self, r: Rule, prio: int) -> None:
        key = f"rule:{r.id}"
        self._active[r.id] = key
        log.info("Automação '%s' começou", r.name)
        sc = self.cfg.scene(r.scene_id) if r.action == "scene" else None
        if self._follows_screen(r):
            self._start_screen(key, prio, self.ids(r.targets))
        elif sc is not None and sc.mode == "cover":
            self._start_cover(key, prio, self.ids(r.targets), sc.brightness)
        elif r.action in R.LOOK_ACTIONS:
            self.stack.push(key, prio, self.ids(r.targets), self._look(r))
        else:
            self.run_action(r)

    def _exit(self, r: Rule) -> None:
        key = self._active.pop(r.id)
        log.info("Automação '%s' terminou", r.name)
        self._screen_rules.pop(key, None)
        if not self._screen_rules:
            self._ambi_timer.stop()
        if self._cover_layers.pop(key, None) is not None:
            self._update_cover_timer()
        if r.restore == "scene" and self.cfg.scene(r.restore_scene):
            ids = [lid for lid in self.ids(r.targets) if self.stack.controls(lid)]
            self.stack.pop(key, restore=False)
            with self.service.automated():
                self.service.apply_scene(ids, self.cfg.scene(r.restore_scene))
        else:
            self.stack.pop(key, restore=r.restore != "none")

    # ------------------------------------------------- gatilhos de evento ---
    def run_time_rules(self) -> None:
        s = self.cfg.settings
        now = self._now()
        self.focus_schedule(now)
        timed = [r for r in self.cfg.rules if r.trigger in ("time", "sunrise", "sunset")]
        due = scheduler.due(timed, now, s.location, self._fired)  # marca como disparadas mesmo pausadas
        if R.paused(s.pause_until, now.date()):
            return
        self.fire("time", due)

    def on_notification(self, app_id: str, text: str) -> None:
        self.last_notification = (app_id, text)
        now = time.monotonic()
        rules = [r for r in self._rules("notification") if R.notification_matches(r, app_id, text)
                 and now - self._notified.get(r.id, -1e9) >= NOTIFY_GAP_S]  # rajada de mensagens: pisca uma vez
        if rules and self.fire("notification", rules):
            for r in rules:
                self._notified[r.id] = now

    def _on_hotkey(self, hid: int) -> None:
        rid = self._hotkey_map.get(hid)
        rule = next((r for r in self.cfg.rules if r.id == rid and r.enabled), None)
        if rule:
            self.fire("hotkey", [rule])

    def startup(self, force: bool = False, tries: int = 4) -> None:
        """App abriu: cancela o timer interno pedido no desligamento e roda "ao ligar o PC"."""
        if tries > 0 and not all(self.service.state(l.id).online for l in self.cfg.lamps):
            # o Wi-Fi ainda está voltando: espera as lâmpadas conectarem (até ~20 s)
            QTimer.singleShot(5000, lambda: self.startup(force, tries - 1))
            return
        s = self.cfg.settings
        if s.focus.active:  # as lâmpadas acabaram de conectar: aplica a luz do foco nelas
            self._push_focus()
        if s.countdown_pending:
            with self.service.automated():
                self.service.countdown(self.ids(["*"]), 0)
            s.countdown_pending = False
            self.store.save()
        up = winsys.uptime_seconds()
        if force or up is None or up < BOOT_WINDOW_S:
            self.fire("startup")

    def on_resume(self) -> None:
        if time.monotonic() - self._resumed_at < 30:
            return  # o Windows manda dois avisos de "voltou"
        self._resumed_at = time.monotonic()
        self._shutdown_at = 0.0
        QTimer.singleShot(5000, lambda: self.startup(force=True))  # Wi-Fi volta alguns segundos depois

    def on_shutdown(self, suspend: bool = False) -> None:
        if time.monotonic() - self._shutdown_at < 30:
            return
        self._shutdown_at = time.monotonic()
        rules = [r for r in self._rules("shutdown") if r.suspend or not suspend]
        if self.fire("shutdown", rules):
            self.service.flush(1.5)  # o Windows dá poucos segundos: espera os comandos saírem

    def _setup_hotkeys(self) -> None:
        keys, mapping = {}, {}
        for i, r in enumerate(self._rules("hotkey"), start=1):
            parsed = R.parse_hotkey(r.hotkey)
            if parsed:
                keys[i], mapping[i] = parsed, r.id
        sig = tuple(sorted((k, v, mapping[k]) for k, v in keys.items()))
        if sig == self._hotkey_sig:
            return
        self._hotkey_sig = sig
        if self._hotkeys:
            self._hotkeys.stop()
            self._hotkeys = None
        self._hotkey_map = mapping
        if keys and winsys.WINDOWS:
            self._hotkeys = winsys.HotkeyThread(keys, self._hotkey.emit)
            self._hotkeys.start()

    def hotkey_failures(self) -> List[str]:
        if not self._hotkeys:
            return []
        self._hotkeys.wait_ready(0.2)
        names = {r.id: r for r in self.cfg.rules}
        return [names[self._hotkey_map[h]].hotkey for h in self._hotkeys.failed if self._hotkey_map.get(h) in names]

    # ------------------------------------------------------- modos/recursos ---
    def set_discord(self, on: bool) -> None:
        self.cfg.settings.discord_mode = on
        self.store.save()
        self.changed.emit()

    def set_circadian(self, on: bool) -> None:
        self.cfg.settings.circadian.enabled = on
        self.store.save()
        if on:
            self._circ_paused.clear()
            self.circadian_tick()
        self.changed.emit()

    def set_music(self, on: bool) -> None:
        self.cfg.settings.music.enabled = on
        self.store.save()
        self._setup_music()
        self.changed.emit()

    def set_pause(self, until: str) -> None:
        self.cfg.settings.pause_until = until
        self.store.save()
        self.changed.emit()

    def is_paused(self) -> bool:
        return R.paused(self.cfg.settings.pause_until, self._now().date())

    # ------------------------------------------------------------ modo foco ---
    def focus_ids(self) -> List[str]:
        return self.ids(self.cfg.settings.focus.targets)

    def focus_scene(self) -> Scene:
        f = self.cfg.settings.focus
        sc = self.cfg.scene(f.scene_id)
        if sc is not None and sc.mode in REACTIVE_MODES:
            sc = None  # foco é luz parada
        if sc is None:
            from .i18n import STRINGS
            names = {STRINGS[lang]["scene.focus"] for lang in STRINGS}
            sc = next((x for x in self.cfg.scenes if x.name in names), None)
        return sc or Scene("", "white", 100, 100)

    def _apply_focus_lock(self) -> None:
        f = self.cfg.settings.focus
        self.service.locked = set(self.focus_ids()) if f.active else set()

    def _push_focus(self) -> None:
        self.stack.push("focus", PRIO_FOCUS, self.focus_ids(), self.focus_scene(), bypass=True)

    def set_focus(self, on: bool) -> None:
        """Modo foco: luz de trabalho e nenhuma automação mexe nas lâmpadas (só o pomodoro pisca).

        Mexer à mão continua livre. Ao desligar, a luz volta ao que era antes do foco.
        """
        f = self.cfg.settings.focus
        was = set(self.service.locked)
        f.active = on
        self.store.save()
        self._apply_focus_lock()
        if on:
            self._push_focus()
        else:
            self.stack.pop("focus")
            self.stack.refresh(list(was), force=True)  # camadas que ficaram travadas (música, tela) voltam
        log.info("Modo foco %s", "ligado" if on else "desligado")
        self.changed.emit()

    def is_focus(self) -> bool:
        return self.cfg.settings.focus.active

    def focus_schedule(self, now: Optional[dt.datetime] = None) -> None:
        """Horário de trabalho: liga ao entrar e desliga ao sair (dá para mudar à mão no meio)."""
        f = self.cfg.settings.focus
        if not f.schedule:
            self._focus_window = None
            return
        now = now or self._now()
        inside = now.weekday() in f.days and R.parse_hhmm(f.start) is not None and \
            R.parse_hhmm(f.end) is not None and R.in_window(now, f.start, f.end)
        if inside != self._focus_window:
            prev, self._focus_window = self._focus_window, inside
            if inside and not f.active:
                self.set_focus(True)
            elif not inside and prev and f.active:
                self.set_focus(False)  # só desliga se o app viu o horário acabar

    # -------------------------------------------------------- ciclo do dia ---
    def circadian_tick(self, now: Optional[dt.datetime] = None) -> None:
        c = self.cfg.settings.circadian
        if not c.enabled:
            return
        now = now or self._now()
        temp, bright = R.circadian_look(now, self.cfg.settings.location, c.night_brightness)
        svc = self.service
        for lid in self.ids(c.targets):
            if self._circ_paused.get(lid) == now.date() or self.fading(lid):
                continue
            st = svc.state(lid)
            if not st.online or not st.has_temperature:
                continue
            b = bright if c.brightness else st.brightness
            look = Scene("", "white", b, temp)
            if self.stack.controls(lid):
                base = self.stack.base(lid)
                if isinstance(base, Scene) and base.mode == "white":
                    self.stack.set_base(lid, Scene("", "white", b if c.brightness else base.brightness, temp))
                continue
            if not st.is_on or st.mode != "white":
                continue  # não acende sozinho nem apaga uma cor escolhida
            if abs(st.temperature - temp) < 2 and abs(st.brightness - b) < 2:
                continue
            with svc.automated():
                svc.apply_scene([lid], look)

    # ---------------------------------------------------------------- música ---
    def _setup_music(self) -> None:
        m = self.cfg.settings.music
        screen = m.enabled and m.source == "screen"
        (self._screen_timer.start if screen else self._screen_timer.stop)()
        self._update_cover_timer()
        if not m.enabled and self.stack.active("music"):
            self.stack.pop("music")
            self._music_color = None
            if not self._cover_layers:
                self.last_track = ""
                self.cover = CoverTracker()

    def set_music_color(self, rgb) -> None:
        """Nova cor da música/tela (None = nada tocando: a luz volta ao normal)."""
        m = self.cfg.settings.music
        if rgb is None:
            self._music_color = None
            self.stack.pop("music")
            return
        if self._music_color is not None and R.color_distance(rgb, self._music_color) < 24:
            return
        self._music_color = tuple(rgb)
        self.stack.push("music", PRIO_MUSIC, self.ids(m.targets), colour_look(rgb, m.brightness))

    def _poll_cover(self) -> None:
        if self._cover_busy or not winsys.WINDOWS:
            return
        self._cover_busy = True
        want = self.cover.want_cover

        def job():
            try:
                status, key, data = winsys.media_now(want)
                digest = hashlib.sha1(data).hexdigest() if data else None
                self._cover.emit((status, key, digest, image_color(data) if data else None))
            except Exception:  # noqa: BLE001
                log.debug("Capa do álbum", exc_info=True)
                self._cover.emit(("busy", "", None, None))
        threading.Thread(target=job, daemon=True, name="cover").start()

    def _on_cover(self, res) -> None:
        self._cover_busy = False
        m = self.cfg.settings.music
        feature = m.enabled and m.source == "cover"
        if not feature and not self._cover_layers:
            return
        status, key, digest, color = res
        what = self.cover.update(status, key, digest)
        if what == "stop":
            self.last_track = ""
            if feature:
                self.set_music_color(None)
            self._cover_changed(None)
            self.changed.emit()
        elif what == "color":
            self.last_track = key
            if color is not None:
                if feature:
                    self.set_music_color(color)
                self._cover_changed(color)
            self.changed.emit()

    def _poll_screen(self) -> None:
        img = grab_primary()
        rgb = image_color(img) if img is not None else None
        if rgb is not None:
            self.set_music_color(rgb)

    # ------------------------------------------------- cor da tela (jogo/filme) ---
    def screen_look(self, fresh: bool = False, pixels=None):
        """Visual da tela agora: colorido a 100%, branco a 25% ou branco quente a 1% no escuro.

        Trocar de tipo (cor ↔ branco ↔ escuro) só depois de duas leituras seguidas, para um
        clarão rápido não piscar a luz. `fresh` ignora a espera (ao entrar no modo).
        """
        if pixels is None:
            img = grab_primary()
            pixels = image_pixels(img) if img is not None else []
        kind, value = R.screen_mood(pixels)
        prev = self._mood
        if not fresh and prev is not None and kind != prev[0]:
            pending, count = self._mood_pending
            count = count + 1 if pending == kind else 1
            self._mood_pending = (kind, count)
            if count < 2:
                return prev[1]
        self._mood_pending = (None, 0)
        if kind == "colour":
            if prev and prev[0] == "colour" and R.color_distance(value, prev[1].color) < 24:
                return prev[1]
            look = Scene("", "colour", R.SCREEN_COLOUR_BRIGHTNESS, 50, list(value))
        elif kind == "white":
            look = Scene("", "white", R.SCREEN_WHITE_BRIGHTNESS, value)
            if prev and prev[0] == "white" and abs(prev[1].temperature - value) < 6:
                return prev[1]
        else:
            look = Scene("", "white", R.SCREEN_DARK_BRIGHTNESS, 0)
        self._mood = (kind, look)
        return look

    def _ambi_tick(self) -> None:
        if not self._screen_rules:
            self._ambi_timer.stop()
            return
        look = self.screen_look()
        for key, (prio, ids) in self._screen_rules.items():
            if self.stack.active(key):
                self.stack.push(key, prio, ids, look)

    def _follows_screen(self, rule: Rule) -> bool:
        if rule.action == "screen":
            return True
        sc = self.cfg.scene(rule.scene_id) if rule.action == "scene" else None
        return bool(sc and sc.mode == "screen")

    def _start_screen(self, key: str, prio: int, ids) -> None:
        self._screen_rules[key] = (prio, list(ids))
        self.stack.push(key, prio, ids, self.screen_look(fresh=True))
        self._ambi_timer.start()

    def _stop_screen(self, key: str, restore: bool = True) -> None:
        self._screen_rules.pop(key, None)
        self.stack.pop(key, restore=restore)
        if not self._screen_rules:
            self._ambi_timer.stop()

    def _on_reactive_scene(self, ids, scene=None) -> None:
        """Escolheram uma cena reativa: a luz segue a tela (Ambilight) ou a capa do álbum (Música)
        até outra cena ou uma mudança à mão."""
        if scene is not None and scene.mode == "cover":
            old = self._cover_layers.get(COVER_SCENE, (PRIO_SCENE, [], 100))[1]
            merged = list(dict.fromkeys([*old, *ids]))
            if merged:
                self._start_cover(COVER_SCENE, PRIO_SCENE, merged, scene.brightness)
            return
        old = self._screen_rules.get(SCREEN_SCENE, (PRIO_SCENE, []))[1]
        merged = list(dict.fromkeys([*old, *ids]))
        if merged:
            self._start_screen(SCREEN_SCENE, PRIO_SCENE, merged)

    # ----------------------------------------------- capa do álbum (cena Música) ---
    def _start_cover(self, key: str, prio: int, ids, brightness: int) -> None:
        self._cover_layers[key] = (prio, list(ids), brightness)
        if self._cover_rgb is not None:  # já está tocando: aplica a cor na hora
            self.stack.push(key, prio, ids, colour_look(self._cover_rgb, brightness))
        else:
            self.cover.digest = None     # relê a capa na próxima consulta (em até 1 s)
        self._update_cover_timer()

    def _stop_cover(self, key: str, restore: bool = True) -> None:
        self._cover_layers.pop(key, None)
        self.stack.pop(key, restore=restore)
        self._update_cover_timer()

    def _update_cover_timer(self) -> None:
        m = self.cfg.settings.music
        wanted = (m.enabled and m.source == "cover") or bool(self._cover_layers)
        (self._cover_timer.start if wanted else self._cover_timer.stop)()

    def _cover_changed(self, rgb) -> None:
        """Cor da capa mudou (None = parou de tocar: as camadas somem e a luz volta ao que era)."""
        self._cover_rgb = tuple(rgb) if rgb is not None else None
        for key, (prio, ids, bright) in self._cover_layers.items():
            if rgb is None:
                self.stack.pop(key)
            else:
                self.stack.push(key, prio, ids, colour_look(rgb, bright))

    # ------------------------------------------------------------ diagnóstico ---
    def diagnostics(self) -> Dict[str, str]:
        reader = self.watcher.reader if self.watcher else None
        app, text = self.last_notification
        return {
            "locked": self.locked, "display_off": self.display_off, "idle": int(self.idle),
            "foreground": self.fg_exe, "fullscreen": self.fullscreen,
            "notifications": (reader.error or "ok") if reader and reader.available() else "missing",
            "last_notification": f"{app}: {text}"[:160] if app else "",
            "hotkeys_failed": ", ".join(self.hotkey_failures()),
            "media": "ok" if winsys.media_available() else "missing",
            "track": self.last_track,
            "uptime": winsys.uptime_seconds(),
            "active": ", ".join(self._active_names()),
        }

    def _active_names(self) -> List[str]:
        names = {r.id: r.name for r in self.cfg.rules}
        return [names.get(rid, rid) for rid in self._active]


def primary_area(image, geo, virtual):
    """Recorta o monitor principal quando a captura vem com a área de trabalho inteira.

    Conforme a versão do Qt/Windows, capturar a "tela" pode trazer todos os monitores juntos;
    a cor deve vir só do principal. `geo` e `virtual` são as geometrias do Qt (pixels lógicos).
    """
    if virtual.size() == geo.size() or virtual.width() <= 0 or virtual.height() <= 0:
        return image  # um monitor só
    ratio = image.width() / virtual.width()
    if abs(image.height() - virtual.height() * ratio) > max(2, 0.02 * image.height()):
        return image  # o formato não é o da área inteira: já veio só o principal
    from PySide6.QtCore import QRect
    return image.copy(QRect(round((geo.x() - virtual.x()) * ratio), round((geo.y() - virtual.y()) * ratio),
                            round(geo.width() * ratio), round(geo.height() * ratio)))


def grab_primary():
    """Captura do monitor principal (QImage) ou None."""
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()  # só o principal (Configurações do Windows › Tela)
    if screen is None:
        return None
    pm = screen.grabWindow(0)
    if pm.isNull():
        return None
    return primary_area(pm.toImage(), screen.geometry(), screen.virtualGeometry())


def image_pixels(image) -> list:
    """Pixels (r, g, b) de uma versão reduzida da imagem (QImage ou bytes de PNG/JPEG)."""
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QImage

    if isinstance(image, (bytes, bytearray)):
        image = QImage.fromData(bytes(image))
    if image is None or image.isNull():
        return []
    small = image.scaled(48, 32, _Qt.AspectRatioMode.IgnoreAspectRatio,
                         _Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGB32)
    pixels = []
    for y in range(small.height()):
        for x in range(small.width()):
            v = small.pixel(x, y)
            pixels.append(((v >> 16) & 255, (v >> 8) & 255, v & 255))
    return pixels


def image_color(image) -> Optional[tuple]:
    """Cor viva de uma imagem (QImage ou bytes de PNG/JPEG)."""
    return R.vivid_color(image_pixels(image))
