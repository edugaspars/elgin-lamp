"""Ponte entre a interface (Qt) e as lâmpadas: threads, fila e timers."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Dict, Iterable, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .crypto import mask
from .lamp import FakeBulb, LampError, LampState, TuyaBulb
from .storage import Lamp, Scene, Store

log = logging.getLogger(__name__)


class LampService(QObject):
    stateChanged = Signal(str, object)      # lamp_id, LampState
    versionDetected = Signal(str, str)      # lamp_id, versão
    timersChanged = Signal()

    def __init__(self, store: Store, demo: bool = False, parent=None):
        super().__init__(parent)
        self.store = store
        self.demo = demo
        self._bulbs: Dict[str, object] = {}
        self._signature: Dict[str, tuple] = {}
        self._pools: Dict[str, ThreadPoolExecutor] = {}
        self._states: Dict[str, LampState] = {}
        self._gen: Dict[tuple, int] = {}
        self._timers: Dict[str, tuple] = {}  # chave -> (deadline, [ids])
        self._pending: Dict[str, int] = {}   # comandos de escrita na fila, por lâmpada
        self._lock = threading.Lock()

        self._poll = QTimer(self)
        self._poll.timeout.connect(lambda: self.refresh())
        self._poll.start(60_000)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._check_timers)
        self._tick.start(1000)

        self.reload()

    # ------------------------------------------------------------ lâmpadas ---
    def reload(self) -> None:
        """Sincroniza com a lista de lâmpadas da configuração."""
        lamps = {l.id: l for l in self.store.config.lamps}
        for lid in list(self._bulbs):
            if lid not in lamps:
                self._bulbs.pop(lid)
                self._states.pop(lid, None)
                self._signature.pop(lid, None)
                self._pools.pop(lid).shutdown(wait=False, cancel_futures=True)
        for lid, lamp in lamps.items():
            sig = (lamp.device_id, lamp.ip, lamp.local_key, lamp.version)
            if self._signature.get(lid) != sig:
                self._bulbs[lid] = FakeBulb(lamp) if self.demo else TuyaBulb(lamp)
                self._signature[lid] = sig
                self._pools.setdefault(lid, ThreadPoolExecutor(1, thread_name_prefix=f"lamp-{lid}"))
                self._states.setdefault(lid, LampState())
        self.refresh()

    def state(self, lamp_id: str) -> LampState:
        return self._states.get(lamp_id, LampState())

    def ids(self, selection: str) -> List[str]:
        return [l.id for l in self.store.config.resolve_targets([selection])]

    def any_on(self) -> bool:
        return any(s.online and s.is_on for s in self._states.values())

    def shutdown(self) -> None:
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------- comandos ---
    def refresh(self, ids: Optional[Iterable[str]] = None) -> None:
        for lid in ids if ids is not None else list(self._bulbs):
            self._submit(lid, "read", None)

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

    # ---------------------------------------------------------- internos ---
    def _apply(self, ids, kind, value, optimistic) -> None:
        for lid in ids:
            if lid not in self._bulbs:
                continue
            self._states[lid] = optimistic(self.state(lid))
            self.stateChanged.emit(lid, self._states[lid])
            self._submit(lid, kind, value, optimistic)

    def _submit(self, lid: str, kind: str, value, optimistic=None) -> None:
        pool = self._pools.get(lid)
        if pool is None:
            return
        with self._lock:
            key = (lid, kind)
            gen = self._gen.get(key, 0) + 1
            self._gen[key] = gen
            if optimistic:
                self._pending[lid] = self._pending.get(lid, 0) + 1
        pool.submit(self._run, lid, kind, value, gen, optimistic)

    def _run(self, lid, kind, value, gen, optimistic) -> None:
        try:
            self._execute(lid, kind, value, gen, optimistic)
        finally:
            if optimistic:
                with self._lock:
                    self._pending[lid] -= 1

    def _execute(self, lid, kind, value, gen, optimistic) -> None:
        # Arrastar um slider gera muitos comandos: só o mais recente é enviado.
        if self._gen.get((lid, kind)) != gen:
            return
        bulb = self._bulbs.get(lid)
        if bulb is None:
            return
        current = self.state(lid)
        try:
            if kind == "read":
                new = bulb.read()
                if self._pending.get(lid, 0):
                    # um comando mais novo está na fila: esta leitura já está velha
                    new = replace(self.state(lid), online=True, error="")
            else:
                if kind == "power":
                    bulb.set_power(value)
                elif kind == "brightness":
                    bulb.set_brightness(value, current)
                elif kind == "temperature":
                    bulb.set_temperature(value, current)
                elif kind == "color":
                    bulb.set_color(value, current.brightness)
                elif kind == "scene":
                    bulb.apply_scene(value, current)
                new = replace(optimistic(self.state(lid)), online=True, error="", updated=time.time())
            ver = getattr(bulb, "detected_version", None)
            lamp: Lamp = bulb.lamp
            if ver and lamp.version == "auto" and not self.demo:
                self.versionDetected.emit(lid, ver)
        except (LampError, OSError, ValueError, RuntimeError) as exc:
            log.warning("Lâmpada %s: %s falhou: %s", mask(bulb.lamp.device_id), kind, exc)
            new = replace(self.state(lid), online=False, error=str(exc))
        except Exception as exc:  # nunca derrubar a thread
            log.exception("Erro inesperado na lâmpada %s", mask(bulb.lamp.device_id))
            new = replace(self.state(lid), online=False, error=str(exc))
        self._states[lid] = new
        self.stateChanged.emit(lid, new)
