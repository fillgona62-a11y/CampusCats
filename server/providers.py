"""Account-scoped campus assistant providers."""
import http.client
import ipaddress
import json
import os
import socket
import ssl
from contextvars import ContextVar
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from media import Problem

active = ContextVar("campus_agent_provider", default=None)
FIELDS = ("base_url", "chat_model", "vision_model", "protocol")


def text_field(body, key, limit, required=True):
    value = body.get(key, "")
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise Problem("接入参数格式无效。")
    value = value.strip()
    if required and not value:
        raise Problem("请填写接口地址、对话模型和 API Key。")
    return value


def base_url(value):
    try:
        u = urlsplit(value)
        port = u.port
        if (u.scheme != "https" or not u.hostname or u.username is not None or u.password is not None
                or u.query or u.fragment or "\\" in value or not value.isascii() or " " in value or port == 0):
            raise ValueError
    except ValueError:
        raise Problem("请填写服务商的 HTTPS 接口地址，查询参数和密钥请勿写入地址。") from None
    return value.rstrip("/").removesuffix("/chat/completions").rstrip("/")


def public_socket(address, timeout, source_address=None):
    # Connect to the exact numeric address checked here. TLS still verifies the provider hostname.
    for family, kind, proto, _, sockaddr in socket.getaddrinfo(*address, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global or ip.is_multicast or getattr(ip, "ipv4_mapped", None) or getattr(ip, "sixtofour", None) or getattr(ip, "teredo", None) or (ip.version == 6 and ip in ipaddress.ip_network("64:ff9b::/96")):
            continue
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock
        except OSError:
            sock.close()
    raise OSError("无法连接到公网 HTTPS 接口。")


def completion(cfg, payload):
    u = urlsplit(cfg["base_url"])
    conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=cfg["timeout"],
                                       context=ssl.create_default_context())
    conn._create_connection = public_socket
    try:
        conn.request("POST", u.path.rstrip("/") + "/chat/completions", json.dumps(payload).encode(),
                     {"Content-Type":"application/json", "Authorization":"Bearer " + cfg["api_key"]})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError(f"服务商返回 HTTP {response.status}，请检查密钥、接口地址和模型名。")
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("服务商响应过大。")
        return json.loads(data)
    except http.client.HTTPException:
        raise OSError("接口响应无效。") from None
    finally:
        conn.close()


def cipher(folder, create=False):
    path = folder / "agent-key.fernet"
    if create and not path.exists():
        # The caller holds the SQLite writer lock until the encrypted record is committed.
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
            file.write(Fernet.generate_key())
            file.flush()
            os.fsync(file.fileno())
    try:
        return Fernet(path.read_bytes())
    except (OSError, ValueError):
        raise Problem("服务端暂时无法读取 Agent 密钥文件。", 503) from None


def saved(db, owner):
    return db.execute("SELECT * FROM agent_providers WHERE owner=?", (owner,)).fetchone()


def public(row):
    return {k:row[k] for k in FIELDS} if row else None


def effective(db, uid, folder):
    row = db.execute("SELECT * FROM agent_providers WHERE owner IN (0,?) ORDER BY owner DESC LIMIT 1",
                     (uid or 0,)).fetchone()
    if not row:
        return None
    try:
        key = cipher(folder).decrypt(row["secret"]).decode()
    except (InvalidToken, Problem):
        # Gracefully fall back to local mode instead of breaking /api/identify with 503.
        return None
    return dict(public(row), api_key=key, enabled=True, timeout=25, scope="personal" if row["owner"] else "shared")


def configure(db, owner, body, folder):
    action = body.get("action")
    if action == "remove":
        db.execute("DELETE FROM agent_providers WHERE owner=?", (owner,))
        return {"ok":True}
    if action not in ("save", "test"):
        raise Problem("未知的配置操作。")
    if action == "save":
        db.execute("BEGIN IMMEDIATE")
    url = base_url(text_field(body, "base_url", 400))
    model = text_field(body, "chat_model", 160)
    vision = text_field(body, "vision_model", 160, False)
    protocol = body.get("protocol", "tools")
    if protocol not in ("tools", "chat"):
        raise Problem("未知的接口类型。")
    key = text_field(body, "api_key", 2048, False)
    if key and (not key.isascii() or " " in key):
        raise Problem("API Key 格式无效。")
    row = saved(db, owner)
    if not key:
        if not row or row["base_url"] != url:
            raise Problem("首次接入或更换地址时，请输入该服务的 API Key。")
        key = cipher(folder).decrypt(row["secret"]).decode()
    if action == "test":
        from agent import TOOLS
        payload = {"model":model, "messages":[{"role":"user","content":"请回复 OK。"}]}
        if protocol == "tools":
            payload.update(tools=TOOLS, tool_choice="auto")
        try:
            reply = completion({"base_url":url, "api_key":key, "timeout":15}, payload)
            message = reply["choices"][0]["message"]
            if not message.get("content") and not message.get("tool_calls"):
                raise KeyError
        except (OSError, ValueError, TypeError, AttributeError, IndexError, KeyError) as error:
            detail = str(error) if isinstance(error, ValueError) and str(error).startswith("服务商返回 HTTP ") else "请核对 HTTPS 地址、模型名和服务商返回的格式。"
            raise Problem("对话模型连接测试失败。" + detail, 422) from None
        vision_tested = False
        if vision:
            import base64
            import io
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (16, 16), "#d9822b").save(buf, format="JPEG", quality=80)
            tiny_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            v_payload = {
                "model": vision,
                "max_tokens": 32,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请回复 OK。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{tiny_b64}"}},
                    ],
                }],
            }
            try:
                v_reply = completion({"base_url":url, "api_key":key, "timeout":15}, v_payload)
                v_msg = v_reply["choices"][0]["message"]
                if not v_msg.get("content"):
                    raise KeyError
                vision_tested = True
            except (OSError, ValueError, TypeError, AttributeError, IndexError, KeyError) as error:
                detail = str(error) if isinstance(error, ValueError) and str(error).startswith("服务商返回 HTTP ") else "请核对视觉模型名是否支持图片输入。"
                raise Problem("对话模型已连通，但视觉模型测试失败。" + detail, 422) from None
        return {"ok":True, "model":model, "vision_model":vision or None, "vision_tested":vision_tested}
    secret = cipher(folder, create=True).encrypt(key.encode())
    db.execute("""INSERT INTO agent_providers(owner,base_url,chat_model,vision_model,protocol,secret)
        VALUES(?,?,?,?,?,?) ON CONFLICT(owner) DO UPDATE SET base_url=excluded.base_url,
        chat_model=excluded.chat_model,vision_model=excluded.vision_model,protocol=excluded.protocol,
        secret=excluded.secret""", (owner,url,model,vision,protocol,secret))
    return {"ok":True}
