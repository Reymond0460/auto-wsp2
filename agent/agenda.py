# agent/agenda.py — Agenda de citas de la barberia
"""
Calcula las horas libres y guarda las reservas en la base de datos (la misma de memory.py).

Reglas (se cambian desde config/business.yaml -> agenda):
  - Atencion de 10:00 a 20:00, hora de Chile (America/Santiago)
  - Cada cita dura lo mismo (duracion_minutos); la ultima empieza antes del cierre
  - Una cita por bloque (un solo barbero)
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from agent.memory import Base, ahora, async_session


def _config() -> dict:
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("agenda", {})
    except FileNotFoundError:
        return {}


def _cfg():
    c = _config()
    return {
        "zona": ZoneInfo(c.get("zona_horaria", "America/Santiago")),
        "apertura": time.fromisoformat(c.get("apertura", "10:00")),
        "cierre": time.fromisoformat(c.get("cierre", "20:00")),
        "duracion": int(c.get("duracion_minutos", 30)),
        # 0=lunes ... 6=domingo
        "dias": set(c.get("dias_atencion", [0, 1, 2, 3, 4, 5, 6])),
        "dias_adelante": int(c.get("dias_reserva_adelante", 14)),
    }


def ahora_local() -> datetime:
    return datetime.now(_cfg()["zona"])


class Cita(Base):
    """Una reserva. La restriccion unica impide que dos clientes tomen el mismo bloque."""

    __tablename__ = "citas"
    __table_args__ = (UniqueConstraint("fecha", "hora", name="uq_cita_bloque"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fecha: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    hora: Mapped[str] = mapped_column(String(5))  # HH:MM
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    nombre: Mapped[str] = mapped_column(String(100))
    servicio: Mapped[str] = mapped_column(String(100))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


def _bloques_del_dia(dia: date) -> list[datetime]:
    c = _cfg()
    if dia.weekday() not in c["dias"]:
        return []
    inicio = datetime.combine(dia, c["apertura"], c["zona"])
    fin = datetime.combine(dia, c["cierre"], c["zona"])
    paso = timedelta(minutes=c["duracion"])
    bloques, t = [], inicio
    while t + paso <= fin:
        bloques.append(t)
        t += paso
    return bloques


async def _ocupadas(fecha: str) -> set[str]:
    async with async_session() as s:
        r = await s.execute(select(Cita.hora).where(Cita.fecha == fecha))
        return set(r.scalars().all())


async def horas_disponibles(fecha: str | None = None, desde: str | None = None, cantidad: int = 4) -> dict:
    """
    Devuelve las horas libres mas cercanas.
    - fecha: YYYY-MM-DD (por defecto hoy). Si ese dia ya no hay, busca en los dias siguientes.
    - desde: HH:MM, la hora que prefiere el cliente (por defecto ahora mismo).
    """
    c = _cfg()
    ahora_cl = ahora_local()
    hoy = ahora_cl.date()
    try:
        dia = date.fromisoformat(fecha) if fecha else hoy
    except ValueError:
        return {"error": "Fecha invalida, usa YYYY-MM-DD"}
    if dia < hoy:
        return {"error": "Esa fecha ya paso"}

    for _ in range(c["dias_adelante"]):
        if dia > hoy + timedelta(days=c["dias_adelante"]):
            break
        ocupadas = await _ocupadas(dia.isoformat())
        libres = [b for b in _bloques_del_dia(dia) if b > ahora_cl and b.strftime("%H:%M") not in ocupadas]
        if libres:
            if desde:
                try:
                    ref = datetime.combine(dia, time.fromisoformat(desde), c["zona"])
                    libres.sort(key=lambda b: abs((b - ref).total_seconds()))
                except ValueError:
                    pass
            elegidas = sorted(libres[:cantidad])
            return {"fecha": dia.isoformat(), "horas": [b.strftime("%H:%M") for b in elegidas]}
        dia += timedelta(days=1)
        desde = None  # en otro dia, se ofrece desde la apertura
    return {"horas": [], "detalle": "No hay horas libres en los proximos dias"}


async def reservar_cita(telefono: str, nombre: str, fecha: str, hora: str, servicio: str = "Corte de pelo") -> dict:
    """Reserva un bloque. Falla si la hora no existe, ya paso o esta tomada."""
    try:
        dia = date.fromisoformat(fecha)
        h = time.fromisoformat(hora)
    except ValueError:
        return {"ok": False, "error": "Fecha u hora invalida"}
    hora_txt = h.strftime("%H:%M")
    bloques = {b.strftime("%H:%M"): b for b in _bloques_del_dia(dia)}
    if hora_txt not in bloques:
        return {"ok": False, "error": "Esa hora no esta dentro del horario de atencion"}
    if bloques[hora_txt] <= ahora_local():
        return {"ok": False, "error": "Esa hora ya paso"}

    async with async_session() as s:
        s.add(Cita(fecha=dia.isoformat(), hora=hora_txt, telefono=telefono, nombre=nombre, servicio=servicio))
        try:
            await s.commit()
        except IntegrityError:
            await s.rollback()
            return {"ok": False, "error": "Esa hora ya fue tomada por otro cliente"}
    return {"ok": True, "fecha": dia.isoformat(), "hora": hora_txt, "servicio": servicio, "nombre": nombre}


async def mis_citas(telefono: str) -> dict:
    """Citas futuras de este cliente."""
    hoy = ahora_local().date().isoformat()
    async with async_session() as s:
        r = await s.execute(
            select(Cita).where(Cita.telefono == telefono, Cita.fecha >= hoy).order_by(Cita.fecha, Cita.hora)
        )
        return {"citas": [{"fecha": x.fecha, "hora": x.hora, "servicio": x.servicio} for x in r.scalars()]}


async def cancelar_cita(telefono: str, fecha: str, hora: str) -> dict:
    """Cancela una cita del propio cliente."""
    async with async_session() as s:
        r = await s.execute(
            select(Cita).where(Cita.telefono == telefono, Cita.fecha == fecha, Cita.hora == hora)
        )
        cita = r.scalar_one_or_none()
        if not cita:
            return {"ok": False, "error": "No encontre una cita tuya en esa fecha y hora"}
        await s.delete(cita)
        await s.commit()
    return {"ok": True}
