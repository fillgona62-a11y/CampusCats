"""HTTP contract regressions: cold start, same-frame constraints and reviewer corrections."""
import base64
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

from app import App
from backup import backup
from catalog import connect


class CatalogFlow(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.app = App(Path(folder.name),None)
        self.member = self.register("member@example.edu")
        self.reviewer = self.register("review@example.edu")
        with closing(connect(self.app.db_path)) as db, db:
            db.execute("UPDATE users SET role='reviewer' WHERE email='review@example.edu'")

    def call(self, path, payload=None, cookie="", expected=200):
        raw = json.dumps(payload).encode() if payload is not None else b""
        env = {"REQUEST_METHOD":"POST" if payload is not None else "GET","PATH_INFO":path,
               "wsgi.input":io.BytesIO(raw),"CONTENT_LENGTH":str(len(raw)),"CONTENT_TYPE":"application/json",
               "HTTP_COOKIE":cookie,"REMOTE_ADDR":"127.0.0.1","HTTP_HOST":"localhost"}
        reply = {}
        def start(status, headers):
            reply.update(code=int(status[:3]),headers=dict(headers))
        result = b"".join(self.app(env,start))
        self.assertEqual(reply["code"],expected,(path,result[:500]))
        body = json.loads(result) if "json" in reply["headers"]["Content-Type"] else result
        return body,reply["headers"]

    def register(self, email):
        body,headers = self.call("/api/register",{"email":email,"password":"testpass-123","nickname":"观察者"})
        return headers["Set-Cookie"].split(";")[0]

    def photo(self, nonce=0):
        image = Image.new("RGB",(300,180),"#724f3e")
        draw = ImageDraw.Draw(image)
        for i in range(0,300,10):
            draw.ellipse((i,20+(i+nonce)%14,i+18,150),fill="#e3a85b",outline="#272521",width=3)
        data = io.BytesIO()
        image.save(data,"PNG")
        return base64.b64encode(data.getvalue()).decode()

    def submit(self, photo, key, boxes=None, days_ago=0):
        time = (datetime.now(timezone.utc)-timedelta(days=days_ago)).isoformat()
        return {"request_id":key,"photo":photo,"area":"教学区","note":"观察记录","boxes":boxes or [[0,0,1,1]],
                "observed_at":time}

    def test_cold_start_review_repeat_and_reunion(self):
        photo = self.photo()
        two_boxes = [[0,0,.5,1],[.5,0,.5,1]]
        preview,_ = self.call("/api/identify",{"photo":photo,"boxes":two_boxes},self.member)
        self.assertEqual(preview["reference_count"],0)
        self.assertEqual([r["candidates"] for r in preview["results"]],[[],[]])
        self.assertFalse(list(self.app.media.iterdir()))
        self.assertEqual(self.call("/api/home")[0]["stats"],{"cats":0,"active":0,"pending":0})

        submission = self.submit(photo,"same-request",two_boxes,days_ago=3)
        def send(_):
            return self.call("/api/sightings",submission,self.member)[0]["sightings"]
        with ThreadPoolExecutor(2) as pool:
            a,b = pool.map(send,range(2))
        self.assertEqual([x["id"] for x in a],[x["id"] for x in b])
        s,t = a
        self.call("/api/sightings",dict(submission,note="其他内容"),self.member,409)
        self.call("/api/sightings",dict(submission,request_id="other"),self.reviewer,409)
        self.call(s["photo_url"],expected=404)
        self.call(s["frame_url"],expected=404)
        self.call(s["photo_url"],cookie=self.member)
        self.call("/api/review",cookie=self.member,expected=403)
        self.assertEqual(len(self.call("/api/review",cookie=self.reviewer)[0]["sightings"]),2)
        action = {"action":"new","name":"小橘","reason":"左耳尖有显著缺口"}
        self.call(f"/api/review/{s['id']}",action,self.member,403)
        profile = self.call(f"/api/review/{s['id']}",action,self.reviewer)[0]["cat_id"]
        match = {"action":"match","cat_id":profile,"reason":"复核耳尖与侧身花纹"}
        self.call(f"/api/review/{t['id']}",match,self.reviewer,409)
        self.call(s["photo_url"])
        self.call(s["frame_url"],expected=404)
        t_action = dict(action,name="小白")
        self.call(f"/api/review/{t['id']}",dict(t_action,catalog_revision=0),self.reviewer,409)
        other = self.call(f"/api/review/{t['id']}",t_action,self.reviewer)[0]["cat_id"]
        self.assertEqual(self.call("/api/home")[0]["stats"],{"cats":2,"active":2,"pending":0})

        result,_ = self.call("/api/identify",{"photo":photo,"boxes":[two_boxes[0]]},self.member)
        self.assertIn(profile,[c["id"] for c in result["results"][0]["candidates"]])
        self.assertIsNone(result["results"][0]["breed_hint"])
        reunion = self.submit(self.photo(1),"later",[two_boxes[0]])
        reunion["suggested_cat_ids"] = [profile]
        r = self.call("/api/sightings",reunion,self.member)[0]["sightings"][0]
        self.assertEqual(r["suggested_cat_id"],profile)
        self.call(f"/api/review/{r['id']}",match,self.reviewer)
        me = self.call("/api/me",cookie=self.member)[0]
        self.assertEqual(me["reunions"][0]["days"],3)
        self.assertEqual(me["reunions"][0]["first_photo_url"],s["photo_url"])
        cat = self.call(f"/api/cats/{profile}")[0]["cat"]
        self.assertEqual((cat["sightings"],cat["breed_status"]),(2,"unknown"))
        self.call(f"/api/cats/{profile}/aliases",{"name":"食堂大橘"},self.member)
        alias = self.call("/api/review",cookie=self.reviewer)[0]["aliases"][0]
        self.call(f"/api/aliases/{alias['id']}/review",{"approve":True},self.reviewer)
        self.assertIn("食堂大橘",self.call(f"/api/cats/{profile}")[0]["cat"]["aliases"])
        self.call(f"/api/cats/{profile}/breed",{"breed":"示例品种","evidence":""},self.reviewer,400)
        self.call(f"/api/cats/{profile}/breed",{"breed":"示例品种","evidence":"测试凭证编号"},self.reviewer)
        self.assertEqual(self.call(f"/api/cats/{profile}")[0]["cat"]["breed_status"],"verified")
        self.call(f"/api/cats/{other}/breed",{"breed":"示例品种","evidence":"测试凭证二"},self.reviewer)
        matched = self.call("/api/identify",{"photo":photo,"boxes":[two_boxes[0]]},self.member)[0]["results"][0]
        self.assertEqual(set(matched["breed_hint"]["cat_ids"]),{profile,other})
        self.assertEqual(matched["breed_hint"]["label"],"示例品种")
        self.call(f"/api/cats/{other}/breed",{"breed":"其他品种","evidence":"修订测试凭证二"},self.reviewer)
        conflicted = self.call("/api/identify",{"photo":photo,"boxes":[two_boxes[0]]},self.member)[0]["results"][0]
        self.assertIsNone(conflicted["breed_hint"])
        self.call(f"/api/cats/{other}/breed",{"breed":"","evidence":""},self.reviewer)
        revoked = self.call("/api/identify",{"photo":photo,"boxes":[two_boxes[0]]},self.member)[0]["results"][0]
        self.assertIsNone(revoked["breed_hint"])
        self.call(f"/api/review/{r['id']}",{"action":"reopen","reason":"撤回错误归档"},self.reviewer)
        self.assertEqual(self.call("/api/me",cookie=self.member)[0]["reunions"],[])
        self.call(r["photo_url"],expected=404)
        with closing(connect(self.app.db_path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM audit").fetchone()[0],9)
        thumb = self.call(f"/api/cats/{profile}")[0]["cat"]["thumbnail_url"]
        with Image.open(io.BytesIO(self.call(thumb)[0])) as image:
            self.assertLessEqual(max(image.size),320)
        with tempfile.TemporaryDirectory() as scratch:
            dest = Path(scratch)/"snapshot.zip"
            backup(self.app.data,self.app.media,dest)
            with ZipFile(dest) as archive:
                archive.extractall(Path(scratch)/"restore")
            restored = App(Path(scratch)/"restore",None)
            active_app,self.app=self.app,restored
            self.assertIsNone(self.call("/api/me",cookie=self.member)[0]["user"])
            self.assertEqual(self.call("/api/home")[0]["stats"]["cats"],2)
            self.call(thumb)
            self.app=active_app

    def test_personal_album_and_receipt_follow_review_changes(self):
        album = "/api/me/album"
        self.call(album, expected=401)
        self.assertEqual(self.call(album, cookie=self.member)[0], {"visits":[], "campus_total":0, "pending":0})
        def submit(n, area, days, boxes=None):
            payload = dict(self.submit(self.photo(n), str(n), boxes, days), area=area)
            return self.call("/api/sightings", payload, self.member)[0]["sightings"]

        first, second = submit(0, "图书馆", 3, [[0,0,.5,1],[.5,0,.5,1]])
        receipt = "/api/me/frames/" + str(first["frame_id"])
        self.call(receipt, expected=401)
        self.call(receipt, cookie=self.reviewer, expected=404)
        self.assertEqual(self.call(album, cookie=self.member)[0]["pending"], 2)
        cid = self.call(f"/api/review/{first['id']}", {"action":"new","name":"小橘","reason":"人工复核"},
                        self.reviewer)[0]["cat_id"]
        view = lambda: self.call(receipt, cookie=self.member)[0]["sightings"]
        self.assertEqual([(s["status"],s["encounter_number"]) for s in view()], [("confirmed",1),("pending",None)])
        latest = submit(1, "食堂", 0)[0]
        middle = submit(2, "图书馆", 2)[0]
        match = {"action":"match","cat_id":cid,"reason":"人工复核"}
        for item in (latest,middle):
            self.call(f"/api/review/{item['id']}", match, self.reviewer)
        current = self.call(album, cookie=self.member)[0]
        self.assertEqual((current["campus_total"], current["pending"]), (1,1))
        self.assertEqual([(v["area"],v["encounters"],v["sighting_id"],v["first_at"]) for v in current["visits"]],
                         [("食堂",1,latest["id"],latest["observed_at"]),("图书馆",2,middle["id"],first["observed_at"])])
        self.assertEqual(self.call(album, cookie=self.reviewer)[0], {"visits":[],"campus_total":1,"pending":0})
        latest_path = "/api/me/frames/" + str(latest["frame_id"])
        self.assertEqual(self.call(latest_path, cookie=self.member)[0]["sightings"][0]["encounter_number"], 3)
        self.call(f"/api/review/{first['id']}", {"action":"reopen","reason":"重新核对"}, self.reviewer)
        self.assertIsNone(view()[0]["encounter_number"])
        self.assertEqual(self.call(latest_path, cookie=self.member)[0]["sightings"][0]["encounter_number"], 2)
        self.call(f"/api/review/{second['id']}", {"action":"reject","reason":"无有效特征"}, self.reviewer)
        self.assertEqual(self.call(album, cookie=self.member)[0]["pending"], 1)
        self.assertEqual(view()[1]["status"], "rejected")

    def test_sessions_recover_and_validation(self):
        credentials = {"email":"lost@example.edu","password":"first-password","nickname":"小林"}
        registered,headers = self.call("/api/register",credentials)
        old_session = headers["Set-Cookie"].split(";")[0]
        reset = {"email":credentials["email"],"password":"second-password","recovery_code":registered["recovery_code"]}
        renewed,headers = self.call("/api/recover",reset)
        new_session = headers["Set-Cookie"].split(";")[0]
        self.assertNotEqual(renewed["recovery_code"],registered["recovery_code"])
        self.assertIsNone(self.call("/api/me",cookie=old_session)[0]["user"])
        self.call("/api/recover",reset,expected=401)
        self.call("/api/login",credentials,expected=401)
        self.call("/api/login",{"email":credentials["email"],"password":reset["password"]})
        self.call("/api/identify",{"photo":"bad","boxes":[[0,0,1,1]]},new_session,400)
        self.call("/api/identify",{"photo":self.photo(),"boxes":[[0,0,1,1]]*2},new_session,400)
        self.call("/api/account/delete",{"password":reset["password"]},new_session)
        self.assertIsNone(self.call("/api/me",cookie=new_session)[0]["user"])

    def test_returns_the_actual_matching_reference(self):
        def submit(payload):
            return self.call("/api/sightings",payload,self.member)[0]["sightings"][0]
        good = submit(self.submit(self.photo(),"clear-reference",days_ago=2))
        cid = self.call(f"/api/review/{good['id']}",{"action":"new","name":"测试猫","reason":"人工核实"},
                        self.reviewer)[0]["cat_id"]
        flat = io.BytesIO()
        Image.new("RGB",(300,180),"#777777").save(flat,"PNG")
        poor = submit(self.submit(base64.b64encode(flat.getvalue()).decode(),"weak-reference"))
        self.call(f"/api/review/{poor['id']}",{"action":"match","cat_id":cid,"reason":"另有线下身份记录"},self.reviewer)
        self.assertEqual(self.call(f"/api/cats/{cid}")[0]["cat"]["photo_url"],poor["photo_url"])
        query = {"photo":self.photo(1),"boxes":[[0,0,1,1]]}
        preview = self.call("/api/identify",query,self.member)[0]["results"][0]["candidates"][0]
        fresh = submit(self.submit(query["photo"],"pending-query"))
        reviewed = self.call("/api/review",cookie=self.reviewer)[0]["sightings"][0]["candidates"][0]
        for candidate in (preview,fresh["candidates"][0],reviewed):
            self.assertEqual(candidate["reference_id"],good["id"])
            self.assertEqual(candidate["photo_url"],good["photo_url"])
            self.assertEqual(candidate["thumbnail_url"],f"/media/thumb/{good['id']}.jpg")


if __name__ == "__main__":
    unittest.main()
