"""CPU ONNX Re-ID encoder with Spatial Patch Pooling + CLS fusion & 3-view TTA (v0.6.0).

Upgrades over CLS-only ViT embedding:
- Extracts both global CLS token AND foreground-weighted spatial patch tokens
  (global foreground GeM + upper head/ear region + lower chest/body region) from
  3D ViT/DINOv2 outputs (`[1, 1+G*G, D]`), dramatically reducing false-positive
  cross-cat matches caused by semantic "catness" sharing in the CLS token alone.
- Supports single or comma-separated multi-model ONNX ensembles (`CAMPUSCATS_ENCODER`).
"""

import hashlib
import math
import os
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps

MODEL_SPEC = os.getenv("CAMPUSCATS_ENCODER", "").strip()
MODEL_PATHS = [p.strip() for p in MODEL_SPEC.split(",") if p.strip()]
MODEL_PATH = MODEL_PATHS[0] if MODEL_PATHS else ""
USE_TTA = os.getenv("CAMPUSCATS_ENCODER_TTA", "1").strip().lower() not in ("0", "false", "no")


def _sha256_multi(paths):
    digest = hashlib.sha256()
    for p in paths:
        with Path(p).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"|")
    return digest.hexdigest()[:24]


VERSION = (
    ("onnx-ensemble-spatial-tta-v6-" if len(MODEL_PATHS) > 1 else "onnx-spatial-tta-v6-")
    + _sha256_multi(MODEL_PATHS)
    if MODEL_PATHS
    else None
)
_LOCK = threading.Lock()


def _feature_output(names):
    if len(names) == 1:
        return names[0]
    # Prefer last_hidden_state when available so spatial patch tokens can be pooled alongside CLS
    for name in ("last_hidden_state", "image_embeds", "pooler_output"):
        if name in names:
            return name
    raise ValueError("请导出一个特征输出，或命名为 last_hidden_state、image_embeds、pooler_output。")


def _load_one_engine(path):
    try:
        import onnxruntime as ort
    except ImportError:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("启用 ONNX 特征模型需要安装 onnxruntime。") from exc
        net = cv2.dnn.readNetFromONNX(path)
        output = _feature_output(net.getUnconnectedOutLayersNames())

        def run(data):
            with _LOCK:
                net.setInput(data)
                return net.forward(output)

        return run, 224

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(path, sess_options=options, providers=["CPUExecutionProvider"])
    if len(session.get_inputs()) != 1:
        raise ValueError("请导出一个像素输入的独立 ONNX 文件。")
    inp = session.get_inputs()[0]
    name = inp.name
    shape = inp.shape
    side = 224
    if isinstance(shape, (list, tuple)) and len(shape) == 4 and isinstance(shape[2], int) and 128 <= shape[2] <= 518:
        side = int(shape[2])
    output = _feature_output([result.name for result in session.get_outputs()])
    def run_ort(data, _s=session, _o=output, _n=name):
        return _s.run([_o], {_n: data})[0]
    run_ort._input_side = side
    return run_ort, side


@lru_cache(maxsize=1)
def _engine():
    return _load_one_engine(MODEL_PATH)[0]


@lru_cache(maxsize=1)
def _engines():
    if len(MODEL_PATHS) <= 1:
        fn = _engine()
        return ((fn, getattr(fn, "_input_side", 224)),)
    return tuple(_load_one_engine(p) for p in MODEL_PATHS)


@lru_cache(maxsize=8)
def _spatial_weights(grid_side):
    import numpy as np

    coords = np.linspace(-1.0, 1.0, grid_side, dtype=np.float32)
    yy, xx = np.meshgrid(coords, coords, indexing="ij")
    r2 = xx * xx + yy * yy
    # Center-elliptical Gaussian suppresses background grass/floor corners
    fg = np.exp(-1.15 * r2).astype(np.float32)
    fg /= float(np.sum(fg)) + 1e-8
    mid = max(1, grid_side // 2)
    top = fg.copy()
    top[mid:, :] *= 0.15
    top /= float(np.sum(top)) + 1e-8
    bot = fg.copy()
    bot[:mid, :] *= 0.15
    bot /= float(np.sum(bot)) + 1e-8
    return fg.reshape(-1, 1), top.reshape(-1, 1), bot.reshape(-1, 1)


def _l2_norm(vec, np):
    norm = float(np.linalg.norm(vec))
    if not np.isfinite(norm) or norm < 1e-8:
        raise ValueError("图像编码器输出无效，请检查模型导出。")
    return vec / norm


def _extract_descriptor(output, np):
    if output.ndim == 2 and output.shape[0] == 1:
        return _l2_norm(output[0].astype(np.float32), np)
    if output.ndim != 3 or output.shape[0] != 1:
        raise ValueError("ONNX 特征输出应为 [1,D] 或 [1,N,D]，首个 token 为 CLS。")

    tokens = output[0].astype(np.float32)
    n_tok, dim = tokens.shape
    cls_vec = _l2_norm(tokens[0], np)

    # Check if remaining tokens (with 0 or 4 DINOv2 register tokens) form a square spatial patch grid
    grid_side = 0
    for reg in (0, 4):
        rem = n_tok - 1 - reg
        if rem >= 49:
            g = int(round(math.sqrt(rem)))
            if g * g == rem:
                grid_side = g
                patches = tokens[n_tok - rem :]
                break

    if grid_side == 0:
        return cls_vec

    # Normalize each patch token, then compute horizontally symmetric spatial pools
    p_norms = np.linalg.norm(patches, axis=1, keepdims=True)
    patches_unit = patches / np.maximum(p_norms, 1e-8)
    fg_w, top_w, bot_w = _spatial_weights(grid_side)

    # Signed power-mean (GeM-like p=2) sharpens localized markings (ear clip, blaze, stripes)
    signed_sq = np.sign(patches_unit) * (patches_unit * patches_unit)
    fg_gem = np.sum(signed_sq * fg_w, axis=0)
    fg_pool = _l2_norm(np.sign(fg_gem) * np.sqrt(np.abs(fg_gem) + 1e-8), np)
    top_pool = _l2_norm(np.sum(patches_unit * top_w, axis=0), np)
    bot_pool = _l2_norm(np.sum(patches_unit * bot_w, axis=0), np)

    # Combine CLS (0.48) + Foreground GeM (0.52) + Head/Ears (0.45) + Body/Chest (0.40)
    hybrid = np.concatenate(
        [0.48 * cls_vec, 0.52 * fg_pool, 0.45 * top_pool, 0.40 * bot_pool],
        axis=0,
    )
    return _l2_norm(hybrid, np)


def _preprocess(crop, side, np):
    w, h = crop.size
    scale = float(side) / max(w, h)
    nw = max(1, min(side, round(w * scale)))
    nh = max(1, min(side, round(h * scale)))
    resized = crop.resize((nw, nh), Image.Resampling.BICUBIC)
    mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
    canvas = np.broadcast_to(mean, (side, side, 3)).copy()
    top = (side - nh) // 2
    left = (side - nw) // 2
    canvas[top : top + nh, left : left + nw] = np.asarray(resized, dtype=np.float32) / 255.0
    pixels = (canvas - mean) / std
    return np.ascontiguousarray(pixels.transpose(2, 0, 1)[None])


def _run_model(run_fn, side, crop, np):
    def _single(im):
        output = np.asarray(run_fn(_preprocess(im, side, np)))
        vector = _extract_descriptor(output, np)
        if not 2 <= vector.size <= 16384:
            raise ValueError("图像编码器输出维度超出预期范围，请检查模型导出。")
        return vector

    vec = _single(crop)
    if USE_TTA:
        views = [vec, _single(ImageOps.mirror(crop))]
        w, h = crop.size
        if min(w, h) >= 96:
            nw, nh = int(w * 0.78), int(h * 0.78)
            left, top = (w - nw) // 2, (h - nh) // 2
            views.append(_single(crop.crop((left, top, left + nw, top + nh))))
        combined = sum(views)
        norm = np.linalg.norm(combined)
        if np.isfinite(norm) and norm >= 1e-8:
            vec = combined / norm
    return vec


def embed(crop):
    import numpy as np

    parts = [_run_model(run_fn, side, crop, np) for run_fn, side in _engines()]
    if len(parts) == 1:
        fused = parts[0]
    else:
        fused = np.concatenate(parts, axis=0)
        norm = np.linalg.norm(fused)
        if not np.isfinite(norm) or norm < 1e-8:
            raise ValueError("融合编码器输出无效。")
        fused = fused / norm
    return fused.round(7).tolist()
