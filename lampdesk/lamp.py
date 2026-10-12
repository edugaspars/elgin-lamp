"""Comunicação local com as lâmpadas (protocolo Tuya/Smart Life, usado por
lâmpadas de várias marcas, como Elgin e Positivo).

Nada aqui depende de Qt: dá para usar como biblioteca/script também.
"""

import colorsys
import logging
import queue
import random
import select
import socket
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Optional, Tuple

from .crypto import mask
from .storage import Lamp, Scene

log = logging.getLogger(__name__)

AUTO_VERSIONS = ["3.3", "3.4", "3.5", "3.1"]


class LampError(Exception):
    pass


@dataclass
class LampState:
    online: bool = False
    is_on: bool = False
    mode: str = "white"           # "white" | "colour" | "scene" | "music"
    brightness: int = 100         # 1..100
    temperature: int = 50         # 0 (quente) .. 100 (frio)
    color: Tuple[int, int, int] = (255, 255, 255)
    has_temperature: bool = True
    has_colour: bool = True
    error: str = ""
    updated: float = field(default_factory=time.time)

    @property
    def hue(self) -> int:
        h, _s, _v = colorsys.rgb_to_hsv(*(c / 255 for c in self.color))
        return round(h * 360)


def rgb_from_hue(hue: float) -> Tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360, 1.0, 1.0)
    return round(r * 255), round(g * 255), round(b * 255)


def white_rgb(temperature: int) -> Tuple[int, int, int]:
    """Cor aproximada do branco para desenhar na tela (0=quente, 100=frio)."""
    t = max(0, min(100, temperature)) / 100
    warm, cool = (255, 176, 92), (214, 232, 255)
    return tuple(round(w + (c - w) * t) for w, c in zip(warm, cool))


def display_rgb(state: LampState) -> Tuple[int, int, int]:
    return state.color if state.mode == "colour" else white_rgb(state.temperature)


# ------------------------------------------------------------- Tuya real ---
class TuyaBulb:
    """Envolve tinytuya.BulbDevice: monta os DPs de cada comando e (no modo
    bloqueante, usado pela CLI e pelo "Testar conexão") envia um pacote por vez."""

    def __init__(self, lamp: Lamp, port: int = 6668):
        self.lamp = lamp
        self.port = port
        self.detected_version: Optional[str] = None
        self._dev = None

    # -- conexão -------------------------------------------------------------
    def _make(self, version: str, persist: bool):
        import tinytuya

        dev = tinytuya.BulbDevice(
            self.lamp.device_id, self.lamp.ip, self.lamp.local_key,
            version=float(version), connection_timeout=3,
            connection_retry_limit=1, connection_retry_delay=1, port=self.port,
        )
        dev.set_socketPersistent(persist)
        return dev

    def connect(self, persist: bool = False) -> dict:
        """Conecta (descobrindo o protocolo se for "auto") e retorna o status inicial."""
        versions = [self.lamp.version] if self.lamp.version != "auto" else AUTO_VERSIONS
        last_err = "sem resposta"
        for v in versions:
            dev = self._make(v, persist)
            res = dev.status()
            if res and "dps" in res and not res.get("Error"):
                dev.detect_bulb(res)
                self._dev = dev
                self.detected_version = v
                log.info("Lâmpada %s conectada (protocolo %s)", mask(self.lamp.device_id), v)
                return res
            dev.set_socketPersistent(False)  # fecha o socket da tentativa
            last_err = (res or {}).get("Error", last_err)
            if (res or {}).get("Err") in ("901", "905"):
                break  # nem conectou: trocar de versão não adianta
        raise LampError(last_err)

    def _device(self):
        if self._dev is None:
            self.connect()
        return self._dev

    def reset(self):
        if self._dev is not None:
            self._dev.set_socketPersistent(False)
        self._dev = None

    # -- leitura -------------------------------------------------------------
    def read(self) -> LampState:
        dev = self._device()
        res = dev.status()
        if not res or res.get("Error") or "dps" not in res:
            self.reset()
            raise LampError((res or {}).get("Error", "sem resposta"))
        return self._parse(dev, res["dps"])

    @staticmethod
    def _parse(dev, dps: dict) -> LampState:
        ds = dev.dpset
        vmax = ds["value_max"] if ds["value_max"] and ds["value_max"] > 0 else 1000
        st = LampState(online=True)
        st.has_temperature = bool(ds["colourtemp"])
        st.has_colour = bool(ds["colour"])
        st.is_on = bool(dps.get(ds["switch"], False)) if ds["switch"] else False
        if ds["mode"] and isinstance(dps.get(ds["mode"]), str):
            st.mode = dps[ds["mode"]]
        if ds["brightness"] and ds["brightness"] in dps:
            st.brightness = _clamp(round(dps[ds["brightness"]] / vmax * 100), 1, 100)
        if ds["colourtemp"] and ds["colourtemp"] in dps:
            st.temperature = _clamp(round(dps[ds["colourtemp"]] / vmax * 100), 0, 100)
        if ds["colour"] and dps.get(ds["colour"]):
            try:
                h, s, v = dev.hexvalue_to_hsv(dps[ds["colour"]], ds["value_hexformat"])
                r, g, b = colorsys.hsv_to_rgb(h, s, 1.0)
                st.color = (round(r * 255), round(g * 255), round(b * 255))
                if st.mode == "colour":
                    st.brightness = _clamp(round(v * 100), 1, 100)
            except Exception:  # valor fora do formato esperado
                pass
        return st

    # -- DPs de cada comando --------------------------------------------------
    def _scale(self, pct: int, floor: bool = True) -> int:
        """Converte 0..100 para a escala da lâmpada (10..1000 ou 25..255)."""
        ds = self._device().dpset
        value = round(ds["value_max"] * _clamp(pct, 0, 100) / 100)
        return max(ds["value_min"], value) if floor else value

    def _colour_hex(self, rgb, brightness: int) -> str:
        dev = self._device()
        h, s, _v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
        r, g, b = colorsys.hsv_to_rgb(h, s, _clamp(brightness, 1, 100) / 100)
        # passa inteiros: a conversão do tinytuya quebra com float no formato rgb8
        return dev.rgb_to_hexvalue(round(r * 255), round(g * 255), round(b * 255),
                                   dev.dpset["value_hexformat"])

    def values(self, kind: str, value, current: LampState) -> dict:
        """DPs a enviar para um comando ("power", "brightness", "temperature", "color", "scene")."""
        ds = self._device().dpset
        if kind == "power":
            out = {ds["switch"] or "1": bool(value)}
        elif kind == "brightness":
            if current.mode == "colour" and ds["colour"]:
                out = {ds["switch"]: True, ds["colour"]: self._colour_hex(current.color, value)}
            else:
                out = {ds["switch"]: True, ds["mode"]: "white", ds["brightness"]: self._scale(value)}
        elif kind == "temperature":
            if not ds["colourtemp"]:
                raise LampError("sem suporte a temperatura de cor")
            out = {ds["switch"]: True, ds["mode"]: "white", ds["brightness"]: self._scale(current.brightness),
                   ds["colourtemp"]: self._scale(value, floor=False)}
        elif kind == "color":
            if not ds["colour"]:
                raise LampError("sem suporte a cor")
            out = {ds["switch"]: True, ds["mode"]: "colour", ds["colour"]: self._colour_hex(value, current.brightness)}
        elif kind == "scene":
            scene: Scene = value
            if scene.mode == "colour" and ds["colour"]:
                out = {ds["switch"]: True, ds["mode"]: "colour",
                       ds["colour"]: self._colour_hex(scene.color, scene.brightness)}
            else:
                out = {ds["switch"]: True, ds["mode"]: "white", ds["brightness"]: self._scale(scene.brightness)}
                if ds["colourtemp"]:
                    out[ds["colourtemp"]] = self._scale(scene.temperature, floor=False)
        else:
            raise ValueError(kind)
        return {str(k): v for k, v in out.items() if k}

    # -- escrita bloqueante (CLI / testar conexão) ----------------------------
    def _send(self, values: dict) -> None:
        res = self._device().set_multiple_values(values)
        if isinstance(res, dict) and res.get("Error"):
            self.reset()
            raise LampError(res["Error"])

    def set_power(self, on: bool) -> None:
        self._send(self.values("power", on, LampState()))

    def set_brightness(self, pct: int, current: LampState) -> None:
        self._send(self.values("brightness", pct, current))

    def set_temperature(self, pct: int, current: LampState) -> None:
        self._send(self.values("temperature", pct, current))

    def set_color(self, rgb, brightness: int) -> None:
        self._send(self.values("color", rgb, LampState(brightness=brightness)))

    def apply_scene(self, scene: Scene, current: LampState) -> None:
        self._send(self.values("scene", scene, current))


# --------------------------------------------------------- modo de demo ---
class FakeBulb:
    """Lâmpada simulada (python -m lampdesk --demo) para testar sem hardware."""

    def __init__(self, lamp: Lamp):
        self.lamp = lamp
        self.detected_version = "3.3"
        rnd = random.Random(lamp.name)
        self.state = LampState(
            online=True, is_on=rnd.random() > 0.4, mode=rnd.choice(["white", "colour"]),
            brightness=rnd.randint(30, 100), temperature=rnd.randint(0, 100),
            color=rgb_from_hue(rnd.randint(0, 359)),
        )

    def _lag(self):
        time.sleep(0.03)

    def reset(self):
        pass

    def read(self) -> LampState:
        self._lag()
        return replace(self.state, updated=time.time())

    def set_power(self, on):
        self._lag()
        self.state.is_on = bool(on)

    def set_brightness(self, pct, current):
        self._lag()
        self.state.is_on, self.state.brightness = True, pct

    def set_temperature(self, pct, current):
        self._lag()
        self.state.is_on, self.state.mode, self.state.temperature = True, "white", pct

    def set_color(self, rgb, brightness):
        self._lag()
        self.state.is_on, self.state.mode = True, "colour"
        self.state.color, self.state.brightness = tuple(rgb), brightness

    def apply_scene(self, scene, current):
        if scene.mode == "colour":
            self.set_color(scene.color, scene.brightness)
        else:
            self._lag()
            self.state.is_on, self.state.mode = True, "white"
            self.state.brightness, self.state.temperature = scene.brightness, scene.temperature


def _clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


# ------------------------------------------------------ conexão ao vivo ---
class LiveBulb(threading.Thread):
    """Conexão permanente com uma lâmpada, numa thread própria.

    - Comandos são enviados sem esperar resposta (a lâmpada confirma depois,
      empurrando o novo estado) e a thread acorda na hora em que chegam.
    - Mudanças feitas por fora (Alexa, app, interruptor) chegam como
      notificações e atualizam o estado em tempo real.
    - Rajadas (arrastar um slider) são condensadas: só o valor mais recente
      de cada tipo de comando é enviado.
    """

    HEARTBEAT_S = 10     # mantém o TCP aberto (as lâmpadas fecham conexões ociosas)
    STALE_S = 35         # sem nenhum dado por esse tempo: reconecta
    EXPECT_S = 1.0       # janela em que ignoramos valores antigos que a lâmpada ainda reporta
    MIN_GAP_S = 0.08     # no máximo ~12 comandos/s: lâmpadas engasgam com rajadas maiores
    MAX_BACKOFF_S = 30

    def __init__(self, lamp: Lamp, on_state, on_version=None, port: int = 6668):
        super().__init__(daemon=True, name=f"lamp-{lamp.id}")
        self.lamp = lamp
        self.tuya = TuyaBulb(lamp, port)
        self.on_state = on_state
        self.on_version = on_version
        self.state = LampState()
        self._queue: "dict[str, tuple]" = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._want_status = False
        self._dps: dict = {}
        self._expect: dict = {}
        self._wake_r, self._wake_w = socket.socketpair()
        self._wake_r.setblocking(False)
        self._last_send = 0.0
        self._resync_at = 0.0    # quando pedir o estado real após descartar um valor

    @property
    def detected_version(self):
        return self.tuya.detected_version

    # -- API (chamada de qualquer thread) -------------------------------------
    def command(self, kind: str, value, current: LampState) -> None:
        with self._lock:
            self._queue.pop(kind, None)  # o mais novo substitui e vai para o fim da fila
            self._queue[kind] = (value, current)
        self._wake()

    def refresh(self) -> None:
        self._want_status = True
        self._wake()

    def stop(self) -> None:
        self._stop.set()
        self._wake()

    def _wake(self):
        try:
            self._wake_w.send(b"x")
        except OSError:
            pass

    # -- laço da thread ------------------------------------------------------
    def run(self):
        backoff = 1.0
        while not self._stop.is_set():
            if self.tuya._dev is None:
                try:
                    self._connect()
                    backoff = 1.0
                except Exception as exc:  # offline, chave errada, etc.
                    self._offline(exc)
                    self._sleep(backoff)  # um comando novo acorda antes e tenta de novo
                    backoff = min(backoff * 2, self.MAX_BACKOFF_S)
                    continue
            try:
                self._step()
            except Exception as exc:
                log.info("Lâmpada %s: conexão perdida (%s)", mask(self.lamp.device_id), exc)
                self._drop(exc)
        self.tuya.reset()
        self._wake_r.close()
        self._wake_w.close()

    def _connect(self):
        res = self.tuya.connect(persist=True)
        dev = self.tuya._dev
        dev.set_retry(False)            # não fica esperando após confirmações vazias
        dev.set_socketRetryLimit(1)
        dev.set_socketRetryDelay(0.2)
        self._dps = {str(k): v for k, v in res["dps"].items()}
        self._expect.clear()
        self._resync_at = 0.0
        self._last_rx = self._last_hb = time.monotonic()
        self._want_status = False
        if self.on_version and self.lamp.version == "auto":
            _notify(self.on_version, self.tuya.detected_version)
        self._emit()

    def _step(self):
        dev = self.tuya._dev
        self._flush(dev)
        now = time.monotonic()
        if self._resync_at and now >= self._resync_at:
            self._resync_at = 0.0
            self._want_status = True
        if self._want_status:
            self._want_status = False
            _check(dev.status(nowait=True))
        if now - self._last_hb >= self.HEARTBEAT_S:
            self._last_hb = now
            _check(dev.heartbeat(nowait=True))
        sock = dev.socket
        if sock is None:
            raise LampError("conexão fechada")
        timeout = 1.0
        if self._resync_at:
            timeout = min(timeout, max(0.0, self._resync_at - time.monotonic()))
        if self._queue:  # há comando esperando o intervalo mínimo
            timeout = max(0.0, self._last_send + self.MIN_GAP_S - time.monotonic())
        ready, _, _ = select.select([sock, self._wake_r], [], [], timeout)
        if self._wake_r in ready:
            self._drain_wake()
        if sock in ready:
            self._last_rx = time.monotonic()
            data = dev.receive()
            _check(data)
            if data:
                self._merge(data)
        elif time.monotonic() - self._last_rx > self.STALE_S:
            raise LampError("sem resposta")

    def _flush(self, dev):
        if time.monotonic() - self._last_send < self.MIN_GAP_S:
            return
        with self._lock:
            items = list(self._queue.items())
            self._queue.clear()
        for i, (kind, (value, current)) in enumerate(items):
            try:
                values = self.tuya.values(kind, value, current)
            except (LampError, ValueError) as exc:
                log.warning("Comando %s ignorado: %s", kind, exc)
                continue
            deadline = time.monotonic() + self.EXPECT_S
            for dp, v in values.items():
                self._expect[dp] = (v, deadline)
            self._dps.update(values)
            try:
                _check(dev.set_multiple_values(values, nowait=True))
                self._last_send = time.monotonic()
            except Exception:
                with self._lock:  # devolve à fila o que não foi enviado (se não foi substituído)
                    for k, v in items[i:]:
                        self._queue.setdefault(k, v)
                raise

    def _merge(self, data: dict):
        dps = data.get("dps")
        if dps is None and isinstance(data.get("data"), dict):
            dps = data["data"].get("dps")
        if not isinstance(dps, dict):
            return
        now = time.monotonic()
        for k, v in dps.items():
            k = str(k)
            exp = self._expect.get(k)
            if exp:
                if now < exp[1] and v != exp[0]:
                    # valor antigo de um comando já substituído (ou mudança externa
                    # bem nessa hora): ignora e confere o estado real ao fim da janela
                    self._resync_at = max(self._resync_at, exp[1])
                    continue
                del self._expect[k]
            self._dps[k] = v
        self._emit()

    def _emit(self):
        self.state = TuyaBulb._parse(self.tuya._dev, self._dps)
        _notify(self.on_state, self.state)

    def _offline(self, exc):
        self.state = replace(self.state, online=False, error=str(exc))
        _notify(self.on_state, self.state)

    def _drop(self, exc):
        self.tuya.reset()
        self._offline(exc)
        self._sleep(0.5)

    def _sleep(self, seconds: float):
        select.select([self._wake_r], [], [], seconds)
        self._drain_wake()

    def _drain_wake(self):
        try:
            while self._wake_r.recv(1024):
                pass
        except (BlockingIOError, OSError):
            pass


class FakeLiveBulb(threading.Thread):
    """Versão "ao vivo" da lâmpada simulada do modo --demo (mesma interface da LiveBulb)."""

    def __init__(self, lamp: Lamp, on_state, on_version=None, **_):
        super().__init__(daemon=True, name=f"fake-{lamp.id}")
        self.lamp = lamp
        self.bulb = FakeBulb(lamp)
        self.on_state = on_state
        self.detected_version = "3.3"
        self._q: "queue.Queue" = queue.Queue()

    def command(self, kind, value, current):
        self._q.put((kind, value, current))

    def refresh(self):
        self._q.put(("read", None, None))

    def stop(self):
        self._q.put(None)

    def run(self):
        _notify(self.on_state, self.bulb.read())
        while True:
            item = self._q.get()
            if item is None:
                return
            kind, value, current = item
            if kind == "power":
                self.bulb.set_power(value)
            elif kind == "brightness":
                self.bulb.set_brightness(value, current)
            elif kind == "temperature":
                self.bulb.set_temperature(value, current)
            elif kind == "color":
                self.bulb.set_color(value, current.brightness)
            elif kind == "scene":
                self.bulb.apply_scene(value, current)
            _notify(self.on_state, self.bulb.read())


def _notify(callback, *args):
    """Chama o callback da interface; ignora se ela já foi fechada."""
    try:
        callback(*args)
    except RuntimeError:  # objeto do Qt já destruído (app encerrando)
        pass


def _check(res):
    if isinstance(res, dict) and res.get("Error"):
        raise LampError(res["Error"])
    return res
