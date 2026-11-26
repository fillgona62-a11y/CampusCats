"""Persistent pilot catalog. Every write is checked again inside its transaction."""
import hashlib
import json
import re
import sqlite3
import threading
import time
from collections import Counter, OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ai_vision
import clip_classifier
import detector
import face_match
from face_match import automatic_match
from media import Problem, canonical_photo, prepare, save_media, validate_boxes
from vision import DEFAULT_MAX_DISTANCE, MODEL_VERSION, analyze_crop, assess_db_match, distance_to_similarity, pixel_box, rank_candidates

SYLU_PRESET_AREAS = (
    "图书馆（琴园环路）",
    "兵器博物馆 / 兵器广场",
    "志学堂",
    "教学楼区",
    "餐饮服务中心（食堂）",
    "学生生活区（宿舍）",
    "体育场 / 操场",
    "琴园绿地",
    "北门（汇泉东路）",
    "南门（南屏中路）",
)
SEX_VALUES = ("unknown", "female", "male")
NEUTERED_VALUES = ("unknown", "neutered", "intact")
CARE_VALUES = ("school", "attention", "adopted", "memorial")
_REF_CACHE_LOCK = threading.Lock()
_REF_CACHE = OrderedDict()
_EXTRA_LOOKUP_WORKERS = threading.BoundedSemaphore(2)


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def migrate(db):
    """Idempotently add newer columns when opening an existing pilot database."""
    existing = {row["name"] for row in db.execute("PRAGMA table_info(cats)")}
    migrations = (
        ("sex", "TEXT NOT NULL DEFAULT 'unknown' CHECK(sex IN ('unknown','female','male'))"),
        ("neutered", "TEXT NOT NULL DEFAULT 'unknown' CHECK(neutered IN ('unknown','neutered','intact'))"),
        ("care_status", "TEXT NOT NULL DEFAULT 'school' CHECK(care_status IN ('school','attention','adopted','memorial'))"),
        ("temperament", "TEXT NOT NULL DEFAULT ''"),
        ("cover_sighting_id", "INTEGER DEFAULT NULL"),
    )
    for col, spec in migrations:
        if col not in existing:
            db.execute(f"ALTER TABLE cats ADD COLUMN {col} {spec}")
    existing_frames = {row["name"] for row in db.execute("PRAGMA table_info(frames)")}
    for col, spec in (
        ("latitude", "REAL"),
        ("longitude", "REAL"),
        ("location_accuracy", "REAL"),
    ):
        if col not in existing_frames:
            db.execute(f"ALTER TABLE frames ADD COLUMN {col} {spec}")


def choice_field(body, key, allowed, default):
    if key not in body or body.get(key) is None or body.get(key) == "":
        return default
    val = body.get(key)
    if not isinstance(val, str) or val not in allowed:
        raise Problem(f"请检查 {key} 选项。")
    return val


def area_field(body, key="area", size=80, *, required=False):
    raw = field(body, key, size, required=required)
    return " ".join(raw.split())


def iso(value=None):
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def field(body, key, size, *, required=False):
    value = body.get(key, "")
    if not isinstance(value, str) or len(value) > size or (required and not value.strip()):
        raise Problem(f"请检查 {key} 字段，最长 {size} 个字符。")
    return value.strip()


def one(db, sql, *args):
    row = db.execute(sql, args).fetchone()
    if row is None:
        raise Problem("记录不存在或已撤回。", 404)
    return row


def audit(db, actor, kind, target, before, after, reason):
    db.execute("INSERT INTO audit(actor,kind,target,before_state,after_state,reason,created_at) VALUES(?,?,?,?,?,?,?)",
               (actor, kind, target, json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False), reason, iso()))


def catalog(db):
    rows = db.execute("""
        WITH ranked AS (
          SELECT s.id,s.cat_id,f.area,f.observed_at,
                 COUNT(*) OVER (PARTITION BY s.cat_id) AS sightings,
                 ROW_NUMBER() OVER (PARTITION BY s.cat_id ORDER BY f.observed_at DESC,s.id DESC) AS priority
          FROM sightings s JOIN frames f ON f.id=s.frame_id WHERE s.status='confirmed'
        )
        SELECT c.id,c.name,c.coat,c.breed,c.sex,c.neutered,c.care_status,c.temperament,
               cs.id AS cover_sighting_id,COALESCE(cs.id,r.id) AS sid,
               r.area,r.observed_at AS last_seen,r.sightings
        FROM ranked r
        JOIN cats c ON c.id=r.cat_id
        LEFT JOIN sightings cs ON cs.id=c.cover_sighting_id AND cs.cat_id=c.id AND cs.status='confirmed'
        WHERE r.priority=1
        ORDER BY r.observed_at DESC,c.id
    """)
    cats = {}
    for row in rows:
        cat = dict(row)
        cat["breed_status"] = "verified" if cat["breed"] else "unknown"
        cat["aliases"] = []
        sighting_id = cat.pop("sid")
        cat["photo_url"] = f"/media/crop/{sighting_id}.jpg"
        cat["thumbnail_url"] = f"/media/thumb/{sighting_id}.jpg"
        cats[cat["id"]] = cat
    for row in db.execute("SELECT cat_id,name FROM aliases WHERE status='approved' ORDER BY id"):
        if row["cat_id"] in cats:
            cats[row["cat_id"]]["aliases"].append(row["name"])
    return cats


def stats(db, cats):
    cutoff = iso(datetime.now(timezone.utc) - timedelta(days=30))
    return {"cats": len(cats), "active": sum(c["last_seen"] >= cutoff for c in cats.values()),
            "pending": db.execute("SELECT count(*) FROM sightings WHERE status='pending'").fetchone()[0]}


SIGHTING_QUERY = """
 SELECT s.id,s.box,s.analysis,s.status,s.cat_id,s.suggested_cat_id,c.name AS cat_name,
        CASE WHEN a.sighting_id IS NOT NULL THEN 'automatic'
             WHEN s.status='confirmed' THEN 'reviewed' END AS identity_source,
        f.id AS frame_id,f.observed_at,f.area,f.note,f.latitude,f.longitude,f.location_accuracy
 FROM sightings s JOIN frames f ON f.id=s.frame_id LEFT JOIN cats c ON c.id=s.cat_id
 LEFT JOIN auto_identity a ON a.sighting_id=s.id
"""


def _ref_cache_key(db):
    db_list = db.execute("PRAGMA database_list").fetchone()
    db_file = db_list[2] if db_list else ""
    if not db_file:
        return None
    confirmed, max_sid = db.execute(
        "SELECT COUNT(*), COALESCE(MAX(id),0) FROM sightings WHERE status='confirmed'"
    ).fetchone()
    auto_count = db.execute("SELECT COUNT(*) FROM auto_identity").fetchone()[0]
    max_audit = db.execute("SELECT COALESCE(MAX(id),0) FROM audit").fetchone()[0]
    return (db_file, confirmed, max_sid, auto_count, max_audit, MODEL_VERSION)


def references(db):
    cache_key = _ref_cache_key(db)
    if cache_key is not None:
        with _REF_CACHE_LOCK:
            cached = _REF_CACHE.get(cache_key)
            if cached is not None:
                _REF_CACHE.move_to_end(cache_key)
                return list(cached)
    rows = db.execute("""
        WITH reviewed AS (
            SELECT s.id,s.cat_id,s.analysis,s.crop,s.box,f.image,date(f.observed_at,'+8 hours') AS day,
                   ROW_NUMBER() OVER(PARTITION BY s.cat_id,date(f.observed_at,'+8 hours') ORDER BY s.id DESC) AS within_day
            FROM sightings s JOIN frames f ON f.id=s.frame_id
            LEFT JOIN auto_identity a ON a.sighting_id=s.id
            WHERE s.status='confirmed' AND a.sighting_id IS NULL
            AND json_extract(s.analysis,'$.usable')=1 AND json_extract(s.analysis,'$.version')=?
        ) SELECT id,cat_id,analysis,crop,box,image,day FROM (
            SELECT reviewed.*, ROW_NUMBER() OVER(PARTITION BY cat_id ORDER BY within_day,id DESC) AS n FROM reviewed
        ) WHERE n<=12 ORDER BY cat_id,n
    """, (MODEL_VERSION,))
    parsed = [(r["cat_id"], dict(json.loads(r["analysis"]), _reference_id=r["id"],
                                 crop_file=r["crop"], frame=r["image"], box=tuple(json.loads(r["box"])), day=r["day"])) for r in rows]
    if cache_key is not None:
        with _REF_CACHE_LOCK:
            _REF_CACHE[cache_key] = tuple(parsed)
            while len(_REF_CACHE) > 6:
                _REF_CACHE.popitem(last=False)
    return parsed


def matched_profiles(analysis, refs, cats, *, limit=3, area=""):
    cat_areas = {cid: c.get("area", "") for cid, c in cats.items()}
    candidates = []
    for match in rank_candidates(analysis, refs, limit=limit, area=area, cat_areas=cat_areas):
        target = match["reference_id"]
        candidates.append(dict(
            cats[match["cat_id"]],
            reference_id=target,
            distance=match["distance"],
            similarity=match["similarity"],
            photo_url=f"/media/crop/{target}.jpg",
            thumbnail_url=f"/media/thumb/{target}.jpg",
        ))
    return candidates


def breed_hint(candidates):
    verified = {cat["id"]:cat["breed"] for cat in candidates
                if cat["breed_status"] == "verified" and cat["breed"]}
    labels = set(verified.values())
    if len(verified) < 2 or len(labels) != 1:
        return None
    return {"label":next(iter(labels)), "kind":"library_comparison", "cat_ids":list(verified)}


def _load_candidate_crops(candidates, refs, media_dir):
    from PIL import Image

    def read_crop(ref):
        if ref.get("crop_file"):
            try:
                with Image.open(Path(media_dir) / ref["crop_file"]) as saved:
                    saved.thumbnail((256, 256), Image.Resampling.LANCZOS)
                    return saved.convert("RGB")
            except OSError:
                return None
        try:
            with Image.open(Path(media_dir) / ref["frame"]) as image:
                crop = image.crop(pixel_box(image, ref["box"]))
                crop.thumbnail((256, 256), Image.Resampling.LANCZOS)
                return crop.convert("RGB")
        except (KeyError, OSError, TypeError, ValueError):
            return None

    by_cat = defaultdict(list)
    for cat_id, ref in refs:
        by_cat[cat_id].append(ref)
    items = []
    primary_refs = []
    for candidate in candidates:
        pool = by_cat[candidate["id"]]
        ordered = sorted(pool, key=lambda r: r.get("_reference_id") != candidate["reference_id"])
        for ref in ordered:
            crop = read_crop(ref)
            if crop is None:
                continue
            ref_id = ref["_reference_id"]
            items.append(dict(candidate, crop=crop, reference_id=ref_id,
                              photo_url=f"/media/crop/{ref_id}.jpg", thumbnail_url=f"/media/thumb/{ref_id}.jpg"))
            primary_refs.append(ref)
            break

    # An extra view fills a spare tile; it never displaces another identity.
    spare = 5 - len(items)
    for item, first in zip(items, primary_refs):
        if not spare:
            break
        others = (r for r in by_cat[item["id"]] if r.get("frame") != first.get("frame"))
        for ref in sorted(others, key=lambda r: r.get("day") == first.get("day")):
            alternate = read_crop(ref)
            if alternate is not None:
                item["alternate"] = alternate
                spare -= 1
                break
    return items


def _coat_conflict(query_coat, cand_coat):
    """Return True when two coats are mutually incompatible (e.g. pure black vs orange/white)."""
    q = (query_coat or "").strip()
    c = (cand_coat or "").strip()
    if not q or not c:
        return False
    groups = (
        ("纯白", ("纯黑", "橘猫", "玳瑁", "黑猫")),
        ("纯黑", ("纯白", "橘猫", "橘白", "三花", "白猫")),
        ("橘猫", ("纯黑", "纯白", "奶牛", "蓝猫", "蓝白", "灰白")),
        ("奶牛", ("橘猫", "玳瑁")),
    )
    for key, incompatible in groups:
        if key in q and any(inc in c for inc in incompatible):
            return True
        if key in c and any(inc in q for inc in incompatible):
            return True
    return False


def detect_photo(body):
    _, image = canonical_photo(body.get("photo"))
    info = detector.inspect_image_subjects(image)
    detections = info["cats"]
    return {
        "detector_enabled": detector.is_enabled() or clip_classifier.is_enabled(),
        "detections": detections,
        "boxes": [d["box"] for d in detections],
        "non_cat_type": info["non_cat_type"],
    }


def _identify_boxes(boxes, identify_one, cloud_ready):
    if len(boxes) < 2 or not cloud_ready or not _EXTRA_LOOKUP_WORKERS.acquire(blocking=False):
        return [identify_one(box) for box in boxes]
    try:
        results = []
        with ThreadPoolExecutor(max_workers=1) as worker:
            for index in range(0, len(boxes), 2):
                second = None
                if index + 1 < len(boxes):
                    second = worker.submit(copy_context().run, identify_one, boxes[index + 1])
                results.append(identify_one(boxes[index]))
                if second is not None:
                    results.append(second.result())
        return results
    finally:
        _EXTRA_LOOKUP_WORKERS.release()


def _review_digest(photo, boxes):
    coordinates = [[float(v) for v in box] for box in boxes]
    return hashlib.sha256(json.dumps([photo, coordinates], separators=(",", ":")).encode()).hexdigest()


def identify(db, body, media_dir=None, *, reviewer_uid=None):
    mode = body.get("box_mode", "manual")
    boxes = validate_boxes(body.get("boxes")) if mode == "manual" else []
    if mode not in ("manual", "auto", "cloud_review"):
        raise Problem("未知的识别方式。")
    area = area_field(body, "area", 80) if body.get("area") is not None else ""
    _, image = canonical_photo(body.get("photo"))
    deadline = time.monotonic() + 45
    allow_remote = body.get("cloud_photo") is True
    cloud_vlm_ready = allow_remote and ai_vision.has_cloud_vlm()
    frame_info = None
    detected_boxes = None
    if mode == "cloud_review":
        if not cloud_vlm_ready:
            raise Problem("云端复核暂不可用，可以手动框选后再查。", 503)
        scene = ai_vision.review_scene(image, timeout=15)
        if not scene or scene.get("uncertain") or not isinstance(scene.get("boxes"), list):
            raise Problem("云端未能确认照片中的猫，可以手动框选。", 422)
        if not scene["boxes"]:
            return {"results": [], "detected_boxes": [], "box_source": mode}
        try:
            boxes = validate_boxes(scene["boxes"])
        except Problem:
            raise Problem("云端未能准确框出目标，可以手动框选。", 422) from None
        detected_boxes = boxes
    elif mode == "auto":
        scan = detector.inspect_image_subjects(image)
        detected_boxes = [item["box"] for item in scan["cats"][:8]]
        if not detected_boxes and (detector.is_enabled() or clip_classifier.is_enabled()):
            return {"results": [], "detected_boxes": [], "box_source": mode,
                    "non_cat_type": scan["non_cat_type"]}
        boxes = detected_boxes or [[0, 0, 1, 1]]
    elif detector.is_enabled():
        frame_info = detector._run_full_frame_scan(image)
    if detected_boxes:
        frame_info = {"cats": [{"box": box} for box in detected_boxes]}
    db.execute("BEGIN")
    cats = catalog(db)
    refs = references(db)
    db.commit()
    reference_count = len({r[0] for r in refs})

    def identify_one(box):
        gate = detector.verify_box_is_cat(
            image, box, frame_info=frame_info, cloud_vlm_active=cloud_vlm_ready
        )
        if not gate["is_cat"]:
            return {
                "box": box,
                "quality": [gate["reason"]],
                "warnings": [gate["reason"]],
                "usable": False,
                "not_cat": True,
                "non_cat_type": gate["non_cat_type"],
                "candidates": [],
                "breed_hint": None,
                "record_status": assess_db_match(
                    [], reference_count, area=area, usable=False,
                    not_cat=True, not_cat_reason=gate["reason"],
                ),
                "ai_profile": None,
                "vlm_compare": None,
            }

        # === 第一关（纯本地快速辅助初筛）：仅提取个体特征向量 + SIFT 局部重排，召回相似的已审核档案 ===
        analysis = analyze_crop(image, box)
        crop = image.crop(pixel_box(image, box)).convert("RGB")
        candidates = matched_profiles(analysis, refs, cats, limit=5, area=area)

        # 仅当未启用云端大模型时才用本地辅助花色做互斥过滤，避免本地暗色毛误判拖累云端候选
        ai_profile = None
        if not cloud_vlm_ready and analysis["usable"]:
            ai_profile = ai_vision.classify_cat_crop(
                crop, allow_remote=False, precomputed_clip=gate.get("clip_analysis")
            )
            if ai_profile and ai_profile.get("source") != "local_heuristic" and candidates:
                q_coat = ai_profile.get("coat", "")
                filtered = []
                for cand in candidates:
                    if _coat_conflict(q_coat, cand.get("coat", "")):
                        new_dist = round(cand["distance"] + 0.08, 5)
                        if new_dist > DEFAULT_MAX_DISTANCE:
                            continue
                        cand = dict(cand, distance=new_dist, similarity=distance_to_similarity(new_dist))
                    filtered.append(cand)
                filtered.sort(key=lambda c: (c["distance"], str(c["id"])))
                candidates = filtered

        if analysis["usable"] and candidates and media_dir is not None:
            candidates = face_match.rerank_with_local_features(crop, candidates, refs, media_dir)
            if not cloud_vlm_ready:
                candidates = [c for c in candidates if float(c.get("distance", 0.0)) <= DEFAULT_MAX_DISTANCE]
        candidates = candidates[:5 if cloud_vlm_ready else 3]

        # === 第二关（云端精准拍板，权重最高，每只猫最多仅 1 次云端请求）===
        # 有候选时：只发一张带编号的对比图，一次完成「同猫拍板 + 新猫品种毛色剪耳描述」；
        # 无候选（新猫/空库）时：单独发 NEW 裁剪图识别毛色、品种与剪耳特征。
        remaining = deadline - time.monotonic()
        vlm_compare = None
        if analysis["usable"] and allow_remote and remaining >= 2:
            cand_crops = _load_candidate_crops(candidates, refs, media_dir) if candidates and media_dir is not None and cloud_vlm_ready else []
            if cloud_vlm_ready and media_dir is not None and not cand_crops:
                candidates = []
            if cand_crops:
                candidates = [{k: v for k, v in item.items() if k not in ("crop", "alternate")} for item in cand_crops]
                vlm_compare = ai_vision.compare_candidates_vlm(
                    crop, cand_crops, allow_remote=True, timeout=min(30, max(1, remaining - 1))
                )
                if vlm_compare and vlm_compare.get("is_cat") is False:
                    reason = vlm_compare.get("reason") or "视觉模型复核判定该画面并非猫咪，已拦截档案匹配。"
                    return {
                        "box": box,
                        "quality": [reason],
                        "warnings": [reason],
                        "usable": False,
                        "not_cat": True,
                        "non_cat_type": vlm_compare.get("non_cat_type") or "other",
                        "candidates": [],
                        "breed_hint": None,
                        "record_status": assess_db_match(
                            [], reference_count, area=area, usable=False,
                            not_cat=True, not_cat_reason=reason,
                        ),
                        "ai_profile": None,
                        "vlm_compare": None,
                    }
                if vlm_compare and vlm_compare.get("ai_profile"):
                    ai_profile = vlm_compare["ai_profile"]
                if vlm_compare and vlm_compare.get("verdict") == "same_cat":
                    idx = vlm_compare.get("best_candidate_index")
                    conf = float(vlm_compare.get("confidence", 0.0))
                    if idx and 1 <= idx <= len(candidates) and conf >= 0.55:
                        picked = candidates.pop(idx - 1)
                        picked = dict(picked, similarity=round(max(float(picked.get("similarity", 0.0)), min(0.98, 0.58 + 0.40 * conf)), 4))
                        candidates.insert(0, picked)
                elif vlm_compare and vlm_compare.get("verdict") == "different_cat" and float(vlm_compare.get("confidence", 0.0)) >= 0.55:
                    candidates = []
            else:
                remote_profile = ai_vision.classify_cat_crop(
                    crop, allow_remote=True, timeout=min(28, max(1, remaining - 1)), precomputed_clip=gate.get("clip_analysis")
                )
                if remote_profile and remote_profile.get("is_cat") is False:
                    reason = remote_profile.get("summary") or "视觉模型识别该画面并非猫咪，已拦截档案匹配。"
                    return {
                        "box": box,
                        "quality": [reason],
                        "warnings": [reason],
                        "usable": False,
                        "not_cat": True,
                        "non_cat_type": remote_profile.get("non_cat_type") or "other",
                        "candidates": [],
                        "breed_hint": None,
                        "record_status": assess_db_match(
                            [], reference_count, area=area, usable=False,
                            not_cat=True, not_cat_reason=reason,
                        ),
                        "ai_profile": None,
                        "vlm_compare": None,
                    }
                if remote_profile:
                    ai_profile = remote_profile

            # 若云端超时返回 None，兜底补充本地辅助结果避免页面空白
            if ai_profile is None:
                ai_profile = ai_vision.classify_cat_crop(
                    crop, allow_remote=False, precomputed_clip=gate.get("clip_analysis")
                )

        record_status = assess_db_match(
            candidates, reference_count, area=area, usable=analysis["usable"], vlm_compare=vlm_compare
        )
        if cloud_vlm_ready and candidates and not vlm_compare and analysis["usable"]:
            record_status.update(status="ambiguous", top_cat_id=None, top_cat_name="", area_matched=False,
                                 summary="云端未完成身份比对，可以先查看候选参考照。")
        return {
            "box": box,
            "quality": analysis["warnings"],
            "warnings": analysis["warnings"],
            "usable": analysis["usable"],
            "not_cat": False,
            "candidates": candidates,
            "breed_hint": breed_hint(candidates),
            "record_status": record_status,
            "ai_profile": ai_profile,
            "vlm_compare": vlm_compare,
        }
    results = _identify_boxes(boxes, identify_one, cloud_vlm_ready)
    response = {"results": results, "reference_count": reference_count}
    if mode == "cloud_review" and reviewer_uid and body.get("for_sighting") is True and all(
        r["usable"] and not r["not_cat"] for r in results
    ):
        now = int(time.time())
        db.execute("DELETE FROM photo_reviews WHERE expires<=?", (now,))
        db.execute("INSERT OR REPLACE INTO photo_reviews(user_id,digest,expires) VALUES(?,?,?)",
                   (reviewer_uid, _review_digest(body["photo"], boxes), now + 3600))
        db.commit()
        response["reviewed_for_sighting"] = True
    if detected_boxes is not None:
        response.update(detected_boxes=detected_boxes, box_source=mode)
    return response


def serialize(db, rows, *, private=False):
    result = []
    refs = None
    for raw in rows:
        sighting = dict(raw)
        frame_id = sighting["frame_id"]
        analysis = json.loads(sighting.pop("analysis"))
        sighting["box"] = json.loads(sighting["box"])
        sighting["photo_url"] = f"/media/crop/{sighting['id']}.jpg"
        sighting["candidates"] = []
        if private:
            sighting["frame_url"] = f"/media/frame/{frame_id}.jpg"
            sighting["quality"] = analysis["warnings"]
            sighting["coat_hint"] = analysis.get("coat_hint", "")
            if sighting["status"] == "pending" and analysis["usable"]:
                if refs is None:
                    cats = catalog(db)
                    refs = references(db)
                excluded = {r[0] for r in db.execute(
                    "SELECT cat_id FROM sightings WHERE frame_id=? AND status='confirmed'", (frame_id,))}
                sighting["candidates"] = matched_profiles(analysis, ((i,a) for i,a in refs if i not in excluded),cats)
        else:
            sighting.pop("suggested_cat_id")
            sighting.pop("frame_id")
        result.append(sighting)
    return result


def upload(db, media_dir, uid, body):
    key = field(body, "request_id", 80, required=True)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise Problem("提交编号无效，请重试。")
    area = area_field(body, "area", 80, required=True)
    note = field(body, "note", 800)
    lat = body.get("latitude")
    lng = body.get("longitude")
    acc = body.get("location_accuracy")
    if lat is not None or lng is not None:
        try:
            lat = float(lat)
            lng = float(lng)
        except (TypeError, ValueError):
            raise Problem("定位坐标格式无效。")
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
            raise Problem("定位坐标超出有效范围。")
        if acc is not None:
            try:
                acc = max(0.0, min(10000.0, float(acc)))
            except (TypeError, ValueError):
                acc = None
    else:
        acc = None
    boxes = validate_boxes(body.get("boxes"))
    suggestions = body.get("suggested_cat_ids", [None]*len(boxes))
    if not isinstance(suggestions,list) or len(suggestions)!=len(boxes):
        raise Problem("请检查每只猫的候选选择。")
    selected = [integer(cid) for cid in suggestions if cid is not None]
    if len(selected)!=len(set(selected)):
        raise Problem("同框的两只猫不能选同一个档案。")
    automatic = body.get("automatic", True)
    if type(automatic) is not bool:
        raise Problem("自动归档选项无效。")
    observed = field(body, "observed_at", 40)
    if observed:
        try:
            timestamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp > datetime.now(timezone.utc) + timedelta(minutes=5):
                raise ValueError
            observed = iso(timestamp)
        except (ValueError, OverflowError):
            raise Problem("拍摄时间无效，请检查时区和日期。") from None
    fingerprint_fields = [body.get("photo"), boxes, area, note, observed, suggestions]
    if not automatic:
        fingerprint_fields.append(False)
    fingerprint = hashlib.sha256(json.dumps(fingerprint_fields, separators=(",", ":")).encode()).hexdigest()

    def previous():
        row = db.execute("SELECT id,request_hash FROM frames WHERE user_id=? AND request_id=?", (uid, key)).fetchone()
        if row and row["request_hash"] != fingerprint:
            raise Problem("此提交编号已被其他内容使用，请重新提交。", 409)
        return row["id"] if row else None

    frame_id = previous()
    if frame_id is None:
        reviewed = body.get("reviewed_photo") is True and db.execute(
            "SELECT 1 FROM photo_reviews WHERE user_id=? AND digest=? AND expires>?",
            (uid, _review_digest(body.get("photo"), boxes), int(time.time())),
        ).fetchone()
        if reviewed:
            automatic = False
        for cat_id in selected:
            one(db, "SELECT 1 FROM sightings WHERE cat_id=? AND status='confirmed'", cat_id)
        ref_revision = revision(db) if automatic else None
        refs = references(db) if automatic else []
        reference_days = defaultdict(set)
        for cat_id, ref in refs:
            if ref["day"]:
                reference_days[cat_id].add(ref["day"])
        if not any(len(days) >= 2 for days in reference_days.values()):
            refs = []
        if not reviewed and (detector.is_enabled() or clip_classifier.is_enabled()):
            _, check_img = canonical_photo(body.get("photo"))
            for box in boxes:
                gate = detector.verify_box_is_cat(check_img, box)
                if not gate["is_cat"]:
                    raise Problem(gate["reason"] or "未在照片中检测到猫咪（识别为人像或非猫画面），请上传清晰的猫咪照片。", 422)
        filename, targets, media = prepare(body.get("photo"), boxes, verify=bool(refs))
        if db.execute("SELECT 1 FROM frames WHERE image=?", (filename,)).fetchone():
            frame_id = previous()
            if frame_id is None:
                raise Problem("这张相同的照片已提交过，请使用本次目击的新照片。", 409)
        if frame_id is None:
            matches = []
            for _, _, _, analysis, features in targets:
                ranked = rank_candidates(analysis, refs, limit=7) if features is not None else []
                matches.append(automatic_match(features, ranked, refs, media_dir))
            proposed = Counter(match[0] for match in matches if match)
            # Persist immutable content-addressed blobs before taking SQLite's global writer lock.
            created = save_media(media_dir, media)
            try:
                db.execute("BEGIN IMMEDIATE")
                frame_id = previous()
                if frame_id is None:
                    for cat_id in selected:
                        one(db, "SELECT 1 FROM sightings WHERE cat_id=? AND status='confirmed'",cat_id)
                    if db.execute("SELECT 1 FROM frames WHERE image=?", (filename,)).fetchone():
                        raise Problem("这张相同的照片已提交过，请使用本次目击的新照片。", 409)
                    frame_id = db.execute("""
                        INSERT INTO frames(user_id,request_id,request_hash,image,area,note,observed_at,latitude,longitude,location_accuracy)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""", (uid, key, fingerprint, filename, area, note, observed or iso(), lat, lng, acc)).lastrowid
                    current_refs = set()
                    if proposed and ref_revision == revision(db):
                        current_refs = {ref["_reference_id"] for _, ref in references(db)}
                    for index, ((box, crop, thumb, analysis, _), suggestion, match) in enumerate(zip(targets,suggestions,matches)):
                        record = db.execute("INSERT INTO sightings(frame_id,box,crop,analysis,suggested_cat_id) "
                                            "VALUES(?,?,?,?,?)",(frame_id,json.dumps(box),crop,json.dumps(analysis),suggestion))
                        db.execute("INSERT INTO thumbnails(sighting_id,image) VALUES(?,?)",(record.lastrowid,thumb))
                        if match:
                            cat_id, first_reference, second_reference = match
                            other_suggestions = suggestions[:index] + suggestions[index+1:]
                            if (suggestion in (None, cat_id) and proposed[cat_id] == 1 and cat_id not in other_suggestions
                                    and {first_reference, second_reference} <= current_refs):
                                sighting_id = record.lastrowid
                                db.execute("UPDATE sightings SET status='confirmed',cat_id=? WHERE id=?", (cat_id, sighting_id))
                                db.execute("INSERT INTO auto_identity VALUES(?,?,?)",
                                           (sighting_id, first_reference, second_reference))
                                audit(db, uid, "identity_auto", sighting_id, None, list(match), "两天人工参考照的脸部特征一致")
                db.commit()
            except BaseException:
                db.rollback()
                if created:
                    db.execute("BEGIN IMMEDIATE")
                    for item in created:
                        in_use = db.execute(
                            "SELECT 1 FROM frames WHERE image=? UNION ALL SELECT 1 FROM sightings WHERE crop=? "
                            "UNION ALL SELECT 1 FROM thumbnails WHERE image=? LIMIT 1",
                            (item, item, item),
                        ).fetchone()
                        if not in_use:
                            (media_dir / item).unlink(missing_ok=True)
                    db.commit()
                raise
    rows = db.execute(SIGHTING_QUERY + " WHERE f.id=? ORDER BY s.id", (frame_id,))
    return {"sightings": serialize(db, rows, private=True)}


def revision(db):
    return db.execute("SELECT COALESCE(MAX(id),0) FROM audit WHERE kind='identity'").fetchone()[0]


def similar_pending(db, sid):
    target = one(db, "SELECT analysis,frame_id FROM sightings WHERE id=? AND status='pending'", sid)
    rows = db.execute("""
        SELECT s.id,s.analysis,f.area,f.observed_at FROM sightings s JOIN frames f ON f.id=s.frame_id
        WHERE s.status='pending' AND s.frame_id!=? ORDER BY s.id DESC LIMIT 251
        """, (target["frame_id"],)).fetchall()
    candidates = rank_candidates(json.loads(target["analysis"]),
                                 ((r["id"],json.loads(r["analysis"])) for r in rows[:250]))
    by_id = {r["id"]:r for r in rows}
    matches = []
    for candidate in candidates:
        row = by_id[candidate["cat_id"]]
        matches.append({"id":row["id"],"area":row["area"],"observed_at":row["observed_at"],
                        "photo_url":f"/media/crop/{row['id']}.jpg"})
    return {"sightings":matches, "limited":len(rows)>250}


def review_identity(db, actor, sid, body):
    action = field(body, "action", 12, required=True)
    reason = field(body, "reason", 800, required=True)
    db.execute("BEGIN IMMEDIATE")
    row = one(db, "SELECT frame_id,status,cat_id FROM sightings WHERE id=?", sid)
    if action == "reopen":
        if row["status"] == "pending":
            raise Problem("这条记录已经在审核队列中。", 409)
        status, cat_id = "pending", None
    else:
        if row["status"] != "pending":
            raise Problem("这条记录已处理，请刷新后再查看。", 409)
        status, cat_id = "confirmed", None
        if action == "new":
            supplied = body.get("catalog_revision")
            if supplied is not None and supplied != revision(db):
                raise Problem("审核期间图鉴已有变动，请刷新后再次比对再建档。",409)
            name = field(body, "name", 60, required=True)
            coat = field(body, "coat", 80)
            sex = choice_field(body, "sex", SEX_VALUES, "unknown")
            neutered = choice_field(body, "neutered", NEUTERED_VALUES, "unknown")
            care_status = choice_field(body, "care_status", CARE_VALUES, "school")
            temperament = field(body, "temperament", 120)
            cat_id = db.execute(
                "INSERT INTO cats(name,coat,sex,neutered,care_status,temperament) VALUES(?,?,?,?,?,?)",
                (name, coat, sex, neutered, care_status, temperament),
            ).lastrowid
        elif action == "match":
            cat_id = one(db, "SELECT id FROM cats WHERE id=?", integer(body.get("cat_id")))["id"]
            if db.execute("SELECT 1 FROM sightings WHERE frame_id=? AND cat_id=?", (row["frame_id"],cat_id)).fetchone():
                raise Problem("同框的另一个标记已经关联到这只猫，请重新辨认。", 409)
        elif action == "reject":
            status = "rejected"
        else:
            raise Problem("无效的审核操作。")
    db.execute("UPDATE sightings SET status=?,cat_id=? WHERE id=?", (status, cat_id, sid))
    db.execute("DELETE FROM auto_identity WHERE sighting_id=?", (sid,))
    audit(db, actor, "identity", sid, [row["status"],row["cat_id"]], [status,cat_id], reason)
    return {"id": sid, "status": status, "cat_id": cat_id}


def integer(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise Problem("编号无效。")
    return value


def review_breed(db, actor, cat_id, body):
    breed = field(body, "breed", 80)
    evidence = field(body, "evidence", 800, required=bool(breed))
    db.execute("BEGIN IMMEDIATE")
    row = one(db, "SELECT breed,evidence FROM cats WHERE id=?", cat_id)
    db.execute("UPDATE cats SET breed=?,evidence=? WHERE id=?", (breed, evidence if breed else "", cat_id))
    audit(db, actor, "breed", cat_id, dict(row), {"breed":breed,"evidence":evidence}, evidence or "撤回认证")
    return {"ok": True}


def update_cat_profile(db, actor, cat_id, body):
    reason = field(body, "reason", 400) or "更新档案信息"
    db.execute("BEGIN IMMEDIATE")
    row = dict(one(
        db,
        "SELECT name,coat,sex,neutered,care_status,temperament,cover_sighting_id FROM cats WHERE id=?",
        cat_id,
    ))
    name = field(body, "name", 60, required=True) if "name" in body else row["name"]
    coat = field(body, "coat", 80) if "coat" in body else row["coat"]
    sex = choice_field(body, "sex", SEX_VALUES, row["sex"]) if "sex" in body else row["sex"]
    neutered = choice_field(body, "neutered", NEUTERED_VALUES, row["neutered"]) if "neutered" in body else row["neutered"]
    care_status = choice_field(body, "care_status", CARE_VALUES, row["care_status"]) if "care_status" in body else row["care_status"]
    temperament = field(body, "temperament", 120) if "temperament" in body else row["temperament"]
    cover_id = row["cover_sighting_id"]
    if "cover_sighting_id" in body:
        supplied_cover = body.get("cover_sighting_id")
        if supplied_cover is None:
            cover_id = None
        else:
            cover_id = integer(supplied_cover)
            one(db, "SELECT 1 FROM sightings WHERE id=? AND cat_id=? AND status='confirmed'", cover_id, cat_id)
    updated = {
        "name": name,
        "coat": coat,
        "sex": sex,
        "neutered": neutered,
        "care_status": care_status,
        "temperament": temperament,
        "cover_sighting_id": cover_id,
    }
    db.execute(
        "UPDATE cats SET name=?,coat=?,sex=?,neutered=?,care_status=?,temperament=?,cover_sighting_id=? WHERE id=?",
        (name, coat, sex, neutered, care_status, temperament, cover_id, cat_id),
    )
    audit(db, actor, "profile", cat_id, row, updated, reason)
    return {"ok": True, "cat_id": cat_id, "cover_sighting_id": cover_id}


def merge_cats(db, actor, source_id, body):
    target_id = integer(body.get("target_id"))
    reason = field(body, "reason", 800, required=True)
    if source_id == target_id:
        raise Problem("不能将档案合并到自身。")
    db.execute("BEGIN IMMEDIATE")
    src = dict(one(db, "SELECT * FROM cats WHERE id=?", source_id))
    dst = dict(one(db, "SELECT * FROM cats WHERE id=?", target_id))
    conflict = db.execute(
        "SELECT 1 FROM sightings a JOIN sightings b ON a.frame_id=b.frame_id "
        "WHERE a.cat_id=? AND b.cat_id=? LIMIT 1",
        (source_id, target_id),
    ).fetchone()
    if conflict:
        raise Problem("两份档案在同一张同框照片中同时出现，请先退回其中一条同框目击再合并。", 409)
    # Revert auto-archived sightings directly assigned to source_id so they can be re-evaluated cleanly.
    db.execute(
        "UPDATE sightings SET status='pending',cat_id=NULL "
        "WHERE cat_id=? AND id IN (SELECT sighting_id FROM auto_identity)",
        (source_id,),
    )
    db.execute(
        "DELETE FROM auto_identity WHERE sighting_id NOT IN "
        "(SELECT id FROM sightings WHERE status='confirmed')"
    )
    # Clear conflicting pending suggestions on frames that already reference target_id.
    db.execute(
        "UPDATE sightings SET suggested_cat_id=NULL WHERE suggested_cat_id=? AND frame_id IN ("
        "SELECT frame_id FROM sightings WHERE cat_id=? OR suggested_cat_id=?)",
        (source_id, target_id, target_id),
    )
    db.execute("UPDATE sightings SET suggested_cat_id=? WHERE suggested_cat_id=?", (target_id, source_id))
    db.execute("UPDATE sightings SET cat_id=? WHERE cat_id=?", (target_id, source_id))

    coat = dst["coat"] or src["coat"]
    breed = dst["breed"] or src["breed"]
    evidence = dst["evidence"] if dst["breed"] else src["evidence"]
    sex = dst["sex"] if dst["sex"] != "unknown" else src["sex"]
    neutered = dst["neutered"] if dst["neutered"] != "unknown" else src["neutered"]
    temperament = dst["temperament"] or src["temperament"]
    cover_id = dst["cover_sighting_id"]
    if cover_id is None and src["cover_sighting_id"] is not None:
        valid_cover = db.execute(
            "SELECT 1 FROM sightings WHERE id=? AND cat_id=? AND status='confirmed'",
            (src["cover_sighting_id"], target_id),
        ).fetchone()
        if valid_cover:
            cover_id = src["cover_sighting_id"]
    db.execute(
        "UPDATE cats SET coat=?,breed=?,evidence=?,sex=?,neutered=?,temperament=?,cover_sighting_id=? WHERE id=?",
        (coat, breed, evidence, sex, neutered, temperament, cover_id, target_id),
    )
    for alias_row in db.execute("SELECT name,submitter,status FROM aliases WHERE cat_id=?", (source_id,)).fetchall():
        if alias_row["name"].casefold() != dst["name"].casefold():
            db.execute(
                "INSERT OR IGNORE INTO aliases(cat_id,name,submitter,status) VALUES(?,?,?,?)",
                (target_id, alias_row["name"], alias_row["submitter"], alias_row["status"]),
            )
    if src["name"].casefold() != dst["name"].casefold():
        db.execute(
            "INSERT OR IGNORE INTO aliases(cat_id,name,submitter,status) VALUES(?,?,?,'approved')",
            (target_id, src["name"], actor),
        )
    db.execute("DELETE FROM aliases WHERE cat_id=?", (source_id,))
    db.execute("DELETE FROM cats WHERE id=?", (source_id,))
    audit(db, actor, "identity", target_id, {"merged_from": src}, {"target_id": target_id}, reason)
    return {"ok": True, "target_id": target_id}


def known_areas(db):
    canonical = [
        r["name"]
        for r in db.execute("SELECT name FROM campus_areas ORDER BY sort_order, name").fetchall()
    ]
    seen = {name.casefold() for name in canonical}
    observed = db.execute("""
        SELECT area FROM (
            SELECT f.area, COUNT(*) AS cnt FROM frames f
            JOIN sightings s ON s.frame_id=f.id WHERE s.status='confirmed' GROUP BY f.area
            UNION ALL
            SELECT area, COUNT(*) AS cnt FROM spot_checks WHERE state='done' GROUP BY area
        ) GROUP BY area ORDER BY SUM(cnt) DESC, area
    """).fetchall()
    extras = []
    for row in observed:
        val = row["area"]
        if val and val.casefold() not in seen:
            seen.add(val.casefold())
            extras.append(val)
    presets = []
    for preset in SYLU_PRESET_AREAS:
        if preset.casefold() not in seen:
            seen.add(preset.casefold())
            presets.append(preset)
    return {"canonical": canonical, "preset": list(SYLU_PRESET_AREAS), "areas": canonical + extras + presets}


def manage_areas(db, actor, body):
    action = field(body, "action", 12, required=True)
    name = area_field(body, "name", 60, required=True)
    db.execute("BEGIN IMMEDIATE")
    if action == "add":
        db.execute("INSERT OR IGNORE INTO campus_areas(name) VALUES(?)", (name,))
    elif action == "remove":
        db.execute("DELETE FROM campus_areas WHERE name=?", (name,))
    else:
        raise Problem("无效的区域管理操作。")
    audit(db, actor, "campus_area", 0, None, {"action": action, "name": name}, "维护校园标准区域")
    return known_areas(db)


def personal_album(db, uid):
    # Keep the most recent personal photo in each area, even after a cat changes areas.
    rows = db.execute("""
        WITH visits AS (
            SELECT s.cat_id,s.id,f.id AS frame_id,f.area,f.observed_at,
                   COUNT(*) OVER place AS encounters, MIN(f.observed_at) OVER place AS first_at,
                   ROW_NUMBER() OVER (place ORDER BY f.observed_at DESC,s.id DESC) AS priority
            FROM frames f JOIN sightings s ON s.frame_id=f.id
            WHERE f.user_id=? AND s.status='confirmed'
            WINDOW place AS (PARTITION BY s.cat_id,f.area)
        )
        SELECT v.cat_id,c.name,v.area,v.encounters,v.first_at,v.observed_at AS last_at,
               v.id AS sighting_id,v.frame_id
        FROM visits v JOIN cats c ON c.id=v.cat_id WHERE v.priority=1
        ORDER BY v.observed_at DESC,v.id DESC
    """, (uid,))
    return {"visits": [dict(row) for row in rows],
            "campus_total": db.execute("SELECT COUNT(DISTINCT cat_id) FROM sightings WHERE cat_id IS NOT NULL").fetchone()[0],
            "pending": db.execute("SELECT COUNT(*) FROM frames f JOIN sightings s ON s.frame_id=f.id "
                                  "WHERE f.user_id=? AND s.status='pending'", (uid,)).fetchone()[0]}


def encounter_receipt(db, uid, frame_id):
    frame = one(db, "SELECT area,observed_at FROM frames WHERE id=? AND user_id=?", frame_id, uid)
    rows = db.execute("""
        SELECT s.id,s.status,s.cat_id,c.name AS cat_name,a.sighting_id IS NOT NULL AS automatic,
               CASE WHEN s.cat_id IS NOT NULL THEN (
                   SELECT COUNT(*) FROM sightings p JOIN frames f ON f.id=p.frame_id
                   WHERE p.cat_id=s.cat_id AND f.user_id=? AND (f.observed_at,p.id)<=(?,s.id)
               ) END AS encounter_number
        FROM sightings s LEFT JOIN cats c ON c.id=s.cat_id
        LEFT JOIN auto_identity a ON a.sighting_id=s.id
        WHERE s.frame_id=? ORDER BY s.id
    """, (uid, frame["observed_at"], frame_id))
    return dict(frame, sightings=[dict(row) for row in rows])


def reunions(db, uid):
    rows = db.execute("""
        SELECT s.id,s.cat_id,c.name,f.observed_at
        FROM sightings s JOIN frames f ON f.id=s.frame_id JOIN cats c ON c.id=s.cat_id
        WHERE f.user_id=? AND s.status='confirmed' ORDER BY f.observed_at,s.id
    """, (uid,))
    grouped = {}
    for row in rows:
        pair = grouped.setdefault(row["cat_id"], [row,row])
        pair[1] = row
    # The pilot campus uses China Standard Time; consecutive local dates constitute a reunion.
    campus_time = timezone(timedelta(hours=8))
    cards = []
    for first, last in grouped.values():
        start = datetime.fromisoformat(first["observed_at"]).astimezone(campus_time).date()
        end = datetime.fromisoformat(last["observed_at"]).astimezone(campus_time).date()
        if end > start:
            cards.append({"cat_id": first["cat_id"], "cat_name": first["name"], "days": (end-start).days,
                          "first_at":first["observed_at"], "last_at":last["observed_at"],
                          "first_photo_url":f"/media/crop/{first['id']}.jpg",
                          "last_photo_url":f"/media/crop/{last['id']}.jpg"})
    return sorted(cards, key=lambda v: v["last_at"], reverse=True)


def map_sightings(db, uid=None):
    """Return confirmed sightings (plus caller's own pending sightings) that carry exact GPS coordinates."""
    if uid is not None:
        rows = db.execute(
            """SELECT s.id, s.cat_id, s.status, c.name AS cat_name, c.coat,
                      f.area, f.note, f.observed_at, f.latitude, f.longitude, f.location_accuracy
               FROM sightings s
               JOIN frames f ON f.id=s.frame_id
               LEFT JOIN cats c ON c.id=s.cat_id
               WHERE f.latitude IS NOT NULL AND f.longitude IS NOT NULL
                 AND (s.status='confirmed' OR (s.status='pending' AND f.user_id=?))
               ORDER BY f.observed_at DESC, s.id DESC
               LIMIT 300""",
            (uid,),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT s.id, s.cat_id, s.status, c.name AS cat_name, c.coat,
                      f.area, f.note, f.observed_at, f.latitude, f.longitude, f.location_accuracy
               FROM sightings s
               JOIN frames f ON f.id=s.frame_id
               LEFT JOIN cats c ON c.id=s.cat_id
               WHERE f.latitude IS NOT NULL AND f.longitude IS NOT NULL
                 AND s.status='confirmed'
               ORDER BY f.observed_at DESC, s.id DESC
               LIMIT 300"""
        ).fetchall()
    return [
        dict(
            dict(r),
            photo_url=f"/media/crop/{r['id']}.jpg",
            thumbnail_url=f"/media/thumb/{r['id']}.jpg",
        )
        for r in rows
    ]
