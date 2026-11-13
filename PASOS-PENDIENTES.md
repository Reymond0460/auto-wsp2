# StudioBarber — Pasos para mañana

El agente "Brayan" ya está programado. Falta conectarlo (≈ 20 min).

## 1. Zernio (WhatsApp)
1. Crear cuenta gratis en zernio.com (sin tarjeta).
2. Settings → API Keys → Create API Key. Copiarla (solo se muestra una vez, empieza con `sk_`).
3. Si no tienes número de WhatsApp Business, activa el número de prueba (sandbox) para +56940916058.
   Claude lo puede hacer por ti con la API key (50 mensajes/día, dura 7 días).
4. Inventa un "webhook secret" (cualquier texto largo y secreto).

## 2. Railway
1. railway.com → New Project → Deploy from GitHub repo → `auto-wsp2`
   (rama `claude/wonderful-newton-wevjkv`, o haz merge a main antes).
2. En el proyecto: New → Database → Add PostgreSQL.
3. En el servicio del agente → Variables:

| Variable | Valor |
|---|---|
| ANTHROPIC_API_KEY | tu clave `sk-ant-...` |
| ANTHROPIC_MODEL | `claude-haiku-5-5` |
| WHATSAPP_PROVIDER | `zernio` |
| ZERNIO_API_KEY | tu clave `sk_...` |
| ZERNIO_WEBHOOK_SECRET | tu secreto inventado |
| ENVIRONMENT | `production` |
| DATABASE_URL | `${{Postgres.DATABASE_URL}}` (literal, con llaves) |

   NO agregues `PORT`.
4. Settings → Networking → Generate Domain. Abre `https://TU-APP.up.railway.app/`:
   debe decir `"status":"ok"`.

## 3. Webhook en Zernio
Webhooks → Create: URL `https://TU-APP.up.railway.app/webhook`, el mismo secret,
evento `message.received`. Luego escribe al número desde tu celular.

## Supuestos a confirmar
- Citas de 30 minutos (última hora 19:30). Se cambia en `config/business.yaml` → `agenda`.
- Atiende los 7 días. Se cambia en `dias_atencion`.
- Un solo barbero (una cita por bloque).
- Las citas se guardan en la base del agente, NO en el sistema de reservas de la web demo.
