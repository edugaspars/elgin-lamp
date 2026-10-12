"""Criptografia do arquivo de configuração.

Windows: DPAPI (CryptProtectData), atrelado à conta do usuário. O arquivo
copiado para outro PC ou outra conta não pode ser lido.

Linux/macOS: Fernet (AES-128-CBC + HMAC) com a chave guardada no keyring do
sistema (Secret Service / KWallet / Keychain). Sem keyring disponível, a
chave fica num arquivo com permissão 0600 ao lado da configuração.
"""

import os
import sys
from pathlib import Path

_ENTROPY = b"lampdesk/config/v1"
_KEYRING_SERVICE = "lampdesk"
_KEYRING_USER = "config-key"
# Identificadores do nome anterior do app: só para ler configurações já existentes.
_LEGACY_ENTROPY = b"elgin-lamp/config/v1"
_LEGACY_KEYRING_SERVICE = "elgin-lamp"


class CryptoError(Exception):
    pass


# ---------------------------------------------------------------- Windows ---
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _CRYPTPROTECT_UI_FORBIDDEN = 0x01

    def _blob(data: bytes) -> _DataBlob:
        buf = ctypes.create_string_buffer(data, len(data))
        return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _take(blob: _DataBlob) -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            _kernel32.LocalFree(blob.pbData)

    def encrypt(data: bytes) -> bytes:
        src, ent, out = _blob(data), _blob(_ENTROPY), _DataBlob()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(src), "LampDesk", ctypes.byref(ent), None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out),
        )
        if not ok:
            raise CryptoError("CryptProtectData falhou")
        return b"DPAPI1" + _take(out)

    def decrypt(data: bytes) -> bytes:
        if not data.startswith(b"DPAPI1"):
            raise CryptoError("formato desconhecido")
        for entropy in (_ENTROPY, _LEGACY_ENTROPY):  # o próximo save já grava no formato novo
            src, ent, out = _blob(data[6:]), _blob(entropy), _DataBlob()
            ok = _crypt32.CryptUnprotectData(
                ctypes.byref(src), None, ctypes.byref(ent), None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out),
            )
            if ok:
                return _take(out)
        raise CryptoError("CryptUnprotectData falhou (arquivo de outro usuário/PC?)")

# ------------------------------------------------------------ Linux/macOS ---
else:
    def _key_file() -> Path:
        from .paths import data_dir
        return data_dir() / ".key"

    def _load_or_create_key() -> bytes:
        from cryptography.fernet import Fernet

        try:
            import keyring
            stored = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
            if stored:
                return stored.encode()
            legacy = keyring.get_password(_LEGACY_KEYRING_SERVICE, _KEYRING_USER)
            if legacy:  # chave gravada com o nome anterior do app: passa para o nome novo
                keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, legacy)
                try:
                    keyring.delete_password(_LEGACY_KEYRING_SERVICE, _KEYRING_USER)
                except Exception:  # noqa: BLE001
                    pass
                return legacy.encode()
            # Sem chave no keyring: migra a do arquivo, se houver, ou cria nova.
            kf = _key_file()
            key = kf.read_bytes().strip() if kf.exists() else Fernet.generate_key()
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, key.decode())
            if kf.exists():
                kf.unlink()
            return key
        except Exception:
            pass  # keyring ausente ou sem backend: usa o arquivo

        kf = _key_file()
        if kf.exists():
            return kf.read_bytes().strip()
        key = Fernet.generate_key()
        fd = os.open(kf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        return key

    def encrypt(data: bytes) -> bytes:
        from cryptography.fernet import Fernet
        return b"FERNET1" + Fernet(_load_or_create_key()).encrypt(data)

    def decrypt(data: bytes) -> bytes:
        from cryptography.fernet import Fernet, InvalidToken
        if not data.startswith(b"FERNET1"):
            raise CryptoError("formato desconhecido")
        try:
            return Fernet(_load_or_create_key()).decrypt(data[7:])
        except InvalidToken as exc:
            raise CryptoError("chave inválida para este arquivo") from exc


def mask(value: str, keep: int = 4) -> str:
    """Esconde dados sensíveis em logs/telas: 'bf12...a9c3' -> '••••a9c3'."""
    if not value:
        return ""
    value = str(value)
    return "•" * max(0, min(len(value) - keep, 8)) + value[-keep:]

