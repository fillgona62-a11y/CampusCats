"""Frontal-face photo hint using Joseph Howse's OpenCV Haar cascade.

Model and redistribution terms are in models/haarcascade_frontalcatface.xml.
The NumPy path evaluates the upright 24-pixel stump cascade at several scales.
This is only a photo hint; profiles and bodies can still identify a cat.
"""

import math
from functools import lru_cache
from pathlib import Path
from threading import local
from xml.etree import ElementTree

from PIL import Image, ImageOps

try:
    import numpy as np
except ImportError:
    np = None
try:
    import cv2
except ImportError:
    cv2 = None

MODEL_FILE = Path(__file__).with_name("models") / "haarcascade_frontalcatface.xml"
_PER_THREAD = local()


@lru_cache(maxsize=1)
def _stages():
    cascade = ElementTree.parse(MODEL_FILE).getroot().find("cascade")
    rectangles = []
    for feature in cascade.find("features"):
        rects = []
        for element in feature.find("rects"):
            x, y, width, height, weight = (int(float(n)) for n in element.text.split())
            rects.append((x, y, width, height, weight))
        rectangles.append(rects)
    stages = []
    for stage in cascade.find("stages"):
        rules = []
        for rule in stage.find("weakClassifiers"):
            left, right, feature_id, threshold = rule.findtext("internalNodes").split()
            if (left, right) != ("0", "-1"):
                raise ValueError("Unsupported cat-face cascade")
            leaves = list(map(float, rule.findtext("leafValues").split()))
            rules.append((rectangles[int(feature_id)], float(threshold), *leaves))
        stages.append((float(stage.findtext("stageThreshold")), rules))
    return stages


def _integral(pixels):
    return np.pad(pixels.cumsum(axis=0).cumsum(axis=1), ((1, 0), (1, 0)))


def _sum(integral, x, y, width, height):
    return (integral[y+height, x+width] - integral[y+height, x]
            - integral[y, x+width] + integral[y, x])


def _scan(image):
    pixels = np.asarray(image, dtype=np.int64)
    summed = _integral(pixels)
    squared = _integral(pixels * pixels)
    yy, xx = np.mgrid[0:image.height-23:2, 0:image.width-23:2]
    x, y = xx.ravel(), yy.ravel()
    # Standard deviation of the inner 22x22 patch, multiplied by its area.
    norm = np.sqrt(np.maximum(0, 484 * _sum(squared, x+1, y+1, 22, 22)
                              - _sum(summed, x+1, y+1, 22, 22)**2))
    keep = norm > 4840
    x, y, norm = x[keep], y[keep], norm[keep]
    for minimum, rules in _stages():
        if len(x) == 0:
            break
        votes = np.zeros(len(x))
        for rects, threshold, left, right in rules:
            response = np.zeros(len(x), dtype=np.int64)
            for dx, dy, width, height, weight in rects:
                response += weight * _sum(summed, x+dx, y+dy, width, height)
            votes += np.where(response < threshold * norm, left, right)
        keep = votes >= minimum - 1e-5
        x, y, norm = x[keep], y[keep], norm[keep]
    return zip(x.tolist(), y.tolist())


def has_frontal_face(crop):
    """Return True/False after a scan, or None if NumPy is unavailable."""
    if np is None:
        return None
    gray = crop.convert("L")
    gray.thumbnail((144, 144), Image.Resampling.BILINEAR)
    if min(gray.size) < 24:
        return False
    gray = ImageOps.equalize(gray)
    if cv2 is not None:
        if not hasattr(_PER_THREAD, "cascade"):
            _PER_THREAD.cascade = cv2.CascadeClassifier(str(MODEL_FILE))
        rects = _PER_THREAD.cascade.detectMultiScale(np.asarray(gray), scaleFactor=1.2, minNeighbors=2)
        return len(rects) > 0
    previous = []
    scale = 1.0
    while round(min(gray.size) / scale) >= 24:
        level = gray.resize((round(gray.width / scale), round(gray.height / scale)),
                            Image.Resampling.BILINEAR)
        for x, y in _scan(level):
            cx, cy = (x + 12) * scale, (y + 12) * scale
            for px, py, ps in previous:
                if scale <= 1.55 * ps and math.hypot(cx - px, cy - py) < 5 * ps:
                    return True
            previous.append((cx, cy, scale))
        scale *= 1.25
    return False
