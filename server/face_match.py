"""Verify whether two detected cat faces or body crops share localized markings.

v0.4.4-SYLU upgrades:
- CLAHE local contrast enhancement before SIFT (boosts dark/tabby/tuxedo fur keypoints)
- Multi-angle Haar frontal cat face detection (0°, -12°, +12° head tilt tolerance)
- Full-body/coat SIFT + RANSAC reranking for side-profile & back-view cats
- Keeps strict two-day frontal-face geometric threshold for automatic_match()
"""

from functools import lru_cache
from pathlib import Path
from threading import local

from PIL import Image

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

_thread = local()
_cascade = Path(__file__).with_name("models") / "haarcascade_frontalcatface.xml"
_size = 240
_body_size = 256


def _ensure_detectors():
    if not hasattr(_thread, "detector"):
        cv2.setNumThreads(1)
        _thread.detector = cv2.CascadeClassifier(str(_cascade))
        _thread.sift = cv2.SIFT_create(nfeatures=450, contrastThreshold=0.020)
        _thread.clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))


def _detect_single_face(gray_img):
    """Try upright first, then slight +-12 degree tilts for head-tilted campus cats."""
    for angle in (0, -12, 12):
        candidate = gray_img if angle == 0 else gray_img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
        boxes = _thread.detector.detectMultiScale(
            np.asarray(candidate), scaleFactor=1.10, minNeighbors=3, minSize=(50, 50),
        )
        if len(boxes) == 1:
            x, y, w, h = map(int, boxes[0])
            if w >= candidate.width * 0.25 and h >= candidate.height * 0.25:
                return candidate.crop((x, y, x + w, y + h))
    return None


def face_features(image):
    """Return CLAHE-enhanced SIFT landmarks within one large, frontal cat face."""
    if cv2 is None or min(image.size) < 120:
        return None
    _ensure_detectors()

    gray = image.convert("L")
    gray.thumbnail((900, 900), Image.Resampling.LANCZOS)
    face_crop = _detect_single_face(gray)
    if face_crop is None:
        return None
    face = face_crop.resize((_size, _size), Image.Resampling.LANCZOS)
    arr = _thread.clahe.apply(np.asarray(face))
    mask = np.zeros((_size, _size), dtype=np.uint8)
    # Keep matches within the face, away from the corners of the detector box.
    cv2.ellipse(mask, (120, 127), (86, 86), 0, 0, 360, 255, -1)
    points, descriptors = _thread.sift.detectAndCompute(arr, mask)
    if descriptors is None or len(points) < 24:
        return None
    xy = np.float32([point.pt for point in points])
    return xy, descriptors


def body_features(image):
    """Return foreground-masked CLAHE+SIFT landmarks across the whole cat crop (side/back views)."""
    if cv2 is None or min(image.size) < 96:
        return None
    _ensure_detectors()
    gray = image.convert("L").resize((_body_size, _body_size), Image.Resampling.LANCZOS)
    arr = _thread.clahe.apply(np.asarray(gray))
    mask = np.zeros((_body_size, _body_size), dtype=np.uint8)
    cv2.ellipse(mask, (_body_size // 2, _body_size // 2), (int(_body_size * 0.42), int(_body_size * 0.42)), 0, 0, 360, 255, -1)
    points, descriptors = _thread.sift.detectAndCompute(arr, mask)
    if descriptors is None or len(points) < 20:
        return None
    xy = np.float32([point.pt for point in points])
    return xy, descriptors


@lru_cache(maxsize=64)
def reference_features(path, box):
    from vision import pixel_box

    with Image.open(path) as image:
        return face_features(image.crop(pixel_box(image, box)))


@lru_cache(maxsize=64)
def reference_body_features(path, box):
    from vision import pixel_box

    with Image.open(path) as image:
        return body_features(image.crop(pixel_box(image, box)))


def _match_inliers(first, second, *, ratio=0.72, min_pairs=18, min_ratio=0.72, min_span=64, min_area=4200, max_shift=35, max_angle=30, center_pt=120.0):
    if first is None or second is None:
        return 0
    left, left_desc = first
    right, right_desc = second
    matcher = cv2.BFMatcher(cv2.NORM_L2)

    def distinctive_pairs(source, target):
        return {m.queryIdx: m.trainIdx for m, n in matcher.knnMatch(source, target, k=2)
                if m.distance < ratio * n.distance}

    backward = distinctive_pairs(right_desc, left_desc)
    pairs = [(a, b) for a, b in distinctive_pairs(left_desc, right_desc).items() if backward.get(b) == a]
    if len(pairs) < min_pairs:
        return 0
    src = left[[a for a, _ in pairs]]
    dst = right[[b for _, b in pairs]]
    transform, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    if transform is None:
        return 0
    scale = np.hypot(transform[0, 0], transform[1, 0])
    angle = abs(np.degrees(np.arctan2(transform[1, 0], transform[0, 0])))
    center = transform[:, :2] @ np.array([center_pt, center_pt]) + transform[:, 2]
    if not 0.65 <= scale <= 1.50 or angle > max_angle or np.linalg.norm(center - center_pt) > max_shift:
        return 0
    good_mask = mask.ravel().astype(bool)
    points = src[good_mask]
    count = len(points)
    if count < min_pairs or count / len(pairs) < min_ratio:
        return 0
    if min(np.ptp(points, axis=0)) < min_span or cv2.contourArea(cv2.convexHull(points)) < min_area:
        return 0
    return count


def correspondence_score(first, second):
    """Count geometrically consistent matches spread across the detected frontal face."""
    return _match_inliers(first, second)


def body_correspondence_score(first, second):
    """Slightly more permissive RANSAC check for side-profile / body coat markings (ranking only)."""
    return _match_inliers(
        first, second,
        ratio=0.75, min_pairs=12, min_ratio=0.55,
        min_span=40, min_area=2000, max_shift=58, max_angle=42, center_pt=_body_size / 2.0,
    )


def rerank_with_local_features(query_crop, candidates, references, media_dir):
    """Boost candidate similarity using frontal-face and body-coat SIFT+RANSAC local markings."""
    if cv2 is None or not candidates or media_dir is None:
        return candidates
    q_face = face_features(query_crop)
    q_body = body_features(query_crop)
    if q_face is None and q_body is None:
        return candidates

    ref_by_id = {ref.get("_reference_id"): ref for _, ref in references if ref.get("_reference_id") is not None}
    updated = []
    for cand in candidates:
        item = dict(cand)
        ref = ref_by_id.get(item.get("reference_id"))
        best_inliers = 0
        if ref and ref.get("frame") and ref.get("box"):
            ref_path = Path(media_dir) / ref["frame"]
            if ref_path.is_file():
                try:
                    if q_face is not None:
                        r_face = reference_features(ref_path, tuple(ref["box"]))
                        best_inliers = max(best_inliers, int(round(correspondence_score(q_face, r_face) * 1.4)))
                    if q_body is not None:
                        r_body = reference_body_features(ref_path, tuple(ref["box"]))
                        best_inliers = max(best_inliers, body_correspondence_score(q_body, r_body))
                except OSError:
                    pass
        item["local_inliers"] = best_inliers
        if best_inliers >= 12:
            boost = min(0.22, (best_inliers - 10) * 0.008)
            item["similarity"] = round(min(0.99, float(item.get("similarity", 0.0)) + boost), 4)
            item["distance"] = round(max(0.0, float(item.get("distance", 0.3)) - boost * 0.45), 5)
        updated.append(item)

    updated.sort(key=lambda c: (-float(c.get("similarity", 0.0)), float(c.get("distance", 1.0))))
    return updated


def automatic_match(features, ranked, references, media_dir):
    """Require strong frontal-face landmark agreement on two independently reviewed dates."""
    if features is None or len(ranked) > 6:
        return None
    ranked = {candidate["cat_id"] for candidate in ranked}
    hits = {}
    for cat_id, reference in references:
        if cat_id not in ranked or not reference["day"]:
            continue
        try:
            landmarks = reference_features(media_dir / reference["frame"], reference["box"])
        except OSError:
            continue
        score = correspondence_score(features, landmarks)
        if score >= 18:
            hits.setdefault(cat_id, []).append((score, reference))
    if len(hits) != 1:
        return None
    cat_id, matches = next(iter(hits.items()))
    matches.sort(key=lambda match: (-match[0], match[1]["_reference_id"]))
    strong = [reference for score, reference in matches if score >= 26]
    if not strong:
        return None
    first = strong[0]
    second = next((ref for ref in strong if ref["day"] and ref["day"] != first["day"]), None)
    if second is None:
        return None
    return cat_id, first["_reference_id"], second["_reference_id"]
