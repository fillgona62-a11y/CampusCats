#!/usr/bin/env python3
"""Zero-PyTorch one-click installer for a 23 MB quantized DINOv2-small ONNX encoder on CampusCats servers.

Runs directly on 4 GB CPU servers with only `onnxruntime` (no 2 GB PyTorch/timm needed).
Automatically tries China mainland HuggingFace mirror (https://hf-mirror.com) first, then official huggingface.co.

Usage on server (inside /srv/campuscats/vision-venv):
    python3 deploy/install_reid_model.py --out /srv/campuscats/models/dinov2-small-q8.onnx
"""

import argparse
import os
import sys
import urllib.request
from pathlib import Path

MODEL_REL_PATH = "Xenova/dinov2-small/resolve/main/onnx/model_quantized.onnx"


def download_file(urls, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    last_err = None
    for url in urls:
        print(f"[1/2] 尝试下载 23MB 量化 DINOv2-small ONNX 模型: {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CampusCats-Server/0.4.4"})
            with urllib.request.urlopen(req, timeout=90) as resp, tmp.open("wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
            if done < 5_000_000:
                raise RuntimeError(f"下载文件过小 ({done} bytes)，可能被拦截")
            tmp.replace(dst)
            print(f"下载完成：{dst} ({done / 1024 / 1024:.1f} MB)")
            return
        except Exception as exc:
            last_err = exc
            tmp.unlink(missing_ok=True)
            print(f"  下载失败（{exc}），尝试下一个源...")
    raise RuntimeError(f"所有下载源均失败：{last_err}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/srv/campuscats/models/dinov2-small-q8.onnx", help="Output ONNX path")
    parser.add_argument("--hf-endpoint", default=os.getenv("HF_ENDPOINT", "https://hf-mirror.com"), help="Primary HuggingFace mirror")
    args = parser.parse_args()

    out_path = Path(args.out).resolve()
    mirrors = [args.hf_endpoint.rstrip("/"), "https://huggingface.co"]
    urls = [f"{m}/{MODEL_REL_PATH}" for m in dict.fromkeys(mirrors) if m]
    if not out_path.is_file() or out_path.stat().st_size < 5_000_000:
        download_file(urls, out_path)
    else:
        print(f"[1/2] 模型已存在，跳过下载：{out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")

    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as exc:
        print(
            "缺少 onnxruntime，请先在服务端虚拟环境中运行：\n"
            "  pip install -i https://pypi.tuna.tsinghua.edu.cn/simple onnxruntime numpy\n"
            f"详细错误：{exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    print("[2/2] 正在使用 onnxruntime 校验 CPU 推理输出...")
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    sess = ort.InferenceSession(str(out_path), sess_options=opts, providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_names = [o.name for o in sess.get_outputs()]
    target_out = "pooler_output" if "pooler_output" in out_names else out_names[0]
    dummy = np.zeros((1, 3, 224, 224), dtype=np.float32)
    vec = sess.run([target_out], {in_name: dummy})[0]
    print(f"校验通过！输入={in_name}, 输出={target_out} {vec.shape}, 文件大小={out_path.stat().st_size / 1024 / 1024:.1f} MB")
    print(
        "\n下一步（启用深度 DINOv2-small ONNX 识猫引擎）：\n"
        f"  1. 在 systemd 服务配置中加入：Environment=\"CAMPUSCATS_ENCODER={out_path}\"\n"
        "  2. 重建历史照片深度特征索引：\n"
        f"     CAMPUSCATS_ENCODER={out_path} /srv/campuscats/vision-venv/bin/python /srv/campuscats/current/server/maintenance.py --reindex-vision --apply\n"
        "  3. 重启服务：sudo systemctl daemon-reload && sudo systemctl restart campuscats"
    )


if __name__ == "__main__":
    main()
