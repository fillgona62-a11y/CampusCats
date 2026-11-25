"""Local zero-shot cat species gate, breed, and coat classifier via CLIP-ViT-B/32 INT8 ONNX.

Runs 100% locally on CPU without PyTorch or external API keys:
- `clip-vision-q8.onnx` (~89 MB, CLIPVisionModelWithProjection INT8)
- `clip-cat-prompts.npz` (~35 KB, precomputed text embeddings generated at install time)

Provides:
1. `inspect_species(crop)` — rejects humans, dogs, and non-animal scenes before catalog matching.
2. `classify_breed_and_coat(crop)` — recognizes 16 cat breeds/types and 11 coat patterns offline.
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
        "a solid pure white domestic shorthair cat or山东狮子猫",
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
    ("纯黑", ["a completely solid black cat"]),
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


def inspect_species(crop):
    """Classify crop into cat / person / dog / other to block non-cat uploads."""
    vec, bank = _encode_image(crop)
    if vec is None or "species_vecs" not in bank:
        return None
    import numpy as np

    keys = [str(k) for k in bank["species_keys"].tolist()]
    mat = np.asarray(bank["species_vecs"], dtype=np.float32)
    scale = float(bank.get("logit_scale", 100.0))
    probs = _softmax((mat @ vec) * scale, np)
    scores = {k: round(float(p), 4) for k, p in zip(keys, probs)}
    cat_p = scores.get("cat", 0.0)
    person_p = scores.get("person", 0.0)
    dog_p = scores.get("dog", 0.0)
    other_p = scores.get("other", 0.0)
    dominant = max(scores, key=scores.get)
    is_cat = bool(
        cat_p >= 0.34
        and cat_p >= person_p * 1.20
        and cat_p >= dog_p * 1.15
        and cat_p >= other_p * 0.80
    )
    return {
        "is_cat": is_cat,
        "dominant": dominant,
        "cat_prob": cat_p,
        "person_prob": person_p,
        "dog_prob": dog_p,
        "other_prob": other_p,
    }


def classify_breed_and_coat(crop):
    """Zero-shot local ONNX breed + coat classification."""
    vec, bank = _encode_image(crop)
    if vec is None or "breed_vecs" not in bank or "coat_vecs" not in bank:
        return None
    import numpy as np

    scale = float(bank.get("logit_scale", 100.0))
    breed_keys = [str(k) for k in bank["breed_keys"].tolist()]
    breed_native = [bool(x) for x in bank["breed_native"].tolist()]
    breed_mat = np.asarray(bank["breed_vecs"], dtype=np.float32)
    breed_probs = _softmax((breed_mat @ vec) * scale, np)

    top_idx = int(np.argmax(breed_probs))
    top_breed = breed_keys[top_idx]
    top_prob = float(breed_probs[top_idx])
    is_native = breed_native[top_idx]

    # Sum probability across all Chinese domestic /田园猫 sub-types
    native_mass = float(sum(p for p, nat in zip(breed_probs, breed_native) if nat))

    if top_prob >= 0.44 or (is_native and native_mass >= 0.62):
        confidence = "high"
    elif top_prob >= 0.25 or (is_native and native_mass >= 0.45):
        confidence = "medium"
    else:
        confidence = "low"

    # Guard against over-claiming rare purebreds on ordinary campus stray cats
    if not is_native and top_prob < 0.30 and native_mass >= 0.35:
        breed_label = f"中华田园猫 / 混血（具{top_breed}特征）"
        confidence = "low"
    elif is_native:
        breed_label = "中华田园猫"
    else:
        breed_label = top_breed

    coat_keys = [str(k) for k in bank["coat_keys"].tolist()]
    coat_mat = np.asarray(bank["coat_vecs"], dtype=np.float32)
    coat_probs = _softmax((coat_mat @ vec) * scale, np)
    coat_idx = int(np.argmax(coat_probs))
    coat_label = coat_keys[coat_idx]
    coat_prob = float(coat_probs[coat_idx])

    features = []
    if is_native and "（" in top_breed:
        sub = top_breed.split("（", 1)[1].rstrip("）")
        features.append(f"田园猫常见{sub}品相")
    if coat_prob >= 0.35:
        features.append(f"毛色呈{coat_label}特征")

    return {
        "source": "local_clip",
        "model": "clip-vit-b32-q8",
        "breed": breed_label,
        "breed_confidence": confidence,
        "coat": coat_label,
        "features": features[:4],
        "neutered_hint": "unknown",
        "summary": f"本地视觉模型识别为「{breed_label}」（{coat_label}，置信度：{'高' if confidence == 'high' else '中' if confidence == 'medium' else '参考'}）。",
    }
