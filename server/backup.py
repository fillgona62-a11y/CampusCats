"""Snapshot a pilot's SQLite database and every referenced, verified photo."""
import argparse
import hashlib
import os
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile, TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


def backup(data, media, destination):
    source_path = Path(data).resolve() / "campus.sqlite3"
    media = Path(media or source_path.parent / "media").resolve()
    destination = Path(destination).resolve()
    if not source_path.is_file():
        raise ValueError("No database at " + str(source_path))
    if destination.exists():
        raise ValueError("Choose a new backup filename")
    with TemporaryDirectory() as scratch, NamedTemporaryFile(
            dir=destination.parent, prefix=".campus-backup-", delete=False) as pending:
        temp = Path(pending.name)
        pending.close()
        try:
            snapshot = Path(scratch) / "campus.sqlite3"
            with closing(sqlite3.connect(source_path)) as src, closing(sqlite3.connect(snapshot)) as db:
                src.backup(db)
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Snapshot failed integrity check")
                records = db.execute("SELECT image FROM frames UNION SELECT crop FROM sightings "
                                     "UNION SELECT image FROM thumbnails").fetchall()
                # Restoring a backup should require everyone to sign in again.
                db.execute("DELETE FROM sessions")
                db.commit()
            with ZipFile(temp,"w") as archive:
                archive.write(snapshot,"campus.sqlite3",compress_type=ZIP_DEFLATED)
                for (filename,) in records:
                    payload = (media/filename).read_bytes()
                    if hashlib.sha256(payload).hexdigest()+".jpg" != filename:
                        raise ValueError("Media failed integrity check: " + filename)
                    archive.writestr("media/"+filename,payload,compress_type=ZIP_STORED)
            # Exclusive publication. A parallel backup targeting the same name cannot overwrite it.
            os.link(temp,destination)
        finally:
            temp.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",type=Path,required=True)
    parser.add_argument("--media-dir",type=Path)
    parser.add_argument("destination",type=Path)
    args = parser.parse_args()
    backup(args.data_dir,args.media_dir,args.destination)
    print("Backup verified:",args.destination)
