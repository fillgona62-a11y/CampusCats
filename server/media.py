"""Validate and prepare photos outside the database write transaction."""
import base64
import binascii
import hashlib
import io
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, ImageOps, UnidentifiedImageError

from vision import analyze_crop, pixel_box
from face_match import face_features


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def decode_photo(value):
    if not isinstance(value, str) or not value:
        raise Problem("请上传一张照片。")
    if value.startswith("data:"):
        marker, sep, value = value.partition(",")
        if not sep or marker.lower() not in {
            "data:image/jpeg;base64", "data:image/png;base64", "data:image/webp;base64"
        }:
            raise Problem("请使用 JPG、PNG 或 WebP 格式。")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise Problem("照片编码不完整，请重新选择。") from None
    if len(raw) > 6 * 1024 * 1024:
        raise Problem("照片超过 6 MiB，请压缩后再上传。", 413)
    try:
        with Image.open(io.BytesIO(raw), formats=["JPEG", "PNG", "WEBP"]) as source:
            if source.width * source.height > 20_000_000:
                raise Problem("照片像素过高，请缩小后再上传。", 413)
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            image.info.clear()
            return image
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, ValueError):
        raise Problem("无法读取照片，请重新选择 JPG、PNG 或 WebP 图片。") from None


def validate_boxes(boxes):
    if not isinstance(boxes, list) or not 1 <= len(boxes) <= 8:
        raise Problem("请标出 1 至 8 只猫的位置。")
    normalized = []
    for box in boxes:
        if not isinstance(box, list) or len(box) != 4:
            raise Problem("标记位置无效。")
        if any(type(v) not in (float, int) or not 0 <= v <= 1 or not math.isfinite(v) for v in box):
            raise Problem("请在照片范围内标记。")
        x, y, w, h = box
        if w < .01 or h < .01 or x + w > 1.000001 or y + h > 1.000001:
            raise Problem("标记范围太小或超出了照片。")
        box = [x, y, min(1 - x, w), min(1 - y, h)]
        for a, b, c, d in normalized:
            overlap = max(0, min(x+w, a+c) - max(x, a)) * max(0, min(y+h, b+d) - max(y, b))
            if overlap / (w*h + c*d - overlap) > .85:
                raise Problem("两个标记几乎重合，请分别框出不同的猫。")
        normalized.append(box)
    return normalized


def jpeg_bytes(image, edge):
    target = image.copy()
    target.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    target.save(buffer, "JPEG", quality=84, optimize=True)
    return buffer.getvalue()


def media_name(data):
    return hashlib.sha256(data).hexdigest() + ".jpg"


def canonical_photo(photo):
    frame = jpeg_bytes(decode_photo(photo),2048)
    # Index exactly the same pixels when uploading, previewing and later rebuilding features.
    with Image.open(io.BytesIO(frame)) as image:
        return frame,image.convert("RGB")


def prepare(photo, boxes, *, verify=False):
    frame,image = canonical_photo(photo)
    media = {media_name(frame): frame}
    crops = []
    for box in boxes:
        target = image.crop(pixel_box(image, box))
        crop = jpeg_bytes(target, 768)
        thumb = jpeg_bytes(target, 320)
        media[media_name(crop)] = crop
        media[media_name(thumb)] = thumb
        analysis = analyze_crop(image, box)
        landmarks = face_features(target) if verify and analysis["usable"] else None
        crops.append((box, media_name(crop), media_name(thumb), analysis, landmarks))
    return media_name(frame), crops, media


def save_media(folder, media):
    # Publish complete immutable files before committing rows which point to them.
    for filename, content in media.items():
        destination = folder / filename
        if destination.is_file():
            continue
        with NamedTemporaryFile(dir=folder, delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            except BaseException:
                output.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            # Nginx can share the service group on a provisioned media mount.
            if os.name == "posix":
                temporary.chmod(0o640)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
