"""Password accounts and expiring, same-origin cookie sessions."""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from http.cookies import CookieError, SimpleCookie

from catalog import field
from media import Problem


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


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
