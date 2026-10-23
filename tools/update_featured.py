"""刷新热门模型快照 featured_models.json，并同步专属节点的中文语言包。

用法（在节点包根目录）：python tools/update_featured.py
读取 config.json / LINGKE_API_KEY 拉 /v1/media/models。改 FEATURED 增删专属节点；
已发布的模型若参数顺序变化，旧工作流控件会错位，发版前请在 Desktop 里打开示例工作流核对。
"""
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = os.path.join(ROOT, "featured_models.json")

FEATURED = {
    "image": ["tt-image-2.5", "banana-2.1", "tt-image-2"],
    "video": ["seedance-2.0-anci", "seedance-2.5-guanfang-anmiao", "gk-video-3.5", "viduq4-preview", "minimax-h3"],
    "audio": ["suno-v6", "doubao-tts-2.0", "music-2.5+"],
}
URL_NOTE = re.compile(r"（传可公开访问的文件直链 URL.*$", re.S)
BRAND = {"zh": "灵客AI", "zh-TW": "靈客AI"}
COMMON_INPUTS = {
    "zh": {"prompt": "提示词", "seed": "种子", "params_json": "参数JSON"},
    "zh-TW": {"prompt": "提示詞", "seed": "種子", "params_json": "參數JSON"},
}


def node_id(model):
    return "LingKe_" + re.sub(r"[^0-9A-Za-z]+", "_", model).strip("_")


def load_config():
    cfg = {}
    path = os.path.join(ROOT, "config.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    key = os.environ.get("LINGKE_API_KEY") or cfg.get("api_key")
    base = (os.environ.get("LINGKE_BASE_URL") or cfg.get("base_url") or "https://api.lk888.ai/api").rstrip("/")
    if not key:
        sys.exit("missing api key")
    return key, base


def fetch(base, key, media_type):
    req = urllib.request.Request(f"{base}/v1/media/models?type={media_type}", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return {m["name"]: m for m in json.loads(r.read())["models"]}


def main():
    key, base = load_config()
    old = {}
    if os.path.isfile(SNAPSHOT):
        with open(SNAPSHOT, encoding="utf-8") as f:
            old = json.load(f)

    snapshot = {}
    for media_type, names in FEATURED.items():
        live = fetch(base, key, media_type)
        for name in names:
            if name not in live:
                print(f"skip {name}: not in live list")
                continue
            m = live[name]
            old_opts = {p["name"]: p.get("options") for p in old.get(name, {}).get("params", [])}
            for p in m["params"]:
                if p.get("description"):
                    p["description"] = URL_NOTE.sub("", p["description"]).strip()
                # 后端发版前 segment 没有 options，沿用旧快照
                if p["type"] == "segment" and not p.get("options") and old_opts.get(p["name"]):
                    p["options"] = old_opts[p["name"]]
            m["type"] = media_type
            snapshot[name] = m

    with open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=1)

    for lang in ("zh", "zh-TW"):
        path = os.path.join(ROOT, "locales", lang, "nodeDefs.json")
        with open(path, encoding="utf-8") as f:
            defs = json.load(f)
        defs = {k: v for k, v in defs.items() if not k.startswith("LingKe_")}
        for name, m in snapshot.items():
            inputs = {k: {"name": v} for k, v in COMMON_INPUTS[lang].items()}
            for p in m["params"]:
                if p.get("label") and p["name"] not in inputs:
                    inputs[p["name"]] = {"name": p["label"]}
            defs[node_id(name)] = {"display_name": f"{BRAND[lang]} · {m.get('display_name') or name}", "inputs": inputs}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(defs, f, ensure_ascii=False, indent=2)
            f.write("\n")
    print(f"{len(snapshot)} featured models written")


if __name__ == "__main__":
    main()
