"""Campus Cats pilot HTTP API. Run locally or serve create_app() with a WSGI host."""
import argparse
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import traceback
from contextlib import closing
from http import HTTPStatus
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIServer, make_server

import accounts
from catalog import (SIGHTING_QUERY, audit, catalog, connect, encounter_receipt, field, identify, integer, one, personal_album,
                     reunions, review_breed, review_identity, revision, serialize, similar_pending, stats, upload)
from media import Problem

HERE = Path(__file__).resolve().parent


def read_json(env, max_bytes):
    if env.get("CONTENT_TYPE","").partition(";")[0].lower() != "application/json":
        raise Problem("请使用 JSON 格式提交。",415)
    try:
        length = int(env.get("CONTENT_LENGTH","0"))
    except ValueError:
        raise Problem("请求长度无效。") from None
    if length <= 0 or length > max_bytes:
        raise Problem("请求为空或超过大小限制。",413)
    try:
        body = json.loads(env["wsgi.input"].read(length))
    except (ValueError, UnicodeError, RecursionError):
        raise Problem("请求内容无法解析。") from None
    if not isinstance(body,dict):
        raise Problem("请求格式无效。")
    return body


def require(user, reviewer=False):
    if not user:
        raise Problem("请先登录。",401)
    if reviewer and user["role"] != "reviewer":
        raise Problem("需要审核员权限。",403)
    return user["id"]


def aliases(db, uid, cid, body):
    name = field(body,"name",60,required=True)
    cat = one(db,"SELECT c.name FROM cats c JOIN sightings s ON s.cat_id=c.id WHERE c.id=?",cid)
    if name.casefold() == cat["name"].casefold():
        raise Problem("这个名字已是档案名称。",409)
    try:
        db.execute("INSERT INTO aliases(cat_id,name,submitter) VALUES(?,?,?)",(cid,name,uid))
    except sqlite3.IntegrityError:
        raise Problem("这个别名已经提交过。",409) from None
    return {"ok":True}


def delete_account(db, media_dir, uid, body):
    row = one(db,"SELECT salt,password_hash FROM users WHERE id=?",uid)
    password = accounts.password_field(body)
    if not hmac.compare_digest(row["password_hash"], accounts.password_hash(password,row["salt"])):
        raise Problem("密码不正确。",403)
    db.execute("BEGIN IMMEDIATE")
    removed = [r[0] for r in db.execute(
        "SELECT image FROM frames WHERE user_id=? UNION SELECT s.crop FROM sightings s "
        "JOIN frames f ON f.id=s.frame_id WHERE f.user_id=? UNION SELECT t.image FROM thumbnails t "
        "JOIN sightings s ON s.id=t.sighting_id JOIN frames f ON f.id=s.frame_id WHERE f.user_id=?", (uid,uid,uid))]
    db.execute("DELETE FROM sessions WHERE user_id=?",(uid,))
    db.execute("DELETE FROM sightings WHERE frame_id IN (SELECT id FROM frames WHERE user_id=?)",(uid,))
    db.execute("DELETE FROM frames WHERE user_id=?",(uid,))
    db.execute("DELETE FROM aliases WHERE submitter=?",(uid,))
    # Historical review entries keep an anonymous actor ID for traceability.
    db.execute("UPDATE users SET email=?,nickname='',role='member',salt=?,password_hash=?,recovery_hash='' WHERE id=?",
               (f"deleted-{secrets.token_hex(20)}",secrets.token_bytes(16),secrets.token_bytes(32),uid))
    db.commit()
    # Keep blobs shared by other records. The writer lock also protects concurrent re-uploads.
    db.execute("BEGIN IMMEDIATE")
    for filename in removed:
        in_use = db.execute("SELECT 1 FROM frames WHERE image=? UNION ALL "
                            "SELECT 1 FROM sightings WHERE crop=? UNION ALL SELECT 1 FROM thumbnails "
                            "WHERE image=? LIMIT 1",(filename,filename,filename)).fetchone()
        if not in_use:
            (media_dir / filename).unlink(missing_ok=True)
    return {"ok":True}


class App:
    def __init__(self, data_dir, media_dir, accel_media=False, secure_cookie=False):
        self.data = Path(data_dir).resolve()
        self.media = Path(media_dir or self.data / "media").resolve()
        self.web = (HERE.parent / "web").resolve()
        if any(path.is_relative_to(self.web) for path in (self.data,self.media)):
            raise ValueError("Data and media directories must be outside the public web directory")
        self.db_path = self.data / "campus.sqlite3"
        self.accel = accel_media
        self.secure = secure_cookie
        self.data.mkdir(parents=True,exist_ok=True)
        self.media.mkdir(parents=True,exist_ok=True)
        with closing(connect(self.db_path)) as db:
            db.executescript((HERE/"schema.sql").read_text(encoding="utf-8"))

    def __call__(self, env, start_response):
        method, path = env["REQUEST_METHOD"], env["PATH_INFO"]
        headers = [("Cache-Control","no-store"),("X-Content-Type-Options","nosniff"),
                   ("Referrer-Policy","same-origin")]
        try:
            if path.startswith(("/api/","/media/")):
                with closing(connect(self.db_path)) as db, db:
                    user = accounts.current_user(db,env)
                    if method == "POST" and path.startswith("/api/"):
                        if env.get("HTTP_ORIGIN") and urlsplit(env["HTTP_ORIGIN"]).netloc != env.get("HTTP_HOST"):
                            raise Problem("请求来源无效。",403)
                        data = self.post(db,path,user,env,headers)
                    elif method == "GET" and path.startswith("/api/"):
                        db.execute("BEGIN")
                        data = self.get(db,path,user)
                    elif method in {"HEAD","GET"} and path.startswith("/media/"):
                        body, mime = self.media_response(db,path,user,headers)
                        data = None
                    else:
                        raise Problem("不支持该请求方式。",405)
            elif method in {"HEAD","GET"}:
                body,mime = self.static(path)
                data = None
            else:
                raise Problem("不支持该请求方式。",405)
            if data is not None:
                body,mime = json.dumps(data,ensure_ascii=False).encode(), "application/json; charset=utf-8"
            status = 200
        except (Problem, OverflowError) as error:
            status = error.status if isinstance(error, Problem) else 400
            body,mime = json.dumps({"error":str(error) if isinstance(error,Problem) else "数字过大。"},
                                   ensure_ascii=False).encode(),"application/json; charset=utf-8"
            headers = [h for h in headers if h[0] != "Set-Cookie"]
        except Exception:
            traceback.print_exc()
            status = 500
            body,mime = '{"error":"服务器处理失败，请稍后再试。"}'.encode(),"application/json; charset=utf-8"
            headers = [h for h in headers if h[0] != "Set-Cookie"]
        headers += [("Content-Type",mime),("Content-Length",str(len(body)))]
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [b"" if method == "HEAD" else body]

    def static(self, path):
        if "\\" in path or "\0" in path:
            raise Problem("文件不存在。",404)
        name = (self.web / (path.lstrip("/") or "index.html")).resolve()
        if not name.is_relative_to(self.web) or not name.is_file() or any(p.startswith(".") for p in name.relative_to(self.web).parts):
            raise Problem("文件不存在。",404)
        mime = {".webmanifest":"application/manifest+json",".js":"text/javascript"}.get(name.suffix)
        return name.read_bytes(), mime or mimetypes.guess_type(name.name)[0] or "application/octet-stream"

    def media_response(self, db, path, user, headers):
        match = re.fullmatch(r"/media/(crop|thumb|frame)/(\d{1,18})\.jpg",path)
        if not match:
            raise Problem("照片不存在。",404)
        kind, identifier = match.groups()
        if kind in {"crop","thumb"}:
            source = "coalesce(t.image,s.crop)" if kind == "thumb" else "s.crop"
            row = one(db,f"SELECT {source} AS file,s.status,f.user_id FROM sightings s "
                         "JOIN frames f ON f.id=s.frame_id LEFT JOIN thumbnails t ON t.sighting_id=s.id "
                         "WHERE s.id=?",int(identifier))
            public = row["status"] == "confirmed"
        else:
            row = one(db,"SELECT image AS file,user_id FROM frames WHERE id=?",int(identifier))
            public = False
        if not public and (not user or (user["id"] != row["user_id"] and user["role"]!="reviewer")):
            raise Problem("照片不存在。",404)
        if self.accel:
            headers.append(("X-Accel-Redirect","/_campus_media/"+row["file"]))
            return b"","image/jpeg"
        try:
            return (self.media / row["file"]).read_bytes(),"image/jpeg"
        except FileNotFoundError:
            raise Problem("照片已撤回或暂不可用。",404) from None

    def get(self, db, path, user):
        if path == "/api/session":
            return {"user":user}
        if path == "/api/home":
            cats = catalog(db)
            return {"stats":stats(db,cats),"cats":list(cats.values())}
        if path == "/api/me/album":
            return personal_album(db, require(user))
        receipt = re.fullmatch(r"/api/me/frames/(\d{1,18})", path)
        if receipt:
            return encounter_receipt(db, require(user), int(receipt[1]))
        if path == "/api/me":
            if not user:
                return {"user":None,"sightings":[],"reunions":[]}
            uid = user["id"]
            rows = db.execute(SIGHTING_QUERY+" WHERE f.user_id=? ORDER BY f.observed_at DESC,s.id DESC",(uid,))
            return {"user":user,"sightings":serialize(db,rows,private=True),"reunions":reunions(db,uid)}
        if path == "/api/review":
            require(user,reviewer=True)
            rows = db.execute(SIGHTING_QUERY+" WHERE s.status='pending' ORDER BY s.id")
            aliases_to_review = db.execute("SELECT a.id,a.name,c.name AS cat_name FROM aliases a JOIN cats c "
                                           "ON c.id=a.cat_id WHERE a.status='pending' ORDER BY a.id")
            return {"sightings":serialize(db,rows,private=True),"aliases":[dict(r) for r in aliases_to_review],
                    "catalog_revision":revision(db)}
        match = re.fullmatch(r"/api/review/(\d{1,18})/similar",path)
        if match:
            require(user,reviewer=True)
            return similar_pending(db,int(match[1]))
        match = re.fullmatch(r"/api/cats/(\d{1,18})",path)
        if match:
            cid = int(match[1])
            cat = catalog(db).get(cid)
            if not cat:
                raise Problem("档案不存在或已撤回。",404)
            if user and user["role"]=="reviewer":
                cat["evidence"] = one(db,"SELECT evidence FROM cats WHERE id=?",cid)["evidence"]
            rows = db.execute(SIGHTING_QUERY + " WHERE s.cat_id=? ORDER BY f.observed_at DESC,s.id DESC",(cid,))
            return {"cat":cat,"sightings":serialize(db,rows)}
        raise Problem("接口不存在。",404)

    def post(self, db, path, user, env, headers):
        auth_route = re.fullmatch(r"/api/(register|login|recover)",path)
        if auth_route:
            body = read_json(env,8192)
            return accounts.auth(db,auth_route[1],body,env,self.secure,headers)
        uid = require(user)
        is_photo = path in ("/api/identify","/api/sightings")
        if is_photo:
            accounts.throttle(db,f"photo:{uid}",180,3600)
        body = read_json(env,9*1024*1024 if is_photo else 16384)
        if path == "/api/logout":
            db.execute("DELETE FROM sessions WHERE token=?",(accounts.digest(accounts.session_token(env)),))
            headers.append(accounts.cookie("",self.secure))
            return {"ok":True}
        if path == "/api/account/delete":
            result = delete_account(db,self.media,uid,body)
            headers.append(accounts.cookie("",self.secure))
            return result
        if path == "/api/identify":
            return identify(db,body)
        if path == "/api/sightings":
            return upload(db,self.media,uid,body)
        match = re.fullmatch(r"/api/cats/(\d{1,18})/aliases",path)
        if match:
            return aliases(db,uid,int(match[1]),body)
        match = re.fullmatch(r"/api/sightings/(\d{1,18})/suggest",path)
        if match:
            db.execute("BEGIN IMMEDIATE")
            row = one(db,"SELECT s.status,s.frame_id FROM sightings s JOIN frames f ON f.id=s.frame_id "
                         "WHERE s.id=? AND f.user_id=?",int(match[1]),uid)
            if row["status"] != "pending":
                raise Problem("已审核的目击不能更改候选。",409)
            cid = body.get("cat_id")
            if cid is not None:
                one(db,"SELECT 1 FROM sightings WHERE cat_id=? AND status='confirmed'",integer(cid))
                overlap = db.execute("SELECT 1 FROM sightings WHERE frame_id=? AND id!=? AND "
                                     "(cat_id=? OR suggested_cat_id=?)",(row["frame_id"],int(match[1]),cid,cid)).fetchone()
                if overlap:
                    raise Problem("同框的猫不能选择同一个档案。",409)
            db.execute("UPDATE sightings SET suggested_cat_id=? WHERE id=?",(cid,int(match[1])))
            return {"ok":True}
        require(user,reviewer=True)
        match = re.fullmatch(r"/api/review/(\d{1,18})",path)
        if match:
            return review_identity(db,uid,int(match[1]),body)
        match = re.fullmatch(r"/api/cats/(\d{1,18})/breed",path)
        if match:
            return review_breed(db,uid,int(match[1]),body)
        match = re.fullmatch(r"/api/aliases/(\d{1,18})/review",path)
        if match:
            approve = body.get("approve")
            if type(approve) is not bool:
                raise Problem("审核选择无效。")
            status = "approved" if approve else "rejected"
            result = db.execute("UPDATE aliases SET status=? WHERE id=? AND status='pending'",(status,int(match[1])))
            if not result.rowcount:
                raise Problem("别名不存在或已审核。",409)
            audit(db,uid,"alias",int(match[1]),"pending",status,"别名审核")
            return {"ok":True}
        raise Problem("接口不存在。",404)


def create_app():
    return App(os.getenv("CAMPUS_DATA_DIR") or HERE.parent/"instance", os.getenv("CAMPUS_MEDIA_DIR"),
               os.getenv("CAMPUS_ACCEL_MEDIA")=="1", os.getenv("CAMPUS_SECURE_COOKIE")=="1")


class LocalServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",default=os.getenv("CAMPUS_DATA_DIR") or HERE.parent/"instance")
    parser.add_argument("--media-dir",default=os.getenv("CAMPUS_MEDIA_DIR"))
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--promote",metavar="EMAIL",help="Grant review access to an existing, trusted pilot account")
    parser.add_argument("--accel-media",action="store_true",default=os.getenv("CAMPUS_ACCEL_MEDIA")=="1")
    parser.add_argument("--secure-cookie",action="store_true",default=os.getenv("CAMPUS_SECURE_COOKIE")=="1")
    options = parser.parse_args()
    app = App(options.data_dir,options.media_dir,options.accel_media,options.secure_cookie)
    if options.promote:
        with closing(connect(app.db_path)) as db, db:
            result = db.execute("UPDATE users SET role='reviewer' WHERE email=?",(options.promote.strip().lower(),))
            if result.rowcount != 1:
                parser.error("Register the account before granting review access")
        print("Reviewer access granted.")
        return
    with make_server(options.host,options.port,app,server_class=LocalServer) as httpd:
        print(f"Campus Cats: http://{options.host}:{httpd.server_port}",flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
