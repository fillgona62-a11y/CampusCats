#!/usr/bin/env python3
"""Zero-PyTorch one-click installer for CampusCats local ONNX vision stack (v0.6.0):
1. dinov2-base-q8.onnx (90.9 MB, or --lite for 23.3 MB dinov2-small-q8.onnx)
   -> Spatial patch + CLS hybrid individual cat Re-ID embedding
2. yolov8s.onnx (44.8 MB, or --lite for 12.2 MB yolov8n.onnx)
   -> 80-class anti-human/anti-dog multi-cat Soft-NMS detector
3. clip-vision-q8.onnx (89.1 MB) + precomputed clip-cat-prompts.npz (~35 KB)
   -> Zero-cost local species gate (cat vs human/dog/scene) + 16 cat breeds + 11 coat patterns

Runs directly on 4 GB CPU servers with ONLY `onnxruntime` and `numpy` (no PyTorch/transformers needed).
Automatically tries China mainland HuggingFace mirror (https://hf-mirror.com) first.

Usage on server:
    python3 deploy/install_reid_model.py --model-dir /srv/campuscats/models
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "server") not in sys.path:
    sys.path.insert(0, str(ROOT / "server"))

from clip_classifier import BREED_PROMPTS, COAT_PROMPTS, SPECIES_PROMPTS  # noqa: E402

STANDARD_MODELS = {
    "dinov2-base-q8.onnx": {
        "rel": "Xenova/dinov2-base/resolve/main/onnx/model_quantized.onnx",
        "min_bytes": 40_000_000,
    },
    "yolov8s.onnx": {
        "rel": "Kalray/yolov8/resolve/main/yolov8s.onnx",
        "min_bytes": 20_000_000,
    },
    "clip-vision-q8.onnx": {
        "rel": "Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx",
        "min_bytes": 40_000_000,
    },
}

LITE_MODELS = {
    "dinov2-small-q8.onnx": {
        "rel": "Xenova/dinov2-small/resolve/main/onnx/model_quantized.onnx",
        "min_bytes": 5_000_000,
    },
    "yolov8n.onnx": {
        "rel": "salim4n/yolov8n-detect-onnx/resolve/main/yolov8n-onnx-web/yolov8n.onnx",
        "min_bytes": 4_000_000,
    },
    "clip-vision-q8.onnx": {
        "rel": "Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx",
        "min_bytes": 40_000_000,
    },
}

CLIP_TEXT_BUILD_FILES = {
    "_clip_text_q8.onnx": {
        "rel": "Xenova/clip-vit-base-patch32/resolve/main/onnx/text_model_quantized.onnx",
        "min_bytes": 30_000_000,
    },
    "_clip_tokenizer.json": {
        "rel": "Xenova/clip-vit-base-patch32/resolve/main/tokenizer.json",
        "min_bytes": 500_000,
    },
}


def download_file(urls, dst: Path, min_bytes: int):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    last_err = None
    for url in urls:
        print(f"  尝试下载 {dst.name}: {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CampusCats-Server/0.6.0"})
            with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
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


class _SimpleClipBpeTokenizer:
    """Pure-Python CLIP byte-level BPE tokenizer reading HuggingFace tokenizer.json."""

    def __init__(self, tokenizer_json_path: Path):
        data = json.loads(tokenizer_json_path.read_text(encoding="utf-8"))
        model = data["model"]
        self.vocab = model["vocab"]
        merges = [tuple(m.split()) if isinstance(m, str) else tuple(m) for m in model["merges"]]
        self.bpe_ranks = {pair: idx for idx, pair in enumerate(merges)}
        self.bos_id = self.vocab.get("<|startoftext|>", 49406)
        self.eos_id = self.vocab.get("<|endoftext|>", 49407)
        self.byte_encoder = self._bytes_to_unicode()

    @staticmethod
    def _bytes_to_unicode():
        bs = (
            list(range(ord("!"), ord("~") + 1))
            + list(range(ord("¡"), ord("¬") + 1))
            + list(range(ord("®"), ord("ÿ") + 1))
        )
        cs = bs[:]
        n = 0
        for b in range(256):
            if b not in bs:
                bs.append(b)
                cs.append(256 + n)
                n += 1
        return {b: chr(c) for b, c in zip(bs, cs)}

    def _bpe(self, token: str):
        word = tuple(token[:-1]) + (token[-1] + "</w>",)
        if len(word) == 1:
            return word
        while True:
            pairs = {(word[i], word[i + 1]) for i in range(len(word) - 1)}
            bigram = min(pairs, key=lambda p: self.bpe_ranks.get(p, 10**9))
            if bigram not in self.bpe_ranks:
                break
            first, second = bigram
            new_word = []
            i = 0
            while i < len(word):
                try:
                    j = word.index(first, i)
                    new_word.extend(word[i:j])
                    i = j
                except ValueError:
                    new_word.extend(word[i:])
                    break
                if i < len(word) - 1 and word[i] == first and word[i + 1] == second:
                    new_word.append(first + second)
                    i += 2
                else:
                    new_word.append(word[i])
                    i += 1
            word = tuple(new_word)
            if len(word) == 1:
                break
        return word

    def encode(self, text: str, context_length: int = 77):
        import re

        cleaned = " ".join(text.lower().strip().split())
        raw_tokens = re.findall(r"<\|startoftext\|>|<\|endoftext\|>|'s|'t|'re|'ve|'m|'ll|'d|[\w]+|[^\s\w]+", cleaned)
        ids = [self.bos_id]
        for tok in raw_tokens:
            encoded = "".join(self.byte_encoder[b] for b in tok.encode("utf-8"))
            for piece in self._bpe(encoded):
                if piece in self.vocab:
                    ids.append(self.vocab[piece])
        ids = ids[: context_length - 1] + [self.eos_id]
        mask = [1] * len(ids) + [0] * (context_length - len(ids))
        ids = ids + [self.eos_id] * (context_length - len(ids))
        return ids, mask


def _build_clip_prompt_bank(model_dir: Path, mirrors, opts, np, ort):
    npz_path = model_dir / "clip-cat-prompts.npz"
    if npz_path.is_file() and npz_path.stat().st_size >= 10_000:
        print(f"[跳过] 已存在：{npz_path} ({npz_path.stat().st_size / 1024:.1f} KB)")
        return npz_path

    temp_files = []
    try:
        for fname, spec in CLIP_TEXT_BUILD_FILES.items():
            dst = model_dir / fname
            temp_files.append(dst)
            if not (dst.is_file() and dst.stat().st_size >= spec["min_bytes"]):
                urls = [f"{m}/{spec['rel']}" for m in dict.fromkeys(mirrors) if m]
                download_file(urls, dst, spec["min_bytes"])

        tok = _SimpleClipBpeTokenizer(model_dir / "_clip_tokenizer.json")
        sess = ort.InferenceSession(str(model_dir / "_clip_text_q8.onnx"), sess_options=opts, providers=["CPUExecutionProvider"])
        in_names = {i.name for i in sess.get_inputs()}
        out_names = [o.name for o in sess.get_outputs()]
        out_name = "text_embeds" if "text_embeds" in out_names else out_names[0]

        def encode_group(prompts):
            vecs = []
            for p in prompts:
                ids, mask = tok.encode(p)
                feed = {"input_ids": np.asarray([ids], dtype=np.int64)}
                if "attention_mask" in in_names:
                    feed["attention_mask"] = np.asarray([mask], dtype=np.int64)
                v = np.asarray(sess.run([out_name], feed)[0], dtype=np.float32)[0]
                v = v / (np.linalg.norm(v) + 1e-9)
                vecs.append(v)
            mean_v = np.mean(np.stack(vecs, axis=0), axis=0)
            return (mean_v / (np.linalg.norm(mean_v) + 1e-9)).astype(np.float32)

        species_keys = [k for k, _ in SPECIES_PROMPTS]
        species_vecs = np.stack([encode_group(ps) for _, ps in SPECIES_PROMPTS], axis=0)

        breed_keys = [k for k, _, _ in BREED_PROMPTS]
        breed_native = [nat for _, nat, _ in BREED_PROMPTS]
        breed_vecs = np.stack([encode_group(ps) for _, _, ps in BREED_PROMPTS], axis=0)

        coat_keys = [k for k, _ in COAT_PROMPTS]
        coat_vecs = np.stack([encode_group(ps) for _, ps in COAT_PROMPTS], axis=0)

        np.savez_compressed(
            npz_path,
            logit_scale=np.float32(100.0),
            species_keys=np.asarray(species_keys),
            species_vecs=species_vecs,
            breed_keys=np.asarray(breed_keys),
            breed_native=np.asarray(breed_native),
            breed_vecs=breed_vecs,
            coat_keys=np.asarray(coat_keys),
            coat_vecs=coat_vecs,
        )
        print(f"  已生成零样本物种/品种/花色向量库：{npz_path} ({npz_path.stat().st_size / 1024:.1f} KB)")
        return npz_path
    finally:
        for tmp in temp_files:
            tmp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", default="/srv/campuscats/models", help="Directory to store ONNX models")
    parser.add_argument("--out", default="", help="Legacy single-model path (optional)")
    parser.add_argument("--lite", action="store_true", help="Use lighter DINOv2-small + YOLOv8n instead of DINOv2-base + YOLOv8s")
    parser.add_argument("--hf-endpoint", default=os.getenv("HF_ENDPOINT", "https://hf-mirror.com"), help="Primary HuggingFace mirror")
    args = parser.parse_args()

    model_dir = Path(args.out).resolve().parent if args.out else Path(args.model_dir).resolve()
    mirrors = [args.hf_endpoint.rstrip("/"), "https://huggingface.co"]
    manifest = LITE_MODELS if args.lite else STANDARD_MODELS
    dino_name = "dinov2-small-q8.onnx" if args.lite else "dinov2-base-q8.onnx"
    yolo_name = "yolov8n.onnx" if args.lite else "yolov8s.onnx"

    for fname, spec in manifest.items():
        dst = Path(args.out).resolve() if (args.out and fname == dino_name) else (model_dir / fname)
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

    npz_path = _build_clip_prompt_bank(model_dir, mirrors, opts, np, ort)

    dino_path = Path(args.out).resolve() if args.out else (model_dir / dino_name)
    s1 = ort.InferenceSession(str(dino_path), sess_options=opts, providers=["CPUExecutionProvider"])
    v1 = s1.run([s1.get_outputs()[0].name], {s1.get_inputs()[0].name: np.zeros((1, 3, 224, 224), dtype=np.float32)})[0]
    print(f"[校验通过] 个体 Re-ID ({dino_name}) -> {v1.shape}")

    yolo_path = model_dir / yolo_name
    s2 = ort.InferenceSession(str(yolo_path), sess_options=opts, providers=["CPUExecutionProvider"])
    v2 = s2.run([s2.get_outputs()[0].name], {s2.get_inputs()[0].name: np.zeros((1, 3, 640, 640), dtype=np.float32)})[0]
    print(f"[校验通过] 多猫+防误识检测 ({yolo_name}) -> {v2.shape}")

    clip_path = model_dir / "clip-vision-q8.onnx"
    s3 = ort.InferenceSession(str(clip_path), sess_options=opts, providers=["CPUExecutionProvider"])
    c_out = "image_embeds" if "image_embeds" in [o.name for o in s3.get_outputs()] else s3.get_outputs()[0].name
    v3 = s3.run([c_out], {s3.get_inputs()[0].name: np.zeros((1, 3, 224, 224), dtype=np.float32)})[0]
    print(f"[校验通过] 品种/花色/防人像模型 (clip-vision-q8.onnx + {npz_path.name}) -> {v3.shape}")

    print("\n推荐写入 /etc/campuscats.env 的配置：")
    print(f"CAMPUSCATS_ENCODER={dino_path}")
    print(f"CAMPUSCATS_DETECTOR={yolo_path}")
    print(f"CAMPUSCATS_CLIP_MODEL={clip_path}")
    print("升级编码器后请执行一次历史参考照特征重建：")
    print("python3 server/maintenance.py --data-dir /var/lib/campuscats --media-dir /srv/campuscats-media --reindex-vision --apply")


if __name__ == "__main__":
    main()
