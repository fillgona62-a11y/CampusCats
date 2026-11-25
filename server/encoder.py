"""Optional CPU encoder supporting single or comma-separated multi-model ONNX Re-ID ensemble (with 2-view TTA).

Examples:
  Single model:
    CAMPUSCATS_ENCODER=/srv/campuscats/models/megadescriptor-t-224-q8.onnx
  Dual-model ensemble (DINOv2-small + MegaDescriptor-T-224):
    CAMPUSCATS_ENCODER=/srv/campuscats/models/dinov2-small-q8.onnx,/srv/campuscats/models/megadescriptor-t-224-q8.onnx
"""

import hashlib
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
    ("onnx-ensemble-tta-v5-" if len(MODEL_PATHS) > 1 else "onnx-letterbox224-tta-v5-")
    + _sha256_multi(MODEL_PATHS)
    if MODEL_PATHS
    else None
)
_LOCK = threading.Lock()


def _feature_output(names):
    if len(names) == 1:
        return names[0]
    for name in ("image_embeds", "last_hidden_state", "pooler_output"):
        if name in names:
            return name
    raise ValueError("请导出一个特征输出，或命名为 image_embeds、pooler_output、last_hidden_state。")


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
    return (lambda data, _s=session, _o=output, _n=name: _s.run([_o], {_n: data})[0]), side


@lru_cache(maxsize=1)
def _engine():
    return _load_one_engine(MODEL_PATH)[0]


@lru_cache(maxsize=1)
def _engines():
    if len(MODEL_PATHS) <= 1:
        return ((_engine(), 224),)
    return tuple(_load_one_engine(p) for p in MODEL_PATHS)


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
        if output.ndim == 3 and output.shape[0] == 1:
            vector = output[0, 0]
        elif output.ndim == 2 and output.shape[0] == 1:
            vector = output[0]
        else:
            raise ValueError("ONNX 特征输出应为 [1,D] 或 [1,N,D]，首个 token 为 CLS。")
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm < 1e-8 or not 2 <= vector.size <= 4096:
            raise ValueError("图像编码器输出无效，请检查模型导出。")
        return vector / norm

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
