# Lunar Market - Bot para Railway

Este repositorio contiene un bot de Discord listo para desplegar en Railway. Incluye un sistema de tickets básico con persistencia en SQLite.

Archivos principales:
- bot.py — código principal del bot.
- requirements.txt — dependencias.
- Procfile — para Railway (worker: python bot.py).
- config.sample.json — archivo de ejemplo con categorías y emojis.
- .gitignore — ignorar archivos sensibles.

Instrucciones rápidas para Railway
1. Asegúrate de que tu repo esté en GitHub con estos archivos.
2. Crea un proyecto en https://railway.app y conecta el repo.
3. Elige Deploy from GitHub → selecciona la rama add/railway-bot.
4. En Settings → Environment Variables agrega:
   - DISCORD_TOKEN = (tu token regenerado)
   - (Opcional) GUILD_ID = (si quieres sincronizar slash commands inmediatamente)
   - (Opcional) TICKET_CATEGORY_ID = 1548068709443305583
   - (Opcional) TAG_ON_CREATE_ROLE_ID = 1451204772672831564
5. Build command: pip install -r requirements.txt
   Start command: python bot.py
6. Deploy y revisa los logs. Debes ver "Conectado como <bot>".

Probar localmente
- Crea un archivo .env con DISCORD_TOKEN (solo para pruebas locales).
- Ejecuta:
  pip install -r requirements.txt
  export DISCORD_TOKEN="tu_token"  # o set en Windows
  python bot.py

Seguridad
- Nunca subas DISCORD_TOKEN al repositorio.
- Si has expuesto el token antes, regenera uno nuevo en Discord Developer Portal.

Si quieres que sincronice comandos al instante pegá tu GUILD_ID en las env vars (GUILD_ID) y redeploy.
