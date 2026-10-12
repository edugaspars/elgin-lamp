"""Mostra ou grava a versão do app (veja lampdesk/version.py para a regra).

    python scripts/version.py                 versão do commit atual (ex.: 1.1.3)
    python scripts/version.py --next-release  versão da próxima release (ex.: 1.2.0)
    python scripts/version.py --write [X.Y.Z] grava lampdesk/_version.py para o build
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lampdesk import version  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--next-release", action="store_true")
    ap.add_argument("--write", nargs="?", const="", metavar="X.Y.Z")
    args = ap.parse_args()
    if args.next_release:
        print(version.next_release())
        return 0
    if args.write is not None:
        v = args.write or version.from_git() or "0.0.0"
        if args.write and not version.parse("v" + v):
            ap.error(f"versão inválida: {v}")
        version.write(v)
        print(v)
        return 0
    print(version.from_git() or "0.0.0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
