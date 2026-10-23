"""热门模型专属节点：参数直接做成下拉/输入框/接口，免写 params_json。

控件顺序固定取自随包快照 featured_models.json：ComfyUI 工作流按顺序存控件值，
若跟着线上参数增删控件，已保存的工作流会错位。线上数据只用来刷新下拉选项；
快照里没有的新参数走 params_json。
"""
import json
import os
import re

from .lingke_client import get_model_meta, log
from .lingke_common import (
    CATEGORY,
    PARAMS_TOOLTIP,
    RETURNS,
    SEED_INPUT,
    build_result,
    parse_params,
    put,
    put_audio,
    put_images,
    run_task,
)
from .lingke_config import PACK_DIR

SNAPSHOT_PATH = os.path.join(PACK_DIR, "featured_models.json")
DEFAULT = "default"
CHOICE_TYPES = ("select", "radio", "switch", "checkbox", "segment")
TEXT_TYPES = ("textarea", "input", "number", "slider")
REF_PARAMS = ("image_url", "video_url", "audio_url")
_URL_NOTE = re.compile(r"（传可公开访问的文件直链 URL.*$", re.S)


def _load_snapshot():
    try:
        with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"load featured_models.json failed: {e}")
        return {}


SNAPSHOT = _load_snapshot()


def node_id(model):
    return "LingKe_" + re.sub(r"[^0-9A-Za-z]+", "_", model).strip("_")


def upload_kind(name):
    n = name.lower()
    if "video" in n:
        return "video"
    if any(k in n for k in ("audio", "voice", "sound", "music")):
        return "audio"
    return "image"


def _tooltip(p):
    desc = _URL_NOTE.sub("", p.get("description") or "").strip()
    return f"{p.get('label') or p['name']} ({p['name']})" + (f"\n{desc}" if desc else "")


def _pick_default(name, values):
    if name == "duration" and "5" in values:
        return "5"
    return values[0]


def resolved_params(model):
    """快照参数顺序 + 线上最新选项。"""
    snap = SNAPSHOT[model]
    live = get_model_meta(snap["type"], model)
    live_opts = {p["name"]: p.get("options") for p in (live or {}).get("params", [])}
    out = []
    for p in snap["params"]:
        opts = live_opts.get(p["name"])
        out.append(dict(p, options=opts) if opts else p)
    return out


class _FeaturedBase:
    MODEL = ""
    MEDIA = ""
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        required = {"prompt": ("STRING", {"multiline": True, "default": ""})}
        optional = {}
        for p in resolved_params(cls.MODEL):
            name, t = p["name"], p.get("type")
            if name in ("prompt", "seed"):
                continue
            tip = _tooltip(p)
            values = [o["value"] for o in p.get("options") or []]
            if t in CHOICE_TYPES and values:
                if p.get("required") and t != "segment":
                    required[name] = (values, {"default": _pick_default(name, values), "tooltip": tip})
                else:
                    required[name] = ([DEFAULT] + values, {"default": DEFAULT, "tooltip": tip + "\n\ndefault = 不传，按模型默认 / not sent"})
            elif t == "upload":
                kind = upload_kind(name)
                if kind == "video":
                    optional[name] = ("STRING", {"default": "", "tooltip": tip + "\n\n填公网视频直链，多个用换行分隔 / public video URLs, one per line"})
                else:
                    optional[name] = ("AUDIO" if kind == "audio" else "IMAGE", {"tooltip": tip})
            elif t in TEXT_TYPES:
                required[name] = ("STRING", {"multiline": t == "textarea", "default": "", "tooltip": tip})
        required["seed"] = SEED_INPUT
        optional["params_json"] = ("STRING", {"multiline": True, "default": "{}", "tooltip": PARAMS_TOOLTIP})
        return {"required": required, "optional": optional}

    def run(self, prompt, seed, params_json="{}", **kwargs):
        defs = resolved_params(self.MODEL)
        params = {}
        mode_values = []
        for p in defs:
            name, t = p["name"], p.get("type")
            if name == "mode" and t == "segment":
                mode_values = [o["value"] for o in p.get("options") or []]
            value = kwargs.get(name)
            if value is None:
                continue
            if t == "upload":
                kind = upload_kind(name)
                if kind == "image":
                    put_images(params, name, value)
                elif kind == "audio":
                    put_audio(params, name, value)
                else:
                    urls = [u for u in re.split(r"[\s,]+", value) if u]
                    if urls:
                        put(params, name, urls)
            elif isinstance(value, str) and value.strip() and value != DEFAULT:
                params[name] = value.strip() if t != "textarea" else value
        # 模式没选时按接了哪路素材推断，避免首帧图被当成参考图
        if "mode" not in params and mode_values:
            if any(k in params for k in REF_PARAMS) and "cankaosheng" in mode_values:
                params["mode"] = "cankaosheng"
            elif "images" in params and "shouweizhen" in mode_values:
                params["mode"] = "shouweizhen"
        if any(p["name"] == "seed" for p in defs):
            params["seed"] = seed
        params.update(parse_params(params_json))
        return build_result(self.MEDIA, self.MODEL, *run_task(self.MODEL, prompt, params))


FEATURED_NODE_CLASS_MAPPINGS = {}
FEATURED_NODE_DISPLAY_NAME_MAPPINGS = {}
FEATURED_NODE_MODELS = {}

for _model, _snap in SNAPSHOT.items():
    _id = node_id(_model)
    _ret_types, _ret_names = RETURNS[_snap["type"]]
    FEATURED_NODE_CLASS_MAPPINGS[_id] = type(_id, (_FeaturedBase,), {
        "MODEL": _model,
        "MEDIA": _snap["type"],
        "CATEGORY": f"{CATEGORY}/{_snap['type']}",
        "RETURN_TYPES": _ret_types,
        "RETURN_NAMES": _ret_names,
        "DESCRIPTION": "\n\n".join(x for x in (_snap.get("description"), _snap.get("input_hint")) if x),
    })
    FEATURED_NODE_DISPLAY_NAME_MAPPINGS[_id] = f"LingKe AI · {_snap.get('display_name') or _model}"
    FEATURED_NODE_MODELS[_id] = _model
