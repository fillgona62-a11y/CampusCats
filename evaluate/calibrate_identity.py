"""Fit novelty and candidate probabilities from independent identity-labeled photos."""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from run import MODEL_VERSION, load_set, rank_candidates


def samples(manifest):
    entries = load_set(manifest)
    references = [(cat, analysis) for split, cat, _, _, analysis, _ in entries if split == "gallery"]
    days = defaultdict(set)
    for split, cat, day, _, _, _ in entries:
        if split == "gallery":
            days[cat].add(day)
    observations = []
    for split, cat, day, photo, analysis, _ in entries:
        if split != "test":
            continue
        if day in days[cat]:
            raise ValueError(f"{photo} 与参考照属于同一天。")
        ranked = rank_candidates(analysis, references, limit=3, max_distance=1.0)
        if ranked:
            observations.append((cat, not days[cat], ranked))
    if len({cat for cat, new, _ in observations if new}) < 2 or len({cat for cat, new, _ in observations if not new}) < 2:
        raise ValueError("至少需要两只库内猫和两只陌生猫的可用测试照片。")
    return observations


def sigmoid(value):
    return 1 / (1 + math.exp(-value))


def fit(observations):
    # Balanced novelty log loss, so the split's known/unknown ratio is not a free weight.
    counts = [sum(new == flag for _, new, _ in observations) for flag in (False, True)]
    def novelty_loss(mid, slope):
        return sum(
            -math.log(max(1e-12, sigmoid((1 if new else -1) * slope * (ranked[0]["distance"] - mid)))) / counts[new]
            for _, new, ranked in observations
        )
    _, mid, slope = min(
        (novelty_loss(n / 100, s), n / 100, s)
        for n in range(1, 100) for s in (4, 8, 12, 18, 25, 40, 65, 100)
    )

    def identity_loss(temperature):
        loss = 0.0
        for cat, new, ranked in observations:
            if new:
                continue
            best = ranked[0]["distance"]
            weights = {item["cat_id"]: math.exp(-(item["distance"]-best) / temperature) for item in ranked}
            loss -= math.log(max(1e-12, weights.get(cat, 0.0) / sum(weights.values())))
        return loss
    temp = min((.012, .018, .025, .035, .045, .065, .1, .16, .25, .4), key=identity_loss)
    return {"model":MODEL_VERSION, "new_midpoint":mid, "new_slope":slope, "identity_temperature":temp}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        observations = samples(args.manifest)
        with args.out.open("x", encoding="utf-8") as handle:
            json.dump(fit(observations), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"校准样本 {len(observations)} 张。启用前请另用未参与校准的照片校验阈值。")


if __name__ == "__main__":
    main()
