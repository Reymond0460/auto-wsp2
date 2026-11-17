# tests/test_produccion.py — QA contra lo publicado (agente en Railway + reglas de Firestore)
# Uso: python tests/test_produccion.py https://<app>.up.railway.app <proyecto-firebase> <apiKey-web>
# No escribe nada: solo lee. Falla si las reglas publicadas de Firestore estan desactualizadas.
import json
import sys
import urllib.error
import urllib.request

URL, PROYECTO, API_KEY = (sys.argv[1:4] + [None] * 3)[:3]
if not URL:
    URL, PROYECTO, API_KEY = (
        "https://auto-wsp2-production.up.railway.app",
        "barber-diego",
        "AIzaSyDm6HxU-Tl6ObUc9F-CfbKGWXPPU6BfkM8",  # clave web publica (no es secreta)
    )

fallas = 0


def caso(nombre, ok, detalle=""):
    global fallas
    fallas += not ok
    print(f"[{'OK ' if ok else 'FALLA'}] {nombre}" + ("" if ok else f" — {detalle}"))


def pedir(url, metodo="GET", datos=None, headers=None):
    req = urllib.request.Request(url, data=datos, method=metodo, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# 1. Agente
st, cuerpo = pedir(URL + "/")
salud = json.loads(cuerpo) if st == 200 else {}
caso("Agente responde status ok", salud.get("status") == "ok", cuerpo[:200])
caso("WhatsApp conectado", (salud.get("conexion") or {}).get("ok") is True, cuerpo[:200])
caso("Agenda conectada a Firestore", (salud.get("agenda") or {}).get("tipo") == "web (Firestore)"
     and (salud.get("agenda") or {}).get("ok") is True, cuerpo[:300])

# 2. Webhook protegido
st, _ = pedir(URL + "/webhook", "POST", b'{"id":"qa","event":"message.received"}', {"Content-Type": "application/json"})
caso("Webhook sin firma rechazado (401)", st == 401, str(st))

# 3. Reglas de Firestore publicadas = las del repositorio (lo publico debe poder leerse)
base = f"https://firestore.googleapis.com/v1/projects/{PROYECTO}/databases/(default)/documents"
for ruta, nombre in (("settings/sitio", "settings (Mi horario)"), ("services", "services"), ("slots", "slots")):
    st, cuerpo = pedir(f"{base}/{ruta}?key={API_KEY}")
    # 404 en settings/sitio = el documento aun no existe (permiso OK). 403 = reglas desactualizadas.
    caso(f"Reglas publicadas permiten leer {nombre}", st in (200, 404),
         f"HTTP {st}: publica firestore.rules con 'firebase deploy --only hosting,firestore:rules'")
st, _ = pedir(f"{base}/appointments?key={API_KEY}")
caso("Reglas publicadas protegen appointments (datos de clientes)", st == 403, f"HTTP {st}")

print("\nTODO OK" if not fallas else f"\n{fallas} FALLA(S)")
sys.exit(1 if fallas else 0)
