"""Onde o app guarda seus dados: sempre fora da pasta do projeto."""

import os
import shutil
import sys
from pathlib import Path

from . import APP_ID


# Nome anterior do app: a pasta antiga é movida para a nova na primeira execução.
LEGACY_APP_ID = "ElginLamp"
LEGACY_XDG_NAME = "elgin-lamp"


def _default_dir(app_id: str, xdg_name: str) -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / app_id
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_id
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / xdg_name


def _migrate_legacy(base: Path) -> None:
    legacy = _default_dir(LEGACY_APP_ID, LEGACY_XDG_NAME)
    if base.exists() or not legacy.is_dir():
        return
    try:
        shutil.move(str(legacy), str(base))
    except OSError:
        try:  # outro processo (a versão antiga aberta) segura a pasta: copia e deixa a antiga
            shutil.copytree(legacy, base)
        except OSError:
            pass


def data_dir() -> Path:
    """%APPDATA%\\LampDesk no Windows, ~/.config/lampdesk no Linux."""
    override = os.environ.get("LAMPDESK_HOME")
    if override:
        base = Path(override)
    else:
        base = _default_dir(APP_ID, "lampdesk")
        _migrate_legacy(base)
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
