import json
import os

PACK_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PACK_DIR, "config.json")
CACHE_PATH = os.path.join(PACK_DIR, "models_cache.json")

DEFAULT_BASE_URL = "https://api.lk888.ai/api"


def load_config():
    """读取 API Key 与 base_url。优先级：环境变量 > config.json > 默认地址。

    API Key 故意不做成节点输入：ComfyUI 工作流 JSON 会带上所有控件值，分享工作流就等于泄露 Key。
    """
    cfg = {}
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except Exception as e:
            print(f"[LingKe] config.json 解析失败，已忽略: {e}")

    api_key = os.environ.get("LINGKE_API_KEY") or cfg.get("api_key") or ""
    base_url = os.environ.get("LINGKE_BASE_URL") or cfg.get("base_url") or DEFAULT_BASE_URL
    return api_key.strip(), base_url.strip().rstrip("/")
