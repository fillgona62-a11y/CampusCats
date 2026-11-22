"""Reproduce the 1000 visitor / 30 s pilot browse trial on loopback and temporary test data."""
import concurrent.futures
import http.client
import json
import math
import random
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

from PIL import Image

from app import App, LocalServer
from catalog import connect, iso
from media import jpeg_bytes, media_name


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def fixtures(app):
    with closing(connect(app.db_path)) as db, db:
        db.execute("INSERT INTO users(email,nickname,salt,password_hash,recovery_hash) "
                   "VALUES('benchmark@local.test','fixture',X'00',X'00','')")
        now = iso()
        for index in range(1,25):
            pixels = random.Random(index).randbytes(320*240*3)
            jpeg = jpeg_bytes(Image.frombytes("RGB",(320,240),pixels),320)
            name = media_name(jpeg)
            (app.media/name).write_bytes(jpeg)
            db.execute("INSERT INTO cats(id,name) VALUES(?,?)",(index,f"fixture-{index}"))
            db.execute("INSERT INTO frames(id,user_id,request_id,request_hash,image,area,note,observed_at) "
                       "VALUES(?,1,?,'',?,'Zone','',?)",(index,str(index),name,now))
            db.execute("INSERT INTO sightings(id,frame_id,box,crop,analysis,cat_id,status) "
                       "VALUES(?,?,'[0,0,1,1]',?,'{}',?,'confirmed')",(index,index,name,index))
            db.execute("INSERT INTO thumbnails(sighting_id,image) VALUES(?,?)",(index,name))


def visit(port, scheduled):
    requests = transferred = 0
    def get(path):
        nonlocal requests,transferred
        with closing(http.client.HTTPConnection("127.0.0.1",port,timeout=5)) as conn:
            conn.request("GET",path)
            reply = conn.getresponse()
            data = reply.read()
            if reply.status != 200:
                raise RuntimeError(f"{path}: HTTP {reply.status}")
            requests += 1
            transferred += len(data)
            return data
    try:
        get("/api/session")
        cats = json.loads(get("/api/home"))["cats"]
        for cat in cats[:3]:
            get(cat["thumbnail_url"])
        success = True
    except (OSError,RuntimeError,http.client.HTTPException):
        success = False
    return success,time.perf_counter()-scheduled,requests,transferred


def run():
    visitors, seconds = 1000, 30
    with tempfile.TemporaryDirectory() as folder:
        app = App(Path(folder),None)
        fixtures(app)
        with make_server("127.0.0.1",0,app,server_class=LocalServer,handler_class=Quiet) as server:
            thread = threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=48) as pool:
                    start = time.perf_counter()
                    jobs = []
                    for index in range(visitors):
                        scheduled = start + index*seconds/visitors
                        delay = scheduled-time.perf_counter()
                        if delay > 0:
                            time.sleep(delay)
                        jobs.append(pool.submit(visit,server.server_port,scheduled))
                    results = [job.result() for job in jobs]
                    elapsed = time.perf_counter()-start
            finally:
                server.shutdown()
                thread.join()
    durations = sorted(r[1] for r in results if r[0])
    pct95 = durations[math.ceil(.95*len(durations))-1] if durations else None
    return {"visitors":visitors, "successful_visits":len(durations), "duration_s":round(elapsed,2),
            "visit_p95_s":round(pct95,3) if pct95 is not None else None, "http_200":sum(r[2] for r in results),
            "body_MiB":round(sum(r[3] for r in results)/1048576,1)}


if __name__ == "__main__":
    report = run()
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report["successful_visits"]==report["visitors"] else 1)
