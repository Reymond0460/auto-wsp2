# StudioBarber — Pasos para mañana

El agente "Brayan" ya está programado. Falta conectarlo (≈ 20 min).

## 1. Zernio (WhatsApp) — LISTO
- Número +56 9 4091 6058 ("Brayan") conectado en modo coexistencia (sigues usando la app de WhatsApp Business).
- `ZERNIO_ACCOUNT_ID` = `6afb5a014bf0600df76b2350`
- Falta: inventar un "webhook secret" (texto largo y secreto) y guardarlo para Railway.

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
| ZERNIO_ACCOUNT_ID | `6afb5a014bf0600df76b2350` |
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
