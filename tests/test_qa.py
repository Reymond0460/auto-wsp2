# tests/test_qa.py — Pruebas de QA del agente (sin gastar API ni tocar WhatsApp real)
# Uso: python tests/test_qa.py
import asyncio
import hashlib
import hmac
import json
import os
import sys
from datetime import date, timedelta
from types import SimpleNamespace as NS

os.environ.update({
    "DATABASE_URL": "sqlite+aiosqlite:///./qa.db",
    "WHATSAPP_PROVIDER": "zernio",
    "ZERNIO_API_KEY": "sk_prueba",
    "ZERNIO_WEBHOOK_SECRET": "secreto-qa",
    "ANTHROPIC_API_KEY": "simulada",
    "ESPERA_AGRUPAR_SEGUNDOS": "0.5",
    "NUMEROS_PERMITIDOS": "+56911112222",
})
os.environ.pop("FIREBASE_CREDENCIALES", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import agent.main as m  # noqa: E402
from agent import agenda, agenda_web, brain  # noqa: E402

RESULTADOS = []


def caso(nombre, ok, detalle=""):
    RESULTADOS.append((nombre, bool(ok), detalle))
    print(f"[{'OK ' if ok else 'FALLA'}] {nombre}" + (f" — {detalle}" if detalle and not ok else ""))


def payload(evento_id, tel="+56911112222", texto="hola", direccion="incoming"):
    return {
        "id": evento_id, "event": "message.received", "account": {"id": "acc1"},
        "message": {"direction": direccion, "platform": "whatsapp", "text": texto,
                    "conversationId": "conv1", "id": "m" + evento_id,
                    "sender": {"phoneNumber": tel}},
    }


def firmar(cuerpo: bytes, secreto="secreto-qa"):
    return hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def main():
    enviados, llamadas = [], []

    async def gen(texto, historial, tel):
        llamadas.append(texto)
        return "respuesta de prueba", True

    async def env(tel, msg, ctx=None):
        enviados.append((tel, msg))
        return True

    async def conexion():
        return True, "simulada"

    m.generar_respuesta = gen
    m.proveedor.enviar_mensaje = env
    m.proveedor.verificar_conexion = conexion

    with TestClient(m.app) as c:
        # 1. Salud
        r = c.get("/").json()
        caso("Health check responde ok", r.get("status") == "ok", str(r))
        caso("Health check informa la agenda", "agenda" in r, str(r))

        # 2. Firma del webhook
        cuerpo = json.dumps(payload("e1")).encode()
        caso("Webhook sin firma -> 401", c.post("/webhook", content=cuerpo).status_code == 401)
        caso("Webhook con firma falsa -> 401",
             c.post("/webhook", content=cuerpo, headers={"X-Zernio-Signature": "abc"}).status_code == 401)
        caso("Firma con caracteres raros -> 401 (no 500)",
             c.post("/webhook", content=cuerpo, headers={"X-Zernio-Signature": "ñ".encode("latin-1")}).status_code == 401)
        r = c.post("/webhook", content=cuerpo, headers={"X-Zernio-Signature": firmar(cuerpo)})
        caso("Webhook firmado -> 200 y se encola", r.status_code == 200 and r.json().get("encolados") == 1, r.text)

        # 3. Deduplicacion (Zernio reintenta hasta 7 veces)
        r = c.post("/webhook", content=cuerpo, headers={"X-Zernio-Signature": firmar(cuerpo)})
        caso("Evento repetido no se procesa 2 veces", r.json().get("encolados") == 0, r.text)

        # 4. Filtro de numeros
        b = json.dumps(payload("e2", tel="+56999999999")).encode()
        r = c.post("/webhook", content=b, headers={"X-Zernio-Signature": firmar(b)})
        caso("Numero no permitido se ignora", r.json().get("encolados") == 0, r.text)

        # 5. Mensajes propios (los que escribe el dueno desde su telefono)
        b = json.dumps(payload("e3", direccion="outgoing")).encode()
        r = c.post("/webhook", content=b, headers={"X-Zernio-Signature": firmar(b)})
        caso("Mensaje propio (outgoing) se ignora", r.json().get("encolados") == 0, r.text)

        # 6. Eventos que no son mensajes
        b = json.dumps({"id": "e4", "event": "message.delivered"}).encode()
        r = c.post("/webhook", content=b, headers={"X-Zernio-Signature": firmar(b)})
        caso("Eventos que no son mensajes se ignoran", r.status_code == 200 and r.json().get("encolados") == 0)

        # 7. Payload roto no provoca reintentos infinitos
        b = b"esto no es json"
        r = c.post("/webhook", content=b, headers={"X-Zernio-Signature": firmar(b)})
        caso("Payload invalido -> 200 ignorado", r.status_code == 200, r.text)

    # 8. Agrupar mensajes seguidos
    llamadas.clear()

    async def agrupar():
        from agent.providers.base import MensajeEntrante as M
        a = M("56911112222", "No tienes otro dia?", "1", False, {"evento_id": "g1"})
        b = M("56911112222", "Otra hora?", "2", False, {"evento_id": "g2"})
        t1 = asyncio.create_task(m.procesar_mensaje(a))
        await asyncio.sleep(0.2)
        t2 = asyncio.create_task(m.procesar_mensaje(b))
        await asyncio.gather(t1, t2)

    asyncio.run(agrupar())
    caso("Dos mensajes seguidos = una sola respuesta", llamadas == ["No tienes otro dia?\nOtra hora?"], str(llamadas))

    # 9. Agenda local
    async def agenda_local():
        await m.inicializar_db()
        manana = (agenda.ahora_local().date() + timedelta(days=1)).isoformat()
        r1 = await agenda.reservar_cita("569A", "Ana", manana, "15:00")
        r2 = await agenda.reservar_cita("569B", "Beto", manana, "15:00")
        r3 = await agenda.reservar_cita("569B", "Beto", manana, "21:00")
        r4 = await agenda.reservar_cita("569B", "Beto", "2020-01-01", "15:00")
        libres = await agenda.horas_disponibles(manana, "15:00")
        caso("Reserva valida queda guardada", r1.get("ok"), str(r1))
        caso("Doble reserva de la misma hora se rechaza", not r2.get("ok"), str(r2))
        caso("Hora fuera de horario se rechaza", not r3.get("ok"), str(r3))
        caso("Fecha pasada se rechaza", not r4.get("ok"), str(r4))
        caso("Hora tomada no se ofrece", "15:00" not in libres.get("horas", []), str(libres))

    asyncio.run(agenda_local())

    # 10. Agenda web: mismas reglas que js/data.js
    h = json.loads(json.dumps(agenda_web.HORARIO_BASE))
    h["dias"] = {int(k): v for k, v in h["dias"].items()}
    lunes = date(2026, 11, 16)
    caso("Web: lunes 10:00-19:00 en bloques de 60",
         agenda_web._horas_del_dia(lunes, h) == [f"{x}:00" for x in range(10, 20)])
    caso("Web: domingo cerrado", agenda_web._horas_del_dia(date(2026, 11, 22), h) == [])
    h2 = json.loads(json.dumps(h)); h2["dias"] = h["dias"]
    h2["descanso"] = {"activo": True, "desde": "13:00", "hasta": "14:00"}
    caso("Web: pausa de almuerzo se respeta", "13:00" not in agenda_web._horas_del_dia(lunes, h2))
    h3 = dict(h); h3["diasLibres"] = ["2026-11-16"]
    caso("Web: dia libre no tiene horas", agenda_web._horas_del_dia(lunes, h3) == [])
    caso("Web: horas vecinas chocan si cambio la duracion", agenda_web._choca("11:00", ["10:30"], 60))
    caso("Web: telefono se guarda como +569XXXXXXXX",
         agenda_web._telefono_web("56940916058") == "+56940916058" and agenda_web._telefono_web("940916058") == "+56940916058")

    # 11. Ciclo de herramientas de Claude (simulado)
    guion = [
        NS(stop_reason="tool_use", content=[NS(type="tool_use", id="t1", name="horas_disponibles", input={})]),
        NS(stop_reason="end_turn", content=[NS(type="text", text="Te sirve a las 10:00?")], usage=NS(input_tokens=1, output_tokens=1)),
    ]
    vistos = []

    async def falso(**kw):
        vistos.append(kw)
        return guion.pop(0)

    brain.client.messages.create = falso
    texto, real = asyncio.run(brain.generar_respuesta("hola", [], "569C"))
    caso("Claude usa la herramienta y responde", real and texto == "Te sirve a las 10:00?", texto)
    caso("Se envia la fecha y hora actual al modelo", "Fecha y hora actual" in vistos[0]["system"])

    async def falla(**kw):
        raise RuntimeError("API caida")

    brain.client.messages.create = falla
    texto, real = asyncio.run(brain.generar_respuesta("hola", [], "569C"))
    caso("Si Claude falla, responde aviso y no lo guarda", not real and "sistema" in texto, texto)

    total, ok = len(RESULTADOS), sum(1 for r in RESULTADOS if r[1])
    print(f"\n{ok}/{total} pruebas OK")
    json.dump([{"caso": n, "ok": o} for n, o, _ in RESULTADOS], open("qa_resultados.json", "w"), ensure_ascii=False)
    return ok == total


if __name__ == "__main__":
    try:
        exito = main()
    finally:
        if os.path.exists("qa.db"):
            os.remove("qa.db")
    sys.exit(0 if exito else 1)
