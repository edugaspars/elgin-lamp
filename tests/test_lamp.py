"""Mapeamento dos comandos para DPs Tuya, sem rede (dispositivo falso)."""

import tinytuya

from elgin_lamp.lamp import LampState, TuyaBulb, display_rgb, rgb_from_hue, white_rgb
from elgin_lamp.storage import Lamp, Scene

TYPE_B_STATUS = {"20": True, "21": "white", "22": 500, "23": 250, "24": "00f003e803e8", "25": "", "26": 0}


class FakeDevice(tinytuya.BulbDevice):
    """BulbDevice real (para usar o detect_bulb do tinytuya), mas sem socket."""

    def __init__(self, dps):
        super().__init__("dev", "127.0.0.1", "0" * 16, version=3.3)
        self.dps = dict(dps)
        self.sent = []

    def status(self, nowait=False):
        return {"dps": dict(self.dps)}

    def set_multiple_values(self, data, nowait=False):
        self.sent.append(data)
        self.dps.update(data)
        return {"dps": data}


def make_bulb(dps=TYPE_B_STATUS):
    bulb = TuyaBulb(Lamp("Sala", "dev", "127.0.0.1", "0" * 16))
    dev = FakeDevice(dps)
    dev.detect_bulb({"dps": dps})
    bulb._dev = dev
    return bulb, dev


def test_parse_type_b_white():
    bulb, _ = make_bulb()
    st = bulb.read()
    assert st.online and st.is_on and st.mode == "white"
    assert st.brightness == 50
    assert st.temperature == 25
    assert st.has_colour and st.has_temperature


def test_parse_colour_mode_uses_hsv_value_for_brightness():
    dps = dict(TYPE_B_STATUS, **{"21": "colour", "24": tinytuya.BulbDevice.hsv_to_hexvalue(0.5, 1, 0.4, "hsv16")})
    bulb, _ = make_bulb(dps)
    st = bulb.read()
    assert st.mode == "colour"
    assert st.brightness == 40
    assert st.color == (0, 255, 255)


def test_power_sends_switch_dp():
    bulb, dev = make_bulb()
    bulb.set_power(False)
    assert dev.sent[-1] == {"20": False}


def test_brightness_white_scales_to_device_range():
    bulb, dev = make_bulb()
    bulb.set_brightness(1, LampState(mode="white"))
    assert dev.sent[-1]["22"] == 10  # value_min do tipo B
    bulb.set_brightness(100, LampState(mode="white"))
    assert dev.sent[-1]["22"] == 1000


def test_brightness_in_colour_mode_keeps_hue():
    bulb, dev = make_bulb()
    bulb.set_brightness(30, LampState(mode="colour", color=(255, 0, 0)))
    h, s, v = tinytuya.BulbDevice.hexvalue_to_hsv(dev.sent[-1]["24"], "hsv16")
    assert round(h, 2) == 0 and s == 1 and round(v, 2) == 0.3


def test_temperature_allows_zero():
    bulb, dev = make_bulb()
    bulb.set_temperature(0, LampState(brightness=80))
    assert dev.sent[-1]["23"] == 0
    assert dev.sent[-1]["21"] == "white"


def test_colour_type_a_rgb8_does_not_crash():
    # Tipo A usa o formato rgb8, onde o tinytuya quebra com float
    dps = {"1": True, "2": "colour", "3": 200, "4": 100, "5": "ff00000000ffff"}
    bulb, dev = make_bulb(dps)
    bulb.set_color((0, 128, 255), 50)
    assert dev.sent[-1]["2"] == "colour"
    assert len(dev.sent[-1]["5"]) == 14


def test_scene_white():
    bulb, dev = make_bulb()
    bulb.apply_scene(Scene("Leitura", "white", 90, 55), LampState())
    assert dev.sent[-1] == {"20": True, "21": "white", "22": 900, "23": 550}


def test_display_colors():
    assert white_rgb(0) == (255, 176, 92)
    assert rgb_from_hue(120) == (0, 255, 0)
    assert display_rgb(LampState(mode="colour", color=(1, 2, 3))) == (1, 2, 3)
