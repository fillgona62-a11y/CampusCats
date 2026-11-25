"""Unit tests and quantitative lighting/flip benchmark for CampusCats v0.4.4-SYLU recognition upgrades."""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import ai_vision
import catalog
import face_match
import maintenance
import vision


def _synth_cat_image(seed_color, stripe_color, *, size=(240, 240), asymmetry="left"):
    """Create a rich textured synthetic cat-like image with distinctive asymmetric markings."""
    im = Image.new("RGB", size, (110, 145, 95))  # outdoor grass backdrop
    draw = ImageDraw.Draw(im)
    # Cat torso/head in center
    draw.ellipse([36, 32, 204, 212], fill=seed_color)
    # Tabby/calico stripes & distinctive markings
    for y in range(48, 196, 18):
        draw.line([(56, y), (184, y + 6)], fill=stripe_color, width=5)
    # Asymmetric white blaze on left or right side
    if asymmetry == "left":
        draw.ellipse([52, 66, 108, 140], fill=(242, 240, 234))
        draw.rectangle([72, 146, 122, 196], fill=(246, 244, 238))
    else:
        draw.ellipse([132, 66, 188, 140], fill=(242, 240, 234))
        draw.rectangle([118, 146, 168, 196], fill=(246, 244, 238))
    # Eyes & nose
    draw.ellipse([86, 94, 102, 110], fill=(35, 30, 25))
    draw.ellipse([138, 94, 154, 110], fill=(35, 30, 25))
    draw.polygon([(114, 122), (126, 122), (120, 132)], fill=(215, 130, 125))
    return im


class RecognitionV044Tests(unittest.TestCase):
    def test_flip_and_lighting_invariance(self):
        orange_cat = _synth_cat_image((212, 138, 68), (158, 86, 32), asymmetry="left")
        tuxedo_cat = _synth_cat_image((34, 36, 40), (70, 74, 82), asymmetry="right")
        tabby_cat = _synth_cat_image((132, 124, 108), (62, 56, 48), asymmetry="right")

        ref_orange = vision.analyze_crop(orange_cat, [0.0, 0.0, 1.0, 1.0])
        ref_orange["_reference_id"] = 101
        ref_tux = vision.analyze_crop(tuxedo_cat, [0.0, 0.0, 1.0, 1.0])
        ref_tux["_reference_id"] = 102
        ref_tabby = vision.analyze_crop(tabby_cat, [0.0, 0.0, 1.0, 1.0])
        ref_tabby["_reference_id"] = 103
        refs = [(1, ref_orange), (2, ref_tux), (3, ref_tabby)]

        # Horizontally flipped + darkened (backlit shadow) query of orange_cat
        query_img = ImageEnhance.Brightness(ImageOps.mirror(orange_cat)).enhance(0.68)
        query = vision.analyze_crop(query_img, [0.0, 0.0, 1.0, 1.0])
        ranked = vision.rank_candidates(query, refs, limit=3)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["cat_id"], 1)

    @unittest.skipIf(face_match.cv2 is None, "OpenCV not installed")
    def test_body_sift_rerank_boosts_true_match(self):
        orange_cat = _synth_cat_image((212, 138, 68), (158, 86, 32), asymmetry="left")
        other_cat = _synth_cat_image((208, 136, 72), (180, 118, 56), asymmetry="right")
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp)
            orange_cat.save(media / "ref1.jpg", "JPEG", quality=92)
            other_cat.save(media / "ref2.jpg", "JPEG", quality=92)
            refs = [
                (1, {"_reference_id": 11, "frame": "ref1.jpg", "box": [0.0, 0.0, 1.0, 1.0]}),
                (2, {"_reference_id": 22, "frame": "ref2.jpg", "box": [0.0, 0.0, 1.0, 1.0]}),
            ]
            # Start with other_cat slightly ahead before SIFT reranking
            candidates = [
                {"id": 2, "name": "B", "reference_id": 22, "similarity": 0.62, "distance": 0.18},
                {"id": 1, "name": "A", "reference_id": 11, "similarity": 0.60, "distance": 0.19},
            ]
            # Slightly rotated/scaled crop of orange_cat
            q_img = orange_cat.rotate(8, expand=False)
            reranked = face_match.rerank_with_local_features(q_img, candidates, refs, media)
            self.assertEqual(reranked[0]["id"], 1)
            self.assertGreaterEqual(reranked[0]["local_inliers"], 12)

    def test_vlm_comparison_sheet_and_promotion(self):
        orange_cat = _synth_cat_image((212, 138, 68), (158, 86, 32), asymmetry="left")
        tabby_cat = _synth_cat_image((132, 124, 108), (62, 56, 48), asymmetry="right")
        sheet = ai_vision._make_comparison_sheet(
            orange_cat,
            [{"name": "暖橘", "crop": orange_cat}, {"name": "青苔", "crop": tabby_cat}],
        )
        self.assertIsNotNone(sheet)
        self.assertGreater(sheet.width, 500)

        fake_raw = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "verdict": "same_cat",
                        "best_candidate_index": 2,
                        "confidence": 0.88,
                        "matching_features": ["额头M纹一致", "左侧白斑形状相同"],
                        "differences": [],
                        "reason": "额头纹与面部白斑边界完全一致，高度疑似同一只猫。",
                    }, ensure_ascii=False)
                }
            }]
        }
        with mock.patch.object(ai_vision, "llm_config", return_value={
            "enabled": True, "vision_model": "gpt-4o-mini", "base_url": "https://example.invalid",
            "api_key": "k", "timeout": 10, "scope": "",
        }), mock.patch.object(ai_vision, "_environment_completion", return_value=fake_raw):
            res = ai_vision.compare_candidates_vlm(
                orange_cat,
                [{"name": "青苔", "coat": "狸花", "crop": tabby_cat}, {"name": "暖橘", "coat": "橘白", "crop": orange_cat}],
                allow_remote=True,
            )
            self.assertIsNotNone(res)
            self.assertEqual(res["verdict"], "same_cat")
            self.assertEqual(res["best_candidate_index"], 2)

    def test_reindex_vision_upgrades_legacy_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            media_dir = Path(tmp) / "media"
            data_dir.mkdir()
            media_dir.mkdir()
            db_path = data_dir / "campus.sqlite3"
            db = catalog.connect(db_path)
            db.executescript((SERVER_DIR / 'schema.sql').read_text(encoding='utf-8'))
            catalog.migrate(db)
            img = _synth_cat_image((212, 138, 68), (158, 86, 32))
            img.save(media_dir / "f1.jpg", "JPEG", quality=90)
            db.execute("INSERT INTO users(id, email, nickname, salt, password_hash, recovery_hash, role) VALUES(1, 'a@b.edu', 'A', 's', 'x', 'y', 'member')")
            db.execute("INSERT INTO cats(id, name, coat, breed, evidence) VALUES(1, '橘猫', '橘白', '', '')")
            db.execute("INSERT INTO frames(id, user_id, request_id, request_hash, image, area, note, observed_at) VALUES(1, 1, 'r1', 'h1', 'f1.jpg', '图书馆', '', '2026-01-01')")
            legacy = json.dumps({"version": "coat-texture-1", "usable": True, "warnings": [], "features": [0.0] * 136})
            db.execute(
                "INSERT INTO sightings(id, frame_id, box, crop, analysis, status, cat_id) VALUES(1, 1, '[0,0,1,1]', 'f1.jpg', ?, 'confirmed', 1)",
                (legacy,),
            )
            db.commit()
            db.close()

            dry = maintenance.reindex_vision(data_dir, media_dir, apply=False)
            self.assertEqual(dry["needs_update"], 1)
            self.assertEqual(dry["updated"], 0)

            applied = maintenance.reindex_vision(data_dir, media_dir, apply=True)
            self.assertEqual(applied["updated"], 1)
            self.assertEqual(applied["model_version"], vision.MODEL_VERSION)

            db2 = catalog.connect(db_path)
            updated_row = json.loads(db2.execute("SELECT analysis FROM sightings WHERE id=1").fetchone()[0])
            db2.close()
            self.assertEqual(updated_row["version"], vision.MODEL_VERSION)
            self.assertEqual(len(updated_row["features"]), vision.FEATURE_SIZE)


if __name__ == "__main__":
    unittest.main()
