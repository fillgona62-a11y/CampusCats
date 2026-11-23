"""Cat breed, coat pattern, and distinctive feature recognition.

Supports two modes:
1. OpenAI-compatible Vision LLM API (configured via CAMPUSCATS_LLM_API_KEY /
   CAMPUSCATS_LLM_BASE_URL / CAMPUSCATS_VISION_MODEL).
2. Zero-dependency offline HSV heuristic fallback so the app always returns
   structured coat & breed hints even without external API keys.
"""

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request

from PIL import Image
import providers

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_VISION_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 25


def llm_config():
    configured = providers.active.get()
    if configured:
        return configured
    api_key = os.getenv("CAMPUSCATS_LLM_API_KEY", "").strip()
    base_url = os.getenv("CAMPUSCATS_LLM_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    vision_model = (
        os.getenv("CAMPUSCATS_VISION_MODEL", "").strip()
        or os.getenv("CAMPUSCATS_LLM_MODEL", "").strip()
        or DEFAULT_VISION_MODEL
    )
    timeout = float(os.getenv("CAMPUSCATS_LLM_TIMEOUT", str(DEFAULT_TIMEOUT)))
    return {
        "enabled": bool(api_key),
        "api_key": api_key,
        "base_url": base_url,
        "vision_model": vision_model,
        "timeout": max(5.0, min(timeout, 90.0)),
    }


def _encode_jpeg_b64(crop, max_side=512):
    image = crop.convert("RGB").copy()
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=82, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _extract_json(text):
    text = (text or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _heuristic_profile(crop):
    """Lightweight offline coat & breed estimate from central HSV distribution."""
    rgb = crop.convert("RGB")
    hsv = rgb.resize((48, 48), Image.Resampling.LANCZOS).convert("HSV")
    raw = hsv.tobytes()

    total = 0.0
    orange = 0.0
    white = 0.0
    black = 0.0
    gray = 0.0
    brown = 0.0

    for i in range(48 * 48):
        h, s, v = raw[3 * i : 3 * i + 3]
        x, y = i % 48, i // 48
        w = 2.0 if 8 <= x < 40 and 8 <= y < 40 else 1.0
        total += w
        if v < 52:
            black += w
        elif s < 42 and v > 185:
            white += w
        elif s < 48:
            gray += w
        elif 8 <= h <= 34 and s >= 65 and v >= 90:
            orange += w
        elif (h < 12 or h > 235 or 12 <= h <= 38) and v < 155:
            brown += w
        else:
            gray += w

    ratios = {
        "orange": orange / total,
        "white": white / total,
        "black": black / total,
        "gray": gray / total,
        "brown": brown / total,
    }

    features = []
    if ratios["orange"] >= 0.22 and ratios["white"] >= 0.20 and (ratios["black"] + ratios["brown"]) >= 0.16:
        coat = "三花"
        features.append("橘白黑三色分布")
    elif ratios["orange"] >= 0.18 and (ratios["black"] + ratios["brown"]) >= 0.30 and ratios["white"] < 0.15:
        coat = "玳瑁"
        features.append("黑橘交错花纹")
    elif ratios["orange"] >= 0.28 and ratios["white"] >= 0.18:
        coat = "橘白"
        features.append("橘色与白色相间")
    elif ratios["orange"] >= 0.32:
        coat = "橘猫"
        features.append("主体呈暖橘色")
    elif ratios["black"] >= 0.22 and ratios["white"] >= 0.22:
        coat = "奶牛（黑白）"
        features.append("黑白撞色花纹")
    elif ratios["white"] >= 0.58:
        coat = "纯白"
        features.append("通体偏白")
    elif ratios["black"] >= 0.55:
        coat = "纯黑"
        features.append("深黑毛色")
    elif ratios["gray"] >= 0.45 and ratios["white"] >= 0.18:
        coat = "灰白 / 蓝白"
        features.append("灰白毛色分布")
    elif ratios["brown"] >= 0.22 or (ratios["gray"] >= 0.30 and ratios["black"] >= 0.12):
        coat = "狸花 / 虎斑"
        features.append("棕灰深浅条纹特征")
    else:
        coat = "混合花色"

    return {
        "source": "local_heuristic",
        "breed": "未知",
        "breed_confidence": "low",
        "coat": coat,
        "features": features,
        "neutered_hint": "unknown",
        "summary": f"本地颜色纹理初判为「{coat}」花色；配置多模态 API 后可进一步识别具体品种、剪耳及细部特征。",
    }


def _call_vlm(crop, cfg):
    b64 = _encode_jpeg_b64(crop)
    prompt = (
        "你是一位校园流浪猫图鉴识别专家。请观察这张猫的照片，仅输出严格 JSON，不要包含额外解释。"
        "字段要求：\n"
        '{\n'
        '  "breed": "最可能的猫品种中文名，如 中华田园猫 / 英国短毛猫 / 美国短毛猫 / 布偶猫 / 暹罗猫 / 折耳猫 / 未知",\n'
        '  "breed_confidence": "high | medium | low",\n'
        '  "coat": "简洁花色与毛长描述，如 橘白短毛 / 狸花短毛 / 奶牛猫 / 三花 / 玳瑁 / 蓝白",\n'
        '  "features": ["最多4条肉眼可见的显著辨识特征，如 左耳剪耳 / 白手套 / 粉色鼻头 / 佩戴项圈"],\n'
        '  "neutered_hint": "yes | no | unknown（根据是否可见绝育剪耳标记判断）",\n'
        '  "summary": "一句25字以内的中文总结"\n'
        '}'
    )
    payload = {
        "model": cfg["vision_model"],
        "temperature": 0.1,
        "max_tokens": 300,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
    }
    if cfg.get("scope"):
        payload.pop("temperature", None)
        raw = providers.completion(cfg, payload)
    else:
        raw = _environment_completion(cfg, payload)
    return _vision_result(raw, cfg["vision_model"])


def _environment_completion(cfg, payload):
    url = f"{cfg['base_url']}/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
            "User-Agent": "CampusCats-Server/2.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _vision_result(raw, model):
    content = raw["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    parsed = _extract_json(content)
    if not parsed:
        return None
    confidence = str(parsed.get("breed_confidence", "medium")).lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"
    neutered = str(parsed.get("neutered_hint", "unknown")).lower()
    if neutered not in ("yes", "no", "unknown"):
        neutered = "unknown"
    raw_features = parsed.get("features") or []
    features = [str(item).strip()[:40] for item in raw_features if str(item).strip()][:4]
    breed = str(parsed.get("breed", "")).strip()[:60] or "未知"
    coat = str(parsed.get("coat", "")).strip()[:60] or "花色待补充"
    summary = str(parsed.get("summary", "")).strip()[:120] or f"AI 识别为{breed}（{coat}）"
    return {
        "source": "vlm",
        "model": model,
        "breed": breed,
        "breed_confidence": confidence,
        "coat": coat,
        "features": features,
        "neutered_hint": neutered,
        "summary": summary,
    }


def classify_cat_crop(crop, *, allow_remote=False, timeout=None):
    """Return structured breed/coat/feature analysis for a cropped cat image."""
    cfg = llm_config()
    if allow_remote and cfg["enabled"] and cfg["vision_model"]:
        try:
            result = _call_vlm(crop, dict(cfg, timeout=min(cfg["timeout"], timeout)) if timeout is not None else cfg)
            if result is not None:
                return result
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
            pass
    return _heuristic_profile(crop)
