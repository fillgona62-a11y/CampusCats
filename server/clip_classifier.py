"""Local zero-shot cat species gate & coat assistant via CLIP-ViT-B/32 INT8 ONNX (v0.6.3).

Strictly acts as Stage-1 assist (never asserts authoritative purebred types):
- `clip-vision-q8.onnx` (~89 MB, CLIPVisionModelWithProjection INT8)
- `clip-cat-prompts.npz` (~35 KB, precomputed text embeddings generated at install time)

Provides single-pass `analyze_crop_once(crop)` so both species verification and coat hint
share ONE ONNX forward call.
"""

import os
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image

_LOCK = threading.Lock()

# Canonical English prompt banks used by deploy/install_reid_model.py to precompute clip-cat-prompts.npz
SPECIES_PROMPTS = [
    ("cat", [
        "a photo of a cat",
        "a photo of a stray cat or kitten outdoors",
        "close-up photo of a domestic cat face, ears, whiskers, or fur",
        "a fluffy black or dark brown domestic cat in dim light",
        "a solid black longhaired cat with glowing eyes",
        "multiple cats or kittens sitting together",
    ]),
    ("person", [
        "a photo of a person, human face, man, woman, or student",
        "a human portrait, selfie, or group of people without any cat",
        "human hands, legs, shoes, or clothing",
    ]),
    ("dog", [
        "a photo of a dog or puppy",
        "close-up of a dog snout, nose, and ears",
    ]),
    ("other", [
        "an empty street, building, room, desk, food, or plant without animals",
        "a photo of a car, bicycle, bird, squirrel, or plush toy",
    ]),
]

BREED_PROMPTS = [
    ("中华田园猫（狸花猫）", True, [
        "a Chinese Li Hua brown mackerel tabby domestic shorthair cat",
        "a domestic tabby stray cat with dark stripes and M mark on forehead",
    ]),
    ("中华田园猫（橘猫/橘白）", True, [
        "a domestic ginger orange tabby or orange and white shorthair cat",
        "a chubby orange stray cat outdoors",
    ]),
    ("中华田园猫（三花/玳瑁）", True, [
        "a calico domestic shorthair cat with white, orange, and black patches",
        "a tortoiseshell domestic cat with mottled black and orange fur",
    ]),
    ("中华田园猫（奶牛猫）", True, [
        "a black and white bicolor tuxedo cow cat domestic shorthair",
        "a white cat with black patches on head and back",
    ]),
    ("中华田园猫（纯白/纯黑）", True, [
        "a solid pure white domestic shorthair cat or Chinese Shandong Lion cat",
        "a solid sleek black domestic shorthair cat",
    ]),
    ("英国短毛猫", False, [
        "a British Shorthair cat with chubby cheeks, round face, and dense plush blue-gray or golden shaded coat",
        "a blue and white bicolor or silver shaded British Shorthair cat",
    ]),
    ("美国短毛猫", False, [
        "an American Shorthair cat with classic silver swirled bullseye tabby markings",
    ]),
    ("布偶猫", False, [
        "a fluffy longhaired Ragdoll cat with blue eyes and colorpoint or bicolor coat",
    ]),
    ("暹罗猫", False, [
        "a sleek shorthaired Siamese cat with dark seal point face, ears, paws, and blue eyes",
    ]),
    ("加菲猫 / 异国短毛猫", False, [
        "an Exotic Shorthair flat-faced cat with round eyes and snub nose",
    ]),
    ("波斯猫 / 金吉拉", False, [
        "a longhaired Persian or silver Chinchilla cat with very long fluffy coat and flat face",
    ]),
    ("缅因猫", False, [
        "a large Maine Coon longhaired cat with tufted lynx ears, bushy tail, and neck ruff",
    ]),
    ("俄罗斯蓝猫", False, [
        "a slender Russian Blue cat with emerald green eyes and silvery blue-gray coat",
    ]),
    ("孟加拉豹猫", False, [
        "a Bengal cat with wild leopard rosette spots on golden brown fur",
    ]),
    ("阿比西尼亚猫", False, [
        "an Abyssinian cat with ticked warm ruddy reddish-brown coat and large ears",
    ]),
    ("斯芬克斯无毛猫", False, [
        "a hairless Sphynx cat with wrinkled skin and large ears",
    ]),
]

COAT_PROMPTS = [
    ("橘猫", ["a solid or striped ginger orange cat with little or no white fur"]),
    ("橘白", ["an orange and white bicolor cat with white chest, belly, or paws"]),
    ("狸花 / 虎斑", ["a brown or gray striped mackerel tabby cat with dark stripes"]),
    ("奶牛（黑白）", ["a black and white tuxedo or cow-patterned bicolor cat"]),
    ("三花", ["a calico cat with distinct white, orange, and black patches"]),
    ("玳瑁", ["a dark tortoiseshell cat with mingled black and orange mottled fur and almost no white"]),
    ("蓝猫 / 灰猫", ["a solid blue-gray or slate gray shorthair cat"]),
    ("蓝白 / 灰白", ["a blue-gray and white bicolor cat"]),
    ("重点色（挖煤脸）", ["a colorpoint cat with cream body and dark brown face, ears, and paws"]),
    ("纯白", ["a completely pure white cat"]),
    ("纯黑 / 深色", ["a completely solid black or very dark fluffy cat"]),
]


def _discover_paths():
    explicit = os.getenv("CAMPUSCATS_CLIP_MODEL", "").strip()
    candidates = []
    if explicit:
        p = Path(explicit)
        candidates.append((p, p.with_name("clip-cat-prompts.npz")))
    for env_key in ("CAMPUSCATS_DETECTOR", "CAMPUSCATS_ENCODER"):
        raw = os.getenv(env_key, "").split(",")[0].strip()
        if raw:
            parent = Path(raw).resolve().parent
            candidates.append((parent / "clip-vision-q8.onnx", parent / "clip-cat-prompts.npz"))
    for v_path, p_path in candidates:
        if v_path.is_file() and p_path.is_file():
            return v_path, p_path
    return None, None


def is_enabled():
    v_path, p_path = _discover_paths()
    return bool(v_path and p_path)


@lru_cache(maxsize=1)
def _engine():
    v_path, p_path = _discover_paths()
    if not v_path or not p_path:
        return None
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError:
        return None
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    session = ort.InferenceSession(str(v_path), sess_options=opts, providers=["CPUExecutionProvider"])
    in_name = session.get_inputs()[0].name
    out_names = [o.name for o in session.get_outputs()]
    out_name = "image_embeds" if "image_embeds" in out_names else out_names[0]
    bank = dict(np.load(str(p_path), allow_pickle=False))
    return session, in_name, out_name, bank


def _encode_image(crop):
    eng = _engine()
    if eng is None:
        return None, None
    import numpy as np

    session, in_name, out_name, bank = eng
    rgb = crop.convert("RGB")
    w, h = rgb.size
    scale = 224.0 / max(1, max(w, h))
    nw, nh = max(1, min(224, int(round(w * scale)))), max(1, min(224, int(round(h * scale))))
    resized = rgb.resize((nw, nh), Image.Resampling.BICUBIC)
    mean = np.asarray([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
    std = np.asarray([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
    canvas = np.broadcast_to(mean, (224, 224, 3)).copy()
    top, left = (224 - nh) // 2, (224 - nw) // 2
    canvas[top : top + nh, left : left + nw] = np.asarray(resized, dtype=np.float32) / 255.0
    inp = np.ascontiguousarray(((canvas - mean) / std).transpose(2, 0, 1)[None])
    with _LOCK:
        vec = np.asarray(session.run([out_name], {in_name: inp})[0], dtype=np.float32)
    if vec.ndim == 2:
        vec = vec[0]
    elif vec.ndim == 3:
        vec = vec[0, 0]
    norm = float(np.linalg.norm(vec))
    if not np.isfinite(norm) or norm < 1e-8:
        return None, None
    return vec / norm, bank


def _softmax(logits, np):
    shifted = logits - np.max(logits)
    exps = np.exp(shifted)
    return exps / (np.sum(exps) + 1e-9)


def _species_from_vec(vec, bank):
    if vec is None or bank is None or "species_vecs" not in bank:
        return None
    import numpy as np

    keys = [str(k) for k in bank["species_keys"].tolist()]
    mat = np.asarray(bank["species_vecs"], dtype=np.float32)
    scale = min(float(bank.get("logit_scale", 35.0)), 35.0)
    probs = _softmax((mat @ vec) * scale, np)
    scores = {k: round(float(p), 4) for k, p in zip(keys, probs)}
    cat_p = scores.get("cat", 0.0)
    person_p = scores.get("person", 0.0)
    dog_p = scores.get("dog", 0.0)
    other_p = scores.get("other", 0.0)
    dominant = max(scores, key=scores.get)
    is_cat = bool(
        cat_p >= 0.30
        and cat_p >= person_p * 1.15
        and cat_p >= dog_p * 1.08
        and cat_p >= other_p * 0.75
    )
    return {
        "is_cat": is_cat,
        "dominant": dominant,
        "cat_prob": cat_p,
        "person_prob": person_p,
        "dog_prob": dog_p,
        "other_prob": other_p,
    }


def _coat_from_vec(vec, bank):
    if vec is None or bank is None or "coat_vecs" not in bank:
        return None
    import numpy as np

    scale = min(float(bank.get("logit_scale", 35.0)), 35.0)
    coat_keys = [str(k) for k in bank["coat_keys"].tolist()]
    coat_mat = np.asarray(bank["coat_vecs"], dtype=np.float32)
    coat_probs = _softmax((coat_mat @ vec) * scale, np)
    coat_idx = int(np.argmax(coat_probs))
    coat_label = coat_keys[coat_idx]
    coat_prob = float(coat_probs[coat_idx])
    features = [f"辅助毛色参考：{coat_label}"] if coat_prob >= 0.30 else []
    return {
        "is_cat": True,
        "source": "local_assist",
        "model": "clip-vit-b32-q8",
        "breed": "未知",
        "breed_confidence": "low",
        "coat": coat_label,
        "features": features,
        "neutered_hint": "unknown",
        "summary": f"本地模型仅辅助初筛毛色参考（{coat_label}），具体品种与特征以云端视觉模型拍板或人工核验为准。",
    }


def analyze_crop_once(crop):
    """Run CLIP image encoding ONCE and return both species gate and coat assist hint."""
    vec, bank = _encode_image(crop)
    if vec is None:
        return None
    return {
        "species": _species_from_vec(vec, bank),
        "coat": _coat_from_vec(vec, bank),
    }


def inspect_species(crop):
    """Classify crop into cat / person / dog / other to block non-cat uploads."""
    vec, bank = _encode_image(crop)
    return _species_from_vec(vec, bank)


def classify_coat_only(crop, *, vec=None, bank=None):
    """Local Stage-1 coat assist ONLY (defers authoritative breed/type decision to Cloud VLM)."""
    if vec is None or bank is None:
        vec, bank = _encode_image(crop)
    return _coat_from_vec(vec, bank)


def classify_breed_and_coat(crop):
    """Compatibility alias: delegates to local coat-only assist without claiming purebred types."""
    return classify_coat_only(crop)
