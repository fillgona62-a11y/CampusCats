"""Recompute versioned features from stored frames when switching encoders."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from vision import MODEL_VERSION, analyze_crop


def reindex(data_dir, media_dir):
    database = data_dir / "campus.sqlite3"
    if not database.is_file():
        raise ValueError(f"找不到数据库 {database}")
    connection = sqlite3.connect(database, timeout=20)
    count = 0
    try:
        with connection:
            # One transaction so a failed image/model can never leave half an index.
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("""
                SELECT s.id, s.box, s.analysis, f.image
                FROM sightings s JOIN frames f ON f.id=s.frame_id ORDER BY s.id
            """)
            for sighting_id, box, analysis, filename in rows:
                if json.loads(analysis).get("version") == MODEL_VERSION:
                    continue
                with Image.open(media_dir / filename) as photo:
                    updated = analyze_crop(photo, json.loads(box))
                connection.execute("UPDATE sightings SET analysis=? WHERE id=?",
                                   (json.dumps(updated, ensure_ascii=False), sighting_id))
                count += 1
    finally:
        connection.close()
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--media-dir", type=Path)
    args = parser.parse_args()
    print(f"更新记录数 {reindex(args.data_dir, args.media_dir or args.data_dir / 'media')}"
          f"，当前特征版本 {MODEL_VERSION}")
