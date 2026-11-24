"""Tests for v0.4.0 security, concurrency, media caching, cat archive management, and CV upgrades."""

import base64
import csv
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

import accounts
import agent
import encoder
import vision
from app import App
from catalog import connect


class OptimizationSuite(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.app = App(self.root, None)
        self.member = self.register("member@example.edu")
        self.reviewer = self.register("review@example.edu")
        with closing(connect(self.app.db_path)) as db, db:
            db.execute("UPDATE users SET role='reviewer' WHERE email='review@example.edu'")
        self._seq = 0

    def call(self, path, payload=None, cookie="", expected=200, extra_env=None):
        raw = json.dumps(payload).encode() if payload is not None else b""
        env = {
            "REQUEST_METHOD": "POST" if payload is not None else "GET",
            "PATH_INFO": path,
            "wsgi.input": io.BytesIO(raw),
            "CONTENT_LENGTH": str(len(raw)),
            "CONTENT_TYPE": "application/json",
            "HTTP_COOKIE": cookie,
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_HOST": "localhost",
        }
        if extra_env:
            env.update(extra_env)
        reply = {}

        def start(status, headers):
            reply.update(code=int(status[:3]), headers=dict(headers))

        result = b"".join(self.app(env, start))
        self.assertEqual(reply["code"], expected, (path, result[:500]))
        ct = reply["headers"].get("Content-Type", "")
        body = json.loads(result) if "json" in ct and result else result
        return body, reply["headers"]

    def register(self, email, remote="127.0.0.1"):
        _, headers = self.call(
            "/api/register",
            {"email": email, "password": "testpass-123", "nickname": "测试员"},
            extra_env={"REMOTE_ADDR": remote},
        )
        return headers["Set-Cookie"].split(";")[0]

    def patterned_photo(self, seed=0, bg="#c97a2b", fg="#2b1d0e"):
        image = Image.new("RGB", (320, 220), bg)
        draw = ImageDraw.Draw(image)
        for i in range(8, 300, 16):
            draw.ellipse((i, 18 + (i + seed) % 15, i + 18, 190), fill="#f3be72", outline=fg, width=3)
        buf = io.BytesIO()
        image.save(buf, "PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def submit_sighting(self, photo=None, area="图书馆周边", days_ago=0, boxes=None):
        self._seq += 1
        when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        payload = {
            "request_id": f"opt-req-{self._seq}",
            "photo": photo or self.patterned_photo(self._seq),
            "area": area,
            "note": "日常记录",
            "boxes": boxes or [[0, 0, 1, 1]],
            "observed_at": when,
        }
        return self.call("/api/sightings", payload, self.member)[0]["sightings"]

    def test_legacy_v031_schema_migrates_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy_dir = Path(tmp)
            db_file = legacy_dir / "campus.sqlite3"
            with closing(sqlite3.connect(db_file)) as db, db:
                db.executescript("""
                    CREATE TABLE cats (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        coat TEXT NOT NULL DEFAULT '',
                        breed TEXT NOT NULL DEFAULT '',
                        evidence TEXT NOT NULL DEFAULT ''
                    );
                    INSERT INTO cats(id, name, coat, breed, evidence) VALUES(1, '元老橘', '橘白', '', '');
                """)
            upgraded = App(legacy_dir, None)
            with closing(connect(upgraded.db_path)) as db:
                row = dict(db.execute("SELECT * FROM cats WHERE id=1").fetchone())
            self.assertEqual(row["name"], "元老橘")
            self.assertEqual(row["sex"], "unknown")
            self.assertEqual(row["neutered"], "unknown")
            self.assertEqual(row["care_status"], "school")
            self.assertEqual(row["temperament"], "")
            self.assertIsNone(row["cover_sighting_id"])

    def test_trusted_proxy_subnets_and_auth_ip_throttling(self):
        accounts._trusted_networks.cache_clear()
        with mock.patch.dict(os.environ, {"CAMPUS_TRUSTED_PROXIES": "10.20.0.0/16", "CAMPUS_TRUST_LOCAL_PROXY": "0"}):
            accounts._trusted_networks.cache_clear()
            ip_trusted = accounts.client_ip({
                "REMOTE_ADDR": "10.20.0.4",
                "HTTP_X_REAL_IP": "203.0.113.45",
            })
            self.assertEqual(ip_trusted, "203.0.113.45")
            ip_xff = accounts.client_ip({
                "REMOTE_ADDR": "10.20.0.9",
                "HTTP_X_FORWARDED_FOR": "198.51.100.77, 10.20.0.9",
            })
            self.assertEqual(ip_xff, "198.51.100.77")
            ip_untrusted = accounts.client_ip({
                "REMOTE_ADDR": "198.51.100.9",
                "HTTP_X_REAL_IP": "1.2.3.4",
            })
            self.assertEqual(ip_untrusted, "198.51.100.9")
        accounts._trusted_networks.cache_clear()

        # Verify per-IP registration rate limit blocks automated account flooding across distinct emails.
        flood_ip = "203.0.113.99"
        for idx in range(30):
            self.register(f"flood-{idx}@example.edu", remote=flood_ip)
        self.call(
            "/api/register",
            {"email": "flood-overflow@example.edu", "password": "testpass-123", "nickname": "刷号"},
            expected=429,
            extra_env={"REMOTE_ADDR": flood_ip},
        )

    def test_media_cache_headers_and_etag_304(self):
        s = self.submit_sighting()[0]
        _, pending_headers = self.call(s["photo_url"], cookie=self.member)
        self.assertEqual(pending_headers["Cache-Control"], "private, no-store")
        self.assertNotIn("ETag", pending_headers)

        self.call(
            f"/api/review/{s['id']}",
            {"action": "new", "name": "缓存测试猫", "reason": "确认身份"},
            self.reviewer,
        )
        body, pub_headers = self.call(s["photo_url"])
        self.assertGreater(len(body), 100)
        self.assertIn("public, max-age=3600", pub_headers["Cache-Control"])
        etag = pub_headers["ETag"]
        self.assertTrue(etag.startswith('"') and etag.endswith('.jpg"'))

        not_modified, nm_headers = self.call(
            s["photo_url"],
            expected=304,
            extra_env={"HTTP_IF_NONE_MATCH": etag},
        )
        self.assertEqual(not_modified, b"")
        self.assertEqual(nm_headers["ETag"], etag)

    def test_cat_profile_cover_pin_and_trigger_reset(self):
        s1 = self.submit_sighting(self.patterned_photo(1), days_ago=2)[0]
        cid = self.call(
            f"/api/review/{s1['id']}",
            {
                "action": "new",
                "name": "麻团",
                "coat": "狸花短毛",
                "sex": "female",
                "neutered": "neutered",
                "temperament": "亲人可摸",
                "reason": "建档核实",
            },
            self.reviewer,
        )[0]["cat_id"]

        s2 = self.submit_sighting(self.patterned_photo(2), days_ago=0)[0]
        self.call(f"/api/review/{s2['id']}", {"action": "match", "cat_id": cid, "reason": "复核花纹"}, self.reviewer)
        cat_default = self.call(f"/api/cats/{cid}")[0]["cat"]
        self.assertEqual(cat_default["photo_url"], s2["photo_url"])
        self.assertEqual(cat_default["sex"], "female")
        self.assertEqual(cat_default["neutered"], "neutered")
        self.assertEqual(cat_default["temperament"], "亲人可摸")

        # Agent search matches metadata keywords ("已绝育", "母猫", "亲人")
        found = self.call("/api/agent/chat", {"message": "已绝育"})[0]
        self.assertEqual(found["cards"][0]["id"], cid)

        # Pin s1 as the featured cover portrait
        self.call(
            f"/api/cats/{cid}/profile",
            {"cover_sighting_id": s1["id"], "care_status": "attention", "reason": "选定清晰正脸照"},
            self.reviewer,
        )
        cat_pinned = self.call(f"/api/cats/{cid}")[0]["cat"]
        self.assertEqual(cat_pinned["photo_url"], s1["photo_url"])
        self.assertEqual(cat_pinned["cover_sighting_id"], s1["id"])
        self.assertEqual(cat_pinned["care_status"], "attention")

        # Reopening s1 automatically clears cover_sighting_id and falls back to s2
        self.call(f"/api/review/{s1['id']}", {"action": "reopen", "reason": "重新核查照片"}, self.reviewer)
        cat_after = self.call(f"/api/cats/{cid}")[0]["cat"]
        self.assertIsNone(cat_after["cover_sighting_id"])
        self.assertEqual(cat_after["photo_url"], s2["photo_url"])

    def test_merge_duplicate_cats_and_same_frame_guard(self):
        # Same-frame two cats cannot be merged together
        same_a, same_b = self.submit_sighting(
            self.patterned_photo(10), boxes=[[0, 0, 0.5, 1], [0.5, 0, 0.5, 1]], days_ago=3
        )
        cid_a = self.call(
            f"/api/review/{same_a['id']}",
            {"action": "new", "name": "北馆橘", "reason": "左耳缺角"},
            self.reviewer,
        )[0]["cat_id"]
        cid_b = self.call(
            f"/api/review/{same_b['id']}",
            {"action": "new", "name": "草坪白", "reason": "通体白毛"},
            self.reviewer,
        )[0]["cat_id"]
        self.call(
            f"/api/cats/{cid_b}/merge",
            {"target_id": cid_a, "reason": "同框冲突测试"},
            self.reviewer,
            expected=409,
        )

        # Separate sightings of the same cat registered twice can be merged cleanly
        dup_s = self.submit_sighting(self.patterned_photo(20), area="东门", days_ago=1)[0]
        cid_dup = self.call(
            f"/api/review/{dup_s['id']}",
            {"action": "new", "name": "东门小橘", "neutered": "neutered", "reason": "新志愿者重复建档"},
            self.reviewer,
        )[0]["cat_id"]
        self.call(f"/api/cats/{cid_dup}/aliases", {"name": "橘团子"}, self.member)
        alias_id = self.call("/api/review", cookie=self.reviewer)[0]["aliases"][0]["id"]
        self.call(f"/api/aliases/{alias_id}/review", {"approve": True}, self.reviewer)

        res, _ = self.call(
            f"/api/cats/{cid_dup}/merge",
            {"target_id": cid_a, "reason": "确认为同一只左耳缺角橘猫"},
            self.reviewer,
        )
        self.assertEqual(res["target_id"], cid_a)
        self.call(f"/api/cats/{cid_dup}", expected=404)
        merged = self.call(f"/api/cats/{cid_a}")[0]["cat"]
        self.assertEqual(merged["sightings"], 2)
        self.assertEqual(merged["neutered"], "neutered")
        self.assertIn("东门小橘", merged["aliases"])
        self.assertIn("橘团子", merged["aliases"])

    def test_canonical_campus_areas_and_whitespace_normalization(self):
        self.call("/api/areas", {"action": "add", "name": "  西区   大草坪 "}, self.reviewer)
        areas = self.call("/api/areas")[0]
        self.assertEqual(areas["canonical"], ["西区 大草坪"])
        board = self.call("/api/surveys")[0]
        self.assertIn("西区 大草坪", [a["area"] for a in board["areas"]])
        self.call("/api/areas", {"action": "remove", "name": "西区 大草坪"}, self.reviewer)
        self.assertEqual(self.call("/api/areas")[0]["canonical"], [])

    def test_llm_semaphore_saturation_falls_back_immediately(self):
        small_sem = agent.threading.BoundedSemaphore(1)
        small_sem.acquire()
        try:
            with mock.patch.object(agent, "_LLM_SLOTS", small_sem), \
                 mock.patch.dict(os.environ, {"CAMPUSCATS_LLM_API_KEY": "sk-busy"}), \
                 mock.patch("agent._call_chat_llm") as llm_mock:
                reply, _ = self.call("/api/agent/chat", {"message": "全校现在统计有几只猫？"})
            llm_mock.assert_not_called()
            self.assertEqual(reply["mode"], "local_fallback")
            self.assertIn("本地查库模式", reply["reply"])
        finally:
            small_sem.release()

    def test_vectorized_ranking_equivalence_and_letterbox_embed(self):
        base_img = Image.open(io.BytesIO(base64.b64decode(self.patterned_photo(0))))
        query = vision.analyze_crop(base_img, [0, 0, 1, 1])
        refs = []
        for idx in range(6):
            im = Image.open(io.BytesIO(base64.b64decode(self.patterned_photo(idx))))
            ann = vision.analyze_crop(im, [0, 0, 1, 1])
            ann["_reference_id"] = idx + 10
            refs.append((idx + 1, ann))
        vec_res = vision.rank_candidates(query, refs, limit=5, max_distance=1.0)
        with mock.patch.object(vision, "np", None):
            py_res = vision.rank_candidates(query, refs, limit=5, max_distance=1.0)
        self.assertEqual(vec_res, py_res)

        # Verify wide side-profile image goes through letterbox embed cleanly
        wide = Image.new("RGB", (440, 140), "#d9822b")
        with mock.patch.object(encoder, "_engine", return_value=lambda arr: np.ones((1, 384), dtype=np.float32)):
            vec = encoder.embed(wide)
        self.assertEqual(len(vec), 384)
        self.assertAlmostEqual(sum(x * x for x in vec), 1.0, places=4)

    def test_evaluate_script_canonical_and_auto_archive_report(self):
        import sys
        eval_dir = Path(__file__).resolve().parents[1] / "evaluate"
        if str(eval_dir) not in sys.path:
            sys.path.insert(0, str(eval_dir))
        import run as eval_run

        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            for idx in range(3):
                im = Image.open(io.BytesIO(base64.b64decode(self.patterned_photo(idx))))
                im.save(tdir / f"p{idx}.png")
            manifest = tdir / "photos.csv"
            with manifest.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["split", "cat_id", "date", "photo", "x", "y", "width", "height"])
                w.writerow(["gallery", "cat1", "2026-10-01", "p0.png", 0, 0, 1, 1])
                w.writerow(["test", "cat1", "2026-10-05", "p1.png", 0, 0, 1, 1])
                w.writerow(["test", "cat_new", "2026-10-06", "p2.png", 0, 0, 1, 1])
            report = eval_run.evaluate(manifest, threshold=0.31)
            self.assertTrue(report["canonical_jpeg"])
            self.assertEqual(report["known_top1"]["total"], 1)
            self.assertIn("auto_archive", report)


    def test_maintenance_prunes_expired_rows_and_stale_orphans(self):
        import time
        from maintenance import inspect_and_prune

        now = int(time.time())
        with closing(connect(self.app.db_path)) as db, db:
            db.execute("INSERT INTO sessions(token,user_id,expires) VALUES('expired-tok',1,?)", (now - 10,))
            db.execute("INSERT INTO throttle(bucket,expires,hits) VALUES('old-bucket',?,3)", (now - 10,))

        stale_orphan = self.app.media / "deadbeef-stale.jpg"
        stale_orphan.write_bytes(b"stale-orphan")
        os.utime(stale_orphan, (now - 7200, now - 7200))

        recent_orphan = self.app.media / "deadbeef-recent.jpg"
        recent_orphan.write_bytes(b"recent-orphan")

        dry = inspect_and_prune(self.app.data, self.app.media, apply=False, grace_seconds=3600, now=now)
        self.assertFalse(dry["applied"])
        self.assertGreaterEqual(dry["expired_sessions"], 1)
        self.assertGreaterEqual(dry["expired_throttle"], 1)
        self.assertEqual(dry["orphan_files"], 1)
        self.assertEqual(dry["skipped_recent_orphans"], 1)
        self.assertTrue(stale_orphan.exists())

        done = inspect_and_prune(self.app.data, self.app.media, apply=True, grace_seconds=3600, now=now)
        self.assertTrue(done["applied"])
        self.assertEqual(done["deleted_files"], 1)
        self.assertFalse(stale_orphan.exists())
        self.assertTrue(recent_orphan.exists())


    def test_sylu_preset_areas_exposed_without_polluting_canonical(self):
        areas = self.call("/api/areas")[0]
        self.assertEqual(areas["canonical"], [])
        self.assertIn("兵器博物馆 / 兵器广场", areas["preset"])
        self.assertIn("图书馆（琴园环路）", areas["areas"])
        self.assertIn("南门（南屏中路）", areas["areas"])


if __name__ == "__main__":
    unittest.main()
