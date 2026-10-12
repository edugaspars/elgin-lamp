"""Rotinas: horário fixo, nascer e pôr do sol."""

import datetime as dt
import logging
from typing import Dict, Iterable, List, Optional, Tuple

from .storage import Location, Routine

log = logging.getLogger(__name__)

# Se o PC estava dormindo/desligado no horário, ainda executa até este atraso.
GRACE = dt.timedelta(minutes=10)


def sun_times(location: Location, day: dt.date, tz) -> Optional[Tuple[dt.datetime, dt.datetime]]:
    """(nascer, pôr) do sol no fuso local, ou None se não houver localização/sol."""
    if not location.is_set:
        return None
    from astral import Observer
    from astral.sun import sunrise, sunset

    obs = Observer(latitude=location.latitude, longitude=location.longitude)
    try:
        return sunrise(obs, day, tzinfo=tz), sunset(obs, day, tzinfo=tz)
    except ValueError:  # regiões polares: o sol não nasce/se põe nesse dia
        return None


def occurrence(routine: Routine, day: dt.date, location: Location, tz) -> Optional[dt.datetime]:
    """Quando a rotina dispara no dia `day` (ou None se não dispara)."""
    if not routine.enabled or day.weekday() not in routine.days:
        return None
    if routine.trigger == "time":
        try:
            hh, mm = (int(x) for x in routine.time.split(":"))
            return dt.datetime.combine(day, dt.time(hh, mm), tzinfo=tz)
        except ValueError:
            return None
    times = sun_times(location, day, tz)
    if not times:
        return None
    base = times[0] if routine.trigger == "sunrise" else times[1]
    return (base + dt.timedelta(minutes=routine.offset_min)).replace(second=0, microsecond=0)


def due(routines: Iterable[Routine], now: dt.datetime, location: Location,
        fired: Dict[str, str]) -> List[Routine]:
    """Rotinas que devem rodar agora. `fired` guarda {id: data ISO} para não repetir."""
    out = []
    for r in routines:
        # Ontem também: uma rotina com deslocamento pode cair após a meia-noite.
        for day in (now.date(), now.date() - dt.timedelta(days=1)):
            when = occurrence(r, day, location, now.tzinfo)
            if when is None:
                continue
            stamp = day.isoformat()
            if when <= now < when + GRACE and fired.get(r.id) != stamp:
                fired[r.id] = stamp
                out.append(r)
                break
    return out


def next_occurrence(routine: Routine, now: dt.datetime, location: Location) -> Optional[dt.datetime]:
    for i in range(8):
        when = occurrence(routine, now.date() + dt.timedelta(days=i), location, now.tzinfo)
        if when and when > now:
            return when
    return None
