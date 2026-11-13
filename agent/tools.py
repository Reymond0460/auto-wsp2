# agent/tools.py — Herramientas que Claude puede ejecutar (tool use)
"""
Aqui se definen las ACCIONES del agente y se conectan al ciclo de tool use de Claude
(ver brain.py). El agente NUNCA confirma una hora sin que reservar_cita devuelva ok.
"""

import json
import logging

from agent import agenda

logger = logging.getLogger("agentkit")

DEFINICIONES = [
    {
        "name": "horas_disponibles",
        "description": (
            "Devuelve las horas libres mas cercanas para un corte. Usala SIEMPRE antes de "
            "ofrecer horas: nunca inventes horarios. Si el dia pedido esta lleno, devuelve "
            "el siguiente dia con horas libres (revisa el campo fecha)."
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
    {
        "name": "cancelar_cita",
        "description": "Cancela una cita del cliente que esta escribiendo.",
        "input_schema": {
            "type": "object",
            "properties": {"fecha": {"type": "string"}, "hora": {"type": "string"}},
            "required": ["fecha", "hora"],
        },
    },
]


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
