"""Localização para nascer/pôr do sol: lista offline de cidades ou GPS do Windows."""

import subprocess
import sys
import unicodedata
from typing import List, Optional, Tuple

# (nome, latitude, longitude). Lista offline: nenhuma consulta sai do PC.
CITIES: List[Tuple[str, float, float]] = [
    ("Aracaju - SE", -10.9472, -37.0731), ("Belém - PA", -1.4558, -48.4902),
    ("Belo Horizonte - MG", -19.9167, -43.9345), ("Boa Vista - RR", 2.8235, -60.6758),
    ("Brasília - DF", -15.7939, -47.8828), ("Campo Grande - MS", -20.4697, -54.6201),
    ("Cuiabá - MT", -15.6014, -56.0979), ("Curitiba - PR", -25.4284, -49.2733),
    ("Florianópolis - SC", -27.5954, -48.5480), ("Fortaleza - CE", -3.7319, -38.5267),
    ("Goiânia - GO", -16.6869, -49.2648), ("João Pessoa - PB", -7.1195, -34.8450),
    ("Macapá - AP", 0.0349, -51.0694), ("Maceió - AL", -9.6498, -35.7089),
    ("Manaus - AM", -3.1190, -60.0217), ("Natal - RN", -5.7945, -35.2110),
    ("Palmas - TO", -10.2491, -48.3243), ("Porto Alegre - RS", -30.0346, -51.2177),
    ("Porto Velho - RO", -8.7612, -63.9004), ("Recife - PE", -8.0476, -34.8770),
    ("Rio Branco - AC", -9.9754, -67.8249), ("Rio de Janeiro - RJ", -22.9068, -43.1729),
    ("Salvador - BA", -12.9777, -38.5016), ("São Luís - MA", -2.5307, -44.3068),
    ("São Paulo - SP", -23.5505, -46.6333), ("Teresina - PI", -5.0919, -42.8034),
    ("Vitória - ES", -20.3155, -40.3128),
    ("Campinas - SP", -22.9099, -47.0626), ("Santos - SP", -23.9608, -46.3336),
    ("Ribeirão Preto - SP", -21.1775, -47.8103), ("São José dos Campos - SP", -23.1896, -45.8841),
    ("Sorocaba - SP", -23.5015, -47.4526), ("Guarulhos - SP", -23.4543, -46.5337),
    ("Uberlândia - MG", -18.9186, -48.2772), ("Juiz de Fora - MG", -21.7642, -43.3503),
    ("Joinville - SC", -26.3045, -48.8487), ("Londrina - PR", -23.3045, -51.1696),
    ("Maringá - PR", -23.4205, -51.9333), ("Caxias do Sul - RS", -29.1678, -51.1794),
    ("Niterói - RJ", -22.8832, -43.1034), ("Feira de Santana - BA", -12.2664, -38.9663),
    ("Campina Grande - PB", -7.2307, -35.8817),
    ("Lisboa - PT", 38.7223, -9.1393), ("Porto - PT", 41.1579, -8.6291),
    ("Buenos Aires - AR", -34.6037, -58.3816), ("Santiago - CL", -33.4489, -70.6693),
    ("Montevideo - UY", -34.9011, -56.1645), ("Lima - PE", -12.0464, -77.0428),
    ("Bogotá - CO", 4.7110, -74.0721), ("Mexico City - MX", 19.4326, -99.1332),
    ("New York - US", 40.7128, -74.0060), ("Miami - US", 25.7617, -80.1918),
    ("Orlando - US", 28.5383, -81.3792), ("Los Angeles - US", 34.0522, -118.2437),
    ("Toronto - CA", 43.6532, -79.3832), ("London - UK", 51.5074, -0.1278),
    ("Paris - FR", 48.8566, 2.3522), ("Madrid - ES", 40.4168, -3.7038),
    ("Berlin - DE", 52.5200, 13.4050), ("Rome - IT", 41.9028, 12.4964),
    ("Dublin - IE", 53.3498, -6.2603), ("Amsterdam - NL", 52.3676, 4.9041),
    ("Tokyo - JP", 35.6762, 139.6503), ("Sydney - AU", -33.8688, 151.2093),
]
CITIES = sorted(set(CITIES))


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def search(text: str) -> List[Tuple[str, float, float]]:
    q = _norm(text.strip())
    return [c for c in CITIES if q in _norm(c[0])] if q else list(CITIES)


_PS_SCRIPT = r"""
Add-Type -AssemblyName System.Device
$w = New-Object System.Device.Location.GeoCoordinateWatcher
$w.Start()
$t = 0
while (($w.Status -ne 'Ready') -and ($w.Permission -ne 'Denied') -and ($t -lt 150)) { Start-Sleep -Milliseconds 100; $t++ }
if ($w.Permission -eq 'Denied') { 'DENIED'; exit }
$c = $w.Position.Location
if ($c.IsUnknown) { 'UNKNOWN' } else {
  $ci = [cultureinfo]::InvariantCulture
  '{0};{1}' -f $c.Latitude.ToString($ci), $c.Longitude.ToString($ci)
}
"""


class GeoError(Exception):
    pass


def gps_supported() -> bool:
    return sys.platform == "win32"


def locate_windows() -> Tuple[float, float]:
    """Usa o serviço de localização do Windows (GPS/Wi-Fi). Bloqueia até ~15 s."""
    if not gps_supported():
        raise GeoError("unsupported")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
            capture_output=True, text=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GeoError("unknown") from exc
    if out == "DENIED":
        raise GeoError("denied")
    try:
        lat, lon = (float(x) for x in out.splitlines()[-1].split(";"))
    except (ValueError, IndexError):
        raise GeoError("unknown")
    return round(lat, 3), round(lon, 3)  # ~100 m de precisão é suficiente


def parse_coords(text: str) -> Optional[Tuple[float, float]]:
    """Aceita '-23.55, -46.63' (formato copiado do Google Maps)."""
    try:
        lat, lon = (float(p) for p in text.replace(";", ",").split(","))
    except ValueError:
        return None
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None
