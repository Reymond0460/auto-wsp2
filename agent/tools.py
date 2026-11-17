# agent/tools.py — Herramientas que Claude puede ejecutar (tool use)
"""
Aqui se definen las ACCIONES del agente y se conectan al ciclo de tool use de Claude
(ver brain.py). El agente NUNCA confirma una hora sin que reservar_cita devuelva ok.
"""

import json
import logging

from agent import agenda_web

# Si hay credenciales de Firebase, se usa la agenda de la pagina web (compartida).
# Si no, la agenda local de la base del agente (sirve para probar sin Firebase).
if agenda_web.activa():
    agenda = agenda_web
else:
    from agent import agenda

logger = logging.getLogger("agentkit")

DEFINICIONES = [
    {
        "name": "horas_disponibles",
        "description": (
            "Devuelve las horas libres mas cercanas, el servicio y su precio. Usala SIEMPRE antes de "
            "ofrecer horas o dar el precio: nunca inventes horarios. Si el dia pedido esta lleno, "
            "devuelve el siguiente dia con horas libres (revisa el campo fecha). "
            "hora_pedida_libre dice si la hora exacta que pidio el cliente esta libre."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {"type": "string", "description": "YYYY-MM-DD. Omitir = hoy."},
                "desde": {"type": "string", "description": "HH:MM, hora preferida del cliente. Omitir = lo mas pronto posible."},
            },
        },
    },
    {
        "name": "reservar_cita",
        "description": "Reserva la hora que el cliente eligio. Solo confirma la cita si devuelve ok=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Nombre del cliente"},
                "fecha": {"type": "string", "description": "YYYY-MM-DD"},
                "hora": {"type": "string", "description": "HH:MM"},
            },
            "required": ["nombre", "fecha", "hora"],
        },
    },
    {
        "name": "mis_citas",
        "description": "Lista las citas futuras del cliente que esta escribiendo.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

# Cancelar solo existe en la agenda local: en la web, las cancelaciones las hace el barbero
# desde el panel de administracion.
if agenda is not agenda_web:
    DEFINICIONES.append({
        "name": "cancelar_cita",
        "description": "Cancela una cita del cliente que esta escribiendo.",
        "input_schema": {
            "type": "object",
            "properties": {"fecha": {"type": "string"}, "hora": {"type": "string"}},
            "required": ["fecha", "hora"],
        },
    })


async def ejecutar(nombre: str, args: dict, telefono: str) -> str:
    """Ejecuta una herramienta y devuelve el resultado como JSON (texto para Claude)."""
    try:
        if nombre == "horas_disponibles":
            r = await agenda.horas_disponibles(args.get("fecha"), args.get("desde"))
        elif nombre == "reservar_cita":
            r = await agenda.reservar_cita(telefono, args["nombre"], args["fecha"], args["hora"])
        elif nombre == "mis_citas":
            r = await agenda.mis_citas(telefono)
        elif nombre == "cancelar_cita":
            r = await agenda.cancelar_cita(telefono, args["fecha"], args["hora"])
        else:
            r = {"error": f"Herramienta desconocida: {nombre}"}
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Fallo la herramienta {nombre}")
        r = {"ok": False, "error": f"Error interno: {e}"}
    logger.info(f"Herramienta {nombre}({args}) -> {r}")
    return json.dumps(r, ensure_ascii=False)
