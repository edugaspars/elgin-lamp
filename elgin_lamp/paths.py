"""Onde o app guarda seus dados: sempre fora da pasta do projeto."""

import os
import sys
from pathlib import Path

from . import APP_ID


def data_dir() -> Path:
    """%APPDATA%\\ElginLamp no Windows, ~/.config/elgin-lamp no Linux."""
    override = os.environ.get("ELGIN_LAMP_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_ID
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_ID
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        base = Path(xdg) / "elgin-lamp"
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
    return data_dir() / "elgin-lamp.log"
