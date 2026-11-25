#!/usr/bin/env python3
"""Zero-PyTorch one-click installer for CampusCats ONNX models:
1. dinov2-small-q8.onnx (23.3 MB) - Individual cat Re-ID embedding
2. yolov8n.onnx (12.2 MB) - Automatic multi-cat bounding box detector

Runs directly on 4 GB CPU servers with only `onnxruntime` and `numpy`.
Automatically tries China mainland HuggingFace mirror (https://hf-mirror.com) first.

Usage on server:
    python3 deploy/install_reid_model.py --model-dir /srv/campuscats/models
"""

import argparse
import os
import sys
import urllib.request
from pathlib import Path

MODELS = {
    "dinov2-small-q8.onnx": {
        "rel": "Xenova/dinov2-small/resolve/main/onnx/model_quantized.onnx",
        "min_bytes": 5_000_000,
    },
    "yolov8n.onnx": {
        "rel": "salim4n/yolov8n-detect-onnx/resolve/main/yolov8n-onnx-web/yolov8n.onnx",
        "min_bytes": 4_000_000,
    },
}


def download_file(urls, dst: Path, min_bytes: int):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    last_err = None
    for url in urls:
        print(f"  尝试下载 {dst.name}: {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CampusCats-Server/0.5.0"})
            with urllib.request.urlopen(req, timeout=90) as resp, tmp.open("wb") as out:
                done = 0
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
            if done < min_bytes:
                raise RuntimeError(f"下载文件过小 ({done} bytes)")
            tmp.replace(dst)
            print(f"  下载完成：{dst} ({done / 1024 / 1024:.1f} MB)")
            return
        except Exception as exc:
            last_err = exc
            tmp.unlink(missing_ok=True)
            print(f"    下载失败（{exc}），尝试下一个源...")
    raise RuntimeError(f"{dst.name} 所有下载源均失败：{last_err}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", default="/srv/campuscats/models", help="Directory to store ONNX models")
    parser.add_argument("--out", default="", help="Legacy single-model path (optional)")
    parser.add_argument("--hf-endpoint", default=os.getenv("HF_ENDPOINT", "https://hf-mirror.com"), help="Primary HuggingFace mirror")
    args = parser.parse_args()

    model_dir = Path(args.out).resolve().parent if args.out else Path(args.model_dir).resolve()
    mirrors = [args.hf_endpoint.rstrip("/"), "https://huggingface.co"]

    for fname, spec in MODELS.items():
        dst = Path(args.out).resolve() if (args.out and fname == "dinov2-small-q8.onnx") else (model_dir / fname)
        if dst.is_file() and dst.stat().st_size >= spec["min_bytes"]:
            print(f"[跳过] 已存在：{dst} ({dst.stat().st_size / 1024 / 1024:.1f} MB)")
        else:
            urls = [f"{m}/{spec['rel']}" for m in dict.fromkeys(mirrors) if m]
            download_file(urls, dst, spec["min_bytes"])

    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as exc:
        print(f"缺少 onnxruntime/numpy：{exc}", file=sys.stderr)
        sys.exit(1)

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1

    dino_path = Path(args.out).resolve() if args.out else (model_dir / "dinov2-small-q8.onnx")
    s1 = ort.InferenceSession(str(dino_path), sess_options=opts, providers=["CPUExecutionProvider"])
    v1 = s1.run([s1.get_outputs()[0].name], {s1.get_inputs()[0].name: np.zeros((1, 3, 224, 224), dtype=np.float32)})[0]
    print(f"[校验通过] DINOv2-small -> {v1.shape}")

    yolo_path = model_dir / "yolov8n.onnx"
    s2 = ort.InferenceSession(str(yolo_path), sess_options=opts, providers=["CPUExecutionProvider"])
    v2 = s2.run([s2.get_outputs()[0].name], {s2.get_inputs()[0].name: np.zeros((1, 3, 640, 640), dtype=np.float32)})[0]
    print(f"[校验通过] YOLOv8n 多猫检测 -> {v2.shape}")


if __name__ == "__main__":
    main()
