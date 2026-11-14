# thomas/server

**aiohttp web server, API routing, static serving** | tier: core | health: yellow
Allowed imports: core, agent, memory, models, preferences, tools, observability, policy, system, autonomy, realtime, security, plugins, asset_studio, codex, channels, companion
Known debt: app.py exceeds 1500 lines and imports nearly everything - extract routes; routes/companion_aiohttp.py exceeds 1000 lines, routes/webhooks.py exceeds 1100 lines, routes/mission.py exceeds 2500 lines, routes/asset_studio_aiohttp.py exceeds 960 lines
