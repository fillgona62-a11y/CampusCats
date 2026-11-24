"""Optional CPU encoder for a single-file 224px ImageNet-normalized ONNX model."""

import hashlib
import os
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image

MODEL_PATH = os.getenv("CAMPUSCATS_ENCODER", "").strip()


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


VERSION = "onnx-letterbox224-cls-v3-" + _sha256(MODEL_PATH) if MODEL_PATH else None
_LOCK = threading.Lock()


def _feature_output(names):
    if len(names) == 1:
        return names[0]
    for name in ("last_hidden_state", "pooler_output", "image_embeds"):
        if name in names:
            return name
    raise ValueError("请导出一个特征输出，或命名为 last_hidden_state、pooler_output、image_embeds。")


@lru_cache(maxsize=1)
def _engine():
    # ONNX Runtime supports common transformer exports. OpenCV DNN is also
    # useful for compact encoders that use operators available in that build.
    try:
        import onnxruntime as ort
    except ImportError:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("启用 ONNX 特征模型需要安装 onnxruntime。") from exc
        net = cv2.dnn.readNetFromONNX(MODEL_PATH)
        output = _feature_output(net.getUnconnectedOutLayersNames())

        def run(data):
            with _LOCK:
                net.setInput(data)
                return net.forward(output)
        return run
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(MODEL_PATH, sess_options=options, providers=["CPUExecutionProvider"])
    if len(session.get_inputs()) != 1:
        raise ValueError("请导出一个像素输入的独立 ONNX 文件。")
    name = session.get_inputs()[0].name
    output = _feature_output([result.name for result in session.get_outputs()])
    return lambda data: session.run([output], {name: data})[0]


def embed(crop):
    import numpy as np

    # Aspect-preserving 224x224 letterbox padded with ImageNet mean so wide
    # side-profile cat boxes retain head, ears, legs, and tail without memory blowup.
    w, h = crop.size
    scale = 224.0 / max(w, h)
    nw = max(1, min(224, round(w * scale)))
    nh = max(1, min(224, round(h * scale)))
    resized = crop.resize((nw, nh), Image.Resampling.BICUBIC)
    mean = np.asarray([.485, .456, .406], dtype=np.float32)
    std = np.asarray([.229, .224, .225], dtype=np.float32)
    canvas = np.broadcast_to(mean, (224, 224, 3)).copy()
    top = (224 - nh) // 2
    left = (224 - nw) // 2
    canvas[top:top + nh, left:left + nw] = np.asarray(resized, dtype=np.float32) / 255.0
    pixels = (canvas - mean) / std
    data = np.ascontiguousarray(pixels.transpose(2, 0, 1)[None])
    output = np.asarray(_engine()(data))
    if output.ndim == 3 and output.shape[0] == 1:
        vector = output[0, 0]
    elif output.ndim == 2 and output.shape[0] == 1:
        vector = output[0]
    else:
        raise ValueError("ONNX 特征输出应为 [1,D] 或 [1,N,D]，首个 token 为 CLS。")
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm < 1e-8 or not 2 <= vector.size <= 4096:
        raise ValueError("图像编码器输出无效，请检查模型导出。")
    return (vector / norm).round(7).tolist()
