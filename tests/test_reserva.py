# tests/test_reserva.py — Verifica el ciclo de tool use sin gastar API (Claude simulado)
# Uso: python tests/test_reserva.py
import asyncio
import os
import sys
from types import SimpleNamespace as NS

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_reserva.db"
os.environ.setdefault("ANTHROPIC_API_KEY", "simulada")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import brain  # noqa: E402
from agent.agenda import ahora_local, mis_citas  # noqa: E402
from agent.memory import inicializar_db  # noqa: E402

MANANA = (ahora_local().date().toordinal() + 1)


async def main():
    from datetime import date

    fecha = date.fromordinal(MANANA).isoformat()
    guion = [
        NS(stop_reason="tool_use", content=[NS(type="tool_use", id="t1", name="horas_disponibles", input={"fecha": fecha, "desde": "17:00"})]),
        NS(stop_reason="end_turn", content=[NS(type="text", text="Tengo 16:30, 17:00, 17:30")], usage=NS(input_tokens=1, output_tokens=1)),
        NS(stop_reason="tool_use", content=[NS(type="tool_use", id="t2", name="reservar_cita", input={"nombre": "Matias", "fecha": fecha, "hora": "17:00"})]),
        NS(stop_reason="end_turn", content=[NS(type="text", text="Vale bro, te espero a las 17:00")], usage=NS(input_tokens=1, output_tokens=1)),
    ]
    vistos = []

    async def falso_create(**kw):
        vistos.append(kw["messages"][-1])
        return guion.pop(0)

    brain.client.messages.create = falso_create
    await inicializar_db()
    r1, _ = await brain.generar_respuesta("hora manana a las 5?", [], "569111")
    r2, _ = await brain.generar_respuesta("la de las 17, soy Matias", [], "569111")
    citas = (await mis_citas("569111"))["citas"]
    assert "17:00" in vistos[1]["content"][0]["content"], "horas_disponibles no se ejecuto"
    assert citas and citas[0]["hora"] == "17:00", "la reserva no quedo guardada"
    print("OK:", r1, "|", r2, "|", citas)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        if os.path.exists("test_reserva.db"):
            os.remove("test_reserva.db")
