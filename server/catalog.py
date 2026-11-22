"""Persistent pilot catalog. Every write is checked again inside its transaction."""
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from face_match import automatic_match
from media import Problem, canonical_photo, prepare, save_media, validate_boxes
from vision import MODEL_VERSION, analyze_crop, rank_candidates


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


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
        SELECT c.id,c.name,c.coat,c.breed,r.id AS sid,r.area,r.observed_at AS last_seen,r.sightings
        FROM ranked r JOIN cats c ON c.id=r.cat_id WHERE r.priority=1
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
        f.id AS frame_id,f.observed_at,f.area,f.note
 FROM sightings s JOIN frames f ON f.id=s.frame_id LEFT JOIN cats c ON c.id=s.cat_id
 LEFT JOIN auto_identity a ON a.sighting_id=s.id
"""


def references(db):
    rows = db.execute("""
        SELECT id,cat_id,analysis,box,image,day FROM (
            SELECT s.id,s.cat_id,s.analysis,s.box,f.image,date(f.observed_at,'+8 hours') AS day,
                   ROW_NUMBER() OVER(PARTITION BY s.cat_id ORDER BY s.id DESC) AS n
            FROM sightings s JOIN frames f ON f.id=s.frame_id
            LEFT JOIN auto_identity a ON a.sighting_id=s.id
            WHERE s.status='confirmed' AND a.sighting_id IS NULL
            AND json_extract(s.analysis,'$.usable')=1 AND json_extract(s.analysis,'$.version')=?
        ) WHERE n<=12
    """, (MODEL_VERSION,))
    return [(r["cat_id"], dict(json.loads(r["analysis"]), _reference_id=r["id"],
                              frame=r["image"], box=tuple(json.loads(r["box"])), day=r["day"])) for r in rows]


def matched_profiles(analysis, refs, cats):
    candidates = []
    for match in rank_candidates(analysis, refs):
        target = match["reference_id"]
        candidates.append(dict(cats[match["cat_id"]], reference_id=target,
                               photo_url=f"/media/crop/{target}.jpg", thumbnail_url=f"/media/thumb/{target}.jpg"))
    return candidates


def breed_hint(candidates):
    verified = {cat["id"]:cat["breed"] for cat in candidates
                if cat["breed_status"] == "verified" and cat["breed"]}
    labels = set(verified.values())
    if len(verified) < 2 or len(labels) != 1:
        return None
    return {"label":next(iter(labels)), "kind":"library_comparison", "cat_ids":list(verified)}


def identify(db, body):
    boxes = validate_boxes(body.get("boxes"))
    _,image = canonical_photo(body.get("photo"))
    db.execute("BEGIN")
    cats = catalog(db)
    refs = references(db)
    results = []
    for box in boxes:
        analysis = analyze_crop(image, box)
        candidates = matched_profiles(analysis, refs, cats)
        results.append({"box":box,"quality":analysis["warnings"],"warnings":analysis["warnings"],
                        "usable":analysis["usable"], "candidates":candidates, "breed_hint":breed_hint(candidates)})
    return {"results":results, "reference_count":len({r[0] for r in refs})}


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
    area = field(body, "area", 80, required=True)
    note = field(body, "note", 800)
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
        observed_at = observed or iso()
        ref_revision = revision(db) if automatic else None
        refs = references(db) if automatic else []
        reference_days = defaultdict(set)
        for cat_id, ref in refs:
            if ref["day"]:
                reference_days[cat_id].add(ref["day"])
        if not any(len(days) >= 2 for days in reference_days.values()):
            refs = []
        filename, targets, media = prepare(body.get("photo"), boxes, verify=bool(refs))
        matches = []
        for _, _, _, analysis, features in targets:
            ranked = rank_candidates(analysis, refs, limit=7) if features is not None else []
            matches.append(automatic_match(features, ranked, refs, media_dir))
        proposed = Counter(match[0] for match in matches if match)
        db.execute("BEGIN IMMEDIATE")
        frame_id = previous()
        if frame_id is None:
            for cat_id in selected:
                one(db, "SELECT 1 FROM sightings WHERE cat_id=? AND status='confirmed'",cat_id)
            if db.execute("SELECT 1 FROM frames WHERE image=?", (filename,)).fetchone():
                raise Problem("这张相同的照片已提交过，请使用本次目击的新照片。", 409)
            frame_id = db.execute("""
                INSERT INTO frames(user_id,request_id,request_hash,image,area,note,observed_at)
                VALUES(?,?,?,?,?,?,?)""", (uid, key, fingerprint, filename, area, note, observed or iso())).lastrowid
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
            save_media(media_dir, media)
        db.commit()
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
            cat_id = db.execute("INSERT INTO cats(name,coat) VALUES(?,?)", (name, coat)).lastrowid
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
        FROM sightings s JOIN frames f ON s.frame_id=f.id JOIN cats c ON c.id=s.cat_id
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
