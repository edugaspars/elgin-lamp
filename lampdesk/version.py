"""Versão do app, calculada a partir das tags do Git.

Regra: cada merge na main publica uma release com o minor seguinte
(v1.0.0, v1.1.0, v1.2.0…), e cada commit depois da última tag soma 1 ao
patch (1.1.0 → 1.1.1 → 1.1.2…). O minor novo zera o patch.

O executável não tem Git: o build grava a versão em `_version.py`.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
FIRST_RELEASE = "1.0.0"
_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _git(*args: str, cwd: Path = ROOT) -> Optional[str]:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def parse(tag: str) -> Optional[Tuple[int, int, int]]:
    m = _TAG.match(tag.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def latest_tag(cwd: Path = ROOT) -> Optional[Tuple[int, int, int]]:
    tags = (_git("tag", "--list", "v*", cwd=cwd) or "").split()
    versions = [v for v in (parse(t) for t in tags) if v]
    return max(versions) if versions else None


def from_git(cwd: Path = ROOT) -> Optional[str]:
    """Versão do commit atual: última tag + número de commits desde ela."""
    desc = _git("describe", "--tags", "--long", "--match", "v[0-9]*", cwd=cwd)
    if desc:
        tag, count, _sha = desc.rsplit("-", 2)
        base = parse(tag)
        if base:
            return f"{base[0]}.{base[1]}.{base[2] + int(count)}"
    if _git("rev-parse", "HEAD", cwd=cwd):
        return f"{FIRST_RELEASE}-dev"  # ainda sem nenhuma release
    return None


def next_release(cwd: Path = ROOT) -> str:
    """Versão da próxima release (o próximo merge): minor + 1, patch zerado."""
    last = latest_tag(cwd)
    return f"{last[0]}.{last[1] + 1}.0" if last else FIRST_RELEASE


def get() -> str:
    try:
        from ._version import VERSION  # gravado pelo build
        return VERSION
    except ImportError:
        pass
    if getattr(sys, "frozen", False):
        return "0.0.0"
    return from_git() or "0.0.0"


def write(version: str) -> Path:
    path = Path(__file__).with_name("_version.py")
    path.write_text(f'VERSION = "{version}"\n', encoding="utf-8")
    return path
