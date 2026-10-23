# ComfyUI-LingKe

LingKe AI (灵客AI) API nodes for ComfyUI — call cloud image / video / audio / chat models directly inside your workflows. No GPU required.

灵客AI API 节点：在 ComfyUI 工作流里直接调用灵客AI 云端的生图、生视频、音频与对话模型，本机无需显卡。

## Nodes / 节点

| Node | Output | 说明 |
|---|---|---|
| LingKe AI Image Generation | IMAGE | 文生图 / 图生图，参考图支持批次多张 |
| LingKe AI Video Generation | VIDEO | 文生视频 / 首尾帧生视频 |
| LingKe AI Audio Generation | AUDIO | 语音、音乐，可接参考音频 |
| LingKe AI Chat (LLM) | STRING | 对话模型，适合扩写提示词 |
| LingKe AI Model Params | STRING | 查看某个模型可填的参数，用于写 params_json |
| LingKe AI Balance | STRING | 查看余额 |

The model dropdown is fetched from the API (cached 6h, delete `models_cache.json` and restart to refresh).
模型下拉清单从接口拉取并缓存 6 小时，删除 `models_cache.json` 后重启即可刷新。

A ready-to-run example is in `example_workflows/` (also shown in ComfyUI's template browser).
`example_workflows/` 里有可直接运行的示例工作流（ComfyUI 模板浏览器里也能看到）。

## Install / 安装

1. Clone into `ComfyUI/custom_nodes/`:
   ```
   git clone https://github.com/lingkeai/ComfyUI-LingKe
   ```
2. Create an API key at [lingkeai.ai](https://lingkeai.ai) (开放 API). Copy `config.example.json` to `config.json` and fill it in. / 在 lingkeai.ai 的「开放 API」创建 Key，复制 `config.example.json` 为 `config.json` 并填入：
   ```json
   { "api_key": "sk-xxxx" }
   ```
   Or set the env var `LINGKE_API_KEY`. / 也可以用环境变量 `LINGKE_API_KEY`。
3. Restart ComfyUI. Search `LingKe` (or 灵客) on the canvas to add nodes.

> The API key is never stored in workflow files, so sharing a workflow won't leak it.
> API Key 不会写进工作流文件，分享工作流不会泄露。

## Notes / 注意

- Every run is billed. Changing `seed` (or leaving it on "randomize") triggers a new paid generation; set it to "fixed" to reuse results. / 每次运行都会计费，`seed` 变化即重新生成；设为 fixed 可复用结果。
- Cancelling in ComfyUI only stops waiting; the cloud task keeps running and is still billed. / 在 ComfyUI 里取消只是停止等待，云端任务仍会继续并计费。
- Input images/audio are sent inline (≤9MB each, ≤28MB total). Reference videos must be passed as public URLs in `params_json`. / 参考视频需在 `params_json` 里传公网直链。

## License

GPL-3.0
