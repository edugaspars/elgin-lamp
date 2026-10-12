import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Nunca toca na configuração real do usuário durante os testes."""
    monkeypatch.setenv("ELGIN_LAMP_HOME", str(tmp_path / "home"))
    # sem keyring nos testes: força o caminho do arquivo de chave
    monkeypatch.setitem(sys.modules, "keyring", None)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return tmp_path
