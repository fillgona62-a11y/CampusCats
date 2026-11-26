"""Cat breed, coat pattern, species gate, and distinctive feature recognition (v0.6.0).

Supports three progressive tiers:
1. OpenAI-compatible Vision LLM API (GPT-4o-mini / GLM-4V-Flash / Qwen2.5-VL / Qwen-VL-Plus)
   — includes `is_cat` anti-human/anti-dog verification, breed, coat, ear-tip & fine markings.
2. Local zero-cost ONNX CLIP-ViT-B/32 INT8 classifier (`clip_classifier.py`)
   — recognizes 16 cat breeds/types and 11 coat patterns completely offline.
3. Foreground-weighted HSV heuristic fallback so bare unit-test / zero-model environments still work.
"""

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request

from PIL import Image
import clip_classifier
import providers

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_VISION_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 30


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


def has_cloud_vlm():
    cfg = llm_config()
    return bool(cfg.get("enabled") and cfg.get("vision_model"))


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
    """Lightweight offline coat estimate from elliptical foreground HSV distribution."""
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
        dx = (x - 23.5) / 21.0
        dy = (y - 23.5) / 21.0
        r2 = dx * dx + dy * dy
        if r2 > 1.05:
            continue
        w = 3.0 if r2 <= 0.45 else 1.0
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

    total = max(total, 1.0)
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
        "is_cat": True,
        "source": "local_heuristic",
        "breed": "未知",
        "breed_confidence": "low",
        "coat": coat,
        "features": features,
        "neutered_hint": "unknown",
        "summary": f"本地颜色纹理初判为「{coat}」花色；安装本地 CLIP 品种模型或配置多模态 API 后可识别具体品种与剪耳特征。",
    }


def _call_vlm(crop, cfg):
    b64 = _encode_jpeg_b64(crop)
    prompt = (
        "你是一位校园流浪猫图鉴识别专家。请先判断画面主体是否为猫（若为人像、自拍、狗、其他动物或无猫景物，必须设 is_cat 为 false），"
        "再输出严格 JSON，不要包含任何额外文字：\n"
        '{\n'
        '  "is_cat": true 或 false,\n'
        '  "non_cat_type": "person | dog | other | null",\n'
        '  "breed": "最可能的猫品种中文名，如 中华田园猫 / 英国短毛猫 / 美国短毛猫 / 布偶猫 / 暹罗猫 / 波斯猫 / 缅因猫 / 未知",\n'
        '  "breed_confidence": "high | medium | low",\n'
        '  "coat": "简洁花色与毛长描述，如 橘白短毛 / 狸花短毛 / 奶牛猫 / 三花 / 玳瑁 / 蓝白 / 纯白 / 纯黑",\n'
        '  "features": ["最多4条肉眼可见的显著辨识特征，如 左耳剪耳 / 白手套 / 粉色鼻头 / 佩戴项圈"],\n'
        '  "neutered_hint": "yes | no | unknown（根据是否可见绝育剪耳标记判断）",\n'
        '  "summary": "一句25字以内的中文总结"\n'
        '}'
    )
    payload = {
        "model": cfg["vision_model"],
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
            "User-Agent": "CampusCats-Server/2.1",
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
    if parsed.get("is_cat") is False:
        non_cat = str(parsed.get("non_cat_type") or "other").lower()
        label = "人像" if non_cat == "person" else "犬类" if non_cat == "dog" else "非猫咪目标"
        return {
            "is_cat": False,
            "non_cat_type": non_cat,
            "source": "vlm",
            "model": model,
            "breed": "非猫咪",
            "breed_confidence": "high",
            "coat": "非猫咪",
            "features": [],
            "neutered_hint": "unknown",
            "summary": str(parsed.get("summary") or f"视觉模型识别该画面为{label}，未发现猫咪。").strip()[:120],
        }
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
        "is_cat": True,
        "source": "vlm",
        "model": model,
        "breed": breed,
        "breed_confidence": confidence,
        "coat": coat,
        "features": features,
        "neutered_hint": neutered,
        "summary": summary,
    }


def classify_cat_crop(crop, *, allow_remote=False, timeout=None, precomputed_clip=None):
    """Return structured breed/coat/feature analysis, giving Cloud VLM decisive priority."""
    cfg = llm_config()
    if allow_remote and cfg["enabled"] and cfg["vision_model"]:
        try:
            result = _call_vlm(crop, dict(cfg, timeout=min(cfg["timeout"], timeout)) if timeout is not None else cfg)
            if result is not None:
                return result
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
            pass

    if isinstance(precomputed_clip, dict) and precomputed_clip.get("coat"):
        return precomputed_clip["coat"]

    if clip_classifier.is_enabled():
        clip_profile = clip_classifier.classify_coat_only(crop)
        if clip_profile is not None:
            clip_profile["is_cat"] = True
            return clip_profile

    return _heuristic_profile(crop)


def review_scene(image, timeout):
    """Only used when the photographer explicitly requests a second look."""
    cfg = llm_config()
    if not cfg["enabled"] or not cfg["vision_model"]:
        return None
    prompt = ("请找出照片中真实的家猫，区分狗、人、玩具和背景。"
              "用 JSON 返回 boxes，每只可辨认的猫一个框，最多八只。"
              "每个框是归一化的 [左边,上边,宽,高]，尽量包含整只猫。"
              "确定没有猫时返回空数组。看不清时返回 uncertain 为 true。")
    payload = {"model": cfg["vision_model"], "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + _encode_jpeg_b64(image, 1024)}},
    ]}]}
    cfg = dict(cfg, timeout=min(cfg["timeout"], timeout))
    try:
        raw = providers.completion(cfg, payload) if cfg.get("scope") else _environment_completion(cfg, payload)
        text = raw["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(x.get("text", "") for x in text if isinstance(x, dict))
        return _extract_json(text)
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None


def _make_comparison_sheet(query_crop, candidate_items):
    """Keep the complete crop and label multiple views with the same identity."""
    from PIL import ImageDraw, ImageOps

    panels = [("NEW", query_crop)]
    for idx, item in enumerate(candidate_items, 1):
        if item.get("crop") is not None:
            panels.append((f"#{idx}", item["crop"]))
        if item.get("alternate") is not None:
            panels.append((f"#{idx} B", item["alternate"]))
    if len(panels) < 2:
        return None

    tile = 256
    header = 26
    gap = 6
    columns = min(3, len(panels))
    rows = (len(panels) + columns - 1) // columns
    width = columns * (tile + gap) + gap
    height = rows * (tile + header + gap) + gap
    sheet = Image.new("RGB", (width, height), (245, 245, 240))
    draw = ImageDraw.Draw(sheet)
    for i, (label, im) in enumerate(panels):
        x = gap + (i % columns) * (tile + gap)
        top = gap + (i // columns) * (tile + header + gap)
        y = top + header
        fitted = ImageOps.contain(im.convert("RGB"), (tile, tile), method=Image.Resampling.LANCZOS)
        sheet.paste(fitted, (x + (tile - fitted.width) // 2, y + (tile - fitted.height) // 2))
        bg = (217, 130, 43) if i == 0 else (45, 68, 56)
        draw.rectangle([x, top, x + tile, top + header - 2], fill=bg)
        draw.text((x + 8, top + 6), label, fill=(255, 255, 255))
    return sheet


def compare_candidates_vlm(query_crop, candidate_items, *, allow_remote=False, timeout=None):
    """Compare the query against all pictured identities in one provider request."""
    if not allow_remote or not candidate_items:
        return None
    cfg = llm_config()
    if not (cfg["enabled"] and cfg["vision_model"]):
        return None
    sheet = _make_comparison_sheet(query_crop, candidate_items)
    if sheet is None:
        return None
    b64 = _encode_jpeg_b64(sheet, max_side=1024)
    prompt = (
        f"NEW 是待辨认照片，其余编号 1 到 {len(candidate_items)} 为不同猫的已审核目击。"
        "相同编号的 B 图是同一候选的另一次目击。只比较可见外观。证据不足选 uncertain；"
        "候选都不符可选 different_cat。品种无法判断时填写未知。"
        "\n1）身份拍板：逐项对比额头纹/M纹走向、鼻梁与嘴周白斑边界、耳朵是否剪耳/缺口、胸腹四肢花纹；校园里同花色异猫很常见，局部斑纹不一致请果断判为 different_cat（若 NEW 根本不是猫则设 is_cat 为 false）。"
        "\n2）NEW 自身特征描述：权威判断 NEW 的最可能品种、毛色毛长、是否可见绝育剪耳标记及显著外观特征。"
        "\n严格输出 JSON，不要包含任何额外解释：\n"
        '{\n'
        '  "is_cat": true 或 false,\n'
        '  "non_cat_type": "person | dog | other | null",\n'
        '  "verdict": "same_cat | different_cat | uncertain",\n'
        '  "best_candidate_index": 图中候选编号或 null,\n'
        '  "confidence": 0.0 到 1.0 之间的小数,\n'
        '  "matching_features": ["最多3条一致的局部花纹特征"],\n'
        '  "differences": ["最多3条观察到的差异或不确定点"],\n'
        '  "reason": "一句50字以内的中文比对拍板结论",\n'
        '  "breed": "NEW 最可能的猫品种中文名，如 中华田园猫 / 英国短毛猫 / 布偶猫 / 未知",\n'
        '  "breed_confidence": "high | medium | low",\n'
        '  "coat": "NEW 的简洁毛色与毛长描述，如 橘白短毛 / 狸花短毛 / 奶牛猫 / 三花",\n'
        '  "features": ["NEW 最多4条显著外观特征，如 左耳平剪耳 / 鼻梁白通天 / 白手套"],\n'
        '  "neutered_hint": "yes | no | unknown（NEW 是否可见绝育剪耳标记）",\n'
        '  "summary": "一句25字以内的 NEW 外观特征总结"\n'
        '}'
    )
    eff_cfg = dict(cfg, timeout=min(cfg["timeout"], timeout)) if timeout is not None else cfg
    payload = {
        "model": eff_cfg["vision_model"],
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
    try:
        if eff_cfg.get("scope"):
            raw = providers.completion(eff_cfg, payload)
        else:
            raw = _environment_completion(eff_cfg, payload)
        content = raw["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        parsed = _extract_json(content)
        if not parsed:
            return None
        if parsed.get("is_cat") is False:
            return {
                "source": "vlm",
                "is_cat": False,
                "non_cat_type": str(parsed.get("non_cat_type") or "other").lower(),
                "verdict": "different_cat",
                "best_candidate_index": None,
                "confidence": 1.0,
                "matching_features": [],
                "differences": [],
                "reason": str(parsed.get("reason") or parsed.get("summary") or "云端复核判定该画面并非猫咪。").strip()[:120],
                "ai_profile": None,
            }
        verdict = str(parsed.get("verdict", "uncertain")).lower()
        if verdict not in ("same_cat", "different_cat", "uncertain"):
            verdict = "uncertain"
        idx = parsed.get("best_candidate_index")
        try:
            idx = int(idx) if idx is not None else None
        except (TypeError, ValueError):
            idx = None
        if idx is not None and not (1 <= idx <= len(candidate_items)):
            idx = None
        if verdict == "same_cat" and idx is None:
            verdict = "uncertain"
        try:
            conf = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5

        embedded_profile = None
        if parsed.get("coat") or parsed.get("breed"):
            b_conf = str(parsed.get("breed_confidence", "medium")).lower()
            if b_conf not in ("high", "medium", "low"):
                b_conf = "medium"
            neuter = str(parsed.get("neutered_hint", "unknown")).lower()
            if neuter not in ("yes", "no", "unknown"):
                neuter = "unknown"
            breed = str(parsed.get("breed", "")).strip()[:60] or "未知"
            coat = str(parsed.get("coat", "")).strip()[:60] or "花色待补充"
            feats = [str(x).strip()[:40] for x in (parsed.get("features") or []) if str(x).strip()][:4]
            embedded_profile = {
                "is_cat": True,
                "source": "vlm",
                "model": eff_cfg["vision_model"],
                "breed": breed,
                "breed_confidence": b_conf,
                "coat": coat,
                "features": feats,
                "neutered_hint": neuter,
                "summary": str(parsed.get("summary", "")).strip()[:120] or f"云端识别为{breed}（{coat}）",
            }

        return {
            "source": "vlm",
            "is_cat": True,
            "verdict": verdict,
            "best_candidate_index": idx,
            "confidence": round(conf, 3),
            "matching_features": [str(x).strip()[:40] for x in (parsed.get("matching_features") or []) if str(x).strip()][:3],
            "differences": [str(x).strip()[:40] for x in (parsed.get("differences") or []) if str(x).strip()][:3],
            "reason": str(parsed.get("reason", "")).strip()[:120],
            "ai_profile": embedded_profile,
        }
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None
