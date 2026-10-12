"""Iniciar junto com o sistema (Windows: registro HKCU\\...\\Run; Linux: XDG autostart)."""

import os
import sys
from pathlib import Path

from . import APP_ID, APP_NAME

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _command() -> str:
    if getattr(sys, "frozen", False):  # .exe gerado pelo PyInstaller
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if sys.platform == "win32" and pythonw.exists():
        exe = pythonw
    return f'"{exe}" -m elgin_lamp'


def _desktop_file() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "autostart" / "elgin-lamp.desktop"


def is_enabled() -> bool:
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.QueryValueEx(key, APP_ID)
                return True
        except OSError:
            return False
    return _desktop_file().exists()


def set_enabled(enabled: bool) -> None:
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(key, APP_ID)
                except FileNotFoundError:
                    pass
        return

    f = _desktop_file()
    if enabled:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            "[Desktop Entry]\nType=Application\n"
            f"Name={APP_NAME}\nExec={_command()}\n"
            "X-GNOME-Autostart-enabled=true\nTerminal=false\n",
            encoding="utf-8",
        )
    elif f.exists():
        f.unlink()
