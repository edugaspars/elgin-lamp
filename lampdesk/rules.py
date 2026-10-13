"""Lógica das automações sem Qt: condições, notificações, ciclo do dia, cores e atalhos.

O motor que liga isso às lâmpadas fica em `automation.py`.
"""

import colorsys
import datetime as dt
import re
from typing import Iterable, List, Optional, Sequence, Tuple

from .storage import Location, Rule

# Gatilhos de "estado" duram um tempo (ex.: PC bloqueado); ao terminar, a luz volta.
STATE_TRIGGERS = ("away", "fullscreen")
EVENT_TRIGGERS = ("time", "sunrise", "sunset", "startup", "shutdown", "notification", "hotkey")
TRIGGERS = STATE_TRIGGERS + EVENT_TRIGGERS

# Ações que só "pintam" a lâmpada (podem durar enquanto um estado durar).
LOOK_ACTIONS = ("on", "off", "scene", "color", "brightness")
ACTIONS = LOOK_ACTIONS + ("toggle", "brightness_step", "blink", "fade_in", "fade_out", "off_later",
                          "pomodoro", "discord_mode", "circadian", "music")

MODES = ("discord",)


def parse_hhmm(text: str) -> Optional[dt.time]:
    try:
        hh, mm = (int(x) for x in text.split(":"))
        return dt.time(hh, mm)
    except (ValueError, AttributeError):
        return None


def in_window(now: dt.datetime, start: str, end: str) -> bool:
    """Se `now` está entre start e end (HH:MM). Aceita janelas que passam da meia-noite."""
    a, b = parse_hhmm(start), parse_hhmm(end)
    if a is None or b is None or a == b:
        return True
    t = now.time().replace(second=0, microsecond=0)
    return a <= t < b if a < b else (t >= a or t < b)


def is_dark(now: dt.datetime, location: Location) -> bool:
    """Entre o pôr e o nascer do sol (sem localização: das 18h às 6h)."""
    from .scheduler import sun_times

    sun = sun_times(location, now.date(), now.tzinfo)
    if not sun:
        return in_window(now, "18:00", "06:00")
    rise, set_ = sun
    return now < rise or now >= set_


def conditions_ok(rule: Rule, now: dt.datetime, location: Location, modes: Iterable[str] = ()) -> bool:
    if not rule.enabled:
        return False
    if now.weekday() not in rule.days:
        return False
    if not in_window(now, rule.window_from, rule.window_to):
        return False
    if rule.only_dark and not is_dark(now, location):
        return False
    if rule.mode and rule.mode not in set(modes):
        return False
    return True


def paused(pause_until: str, today: dt.date) -> bool:
    """Férias: rotinas pausadas até `pause_until` (inclusive)."""
    try:
        return today <= dt.date.fromisoformat(pause_until)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------- notificações ---
def _alternatives(text: str) -> List[str]:
    return [t.strip().casefold() for t in text.split("|") if t.strip()]


def notification_matches(rule: Rule, app_id: str, text: str) -> bool:
    """`app_id` é o identificador do Windows (ex.: com.squirrel.Discord.Discord)."""
    app = app_id.casefold()
    if rule.apps and not any(a.strip().casefold() in app for a in rule.apps if a.strip()):
        return False
    body = text.casefold()
    wanted = _alternatives(rule.text)
    if wanted and not any(w in body for w in wanted):
        return False
    if any(w in body for w in _alternatives(rule.exclude)):
        return False
    return True


def toast_text(payload: str) -> str:
    """Junta os <text> do XML de uma notificação do Windows."""
    texts = re.findall(r"<text[^>]*>(.*?)</text>", payload or "", flags=re.S | re.I)
    out = " · ".join(t.strip() for t in texts if t.strip())
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&")):
        out = out.replace(a, b)
    return out


# ---------------------------------------------------------- ciclo do dia ---
def _smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def circadian_level(now: dt.datetime, location: Location) -> float:
    """0 = noite (luz quente) .. 1 = meio do dia (luz fria), com transições suaves."""
    from .scheduler import sun_times

    sun = sun_times(location, now.date(), now.tzinfo)
    if sun:
        rise, set_ = sun
    else:
        base = dt.datetime.combine(now.date(), dt.time(0), tzinfo=now.tzinfo)
        rise, set_ = base + dt.timedelta(hours=6, minutes=30), base + dt.timedelta(hours=18, minutes=30)
    up = _smooth((now - rise) / dt.timedelta(hours=2.5))                    # esfria depois do nascer
    down = _smooth((now - (set_ - dt.timedelta(hours=1.5))) / dt.timedelta(hours=3))  # esquenta no fim da tarde
    return max(0.0, min(1.0, up - down))


def circadian_look(now: dt.datetime, location: Location, night_brightness: int = 40) -> Tuple[int, int]:
    """(temperatura 0..100, brilho 1..100) para este momento."""
    lvl = circadian_level(now, location)
    temperature = round(8 + 82 * lvl)  # nunca o extremo: 8 (bem quente) .. 90 (frio)
    brightness = round(night_brightness + (100 - night_brightness) * lvl)
    return temperature, max(1, min(100, brightness))


# ----------------------------------------------------------------- cores ---
def vivid_color(pixels: Sequence[Tuple[int, int, int]], bins: int = 24) -> Optional[Tuple[int, int, int]]:
    """Cor predominante e "viva" de uma imagem (capa do álbum, tela).

    Pixels cinza ou escuros quase não contam. Retorna None se a imagem não tem cor
    (preto e branco, tela escura), para a luz manter a cor anterior.
    """
    weight = [0.0] * bins
    acc = [[0.0, 0.0, 0.0] for _ in range(bins)]
    total = 0.0
    for r, g, b in pixels:
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        total += 1
        if s < 0.18 or v < 0.16:
            continue
        w = s * v
        i = int(h * bins) % bins
        weight[i] += w
        acc[i][0] += r * w
        acc[i][1] += g * w
        acc[i][2] += b * w
    if not total:
        return None
    best = max(range(bins), key=lambda i: weight[i] + 0.5 * (weight[i - 1] + weight[(i + 1) % bins]))
    group = [(best - 1) % bins, best, (best + 1) % bins]
    w = sum(weight[i] for i in group)
    if w / total < 0.02:
        return None
    r, g, b = (sum(acc[i][c] for i in group) / w for c in range(3))
    h, s, _v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    r, g, b = colorsys.hsv_to_rgb(h, max(s, 0.65), 1.0)  # a lâmpada fica bonita com cor saturada
    return round(r * 255), round(g * 255), round(b * 255)


def color_distance(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


# --------------------------------------------------------------- atalhos ---
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

_NAMED_KEYS = {
    "space": 0x20, "pgup": 0x21, "pgdown": 0x22, "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26,
    "right": 0x27, "down": 0x28, "ins": 0x2D, "insert": 0x2D, "del": 0x2E, "delete": 0x2E, "pause": 0x13,
    "+": 0xBB, "=": 0xBB, "-": 0xBD, ",": 0xBC, ".": 0xBE, ";": 0xBA, "/": 0xBF, "`": 0xC0,
    "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
    "media play": 0xB3, "media next": 0xB0, "media previous": 0xB1, "media stop": 0xB2,
}


def parse_hotkey(text: str) -> Optional[Tuple[int, int]]:
    """"Ctrl+Alt+L" -> (modificadores, tecla virtual) para RegisterHotKey do Windows."""
    if not text:
        return None
    parts = [p.strip() for p in re.split(r"\+(?!$)", text.strip())]
    mods, key = 0, None
    for part in parts:
        low = part.casefold()
        if low in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif low == "alt":
            mods |= MOD_ALT
        elif low == "shift":
            mods |= MOD_SHIFT
        elif low in ("meta", "win"):
            mods |= MOD_WIN
        elif key is None:
            key = low
        else:
            return None
    if key is None:
        return None
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif re.fullmatch(r"f([1-9]|1\d|2[0-4])", key):
        vk = 0x6F + int(key[1:])
    elif key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    else:
        return None
    return mods, vk
