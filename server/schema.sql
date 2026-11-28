PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nickname TEXT NOT NULL,
    salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    recovery_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('member','reviewer'))
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users,
    expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS throttle (
    bucket TEXT PRIMARY KEY,
    expires INTEGER NOT NULL,
    hits INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS photo_reviews (
    user_id INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
    digest TEXT NOT NULL,
    expires INTEGER NOT NULL,
    PRIMARY KEY(user_id,digest)
);
CREATE TABLE IF NOT EXISTS cats (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    coat TEXT NOT NULL DEFAULT '',
    breed TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '',
    sex TEXT NOT NULL DEFAULT 'unknown' CHECK(sex IN ('unknown','female','male')),
    neutered TEXT NOT NULL DEFAULT 'unknown' CHECK(neutered IN ('unknown','neutered','intact')),
    care_status TEXT NOT NULL DEFAULT 'school' CHECK(care_status IN ('school','attention','adopted','memorial')),
    temperament TEXT NOT NULL DEFAULT '',
    cover_sighting_id INTEGER DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS campus_areas (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users,
    request_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    image TEXT UNIQUE NOT NULL,
    area TEXT NOT NULL,
    note TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    location_accuracy REAL,
    UNIQUE(user_id,request_id)
);
CREATE TABLE IF NOT EXISTS sightings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_id INTEGER NOT NULL REFERENCES frames,
    box TEXT NOT NULL,
    crop TEXT NOT NULL,
    analysis TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','rejected')),
    suggested_cat_id INTEGER REFERENCES cats,
    cat_id INTEGER REFERENCES cats,
    CHECK((status='confirmed')=(cat_id IS NOT NULL)),
    UNIQUE(frame_id,cat_id)
);
CREATE INDEX IF NOT EXISTS sightings_by_cat ON sightings(cat_id);
CREATE INDEX IF NOT EXISTS sightings_by_status ON sightings(status);
CREATE TABLE IF NOT EXISTS community_topics (
    sighting_id INTEGER PRIMARY KEY REFERENCES sightings ON DELETE CASCADE,
    state TEXT NOT NULL CHECK(state IN ('poll','closed','private_name','public_name','named','cancelled')),
    cat_id INTEGER REFERENCES cats ON DELETE SET NULL,
    named_by INTEGER REFERENCES users ON DELETE SET NULL,
    closes INTEGER,
    options TEXT NOT NULL,
    distribution TEXT NOT NULL,
    calibrated INTEGER NOT NULL CHECK(calibrated IN (0,1)),
    result TEXT
);
CREATE INDEX IF NOT EXISTS community_topics_deadline ON community_topics(closes) WHERE state='poll';
CREATE TABLE IF NOT EXISTS community_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sighting_id INTEGER NOT NULL REFERENCES community_topics ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
    choice TEXT NOT NULL,
    UNIQUE(sighting_id,user_id)
);
CREATE INDEX IF NOT EXISTS frames_by_owner ON frames(user_id,observed_at);
CREATE TABLE IF NOT EXISTS spot_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users,
    request_id TEXT NOT NULL,
    area TEXT NOT NULL,
    started INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('active','done','withdrawn')),
    peak INTEGER CHECK(peak BETWEEN 0 AND 999),
    CHECK((state='done')=(peak IS NOT NULL)),
    UNIQUE(user_id,request_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_check ON spot_checks(user_id) WHERE state='active';
CREATE INDEX IF NOT EXISTS completed_checks_by_time ON spot_checks(started,area) WHERE state='done';
CREATE TABLE IF NOT EXISTS thumbnails (
    sighting_id INTEGER PRIMARY KEY REFERENCES sightings(id) ON DELETE CASCADE,
    image TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auto_identity (
    sighting_id INTEGER PRIMARY KEY REFERENCES sightings(id) ON DELETE CASCADE,
    first_reference INTEGER NOT NULL REFERENCES sightings(id) ON DELETE CASCADE,
    second_reference INTEGER NOT NULL REFERENCES sightings(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS auto_identity_first ON auto_identity(first_reference);
CREATE INDEX IF NOT EXISTS auto_identity_second ON auto_identity(second_reference);
CREATE TRIGGER IF NOT EXISTS recheck_auto_identity_on_reference_change
BEFORE UPDATE OF status, cat_id ON sightings
WHEN OLD.status='confirmed' AND (NEW.status!='confirmed' OR NEW.cat_id IS NOT OLD.cat_id)
BEGIN
    UPDATE sightings SET status='pending', cat_id=NULL
    WHERE id IN (SELECT sighting_id FROM auto_identity WHERE first_reference=OLD.id OR second_reference=OLD.id);
    DELETE FROM auto_identity WHERE first_reference=OLD.id OR second_reference=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS recheck_auto_identity_on_reference_delete
BEFORE DELETE ON sightings
WHEN OLD.status='confirmed'
BEGIN
    UPDATE sightings SET status='pending', cat_id=NULL
    WHERE id IN (SELECT sighting_id FROM auto_identity WHERE first_reference=OLD.id OR second_reference=OLD.id);
END;
CREATE TRIGGER IF NOT EXISTS clear_cover_on_sighting_change
BEFORE UPDATE OF status, cat_id ON sightings
WHEN OLD.status='confirmed' AND (NEW.status!='confirmed' OR NEW.cat_id IS NOT OLD.cat_id)
BEGIN
    UPDATE cats SET cover_sighting_id=NULL WHERE id=OLD.cat_id AND cover_sighting_id=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS clear_cover_on_sighting_delete
BEFORE DELETE ON sightings
BEGIN
    UPDATE cats SET cover_sighting_id=NULL WHERE cover_sighting_id=OLD.id;
END;
CREATE TABLE IF NOT EXISTS aliases (
    id INTEGER PRIMARY KEY,
    cat_id INTEGER NOT NULL REFERENCES cats,
    name TEXT NOT NULL COLLATE NOCASE,
    submitter INTEGER NOT NULL REFERENCES users,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    UNIQUE(cat_id,name)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    actor INTEGER NOT NULL REFERENCES users,
    kind TEXT NOT NULL,
    target INTEGER NOT NULL,
    before_state TEXT NOT NULL,
    after_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_providers (
  owner INTEGER PRIMARY KEY,
  base_url TEXT NOT NULL,
  chat_model TEXT NOT NULL,
  vision_model TEXT NOT NULL,
  protocol TEXT NOT NULL,
  secret BLOB NOT NULL
);
