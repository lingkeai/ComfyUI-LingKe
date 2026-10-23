import json

from .lingke_client import LingKeClient, LingKeError, get_model_meta, get_model_names, log
from .lingke_common import (
    CATEGORY,
    PARAMS_TOOLTIP,
    RETURNS,
    SEED_INPUT,
    build_result,
    has_param,
    parse_params,
    put_audio,
    put_images,
    run_task,
)

PARAM_KEY_TOOLTIP = (
    "Which upload param receives this input. 'auto' picks it from the model definition. / "
    "这路输入填到模型的哪个上传参数，auto 按模型定义自动选"
)
IMAGE_EXCLUDE = ("video", "audio", "voice", "music", "mask")


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


def _common_required(media_type):
    models = get_model_names(media_type)
    return {
        "model": (models, {"default": models[0]}),
        "prompt": ("STRING", {"multiline": True, "default": ""}),
        "params_json": ("STRING", {"multiline": True, "default": "{}", "tooltip": PARAMS_TOOLTIP}),
        "seed": SEED_INPUT,
    }


def _base_params(media_type, model, params_json, seed):
    params = parse_params(params_json)
    meta = get_model_meta(media_type, model)
    if has_param(meta, "seed") and "seed" not in params:
        params["seed"] = seed
    return params, meta


class LingKeImageGen:
    CATEGORY = CATEGORY
    FUNCTION = "run"
    RETURN_TYPES, RETURN_NAMES = RETURNS["image"]
    DESCRIPTION = "Generate images with any LingKe AI image model. / 调用灵客AI任意生图模型"

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
            put_images(params, _resolve_key(images_param, meta, model, ("image", "img", "ref"), IMAGE_EXCLUDE), images)
        return build_result("image", model, *run_task(model, prompt, params))


class LingKeVideoGen:
    CATEGORY = CATEGORY
    FUNCTION = "run"
    RETURN_TYPES, RETURN_NAMES = RETURNS["video"]
    DESCRIPTION = "Generate videos with any LingKe AI video model. / 调用灵客AI任意生视频模型"

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
        params, meta = _base_params("video", model, params_json, seed)
        end_words = ("last", "end", "tail")
        taken = []
        if end_image is not None:
            key = _resolve_key(end_image_param, meta, model, end_words, IMAGE_EXCLUDE)
            put_images(params, key, end_image)
            taken.append(key)
        if image is not None:
            key = _resolve_key(image_param, meta, model, ("first", "start", "image", "img", "ref"),
                               IMAGE_EXCLUDE + end_words, taken)
            put_images(params, key, image)
        return build_result("video", model, *run_task(model, prompt, params))


class LingKeAudioGen:
    CATEGORY = CATEGORY
    FUNCTION = "run"
    RETURN_TYPES, RETURN_NAMES = RETURNS["audio"]
    DESCRIPTION = "Generate speech / music with any LingKe AI audio model. / 调用灵客AI任意音频模型生成语音或音乐"

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
            put_audio(params, _resolve_key(audio_param, meta, model, ("audio", "voice", "sound", "ref"), ("image", "video")), audio)
        return build_result("audio", model, *run_task(model, prompt, params))


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
                "seed": SEED_INPUT,
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
            lines.append(f"- {p['name']} ({p.get('type')}{', required' if p.get('required') else ''}): {p.get('label') or ''}")
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
        return {"required": {"seed": SEED_INPUT}}

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
