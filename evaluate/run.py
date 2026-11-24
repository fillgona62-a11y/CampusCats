"""Reproducible known/unknown retrieval evaluation on local, labeled photos."""

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from face_match import correspondence_score, face_features
from media import jpeg_bytes
from vision import DEFAULT_MAX_DISTANCE, MODEL_VERSION, analyze_crop, pixel_box, rank_candidates

COLUMNS = {"split", "cat_id", "date", "photo", "x", "y", "width", "height"}


def _auto_verify(probe_landmarks, ranked, gallery_landmarks):
    if probe_landmarks is None or len(ranked) > 6:
        return None
    allowed = {c["cat_id"] for c in ranked}
    hits = {}
    for ref_idx, (cat_id, day, landmarks) in enumerate(gallery_landmarks):
        if cat_id not in allowed or landmarks is None:
            continue
        score = correspondence_score(probe_landmarks, landmarks)
        if score >= 18:
            hits.setdefault(cat_id, []).append((score, day, ref_idx))
    if len(hits) != 1:
        return None
    cat_id, matches = next(iter(hits.items()))
    matches.sort(key=lambda m: (-m[0], m[2]))
    strong = [day for score, day, _ in matches if score >= 26]
    if not strong:
        return None
    first_day = strong[0]
    if not any(day != first_day for day in strong[1:]):
        return None
    return cat_id


def load_set(manifest, *, raw=False):
    entries, seen, splits = [], set(), {}
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not COLUMNS.issubset(reader.fieldnames or []):
            raise ValueError("请按 manifest.example.csv 填写完整列名。")
        for row in reader:
            try:
                split, cat_id = row["split"].strip(), row["cat_id"].strip()
                day = date.fromisoformat(row["date"].strip())
                if not cat_id or split not in {"gallery", "test"}:
                    raise ValueError("请填写 cat_id 以及 gallery 或 test。")
                box = tuple(float(row[f]) for f in ("x", "y", "width", "height"))
                path = manifest.parent / row["photo"]
                with Image.open(path) as file:
                    upright = ImageOps.exif_transpose(file).convert("RGB")
                signature = hashlib.sha256(str(upright.size).encode() + upright.tobytes()).digest()
                if signature in splits and splits[signature] != split:
                    raise ValueError("同一照片出现在两种分组。")
                if (signature, box) in seen:
                    raise ValueError("同一照片与取景框被重复列入清单。")
                seen.add((signature, box))
                splits[signature] = split
                if raw:
                    photo = upright
                else:
                    # Match online media.canonical_photo (2048px JPEG q=84) pixel-for-pixel.
                    with Image.open(io.BytesIO(jpeg_bytes(upright, 2048))) as decoded:
                        photo = decoded.convert("RGB")
                analysis = analyze_crop(photo, box)
                landmarks = face_features(photo.crop(pixel_box(photo, box))) if analysis["usable"] else None
                entries.append((split, cat_id, day, row["photo"], analysis, landmarks))
            except (ValueError, OSError) as error:
                raise ValueError(f"CSV 第 {reader.line_num} 行：{error}") from error
    return entries


def evaluate(manifest, threshold, *, raw=False):
    entries = load_set(manifest, raw=raw)
    references = []
    gallery_landmarks = []
    days = defaultdict(set)
    probes = []
    for split, cat_id, day, photo, analysis, landmarks in entries:
        if split == "gallery":
            references.append((cat_id, analysis))
            gallery_landmarks.append((cat_id, day, landmarks))
            days[cat_id].add(day)
        else:
            probes.append((cat_id, day, photo, analysis, landmarks))
    if not any(v["usable"] for _, v in references) or not probes:
        raise ValueError("至少需要一张能用于比对的建档照片和一张测试照片。")
    has_multi_day_gallery = any(len(d) >= 2 for d in days.values())
    trials = []
    for cat_id, day, photo, analysis, landmarks in probes:
        if day in days.get(cat_id, ()):
            raise ValueError(f"{photo} 与同一只猫的建档照片日期重合。")
        candidates = rank_candidates(analysis, references, max_distance=threshold)
        ranked_7 = rank_candidates(analysis, references, limit=7, max_distance=threshold) if has_multi_day_gallery else []
        auto_cat = _auto_verify(landmarks, ranked_7, gallery_landmarks) if has_multi_day_gallery else None
        trials.append({"photo": photo, "truth": cat_id, "known": cat_id in days,
                       "usable": analysis["usable"], "candidates": [c["cat_id"] for c in candidates],
                       "auto_assigned": auto_cat})
    known = [t for t in trials if t["known"]]
    unknown = [t for t in trials if not t["known"]]

    def measure(count, total):
        return {"count": count, "total": total, "rate": round(count/total, 4) if total else None}

    return {
        "model": MODEL_VERSION, "threshold": threshold,
        "canonical_jpeg": not raw,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "gallery_ids": len(days), "gallery_images": len(references),
        "usable_gallery_images": sum(v["usable"] for _, v in references),
        "known_test_ids": len({t["truth"] for t in known}),
        "unknown_test_ids": len({t["truth"] for t in unknown}),
        "known_top1": measure(sum(t["candidates"][:1] == [t["truth"]] for t in known), len(known)),
        "known_top3": measure(sum(t["truth"] in t["candidates"] for t in known), len(known)),
        "unknown_given_any_candidate": measure(sum(bool(t["candidates"]) for t in unknown), len(unknown)),
        "quality_abstentions": measure(sum(not t["usable"] for t in trials), len(trials)),
        "auto_archive": {
            "known_correct": measure(sum(t["auto_assigned"] == t["truth"] for t in known), len(known)),
            "known_wrong_id": measure(
                sum(t["auto_assigned"] is not None and t["auto_assigned"] != t["truth"] for t in known), len(known)
            ),
            "unknown_false_accept": measure(sum(t["auto_assigned"] is not None for t in unknown), len(unknown)),
        },
        "trials": trials,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--threshold", type=float, default=DEFAULT_MAX_DISTANCE)
    parser.add_argument("--raw", action="store_true", help="Skip 2048px JPEG canonicalization")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not math.isfinite(args.threshold) or not 0 <= args.threshold <= 1:
        parser.error("--threshold 取值范围为 0 至 1。")
    try:
        result = evaluate(args.manifest, args.threshold, raw=args.raw)
    except (ValueError, OSError) as error:
        parser.exit(2, f"{error}\n")
    report = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(report + "\n", encoding="utf-8")
    else:
        print(report)
