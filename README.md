# Ecommerce Router API

Router conversacional para un ecommerce construido con LangGraph, Gemini y FastAPI. Clasifica cada mensaje en una de tres rutas:

- `preventa`: consultas antes de comprar, como productos, stock, tallas, precios y pagos.
- `postventa`: pedidos ya realizados, devoluciones, cambios, garantías y reclamos.
- `generica`: saludos o preguntas sin relación con la tienda.

El router conserva el historial de cada usuario mediante `thread_id`.

## Requisitos y configuración

Se requiere Python 3.12 y una clave de Google Gemini. Crea el entorno e instala las dependencias:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Edita `.env` y configura al menos `GOOGLE_API_KEY`. No subas este archivo al repositorio.

## Ejecutar el router localmente

```bash
.venv/bin/python main.py router "¿Tienen la polera azul en talla M?" --thread-id usuario-123
```

Para ver el recorrido y el motivo de enrutamiento:

```bash
.venv/bin/python main.py router "Mi pedido llegó roto" --saltos --thread-id usuario-123
```

Para imprimir el diagrama Mermaid sin ejecutar el modelo:

```bash
.venv/bin/python main.py router "consulta" --diagrama
```

## Levantar la API

Activa el entorno y levanta FastAPI desde la raíz del proyecto:

```bash
source .venv/bin/activate
uvicorn api.app:app --reload --port 8000
```

Swagger está disponible en <http://localhost:8000/docs>. Prueba el chat con:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id":"usuario-123","texto":"¿Tienen la polera azul en talla M?"}'
```

## Pruebas

La evaluación de rutas usa los 15 casos en `tests/casos_router.json` y requiere `GOOGLE_API_KEY`:

```bash
.venv/bin/python -m pytest -q
```

Para ver el detalle de cada caso, incluyendo ruta, motivo y porcentaje de aciertos:

```bash
.venv/bin/python scripts/test_router.py
```

## Desplegar en Heroku

El repositorio incluye el `Procfile` y `.python-version` necesarios. Con la CLI de Heroku instalada y habiendo iniciado sesión, ejecuta:

```bash
heroku login
heroku create tu-app-ecommerce-router
heroku config:set GOOGLE_API_KEY="tu-clave-de-google" --app tu-app-ecommerce-router
heroku config:set MODELO="gemini-3.5-flash-lite" --app tu-app-ecommerce-router
git push heroku main
heroku open --app tu-app-ecommerce-router
```

La URL pública será `https://tu-app-ecommerce-router.herokuapp.com`. Puedes comprobarla con:

```bash
curl https://tu-app-ecommerce-router.herokuapp.com/health
```

## Conectar Telegram

Primero crea el bot con `@BotFather`, ejecuta `/newbot` y guarda el token entregado. Después sigue estos pasos en orden:

1. Configura el token y un secreto propio en Heroku:

```bash
heroku config:set TELEGRAM_TOKEN="token-de-botfather" --app tu-app-ecommerce-router
heroku config:set TELEGRAM_SECRET="un-secreto-largo-y-privado" --app tu-app-ecommerce-router
```

2. Confirma los cambios de Telegram y despliega tanto a GitHub como a Heroku:

```bash
git add api/app.py scripts/set_webhook.py scripts/webhook_info.py README.md
git commit -m "connect telegram webhook"
git push origin main
git push heroku main
```

3. Registra el webhook con la URL pública de Heroku y confirma su estado. Asegúrate de que `.env` tenga el mismo `TELEGRAM_TOKEN` y `TELEGRAM_SECRET` configurados en Heroku:

```bash
heroku config:set PUBLIC_URL="https://tu-app-ecommerce-router.herokuapp.com" --app tu-app-ecommerce-router
PUBLIC_URL="https://tu-app-ecommerce-router.herokuapp.com" .venv/bin/python scripts/set_webhook.py
.venv/bin/python scripts/webhook_info.py
```

El primer comando debe devolver `"ok": true`. El segundo muestra `url`, `pending_update_count` y `last_error_message` si Telegram detectó un problema.

4. Escribe al bot estos seis mensajes y observa el enrutamiento en los logs:

```bash
heroku logs --tail --app tu-app-ecommerce-router
```

- `¿tienen la polera azul en talla M?` debe ir a `preventa`.
- `mi pedido 4521 llegó roto` debe ir a `postventa`.
- `hola` debe ir a `generica`.
- `¿cuánto cuesta el envío a Valparaíso?` debe ir a `preventa`.
- `quiero devolver unas zapatillas` debe ir a `postventa`.
- `¿qué hora es en Tokio?` debe ir a `generica`.

5. Si el bot no responde, revisa que el webhook apunte a `https://.../telegram`, que `TELEGRAM_SECRET` sea igual en Telegram y Heroku, y que `TELEGRAM_TOKEN` sea el correcto.

Para probar antes de desplegar, levanta la API localmente y abre un túnel HTTPS:

```bash
cloudflared tunnel --url http://localhost:8000
```

Usa la URL HTTPS entregada por Cloudflare como `PUBLIC_URL` al ejecutar `scripts/set_webhook.py`.
