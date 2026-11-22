"""Download an immutable public DINOv2-small ONNX file and verify its published SHA-256."""

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

REPOSITORY = "Xenova/dinov2-small"


def download(directory, revision, variant):
    api = f"https://huggingface.co/api/models/{REPOSITORY}/revision/{quote(revision, safe='')}?blobs=true"
    with urlopen(api, timeout=25) as response:
        model = json.load(response)
    commit = model["sha"]
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("仓库没有返回可固定的提交编号。")
    directory.mkdir(parents=True, exist_ok=True)
    files = {item["rfilename"]: item for item in model["siblings"]}
    name = f"onnx/{variant}"
    expected = files.get(name, {}).get("lfs", {}).get("sha256", "")
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError(f"该版本缺少 {name} 的 SHA-256。")
    source = f"https://huggingface.co/{REPOSITORY}/resolve/{commit}/{name}"
    output = directory / f"dinov2-small-{commit[:12]}-{variant}"
    digest = hashlib.sha256()
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as pending:
            temp_name = Path(pending.name)
            with urlopen(source, timeout=60) as response:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    pending.write(chunk)
                    digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("下载文件的 SHA-256 与仓库公布值不一致。")
        temp_name.replace(output)
    finally:
        if temp_name is not None:
            temp_name.unlink(missing_ok=True)
    return {"path": str(output.resolve()), "source": source, "revision": commit, "sha256": expected}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--revision", default="main", help="Branch or exact Hugging Face commit")
    parser.add_argument("--variant", choices=["model.onnx", "model_quantized.onnx"],
                        default="model.onnx")
    args = parser.parse_args()
    try:
        print(json.dumps(download(args.dest, args.revision, args.variant), ensure_ascii=False, indent=2))
    except (KeyError, OSError, ValueError, URLError) as error:
        parser.exit(2, f"下载失败：{error}\n")
