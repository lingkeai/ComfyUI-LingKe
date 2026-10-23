import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .lingke_config import CACHE_PATH, load_config

VERSION = "0.2.0"
USER_AGENT = f"ComfyUI-LingKe/{VERSION}"

POLL_INTERVAL = 5          # 开放 API 文档建议的轮询间隔（秒）
MAX_WAIT_SECONDS = 4 * 3600  # 视频排队兜底可达数小时，只做防挂死的上限
MODELS_TTL = 6 * 3600
MODELS_RETRY_AFTER = 300

# 拉不到模型清单（没配 Key / 断网）且无缓存时的兜底下拉
DEFAULT_MODELS = {
    "image": ["tt-image-2.5", "tt-image-2", "banana-2.1"],
    "video": ["seedance-2.0-anci", "seedance-2.5-guanfang-anmiao", "gk-video-3.5", "viduq4-preview"],
    "audio": ["suno-v6", "speech-2.8", "doubao-tts-2.0"],
    "chat": ["gem-3.8-flash", "tt-6-luna", "hk-5-5"],
}


class LingKeError(Exception):
    pass


_logger = logging.getLogger("LingKe")


def log(msg):
    # 走 ComfyUI 已配置的 logging：print 在 stdout 重定向时会被缓冲看不到；
    # 且 GBK 控制台编码失败时 logging 只报 handler 错误，不会像 print 那样抛异常打断节点
    _logger.info(f"[LingKe] {msg}")


def _err_msg(obj):
    if not isinstance(obj, dict):
        return str(obj)[:500]
    err = obj.get("error")
    if isinstance(err, dict):
        return err.get("message") or json.dumps(err, ensure_ascii=False)
    if isinstance(err, str) and err:
        return err
    msg = obj.get("msg") or obj.get("message") or json.dumps(obj, ensure_ascii=False)[:500]
    if obj.get("error_code"):
        msg = f"[{obj['error_code']}] {msg}"
    return msg


class LingKeClient:
    def __init__(self):
        self.api_key, self.base_url = load_config()

    def _request(self, method, path, body=None, timeout=60):
        if not self.api_key:
            raise LingKeError(
                "LingKe API Key not configured: set LINGKE_API_KEY or fill config.json in the node folder. / "
                "未设置 API Key：请设环境变量 LINGKE_API_KEY，或在节点包目录填写 config.json"
            )
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                msg = _err_msg(json.loads(raw))
            except Exception:
                msg = raw.decode("utf-8", "replace")[:500]
            raise LingKeError(f"HTTP {e.code}: {msg}") from None
        try:
            obj = json.loads(raw)
        except Exception:
            raise LingKeError(f"Invalid response / 响应不是 JSON: {raw[:300]!r}") from None
        # 部分接口用 HTTP 200 + code!=200 表示业务失败
        if isinstance(obj, dict) and "code" in obj and obj.get("code") not in (0, 200, "0", "200"):
            raise LingKeError(_err_msg(obj))
        return obj

    def submit(self, model, prompt, params):
        # 不做自动重试：请求超时也可能已建任务，重提会重复扣费
        resp = self._request(
            "POST", "/v1/media/generate",
            {"model": model, "prompt": prompt, "params": params},
            timeout=300,
        )
        data = resp.get("data") if isinstance(resp.get("data"), dict) else resp
        task_id = data.get("task_id") or resp.get("task_id")
        if not task_id:
            raise LingKeError(f"No task_id in response / 提交成功但没有返回 task_id: {json.dumps(resp, ensure_ascii=False)[:300]}")
        return str(task_id)

    def status(self, task_id):
        return self._request("GET", "/v1/media/status?task_id=" + urllib.parse.quote(task_id), timeout=30)

    def wait(self, task_id, on_progress=None, check_interrupt=None):
        start = time.time()
        net_errors = 0
        while True:
            if time.time() - start > MAX_WAIT_SECONDS:
                raise LingKeError(f"Task {task_id} still running after {MAX_WAIT_SECONDS // 3600}h / 任务等待超时，可稍后在网站查看结果")
            try:
                st = self.status(task_id)
                net_errors = 0
            except LingKeError:
                raise
            except Exception as e:
                # 网络抖动只重试查询，绝不重提任务
                net_errors += 1
                log(f"poll task {task_id} failed ({net_errors}): {e}")
                st = None
            if st is not None:
                if on_progress:
                    on_progress(st)
                if st.get("is_final"):
                    if st.get("state") == "success":
                        return st
                    code = st.get("error_code")
                    raise LingKeError(f"Task {task_id} failed{f' [{code}]' if code else ''}: {st.get('error') or st.get('status')}")
            deadline = time.time() + POLL_INTERVAL
            while time.time() < deadline:
                if check_interrupt:
                    try:
                        check_interrupt()
                    except BaseException:
                        log(f"stopped waiting; cloud task {task_id} keeps running and is still billed, "
                            f"check the result on the website / 已停止等待，云端任务 {task_id} 仍会继续并计费，可到网站查看结果")
                        raise
                time.sleep(0.5)

    def chat(self, model, messages, timeout=600):
        resp = self._request("POST", "/v1/chat/completions", {"model": model, "messages": messages, "stream": False}, timeout=timeout)
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LingKeError(f"Unexpected chat response / 对话响应格式异常: {json.dumps(resp, ensure_ascii=False)[:300]}") from None

    def balance(self):
        return self._request("GET", "/v1/skills/balance")

    def list_models(self, media_type):
        resp = self._request("GET", "/v1/media/models?type=" + urllib.parse.quote(media_type), timeout=15)
        return resp.get("models") or []


def download(url, timeout=600):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---- 模型清单缓存：INPUT_TYPES 每次刷新前端都会调，必须走缓存 ----

_mem_cache = None
_last_fail = {}


def _read_cache():
    global _mem_cache
    if _mem_cache is None:
        _mem_cache = {}
        if os.path.isfile(CACHE_PATH):
            try:
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    _mem_cache = json.load(f) or {}
            except Exception:
                _mem_cache = {}
    return _mem_cache


def _write_cache(cache):
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        log(f"write models cache failed: {e}")


def get_models(media_type, force=False):
    cache = _read_cache()
    entry = cache.get(media_type)
    fresh = entry and time.time() - entry.get("ts", 0) < MODELS_TTL
    if force or not fresh:
        if force or time.time() - _last_fail.get(media_type, 0) > MODELS_RETRY_AFTER:
            try:
                models = LingKeClient().list_models(media_type)
                if models:
                    entry = {"ts": time.time(), "models": models}
                    cache[media_type] = entry
                    _write_cache(cache)
            except Exception as e:
                _last_fail[media_type] = time.time()
                log(f"fetch {media_type} models failed, using cache/defaults: {e}")
    return (entry or {}).get("models") or []


def get_model_names(media_type):
    names = [m["name"] for m in get_models(media_type) if m.get("name")]
    return names or list(DEFAULT_MODELS.get(media_type, []))


def get_model_meta(media_type, name):
    for m in get_models(media_type):
        if m.get("name") == name:
            return m
    return None
