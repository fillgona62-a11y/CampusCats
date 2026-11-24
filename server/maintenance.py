"""Routine maintenance for CampusCats: prune expired sessions/throttle and audit orphan media.

Dry-run by default. Pass --apply to actually delete expired rows and stale unreferenced files.
"""

import argparse
import os
import time
from contextlib import closing
from pathlib import Path

from catalog import connect

DEFAULT_GRACE_SECONDS = 3600


def inspect_and_prune(data_dir, media_dir=None, *, apply=False, grace_seconds=DEFAULT_GRACE_SECONDS, now=None):
    data = Path(data_dir).resolve()
    media = Path(media_dir or data / "media").resolve()
    db_path = data / "campus.sqlite3"
    if not db_path.is_file():
        raise ValueError(f"Database not found: {db_path}")

    ts = int(time.time() if now is None else now)
    cutoff = ts - max(0, int(grace_seconds))

    with closing(connect(db_path)) as db:
        if apply:
            db.execute("BEGIN IMMEDIATE")
        expired_sessions = db.execute("SELECT COUNT(*) FROM sessions WHERE expires<=?", (ts,)).fetchone()[0]
        expired_throttle = db.execute("SELECT COUNT(*) FROM throttle WHERE expires<=?", (ts,)).fetchone()[0]

        referenced = {
            row[0]
            for row in db.execute(
                "SELECT image FROM frames UNION SELECT crop FROM sightings UNION SELECT image FROM thumbnails"
            )
        }

        orphan_files = []
        skipped_recent = 0
        if media.is_dir():
            for entry in sorted(media.iterdir()):
                if not entry.is_file() or entry.name.startswith("."):
                    continue
                if entry.name in referenced:
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if mtime > cutoff:
                    skipped_recent += 1
                    continue
                orphan_files.append(entry)

        deleted_files = 0
        freed_bytes = 0
        if apply:
            db.execute("DELETE FROM sessions WHERE expires<=?", (ts,))
            db.execute("DELETE FROM throttle WHERE expires<=?", (ts,))
            db.commit()
            for entry in orphan_files:
                try:
                    size = entry.stat().st_size
                    entry.unlink(missing_ok=True)
                    deleted_files += 1
                    freed_bytes += size
                except OSError:
                    pass
        else:
            freed_bytes = sum(entry.stat().st_size for entry in orphan_files if entry.exists())

    return {
        "applied": bool(apply),
        "expired_sessions": expired_sessions,
        "expired_throttle": expired_throttle,
        "orphan_files": len(orphan_files),
        "skipped_recent_orphans": skipped_recent,
        "deleted_files": deleted_files,
        "freed_bytes": freed_bytes,
    }




def reindex_vision(data_dir, media_dir=None, *, apply=False):
    """Recompute stored sightings.analysis descriptors to match current MODEL_VERSION (e.g. coat-texture-2 or ONNX)."""
    import json
    from PIL import Image
    from vision import MODEL_VERSION, analyze_crop

    data = Path(data_dir).resolve()
    media = Path(media_dir or data / "media").resolve()
    db_path = data / "campus.sqlite3"
    if not db_path.is_file():
        raise ValueError(f"Database not found: {db_path}")

    scanned = 0
    needs_update = 0
    updated = 0
    missing_media = 0
    with closing(connect(db_path)) as db:
        rows = db.execute(
            "SELECT s.id, s.box, s.analysis, f.image FROM sightings s JOIN frames f ON f.id=s.frame_id"
        ).fetchall()
        pending_updates = []
        for row in rows:
            scanned += 1
            try:
                old_analysis = json.loads(row["analysis"])
            except ValueError:
                old_analysis = {}
            if old_analysis.get("version") == MODEL_VERSION:
                continue
            needs_update += 1
            if not apply:
                continue
            frame_path = media / row["image"]
            if not frame_path.is_file():
                missing_media += 1
                continue
            try:
                box = json.loads(row["box"])
                with Image.open(frame_path) as im:
                    new_analysis = analyze_crop(im, box)
                pending_updates.append((json.dumps(new_analysis, ensure_ascii=False), row["id"]))
            except (OSError, ValueError):
                missing_media += 1
        if apply and pending_updates:
            db.execute("BEGIN IMMEDIATE")
            db.executemany("UPDATE sightings SET analysis=? WHERE id=?", pending_updates)
            db.commit()
            updated = len(pending_updates)

    return {
        "applied": bool(apply),
        "model_version": MODEL_VERSION,
        "scanned": scanned,
        "needs_update": needs_update,
        "updated": updated,
        "missing_media": missing_media,
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.getenv("CAMPUS_DATA_DIR") or Path(__file__).resolve().parent.parent / "instance")
    parser.add_argument("--media-dir", default=os.getenv("CAMPUS_MEDIA_DIR"))
    parser.add_argument("--grace-seconds", type=int, default=DEFAULT_GRACE_SECONDS,
                        help="Skip unreferenced media modified within this many seconds (default: 3600)")
    parser.add_argument("--apply", action="store_true", help="Perform deletions or reindex writes instead of dry-run")
    parser.add_argument("--reindex-vision", action="store_true", help="Recompute stored sighting features for current vision model")
    args = parser.parse_args()
    if args.reindex_vision:
        rep = reindex_vision(args.data_dir, args.media_dir, apply=args.apply)
        mode = "APPLIED" if rep["applied"] else "DRY-RUN"
        print(f"[{mode}] model={rep['model_version']} scanned={rep['scanned']} needs_update={rep['needs_update']} updated={rep['updated']} missing_media={rep['missing_media']}")
        return
    report = inspect_and_prune(args.data_dir, args.media_dir, apply=args.apply, grace_seconds=args.grace_seconds)
    mode = "APPLIED" if report["applied"] else "DRY-RUN"
    print(
        f"[{mode}] expired_sessions={report['expired_sessions']} "
        f"expired_throttle={report['expired_throttle']} "
        f"orphan_files={report['orphan_files']} "
        f"skipped_recent={report['skipped_recent_orphans']} "
        f"freed_bytes={report['freed_bytes']}"
    )


if __name__ == "__main__":
    main()
