import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from PIL import Image
import app
import ai_vision
import catalog
import providers
from media import Problem
from test_v060 import _rich_photo_b64


class LookupFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = app.App(Path(self.tmp.name), None)
        self.photo = _rich_photo_b64()

    def lookup(self, mode, cloud=False):
        with closing(catalog.connect(self.service.db_path)) as db:
            return catalog.identify(db, {"photo": self.photo, "box_mode": mode, "cloud_photo": cloud},
                                    self.service.media)

    def test_detected_boxes_reuse_the_first_scan(self):
        scan = {"cats": [{"box": [0, 0, .5, 1]}, {"box": [.5, 0, .5, 1]}], "non_cat_type": None}
        with mock.patch("detector.inspect_image_subjects", return_value=scan) as detect, \
             mock.patch("detector.is_enabled", return_value=True), \
             mock.patch("detector._run_full_frame_scan", side_effect=AssertionError("repeated scan")):
            result = self.lookup("auto")
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["detected_boxes"], [r["box"] for r in result["results"]])
        detect.assert_called_once()

    def test_zero_boxes_and_explicit_review(self):
        with mock.patch("detector.inspect_image_subjects", return_value={"cats": [], "non_cat_type": "dog"}), \
             mock.patch("detector.is_enabled", return_value=True), \
             mock.patch("ai_vision.has_cloud_vlm", return_value=True), \
             mock.patch("ai_vision.review_scene") as review:
            self.assertEqual(self.lookup("auto", True)["results"], [])
            with self.assertRaises(Problem):
                self.lookup("cloud_review")
            review.assert_not_called()
            for value in [None, {}, {"uncertain": True}, {"boxes": [[0, 0, 2, 2]]}]:
                review.return_value = value
                with self.assertRaises(Problem):
                    self.lookup("cloud_review", True)
            review.return_value = {"boxes": []}
            self.assertEqual(self.lookup("cloud_review", True)["results"], [])
            review.return_value = {"boxes": [[0, 0, 1, 1]]}
            with mock.patch("ai_vision.classify_cat_crop", return_value={"source": "vlm", "is_cat": True}):
                result = self.lookup("cloud_review", True)
            self.assertEqual(result["results"][0]["ai_profile"]["source"], "vlm")

    def test_reference_budget_and_missing_files(self):
        candidates = []
        refs = []
        for cat in range(1, 6):
            candidates.append({"id": cat, "name": str(cat), "reference_id": cat*10})
            for j, day in enumerate(["day1", "day1", "day2"]):
                filename = f"{cat}-{j}.jpg"
                if cat != 1 or j != 0:
                    Image.new("RGB", (120, 80), (cat*40, j*60, 0)).save(self.service.media/filename)
                refs.append((cat, dict(_reference_id=cat*10+j, frame=filename, box=[0,0,1,1], day=day)))
        selected = catalog._load_candidate_crops(candidates, refs, self.service.media)
        self.assertEqual([r["id"] for r in selected], [1,2,3,4,5])
        self.assertEqual(selected[0]["reference_id"], 11)
        self.assertFalse(any("alternate" in r for r in selected))
        few = catalog._load_candidate_crops(candidates[:2], refs, self.service.media)
        self.assertTrue(all("alternate" in r for r in few))
        self.assertGreater(few[0]["alternate"].getpixel((0,0))[1], 90)

    def test_multicat_parallel_comparison_keeps_order_and_provider(self):
        both_started = threading.Barrier(2, timeout=5)
        def identify_one(box):
            self.assertEqual(providers.active.get(), {"scope": "personal"})
            both_started.wait()
            return box
        token = providers.active.set({"scope": "personal"})
        try:
            self.assertEqual(catalog._identify_boxes([1, 2, 3, 4], identify_one, True), [1, 2, 3, 4])
        finally:
            providers.active.reset(token)
        with mock.patch.object(catalog, "_EXTRA_LOOKUP_WORKERS", threading.Semaphore(0)):
            self.assertEqual(catalog._identify_boxes([1, 2], lambda _: threading.get_ident(), True),
                             [threading.get_ident()] * 2)

    def test_reviewed_photo_can_be_saved_only_for_that_user_frame_and_boxes(self):
        with closing(catalog.connect(self.service.db_path)) as db:
            accounts = []
            for name in ("one", "two"):
                accounts.append(db.execute("INSERT INTO users(email,nickname,salt,password_hash,recovery_hash)"
                    " VALUES(?,?,'salt','hash','recovery')", (name, name)).lastrowid)
            db.commit()
            boxes = [[0, 0, 1, 1]]
            with mock.patch("ai_vision.has_cloud_vlm", return_value=True), \
                 mock.patch("ai_vision.review_scene", return_value={"boxes": boxes}), \
                 mock.patch("ai_vision.classify_cat_crop", return_value={"source":"vlm", "is_cat":True}):
                res = catalog.identify(db, {"photo": self.photo, "cloud_photo": True, "box_mode": "cloud_review",
                                            "for_sighting": True}, self.service.media, reviewer_uid=accounts[0])
            self.assertTrue(res["reviewed_for_sighting"])
            body = {"photo": self.photo, "boxes": boxes, "area": "图书馆", "request_id": "review-test",
                    "reviewed_photo": True}
            with mock.patch("detector.is_enabled", return_value=True), \
                 mock.patch("detector.verify_box_is_cat", return_value={"is_cat":False, "reason":"未检测到猫"}):
                for uid, changes in [(accounts[1], {}), (accounts[0], {"boxes":[[0, 0, .5, 1]]}),
                                     (accounts[0], {"photo": _rich_photo_b64(bg=(80,100,220))})]:
                    with self.assertRaises(Problem):
                        catalog.upload(db, self.service.media, uid, dict(body, **changes))
                catalog.upload(db, self.service.media, accounts[0], body)
                self.assertEqual(db.execute("SELECT status FROM sightings").fetchone()[0], "pending")

    def test_fifth_candidate_and_uncertain_index(self):
        im = Image.new("RGB", (256, 80), "red")
        cands = [{"id": i, "crop": im} for i in range(1,6)]
        sheet = ai_vision._make_comparison_sheet(im, cands)
        self.assertEqual(sheet.getpixel((7, 33)), (245,245,240))
        self.assertEqual(sheet.getpixel((7, 160)), (255,0,0))
        cfg = {"enabled": True, "vision_model":"test","timeout":10,"scope":"shared"}
        with mock.patch("ai_vision.llm_config", return_value=cfg), mock.patch("providers.completion") as remote:
            for idx, verdict in [(5, "same_cat"), (6, "uncertain")]:
                raw = '{"verdict":"same_cat","best_candidate_index":%d,"confidence":0.9}' % idx
                remote.return_value={"choices":[{"message":{"content":raw}}]}
                res=ai_vision.compare_candidates_vlm(im, cands, allow_remote=True)
                self.assertEqual(res["verdict"],verdict)
            self.assertEqual(remote.call_count, 2)
