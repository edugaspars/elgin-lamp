"""Onde o app guarda seus dados: sempre fora da pasta do projeto."""

import os
import sys
from pathlib import Path

from . import APP_ID


def _default_dir(app_id: str, xdg_name: str) -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / app_id
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_id
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / xdg_name


def data_dir() -> Path:
    """%APPDATA%\\LampDesk no Windows, ~/.config/lampdesk no Linux."""
    override = os.environ.get("LAMPDESK_HOME")
    if override:
        base = Path(override)
    else:
        base = _default_dir(APP_ID, "lampdesk")
    base.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        try:
            os.chmod(base, 0o700)
        except OSError:
            pass
    return base


def config_file() -> Path:
    return data_dir() / "config.dat"


def log_file() -> Path:
    return data_dir() / "lampdesk.log"
