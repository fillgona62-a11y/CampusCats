"""Community identity polls, naming rights and account badges."""
import json
import math
import os
import time
from pathlib import Path

from catalog import audit, field, one
from media import Problem
from vision import DEFAULT_MAX_DISTANCE, MODEL_VERSION, rank_candidates

POLL_SECONDS = 48 * 60 * 60
NEW = "new"
UNCLEAR = "unclear"


def calibration():
    path = os.getenv("CAMPUSCATS_IDENTITY_CALIBRATION")
    if not path:
        return None
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
        mid, slope, temp = (float(cfg[k]) for k in ("new_midpoint", "new_slope", "identity_temperature"))
        if cfg["model"] == MODEL_VERSION and 0 < mid <= 1 and 0 < slope <= 200 and .001 <= temp <= 1:
            return mid, slope, temp
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def distribution(ranked, config):
    if not ranked:
        # The gallery cannot distinguish a new cat from an absent or unusable reference.
        return {UNCLEAR: 1.0}
    if config:
        midpoint, slope, temp = config
    else:
        midpoint, slope, temp = DEFAULT_MAX_DISTANCE, 18.0, .045
    best = ranked[0]["distance"]
    novelty = 1 / (1 + math.exp(-slope * (best - midpoint)))
    weights = [math.exp(-(item["distance"] - best) / temp) for item in ranked]
    total = sum(weights)
    values = {str(item["cat_id"]): (1 - novelty) * weight / total for item, weight in zip(ranked, weights)}
    values[NEW] = novelty
    return values


def allows_match(analysis, refs, cat_id, config):
    if not config:
        return True
    scores = distribution(rank_candidates(analysis, refs, limit=3, max_distance=1.0), config)
    probability = scores.get(str(cat_id), 0)
    runner_up = max((p for key, p in scores.items() if key != str(cat_id)), default=0)
    return probability >= .70 and probability - runner_up >= .20


def publish(db, sid, uid, analysis, refs, config, allow_auto, suggestion):
    ranked = rank_candidates(analysis, refs, limit=3, max_distance=1.0)
    probabilities = distribution(ranked, config)
    ordered = sorted(probabilities, key=probabilities.get, reverse=True)
    score = probabilities.get(NEW, 0)
    gap = score - probabilities[ordered[1]] if ordered[0] == NEW and len(ordered) > 1 else 0
    other_crops = db.execute("""
        SELECT s.id,s.analysis FROM sightings s
        WHERE s.status='pending' AND s.frame_id!=(SELECT frame_id FROM sightings WHERE id=?)
        ORDER BY s.id DESC LIMIT 250
    """, (sid,)) if (config and allow_auto and suggestion is None and score >= .80 and gap >= .25
                     and analysis.get("frontal_face") and len({cid for cid, _ in refs}) >= 3) else None
    if other_crops is not None and not rank_candidates(analysis, ((r["id"], json.loads(r["analysis"])) for r in other_crops), limit=1):
        create_cat(db, sid, uid, "private_name", probabilities, config is not None)
        return
    options = [str(item["cat_id"]) for item in ranked]
    if suggestion is not None and str(suggestion) not in options:
        options.append(str(suggestion))
    db.execute("""INSERT INTO community_topics(sighting_id,state,closes,options,distribution,calibrated)
                  VALUES(?,'poll',?,?,?,?)""",
               (sid, int(time.time()) + POLL_SECONDS, json.dumps(options), json.dumps(probabilities), int(config is not None)))


def create_cat(db, sid, actor, state, estimates=None, calibrated=False):
    shot = one(db, "SELECT analysis FROM sightings WHERE id=?", sid)
    coat = json.loads(shot["analysis"]).get("coat_hint", "")[:80]
    cat = db.execute("INSERT INTO cats(name,coat) VALUES(?,?)", (f"待命名猫 #{sid}", coat)).lastrowid
    db.execute("UPDATE sightings SET status='confirmed',cat_id=? WHERE id=?", (cat, sid))
    if state == "private_name":
        db.execute("""INSERT INTO community_topics(sighting_id,state,cat_id,options,distribution,calibrated,result)
                      VALUES(?,?,?,'[]',?,?,'new')""", (sid, state, cat, json.dumps(estimates), int(calibrated)))
    else:
        db.execute("UPDATE community_topics SET state=?,cat_id=?,result='new' WHERE sighting_id=?", (state, cat, sid))
    audit(db, actor, "identity", sid, ["pending", None], ["confirmed", cat],
          "系统高置信判定为新猫" if state == "private_name" else "社区投票判定为新猫")


def close_due(db):
    now = int(time.time())
    if not db.execute("SELECT 1 FROM community_topics WHERE state='poll' AND closes<=? LIMIT 1", (now,)).fetchone():
        return
    db.execute("BEGIN IMMEDIATE")
    due = db.execute("""
        SELECT t.sighting_id,f.user_id,s.frame_id FROM community_topics t
        JOIN sightings s ON s.id=t.sighting_id JOIN frames f ON f.id=s.frame_id
        WHERE t.state='poll' AND t.closes<=? ORDER BY t.closes,t.sighting_id
    """, (now,)).fetchall()
    for topic in due:
        sid = topic["sighting_id"]
        votes = db.execute("""
            SELECT choice,COUNT(*) AS total,MIN(id) AS first_vote FROM community_votes
            WHERE sighting_id=? GROUP BY choice ORDER BY total DESC,first_vote
        """, (sid,)).fetchall()
        # In a tie, favor the option that received its first vote earlier.
        choice = votes[0]["choice"] if votes else UNCLEAR
        if choice == NEW:
            create_cat(db, sid, topic["user_id"], "public_name")
            continue
        cat = None
        if choice != UNCLEAR:
            candidate = int(choice)
            if db.execute("""SELECT 1 FROM sightings WHERE cat_id=? AND status='confirmed' LIMIT 1""", (candidate,)).fetchone() and not db.execute(
                    "SELECT 1 FROM sightings WHERE frame_id=? AND cat_id=?", (topic["frame_id"], candidate)).fetchone():
                cat = candidate
                db.execute("UPDATE sightings SET status='confirmed',cat_id=?,suggested_cat_id=? WHERE id=?", (cat, cat, sid))
                audit(db, topic["user_id"], "identity", sid, ["pending", None], ["confirmed", cat], "社区投票确认已有档案")
        outcome = str(cat) if cat else (UNCLEAR if votes else "no_votes")
        db.execute("UPDATE community_topics SET state='closed',cat_id=?,result=? WHERE sighting_id=?", (cat, outcome, sid))
    db.commit()


def cast(db, sid, uid, choice):
    close_due(db)
    db.execute("BEGIN IMMEDIATE")
    topic = one(db, "SELECT * FROM community_topics WHERE sighting_id=?", sid)
    if topic["state"] != "poll" or int(time.time()) >= topic["closes"]:
        raise Problem("投票已截止。", 409)
    if choice not in (NEW, UNCLEAR) and (choice not in json.loads(topic["options"]) or not db.execute(
            "SELECT 1 FROM sightings WHERE cat_id=? AND status='confirmed'", (choice,)).fetchone()):
        raise Problem("投票选项无效。")
    if db.execute("SELECT 1 FROM community_votes WHERE sighting_id=? AND user_id=?", (sid, uid)).fetchone():
        raise Problem("这个账号已经为本条目击投过票。", 409)
    db.execute("INSERT INTO community_votes(sighting_id,user_id,choice) VALUES(?,?,?)", (sid, uid, choice))
    return {"ok": True}


def claim(db, sid, uid, body):
    name = field(body, "name", 40, required=True)
    if any(not c.isprintable() for c in name):
        raise Problem("猫名含不可见字符。")
    close_due(db)
    db.execute("BEGIN IMMEDIATE")
    topic = one(db, """
        SELECT t.*,f.user_id FROM community_topics t JOIN sightings s ON s.id=t.sighting_id
        JOIN frames f ON f.id=s.frame_id WHERE t.sighting_id=? AND s.cat_id=t.cat_id
    """, sid)
    if topic["state"] not in ("private_name", "public_name"):
        raise Problem("命名已经结束。", 409)
    if topic["state"] == "private_name" and topic["user_id"] != uid:
        raise Problem("命名权属于首位提交该目击的账号。", 403)
    db.execute("UPDATE cats SET name=? WHERE id=?", (name, topic["cat_id"]))
    db.execute("UPDATE community_topics SET state='named',named_by=? WHERE sighting_id=?", (uid, sid))
    audit(db, uid, "cat_name", topic["cat_id"], None, name, "校园猫命名")
    return {"cat_id":topic["cat_id"], "name":name}


def badges(db, uid):
    found, named = db.execute("""
        SELECT coalesce(sum(f.user_id=? AND t.result='new'),0),coalesce(sum(t.named_by=?),0)
        FROM community_topics t JOIN sightings s ON s.id=t.sighting_id
        JOIN frames f ON f.id=s.frame_id WHERE s.status='confirmed' AND s.cat_id=t.cat_id
    """, (uid, uid)).fetchone()
    votes = db.execute("""
        SELECT count(*) FROM community_votes v JOIN community_topics t ON t.sighting_id=v.sighting_id
        WHERE v.user_id=? AND t.result IS NOT NULL AND v.choice=t.result AND v.choice!='unclear'
    """, (uid,)).fetchone()[0]
    return [{"title":title,"description":text,"count":count,"icon":icon}
            for title,text,count,icon in (
                ("校园寻猫员","首发并确认了校园新猫",found,"pin"),
                ("猫名题签","为新猫定下图鉴名字",named,"book"),
                ("花纹见证人","参与了形成身份结论的辨认投票",votes,"focus"),
            ) if count]


def board(db, uid, offset=0):
    topics = db.execute("""
        SELECT t.*, f.user_id, f.area, c.name,
            (SELECT choice FROM community_votes WHERE sighting_id=t.sighting_id AND user_id=?) AS voted
        FROM community_topics t JOIN sightings s ON s.id=t.sighting_id JOIN frames f ON f.id=s.frame_id
        LEFT JOIN cats c ON c.id=t.cat_id
        WHERE t.state!='private_name' OR f.user_id=?
        ORDER BY CASE WHEN t.state='private_name' THEN 0 WHEN t.state='public_name' THEN 1
                      WHEN t.state='poll' THEN 2 ELSE 3 END, t.sighting_id DESC LIMIT 21 OFFSET ?
    """, (uid, uid, offset)).fetchall()
    output = []
    for row in topics[:20]:
        sid = row["sighting_id"]
        options = []
        counts = dict(db.execute("SELECT choice,count(*) FROM community_votes WHERE sighting_id=? GROUP BY choice", (sid,)))
        scores = json.loads(row["distribution"])
        keys = json.loads(row["options"]) + [NEW, UNCLEAR] if row["closes"] is not None else list(scores)
        for choice in keys:
            cat = db.execute("""
                SELECT c.name, max(s.id) AS photo_id FROM cats c JOIN sightings s ON s.cat_id=c.id
                WHERE c.id=? AND s.status='confirmed' GROUP BY c.id
            """, (int(choice),)).fetchone() if choice.isdecimal() else None
            label = cat["name"] if cat else {NEW:"确认是新猫", UNCLEAR:"照片证据不足"}.get(choice, "档案已变更")
            options.append({"key":choice, "label":label, "votes":None if row["state"] == "poll" else counts.get(choice,0),
                            "photo_id":cat["photo_id"] if cat else None, "available":bool(cat) or not choice.isdecimal()})
        output.append({"id":sid,"state":row["state"],"area":row["area"],"cat_id":row["cat_id"],
                       "name":row["name"],"closes":row["closes"],"result":row["result"],
                       "voted":row["voted"],"options":options,"distribution":scores,"calibrated":bool(row["calibrated"])})
    return {"topics":output, "more":len(topics)>20}


def inbox(db, uid):
    return db.execute("""
        SELECT count(*) FROM community_topics t JOIN sightings s ON s.id=t.sighting_id JOIN frames f ON f.id=s.frame_id
        WHERE (s.cat_id=t.cat_id AND (t.state='public_name' OR (t.state='private_name' AND f.user_id=?)))
        OR (s.status='pending' AND t.state='poll' AND NOT EXISTS
            (SELECT 1 FROM community_votes v WHERE v.sighting_id=t.sighting_id AND v.user_id=?))
    """, (uid, uid)).fetchone()[0]
