"""Encontrar lâmpadas: varredura da rede local e importação de chaves da nuvem Tuya."""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

TUYA_REGIONS = ["us", "eu", "cn", "in", "us-e", "eu-w", "sg"]


@dataclass
class Found:
    device_id: str
    ip: str = ""
    version: str = "auto"
    name: str = ""
    local_key: str = ""


def scan_lan(seconds: int = 18) -> List[Found]:
    """Escuta os anúncios UDP das lâmpadas na rede local (não precisa de chave)."""
    import tinytuya

    devices: Dict[str, dict] = tinytuya.deviceScan(
        verbose=False, maxretry=seconds, color=False, poll=False, byID=True
    ) or {}
    out = []
    for dev_id, info in devices.items():
        ver = str(info.get("version") or "auto")
        out.append(Found(device_id=dev_id, ip=info.get("ip", ""), version=ver if ver != "0" else "auto"))
    return out


def import_cloud(region: str, api_key: str, api_secret: str, any_device_id: str) -> List[Found]:
    """Busca nome e Local Key de todas as lâmpadas da conta (Tuya IoT Platform).

    As credenciais da nuvem são usadas só nesta chamada e não são salvas.
    """
    import tinytuya

    cloud = tinytuya.Cloud(apiRegion=region, apiKey=api_key, apiSecret=api_secret,
                           apiDeviceID=any_device_id, configFile=None)
    if cloud.error:
        raise RuntimeError(_cloud_err(cloud.error))
    devices = cloud.getdevices(verbose=False)
    if isinstance(devices, dict) and devices.get("Error"):
        raise RuntimeError(_cloud_err(devices))
    return [
        Found(device_id=d.get("id", ""), name=d.get("name", ""), local_key=d.get("key", ""))
        for d in devices or [] if d.get("id") and d.get("key")
    ]


# Login por QR Code com o app Smart Life / Tuya Smart. Usa o mesmo cliente
# que a integração oficial do Home Assistant (tuya-device-sharing-sdk), que
# dispensa conta de desenvolvedor na Tuya. A Tuya pode desativá-lo no futuro.
SMARTLIFE_CLIENT_ID = "HA_3y9q4ak7g4ephrvke"
SMARTLIFE_SCHEMA = "haauthorize"


class SmartLifeLogin:
    """Fluxo: start() -> mostra o QR -> poll() até logar -> fetch()."""

    def __init__(self, user_code: str):
        from tuya_sharing import LoginControl

        self.user_code = user_code.strip()
        self._control = LoginControl()
        self._token = ""

    def start(self) -> str:
        """Retorna o conteúdo do QR Code a ser escaneado pelo app."""
        res = self._control.qr_code(SMARTLIFE_CLIENT_ID, SMARTLIFE_SCHEMA, self.user_code)
        if not res.get("success"):
            raise RuntimeError(res.get("msg") or res.get("code") or "falha ao gerar QR Code")
        result = res.get("result") or {}
        self._token = result.get("qrcode") or result.get("token") or ""
        if not self._token:
            raise RuntimeError("resposta inesperada da Tuya")
        return f"tuyaSmart--qrLogin?token={self._token}"

    def poll(self) -> Optional[dict]:
        """Dados de login depois que o QR foi escaneado e confirmado; senão None."""
        ok, info = self._control.login_result(self._token, SMARTLIFE_CLIENT_ID, self.user_code)
        return info if ok else None

    def fetch(self, info: dict) -> List[Found]:
        """Lista os dispositivos da conta (com Local Key) e encerra a sessão."""
        from tuya_sharing import Manager

        token = {k: info.get(k) for k in ("t", "uid", "expire_time", "access_token", "refresh_token")}
        manager = Manager(SMARTLIFE_CLIENT_ID, self.user_code, info.get("terminal_id", ""),
                          info.get("endpoint", ""), token)
        try:
            manager.update_device_cache()
            devices = list(manager.device_map.values())
        finally:
            try:
                manager.unload()  # invalida o token: nada fica logado
            except Exception:
                log.debug("Não foi possível encerrar a sessão do Smart Life", exc_info=True)
        # o "ip" retornado pela nuvem é o IP público; o local vem da busca na rede
        return [Found(device_id=d.id, name=d.name, local_key=d.local_key)
                for d in devices if getattr(d, "local_key", "")]


def merge(cloud: List[Found], lan: List[Found]) -> List[Found]:
    """Junta chaves (nuvem) com IP/versão (rede local) pelo Device ID."""
    by_id = {f.device_id: f for f in lan}
    merged = []
    for c in cloud:
        l = by_id.get(c.device_id)
        merged.append(Found(c.device_id, l.ip if l else "", l.version if l else "auto", c.name, c.local_key))
    return merged


def _cloud_err(err) -> str:
    if isinstance(err, dict):
        return str(err.get("Payload") or err.get("Error") or err)
    return str(err)
