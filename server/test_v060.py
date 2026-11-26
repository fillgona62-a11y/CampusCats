"""Tests for v0.6.0-SYLU upgrades:
- 80-class anti-human / anti-dog YOLOv8 gate & Gaussian Soft-NMS multi-cat retention
- Non-cat rejection across /api/identify, /api/sightings, and /api/agent/chat
- Multi-cat auto-detection & Chinese unspaced entity search in 猫猫助手
- Spatial patch + CLS hybrid ONNX Re-ID & weak_candidate anti-false-match status
- Local CLIP zero-shot species gate + breed/coat classifier
"""

import base64
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import app as app_mod
import catalog
import clip_classifier
import detector
import encoder
import vision


def _rich_photo_b64(bg=(210, 138, 66), stripe=(72, 42, 18), size=(300, 240)):
    im = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(im)
    for x in range(16, size[0] - 16, 18):
        draw.ellipse((x, 24, x + 14, size[1] - 24), fill=(244, 198, 128), outline=stripe, width=3)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class V060UpgradeTests(unittest.TestCase):
    def _call(self, application, path, body=None, cookie=""):
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        env = {
            "REQUEST_METHOD": "POST" if body is not None else "GET",
            "PATH_INFO": path,
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(raw)),
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_HOST": "localhost",
            "wsgi.input": io.BytesIO(raw),
        }
        if cookie:
            env["HTTP_COOKIE"] = cookie
        st, hdrs = [], []
        resp = b"".join(application(env, lambda s, h: (st.append(int(s.split()[0])), hdrs.append(dict(h)))))
        return st[0], json.loads(resp.decode("utf-8")), hdrs[0]

    def test_detector_80_class_rejects_person_and_dog_anchors(self):
        # Anchor 0: person=0.82, cat=0.36 (human misread as low-conf cat) -> MUST BE REJECTED
        # Anchor 1: dog=0.74, cat=0.29 (live bug repro!) -> MUST BE REJECTED
        # Anchor 2: cat=0.78, person=0.04, dog=0.05 -> MUST BE KEPT
        out = np.zeros((3, 84), dtype=np.float32)
        out[0, :4] = [320, 320, 260, 420]
        out[0, 4 + 0] = 0.82
        out[0, 4 + 15] = 0.36

        out[1, :4] = [200, 300, 220, 260]
        out[1, 4 + 16] = 0.74
        out[1, 4 + 15] = 0.29

        out[2, :4] = [420, 340, 180, 200]
        out[2, 4 + 15] = 0.78
        out[2, 4 + 0] = 0.04
        out[2, 4 + 16] = 0.05

        boxes, scores = detector._extract_cat_anchors(out, 640, 640, 1.0, 0, 0, 0.28, np)
        self.assertEqual(boxes.shape[0], 1)
        self.assertAlmostEqual(float(scores[0]), 0.78, places=3)

    def test_soft_nms_retains_two_huddled_kittens(self):
        # Two adjacent/overlapping kittens with IoU ~ 0.50 (centers clearly distinct)
        boxes = np.asarray([
            [0.10, 0.20, 0.55, 0.80],
            [0.30, 0.22, 0.75, 0.82],
        ], dtype=np.float32)
        scores = np.asarray([0.84, 0.79], dtype=np.float32)
        picked = detector._soft_nms(boxes, scores, conf_thresh=0.28, iou_hard=0.72, np=np)
        self.assertEqual(len(picked), 2)

    def test_non_cat_blocked_in_identify_upload_and_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            application = app_mod.App(Path(tmp) / "data", Path(tmp) / "media")
            code, _, hdrs = self._call(application, "/api/register", {
                "email": "guard@sylu.edu", "password": "Password123!", "nickname": "Guard"
            })
            self.assertEqual(code, 200)
            cookie = hdrs["Set-Cookie"].split(";")[0]

            human_gate = {
                "checked": True,
                "is_cat": False,
                "non_cat_type": "person",
                "reason": "画面识别为人像且未检测到猫咪，已拦截误识别。",
            }
            with mock.patch.object(detector, "is_enabled", return_value=True), \
                 mock.patch.object(detector, "verify_box_is_cat", return_value=human_gate):
                # 1) /api/identify returns not_a_cat with empty candidates & None ai_profile
                c_id, res_id, _ = self._call(application, "/api/identify", {
                    "photo": _rich_photo_b64(), "boxes": [[0, 0, 1, 1]]
                })
                self.assertEqual(c_id, 200)
                r0 = res_id["results"][0]
                self.assertTrue(r0["not_cat"])
                self.assertEqual(r0["record_status"]["status"], "not_a_cat")
                self.assertIsNone(r0["ai_profile"])
                self.assertEqual(r0["candidates"], [])

                # 2) /api/sightings rejects human upload with HTTP 422
                c_up, res_up, _ = self._call(application, "/api/sightings", {
                    "photo": _rich_photo_b64(),
                    "boxes": [[0, 0, 1, 1]],
                    "area": "图书馆（琴园环路）",
                    "note": "误传人像",
                    "request_id": "human-block-1",
                }, cookie=cookie)
                self.assertEqual(c_up, 422)
                self.assertIn("人像", res_up["error"])

                # 3) /api/agent/chat refuses to call a human a cat
                with mock.patch.object(detector, "detect_cats", return_value=[]):
                    c_ag, res_ag, _ = self._call(application, "/api/agent/chat", {
                        "message": "看看这是什么猫",
                        "photo": _rich_photo_b64(),
                    })
                self.assertEqual(c_ag, 200)
                self.assertIn("非猫咪画面提示", res_ag["reply"])
                self.assertNotIn("猫 1", res_ag["reply"])

    def test_agent_multi_cat_photo_and_unspaced_chinese_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            application = app_mod.App(Path(tmp) / "data", Path(tmp) / "media")
            _, _, m_hdr = self._call(application, "/api/register", {
                "email": "m@sylu.edu", "password": "Password123!", "nickname": "Member"
            })
            _, _, r_hdr = self._call(application, "/api/register", {
                "email": "r@sylu.edu", "password": "Password123!", "nickname": "Reviewer"
            })
            m_cookie = m_hdr["Set-Cookie"].split(";")[0]
            r_cookie = r_hdr["Set-Cookie"].split(";")[0]
            with closing(catalog.connect(application.db_path)) as db, db:
                db.execute("UPDATE users SET role='reviewer' WHERE email='r@sylu.edu'")

            _, up, _ = self._call(application, "/api/sightings", {
                "photo": _rich_photo_b64(),
                "boxes": [[0, 0, 1, 1]],
                "area": "兵器博物馆 / 兵器广场",
                "note": "",
                "request_id": "seed-armory-1",
            }, cookie=m_cookie)
            sid = up["sightings"][0]["id"]
            self._call(application, f"/api/review/{sid}", {
                "action": "new", "name": "炮塔橘", "coat": "橘白", "neutered": "neutered", "reason": "建档"
            }, cookie=r_cookie)

            # Unspaced Chinese natural question matches "兵器广场" and "炮塔橘"
            _, q1, _ = self._call(application, "/api/agent/chat", {"message": "兵器广场附近有哪些猫？"})
            self.assertIn("炮塔橘", q1["reply"])
            self.assertEqual(len(q1["cards"]), 1)

            _, q2, _ = self._call(application, "/api/agent/chat", {"message": "帮我查查炮塔橘最近在哪活动"})
            self.assertIn("炮塔橘", q2["reply"])

            # Multi-cat single image inside 猫猫助手 auto-detects 2 cats
            two_dets = [
                {"box": [0.05, 0.10, 0.40, 0.75], "score": 0.88},
                {"box": [0.52, 0.12, 0.42, 0.76], "score": 0.83},
            ]
            with mock.patch.object(detector, "is_enabled", return_value=True), \
                 mock.patch.object(detector, "detect_cats", return_value=two_dets), \
                 mock.patch.object(detector, "verify_box_is_cat", return_value={"checked": True, "is_cat": True, "non_cat_type": None, "reason": ""}):
                _, m_res, _ = self._call(application, "/api/agent/chat", {
                    "message": "这张图里有几只猫？",
                    "photo": _rich_photo_b64(size=(520, 360)),
                })
            self.assertIn("2 只猫咪", m_res["reply"])
            self.assertEqual(len(m_res["identification"]["results"]), 2)

    def test_spatial_patch_hybrid_embedding_increases_inter_cat_separation(self):
        rng = np.random.default_rng(42)
        shared_cls = rng.normal(size=(384,)).astype(np.float32)
        shared_cls /= np.linalg.norm(shared_cls)

        # Cat A and Cat B share 85% identical CLS ("catness") but have distinct spatial upper/lower markings
        tok_a = np.zeros((1, 257, 384), dtype=np.float32)
        tok_b = np.zeros((1, 257, 384), dtype=np.float32)
        tok_a[0, 0] = shared_cls
        tok_b[0, 0] = 0.85 * shared_cls + 0.15 * rng.normal(size=(384,)).astype(np.float32)
        tok_a[0, 1:129] = rng.normal(loc=1.0, scale=0.4, size=(128, 384)).astype(np.float32)
        tok_a[0, 129:] = rng.normal(loc=-1.0, scale=0.4, size=(128, 384)).astype(np.float32)
        tok_b[0, 1:129] = rng.normal(loc=-1.0, scale=0.4, size=(128, 384)).astype(np.float32)
        tok_b[0, 129:] = rng.normal(loc=1.0, scale=0.4, size=(128, 384)).astype(np.float32)

        cls_a = tok_a[0, 0] / np.linalg.norm(tok_a[0, 0])
        cls_b = tok_b[0, 0] / np.linalg.norm(tok_b[0, 0])
        cls_only_dist = 1.0 - float(cls_a @ cls_b)

        hyb_a = encoder._extract_descriptor(tok_a, np)
        hyb_b = encoder._extract_descriptor(tok_b, np)
        hybrid_dist = 1.0 - float(hyb_a @ hyb_b)
        self.assertEqual(hyb_a.shape[0], 384 * 4)
        self.assertGreater(hybrid_dist, cls_only_dist + 0.25)

        # Borderline candidate triggers weak_candidate warning
        weak = vision.assess_db_match(
            [{"id": 9, "name": "相似橘", "area": "食堂", "distance": 0.27, "local_inliers": 0}],
            reference_count=3,
            max_distance=0.32,
        )
        self.assertEqual(weak["status"], "weak_candidate")

    def test_local_clip_species_and_breed_classifier(self):
        dim = 8
        species_vecs = np.eye(4, dim, dtype=np.float32)  # 0=cat, 1=person, 2=dog, 3=other
        breed_vecs = np.zeros((2, dim), dtype=np.float32)
        breed_vecs[0, 5] = 1.0  # 中华田园猫（狸花猫）
        breed_vecs[1, 4] = 1.0  # 英国短毛猫
        coat_vecs = np.zeros((2, dim), dtype=np.float32)
        coat_vecs[0, 4] = 1.0   # 蓝白 / 灰白
        coat_vecs[1, 6] = 1.0   # 橘猫
        bank = {
            "logit_scale": np.float32(20.0),
            "species_keys": np.asarray(["cat", "person", "dog", "other"]),
            "species_vecs": species_vecs,
            "breed_keys": np.asarray(["中华田园猫（狸花猫）", "英国短毛猫"]),
            "breed_native": np.asarray([True, False]),
            "breed_vecs": breed_vecs,
            "coat_keys": np.asarray(["蓝白 / 灰白", "橘猫"]),
            "coat_vecs": coat_vecs,
        }
        cat_embed = np.asarray([0.72, 0.0, 0.0, 0.0, 0.68, 0.0, 0.0, 0.0], dtype=np.float32)
        cat_embed /= np.linalg.norm(cat_embed)
        im = Image.new("RGB", (120, 120), (120, 130, 140))

        with mock.patch.object(clip_classifier, "_encode_image", return_value=(cat_embed, bank)) as enc_mock:
            once = clip_classifier.analyze_crop_once(im)
            self.assertEqual(enc_mock.call_count, 1)
            self.assertTrue(once["species"]["is_cat"])
            self.assertEqual(once["coat"]["source"], "local_assist")
            self.assertEqual(once["coat"]["breed"], "未知")
            self.assertEqual(once["coat"]["coat"], "蓝白 / 灰白")

            sp = clip_classifier.inspect_species(im)
            self.assertTrue(sp["is_cat"])
            prof = clip_classifier.classify_coat_only(im)
            self.assertEqual(prof["source"], "local_assist")
            self.assertEqual(prof["breed"], "未知")
            self.assertEqual(prof["coat"], "蓝白 / 灰白")

        person_embed = np.asarray([0.05, 0.98, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        person_embed /= np.linalg.norm(person_embed)
        with mock.patch.object(clip_classifier, "_encode_image", return_value=(person_embed, bank)):
            sp_human = clip_classifier.inspect_species(im)
            self.assertFalse(sp_human["is_cat"])
            self.assertEqual(sp_human["dominant"], "person")

    def test_two_stage_funnel_makes_single_vlm_call_on_stitched_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            application = app_mod.App(Path(tmp) / "data", Path(tmp) / "media")
            _, _, m_hdr = self._call(application, "/api/register", {
                "email": "s1@sylu.edu", "password": "Password123!", "nickname": "M"
            })
            _, _, r_hdr = self._call(application, "/api/register", {
                "email": "s2@sylu.edu", "password": "Password123!", "nickname": "R"
            })
            m_cookie = m_hdr["Set-Cookie"].split(";")[0]
            r_cookie = r_hdr["Set-Cookie"].split(";")[0]
            with closing(catalog.connect(application.db_path)) as db, db:
                db.execute("UPDATE users SET role='reviewer' WHERE email='s2@sylu.edu'")

            _, up, _ = self._call(application, "/api/sightings", {
                "photo": _rich_photo_b64(),
                "boxes": [[0, 0, 1, 1]],
                "area": "图书馆（琴园环路）",
                "note": "",
                "request_id": "stage1-seed",
            }, cookie=m_cookie)
            sid = up["sightings"][0]["id"]
            self._call(application, f"/api/review/{sid}", {
                "action": "new", "name": "琴园大橘", "coat": "橘猫", "reason": "建档"
            }, cookie=r_cookie)

            # Configure school GPT provider (gpt-6.1-terra / gpt-6.2-sol)
            self._call(application, "/api/agent/settings", {
                "scope": "shared",
                "action": "save",
                "base_url": "https://school-gateway.example/v1",
                "chat_model": "gpt-6.1-terra",
                "vision_model": "gpt-6.2-sol",
                "protocol": "tools",
                "api_key": "sk-school-quota",
            }, cookie=r_cookie)

            calls = []

            def fake_completion(cfg, payload):
                calls.append((cfg, payload))
                return {
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "is_cat": True,
                                "verdict": "same_cat",
                                "best_candidate_index": 1,
                                "confidence": 0.93,
                                "matching_features": ["额头M纹一致", "左耳平剪耳一致"],
                                "differences": [],
                                "reason": "额头纹与左耳剪耳完全吻合，确认为琴园大橘。",
                                "breed": "中华田园猫",
                                "breed_confidence": "high",
                                "coat": "橘白短毛",
                                "features": ["左耳平剪耳", "胸口白围脖"],
                                "neutered_hint": "yes",
                                "summary": "左耳剪耳的橘白中华田园猫。",
                            }, ensure_ascii=False)
                        }
                    }]
                }

            with mock.patch("providers.completion", side_effect=fake_completion):
                code, res, _ = self._call(application, "/api/identify", {
                    "photo": _rich_photo_b64(),
                    "boxes": [[0, 0, 1, 1]],
                    "area": "图书馆（琴园环路）",
                    "cloud_photo": True,
                })
            self.assertEqual(code, 200)
            # Crucial assertion: ONLY 1 cloud VLM call was made (stitched sheet), NOT 2!
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0]["vision_model"], "gpt-6.2-sol")
            self.assertNotIn("max_tokens", calls[0][1])
            self.assertNotIn("temperature", calls[0][1])
            item = res["results"][0]
            self.assertEqual(item["vlm_compare"]["verdict"], "same_cat")
            self.assertEqual(item["ai_profile"]["source"], "vlm")
            self.assertEqual(item["ai_profile"]["breed"], "中华田园猫")
            self.assertEqual(item["ai_profile"]["neutered_hint"], "yes")

            # Also verify environment-variable direct path omits temperature & max_tokens for GPT-6 reasoning models
            self._call(application, "/api/agent/settings", {"scope": "shared", "action": "remove"}, cookie=r_cookie)
            env_payloads = []

            class _EnvResp:
                def read(self_inner):
                    return json.dumps({"choices": [{"message": {"content": '{"breed":"中华田园猫","coat":"橘白"}'}}]}).encode()
                def __enter__(self_inner): return self_inner
                def __exit__(self_inner, *a): return False

            def fake_urlopen(req, timeout=None):
                env_payloads.append(json.loads(req.data.decode("utf-8")))
                return _EnvResp()

            with mock.patch.dict(os.environ, {
                "CAMPUSCATS_LLM_API_KEY": "sk-env",
                "CAMPUSCATS_LLM_MODEL": "gpt-6.1-terra",
                "CAMPUSCATS_VISION_MODEL": "gpt-6.2-sol",
            }), mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                self._call(application, "/api/agent/chat", {"message": "你好"})
                import ai_vision
                ai_vision.classify_cat_crop(Image.new("RGB", (120, 120), (200, 120, 60)), allow_remote=True)
            self.assertGreaterEqual(len(env_payloads), 2)
            for p in env_payloads:
                self.assertNotIn("temperature", p)
                self.assertNotIn("max_tokens", p)

    def test_builtin_admin_account_login_and_permissions(self):
        # Without explicit env vars, NO default admin account or password exists in source/DB
        with tempfile.TemporaryDirectory() as tmp:
            application = app_mod.App(Path(tmp) / "data", Path(tmp) / "media")
            with closing(catalog.connect(application.db_path)) as db:
                cnt = db.execute("SELECT COUNT(*) FROM users WHERE role='reviewer'").fetchone()[0]
                self.assertEqual(cnt, 0)
            code, _, _ = self._call(application, "/api/login", {
                "email": "admin@sylu.edu.cn",
                "password": "AnyUnconfiguredPassword!2026",
            })
            self.assertEqual(code, 401)

            # /api/app/version reflects v0.6.3 (version_code=10)
            v_code, v_res, _ = self._call(application, "/api/app/version")
            self.assertEqual(v_code, 200)
            self.assertEqual(v_res["version_code"], 10)
            self.assertEqual(v_res["version_name"], "0.6.3")

        # When CAMPUS_ADMIN_EMAIL & CAMPUS_ADMIN_PASSWORD are provided via env, reviewer account is provisioned
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "CAMPUS_ADMIN_EMAIL": "envadmin@sylu.edu.cn",
            "CAMPUS_ADMIN_PASSWORD": "StrongEnvPass!2026",
            "CAMPUS_ADMIN_NICKNAME": "环境管理员",
        }):
            application = app_mod.App(Path(tmp) / "data", Path(tmp) / "media")
            code, res, hdrs = self._call(application, "/api/login", {
                "email": "envadmin@sylu.edu.cn",
                "password": "StrongEnvPass!2026",
            })
            self.assertEqual(code, 200)
            self.assertEqual(res["user"]["role"], "reviewer")
            cookie = hdrs["Set-Cookie"].split(";")[0]

            c_rev, _, _ = self._call(application, "/api/review", cookie=cookie)
            self.assertEqual(c_rev, 200)
            c_ag, ag_set, _ = self._call(application, "/api/agent/settings", cookie=cookie)
            self.assertEqual(c_ag, 200)
            self.assertIn("shared", ag_set)

    def test_dark_cat_not_falsely_rejected_by_tight_crop_and_single_yolo_pass(self):
        im = Image.new("RGB", (640, 480), (45, 45, 48))
        raw_out = np.zeros((2, 84), dtype=np.float32)
        raw_out[0, :4] = [160, 240, 240, 320]
        raw_out[0, 4 + 15] = 0.72
        raw_out[1, :4] = [480, 240, 240, 320]
        raw_out[1, 4 + 15] = 0.75

        with mock.patch.object(detector, "is_enabled", return_value=True), \
             mock.patch.object(clip_classifier, "is_enabled", return_value=False), \
             mock.patch.object(detector, "_engine", return_value=("sess", "in", "out")), \
             mock.patch.object(detector, "_infer_raw_640", return_value=(raw_out, 1.0, 0, 80)) as infer_mock:
            info = detector.inspect_image_subjects(im)
            self.assertEqual(len(info["cats"]), 2)
            # Single full-frame scan: _infer_raw_640 called ONLY ONCE
            self.assertEqual(infer_mock.call_count, 1)

            # Tight crop check reusing frame_info does NOT re-run YOLO and never rejects overlapping detected cats
            gate = detector.verify_box_is_cat(im, info["cats"][0]["box"], frame_info=info)
            self.assertTrue(gate["is_cat"])
            self.assertEqual(infer_mock.call_count, 1)

    def test_cloud_vlm_decisive_threshold_and_beijing_time_and_coat_hint(self):
        # Verify Cloud VLM >= 0.55 takes decisive priority in assess_db_match
        cand = [{"id": 1, "name": "墨团", "coat": "纯黑", "area": "图书馆（琴园环路）", "similarity": 0.71, "distance": 0.24}]
        rs_same = vision.assess_db_match(cand, 1, area="", usable=True, vlm_compare={
            "source": "vlm", "verdict": "same_cat", "best_candidate_index": 1, "confidence": 0.58, "reason": "五官轮廓一致"
        })
        self.assertEqual(rs_same["status"], "possible_match")
        rs_diff = vision.assess_db_match(cand, 1, area="", usable=True, vlm_compare={
            "source": "vlm", "verdict": "different_cat", "best_candidate_index": None, "confidence": 0.58, "reason": "白斑不同"
        })
        self.assertEqual(rs_diff["status"], "no_candidate")
        self.assertIsNone(rs_diff["top_cat_id"])

        with tempfile.TemporaryDirectory() as tmp:
            application = app_mod.App(Path(tmp) / "data", Path(tmp) / "media")
            _, _, m_hdr = self._call(application, "/api/register", {
                "email": "bj1@sylu.edu", "password": "Password123!", "nickname": "M"
            })
            _, _, r_hdr = self._call(application, "/api/register", {
                "email": "bj2@sylu.edu", "password": "Password123!", "nickname": "R"
            })
            m_cookie = m_hdr["Set-Cookie"].split(";")[0]
            r_cookie = r_hdr["Set-Cookie"].split(";")[0]
            with closing(catalog.connect(application.db_path)) as db, db:
                db.execute("UPDATE users SET role='reviewer' WHERE email='bj2@sylu.edu'")

            _, up, _ = self._call(application, "/api/sightings", {
                "photo": _rich_photo_b64(),
                "boxes": [[0, 0, 1, 1]],
                "area": "图书馆（琴园环路）",
                "note": "UTC测试",
                "request_id": "bj-time-1",
                "observed_at": "2026-11-23T12:43:00Z",
            }, cookie=m_cookie)
            sid = up["sightings"][0]["id"]

            # Pending review exposes auto coat_hint
            _, rev, _ = self._call(application, "/api/review", cookie=r_cookie)
            self.assertTrue(rev["sightings"][0].get("coat_hint"))

            self._call(application, f"/api/review/{sid}", {
                "action": "new", "name": "墨团子", "coat": "纯黑", "reason": "建档"
            }, cookie=r_cookie)

            import agent
            with closing(catalog.connect(application.db_path)) as db:
                ctx = {"cards": {}}
                detail = agent._execute_tool(db, "get_cat_detail", {"cat_id": 1}, ctx)
                self.assertEqual(detail["cat"]["last_seen"], "2026-11-23 20:43（北京时间）")
                self.assertEqual(detail["recent_sightings"][0]["observed_at"], "2026-11-23 20:43（北京时间）")
                self.assertNotIn("UTC", detail["cat"]["last_seen"])


if __name__ == "__main__":
    unittest.main()
