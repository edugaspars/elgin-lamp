"""Gera o executável com o PyInstaller (Windows: dist/LampDesk.exe; Linux: dist/LampDesk-linux-x86_64).

    python scripts/build.py           versão calculada pelo Git
    python scripts/build.py 1.2.0     versão explícita (usada pela release)
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
NAME = "LampDesk"


def main() -> int:
    from lampdesk import version

    v = sys.argv[1] if len(sys.argv) > 1 else (version.from_git() or "0.0.0")
    version.write(v)
    print(f"Versão: {v}")

    args = [
        "--noconfirm", "--clean", "--onefile", "--windowed", "--name", NAME, "--paths", str(ROOT),
        "--collect-submodules", "tinytuya", "--collect-submodules", "tuya_sharing",
        "--exclude-module", "tkinter", "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtQuick", "--exclude-module", "PySide6.Qt3DCore",
    ]
    if sys.platform == "win32":
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_icon.py")], check=True, env=env)
        args += ["--icon", str(ROOT / "build" / "icon.ico")]
    args.append(str(ROOT / "lampdesk" / "__main__.py"))

    import PyInstaller.__main__
    PyInstaller.__main__.run(args)

    dist = ROOT / "dist"
    if sys.platform == "win32":
        out = dist / f"{NAME}.exe"
    else:
        out = dist / f"{NAME}-{sys.platform}-{platform.machine().lower()}"
        shutil.move(str(dist / NAME), out)
    print(f"Pronto: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
