"""Linha de comando: liga/desliga usando as lâmpadas já salvas no app.

    python -m lampdesk.cli status
    python -m lampdesk.cli on --lamp Sala
    python -m lampdesk.cli off
    python -m lampdesk.cli brightness 40 --lamp Quarto

IP, Device ID e Local Key vêm da configuração criptografada; nada aparece no comando.
"""

import argparse
import sys

from .lamp import LampError, LampState, TuyaBulb
from .storage import Store


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m lampdesk.cli")
    ap.add_argument("action", choices=["status", "on", "off", "toggle", "brightness"])
    ap.add_argument("value", nargs="?", type=int, help="1-100 para 'brightness'")
    ap.add_argument("--lamp", help="nome da lâmpada (padrão: todas)")
    args = ap.parse_args(argv)

    store = Store()
    cfg = store.load()
    lamps = [l for l in cfg.lamps if not args.lamp or l.name.casefold() == args.lamp.casefold()]
    if not lamps:
        print("Nenhuma lâmpada encontrada. Cadastre pelo app (Configurações › Lâmpadas).", file=sys.stderr)
        return 2
    if args.action == "brightness" and not (args.value and 1 <= args.value <= 100):
        print("Informe um brilho de 1 a 100.", file=sys.stderr)
        return 2

    code = 0
    for lamp in lamps:
        bulb = TuyaBulb(lamp)
        try:
            st = bulb.read()
            if args.action == "on" or (args.action == "toggle" and not st.is_on):
                bulb.set_power(True)
            elif args.action in ("off", "toggle"):
                bulb.set_power(False)
            elif args.action == "brightness":
                bulb.set_brightness(args.value, st)
            if args.action != "status":
                st = bulb.read()
            print(f"{lamp.name}: {_describe(st)}")
        except LampError as exc:
            print(f"{lamp.name}: sem conexão ({exc})", file=sys.stderr)
            code = 1
    return code


def _describe(st: LampState) -> str:
    if not st.is_on:
        return "desligada"
    if st.mode == "colour":
        return "ligada, cor #%02X%02X%02X, %d%%" % (*st.color, st.brightness)
    return f"ligada, branco {st.temperature}%, brilho {st.brightness}%"


if __name__ == "__main__":
    sys.exit(main())
