"""Photo quality checks, candidate retrieval, and DB-presence assessment.

Descriptors compare colour, markings and texture (or ONNX embeddings when
CAMPUSCATS_ENCODER is configured). Automatic identity still requires separate
landmark verification in face_match.py.
"""

import math
import os
from collections import Counter

from PIL import Image, ImageFilter, ImageStat
import encoder

MODEL_VERSION = encoder.VERSION or "coat-texture-1"
# Provisional distance for showing suggestions. Validate on local photographs.
DEFAULT_MAX_DISTANCE = float(os.getenv("CAMPUSCATS_DISTANCE", "0.22" if encoder.VERSION else "0.31"))
if not math.isfinite(DEFAULT_MAX_DISTANCE) or not 0 <= DEFAULT_MAX_DISTANCE <= 1:
    raise ValueError("CAMPUSCATS_DISTANCE 取值范围为 0 至 1。")
HIST_SIZE = 42
FEATURE_SIZE = HIST_SIZE * 3 + 10


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
    edges = gray.filter(ImageFilter.Kernel((3, 3), (0,-1,0,-1,4,-1,0,-1,0), 1, 128))
    if min(gray.size) >= 5:
        edges = edges.crop((1, 1, gray.width - 1, gray.height - 1))
    if ImageStat.Stat(edges).stddev[0] < 5.0:
        warnings.append("可分辨的边缘和花纹较少。请对焦后补拍脸部或侧身。")
    return warnings


def _normalise(bins, mass):
    return [round(n / mass, 6) for n in bins]


def _appearance(crop):
    # Prefer the centre of the user-selected box to the background around it.
    hsv = crop.resize((48, 48), Image.Resampling.LANCZOS).convert("HSV")
    colours = [Counter(), Counter(), Counter()]
    data = hsv.tobytes()
    for i in range(48 * 48):
        hue, sat, value = data[3*i:3*i+3]
        x, y = i % 48, i // 48
        weight = 2 if 8 <= x < 40 and 8 <= y < 40 else 1
        # Separate achromatic brightness from coloured fur; scale hue circularly.
        if sat < 46 or value < 35:
            bucket = min(5, value * 6 // 256)
        else:
            hue_bin = ((hue * 12 + 128) // 256) % 12
            bucket = 6 + hue_bin * 3 + min(2, value * 3 // 256)
        colours[0][bucket] += weight
        colours[1 + (y >= 24)][bucket] += weight
    vector = []
    for counts in colours:
        vector.extend(_normalise([counts[k] for k in range(HIST_SIZE)], sum(counts.values())))

    # Rotation-invariant uniform local binary patterns capture fine markings.
    gray = crop.resize((40, 40), Image.Resampling.LANCZOS).convert("L").tobytes()
    texture = [0] * 10
    offsets = (-41, -40, -39, 1, 41, 40, 39, -1)
    for y in range(1, 39):
        for x in range(1, 39):
            i = y * 40 + x
            ring = [gray[i + offset] > gray[i] + 2 for offset in offsets]
            changes = sum(ring[k] != ring[k-1] for k in range(8))
            texture[sum(ring) if changes <= 2 else 9] += 1
    return vector + _normalise(texture, sum(texture))


def analyze_crop(image, box):
    """Analyze one box. Input image must already be upright (EXIF applied)."""
    crop = image.crop(pixel_box(image, box)).convert("RGB")
    warnings = _quality(crop)
    usable = not warnings
    result = {"version": MODEL_VERSION, "usable": usable, "warnings": warnings,
              "features": [], "frontal_face": None}
    if usable:
        from cat_face import has_frontal_face
        result["features"] = encoder.embed(crop) if encoder.VERSION else _appearance(crop)
        result["frontal_face"] = has_frontal_face(crop)
        if result["frontal_face"] is False:
            warnings.append("未检测到清晰正脸，若侧身花纹也不清楚，可以再补一张正脸照。")
    return result


def distance_to_similarity(distance, max_distance=DEFAULT_MAX_DISTANCE):
    """Convert raw descriptor distance to a user-friendly 0..1 similarity score."""
    if distance is None or not math.isfinite(distance):
        return 0.0
    if encoder.VERSION:
        # Cosine distance in [0, 2]; map [0, max_distance*1.8] cleanly to [1, 0]
        return round(max(0.0, min(1.0, 1.0 - distance)), 4)
    ceiling = max(max_distance * 1.45, 0.45)
    return round(max(0.0, min(1.0, 1.0 - distance / ceiling)), 4)


def rank_candidates(query, references, limit=3, max_distance=DEFAULT_MAX_DISTANCE):
    """Rank unique identities by their closest reviewed photo; [] means abstain."""
    if limit <= 0 or not query.get("usable") or query.get("version") != MODEL_VERSION:
        return []
    a = query.get("features", [])
    if not a or (not encoder.VERSION and len(a) != FEATURE_SIZE):
        return []
    best = {}
    reference_ids = {}
    for cat_id, reference in references:
        if not reference.get("usable") or reference.get("version") != MODEL_VERSION:
            continue
        b = reference.get("features", [])
        if len(b) != len(a):
            continue
        if encoder.VERSION:
            distance = max(0.0, 1 - sum(p*q for p, q in zip(a, b)))
        else:
            groups = ((0, HIST_SIZE, .52), (HIST_SIZE, 2*HIST_SIZE, .13),
                      (2*HIST_SIZE, 3*HIST_SIZE, .13), (3*HIST_SIZE, FEATURE_SIZE, .22))
            distance = sum(weight * .5 * sum(abs(a[i] - b[i]) for i in range(start, end))
                           for start, end, weight in groups)
        if distance <= max_distance and distance < best.get(cat_id, math.inf):
            best[cat_id] = distance
            reference_ids[cat_id] = reference.get("_reference_id")
    ordered = sorted(best, key=lambda identity: (best[identity], str(identity)))
    result = []
    for cat_id in ordered[:limit]:
        dist = round(best[cat_id], 5)
        candidate = {
            "cat_id": cat_id,
            "distance": dist,
            "similarity": distance_to_similarity(dist, max_distance),
        }
        if reference_ids[cat_id] is not None:
            candidate["reference_id"] = reference_ids[cat_id]
        result.append(candidate)
    return result


def assess_db_match(candidates, reference_count, area="", *, usable=True):
    """Describe candidate evidence; only the independent archiving step assigns identity."""
    nearest = candidates[0] if candidates else {}
    result = {"recorded": None, "top_cat_id": nearest.get("id"), "top_cat_name": nearest.get("name", ""),
              "area_matched": bool(area and area.strip() == nearest.get("area"))}
    if not usable:
        return dict(result, status="poor_quality", summary="照片的辨认特征不足，请补拍清晰的脸部或侧身。")
    if not reference_count:
        return dict(result, status="no_reference", summary="图鉴尚无可用于比对的参考照。")
    if not nearest:
        return dict(result, status="no_candidate", summary="目前没有找到外观接近的参考照，可提交目击后继续辨认。")
    if len(candidates) > 1 and candidates[1]["distance"] - nearest["distance"] < 0.03:
        return dict(result, status="ambiguous", summary="有多只外观接近的候选，请对照脸部、四肢和尾巴的花纹。")
    return dict(result, status="possible_match",
                summary=f"可先对照「{nearest['name']}」的历史照片，再核对脸部或侧身特征。")
