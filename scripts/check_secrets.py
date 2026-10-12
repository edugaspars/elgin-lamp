"""Bloqueia commits que vazariam IPs locais, chaves ou arquivos do tinytuya.

Uso:
    python scripts/check_secrets.py            # verifica os arquivos staged (hook)
    python scripts/check_secrets.py --all      # verifica o repositório inteiro (CI)
"""

import re
import subprocess
import sys
from pathlib import Path

# IPs que aparecem de propósito na documentação e nos testes.
ALLOWED_IPS = {"192.168.0.10", "127.0.0.1", "0.0.0.0"}

FORBIDDEN_FILES = {"devices.json", "tinytuya.json", "snapshot.json", "tuya-raw.json", ".env", ".key"}
FORBIDDEN_SUFFIXES = {".dat"}

PRIVATE_IP = re.compile(
    r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"
)
LOCAL_KEY = re.compile(r"""(?i)local_?key["']?\s*[:=]\s*["']([^"'\s]{16})["']""")


def files(all_files: bool):
    cmd = ["git", "ls-files"] if all_files else ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return [Path(p) for p in out.splitlines() if p]


def scan(path: Path):
    problems = []
    if path.name in FORBIDDEN_FILES or path.suffix in FORBIDDEN_SUFFIXES:
        return [f"{path}: arquivo com dados sensíveis não deve ser versionado"]
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return []
    for n, line in enumerate(text.splitlines(), 1):
        for ip in PRIVATE_IP.findall(line):
            if ip not in ALLOWED_IPS:
                problems.append(f"{path}:{n}: IP local {ip}")
        for key in LOCAL_KEY.findall(line):
            if len(set(key)) > 2:  # ignora placeholders como "0000000000000000"
                problems.append(f"{path}:{n}: parece um Local Key")
    return problems


def main() -> int:
    problems = []
    for f in files("--all" in sys.argv):
        problems += scan(f)
    if problems:
        print("Possível vazamento de dados (commit bloqueado):")
        for p in problems:
            print("  " + p)
        print("\nUse 192.168.0.10 nos exemplos. Seus dados reais ficam só no app (%APPDATA%).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
