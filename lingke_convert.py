import base64
import io
import os
import urllib.parse
import wave

import numpy as np
import torch
from PIL import Image, ImageOps

from .lingke_client import LingKeError

# 开放 API 内联 base64 上限：单文件解码后 ≤10MB，单次请求合计 ≤30MB
SINGLE_LIMIT = 9 * 1024 * 1024
TOTAL_LIMIT = 28 * 1024 * 1024


def _data_url(mime, raw):
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def image_tensor_to_data_urls(image):
    """IMAGE [B,H,W,C] float 0~1 → 每张一个 data URL。平台收到后转存对象存储，不会把 base64 入库。"""
    urls = []
    for i in range(image.shape[0]):
        arr = (image[i].cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
        pil = Image.fromarray(arr)
        buf = io.BytesIO()
        pil.save(buf, format="PNG", optimize=True)
        raw, mime = buf.getvalue(), "image/png"
        if len(raw) > SINGLE_LIMIT:
            buf = io.BytesIO()
            pil.convert("RGB").save(buf, format="JPEG", quality=92)
            raw, mime = buf.getvalue(), "image/jpeg"
        if len(raw) > SINGLE_LIMIT:
            raise LingKeError("Input image too large (>9MB after JPEG) / 输入图片过大，请先缩小尺寸")
        urls.append(_data_url(mime, raw))
    return urls


def audio_to_data_url(audio):
    """AUDIO {'waveform': [B,C,T], 'sample_rate'} → 16-bit WAV data URL（取第一条）。"""
    wav = audio["waveform"][0].cpu().clamp(-1, 1).numpy()
    pcm = (wav.T * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(wav.shape[0])
        w.setsampwidth(2)
        w.setframerate(int(audio["sample_rate"]))
        w.writeframes(pcm.tobytes())
    raw = buf.getvalue()
    if len(raw) > SINGLE_LIMIT:
        raise LingKeError("Input audio too large (>9MB WAV) / 输入音频过大，请截短后再传")
    return _data_url("audio/wav", raw)


def check_total(values):
    total = sum(len(v) for v in values if isinstance(v, str) and v.startswith("data:"))
    if total > TOTAL_LIMIT * 4 // 3:
        raise LingKeError("Inline inputs exceed 28MB in total / 输入素材合计过大，请减少张数或缩小尺寸")


def bytes_to_image_tensor(blobs):
    imgs = []
    for raw in blobs:
        pil = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
        if imgs and pil.size != imgs[0].size:
            # 同一批次张量必须同尺寸
            pil = pil.resize(imgs[0].size, Image.LANCZOS)
        imgs.append(pil)
    arrs = [np.asarray(p).astype(np.float32) / 255.0 for p in imgs]
    return torch.from_numpy(np.stack(arrs, axis=0))


def bytes_to_audio(raw):
    import av

    with av.open(io.BytesIO(raw)) as container:
        stream = container.streams.audio[0]
        sr = stream.codec_context.sample_rate or 44100
        layout = stream.codec_context.layout.name if stream.codec_context.layout else "stereo"
        resampler = av.AudioResampler(format="fltp", layout=layout, rate=sr)
        chunks = []
        for frame in container.decode(stream):
            for f in resampler.resample(frame):
                chunks.append(f.to_ndarray())
        for f in resampler.resample(None):
            chunks.append(f.to_ndarray())
    if not chunks:
        raise LingKeError("Empty audio result / 音频结果为空")
    wav = np.concatenate(chunks, axis=1).astype(np.float32)
    return {"waveform": torch.from_numpy(wav).unsqueeze(0), "sample_rate": sr}


def url_ext(url, default):
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    return ext if ext and len(ext) <= 5 else default
