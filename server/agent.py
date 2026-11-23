"""CampusCats conversational Agent with OpenAI-compatible Tool Calling.

Works in two modes:
- LLM Tool-Calling mode when CAMPUSCATS_LLM_API_KEY is set.
- Deterministic local assistant fallback when no API key is configured, so
  search, statistics, and photo-based DB-check/breed lookup work out of the box.
"""

import json
import os
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

import ai_vision
import encoder
import surveys
from catalog import SIGHTING_QUERY, catalog, identify, iso, serialize, stats
from media import Problem

DEFAULT_CHAT_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = (
    "你是「猫迹 · 校园猫图鉴」的智能校园猫管家。你可以调用工具查询数据库中的校园猫档案、"
    "统计校园猫分布、查最近目击记录，并对用户上传的照片执行「是否已在库中记录过」的查重与品种/花色识别。\n"
    "回答原则：\n"
    "1. 严格基于工具返回的真实数据库与识别结果回答，绝不编造不存在的猫档案或目击记录。\n"
    "2. 涉及品种识别时，清晰区分「AI 初判」与「维护者已核验（verified）」。\n"
    "3. 若用户上传了照片，先调用 identify_uploaded_photo，再明确告知：当前照片是否有可供比对的档案、是否需要补拍、"
    "最相似的候选猫是谁（附匹配度）、以及品种/花色/特征初判。\n"
    "4. 语气温暖、简洁、清晰，适合手机端阅读。"
)

TOOLS = [
    {"type": "function", "function": {"name": "weekly_surveys",
     "description": "查看本周已知校园区域的定点观察和零目击统计及尚待观察的区域。",
     "parameters": {"type": "object", "properties": {}}}},
    {
        "type": "function",
        "function": {
            "name": "search_cats",
            "description": "按名字、别名、花色、品种或校园区域检索已建档的校园猫。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词（名字、别名、花色或品种）"},
                    "area": {"type": "string", "description": "校园区域关键词，如 图书馆、食堂"},
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
            "description": "对用户本轮随消息上传的猫照片执行数据库查重（判断是否已在库）及品种/花色/特征识别。",
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
    return {
        "mode": "llm" if cfg["enabled"] else "local_fallback",
        "chat_model": chat_model if cfg["enabled"] else None,
        "scope": cfg.get("scope", "shared"),
        "vision_mode": "vlm" if cfg["enabled"] and cfg["vision_model"] else "local_heuristic",
        "vision_model": cfg["vision_model"] if cfg["enabled"] else None,
        "onnx_encoder": bool(encoder.VERSION),
    }


def _compact_card(cat):
    return {
        "id": cat["id"],
        "name": cat["name"],
        "coat": cat.get("coat", ""),
        "breed": cat.get("breed", ""),
        "breed_status": cat.get("breed_status", "unknown"),
        "area": cat.get("area", ""),
        "last_seen": cat.get("last_seen", ""),
        "sightings": cat.get("sightings", 0),
        "aliases": cat.get("aliases", []),
        "photo_url": cat.get("photo_url", ""),
        "thumbnail_url": cat.get("thumbnail_url", ""),
    }


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
                [cat.get("name", ""), cat.get("coat", ""), cat.get("breed", ""), cat.get("area", ""), *cat.get("aliases", [])]
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
        recent = serialize(db, rows)
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
        items = serialize(db, rows)
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
        boxes = context.get("boxes") or [[0, 0, 1, 1]]
        result = identify(db, {"photo": photo, "boxes": boxes, "area": area, "cloud_photo":context["cloud_photo"]})
        context["identification"] = result
        for entry in result["results"]:
            for cand in entry["candidates"]:
                context["cards"][cand["id"]] = _compact_card(cand)
        return result

    return {"error": f"未知工具：{name}"}


def _call_chat_llm(messages, cfg, *, require_photo=False):
    chat_model = cfg.get("chat_model") or os.getenv("CAMPUSCATS_LLM_MODEL", "").strip() or DEFAULT_CHAT_MODEL
    payload = {
        "model": chat_model,
        "temperature": 0.3,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": {"type":"function","function":{"name":"identify_uploaded_photo"}}
                       if require_photo
                       else "auto",
    }
    if cfg.get("scope"):
        from providers import completion
        payload.pop("temperature")
        if cfg["protocol"] == "chat":
            payload.pop("tools")
            payload.pop("tool_choice")
        return completion(cfg, payload)
    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
            "User-Agent": "CampusCats-Agent/2.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _local_fallback(db, message, context):
    """Deterministic local assistant when no LLM API key is configured."""
    lines = []
    used_tools = []
    text = message.strip()

    if context.get("photo"):
        used_tools.append("identify_uploaded_photo")
        res = _execute_tool(db, "identify_uploaded_photo", {"area": context.get("area", "")}, context)
        for idx, item in enumerate(res.get("results", []), start=1):
            rec = item.get("record_status") or {}
            ai_p = item.get("ai_profile") or {}
            lines.append(f"【照片识别 · 猫 {idx}】")
            lines.append(f"• 在库查重：{rec.get('summary', '暂无法判断')}")
            if ai_p:
                feat = "、".join(ai_p.get("features") or [])
                lines.append(
                    f"• 品种与花色初判：{ai_p.get('breed', '未知')}｜花色：{ai_p.get('coat', '待补')}"
                    + (f"｜特征：{feat}" if feat else "")
                )

    if any(k in text for k in ("定点", "观察", "周报", "零目击")):
        used_tools.append("weekly_surveys")
        report = _execute_tool(db, "weekly_surveys", {}, context)
        areas = report["areas"]
        lines.append("本周暂无区域观察资料。" if not areas else "本周区域周报（优先列出观察较少的区域）")
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
            f"全校目前已建档 {st['cats']} 只猫，近 30 天活跃 {st['active']} 只，待辨认记录 {st['pending']} 条。"
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
        # Clean common question words for better keyword matching
        cleaned = text
        for stop in ("请问", "帮我", "找一下", "查一下", "有没有", "一只", "这只猫", "叫什么", "在哪", "在哪里", "的猫", "小猫", "猫", "？", "?", "。"):
            cleaned = cleaned.replace(stop, " ")
        tokens = [tok for tok in cleaned.split() if tok]
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
            names = "、".join(f"{c['name']}（{c['coat'] or '花色待补'} · {c['area'] or '区域待补'}）" for c in res["cats"])
            lines.append(f"按「{tok}」为你找到 {res['total_matched']} 只校园猫：{names}。")

    if not lines:
        lines.append("你好！你可以发一张猫照片让我查查库里有没有记录过、是什么品种花色，或直接问我某区域有哪些校园猫。")

    return {
        "mode": "local_fallback",
        "reply": "\n".join(lines),
        "cards": list(context["cards"].values()),
        "identification": context.get("identification"),
        "tool_calls": used_tools,
    }


def chat(db, body):
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

    context = {"cloud_photo":body.get("cloud_photo") is True, "photo": photo, "area": area, "boxes": boxes, "cards": {}, "identification": None}
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

    used_tools = []
    try:
        if cfg.get("protocol") == "chat":
            local = _local_fallback(db, message, context)
            messages.insert(1, {"role":"system", "content":"本轮校园图鉴的查询结果供参考：" + local["reply"]})
            response = _call_chat_llm(messages, cfg)
            reply = response["choices"][0]["message"]["content"]
            if not isinstance(reply, str) or not reply.strip():
                raise ValueError("Agent 未返回文本。")
            return dict(local, mode="llm", reply=reply)
        for _ in range(4):
            resp = _call_chat_llm(messages, cfg, require_photo=bool(photo and not context["identification"]))
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
        # Final fallback summary if model exhausted tool loop
        return _local_fallback(db, message, context)
    except (OSError, ValueError, KeyError, IndexError, AttributeError, TypeError):
        fallback = _local_fallback(db, message, context)
        fallback["reply"] += "\n（当前大模型接口暂时不可用，已自动切换为本地查库模式。）"
        return fallback
