"""给前端扩展用的本地路由（挂在 ComfyUI 自己的服务上，API Key 不出本机进程）。"""
import asyncio
import json

from .lingke_client import LingKeError, log
from .lingke_featured import FEATURED_NODE_MODELS
from .lingke_pricing import estimate

GENERIC_MEDIA_NODES = ["LingKeImageGen", "LingKeVideoGen", "LingKeAudioGen"]


def register():
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:
        return
    routes = PromptServer.instance.routes

    @routes.get("/lingke/nodes")
    async def lingke_nodes(request):
        return web.json_response({"featured": FEATURED_NODE_MODELS, "generic": GENERIC_MEDIA_NODES})

    @routes.get("/lingke/estimate")
    async def lingke_estimate(request):
        model = (request.query.get("model") or "").strip()
        if not model:
            return web.json_response({"error": "missing model"}, status=400)
        try:
            params = json.loads(request.query.get("params") or "{}")
            if not isinstance(params, dict):
                params = {}
        except json.JSONDecodeError:
            params = {}
        try:
            return web.json_response(await asyncio.to_thread(estimate, model, params))
        except LingKeError as e:
            return web.json_response({"error": str(e)})
        except Exception as e:
            log(f"estimate {model} failed: {e}")
            return web.json_response({"error": str(e)})
