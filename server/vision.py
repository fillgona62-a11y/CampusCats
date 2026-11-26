"""Photo quality checks, illumination-robust candidate retrieval, and DB-presence assessment.

v0.4.4-SYLU upgrades:
- Illumination-robust normalization (mild Gray-World white balance + luminance stretch)
- Elliptical foreground-weighted spatial pyramid HSV + uniform LBP + gradient orientation (coat-texture-2)
- Horizontal flip-invariant matching (left/right side & mirrored selfie support)
- Multi-reference consensus blending + subtle campus-area tie-breaker
- Seamless ONNX deep embedding support via encoder.py (with TTA)
"""

import math
import os
from collections import Counter

from PIL import Image, ImageFilter, ImageOps, ImageStat
import encoder

try:
    import numpy as np
except ImportError:
    np = None

MODEL_VERSION = encoder.VERSION or "coat-texture-2"
# Calibrated distance ceiling to suppress false-positive cross-cat matches while preserving cross-day recall.
DEFAULT_MAX_DISTANCE = float(os.getenv("CAMPUSCATS_DISTANCE", "0.28" if encoder.VERSION else "0.32"))
if not math.isfinite(DEFAULT_MAX_DISTANCE) or not 0 <= DEFAULT_MAX_DISTANCE <= 1:
    raise ValueError("CAMPUSCATS_DISTANCE 取值范围为 0 至 1。")

HIST_SIZE = 42
LBP_SIZE = 10
HOG_SIZE = 8
# 5 spatial HSV histograms (global, top, bottom, left, right) + LBP + gradient orientation
FEATURE_SIZE = HIST_SIZE * 5 + LBP_SIZE + HOG_SIZE
_HIST_GROUPS = (
    (0, HIST_SIZE, 0.34),
    (HIST_SIZE, 2 * HIST_SIZE, 0.12),
    (2 * HIST_SIZE, 3 * HIST_SIZE, 0.12),
    (3 * HIST_SIZE, 4 * HIST_SIZE, 0.07),
    (4 * HIST_SIZE, 5 * HIST_SIZE, 0.07),
    (5 * HIST_SIZE, 5 * HIST_SIZE + LBP_SIZE, 0.16),
    (5 * HIST_SIZE + LBP_SIZE, FEATURE_SIZE, 0.12),
)
if np is not None:
    _L1_WEIGHTS = np.empty(FEATURE_SIZE, dtype=np.float64)
    for _start, _end, _weight in _HIST_GROUPS:
        _L1_WEIGHTS[_start:_end] = 0.5 * _weight
else:
    _L1_WEIGHTS = None


def pixel_box(image, box):
    """Convert normalized left/top/width/height in EXIF-oriented coordinates."""
    if len(box) != 4 or not all(math.isfinite(float(v)) for v in box):
        raise ValueError("取景框需要四个有限数值")
    x, y, width, height = map(float, box)
    if min(x, y) < 0 or min(width, height) <= 0 or max(x + width, y + height) > 1.000001:
        raise ValueError("取景框超出照片范围")
    return (
        int(x * image.width), int(y * image.height),
        min(image.width, math.ceil((x + width) * image.width)),
        min(image.height, math.ceil((y + height) * image.height)),
    )


def _quality(crop):
    warnings = []
    if min(crop.size) < 72:
        warnings.append("框内主体像素较少，可以补拍一张猫占画面更大的照片。")
    gray = crop.convert("L")
    gray.thumbnail((192, 192), Image.Resampling.LANCZOS)
    mean = ImageStat.Stat(gray).mean[0]
    if mean < 28:
        warnings.append("框内画面偏暗，可以在自然光下补拍。")
    elif mean > 237:
        warnings.append("框内画面偏亮，可以降低曝光后补拍。")
    edges = gray.filter(ImageFilter.Kernel((3, 3), (0, -1, 0, -1, 4, -1, 0, -1, 0), 1, 128))
    if min(gray.size) >= 5:
        edges = edges.crop((1, 1, gray.width - 1, gray.height - 1))
    if ImageStat.Stat(edges).stddev[0] < 5.0:
        warnings.append("可分辨的边缘和花纹较少。请对焦后补拍脸部或侧身。")
    return warnings


def _normalise(bins, mass):
    if mass <= 0:
        return [0.0] * len(bins)
    return [round(n / mass, 6) for n in bins]


def _normalize_lighting(crop):
    """Mild illumination & white-balance stabilization so shadow/backlight still matches."""
    small = crop.resize((64, 64), Image.Resampling.LANCZOS).convert("RGB")
    if np is None:
        return Image.blend(small, ImageOps.autocontrast(small, cutoff=2), 0.75)
    arr = np.asarray(small, dtype=np.float32)
    # Mild Gray-World white balance (50% blend preserves true orange/black/white coats)
    ch_means = arr.mean(axis=(0, 1))
    avg = float(ch_means.mean())
    if avg > 10.0:
        gains = np.clip(avg / np.maximum(ch_means, 10.0), 0.78, 1.28)
        balanced = np.clip(arr * gains, 0, 255)
        arr = 0.5 * arr + 0.5 * balanced
    # Mild percentile contrast stretch (40% blend lifts backlit shadows)
    lo, hi = np.percentile(arr, [2, 98])
    if hi - lo > 20.0:
        stretched = np.clip((arr - lo) * (255.0 / (hi - lo)), 0, 255)
        arr = 0.25 * arr + 0.75 * stretched
    return Image.fromarray(arr.astype(np.uint8), mode="RGB")


def _appearance(crop):
    """Illumination-robust spatial pyramid HSV + rotation-invariant LBP + gradient HOG."""
    norm_crop = _normalize_lighting(crop)
    hsv = norm_crop.resize((48, 48), Image.Resampling.LANCZOS).convert("HSV")
    # 5 regions: global, top, bottom, left, right
    colours = [Counter(), Counter(), Counter(), Counter(), Counter()]
    data = hsv.tobytes()
    for i in range(48 * 48):
        hue, sat, value = data[3 * i : 3 * i + 3]
        x, y = i % 48, i // 48
        # Elliptical center weighting suppresses grass/pavement corners
        dx = (x - 23.5) / 22.0
        dy = (y - 23.5) / 22.0
        r2 = dx * dx + dy * dy
        if r2 > 1.15:
            continue
        weight = 3 if r2 <= 0.48 else 1
        if sat < 44 or value < 34:
            bucket = min(5, value * 6 // 256)
        else:
            hue_bin = ((hue * 12 + 128) // 256) % 12
            bucket = 6 + hue_bin * 3 + min(2, value * 3 // 256)
        colours[0][bucket] += weight
        colours[1 + (y >= 24)][bucket] += weight
        colours[3 + (x >= 24)][bucket] += weight
    vector = []
    for counts in colours:
        vector.extend(_normalise([counts[k] for k in range(HIST_SIZE)], sum(counts.values())))

    # Rotation-invariant uniform LBP on center-weighted 40x40 grayscale
    gray_img = norm_crop.resize((40, 40), Image.Resampling.LANCZOS).convert("L")
    gray = gray_img.tobytes()
    texture = [0] * LBP_SIZE
    offsets = (-41, -40, -39, 1, 41, 40, 39, -1)
    for y in range(1, 39):
        for x in range(1, 39):
            i = y * 40 + x
            ring = [gray[i + offset] > gray[i] + 2 for offset in offsets]
            changes = sum(ring[k] != ring[k - 1] for k in range(8))
            texture[sum(ring) if changes <= 2 else 9] += 1

    # 8-bin gradient orientation histogram (captures tabby stripes & fur edge geometry)
    hog = [0.0] * HOG_SIZE
    for y in range(1, 39):
        for x in range(1, 39):
            i = y * 40 + x
            gx = float(gray[i + 1]) - float(gray[i - 1])
            gy = float(gray[i + 40]) - float(gray[i - 40])
            mag = math.hypot(gx, gy)
            if mag < 6.0:
                continue
            angle = math.degrees(math.atan2(gy, gx)) % 180.0
            bin_idx = min(HOG_SIZE - 1, int(angle * HOG_SIZE / 180.0))
            hog[bin_idx] += mag
    return vector + _normalise(texture, sum(texture)) + _normalise(hog, sum(hog))


def analyze_crop(image, box):
    """Analyze one box. Input image must already be upright (EXIF applied)."""
    crop = image.crop(pixel_box(image, box)).convert("RGB")
    warnings = _quality(crop)
    usable = not warnings
    result = {
        "version": MODEL_VERSION,
        "usable": usable,
        "warnings": warnings,
        "features": [],
        "frontal_face": None,
    }
    if usable:
        from cat_face import has_frontal_face
        if encoder.VERSION:
            result["features"] = encoder.embed(crop)
        else:
            result["features"] = _appearance(crop)
            # Store horizontally flipped descriptor for cross-pose / mirror invariance
            result["flip_features"] = _appearance(ImageOps.mirror(crop))
        result["frontal_face"] = has_frontal_face(crop)
        if result["frontal_face"] is False:
            warnings.append("未检测到清晰正脸，若侧身花纹也不清楚，可以再补一张正脸照。")
    return result


def distance_to_similarity(distance, max_distance=DEFAULT_MAX_DISTANCE):
    """Convert raw descriptor distance to an honest, calibrated 0..1 similarity score."""
    if distance is None or not math.isfinite(distance):
        return 0.0
    if encoder.VERSION:
        # Calibrate ONNX spatial cosine distance so borderline matches (~0.24-0.28) show ~45%-55% instead of 76%
        ceiling = max(max_distance * 1.55, 0.42)
        return round(max(0.0, min(1.0, 1.0 - distance / ceiling)), 4)
    ceiling = max(max_distance * 1.45, 0.48)
    return round(max(0.0, min(1.0, 1.0 - distance / ceiling)), 4)


def _pairwise_distances(query_vec, valid_vecs):
    if np is not None and len(valid_vecs) >= 4:
        mat = np.asarray(valid_vecs, dtype=np.float64)
        q = np.asarray(query_vec, dtype=np.float64)
        if encoder.VERSION:
            return np.maximum(0.0, 1.0 - mat @ q).tolist()
        return (np.abs(mat - q) @ _L1_WEIGHTS).tolist()
    distances = []
    for b in valid_vecs:
        if encoder.VERSION:
            distances.append(max(0.0, 1.0 - sum(p * q for p, q in zip(query_vec, b))))
        else:
            distances.append(
                sum(
                    weight * 0.5 * sum(abs(query_vec[i] - b[i]) for i in range(start, end))
                    for start, end, weight in _HIST_GROUPS
                )
            )
    return distances


def rank_candidates(query, references, limit=3, max_distance=DEFAULT_MAX_DISTANCE, *, area="", cat_areas=None):
    """Rank unique identities by flip-invariant closest + multi-ref consensus; [] means abstain."""
    if limit <= 0 or not query.get("usable") or query.get("version") != MODEL_VERSION:
        return []
    a = query.get("features", [])
    if not a or (not encoder.VERSION and len(a) != FEATURE_SIZE):
        return []
    a_flip = query.get("flip_features") if not encoder.VERSION else None
    if a_flip and len(a_flip) != len(a):
        a_flip = None

    valid_meta = []
    valid_vecs = []
    for cat_id, reference in references:
        if not reference.get("usable") or reference.get("version") != MODEL_VERSION:
            continue
        b = reference.get("features", [])
        if len(b) != len(a):
            continue
        valid_meta.append((cat_id, reference.get("_reference_id")))
        valid_vecs.append(b)
    if not valid_vecs:
        return []

    distances = _pairwise_distances(a, valid_vecs)
    if a_flip:
        flip_distances = _pairwise_distances(a_flip, valid_vecs)
        distances = [min(d1, d2) for d1, d2 in zip(distances, flip_distances)]

    # Group per-cat distances for multi-reference consensus
    per_cat = {}
    for (cat_id, ref_id), distance in zip(valid_meta, distances):
        per_cat.setdefault(cat_id, []).append((distance, ref_id))

    area_clean = area.strip() if area else ""
    scored = {}
    reference_ids = {}
    for cat_id, items in per_cat.items():
        items.sort(key=lambda pair: (pair[0], str(pair[1])))
        best_dist, best_ref = items[0]
        if best_dist > max_distance:
            continue
        # Multi-reference consensus: stabilize when a cat has >=2 reviewed photos
        if len(items) >= 2 and items[1][0] <= max_distance * 1.25:
            eff_dist = 0.85 * best_dist + 0.15 * items[1][0]
        else:
            eff_dist = best_dist
        # Subtle campus-area tie-breaker (-0.015) when location matches
        if area_clean and cat_areas and cat_areas.get(cat_id) == area_clean:
            eff_dist = max(0.0, eff_dist - 0.015)
        scored[cat_id] = eff_dist
        reference_ids[cat_id] = best_ref

    ordered = sorted(scored, key=lambda identity: (scored[identity], str(identity)))
    result = []
    for cat_id in ordered[:limit]:
        dist = round(scored[cat_id], 5)
        candidate = {
            "cat_id": cat_id,
            "distance": dist,
            "similarity": distance_to_similarity(dist, max_distance),
        }
        if reference_ids[cat_id] is not None:
            candidate["reference_id"] = reference_ids[cat_id]
        result.append(candidate)
    return result


def assess_db_match(
    candidates,
    reference_count,
    area="",
    *,
    usable=True,
    vlm_compare=None,
    not_cat=False,
    not_cat_reason="",
    max_distance=DEFAULT_MAX_DISTANCE,
):
    """Describe candidate evidence; combines local retrieval, SIFT local landmarks, anti-human gate, and optional VLM verdict."""
    nearest = candidates[0] if candidates else {}
    result = {
        "recorded": None,
        "top_cat_id": nearest.get("id"),
        "top_cat_name": nearest.get("name", ""),
        "area_matched": bool(area and area.strip() == nearest.get("area")),
    }
    if not_cat:
        return dict(
            result,
            top_cat_id=None,
            top_cat_name="",
            area_matched=False,
            status="not_a_cat",
            summary=not_cat_reason or "画面识别为人像或非猫咪目标，已拦截花色与图鉴比对。",
        )
    if not usable:
        return dict(result, status="poor_quality", summary="照片的辨认特征不足，请补拍清晰的脸部或侧身。")
    if not reference_count:
        return dict(result, status="no_reference", summary="图鉴尚无可用于比对的参考照。")
    if not nearest:
        return dict(result, status="no_candidate", summary="目前没有找到外观足够接近的参考照，可能是尚未建档的新猫。")

    # If VLM pairwise verification gave a clear verdict, surface it concisely
    if isinstance(vlm_compare, dict) and vlm_compare.get("source") == "vlm":
        verdict = vlm_compare.get("verdict")
        reason = vlm_compare.get("reason") or ""
        conf = float(vlm_compare.get("confidence", 0.0) or 0.0)
        best_idx = vlm_compare.get("best_candidate_index")
        if verdict == "same_cat" and conf >= 0.65 and best_idx and nearest.get("name"):
            return dict(
                result,
                status="possible_match",
                summary=f"视觉复核高度疑似「{nearest['name']}」：{reason}" if reason else f"视觉复核高度疑似「{nearest['name']}」，请核对脸部与花纹。",
            )
        if verdict == "different_cat" and conf >= 0.65:
            return dict(
                result,
                top_cat_id=None,
                top_cat_name="",
                area_matched=False,
                status="no_candidate",
                summary=f"视觉复核认为与候选猫存在差异：{reason}" if reason else "视觉复核认为可能不是库内候选猫，建议提交目击建档。",
            )

    if len(candidates) > 1 and candidates[1]["distance"] - nearest["distance"] < 0.025:
        return dict(result, status="ambiguous", summary="有多只外观接近的候选，请对照脸部、四肢和尾巴的花纹。")
    if nearest.get("local_inliers", 0) >= 18:
        return dict(
            result,
            status="possible_match",
            summary=f"局部花纹几何命中「{nearest['name']}」（{nearest['local_inliers']} 处一致特征点），可先对照历史照片核实。",
        )
    # Guard against over-confident cross-cat matching when distance is near the outer margin without local SIFT inliers
    dist = float(nearest.get("distance", 0.0))
    weak_cutoff = max_distance * (0.72 if encoder.VERSION else 0.78)
    if dist > weak_cutoff and nearest.get("local_inliers", 0) < 12:
        return dict(
            result,
            status="weak_candidate",
            summary=f"仅整体毛色与「{nearest['name']}」有部分接近，局部特征吻合度偏弱（同花色不同猫易相似），请重点核对耳尖、鼻梁与四肢花纹。",
        )
    return dict(
        result,
        status="possible_match",
        summary=f"可先对照「{nearest['name']}」的历史照片，再核对脸部或侧身特征。",
    )
