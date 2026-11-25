"""Multi-cat ONNX detector with 80-class anti-human/anti-dog gate & Gaussian Soft-NMS.

Set CAMPUSCATS_DETECTOR=/srv/campuscats/models/yolov8s.onnx (or yolov8n.onnx) to enable:
1. Multi-cat & huddled-kitten bounding box detection (Gaussian Soft-NMS + high-res tiling).
2. Strict 80-class COCO comparison so humans (class 0) and dogs (class 16) are never boxed as cats (class 15).
3. Box-level subject verification (`verify_box_is_cat`) combining YOLOv8 + optional local CLIP species gate.
"""

import os
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image

import clip_classifier

PERSON_CLASS_ID = 0
BIRD_CLASS_ID = 14
CAT_CLASS_ID = 15
DOG_CLASS_ID = 16
BEAR_CLASS_ID = 21
TEDDY_CLASS_ID = 77
_LOCK = threading.Lock()


def _discover_model_path():
    explicit = os.getenv("CAMPUSCATS_DETECTOR", "").strip()
    if explicit:
        return explicit
    enc = os.getenv("CAMPUSCATS_ENCODER", "").split(",")[0].strip()
    if enc:
        parent = Path(enc).resolve().parent
        for name in ("yolov8s.onnx", "yolov8n.onnx"):
            cand = parent / name
            if cand.is_file():
                return str(cand)
    return ""


MODEL_PATH = _discover_model_path()


@lru_cache(maxsize=1)
def _engine():
    path = MODEL_PATH or _discover_model_path()
    if not path or not Path(path).is_file():
        return None
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    session = ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
    in_name = session.get_inputs()[0].name
    out_name = session.get_outputs()[0].name
    return session, in_name, out_name


def is_enabled():
    path = MODEL_PATH or _discover_model_path()
    return bool(path and Path(path).is_file())


def _infer_raw_640(rgb_patch, np, session, in_name, out_name):
    w, h = rgb_patch.size
    scale = 640.0 / max(w, h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = rgb_patch.resize((nw, nh), Image.Resampling.BILINEAR)
    pad_x, pad_y = (640 - nw) // 2, (640 - nh) // 2
    canvas = Image.new("RGB", (640, 640), (114, 114, 114))
    canvas.paste(resized, (pad_x, pad_y))
    arr = np.asarray(canvas, dtype=np.float32) / 255.0
    inp = np.ascontiguousarray(arr.transpose(2, 0, 1)[None])
    with _LOCK:
        out = np.asarray(session.run([out_name], {in_name: inp})[0])[0]
    if out.ndim != 2:
        return None, scale, pad_x, pad_y
    if out.shape[0] < out.shape[1]:
        out = out.T  # [8400, 84]
    if out.shape[1] <= 4 + CAT_CLASS_ID:
        return None, scale, pad_x, pad_y
    return out, scale, pad_x, pad_y


def _extract_cat_anchors(out, w, h, scale, pad_x, pad_y, conf_thresh, np, offset_xy=(0.0, 0.0), tile_wh=(1.0, 1.0)):
    """Filter anchors where cat (15) beats person (0), dog (16), and all other COCO classes."""
    cls_scores = out[:, 4:]
    cat_scores = cls_scores[:, CAT_CLASS_ID]
    num_classes = cls_scores.shape[1]

    person_scores = cls_scores[:, PERSON_CLASS_ID] if num_classes > PERSON_CLASS_ID else 0.0
    dog_scores = cls_scores[:, DOG_CLASS_ID] if num_classes > DOG_CLASS_ID else 0.0
    if num_classes > 1:
        other_cols = [c for c in range(num_classes) if c != CAT_CLASS_ID]
        other_max = np.max(cls_scores[:, other_cols], axis=1)
    else:
        other_max = np.zeros_like(cat_scores)

    mask = (
        (cat_scores >= conf_thresh)
        & (cat_scores > person_scores * 1.25)
        & (person_scores < 0.45)
        & (cat_scores > dog_scores * 1.15)
        & (cat_scores >= other_max * 0.95)
    )
    if not np.any(mask):
        return np.empty((0, 4), dtype=np.float32), np.empty((0,), dtype=np.float32)

    sel = out[mask]
    scores = cat_scores[mask].astype(np.float32)
    cx, cy, bw, bh = sel[:, 0], sel[:, 1], sel[:, 2], sel[:, 3]
    ox, oy = offset_xy
    tw, th = tile_wh
    x1 = np.clip(ox + np.clip((cx - bw / 2.0 - pad_x) / scale / w, 0.0, 1.0) * tw, 0.0, 1.0)
    y1 = np.clip(oy + np.clip((cy - bh / 2.0 - pad_y) / scale / h, 0.0, 1.0) * th, 0.0, 1.0)
    x2 = np.clip(ox + np.clip((cx + bw / 2.0 - pad_x) / scale / w, 0.0, 1.0) * tw, 0.0, 1.0)
    y2 = np.clip(oy + np.clip((cy + bh / 2.0 - pad_y) / scale / h, 0.0, 1.0) * th, 0.0, 1.0)
    boxes = np.stack([x1, y1, x2, y2], axis=1).astype(np.float32)
    return boxes, scores


def _soft_nms(boxes, scores, *, conf_thresh=0.28, iou_hard=0.72, sigma=0.40, max_boxes=8, np=None):
    """Gaussian Soft-NMS preserves huddled/adjacent kittens while suppressing duplicate anchors on one cat."""
    if boxes.shape[0] == 0:
        return []
    work_boxes = boxes.copy()
    work_scores = scores.copy()
    active = np.arange(work_boxes.shape[0])
    picked = []

    while active.size > 0 and len(picked) < max_boxes:
        best_pos = int(np.argmax(work_scores[active]))
        best_idx = int(active[best_pos])
        best_score = float(work_scores[best_idx])
        if best_score < conf_thresh:
            break
        picked.append((work_boxes[best_idx], best_score))
        if active.size == 1:
            break
        rest = np.delete(active, best_pos)
        b = work_boxes[best_idx]
        r = work_boxes[rest]

        xx1 = np.maximum(b[0], r[:, 0])
        yy1 = np.maximum(b[1], r[:, 1])
        xx2 = np.minimum(b[2], r[:, 2])
        yy2 = np.minimum(b[3], r[:, 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area_b = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
        area_r = np.maximum(1e-6, (r[:, 2] - r[:, 0]) * (r[:, 3] - r[:, 1]))
        iou = inter / (area_b + area_r - inter + 1e-6)
        containment = inter / np.minimum(area_b, area_r)

        # Center distance check: concentric duplicate boxes on the same cat are suppressed harder
        bcx, bcy = 0.5 * (b[0] + b[2]), 0.5 * (b[1] + b[3])
        rcx, rcy = 0.5 * (r[:, 0] + r[:, 2]), 0.5 * (r[:, 1] + r[:, 3])
        diag = max(1e-4, ((b[2] - b[0]) ** 2 + (b[3] - b[1]) ** 2) ** 0.5)
        center_ratio = (((bcx - rcx) ** 2 + (bcy - rcy) ** 2) ** 0.5) / diag

        duplicate = (iou > iou_hard) | ((iou > 0.48) & (center_ratio < 0.22)) | (containment > 0.86)
        decay = np.where(duplicate, 0.0, np.where(iou > 0.30, np.exp(-(iou * iou) / sigma), 1.0))
        work_scores[rest] *= decay
        active = rest[work_scores[rest] >= conf_thresh]

    return picked


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

    out, scale, pad_x, pad_y = _infer_raw_640(rgb, np, session, in_name, out_name)
    if out is None:
        return []

    all_boxes, all_scores = _extract_cat_anchors(out, w, h, scale, pad_x, pad_y, conf_thresh, np)

    # Multi-scale high-res tile assist for wide/tall multi-cat or small-cat scenes
    small_or_empty = all_boxes.shape[0] == 0 or np.any(
        ((all_boxes[:, 2] - all_boxes[:, 0]) * (all_boxes[:, 3] - all_boxes[:, 1])) < 0.12
    )
    if max(w, h) >= 900 and small_or_empty:
        tiles = []
        if w >= h * 1.15:
            tiles = [(0.0, 0.0, 0.62, 1.0), (0.38, 0.0, 0.62, 1.0)]
        elif h > w * 1.15:
            tiles = [(0.0, 0.0, 1.0, 0.62), (0.0, 0.38, 1.0, 0.62)]
        else:
            tiles = [(0.12, 0.12, 0.76, 0.76)]
        extra_b, extra_s = [all_boxes], [all_scores]
        for tx, ty, tw, th in tiles:
            px1, py1 = int(round(tx * w)), int(round(ty * h))
            px2, py2 = int(round((tx + tw) * w)), int(round((ty + th) * h))
            sub = rgb.crop((px1, py1, px2, py2))
            if min(sub.size) < 64:
                continue
            t_out, t_scale, t_px, t_py = _infer_raw_640(sub, np, session, in_name, out_name)
            if t_out is None:
                continue
            tb, ts = _extract_cat_anchors(
                t_out, sub.width, sub.height, t_scale, t_px, t_py, max(conf_thresh, 0.30), np,
                offset_xy=(tx, ty), tile_wh=(tw, th),
            )
            if tb.shape[0]:
                extra_b.append(tb)
                extra_s.append(ts)
        all_boxes = np.concatenate(extra_b, axis=0)
        all_scores = np.concatenate(extra_s, axis=0)

    picked = _soft_nms(
        all_boxes, all_scores,
        conf_thresh=conf_thresh,
        iou_hard=max(0.65, min(0.80, iou_thresh + 0.25)),
        max_boxes=max_boxes,
        np=np,
    )

    detections = []
    for (bx1, by1, bx2, by2), sc in picked:
        bw_n, bh_n = float(bx2 - bx1), float(by2 - by1)
        if bw_n >= 0.03 and bh_n >= 0.03:
            detections.append({
                "box": [round(float(bx1), 4), round(float(by1), 4), round(bw_n, 4), round(bh_n, 4)],
                "score": round(float(sc), 3),
            })
    # Sort left-to-right, top-to-bottom for deterministic multi-cat numbering
    detections.sort(key=lambda d: (round(d["box"][1], 1), d["box"][0]))
    return detections


def inspect_image_subjects(image):
    """Detect cats AND check if non-cat subjects (person/dog) dominate the frame."""
    cats = detect_cats(image)
    person_score = 0.0
    dog_score = 0.0
    eng = _engine()
    if eng is not None:
        import numpy as np
        session, in_name, out_name = eng
        rgb = image.convert("RGB")
        if min(rgb.size) >= 32:
            out, _, _, _ = _infer_raw_640(rgb, np, session, in_name, out_name)
            if out is not None and out.shape[1] > 4 + DOG_CLASS_ID:
                person_score = round(float(np.max(out[:, 4 + PERSON_CLASS_ID])), 3)
                dog_score = round(float(np.max(out[:, 4 + DOG_CLASS_ID])), 3)

    clip_res = clip_classifier.inspect_species(image) if clip_classifier.is_enabled() else None
    non_cat = None
    if not cats:
        if person_score >= 0.42 or (clip_res and clip_res["dominant"] == "person" and not clip_res["is_cat"]):
            non_cat = "person"
        elif dog_score >= 0.42 or (clip_res and clip_res["dominant"] == "dog" and not clip_res["is_cat"]):
            non_cat = "dog"
        elif clip_res and not clip_res["is_cat"]:
            non_cat = "other"

    return {
        "cats": cats,
        "person_score": person_score,
        "dog_score": dog_score,
        "non_cat_type": non_cat,
        "clip_species": clip_res,
    }


def verify_box_is_cat(image, box):
    """Verify whether a user-supplied or full-frame box actually contains a cat.

    Returns {"checked": bool, "is_cat": bool, "non_cat_type": str|None, "reason": str}.
    Gracefully returns is_cat=True when neither ONNX detector nor CLIP is installed.
    """
    det_on = is_enabled()
    clip_on = clip_classifier.is_enabled()
    if not det_on and not clip_on:
        return {"checked": False, "is_cat": True, "non_cat_type": None, "reason": ""}

    rgb = image.convert("RGB")
    w, h = rgb.size
    x, y, bw, bh = map(float, box)
    pad = 0.06
    x1 = max(0, int(round(max(0.0, x - pad * bw) * w)))
    y1 = max(0, int(round(max(0.0, y - pad * bh) * h)))
    x2 = min(w, int(round(min(1.0, x + bw + pad * bw) * w)))
    y2 = min(h, int(round(min(1.0, y + bh + pad * bh) * h)))
    crop = rgb.crop((x1, y1, max(x1 + 1, x2), max(y1 + 1, y2)))

    clip_res = clip_classifier.inspect_species(crop) if clip_on else None
    if clip_res is not None and not clip_res["is_cat"]:
        dom = clip_res["dominant"]
        label = "人像" if dom == "person" else "犬类" if dom == "dog" else "非猫咪景物"
        return {
            "checked": True,
            "is_cat": False,
            "non_cat_type": dom,
            "reason": f"画面识别为{label}，未检测到猫咪特征。",
        }

    if det_on:
        import numpy as np
        eng = _engine()
        if eng is not None and min(crop.size) >= 32:
            session, in_name, out_name = eng
            out, _, _, _ = _infer_raw_640(crop, np, session, in_name, out_name)
            if out is not None and out.shape[1] > 4 + DOG_CLASS_ID:
                cat_max = float(np.max(out[:, 4 + CAT_CLASS_ID]))
                person_max = float(np.max(out[:, 4 + PERSON_CLASS_ID]))
                dog_max = float(np.max(out[:, 4 + DOG_CLASS_ID]))
                clip_confirms_cat = bool(clip_res and clip_res.get("cat_prob", 0.0) >= 0.58)
                if person_max >= 0.45 and cat_max < 0.25 and not clip_confirms_cat:
                    return {
                        "checked": True,
                        "is_cat": False,
                        "non_cat_type": "person",
                        "reason": "画面识别为人像且未检测到猫咪，已拦截误识别。",
                    }
                if dog_max >= 0.45 and cat_max < dog_max * 0.85 and not clip_confirms_cat:
                    return {
                        "checked": True,
                        "is_cat": False,
                        "non_cat_type": "dog",
                        "reason": "画面识别为犬类而非猫咪，已拦截误识别。",
                    }
                is_full_frame = bw >= 0.95 and bh >= 0.95
                if is_full_frame and cat_max < 0.20 and not clip_confirms_cat:
                    return {
                        "checked": True,
                        "is_cat": False,
                        "non_cat_type": "person" if person_max >= 0.30 else "other",
                        "reason": "未在画面中检测到猫咪（可能是人像、远景或遮挡过重）。",
                    }

    return {"checked": True, "is_cat": True, "non_cat_type": None, "reason": ""}
