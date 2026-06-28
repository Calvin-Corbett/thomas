import asyncio

from thomas.core.config import load_config
from thomas.server.app_lifecycle import serve_async

asyncio.run(serve_async(load_config(), host="127.0.0.1", port=8906))
