"""CampusCats conversational Agent with OpenAI-compatible Tool Calling & Multi-Cat Vision (v0.6.0).

Upgrades:
- Automatic multi-cat bounding box detection & anti-human/anti-dog filtering on uploaded chat photos.
- Passes `media_dir` so SIFT local landmark reranking and side-by-side VLM verification work inside chat.
- Smart Chinese entity & attribute extraction in `_local_fallback` (matches cat names, aliases, SYLU landmarks,
  coats, breeds, sex, and neutered status without requiring spaces).
- Automatic graceful retry when a configured provider rejects `tools` schema, plus clean fallback handling.
"""

import json
import os
import threading
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

import ai_vision
import clip_classifier
import detector
import encoder
import surveys
from catalog import SYLU_PRESET_AREAS, SIGHTING_QUERY, catalog, identify, iso, serialize, stats
from media import Problem, canonical_photo

DEFAULT_CHAT_MODEL = "gpt-4o-mini"
_BEIJING_TZ = timezone(timedelta(hours=8))
_MAX_LLM_CONCURRENCY = max(1, min(int(os.getenv("CAMPUSCATS_LLM_CONCURRENCY", "3")), 32))
_LLM_SLOTS = threading.BoundedSemaphore(_MAX_LLM_CONCURRENCY)

SYSTEM_PROMPT = (
    "你是「琴园有猫 · 沈阳理工大学校园猫图鉴」的智能校园猫管家。你可以调用工具查询数据库中的校园猫档案、"
    "统计校园猫分布、查看最近目击记录，并对用户上传的照片执行自动多猫检测、人像/非猫过滤、在库查重与品种/花色识别。\n"
    "回答原则：\n"
    "1. 严格基于工具返回的真实数据库与识别结果回答，绝不编造不存在的猫档案或目击记录。\n"
    "2. 若工具返回 status 为 not_a_cat（画面为人像、犬类或无猫景物），请温和明确告知未检测到猫咪，不要强行猜测猫品种或花色。\n"
    "3. 若一张图检测到多只猫，请按编号逐只说明查重结果与品种/花色初判；若为 weak_candidate，提醒同学同花色不同猫易相似，需核对耳尖与脸部花纹。\n"
    "4. 涉及品种识别时，清晰区分「AI / 云端模型初判」与「维护者已核验（verified）」；本地辅助仅作花色初筛，不要把本地辅助说成绝对品种结论。\n"
    "5. 所有时间均按北京时间（UTC+8）展示，不要输出 UTC 时间。\n"
    "6. 语气温暖、简洁、条理清晰，适合手机端阅读。"
)

TOOLS = [
    {"type": "function", "function": {"name": "weekly_surveys",
     "description": "查看本周已知校园区域的定点观察和零目击统计及尚待观察的区域。",
     "parameters": {"type": "object", "properties": {}}}},
    {
        "type": "function",
        "function": {
            "name": "search_cats",
            "description": "按名字、别名、花色、品种、性别、绝育状态或校园区域检索已建档的校园猫。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词（名字、别名、花色、品种或状态）"},
                    "area": {"type": "string", "description": "校园区域关键词，如 图书馆、食堂、兵器广场"},
                    "limit": {"type": "integer", "description": "返回数量上限，默认 6"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cat_detail",
            "description": "按档案 ID 获取某只校园猫的详细信息、别名与最近目击时间线。",
            "parameters": {
                "type": "object",
                "properties": {"cat_id": {"type": "integer", "description": "猫档案 ID"}},
                "required": ["cat_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_campus_overview",
            "description": "获取全校已建档猫总数、近30天活跃数、待审核数及各区域猫数量分布。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_recent_sightings",
            "description": "查看全校或指定校园区域最近几天的已确认目击记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {"type": "string", "description": "可选校园区域过滤"},
                    "days": {"type": "integer", "description": "最近天数，默认 7"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "identify_uploaded_photo",
            "description": "对用户本轮随消息上传的照片执行自动多猫框选、非猫拦截、数据库查重及品种/花色/特征识别。",
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {"type": "string", "description": "用户提到的目击校园区域（可选）"}
                },
            },
        },
    },
]


def status_info():
    cfg = ai_vision.llm_config()
    chat_model = cfg.get("chat_model") or os.getenv("CAMPUSCATS_LLM_MODEL", "").strip() or DEFAULT_CHAT_MODEL
    if cfg["enabled"] and cfg["vision_model"]:
        vision_mode = "vlm"
    elif clip_classifier.is_enabled():
        vision_mode = "local_clip"
    else:
        vision_mode = "local_heuristic"
    return {
        "mode": "llm" if cfg["enabled"] else "local_fallback",
        "chat_model": chat_model if cfg["enabled"] else None,
        "scope": cfg.get("scope", "shared"),
        "photo_box_modes": True,
        "vision_mode": vision_mode,
        "vision_model": cfg["vision_model"] if cfg["enabled"] and cfg["vision_model"] else None,
        "onnx_encoder": bool(encoder.VERSION),
        "detector_enabled": detector.is_enabled(),
        "clip_enabled": clip_classifier.is_enabled(),
    }


def _fmt_bj_time(iso_str):
    raw = str(iso_str or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M（北京时间）")
    except ValueError:
        return raw


def _compact_card(cat):
    return {
        "id": cat["id"],
        "name": cat["name"],
        "coat": cat.get("coat", ""),
        "breed": cat.get("breed", ""),
        "breed_status": cat.get("breed_status", "unknown"),
        "sex": cat.get("sex", "unknown"),
        "neutered": cat.get("neutered", "unknown"),
        "care_status": cat.get("care_status", "school"),
        "temperament": cat.get("temperament", ""),
        "area": cat.get("area", ""),
        "last_seen": _fmt_bj_time(cat.get("last_seen", "")),
        "sightings": cat.get("sightings", 0),
        "aliases": cat.get("aliases", []),
        "photo_url": cat.get("photo_url", ""),
        "thumbnail_url": cat.get("thumbnail_url", ""),
    }


_META_KEYWORDS = {
    "female": "母 母猫 妹妹 小母猫",
    "male": "公 公猫 弟弟 小公猫",
    "neutered": "已绝育 绝育 剪耳",
    "intact": "未绝育 没绝育",
    "attention": "需关注 生病 住院 受伤",
    "adopted": "已领养 领养 毕业",
    "memorial": "喵星 纪念 去世",
}

_SEARCH_TERMS = (
    "图书馆", "琴园", "兵器博物馆", "兵器广场", "兵器", "博物馆", "志学堂", "教学楼",
    "食堂", "餐饮", "一食堂", "二食堂", "三食堂", "宿舍", "生活区", "体育场", "操场", "绿地", "北门", "南门",
    "东区", "西区", "南区", "北区", "东门", "西门",
    "橘白", "橘猫", "大橘", "小橘", "三花", "玳瑁", "奶牛", "黑白", "狸花", "虎斑",
    "蓝白", "灰白", "蓝猫", "灰猫", "纯白", "白猫", "纯黑", "黑猫", "重点色", "挖煤",
    "英短", "英国短毛猫", "美短", "美国短毛猫", "布偶", "暹罗", "波斯", "加菲", "缅因", "田园猫",
    "已绝育", "未绝育", "绝育", "剪耳", "母猫", "公猫", "亲人", "领养", "需关注",
)


def _resolve_photo_boxes(photo, explicit_boxes):
    """Auto-detect multiple cats when caller didn't supply explicit boxes."""
    if explicit_boxes:
        return explicit_boxes, None
    _, image = canonical_photo(photo)
    if detector.is_enabled():
        dets = detector.detect_cats(image)
        if dets:
            return [d["box"] for d in dets[:8]], len(dets)
    return [[0, 0, 1, 1]], 0


def _execute_tool(db, name, args, context):
    if name == "weekly_surveys":
        report = surveys.board(db, None)
        return {"week_start": report["week_start"], "areas": report["areas"]}
    cats_map = catalog(db)
    cats = list(cats_map.values())

    if name == "search_cats":
        q = str(args.get("query") or "").strip().lower()
        area = str(args.get("area") or "").strip().lower()
        limit = max(1, min(int(args.get("limit") or 6), 12))
        matched = []
        for cat in cats:
            if area and area not in str(cat.get("area", "")).lower():
                continue
            haystack = " ".join(
                [
                    cat.get("name", ""),
                    cat.get("coat", ""),
                    cat.get("breed", ""),
                    cat.get("area", ""),
                    cat.get("temperament", ""),
                    _META_KEYWORDS.get(cat.get("sex", ""), ""),
                    _META_KEYWORDS.get(cat.get("neutered", ""), ""),
                    _META_KEYWORDS.get(cat.get("care_status", ""), ""),
                    *cat.get("aliases", []),
                ]
            ).lower()
            if q and q not in haystack:
                continue
            matched.append(cat)
        cards = [_compact_card(c) for c in matched[:limit]]
        for card in cards:
            context["cards"][card["id"]] = card
        return {"total_matched": len(matched), "cats": cards}

    if name == "get_cat_detail":
        cid = int(args["cat_id"])
        cat = cats_map.get(cid)
        if not cat:
            return {"error": f"未找到编号为 #{cid} 的校园猫档案。"}
        card = _compact_card(cat)
        context["cards"][card["id"]] = card
        rows = db.execute(
            SIGHTING_QUERY + " WHERE s.cat_id=? ORDER BY f.observed_at DESC, s.id DESC LIMIT 5",
            (cid,),
        )
        recent = [dict(item, observed_at=_fmt_bj_time(item.get("observed_at", ""))) for item in serialize(db, rows)]
        return {"cat": card, "recent_sightings": recent}

    if name == "get_campus_overview":
        overview = stats(db, cats_map)
        areas = Counter(c["area"] for c in cats if c.get("area"))
        return {
            "stats": overview,
            "top_areas": [{"area": a, "count": n} for a, n in areas.most_common(8)],
        }

    if name == "check_recent_sightings":
        area = str(args.get("area") or "").strip()
        days = max(1, min(int(args.get("days") or 7), 90))
        cutoff = iso(datetime.now(timezone.utc) - timedelta(days=days))
        where = " WHERE s.status='confirmed' AND f.observed_at>=?"
        params = [cutoff]
        if area:
            where += " AND instr(f.area,?)>0"
            params.append(area)
        count = db.execute("SELECT COUNT(*) FROM sightings s JOIN frames f ON f.id=s.frame_id" + where, params).fetchone()[0]
        rows = db.execute(SIGHTING_QUERY + where + " ORDER BY f.observed_at DESC,s.id DESC LIMIT 10", params)
        items = [dict(item, observed_at=_fmt_bj_time(item.get("observed_at", ""))) for item in serialize(db, rows)]
        for item in items:
            cid = item.get("cat_id")
            if cid and cid in cats_map:
                context["cards"][cid] = _compact_card(cats_map[cid])
        return {"days": days, "area": area or "全校", "count": count, "sightings": items}

    if name == "identify_uploaded_photo":
        if context.get("identification") is not None:
            return context["identification"]
        photo = context.get("photo")
        if not photo:
            return {"error": "当前对话未附带照片，请先选一张照片。"}
        area = str(args.get("area") or context.get("area") or "").strip()
        boxes, auto_count = _resolve_photo_boxes(photo, context.get("boxes"))
        result = identify(
            db,
            {"photo": photo, "boxes": boxes, "area": area, "cloud_photo": context["cloud_photo"]},
            media_dir=context.get("media_dir"),
        )
        result["auto_detected_count"] = auto_count
        context["identification"] = result
        for entry in result["results"]:
            for cand in entry["candidates"]:
                context["cards"][cand["id"]] = _compact_card(cand)
        return result

    return {"error": f"未知工具：{name}"}


def _call_chat_llm(messages, cfg, *, require_photo=False, force_plain_chat=False):
    chat_model = cfg.get("chat_model") or os.getenv("CAMPUSCATS_LLM_MODEL", "").strip() or DEFAULT_CHAT_MODEL
    payload = {
        "model": chat_model,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": {"type": "function", "function": {"name": "identify_uploaded_photo"}}
        if require_photo
        else "auto",
    }
    if force_plain_chat:
        payload.pop("tools", None)
        payload.pop("tool_choice", None)
    if cfg.get("scope"):
        from providers import completion

        if cfg["protocol"] == "chat" or force_plain_chat:
            payload.pop("tools", None)
            payload.pop("tool_choice", None)
        return completion(cfg, payload)
    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
            "User-Agent": "CampusCats-Agent/2.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_chinese_tokens(db, text):
    """Extract cat names, aliases, landmarks, coats, breeds, and cleaned phrases from unspaced Chinese queries."""
    tokens = []
    seen = set()

    def add(tok):
        t = tok.strip()
        if t and t not in seen:
            seen.add(t)
            tokens.append(t)

    # 1. Exact cat names and aliases currently in catalog
    for cat in catalog(db).values():
        if cat["name"] and cat["name"].lower() in text.lower():
            add(cat["name"])
        for al in cat.get("aliases", []):
            if al and al.lower() in text.lower():
                add(al)

    # 2. Known campus landmarks, coats, breeds, and care/neuter keywords
    for kw in _SEARCH_TERMS:
        if kw in text:
            add(kw)
    for preset in SYLU_PRESET_AREAS:
        if preset in text:
            add(preset)

    # 3. Cleaned phrase fallback
    cleaned = text
    for stop in (
        "请问", "帮我", "找一下", "查一下", "搜一下", "看看", "有没有", "有哪些", "有什么",
        "附近", "周边", "那边", "一只", "这只猫", "叫什么", "在哪", "在哪里", "的猫", "校园猫", "小猫", "猫",
        "？", "?", "。", "！", "!", "，", ",",
    ):
        cleaned = cleaned.replace(stop, " ")
    for tok in cleaned.split():
        add(tok)
    return tokens


def _local_fallback(db, message, context):
    """Deterministic local assistant when no LLM API key is configured or when pre-grounding chat mode."""
    lines = []
    used_tools = []
    text = message.strip()

    if context.get("photo"):
        used_tools.append("identify_uploaded_photo")
        res = _execute_tool(db, "identify_uploaded_photo", {"area": context.get("area", "")}, context)
        items = res.get("results", [])
        if len(items) > 1:
            lines.append(f"已在照片中自动识别出 **{len(items)} 只猫咪**，逐只比对结果如下：")
        for idx, item in enumerate(items, start=1):
            rec = item.get("record_status") or {}
            if rec.get("status") == "not_a_cat" or item.get("not_cat"):
                lines.append("【非猫咪画面提示】")
                lines.append(f"• {rec.get('summary', '未在照片中检测到猫咪（可能是人像或非猫景物），已跳过品种与档案比对。')}")
                continue
            ai_p = item.get("ai_profile") or {}
            title = f"【照片识别 · 猫 {idx}】" if len(items) > 1 else "【照片识别结果】"
            lines.append(title)
            lines.append(f"• 在库查重：{rec.get('summary', '暂无法判断')}")
            if item.get("candidates"):
                top = item["candidates"][0]
                pct = round(float(top.get("similarity", 0.0)) * 100)
                lines.append(f"• 首选候选：**{top['name']}**（匹配度约 {pct}%，常出没：{top.get('area') or '待补充'}）")
            if ai_p:
                feat = "、".join(ai_p.get("features") or [])
                src = ai_p.get("source")
                if src == "vlm":
                    lines.append(
                        f"• 品种与花色（云端视觉）：**{ai_p.get('breed', '未知')}**｜花色：**{ai_p.get('coat', '待补')}**"
                        + (f"｜特征：{feat}" if feat else "")
                    )
                else:
                    lines.append(
                        f"• 本地花色辅助初筛：**{ai_p.get('coat', '待补')}**（品种需云端视觉模型拍板或维护者核验）"
                        + (f"｜{feat}" if feat else "")
                    )

    if any(k in text for k in ("定点", "观察", "周报", "零目击")):
        used_tools.append("weekly_surveys")
        report = _execute_tool(db, "weekly_surveys", {}, context)
        areas = report["areas"]
        lines.append("本周暂无区域观察资料。" if not areas else "本周区域周报（优先列出观察较少的区域）：")
        for row in areas[:8]:
            visits, seen = row["visits"], row["seen"]
            summary = f"{visits} 次观察，其中 {visits - seen} 次零目击" if visits else "本周待观察"
            lines.append(f"• {row['area']}：{summary}")
    elif any(k in text for k in ("多少", "统计", "总数", "几只", "分布", "活跃", "概览")):
        used_tools.append("get_campus_overview")
        ov = _execute_tool(db, "get_campus_overview", {}, context)
        st = ov["stats"]
        areas = "、".join(f"{a['area']}({a['count']}只)" for a in ov["top_areas"][:5])
        lines.append(
            f"全校目前已建档 **{st['cats']} 只猫**，近 30 天活跃 **{st['active']} 只**，待辨认记录 {st['pending']} 条。"
            + (f"常见区域：{areas}。" if areas else "")
        )
    elif any(k in text for k in ("最近", "今天", "昨天", "刚看到", "动态")):
        used_tools.append("check_recent_sightings")
        rec = _execute_tool(db, "check_recent_sightings", {"days": 7}, context)
        if rec["count"]:
            summary = "、".join(
                f"{s.get('cat_name') or '未命名'}（{s.get('area', '未知区域')}）" for s in rec["sightings"][:4]
            )
            lines.append(f"近 7 天共确认 {rec['count']} 条目击，最近出现：{summary}。")
        else:
            lines.append("近 7 天暂无已确认的目击记录。")
    elif text and not context.get("photo"):
        tokens = _extract_chinese_tokens(db, text)
        used_tools.append("search_cats")
        matched = None
        for tok in tokens:
            res = _execute_tool(db, "search_cats", {"query": tok, "limit": 6}, context)
            if res["total_matched"] > 0:
                matched = (tok, res)
                break
        if matched is None:
            res = _execute_tool(db, "search_cats", {"query": "", "limit": 5}, context)
            if res["total_matched"]:
                names = "、".join(f"{c['name']}（{c['area'] or '区域待补'}）" for c in res["cats"])
                lines.append(f"没有直接匹配到「{text}」，为你列出图鉴中最近活跃的猫：{names}。")
            else:
                lines.append("图鉴目前还没有已建档的校园猫，欢迎先拍照提交第一条目击。")
        else:
            tok, res = matched
            names = "、".join(f"**{c['name']}**（{c['coat'] or '花色待补'} · {c['area'] or '区域待补'}）" for c in res["cats"])
            lines.append(f"按「{tok}」为你找到 {res['total_matched']} 只校园猫：{names}。")

    if not lines:
        lines.append("你好！你可以发一张猫照片让我查查库里有没有记录过、是什么品种花色（支持一图多猫），或直接问我某区域有哪些校园猫。")

    return {
        "mode": "local_fallback",
        "reply": "\n".join(lines),
        "cards": list(context["cards"].values()),
        "identification": context.get("identification"),
        "tool_calls": used_tools,
    }


def chat(db, body, media_dir=None):
    message = str(body.get("message") or "").strip()
    photo = body.get("photo")
    area = str(body.get("area") or "").strip()[:80]
    boxes = body.get("boxes")
    if not message and not photo:
        raise Problem("请输入想咨询的内容，或附带一张猫的照片。")
    if len(message) > 1000:
        raise Problem("消息过长，请控制在 1000 字以内。")

    history = body.get("history") or []
    if not isinstance(history, list):
        raise Problem("对话历史格式无效。")

    context = {
        "cloud_photo": body.get("cloud_photo") is True,
        "photo": photo,
        "area": area,
        "boxes": boxes,
        "media_dir": media_dir,
        "cards": {},
        "identification": None,
    }
    cfg = ai_vision.llm_config()

    if not cfg["enabled"]:
        return _local_fallback(db, message, context)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-8:]:
        if isinstance(turn, dict) and turn.get("role") in ("user", "assistant"):
            content = str(turn.get("content") or "").strip()[:1000]
            if content:
                messages.append({"role": turn["role"], "content": content})

    user_text = message or "请帮我看看这张照片里的猫是否已在数据库中记录过，并判断它的品种和花色。"
    if photo:
        user_text += f"\n（系统提示：用户本轮附带了一张照片，区域提示：{area or '未填'}，请调用 identify_uploaded_photo 工具分析。）"
    messages.append({"role": "user", "content": user_text})

    if not _LLM_SLOTS.acquire(blocking=False):
        busy_fallback = _local_fallback(db, message, context)
        busy_fallback["reply"] += "\n（当前智能对话请求较多，已自动切换为快速本地查库模式。）"
        return busy_fallback

    used_tools = []
    try:
        if cfg.get("protocol") == "chat":
            local = _local_fallback(db, message, context)
            db.commit()
            messages.insert(1, {"role": "system", "content": "本轮校园图鉴的真实数据库与识图结果供参考：\n" + local["reply"]})
            response = _call_chat_llm(messages, cfg)
            reply = response["choices"][0]["message"]["content"]
            if not isinstance(reply, str) or not reply.strip():
                raise ValueError("Agent 未返回文本。")
            return dict(local, mode="llm", reply=reply)

        for step in range(4):
            db.commit()
            try:
                resp = _call_chat_llm(messages, cfg, require_photo=bool(photo and not context["identification"]))
            except ValueError as err:
                # If a provider endpoint does not support function calling (`tools`), retry once grounded with local results
                if step == 0 and "HTTP 400" in str(err):
                    local = _local_fallback(db, message, context)
                    db.commit()
                    grounded = list(messages)
                    grounded.insert(1, {"role": "system", "content": "本轮校园图鉴的真实数据库与识图结果供参考：\n" + local["reply"]})
                    resp2 = _call_chat_llm(grounded, cfg, force_plain_chat=True)
                    reply2 = (resp2["choices"][0]["message"].get("content") or "").strip()
                    if reply2:
                        return dict(local, mode="llm", reply=reply2)
                raise
            choice = resp["choices"][0]["message"]
            tool_calls = choice.get("tool_calls") or []
            if not tool_calls:
                if photo and not context["identification"]:
                    return _local_fallback(db, message, context)
                reply_text = (choice.get("content") or "").strip()
                return {
                    "mode": "llm",
                    "reply": reply_text or "已完成查询，请查看下方卡片。",
                    "cards": list(context["cards"].values()),
                    "identification": context.get("identification"),
                    "tool_calls": used_tools,
                }
            messages.append(choice)
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"].get("arguments") or "{}")
                except ValueError:
                    fn_args = {}
                used_tools.append(fn_name)
                result = _execute_tool(db, fn_name, fn_args, context)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        return _local_fallback(db, message, context)
    except (OSError, ValueError, KeyError, IndexError, AttributeError, TypeError):
        fallback = _local_fallback(db, message, context)
        fallback["reply"] += "\n（当前大模型接口暂时不可用，已自动切换为本地查库模式。）"
        return fallback
    finally:
        _LLM_SLOTS.release()
