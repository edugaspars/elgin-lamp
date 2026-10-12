"""Efeitos nativos do Windows (DWM): barra de título escura e fundo Mica.

Tudo aqui é opcional: se a chamada falhar (Windows 10, DWM desligado, outro
sistema), a janela continua com o fundo sólido do tema.
"""

import ctypes
import logging
import sys

log = logging.getLogger(__name__)

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20      # Windows 10 20H1+ (19 em versões anteriores)
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
_DWMWA_SYSTEMBACKDROP_TYPE = 38          # Windows 11 22H2+
_DWMSBT_NONE = 1
_DWMSBT_MAINWINDOW = 2                   # Mica


def _build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:  # noqa: BLE001
        return 0


def mica_supported() -> bool:
    return _build() >= 22621


def _set(hwnd: int, attr: int, value: int) -> bool:
    v = ctypes.c_int(value)
    res = ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                                                     ctypes.byref(v), ctypes.sizeof(v))
    return res == 0


def set_dark_title(widget, dark: bool) -> bool:
    """Barra de título clara/escura conforme o tema."""
    build = _build()
    if build < 17763:
        return False
    try:
        hwnd = int(widget.winId())
        attr = _DWMWA_USE_IMMERSIVE_DARK_MODE if build >= 18985 else _DWMWA_USE_IMMERSIVE_DARK_MODE_OLD
        return _set(hwnd, attr, 1 if dark else 0)
    except Exception:  # noqa: BLE001
        log.debug("DWM: falha ao ajustar a barra de título", exc_info=True)
        return False


def set_mica(widget, enabled: bool) -> bool:
    """Liga/desliga o fundo Mica. A janela precisa de WA_TranslucentBackground desde a criação."""
    if not mica_supported():
        return False
    try:
        hwnd = int(widget.winId())

        class MARGINS(ctypes.Structure):
            _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int),
                        ("top", ctypes.c_int), ("bottom", ctypes.c_int)]

        m = MARGINS(-1, -1, -1, -1) if enabled else MARGINS(0, 0, 0, 0)
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(ctypes.c_void_p(hwnd), ctypes.byref(m))
        return _set(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_MAINWINDOW if enabled else _DWMSBT_NONE) and enabled
    except Exception:  # noqa: BLE001
        log.debug("DWM: falha ao aplicar Mica", exc_info=True)
        return False
