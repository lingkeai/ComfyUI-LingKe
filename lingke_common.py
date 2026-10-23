import json
import os
import uuid

import comfy.model_management
import comfy.utils
import folder_paths

from .lingke_client import LingKeClient, LingKeError, download, log
from .lingke_convert import (
    audio_to_data_url,
    bytes_to_audio,
    bytes_to_image_tensor,
    check_total,
    image_tensor_to_data_urls,
    url_ext,
)

CATEGORY = "LingKe AI"
SEED_MAX = 2147483647

SEED_INPUT = ("INT", {
    "default": 0, "min": 0, "max": SEED_MAX, "control_after_generate": True,
    "tooltip": "Change to re-run (each run is billed). Sent to the model only if it supports seed. / 改变即重新生成（每次都会计费），模型支持 seed 时才会传",
})

PARAMS_TOOLTIP = (
    "Extra model params as JSON, e.g. {\"aspect_ratio\": \"16:9\"}; overrides the widgets above. "
    "Use the LingKe AI Model Params node to see what a model accepts. / "
    "额外模型参数 JSON，例如 {\"aspect_ratio\": \"16:9\"}，会覆盖上方控件；可用「灵客AI 模型参数」节点查看模型支持哪些参数"
)

RETURNS = {
    "image": (("IMAGE", "STRING", "STRING"), ("image", "urls", "task_id")),
    "video": (("VIDEO", "STRING", "STRING"), ("video", "url", "task_id")),
    "audio": (("AUDIO", "STRING", "STRING"), ("audio", "urls", "task_id")),
}


def parse_params(params_json):
    s = (params_json or "").strip()
    if not s:
        return {}
    try:
        v = json.loads(s)
    except json.JSONDecodeError as e:
        raise LingKeError(f"params_json is not valid JSON / params_json 不是合法 JSON: {e}") from None
    if not isinstance(v, dict):
        raise LingKeError("params_json must be a JSON object / params_json 必须是 JSON 对象 {...}")
    return v


def put(params, key, values):
    # 开放 API 约定：复数名上传参数（images/videos/...）一律传数组
    plural = len(values) > 1 or (key.endswith("s") and not key.endswith("ss"))
    params[key] = values if plural else values[0]


def put_images(params, key, image):
    put(params, key, image_tensor_to_data_urls(image))


def put_audio(params, key, audio):
    put(params, key, [audio_to_data_url(audio)])


def has_param(meta, name):
    return any(p.get("name") == name for p in (meta or {}).get("params", []))


def run_task(model, prompt, params):
    if not (prompt or "").strip():
        raise LingKeError("Prompt is required / 提示词不能为空")
    check_total(v for val in params.values() for v in (val if isinstance(val, list) else [val]))
    client = LingKeClient()
    task_id = client.submit(model, prompt, params)
    log(f"{model} task {task_id} submitted")
    pbar = comfy.utils.ProgressBar(100)

    def on_progress(st):
        try:
            pbar.update_absolute(min(99, int(float(st.get("progress") or 0))), 100)
        except (TypeError, ValueError):
            pass

    st = client.wait(task_id, on_progress, comfy.model_management.throw_exception_if_processing_interrupted)
    pbar.update_absolute(100, 100)
    urls = st.get("result_urls") or ([st["result_url"]] if st.get("result_url") else [])
    if not urls:
        raise LingKeError(f"Task {task_id} succeeded without result URL / 任务成功但没有结果地址")
    log(f"task {task_id} done, cost={st.get('cost')}")
    return task_id, urls, st


def _save_temp(task_id, url, default_ext):
    out_dir = os.path.join(folder_paths.get_temp_directory(), "lingke")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{task_id}_{uuid.uuid4().hex[:6]}{url_ext(url, default_ext)}")
    with open(path, "wb") as f:
        f.write(download(url))
    return path


def build_result(media_type, model, task_id, urls, st):
    """把任务结果转成 ComfyUI 输出，并带上 ui.lingke 供前端扩展显示任务号与实扣。"""
    if media_type == "image":
        out = (bytes_to_image_tensor([download(u) for u in urls]), "\n".join(urls), task_id)
    elif media_type == "video":
        try:
            from comfy_api.input_impl import VideoFromFile
        except ImportError:
            raise LingKeError("This ComfyUI is too old for VIDEO outputs, please update. / ComfyUI 版本过旧不支持 VIDEO，请升级") from None
        out = (VideoFromFile(_save_temp(task_id, urls[0], ".mp4")), urls[0], task_id)
    else:
        # 多首结果（如 Suno 一次两首）只解码第一首，其余见 urls
        out = (bytes_to_audio(download(urls[0])), "\n".join(urls), task_id)
    info = {"task_id": task_id, "model": model, "cost": st.get("cost"), "count": len(urls)}
    return {"ui": {"lingke": [info]}, "result": out}
