"""Tests for v0.5.0-SYLU multi-cat auto-detection (/api/detect) and geolocation persistence."""

import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import app as app_mod
import detector


def _jpeg_data_url(color=(210, 140, 70), size=(260, 260)):
    im = Image.new("RGB", size, color)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class V050MultiCatAndGeoTests(unittest.TestCase):
    def _call(self, application, path, body, cookie=""):
        raw = json.dumps(body).encode("utf-8")
        env = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": path,
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(raw)),
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.input": io.BytesIO(raw),
        }
        if cookie:
            env["HTTP_COOKIE"] = cookie
        status_holder = []
        headers_holder = []

        def start_resp(status, headers):
            status_holder.append(int(status.split()[0]))
            headers_holder.append(dict(headers))

        resp = b"".join(application(env, start_resp))
        return status_holder[0], json.loads(resp.decode("utf-8")), headers_holder[0]

    def test_detect_endpoint_returns_multiple_boxes(self):
        with tempfile.TemporaryDirectory() as tmp:
            application = app_mod.App(Path(tmp) / "data", Path(tmp) / "media")
            fake_boxes = [
                {"box": [0.05, 0.1, 0.35, 0.6], "score": 0.89},
                {"box": [0.55, 0.15, 0.38, 0.62], "score": 0.81},
            ]
            with mock.patch.object(detector, "detect_cats", return_value=fake_boxes), \
                 mock.patch.object(detector, "is_enabled", return_value=True):
                code, data, _ = self._call(application, "/api/detect", {"photo": _jpeg_data_url()})
            self.assertEqual(code, 200)
            self.assertTrue(data["detector_enabled"])
            self.assertEqual(len(data["boxes"]), 2)
            self.assertEqual(data["detections"][0]["score"], 0.89)

    def test_upload_persists_geolocation_with_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            application = app_mod.App(Path(tmp) / "data", Path(tmp) / "media")
            code, _, hdrs = self._call(application, "/api/register", {
                "email": "geo@sylu.edu", "password": "Password123!", "nickname": "GeoTester"
            })
            self.assertEqual(code, 200)
            cookie = hdrs.get("Set-Cookie", "").split(";")[0]

            code, up, _ = self._call(application, "/api/sightings", {
                "photo": _jpeg_data_url(),
                "boxes": [[0.1, 0.1, 0.8, 0.8]],
                "area": "兵器博物馆 / 兵器广场",
                "note": "在兵器广场晒太阳",
                "request_id": "geo-req-1",
                "observed_at": "2026-11-24T09:30:00Z",
                "latitude": 41.726883,
                "longitude": 123.491791,
                "location_accuracy": 14,
            }, cookie=cookie)
            self.assertEqual(code, 200)
            s = up["sightings"][0]
            self.assertAlmostEqual(s["latitude"], 41.726883, places=5)
            self.assertAlmostEqual(s["longitude"], 123.491791, places=5)
            self.assertEqual(s["location_accuracy"], 14)
            self.assertEqual(s["observed_at"], "2026-11-24T09:30:00+00:00")




    def test_map_config_and_geo_sightings_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            application = app_mod.App(Path(tmp) / "data", Path(tmp) / "media")
            code, _, hdrs = self._call(application, "/api/register", {
                "email": "map@sylu.edu", "password": "Password123!", "nickname": "MapUser"
            })
            self.assertEqual(code, 200)
            cookie = hdrs.get("Set-Cookie", "").split(";")[0]
            self._call(application, "/api/sightings", {
                "photo": _jpeg_data_url(),
                "boxes": [[0.1, 0.1, 0.8, 0.8]],
                "area": "图书馆南门",
                "note": "",
                "request_id": "map-req-1",
                "observed_at": "2026-11-24T09:30:00Z",
                "latitude": 41.727829,
                "longitude": 123.493886,
                "location_accuracy": 10,
            }, cookie=cookie)

            def _get(path):
                env = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "REMOTE_ADDR": "127.0.0.1", "HTTP_COOKIE": cookie}
                st = []
                body = b"".join(application(env, lambda s, h: st.append(int(s.split()[0]))))
                return st[0], json.loads(body.decode("utf-8"))

            c1, cfg = _get("/api/map/config")
            self.assertEqual(c1, 200)
            self.assertIn("amap_key", cfg)
            c2, ms = _get("/api/map/sightings")
            self.assertEqual(c2, 200)
            self.assertEqual(len(ms["sightings"]), 1)
            self.assertAlmostEqual(ms["sightings"][0]["latitude"], 41.727829, places=5)


if __name__ == "__main__":
    unittest.main()
