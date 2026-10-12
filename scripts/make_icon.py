"""Gera build/icon.ico (ícone do .exe) a partir do mesmo desenho da bandeja."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ELGIN_LAMP_HOME", str(ROOT / "build" / "tmp-home"))


def main():
    from PIL import Image
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
    from PySide6.QtWidgets import QApplication

    app = QApplication([])  # QPixmap exige uma QApplication
    from elgin_lamp.ui import icons

    size = 256
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    bg = QPainterPath()
    bg.addRoundedRect(QRectF(8, 8, size - 16, size - 16), 56, 56)
    p.fillPath(bg, QColor(18, 18, 18))
    glass = QPainterPath()
    glass.addEllipse(QRectF(78, 46, 100, 100))
    p.fillPath(glass, QColor(255, 196, 107))
    icons.paint(p, "bulb", QRectF(28, 28, 200, 200), QColor(255, 226, 170), 1.6)
    p.end()

    out = ROOT / "build"
    out.mkdir(exist_ok=True)
    png = out / "icon.png"
    pm.save(str(png))
    Image.open(png).save(out / "icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print(f"ok: {out / 'icon.ico'}")
    app.quit()


if __name__ == "__main__":
    main()
