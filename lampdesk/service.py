"""Ponte entre a interface (Qt) e as lâmpadas: conexões ao vivo e timers."""

import contextlib
import logging
import time
from dataclasses import replace
from typing import Dict, Iterable, List, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .lamp import FakeLiveBulb, LampState, LiveBulb
from .storage import Scene, Store

log = logging.getLogger(__name__)


class LampService(QObject):
    stateChanged = Signal(str, object)      # lamp_id, LampState
    versionDetected = Signal(str, str)      # lamp_id, versão
    timersChanged = Signal()
    userCommand = Signal(list, str)         # ids e tipo de comando mexidos à mão (painel, bandeja, atalhos)

    # usados pelas threads das lâmpadas; o Qt entrega na thread da interface
    _bulbState = Signal(str, object)
    _bulbVersion = Signal(str, str)

    def __init__(self, store: Store, demo: bool = False, parent=None):
        super().__init__(parent)
        self.store = store
        self.demo = demo
        self._bulbs: Dict[str, object] = {}
        self._signature: Dict[str, tuple] = {}
        self._states: Dict[str, LampState] = {}
        self._timers: Dict[str, tuple] = {}  # chave -> (deadline, [ids])
        self._auto = 0  # > 0 enquanto as automações mandam comandos

        self._bulbState.connect(self._on_bulb_state, Qt.ConnectionType.QueuedConnection)
        self._bulbVersion.connect(self.versionDetected, Qt.ConnectionType.QueuedConnection)

        # as lâmpadas avisam sozinhas quando mudam; isto só corrige eventuais desvios
        self._poll = QTimer(self)
        self._poll.timeout.connect(lambda: self.refresh())
        self._poll.start(60_000)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._check_timers)
        self._tick.start(1000)

        self.reload()

    # ------------------------------------------------------------ lâmpadas ---
    def reload(self) -> None:
        """Sincroniza as conexões com a lista de lâmpadas da configuração."""
        lamps = {l.id: l for l in self.store.config.lamps}
        for lid in list(self._bulbs):
            if lid not in lamps:
                self._bulbs.pop(lid).stop()
                self._states.pop(lid, None)
                self._signature.pop(lid, None)
        for lid, lamp in lamps.items():
            sig = (lamp.device_id, lamp.ip, lamp.local_key, lamp.version)
            old = self._signature.get(lid)
            if old == sig:
                continue
            bulb = self._bulbs.get(lid)
            if old and bulb and old[:3] == sig[:3] and old[3] == "auto" \
                    and sig[3] == getattr(bulb, "detected_version", None):
                self._signature[lid] = sig  # só gravou a versão detectada: mantém a conexão
                continue
            if bulb:
                bulb.stop()
            self._bulbs[lid] = self._start_bulb(lamp)
            self._signature[lid] = sig
            self._states.setdefault(lid, LampState())

    def _start_bulb(self, lamp):
        cls = FakeLiveBulb if self.demo else LiveBulb
        bulb = cls(lamp,
                   on_state=lambda st, lid=lamp.id: self._bulbState.emit(lid, st),
                   on_version=lambda v, lid=lamp.id: self._bulbVersion.emit(lid, v))
        bulb.start()
        return bulb

    def _on_bulb_state(self, lid: str, st: LampState) -> None:
        if lid not in self._bulbs:
            return
        if not st.online:  # mantém os últimos valores conhecidos para exibir
            st = replace(self.state(lid), online=False, error=st.error)
        self._states[lid] = st
        self.stateChanged.emit(lid, st)

    def state(self, lamp_id: str) -> LampState:
        return self._states.get(lamp_id, LampState())

    def version(self, lamp_id: str) -> Optional[str]:
        return getattr(self._bulbs.get(lamp_id), "detected_version", None)

    def ids(self, selection: str) -> List[str]:
        return [l.id for l in self.store.config.resolve_targets([selection])]

    def any_on(self) -> bool:
        return any(s.online and s.is_on for s in self._states.values())

    def shutdown(self) -> None:
        for bulb in self._bulbs.values():
            bulb.stop()

    def flush(self, timeout: float = 2.0) -> bool:
        """Espera os comandos na fila saírem (antes de o PC desligar). True se deu tempo."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not any(getattr(b, "pending", lambda: False)() for b in self._bulbs.values()):
                return True
            time.sleep(0.03)
        return False

    @contextlib.contextmanager
    def automated(self):
        """Comandos dentro deste bloco vêm das automações (não contam como mudança manual)."""
        self._auto += 1
        try:
            yield
        finally:
            self._auto -= 1

    # ------------------------------------------------------------- comandos ---
    def refresh(self, ids: Optional[Iterable[str]] = None) -> None:
        for lid in ids if ids is not None else list(self._bulbs):
            bulb = self._bulbs.get(lid)
            if bulb:
                bulb.refresh()

    def set_power(self, ids: Iterable[str], on: bool) -> None:
        self._apply(ids, "power", on, lambda s: replace(s, is_on=on))

    def toggle(self, ids: List[str]) -> None:
        self.set_power(ids, not any(self.state(i).is_on for i in ids))

    def set_brightness(self, ids, pct: int) -> None:
        self._apply(ids, "brightness", pct, lambda s: replace(s, is_on=True, brightness=pct))

    def set_temperature(self, ids, pct: int) -> None:
        self._apply(ids, "temperature", pct, lambda s: replace(s, is_on=True, mode="white", temperature=pct))

    def set_color(self, ids, rgb) -> None:
        rgb = tuple(int(c) for c in rgb)
        self._apply(ids, "color", rgb, lambda s: replace(s, is_on=True, mode="colour", color=rgb))

    def apply_scene(self, ids, scene: Scene) -> None:
        def optimistic(s):
            if scene.mode == "colour":
                return replace(s, is_on=True, mode="colour", color=tuple(scene.color), brightness=scene.brightness)
            return replace(s, is_on=True, mode="white", brightness=scene.brightness, temperature=scene.temperature)
        self._apply(ids, "scene", scene, optimistic)

    def apply_look(self, ids, look: Optional[Scene]) -> None:
        """Aplica um "visual" (cena) ou desliga (None)."""
        if look is None:
            self.set_power(ids, False)
        else:
            self.apply_scene(ids, look)

    def countdown(self, ids, seconds: int) -> None:
        """Timer interno da lâmpada: desliga sozinha depois de N segundos, mesmo com o PC desligado."""
        self._apply(ids, "countdown", int(seconds), lambda s: s)

    def _apply(self, ids, kind, value, optimistic) -> None:
        ids = list(ids)
        if not self._auto and kind != "countdown":
            self.userCommand.emit(ids, kind)
        for lid in ids:
            bulb = self._bulbs.get(lid)
            if bulb is None:
                continue
            current = self.state(lid)
            # a tela muda na hora; a lâmpada confirma logo em seguida
            self._states[lid] = optimistic(current)
            self.stateChanged.emit(lid, self._states[lid])
            bulb.command(kind, value, current)

    # --------------------------------------------------------- temporizador ---
    def start_timer(self, key: str, ids: List[str], minutes: int) -> None:
        self._timers[key] = (time.monotonic() + minutes * 60, list(ids))
        self.timersChanged.emit()

    def cancel_timer(self, key: str) -> None:
        if self._timers.pop(key, None):
            self.timersChanged.emit()

    def timer_remaining(self, key: str) -> Optional[int]:
        """Segundos restantes do timer de desligar, ou None."""
        t = self._timers.get(key)
        return max(0, int(t[0] - time.monotonic())) if t else None

    def _check_timers(self) -> None:
        now = time.monotonic()
        for key, (deadline, ids) in list(self._timers.items()):
            if now >= deadline:
                del self._timers[key]
                self.set_power(ids, False)
                self.timersChanged.emit()
