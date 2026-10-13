import json
import sys

import pytest

from lampdesk import crypto
from lampdesk.i18n import tr
from lampdesk.storage import Config, Lamp, Location, Routine, Store, default_scenes


def test_encrypt_roundtrip():
    blob = crypto.encrypt(b"segredo")
    assert blob != b"segredo"
    assert crypto.decrypt(blob) == b"segredo"


def test_config_file_never_contains_plaintext(tmp_path):
    store = Store(tmp_path / "config.dat")
    store.config.lamps.append(Lamp("Sala", "bf1234567890abcdef", "192.0.2.10", "0123456789abcdef"))
    store.save()
    raw = (tmp_path / "config.dat").read_bytes()
    for secret in (b"192.0.2.10", b"0123456789abcdef", b"bf1234567890abcdef", b"Sala"):
        assert secret not in raw


def test_appearance_settings(tmp_path):
    store = Store(tmp_path / "config.dat")
    assert store.config.settings.theme == "dark"  # padrão
    store.config.settings.theme = "light"
    store.config.settings.reduce_transparency = True
    store.save()
    loaded = Store(tmp_path / "config.dat").load()
    assert loaded.settings.theme == "light"
    assert loaded.settings.reduce_transparency is True
    assert Config.from_dict({"settings": {"theme": "neon"}}).settings.theme == "dark"


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path / "config.dat")
    store.config.lamps.append(Lamp("Sala", "id1", "192.0.2.10", "k" * 16, version="3.3"))
    store.config.scenes = default_scenes(tr)
    store.config.routines.append(Routine("Acordar", time="06:30", days=[0, 1, 2, 3, 4]))
    store.config.settings.location = Location("São Paulo - SP", -23.55, -46.63)
    store.save()

    loaded = Store(tmp_path / "config.dat").load()
    assert loaded.lamps[0].ip == "192.0.2.10"
    assert loaded.lamps[0].version == "3.3"
    assert loaded.routines[0].days == [0, 1, 2, 3, 4]
    assert loaded.settings.location.is_set
    assert len(loaded.scenes) == len(default_scenes(tr))


def test_unreadable_config_is_backed_up(tmp_path):
    path = tmp_path / "config.dat"
    path.write_bytes(b"lixo")
    store = Store(path)
    cfg = store.load()
    assert cfg.lamps == []
    assert store.load_error
    assert list(tmp_path.glob("config.unreadable-*.dat"))


def test_from_dict_ignores_unknown_fields():
    cfg = Config.from_dict({"lamps": [{"name": "a", "device_id": "b", "ip": "c", "local_key": "d", "x": 1}]})
    assert cfg.lamps[0].name == "a"


@pytest.mark.skipif(sys.platform == "win32", reason="permissão POSIX")
def test_key_file_is_private(isolated_home):
    crypto.encrypt(b"x")
    key = isolated_home / "home" / ".key"
    assert key.exists()
    assert oct(key.stat().st_mode & 0o777) == "0o600"


def test_mask_hides_most_of_value():
    assert crypto.mask("0123456789abcdef").endswith("cdef")
    assert "0123" not in crypto.mask("0123456789abcdef")
    assert json.dumps(crypto.mask("")) == '""'
