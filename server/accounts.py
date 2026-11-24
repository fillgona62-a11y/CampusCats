"""Password accounts and expiring, same-origin cookie sessions."""
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import sqlite3
import time
from functools import lru_cache
from http.cookies import CookieError, SimpleCookie

from catalog import field
from media import Problem


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@lru_cache(maxsize=8)
def _trusted_networks(raw, trust_local):
    items = [part.strip() for part in raw.split(",") if part.strip()]
    if trust_local == "1":
        items.extend(("127.0.0.1/32", "::1/128"))
    nets = []
    for item in items:
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(nets)


def _valid_ip(value):
    text = (value or "").strip()
    if not text:
        return None
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def client_ip(env):
    """Return validated client IP, honoring X-Real-IP / X-Forwarded-For only from trusted proxies."""
    remote_raw = (env.get("REMOTE_ADDR") or "").strip()
    remote = _valid_ip(remote_raw)
    if remote is None:
        return remote_raw or "unknown"
    nets = _trusted_networks(
        os.getenv("CAMPUS_TRUSTED_PROXIES", ""),
        os.getenv("CAMPUS_TRUST_LOCAL_PROXY", ""),
    )
    if nets and any(remote in net for net in nets):
        real = _valid_ip(env.get("HTTP_X_REAL_IP"))
        if real is not None:
            return str(real)
        xff = env.get("HTTP_X_FORWARDED_FOR") or ""
        if xff:
            parts = [_valid_ip(p) for p in xff.split(",")]
            valid = [ip for ip in parts if ip is not None]
            for candidate in reversed(valid):
                if not any(candidate in net for net in nets):
                    return str(candidate)
            if valid:
                return str(valid[0])
    return str(remote)


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 420_000)


def password_field(body, new=False):
    value = body.get("password")
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise Problem("请输入有效密码。")
    if new and len(value) < 8:
        raise Problem("密码至少需要 8 个字符。")
    return value


def throttle(db, bucket, count, window):
    now = int(time.time())
    db.execute("BEGIN IMMEDIATE")
    db.execute("DELETE FROM throttle WHERE expires<=?", (now,))
    hits = db.execute("""
        INSERT INTO throttle(bucket,expires,hits) VALUES(?,?,1)
        ON CONFLICT(bucket) DO UPDATE SET hits=hits+1 RETURNING hits
    """, (digest(bucket),now+window)).fetchone()[0]
    db.commit()
    if hits > count:
        raise Problem("操作过于频繁，请稍后再试。", 429)


USER_FIELDS = "u.id,u.email,u.nickname,u.role"


def session_token(env):
    jar = SimpleCookie()
    try:
        jar.load(env.get("HTTP_COOKIE", ""))
    except CookieError:
        return ""
    return jar["campus_session"].value if "campus_session" in jar else ""


def current_user(db, env):
    token = session_token(env)
    if not token:
        return None
    row = db.execute(f"SELECT {USER_FIELDS} FROM users u JOIN sessions s ON s.user_id=u.id "
                     "WHERE s.token=? AND s.expires>?", (digest(token),int(time.time()))).fetchone()
    return dict(row) if row else None


def cookie(value, secure):
    lifetime = 30*86400 if value else 0
    return ("Set-Cookie", f"campus_session={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={lifetime}"
            + ("; Secure" if secure else ""))


def auth(db, path, body, env, secure, headers):
    email = field(body, "email", 254, required=True).lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise Problem("请输入有效的邮箱地址。")
    password = password_field(body, new=path != "login")
    peer = client_ip(env)
    throttle(db, f"auth-ip:{path}:{peer}", 60 if path == "login" else 30, 900)
    throttle(db, f"auth:{path}:{email}", 16, 900)
    if path == "register":
        nickname = field(body, "nickname", 40, required=True)
        recovery_code = secrets.token_urlsafe(18)
        salt = secrets.token_bytes(16)
        credential = password_hash(password,salt)
        try:
            uid = db.execute("INSERT INTO users(email,nickname,salt,password_hash,recovery_hash) VALUES(?,?,?,?,?)",
                             (email,nickname,salt,credential,digest(recovery_code))).lastrowid
        except sqlite3.IntegrityError:
            raise Problem("这个邮箱已经注册。",409) from None
    else:
        row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        recovery_code = None
        if path == "login":
            predicted = password_hash(password,row["salt"] if row else bytes(16))
            if row is None or not hmac.compare_digest(row["password_hash"],predicted):
                raise Problem("邮箱或密码不正确。",401)
        elif path == "recover":
            supplied = field(body,"recovery_code",128,required=True)
            # Serialize rotation; only one request may successfully use a recovery code.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if row is None or not hmac.compare_digest(row["recovery_hash"],digest(supplied)):
                raise Problem("邮箱或恢复码不正确。",401)
            salt = secrets.token_bytes(16)
            recovery_code = secrets.token_urlsafe(18)
            db.execute("UPDATE users SET salt=?,password_hash=?,recovery_hash=? WHERE id=?",
                       (salt,password_hash(password,salt),digest(recovery_code),row["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        uid = row["id"]
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM sessions WHERE expires<=? OR token=?", (now,digest(session_token(env))))
    db.execute("INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)", (digest(token),uid,now+30*86400))
    headers.append(cookie(token, secure))
    result = {"user":dict(db.execute(f"SELECT {USER_FIELDS} FROM users u WHERE id=?", (uid,)).fetchone())}
    if recovery_code:
        result["recovery_code"] = recovery_code
    return result
