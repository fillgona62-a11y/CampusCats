"""Build a repeatable evaluation manifest from locally reviewed individual IDs."""

import argparse
import csv
import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def export(data_dir, media_dir, dest, utc_offset=8):
    database = data_dir / "campus.sqlite3"
    if not database.is_file():
        raise ValueError(f"找不到数据库 {database}")
    local_time = timezone(timedelta(hours=utc_offset))
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        has_automatic = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='auto_identity'"
        ).fetchone()
        exclude_automatic = "AND NOT EXISTS (SELECT 1 FROM auto_identity a WHERE a.sighting_id=s.id)" if has_automatic else ""
        rows = connection.execute(f"""
            SELECT s.cat_id, f.observed_at, f.image, s.box, f.id
            FROM sightings s JOIN frames f ON f.id=s.frame_id
            WHERE s.status='confirmed' {exclude_automatic} ORDER BY f.observed_at,f.id,s.id
        """).fetchall()
    finally:
        connection.close()
    known_days = defaultdict(set)
    entries = []
    for cat_id, timestamp, filename, box, frame_id in rows:
        instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        day = instant.astimezone(local_time).date()
        known_days[cat_id].add(day)
        entries.append((cat_id, day, filename, json.loads(box), frame_id))
    if not any(len(days) >= 2 for days in known_days.values()):
        raise ValueError("至少要有一只经确认的猫在不同日期有目击。")
    order = sorted(known_days, key=lambda key: hashlib.sha256(str(key).encode()).digest())
    # Preserve a cross-day known identity. Hold out other entire identities.
    keep = next(cat_id for cat_id in order if len(known_days[cat_id]) >= 2)
    unknown_count = max(1, len(order) // 5) if len(order) > 1 else 0
    unknown = set([cat_id for cat_id in order if cat_id != keep][:unknown_count])
    first_days = {cat_id: min(days) for cat_id, days in known_days.items()}
    frame_splits = defaultdict(set)
    classified = []
    for cat_id, day, filename, box, frame_id in entries:
        split = "gallery" if cat_id not in unknown and day == first_days[cat_id] else "test"
        frame_splits[frame_id].add(split)
        classified.append((split, cat_id, day, filename, box, frame_id))
    output = []
    for split, cat_id, day, filename, box, frame_id in classified:
        if len(frame_splits[frame_id]) != 1:
            continue
        pic = (media_dir / filename).resolve()
        if not pic.is_file():
            raise ValueError(f"找不到图片 {pic}，请检查媒体目录。")
        try:
            path = os.path.relpath(pic, dest.resolve().parent)
        except ValueError:  # Windows: pictures and manifest can be on separate drives.
            path = str(pic)
        output.append([split, cat_id, day.isoformat(), path, *box])
    gallery = {row[1] for row in output if row[0] == "gallery"}
    if not any(row[0] == "test" and row[1] in gallery for row in output):
        raise ValueError("排除跨组的同框图后缺少跨日测试照片。请另拍一张已建档猫的照片。")
    # Only label truly held-out identities 'unknown'. A known ID might have
    # lost its sole gallery photo when an ambiguous shared frame was removed.
    output = [row for row in output if row[1] in gallery or row[1] in unknown]
    with dest.open("x", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["split", "cat_id", "date", "photo", "x", "y", "width", "height"])
        writer.writerows(output)
    return len(output), sum(len(groups) > 1 for groups in frame_splits.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--media-dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--utc-offset", type=int, default=8, choices=range(-12, 15))
    args = parser.parse_args()
    try:
        count, skipped = export(args.data_dir, args.media_dir or args.data_dir/"media", args.out,
                                args.utc_offset)
        print(f"已列入 {count} 条经复核的记录，省略 {skipped} 张跨组同框图。")
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"生成清单失败：{error}\n")
