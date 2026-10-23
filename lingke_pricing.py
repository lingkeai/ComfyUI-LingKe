import time
import urllib.parse

from .lingke_client import LingKeClient

PRICING_TTL = 300
PREPAY_SECONDS = 10  # 开放 API：按秒计费且没传 duration 时按 10 秒预扣

_cache = {}


def _pricing(model):
    hit = _cache.get(model)
    if hit and time.time() - hit[0] < PRICING_TTL:
        return hit[1]
    data = LingKeClient()._request("GET", f"/v1/skills/models/{urllib.parse.quote(model, safe='')}/pricing?status=active", timeout=20)
    _cache[model] = (time.time(), data)
    return data


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def estimate(model, params):
    """按所选参数估算单次花费区间（各可用分组中最低~最高）。

    实际命中哪个分组由 API Key 的渠道策略决定，所以只给区间；
    没选的参数按基础价算，因此是"约"值。
    """
    data = _pricing(model)
    groups = [g for g in data.get("channel_groups") or []
              if g.get("is_active") and not g.get("excluded_for_this_key") and g.get("in_key_whitelist", True)]
    if not groups:
        return {"model": model, "display_name": data.get("display_name"), "available": False}

    chosen = {k: str(v) for k, v in (params or {}).items() if not isinstance(v, (list, dict))}
    totals, methods = [], set()
    seconds = None
    for g in groups:
        method = g.get("billing_method") or ""
        methods.add(method)
        if method == "按token":
            continue
        mult, add = 1.0, 0.0
        for op in g.get("option_prices") or []:
            if chosen.get(op.get("param_name")) == str(op.get("option_value")):
                mult *= _num(op.get("price_multiplier")) or 1.0
                add += _num(op.get("price_addition")) or 0.0
        unit = (_num(g.get("base_price")) or 0.0) * mult + add
        if method == "按秒":
            seconds = _num(chosen.get("duration")) or PREPAY_SECONDS
            unit *= seconds
        totals.append(unit)

    out = {
        "model": model,
        "display_name": data.get("display_name"),
        "available": True,
        "billing": "token" if methods == {"按token"} else ("second" if "按秒" in methods else "call"),
        "groups": len(groups),
    }
    if totals:
        out["low"] = round(min(totals), 4)
        out["high"] = round(max(totals), 4)
    if seconds is not None:
        out["seconds"] = seconds
        out["prepay_default"] = _num(chosen.get("duration")) is None
    return out
