"""Comunicação local com as lâmpadas (protocolo Tuya, usado pelas lâmpadas Elgin).

Nada aqui depende de Qt: dá para usar como biblioteca/script também.
"""

import colorsys
import logging
import random
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
    """Envolve tinytuya.BulbDevice enviando só um pacote por comando."""

    def __init__(self, lamp: Lamp):
        self.lamp = lamp
        self.detected_version: Optional[str] = None
        self._dev = None

    # -- conexão -------------------------------------------------------------
    def _make(self, version: str):
        import tinytuya

        dev = tinytuya.BulbDevice(
            self.lamp.device_id, self.lamp.ip, self.lamp.local_key,
            version=float(version), connection_timeout=3,
            connection_retry_limit=1, connection_retry_delay=1,
        )
        dev.set_socketPersistent(False)
        return dev

    def _device(self):
        if self._dev is not None:
            return self._dev
        versions = [self.lamp.version] if self.lamp.version != "auto" else AUTO_VERSIONS
        last_err = "sem resposta"
        for v in versions:
            dev = self._make(v)
            res = dev.status()
            if res and "dps" in res and not res.get("Error"):
                dev.detect_bulb(res)
                self._dev = dev
                self.detected_version = v
                log.info("Lâmpada %s conectada (protocolo %s)", mask(self.lamp.device_id), v)
                return dev
            last_err = (res or {}).get("Error", last_err)
            if (res or {}).get("Err") in ("901", "905"):
                break  # nem conectou: trocar de versão não adianta
        raise LampError(last_err)

    def reset(self):
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

    # -- escrita -------------------------------------------------------------
    def _send(self, values: dict) -> None:
        dev = self._device()
        data = {str(k): v for k, v in values.items() if k}
        res = dev.set_multiple_values(data)
        if isinstance(res, dict) and res.get("Error"):
            self.reset()
            raise LampError(res["Error"])

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

    def set_power(self, on: bool) -> None:
        dev = self._device()
        self._send({dev.dpset["switch"] or 1: bool(on)})

    def set_brightness(self, pct: int, current: LampState) -> None:
        ds = self._device().dpset
        if current.mode == "colour" and ds["colour"]:
            self._send({ds["switch"]: True, ds["colour"]: self._colour_hex(current.color, pct)})
        else:
            self._send({ds["switch"]: True, ds["mode"]: "white", ds["brightness"]: self._scale(pct)})

    def set_temperature(self, pct: int, current: LampState) -> None:
        ds = self._device().dpset
        if not ds["colourtemp"]:
            raise LampError("sem suporte a temperatura de cor")
        self._send({ds["switch"]: True, ds["mode"]: "white",
                    ds["brightness"]: self._scale(current.brightness),
                    ds["colourtemp"]: self._scale(pct, floor=False)})

    def set_color(self, rgb, brightness: int) -> None:
        ds = self._device().dpset
        if not ds["colour"]:
            raise LampError("sem suporte a cor")
        self._send({ds["switch"]: True, ds["mode"]: "colour", ds["colour"]: self._colour_hex(rgb, brightness)})

    def apply_scene(self, scene: Scene, current: LampState) -> None:
        if scene.mode == "colour" and self._device().dpset["colour"]:
            self.set_color(scene.color, scene.brightness)
        else:
            ds = self._device().dpset
            values = {ds["switch"]: True, ds["mode"]: "white", ds["brightness"]: self._scale(scene.brightness)}
            if ds["colourtemp"]:
                values[ds["colourtemp"]] = self._scale(scene.temperature, floor=False)
            self._send(values)


# --------------------------------------------------------- modo de demo ---
class FakeBulb:
    """Lâmpada simulada (python -m elgin_lamp --demo) para testar sem hardware."""

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
        time.sleep(0.08)

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
