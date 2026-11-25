"""Lightweight YOLOv8n ONNX multi-cat detector (COCO class 15 = cat).

Set CAMPUSCATS_DETECTOR=/srv/campuscats/models/yolov8n.onnx to enable
automatic multi-cat bounding box detection and background-tight cropping.
"""

import os
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image

MODEL_PATH = os.getenv("CAMPUSCATS_DETECTOR", "").strip()
CAT_CLASS_ID = 15
_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _engine():
    if not MODEL_PATH or not Path(MODEL_PATH).is_file():
        return None
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    session = ort.InferenceSession(MODEL_PATH, sess_options=opts, providers=["CPUExecutionProvider"])
    in_name = session.get_inputs()[0].name
    out_name = session.get_outputs()[0].name
    return session, in_name, out_name


def is_enabled():
    return bool(MODEL_PATH and Path(MODEL_PATH).is_file())


def detect_cats(image, *, conf_thresh=0.28, iou_thresh=0.45, max_boxes=8):
    """Detect all cats in a PIL RGB image, returning normalized [x, y, w, h] boxes."""
    eng = _engine()
    if eng is None:
        return []
    import numpy as np

    session, in_name, out_name = eng
    rgb = image.convert("RGB")
    w, h = rgb.size
    if min(w, h) < 32:
        return []

    scale = 640.0 / max(w, h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = rgb.resize((nw, nh), Image.Resampling.BILINEAR)
    pad_x, pad_y = (640 - nw) // 2, (640 - nh) // 2
    canvas = Image.new("RGB", (640, 640), (114, 114, 114))
    canvas.paste(resized, (pad_x, pad_y))
    arr = np.asarray(canvas, dtype=np.float32) / 255.0
    inp = np.ascontiguousarray(arr.transpose(2, 0, 1)[None])

    with _LOCK:
        out = np.asarray(session.run([out_name], {in_name: inp})[0])[0]

    if out.ndim != 2:
        return []
    if out.shape[0] < out.shape[1]:
        out = out.T  # [8400, 84]
    if out.shape[1] <= 4 + CAT_CLASS_ID:
        return []

    cat_scores = out[:, 4 + CAT_CLASS_ID]
    mask = cat_scores >= conf_thresh
    if not np.any(mask):
        return []

    sel = out[mask]
    scores = cat_scores[mask]
    cx, cy, bw, bh = sel[:, 0], sel[:, 1], sel[:, 2], sel[:, 3]
    x1 = np.clip((cx - bw / 2.0 - pad_x) / scale / w, 0.0, 1.0)
    y1 = np.clip((cy - bh / 2.0 - pad_y) / scale / h, 0.0, 1.0)
    x2 = np.clip((cx + bw / 2.0 - pad_x) / scale / w, 0.0, 1.0)
    y2 = np.clip((cy + bh / 2.0 - pad_y) / scale / h, 0.0, 1.0)
    boxes = np.stack([x1, y1, x2, y2], axis=1)

    order = np.argsort(-scores)
    keep = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1 or len(keep) >= max_boxes:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_r = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
        iou = inter / (area_i + area_r - inter + 1e-6)
        order = rest[iou <= iou_thresh]

    detections = []
    for idx in keep:
        bx1, by1, bx2, by2 = boxes[idx]
        bw_n, bh_n = float(bx2 - bx1), float(by2 - by1)
        if bw_n >= 0.04 and bh_n >= 0.04:
            detections.append({
                "box": [round(float(bx1), 4), round(float(by1), 4), round(bw_n, 4), round(bh_n, 4)],
                "score": round(float(scores[idx]), 3),
            })
    return detections
