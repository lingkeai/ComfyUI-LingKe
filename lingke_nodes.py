import json
import os
import uuid

import comfy.model_management
import comfy.utils
import folder_paths

from .lingke_client import LingKeClient, LingKeError, download, get_model_meta, get_model_names, log
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

PARAMS_TOOLTIP = (
    "Extra model params as JSON, e.g. {\"aspect_ratio\": \"16:9\"}. Use the LingKe Model Params node to see what a model accepts. / "
    "模型参数 JSON，例如 {\"aspect_ratio\": \"16:9\"}；可用「LingKe 模型参数」节点查看该模型支持哪些参数"
)
PARAM_KEY_TOOLTIP = (
    "Which upload param receives this input. 'auto' picks it from the model definition. / "
    "这路输入填到模型的哪个上传参数，auto 按模型定义自动选"
)


def _parse_params(params_json):
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


def _pick_upload_key(meta, prefer, exclude, taken=()):
    uploads = [p["name"] for p in (meta or {}).get("params", []) if p.get("type") == "upload" and p["name"] not in taken]
    allowed = [n for n in uploads if not any(x in n.lower() for x in exclude)]
    for kw in prefer:
        for n in allowed:
            if kw in n.lower():
                return n
    return allowed[0] if allowed else None


def _resolve_key(choice, meta, model, prefer, exclude, taken=()):
    if choice and choice.strip() and choice.strip() != "auto":
        return choice.strip()
    key = _pick_upload_key(meta, prefer, exclude, taken)
    if not key:
        raise LingKeError(
            f"Model {model} has no matching upload param; set the *_param input manually. / "
            f"模型 {model} 没有可自动匹配的上传参数，请手动填写对应的 *_param"
        )
    return key


def _put(params, key, values):
    plural = len(values) > 1 or (key.endswith("s") and not key.endswith("ss"))
    params[key] = values if plural else values[0]


def _has_param(meta, name):
    return any(p.get("name") == name for p in (meta or {}).get("params", []))


def _run(model, prompt, params):
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
    return task_id, urls


def _save_temp(task_id, url, default_ext):
    out_dir = os.path.join(folder_paths.get_temp_directory(), "lingke")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{task_id}_{uuid.uuid4().hex[:6]}{url_ext(url, default_ext)}")
    with open(path, "wb") as f:
        f.write(download(url))
    return path


def _common_required(media_type):
    models = get_model_names(media_type)
    return {
        "model": (models, {"default": models[0]}),
        "prompt": ("STRING", {"multiline": True, "default": ""}),
        "params_json": ("STRING", {"multiline": True, "default": "{}", "tooltip": PARAMS_TOOLTIP}),
        "seed": ("INT", {"default": 0, "min": 0, "max": SEED_MAX, "control_after_generate": True,
                         "tooltip": "Change to re-run (each run is billed). Sent to the model only if it supports seed. / 改变即重新生成（每次都会计费），模型支持 seed 时才会传"}),
    }


def _base_params(media_type, model, params_json, seed):
    params = _parse_params(params_json)
    meta = get_model_meta(media_type, model)
    if _has_param(meta, "seed") and "seed" not in params:
        params["seed"] = seed
    return params, meta


IMAGE_EXCLUDE = ("video", "audio", "voice", "music", "mask")


class LingKeImageGen:
    CATEGORY = CATEGORY
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "urls", "task_id")
    DESCRIPTION = "Generate images with LingKe AI cloud models. / 调用灵客AI云端模型生图"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": _common_required("image"),
            "optional": {
                "images": ("IMAGE", {"tooltip": "Reference images (batch supported) / 参考图，支持批次多张"}),
                "images_param": ("STRING", {"default": "auto", "tooltip": PARAM_KEY_TOOLTIP}),
            },
        }

    def run(self, model, prompt, params_json, seed, images=None, images_param="auto"):
        params, meta = _base_params("image", model, params_json, seed)
        if images is not None:
            key = _resolve_key(images_param, meta, model, ("image", "img", "ref"), IMAGE_EXCLUDE)
            _put(params, key, image_tensor_to_data_urls(images))
        task_id, urls = _run(model, prompt, params)
        image = bytes_to_image_tensor([download(u) for u in urls])
        return (image, "\n".join(urls), task_id)


class LingKeVideoGen:
    CATEGORY = CATEGORY
    FUNCTION = "run"
    RETURN_TYPES = ("VIDEO", "STRING", "STRING")
    RETURN_NAMES = ("video", "url", "task_id")
    DESCRIPTION = "Generate videos with LingKe AI cloud models. / 调用灵客AI云端模型生视频"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": _common_required("video"),
            "optional": {
                "image": ("IMAGE", {"tooltip": "First frame / reference images / 首帧或参考图"}),
                "image_param": ("STRING", {"default": "auto", "tooltip": PARAM_KEY_TOOLTIP}),
                "end_image": ("IMAGE", {"tooltip": "Last frame / 尾帧"}),
                "end_image_param": ("STRING", {"default": "auto", "tooltip": PARAM_KEY_TOOLTIP}),
            },
        }

    def run(self, model, prompt, params_json, seed, image=None, image_param="auto", end_image=None, end_image_param="auto"):
        try:
            from comfy_api.input_impl import VideoFromFile
        except ImportError:
            raise LingKeError("This ComfyUI is too old for VIDEO outputs, please update. / ComfyUI 版本过旧不支持 VIDEO，请升级") from None

        params, meta = _base_params("video", model, params_json, seed)
        end_words = ("last", "end", "tail")
        taken = []
        if end_image is not None:
            key = _resolve_key(end_image_param, meta, model, end_words, IMAGE_EXCLUDE)
            _put(params, key, image_tensor_to_data_urls(end_image))
            taken.append(key)
        if image is not None:
            key = _resolve_key(image_param, meta, model, ("first", "start", "image", "img", "ref"),
                               IMAGE_EXCLUDE + end_words, taken)
            _put(params, key, image_tensor_to_data_urls(image))
        task_id, urls = _run(model, prompt, params)
        path = _save_temp(task_id, urls[0], ".mp4")
        return (VideoFromFile(path), urls[0], task_id)


class LingKeAudioGen:
    CATEGORY = CATEGORY
    FUNCTION = "run"
    RETURN_TYPES = ("AUDIO", "STRING", "STRING")
    RETURN_NAMES = ("audio", "urls", "task_id")
    DESCRIPTION = "Generate speech / music with LingKe AI cloud models. / 调用灵客AI云端模型生成语音或音乐"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": _common_required("audio"),
            "optional": {
                "audio": ("AUDIO", {"tooltip": "Reference audio / 参考音频"}),
                "audio_param": ("STRING", {"default": "auto", "tooltip": PARAM_KEY_TOOLTIP}),
            },
        }

    def run(self, model, prompt, params_json, seed, audio=None, audio_param="auto"):
        params, meta = _base_params("audio", model, params_json, seed)
        if audio is not None:
            key = _resolve_key(audio_param, meta, model, ("audio", "voice", "sound", "ref"), ("image", "video"))
            _put(params, key, [audio_to_data_url(audio)])
        task_id, urls = _run(model, prompt, params)
        # 多首结果（如 Suno 一次两首）只解码第一首，其余见 urls
        return (bytes_to_audio(download(urls[0])), "\n".join(urls), task_id)


class LingKeChat:
    CATEGORY = CATEGORY
    FUNCTION = "run"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    DESCRIPTION = "Call LingKe AI chat models, e.g. to expand prompts. / 调用灵客AI对话模型，如扩写提示词"

    @classmethod
    def INPUT_TYPES(cls):
        models = get_model_names("chat")
        return {
            "required": {
                "model": (models, {"default": models[0]}),
                "system": ("STRING", {"multiline": True, "default": ""}),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "seed": ("INT", {"default": 0, "min": 0, "max": SEED_MAX, "control_after_generate": True}),
            }
        }

    def run(self, model, system, prompt, seed):
        if not (prompt or "").strip():
            raise LingKeError("Prompt is required / 提示词不能为空")
        messages = [{"role": "system", "content": system}] if (system or "").strip() else []
        messages.append({"role": "user", "content": prompt})
        return (LingKeClient().chat(model, messages),)


class LingKeModelParams:
    CATEGORY = CATEGORY
    FUNCTION = "run"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("info",)
    DESCRIPTION = "Show the params a model accepts, for writing params_json. / 查看模型可用参数，用于填写 params_json"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "media_type": (["image", "video", "audio"],),
                "model": ("STRING", {"default": "tt-image-2.5"}),
            }
        }

    def run(self, media_type, model):
        meta = get_model_meta(media_type, model.strip())
        if not meta:
            raise LingKeError(f"Model {model} not found in {media_type} list / 在 {media_type} 模型清单里找不到 {model}")
        lines = [f"{meta['name']}  {meta.get('display_name') or ''}", meta.get("description") or ""]
        if meta.get("input_hint"):
            lines.append(meta["input_hint"])
        lines.append("")
        for p in meta.get("params", []):
            head = f"- {p['name']} ({p.get('type')}{', required' if p.get('required') else ''}): {p.get('label') or ''}"
            lines.append(head)
            if p.get("options"):
                lines.append("    options: " + ", ".join(o["value"] for o in p["options"]))
            if p.get("description"):
                lines.append("    " + p["description"].replace("\n", " "))
        text = "\n".join(lines)
        log(text)
        return (text,)


class LingKeBalance:
    CATEGORY = CATEGORY
    FUNCTION = "run"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("balance",)
    DESCRIPTION = "Show account balance. / 查看账户余额"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"seed": ("INT", {"default": 0, "min": 0, "max": SEED_MAX, "control_after_generate": True})}}

    def run(self, seed):
        text = json.dumps(LingKeClient().balance(), ensure_ascii=False, indent=2)
        log(text)
        return (text,)


NODE_CLASS_MAPPINGS = {
    "LingKeImageGen": LingKeImageGen,
    "LingKeVideoGen": LingKeVideoGen,
    "LingKeAudioGen": LingKeAudioGen,
    "LingKeChat": LingKeChat,
    "LingKeModelParams": LingKeModelParams,
    "LingKeBalance": LingKeBalance,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LingKeImageGen": "LingKe AI Image Generation",
    "LingKeVideoGen": "LingKe AI Video Generation",
    "LingKeAudioGen": "LingKe AI Audio Generation",
    "LingKeChat": "LingKe AI Chat (LLM)",
    "LingKeModelParams": "LingKe AI Model Params",
    "LingKeBalance": "LingKe AI Balance",
}
