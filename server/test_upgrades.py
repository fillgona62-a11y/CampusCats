"""Unit tests for DB-presence assessment, AI breed/coat recognition, and Agent API."""

import base64
import io
import json
import os
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from app import App
from catalog import connect


class _FakeHTTPResponse:
    def __init__(self, payload):
        self._data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class UpgradeFeatureTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self._seq = 0
        self.app = App(Path(folder.name), None)
        self.member = self.register("member@example.edu")
        self.reviewer = self.register("review@example.edu")
        with closing(connect(self.app.db_path)) as db, db:
            db.execute("UPDATE users SET role='reviewer' WHERE email='review@example.edu'")

    def call(self, path, payload=None, cookie="", expected=200):
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
        reply = {}

        def start(status, headers):
            reply.update(code=int(status[:3]), headers=dict(headers))

        result = b"".join(self.app(env, start))
        self.assertEqual(reply["code"], expected, (path, result[:500]))
        body = json.loads(result) if "json" in reply["headers"]["Content-Type"] else result
        return body, reply["headers"]

    def register(self, email):
        _, headers = self.call(
            "/api/register",
            {"email": email, "password": "testpass-123", "nickname": "测试同学"},
        )
        return headers["Set-Cookie"].split(";")[0]

    def orange_cat_photo(self, nonce=0):
        image = Image.new("RGB", (260, 200), "#d9822b")
        draw = ImageDraw.Draw(image)
        for i in range(0, 260, 14):
            draw.ellipse((i, 15 + (i + nonce) % 10, i + 20, 175), fill="#f2a649", outline="#4a2b13", width=3)
        buf = io.BytesIO()
        image.save(buf, "PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def black_white_photo(self):
        image = Image.new("RGB", (260, 200), "#101010")
        draw = ImageDraw.Draw(image)
        for i in range(0, 260, 26):
            draw.rectangle((i, 0, i + 13, 200), fill="#f5f5f5")
        buf = io.BytesIO()
        image.save(buf, "PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def seed_cat(self, name="大橘", area="图书馆", photo=None):
        self._seq += 1
        photo = photo or self.orange_cat_photo()
        payload = {
            "request_id": f"seed-cat-{self._seq}",
            "photo": photo,
            "area": area,
            "note": "很亲人",
            "boxes": [[0, 0, 1, 1]],
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        s = self.call("/api/sightings", payload, self.member)[0]["sightings"][0]
        cid = self.call(
            f"/api/review/{s['id']}",
            {"action": "new", "name": name, "coat": "橘猫", "reason": "建档测试"},
            self.reviewer,
        )[0]["cat_id"]
        return cid

    def test_record_status_and_local_breed_profile(self):
        orange = self.orange_cat_photo()
        cold, _ = self.call("/api/identify", {"photo": orange, "boxes": [[0, 0, 1, 1]]}, self.member)
        r0 = cold["results"][0]
        self.assertEqual(r0["record_status"]["status"], "no_reference")
        self.assertIsNone(r0["record_status"]["recorded"])
        self.assertEqual(r0["ai_profile"]["source"], "local_heuristic")
        self.assertIn("橘", r0["ai_profile"]["coat"])
        self.assertEqual(r0["ai_profile"]["breed"], "未知")

        cid = self.seed_cat("胖橘", "图书馆", orange)
        hit, _ = self.call(
            "/api/identify",
            {"photo": self.orange_cat_photo(1), "boxes": [[0, 0, 1, 1]], "area": "图书馆"},
            self.member,
        )
        r1 = hit["results"][0]
        self.assertEqual(r1["record_status"]["status"], "possible_match")
        self.assertIsNone(r1["record_status"]["recorded"])
        self.assertEqual(r1["record_status"]["top_cat_id"], cid)
        self.assertTrue(r1["record_status"]["area_matched"])
        self.assertGreater(r1["candidates"][0]["similarity"], 0.7)

        bw = self.black_white_photo()
        miss, _ = self.call("/api/identify", {"photo": bw, "boxes": [[0, 0, 1, 1]]}, self.member)
        r2 = miss["results"][0]
        self.assertEqual(r2["record_status"]["status"], "no_candidate")
        self.assertIsNone(r2["record_status"]["recorded"])
        self.assertIn("奶牛", r2["ai_profile"]["coat"])

    def test_provider_scope_credentials_and_real_chat_routing(self):
        path = "/api/agent/settings"
        shared = dict(scope="shared", action="save", protocol="tools", base_url="https://campus.example/v1",
                      chat_model="campus-model", api_key="campus-test-key")
        personal = dict(shared, scope="personal", protocol="chat", base_url="https://personal.example/v1",
                        chat_model="my-agent", api_key="personal-test-key")
        self.call(path, shared, expected=401)
        self.call(path, shared, self.member, expected=403)
        self.call(path, shared, self.reviewer)
        self.call(path, personal, self.member)
        visible = self.call(path, cookie=self.member)[0]
        self.assertEqual(set(visible), {"personal"})
        self.assertNotIn("api_key", visible["personal"])
        self.call(path, dict(personal, base_url="https://other.example/v1", api_key=""), self.member, expected=400)
        def provider(cfg, payload):
            self.assertEqual(payload["model"], cfg.get("chat_model", payload["model"]))
            return {"choices":[{"message":{"content":payload["model"]}}]}
        with mock.patch("providers.completion", side_effect=provider) as outbound:
            self.call(path, dict(personal, action="test", api_key=""), self.member)
            for cookie, want, key in (("", "campus-model", "campus-test-key"),
                                      (self.member, "my-agent", "personal-test-key"),
                                      (self.reviewer, "campus-model", "campus-test-key")):
                reply = self.call("/api/agent/chat", {"message":"全校有几只猫？"}, cookie)[0]
                self.assertEqual((reply["mode"], reply["reply"]), ("llm", want))
                cfg, payload = outbound.call_args.args
                self.assertEqual(cfg["api_key"], key)
                self.assertEqual("tools" in payload, want == "campus-model")
        self.call(path, dict(scope="personal", action="remove"), self.member)
        self.assertEqual(self.call("/api/agent/status", cookie=self.member)[0]["chat_model"], "campus-model")

    def test_vlm_breed_recognition_with_mocked_api(self):
        fake_vlm = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "breed": "英国短毛猫",
                                "breed_confidence": "high",
                                "coat": "蓝白短毛",
                                "features": ["左耳剪耳", "圆脸"],
                                "neutered_hint": "yes",
                                "summary": "疑似已绝育的蓝白英短。",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        with mock.patch.dict(os.environ, {"CAMPUSCATS_LLM_API_KEY": "sk-test", "CAMPUSCATS_VISION_MODEL": "qwen-vl-plus"}):
            with mock.patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(fake_vlm)):
                res, _ = self.call("/api/identify", {"photo": self.orange_cat_photo(), "boxes": [[0, 0, 1, 1]], "cloud_photo": True}, self.member)
        ai_p = res["results"][0]["ai_profile"]
        self.assertEqual(ai_p["source"], "vlm")
        self.assertEqual(ai_p["breed"], "英国短毛猫")
        self.assertEqual(ai_p["neutered_hint"], "yes")
        self.assertIn("左耳剪耳", ai_p["features"])

    def test_agent_status_and_local_fallback(self):
        st, _ = self.call("/api/agent/status")
        self.assertEqual(st["mode"], "local_fallback")

        cid = self.seed_cat("图书馆大橘", "图书馆", self.orange_cat_photo())

        ov, _ = self.call("/api/agent/chat", {"message": "全校现在统计有几只猫？"})
        self.assertEqual(ov["mode"], "local_fallback")
        self.assertIn("1 只猫", ov["reply"])
        self.assertIn("get_campus_overview", ov["tool_calls"])

        found, _ = self.call("/api/agent/chat", {"message": "帮我找一下图书馆的猫"})
        self.assertEqual(found["cards"][0]["id"], cid)
        self.assertIn("图书馆大橘", found["reply"])

        pic, _ = self.call("/api/agent/chat", {"message": "这只猫库里记录过吗？", "photo": self.orange_cat_photo(1), "area": "图书馆"})
        self.assertIn("identify_uploaded_photo", pic["tool_calls"])
        self.assertIn("可先对照", pic["reply"])
        self.assertIsNotNone(pic["identification"])

    def test_unclear_and_competing_photos_abstain(self):
        self.seed_cat("甲", photo=self.orange_cat_photo(0))
        self.seed_cat("乙", photo=self.orange_cat_photo(1))
        frame = {"photo":self.orange_cat_photo(2), "boxes":[[0,0,1,1]]}
        similar = self.call("/api/identify",frame,self.member)[0]["results"][0]
        self.assertEqual(similar["record_status"]["status"], "ambiguous")
        buf = io.BytesIO()
        Image.new("RGB",(300,200),"gray").save(buf,"PNG")
        frame["photo"] = base64.b64encode(buf.getvalue()).decode()
        unclear = self.call("/api/identify",frame,self.member)[0]["results"][0]
        self.assertEqual(unclear["record_status"]["status"],"poor_quality")
        self.assertIsNone(unclear["ai_profile"])

    def test_chat_falls_back_after_tool_without_sending_unapproved_crop(self):
        first = {"choices":[{"message":{"tool_calls":[{"id":"one","function":{
            "name":"identify_uploaded_photo","arguments":"{}"}}]}}]}
        with mock.patch.dict(os.environ, {"CAMPUSCATS_LLM_API_KEY":"fixture"}), \
             mock.patch("agent._call_chat_llm", side_effect=[first,TimeoutError()]), \
             mock.patch("ai_vision._call_vlm") as visual:
            reply = self.call("/api/agent/chat",{"photo":self.orange_cat_photo()})[0]
        visual.assert_not_called()
        self.assertEqual(reply["mode"], "local_fallback")
        self.assertEqual(reply["identification"]["results"][0]["ai_profile"]["breed"],"未知")

    def test_agent_llm_tool_calling_loop(self):
        cid = self.seed_cat("奶牛学长", "三食堂", self.black_white_photo())
        first_turn = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "search_cats", "arguments": '{"query":"三食堂"}'},
                            }
                        ],
                    }
                }
            ]
        }
        second_turn = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "三食堂目前记录了「奶牛学长」，欢迎去图鉴里看看它的档案！",
                    }
                }
            ]
        }
        with mock.patch.dict(os.environ, {"CAMPUSCATS_LLM_API_KEY": "sk-test", "CAMPUSCATS_LLM_MODEL": "qwen-plus"}):
            with mock.patch(
                "urllib.request.urlopen",
                side_effect=[_FakeHTTPResponse(first_turn), _FakeHTTPResponse(second_turn)],
            ):
                reply, _ = self.call("/api/agent/chat", {"message": "三食堂有哪些猫？"})
        self.assertEqual(reply["mode"], "llm")
        self.assertIn("search_cats", reply["tool_calls"])
        self.assertIn("奶牛学长", reply["reply"])
        self.assertEqual(reply["cards"][0]["id"], cid)


    def test_guest_identify_and_backup_restore_provider_safety(self):
        from backup import backup
        from zipfile import ZipFile

        cid = self.seed_cat("校园小橘", "东区草坪", self.orange_cat_photo())
        # Guest (no cookie) can call /api/identify directly without detouring through /api/agent/chat
        guest_res, _ = self.call("/api/identify", {"photo": self.orange_cat_photo(1), "boxes": [[0, 0, 1, 1]]})
        self.assertEqual(guest_res["results"][0]["record_status"]["top_cat_id"], cid)

        # Save a shared provider, then back up and restore into a fresh directory without agent-key.fernet
        self.call(
            "/api/agent/settings",
            {
                "scope": "shared",
                "action": "save",
                "base_url": "https://api.example.com/v1",
                "chat_model": "qwen-plus",
                "vision_model": "qwen-vl-plus",
                "protocol": "tools",
                "api_key": "sk-secret-key",
            },
            self.reviewer,
        )
        with tempfile.TemporaryDirectory() as scratch:
            dest = Path(scratch) / "snap.zip"
            backup(self.app.data, self.app.media, dest)
            restore_dir = Path(scratch) / "restore"
            with ZipFile(dest) as zf:
                zf.extractall(restore_dir)
            restored = App(restore_dir, None)
            prev = self.app
            self.app = restored
            try:
                st, _ = self.call("/api/agent/status")
                self.assertEqual(st["mode"], "local_fallback")
                res, _ = self.call("/api/identify", {"photo": self.orange_cat_photo(1), "boxes": [[0, 0, 1, 1]]})
                self.assertEqual(res["results"][0]["record_status"]["top_cat_id"], cid)
            finally:
                self.app = prev

        # Corrupting agent-key.fernet must gracefully degrade instead of 503
        (self.app.data / "agent-key.fernet").write_bytes(b"corrupted-key")
        st_corrupt, _ = self.call("/api/agent/status")
        self.assertEqual(st_corrupt["mode"], "local_fallback")

    def test_provider_test_verifies_vision_model_and_omits_temperature(self):
        captured = []

        def fake_completion(cfg, payload):
            captured.append(payload)
            return {"choices": [{"message": {"content": "OK"}}]}

        with mock.patch("providers.completion", side_effect=fake_completion):
            res, _ = self.call(
                "/api/agent/settings",
                {
                    "scope": "personal",
                    "action": "test",
                    "base_url": "https://api.example.com/v1",
                    "chat_model": "o3-mini",
                    "vision_model": "qwen-vl-plus",
                    "protocol": "tools",
                    "api_key": "sk-test-123",
                },
                self.member,
            )
        self.assertTrue(res["ok"])
        self.assertTrue(res["vision_tested"])
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0]["model"], "o3-mini")
        self.assertEqual(captured[1]["model"], "qwen-vl-plus")
        self.assertNotIn("temperature", captured[1])


if __name__ == "__main__":
    unittest.main()
