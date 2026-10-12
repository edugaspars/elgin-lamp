"""Encontrar lâmpadas: varredura da rede local e importação de chaves da nuvem Tuya."""

import logging
from dataclasses import dataclass
from typing import Dict, List

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
