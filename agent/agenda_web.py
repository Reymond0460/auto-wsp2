# agent/agenda_web.py — Agenda conectada a la página web (Firestore del proyecto barber-diego)
"""
Lee y escribe en la MISMA base de datos que usa la página de reservas (repo Servicio-Barber),
con las mismas reglas que js/data.js, para que una hora tomada por WhatsApp aparezca
ocupada en la web y en el panel de administración, y al revés.

Colecciones que se usan (igual que la web):
  settings/sitio   horario del barbero (dias, duracionMin, descanso, diasLibres, diasAdelante)
  services         servicios (name, price, active)
  slots            candado por dia+hora. id = "YYYY-MM-DD_HHMM"
  appointments     reservas (date, time, client, phone, svc, price, status 'open'...)

Se activa con la variable FIREBASE_CREDENCIALES (el JSON completo de la cuenta de servicio).
"""

import json
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from google.cloud import firestore
from google.oauth2 import service_account

logger = logging.getLogger("agentkit")

ZONA = ZoneInfo("America/Santiago")
MINUTOS_DE_GRACIA = 30          # igual que la web: una hora se puede tomar hasta 30 min despues de empezar
POLICY_VERSION = "2026-10-19"   # igual que js/data.js
DURACIONES = (30, 45, 60, 90, 120)

# Valores iniciales: copia de AJUSTES_BASE en js/data.js (0 = domingo ... 6 = sabado)
HORARIO_BASE = {
    "dias": {
        0: {"abierto": False, "desde": "10:00", "hasta": "20:00"},
        **{d: {"abierto": True, "desde": "10:00", "hasta": "20:00"} for d in range(1, 7)},
    },
    "duracionMin": 60,
    "descanso": {"activo": False, "desde": "13:00", "hasta": "14:00"},
    "diasLibres": [],
    "diasAdelante": 60,
}

_db: firestore.AsyncClient | None = None


def activa() -> bool:
    return bool(os.getenv("FIREBASE_CREDENCIALES", "").strip())


def _cliente() -> firestore.AsyncClient:
    global _db
    if _db is None:
        info = json.loads(os.environ["FIREBASE_CREDENCIALES"])
        cred = service_account.Credentials.from_service_account_info(info)
        _db = firestore.AsyncClient(project=info["project_id"], credentials=cred)
    return _db


def ahora_local() -> datetime:
    return datetime.now(ZONA)


def _min(hora: str) -> int:
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


def _hora(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _hora_valida(x) -> str | None:
    try:
        return _hora(_min(str(x))) if x else None
    except ValueError:
        return None


def _slot_id(fecha: str, hora: str) -> str:
    return f"{fecha}_{hora.replace(':', '')}"


def _dia_js(dia: date) -> int:
    """Python: lunes=0. JavaScript (la web): domingo=0."""
    return (dia.weekday() + 1) % 7


async def _horario() -> dict:
    """Horario guardado por el barbero en el panel, mezclado con los valores base (como la web)."""
    h = json.loads(json.dumps(HORARIO_BASE))
    h["dias"] = {int(k): v for k, v in h["dias"].items()}
    try:
        snap = await _cliente().collection("settings").document("sitio").get()
        g = (snap.to_dict() or {}).get("horario", {}) if snap.exists else {}
    except Exception as e:  # noqa: BLE001
        logger.error(f"No se pudo leer el horario de la web, uso el base: {e}")
        g = {}
    for d in range(7):
        x = (g.get("dias") or {}).get(str(d)) or (g.get("dias") or {}).get(d)
        if x:
            desde = _hora_valida(x.get("desde")) or h["dias"][d]["desde"]
            hasta = _hora_valida(x.get("hasta")) or h["dias"][d]["hasta"]
            if _min(hasta) <= _min(desde):
                hasta = h["dias"][d]["hasta"]
            h["dias"][d] = {"abierto": bool(x.get("abierto")), "desde": desde, "hasta": hasta}
    if g.get("duracionMin") in DURACIONES or (str(g.get("duracionMin", "")).isdigit() and int(g["duracionMin"]) in DURACIONES):
        h["duracionMin"] = int(g["duracionMin"])
    ds = g.get("descanso") or {}
    d1, d2 = _hora_valida(ds.get("desde")), _hora_valida(ds.get("hasta"))
    if d1 and d2 and _min(d2) > _min(d1):
        h["descanso"] = {"activo": bool(ds.get("activo")), "desde": d1, "hasta": d2}
    if isinstance(g.get("diasLibres"), list):
        h["diasLibres"] = sorted({k for k in g["diasLibres"] if isinstance(k, str) and len(k) == 10})
    try:
        adelante = int(g.get("diasAdelante", 0))
        if 7 <= adelante <= 365:
            h["diasAdelante"] = adelante
    except (TypeError, ValueError):
        pass
    return h


def _horas_del_dia(dia: date, h: dict) -> list[str]:
    """Copia de horasDelDia() en js/data.js."""
    cfg = h["dias"].get(_dia_js(dia))
    if not cfg or not cfg["abierto"] or dia.isoformat() in h["diasLibres"]:
        return []
    dur, fin, pausa = h["duracionMin"], _min(cfg["hasta"]), h["descanso"]
    horas, m = [], _min(cfg["desde"])
    while m + dur <= fin:
        cae_en_pausa = pausa["activo"] and m < _min(pausa["hasta"]) and m + dur > _min(pausa["desde"])
        if not cae_en_pausa:
            horas.append(_hora(m))
        m += dur
    return horas


def _hora_pasada(dia: date, hora: str) -> bool:
    inicio = datetime.combine(dia, datetime.strptime(hora, "%H:%M").time(), ZONA)
    return ahora_local() > inicio + timedelta(minutes=MINUTOS_DE_GRACIA)


async def _ocupadas(fecha: str) -> list[str]:
    q = _cliente().collection("slots").where(filter=firestore.FieldFilter("date", "==", fecha))
    return [d.to_dict().get("time", "") async for d in q.stream()]


def _choca(hora: str, ocupadas: list[str], dur: int) -> bool:
    """Copia de horaOcupada(): si cambio la duracion, las horas vecinas tambien se bloquean."""
    return any(o and abs(_min(o) - _min(hora)) < dur for o in ocupadas)


async def _servicio() -> dict:
    """El primer servicio activo de la web (nombre y precio reales)."""
    async for d in _cliente().collection("services").stream():
        s = d.to_dict()
        if s.get("active", True):
            return {"id": d.id, "name": s.get("name", "Corte"), "price": s.get("price", 0)}
    return {"id": "", "name": "Corte de cabello", "price": 0}


def _telefono_web(telefono: str) -> str:
    """La web guarda +569XXXXXXXX."""
    d = "".join(c for c in telefono if c.isdigit())
    if len(d) == 9 and d.startswith("9"):
        d = "56" + d
    return "+" + d if d.startswith("569") and len(d) == 11 else telefono


# ── Lo que usan las herramientas de Claude ─────────────────────────────

async def horas_disponibles(fecha: str | None = None, desde: str | None = None, cantidad: int = 3) -> dict:
    h = await _horario()
    hoy = ahora_local().date()
    try:
        dia = date.fromisoformat(fecha) if fecha else hoy
    except ValueError:
        return {"error": "Fecha invalida, usa YYYY-MM-DD"}
    if dia < hoy:
        return {"error": "Esa fecha ya paso"}
    ultimo = hoy + timedelta(days=h["diasAdelante"])
    servicio = await _servicio()

    while dia <= ultimo:
        ocupadas = await _ocupadas(dia.isoformat())
        libres = [
            x for x in _horas_del_dia(dia, h)
            if not _hora_pasada(dia, x) and not _choca(x, ocupadas, h["duracionMin"])
        ]
        if libres:
            if desde and _hora_valida(desde):
                ref = _min(_hora_valida(desde))
                libres = sorted(libres, key=lambda x: abs(_min(x) - ref))
            elegidas = sorted(libres[:cantidad])
            hora_pedida = _hora_valida(desde) if desde else None
            return {
                "fecha": dia.isoformat(),
                "horas": elegidas,
                "hora_pedida_libre": (hora_pedida in libres) if hora_pedida else None,
                "duracion_min": h["duracionMin"],
                "servicio": servicio["name"],
                "precio": servicio["price"],
            }
        dia += timedelta(days=1)
        desde = None
    return {"horas": [], "detalle": "No hay horas libres en los proximos dias"}


async def reservar_cita(telefono: str, nombre: str, fecha: str, hora: str, servicio: str | None = None) -> dict:
    h = await _horario()
    try:
        dia = date.fromisoformat(fecha)
    except ValueError:
        return {"ok": False, "error": "Fecha invalida"}
    hora = _hora_valida(hora)
    if not hora or hora not in _horas_del_dia(dia, h):
        return {"ok": False, "error": "Esa hora no esta dentro del horario de atencion"}
    if _hora_pasada(dia, hora):
        return {"ok": False, "error": "Esa hora ya paso"}
    if _choca(hora, await _ocupadas(fecha), h["duracionMin"]):
        return {"ok": False, "error": "Esa hora esta tomada"}

    db = _cliente()
    svc = await _servicio()
    slot_ref = db.collection("slots").document(_slot_id(fecha, hora))
    appt_ref = db.collection("appointments").document()

    @firestore.async_transactional
    async def _tomar(tx):
        # El mismo candado que usa la web: si el slot existe, otro ya tomo esa hora
        if (await slot_ref.get(transaction=tx)).exists:
            return False
        tx.set(slot_ref, {"apptId": appt_ref.id, "date": fecha, "time": hora})
        tx.set(appt_ref, {
            "date": fecha, "time": hora, "client": nombre.strip(), "phone": _telefono_web(telefono),
            "serviceId": svc["id"], "svc": svc["name"], "price": svc["price"],
            "status": "open", "createdAt": firestore.SERVER_TIMESTAMP,
            # Por WhatsApp el cliente no marco la casilla de la politica de privacidad
            "consent": {"accepted": False, "policyVersion": POLICY_VERSION, "at": firestore.SERVER_TIMESTAMP},
            "origen": "whatsapp",
        })
        return True

    if not await _tomar(db.transaction()):
        return {"ok": False, "error": "Esa hora esta tomada"}
    return {"ok": True, "fecha": fecha, "hora": hora, "servicio": svc["name"], "precio": svc["price"], "nombre": nombre}


async def mis_citas(telefono: str) -> dict:
    hoy = ahora_local().date().isoformat()
    q = _cliente().collection("appointments").where(
        filter=firestore.FieldFilter("phone", "==", _telefono_web(telefono))
    )
    citas = []
    async for d in q.stream():
        a = d.to_dict()
        if a.get("status") == "open" and a.get("date", "") >= hoy:
            citas.append({"fecha": a["date"], "hora": a["time"], "servicio": a.get("svc")})
    return {"citas": sorted(citas, key=lambda c: (c["fecha"], c["hora"]))}
