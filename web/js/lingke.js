// 本檔服务于 /extensions/ComfyUI-LingKe/js/，往上三层才是 /scripts/
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

// 节点下方一行说明：改参数时显示预估价，跑完显示任务号与实扣
const I18N = {
  zh: {
    est: "预估 ≈ {range} 算力{suffix}",
    perCall: " / 次",
    secs: "（{s} 秒）",
    prepay: "（未选时长，按 {s} 秒预扣）",
    token: "按 token 计费，跑完显示实扣",
    unavailable: "当前 API Key 没有可用渠道",
    noKey: "未配置 API Key（见节点包 README）",
    failed: "估价失败：{msg}",
    done: "✓ 任务 {id} · 实扣 {cost} 算力",
  },
  "zh-TW": {
    est: "預估 ≈ {range} 算力{suffix}",
    perCall: " / 次",
    secs: "（{s} 秒）",
    prepay: "（未選時長，按 {s} 秒預扣）",
    token: "按 token 計費，跑完顯示實扣",
    unavailable: "目前 API Key 沒有可用渠道",
    noKey: "未設定 API Key（見節點包 README）",
    failed: "估價失敗：{msg}",
    done: "✓ 任務 {id} · 實扣 {cost} 算力",
  },
  en: {
    est: "Est. ≈ {range} credits{suffix}",
    perCall: " / run",
    secs: " ({s}s)",
    prepay: " (no duration set, {s}s prepaid)",
    token: "Billed by tokens; actual cost shown after run",
    unavailable: "No channel available for this API key",
    noKey: "API key not configured (see README)",
    failed: "Estimate failed: {msg}",
    done: "✓ Task {id} · charged {cost} credits",
  },
};

const GENERIC = new Set(["LingKeImageGen", "LingKeVideoGen", "LingKeAudioGen"]);
const SKIP = new Set([
  "prompt", "seed", "control_after_generate", "params_json", "model",
  "images_param", "image_param", "end_image_param", "audio_param",
]);
const COLORS = { info: "#8b95a5", ok: "#4caf7d", warn: "#d89b3c" };

function lang() {
  let l = "en";
  try {
    l = app.ui?.settings?.getSettingValue?.("Comfy.Locale") || navigator.language || "en";
  } catch {}
  if (!l.startsWith("zh")) return "en";
  return /TW|HK|Hant/i.test(l) ? "zh-TW" : "zh";
}

function t(key, vars = {}) {
  let s = (I18N[lang()] || I18N.en)[key] ?? I18N.en[key];
  for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v);
  return s;
}

function fmt(n) {
  return Number(n).toFixed(n < 1 ? 3 : 2).replace(/\.?0+$/, "");
}

let nodeMapPromise = null;
function nodeMap() {
  nodeMapPromise ??= api.fetchApi("/lingke/nodes").then((r) => r.json()).catch(() => ({ featured: {} }));
  return nodeMapPromise;
}

function collectParams(node) {
  const params = {};
  for (const w of node.widgets || []) {
    if (SKIP.has(w.name)) continue;
    const v = w.value;
    if (v === undefined || v === null || v === "" || v === "default") continue;
    if (["string", "number", "boolean"].includes(typeof v)) params[w.name] = String(v);
  }
  const pj = node.widgets?.find((w) => w.name === "params_json");
  if (pj?.value) {
    try {
      const o = JSON.parse(pj.value);
      if (o && typeof o === "object" && !Array.isArray(o)) Object.assign(params, o);
    } catch {}
  }
  return params;
}

function setInfo(node, text, color = COLORS.info) {
  node.__lingkeText = text;
  node.__lingkeColor = color;
  node.setDirtyCanvas?.(true, true);
}

async function estimate(node) {
  const model = GENERIC.has(node.type)
    ? node.widgets?.find((w) => w.name === "model")?.value
    : (await nodeMap()).featured?.[node.type];
  if (!model) return;
  const seq = (node.__lingkeSeq = (node.__lingkeSeq || 0) + 1);
  let data;
  try {
    const q = new URLSearchParams({ model, params: JSON.stringify(collectParams(node)) });
    data = await (await api.fetchApi(`/lingke/estimate?${q}`)).json();
  } catch (e) {
    data = { error: String(e) };
  }
  if (seq !== node.__lingkeSeq) return; // 只认最后一次请求
  if (data.error) {
    const noKey = /API Key|LINGKE_API_KEY/i.test(data.error);
    setInfo(node, noKey ? t("noKey") : t("failed", { msg: data.error.slice(0, 60) }), COLORS.warn);
  } else if (!data.available) {
    setInfo(node, t("unavailable"), COLORS.warn);
  } else if (data.billing === "token" || data.low === undefined) {
    setInfo(node, t("token"));
  } else {
    const range = data.low === data.high ? fmt(data.low) : `${fmt(data.low)}~${fmt(data.high)}`;
    let suffix = t("perCall");
    if (data.billing === "second") suffix = data.prepay_default ? t("prepay", { s: data.seconds }) : t("secs", { s: data.seconds });
    setInfo(node, t("est", { range, suffix }));
  }
}

function scheduleEstimate(node) {
  clearTimeout(node.__lingkeTimer);
  node.__lingkeTimer = setTimeout(() => estimate(node), 400);
}

app.registerExtension({
  name: "LingKe.AI.Nodes",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!GENERIC.has(nodeData.name) && !nodeData.name.startsWith("LingKe_")) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      for (const w of this.widgets || []) {
        const cb = w.callback;
        w.callback = (...args) => {
          const out = cb?.apply(w, args);
          if (w.name !== "seed" && w.name !== "control_after_generate") scheduleEstimate(this);
          return out;
        };
      }
      scheduleEstimate(this);
      return r;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      scheduleEstimate(this);
      return r;
    };

    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (output) {
      const r = onExecuted?.apply(this, arguments);
      const info = output?.lingke?.[0];
      if (info) setInfo(this, t("done", { id: info.task_id, cost: info.cost ?? "?" }), COLORS.ok);
      return r;
    };

    const onDrawForeground = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function (ctx) {
      const r = onDrawForeground?.apply(this, arguments);
      if (this.__lingkeText && !this.flags?.collapsed) {
        ctx.save();
        ctx.font = "12px sans-serif";
        ctx.fillStyle = this.__lingkeColor || COLORS.info;
        ctx.textAlign = "left";
        ctx.fillText(this.__lingkeText, 4, this.size[1] + 18);
        ctx.restore();
      }
      return r;
    };
  },
});
