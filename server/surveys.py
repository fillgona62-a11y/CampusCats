"""Ten-minute fixed-point surveys for the pilot campus."""
import re
import time
from datetime import datetime, timedelta, timezone

from catalog import field, one
from media import Problem

DURATION = 600
CAMPUS_TZ = timezone(timedelta(hours=8))


def board(db, uid):
    now = int(time.time())
    today = datetime.fromtimestamp(now, CAMPUS_TZ)
    monday = (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = int(monday.timestamp())
    previous = week_start - 7 * 86400
    areas = db.execute("""
        WITH known(area) AS (
            SELECT area FROM spot_checks WHERE state='done'
            UNION SELECT f.area FROM frames f WHERE EXISTS
                (SELECT 1 FROM sightings s WHERE s.frame_id=f.id AND s.status='confirmed')
        ), weeks AS (
            SELECT area, COUNT(CASE WHEN started>=? THEN 1 END) AS visits,
                   COUNT(CASE WHEN started>=? AND peak>0 THEN 1 END) AS seen,
                   MAX(CASE WHEN started>=? THEN peak END) AS peak,
                   COUNT(CASE WHEN started<? THEN 1 END) AS previous_visits,
                   COUNT(CASE WHEN started<? AND peak>0 THEN 1 END) AS previous_seen
            FROM spot_checks WHERE state='done' AND started>=? AND started<=? GROUP BY area
        )
        SELECT k.area, COALESCE(w.visits,0) AS visits, COALESCE(w.seen,0) AS seen, w.peak,
               COALESCE(w.previous_visits,0) AS previous_visits, COALESCE(w.previous_seen,0) AS previous_seen
        FROM known k LEFT JOIN weeks w ON w.area=k.area ORDER BY visits,k.area
    """, (week_start,week_start,week_start,week_start,week_start,previous,now))
    result = {"areas":[dict(row) for row in areas], "week_start":monday.date().isoformat(),
              "now":now, "duration":DURATION, "active":None, "recent":[]}
    if uid is not None:
        active = db.execute("SELECT id,area,started FROM spot_checks WHERE user_id=? AND state='active'", (uid,)).fetchone()
        result["active"] = dict(active) if active else None
        result["recent"] = [dict(r) for r in db.execute(
            "SELECT id,area,started,peak FROM spot_checks WHERE user_id=? AND state='done' "
            "ORDER BY started DESC,id DESC LIMIT 10", (uid,))]
    return result


def start(db, uid, body):
    area = field(body, "area", 60, required=True)
    key = field(body, "request_id", 80, required=True)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key) or any(ord(c)<32 for c in area):
        raise Problem("请检查区域和提交编号。")
    db.execute("BEGIN IMMEDIATE")
    existing = db.execute("SELECT id,area FROM spot_checks WHERE user_id=? AND request_id=?", (uid,key)).fetchone()
    if existing:
        if existing["area"] != area:
            raise Problem("该提交编号已用于另一个区域。",409)
        return {"id":existing["id"]}
    if db.execute("SELECT 1 FROM spot_checks WHERE user_id=? AND state='active'", (uid,)).fetchone():
        raise Problem("已有一次进行中的观察，请刷新页面继续。",409)
    visit = db.execute("INSERT INTO spot_checks(user_id,request_id,area,started,state) VALUES(?,?,?,?,'active')",
                       (uid,key,area,int(time.time())))
    return {"id":visit.lastrowid}


def update(db, uid, sid, action, body):
    db.execute("BEGIN IMMEDIATE")
    visit = one(db,"SELECT state,started,peak FROM spot_checks WHERE user_id=? AND id=?",uid,sid)
    if action == "withdraw":
        db.execute("UPDATE spot_checks SET state='withdrawn',peak=NULL WHERE id=?", (sid,))
        return {"ok":True}
    peak = body.get("peak")
    if type(peak) is not int or not 0 <= peak <= 999:
        raise Problem("请填写同时看见的最多只数，取 0 到 999 之间的整数。")
    if visit["state"] == "done" and visit["peak"] == peak:
        return {"ok":True}
    if visit["state"] != "active":
        raise Problem("这次观察已经结束，请刷新查看记录。",409)
    if time.time() < visit["started"] + DURATION:
        raise Problem("请观察满十分钟再提交。",409)
    db.execute("UPDATE spot_checks SET state='done',peak=? WHERE id=?", (peak,sid))
    return {"ok":True}
