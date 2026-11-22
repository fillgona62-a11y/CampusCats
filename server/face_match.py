"""Verify whether two detected cat faces share localized markings."""

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


def face_features(image):
    """Return landmarks within one large, frontal cat face."""
    if cv2 is None or min(image.size) < 120:
        return None
    if not hasattr(_thread, "detector"):
        cv2.setNumThreads(1)
        _thread.detector = cv2.CascadeClassifier(str(_cascade))
        _thread.sift = cv2.SIFT_create(nfeatures=420, contrastThreshold=0.023)

    gray = image.convert("L")
    gray.thumbnail((900, 900), Image.Resampling.LANCZOS)
    boxes = _thread.detector.detectMultiScale(
        np.asarray(gray), scaleFactor=1.10, minNeighbors=3, minSize=(50, 50),
    )
    if len(boxes) != 1:
        return None
    x, y, w, h = map(int, boxes[0])
    if w < gray.width * .26 or h < gray.height * .26:
        return None
    face = gray.crop((x, y, x + w, y + h)).resize((_size, _size), Image.Resampling.LANCZOS)
    mask = np.zeros((_size, _size), dtype=np.uint8)
    # Keep matches within the face, away from the corners of the detector box.
    cv2.ellipse(mask, (120, 127), (86, 86), 0, 0, 360, 255, -1)
    points, descriptors = _thread.sift.detectAndCompute(np.asarray(face), mask)
    if descriptors is None or len(points) < 24:
        return None
    xy = np.float32([point.pt for point in points])
    return xy, descriptors


@lru_cache(maxsize=64)
def reference_features(path, box):
    from vision import pixel_box

    with Image.open(path) as image:
        return face_features(image.crop(pixel_box(image, box)))


def correspondence_score(first, second):
    """Count geometrically consistent matches spread across the detected face."""
    if first is None or second is None:
        return 0
    left, left_desc = first
    right, right_desc = second
    matcher = cv2.BFMatcher(cv2.NORM_L2)

    def distinctive_pairs(source, target):
        return {m.queryIdx: m.trainIdx for m, n in matcher.knnMatch(source, target, k=2)
                if m.distance < .72 * n.distance}

    backward = distinctive_pairs(right_desc, left_desc)
    pairs = [(a, b) for a, b in distinctive_pairs(left_desc, right_desc).items() if backward.get(b) == a]
    if len(pairs) < 18:
        return 0
    src = left[[a for a, _ in pairs]]
    dst = right[[b for _, b in pairs]]
    transform, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.5)
    if transform is None:
        return 0
    scale = np.hypot(transform[0, 0], transform[1, 0])
    angle = abs(np.degrees(np.arctan2(transform[1, 0], transform[0, 0])))
    center = transform[:, :2] @ np.array([120., 120.]) + transform[:, 2]
    if not .70 <= scale <= 1.42 or angle > 30 or np.linalg.norm(center - 120) > 35:
        return 0
    good_mask = mask.ravel().astype(bool)
    points = src[good_mask]
    count = len(points)
    if count < 18 or count / len(pairs) < .72:
        return 0
    if min(np.ptp(points, axis=0)) < 64 or cv2.contourArea(cv2.convexHull(points)) < 4200:
        return 0
    return count


def automatic_match(features, ranked, references, media_dir):
    """Require strong landmark agreement on two independently reviewed dates."""
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
