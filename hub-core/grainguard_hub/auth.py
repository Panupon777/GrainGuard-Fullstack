"""Pi-local accounts and explicitly approved read-only remote sessions.

The remote listener MUST wrap the app in OnlineOnlyApp and disable proxy headers.
No client header or JSON field can establish the trusted local channel.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

TTL = 12 * 3600
ITERATIONS = 600_000
SITE_DEFINITIONS = (
    ("pumpkintec", "PumpkinTec", "live", 1),
    ("uengliangseng", "โรงสีไฟอึ้งเลี่ยงเส็ง", "mock", 6),
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def channel(scope):
    if scope.get("gg_channel") == "online":
        return "online"
    try:
        host = dict(scope.get("headers", [])).get(b"host",b"").decode("ascii",errors="ignore")
        hostname = urlsplit("//"+host).hostname
        local_host = hostname in ("localhost","127.0.0.1","::1")
        return "local" if local_host and ipaddress.ip_address(scope.get("client", ("", 0))[0]).is_loopback else "online"
    except ValueError:
        return "online"


def cookie_name(scope):
    return "gg_local_session" if channel(scope) == "local" else "gg_online_session"


class OnlineOnlyApp:
    """Trusted entry point for the external listener, including localhost proxies."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(dict(scope, gg_channel="online"), receive, send)


class AuthStore:
    def __init__(self, data_dir):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "accounts.sqlite3")
        self.lock = threading.RLock()
        self.attempts = OrderedDict()
        self.public_origin = os.environ.get("GG_PUBLIC_ORIGIN", "").strip().rstrip("/")
        if self.public_origin:
            parsed = urlsplit(self.public_origin)
            if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
                raise ValueError("GG_PUBLIC_ORIGIN must be one HTTPS origin without path or credentials")
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, phone TEXT UNIQUE,
                  full_name TEXT NOT NULL, role TEXT NOT NULL, salt TEXT NOT NULL, password TEXT NOT NULL,
                  account_channel TEXT NOT NULL, access TEXT NOT NULL, last_seen REAL NOT NULL DEFAULT 0,
                  monitoring REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sessions (
                  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, csrf TEXT NOT NULL,
                  channel TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            self._migrate_sites(db)
        os.chmod(self.path, 0o600)

    def _migrate_sites(self, db):
        """Transactional, idempotent migration; never modifies the real Hub DB."""
        db.execute("BEGIN IMMEDIATE")
        columns = {r["name"]:r for r in db.execute("PRAGMA table_info(users)")}
        if columns["phone"]["notnull"]:
            db.execute("ALTER TABLE users RENAME TO users_legacy_phone")
            db.execute("""CREATE TABLE users (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, phone TEXT UNIQUE,
                full_name TEXT NOT NULL, role TEXT NOT NULL, salt TEXT NOT NULL, password TEXT NOT NULL,
                account_channel TEXT NOT NULL, access TEXT NOT NULL, last_seen REAL NOT NULL DEFAULT 0,
                monitoring REAL NOT NULL DEFAULT 0)""")
            db.execute("INSERT INTO users SELECT * FROM users_legacy_phone")
            db.execute("DROP TABLE users_legacy_phone")
        db.execute("""CREATE TABLE IF NOT EXISTS sites (
            id TEXT PRIMARY KEY,name TEXT NOT NULL,mode TEXT NOT NULL,machine_count INTEGER NOT NULL,
            invite_code TEXT UNIQUE NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS memberships (
            user_id INTEGER NOT NULL,site_id TEXT NOT NULL,local_admin INTEGER NOT NULL DEFAULT 0,
            online_access TEXT NOT NULL,last_seen REAL NOT NULL DEFAULT 0,monitoring REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id,site_id))""")
        if "site_id" not in {r["name"] for r in db.execute("PRAGMA table_info(sessions)")}:
            db.execute("ALTER TABLE sessions ADD COLUMN site_id TEXT")
        old_code = db.execute("SELECT value FROM meta WHERE key='invite_code'").fetchone()
        for sid,name,mode,count in SITE_DEFINITIONS:
            code = old_code[0] if sid == "pumpkintec" and old_code else secrets.token_urlsafe(18)
            db.execute("INSERT OR IGNORE INTO sites VALUES (?,?,?,?,?)",(sid,name,mode,count,code))
        if not db.execute("SELECT 1 FROM meta WHERE key='sites_schema_v1'").fetchone():
            for user in db.execute("SELECT * FROM users").fetchall():
                local = user["account_channel"] in ("local","both")
                online_access="approved" if user["account_channel"]=="both" else "unlinked" if local else user["access"]
                db.execute("INSERT OR IGNORE INTO memberships(user_id,site_id,local_admin,online_access,last_seen,monitoring) VALUES (?,?,?,?,?,?)",
                    (user["id"],"pumpkintec",int(local),online_access,user["last_seen"],user["monitoring"]))
            # Old sessions held global access: force one safe sign-in after migration.
            db.execute("DELETE FROM sessions")
            db.execute("INSERT INTO meta VALUES ('sites_schema_v1','1')")
            db.execute("DELETE FROM meta WHERE key='invite_code'")

    def site(self, site_id):
        with self.db() as db:
            row=db.execute("SELECT id,name,mode,machine_count FROM sites WHERE id=?",(site_id,)).fetchone()
        return dict(row) if row else None

    def provision_site_owner(self, username, password, full_name,site_id, role="entrepreneur"):
        """Administrative provisioning; caller supplies secrets outside source/logs."""
        if not self.site(site_id) or not isinstance(username,str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{3,31}",username):
            raise ValueError("Invalid site or username")
        if not isinstance(password,str) or not 8<=len(password)<=128 or not isinstance(full_name,str) or not 1<=len(full_name)<=100 or role not in ("entrepreneur","employee"):
            raise ValueError("Invalid owner fields")
        salt=secrets.token_hex(16)
        hashed=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),ITERATIONS).hex()
        with self.lock,self.db() as db:
            existing=db.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()
            if existing:
                uid=existing[0]
                if db.execute("SELECT 1 FROM memberships WHERE user_id=? AND site_id<>?",(uid,site_id)).fetchone():
                    raise ValueError("Existing identity belongs to another site")
                db.execute("UPDATE users SET salt=?,password=?,full_name=?,role=?,account_channel='both',access='admin' WHERE id=?",(salt,hashed,full_name,role,uid))
            else:
                uid=db.execute("INSERT INTO users(username,phone,full_name,role,salt,password,account_channel,access) VALUES (?,NULL,?,?,?,?,'both','admin')",(username,full_name,role,salt,hashed)).lastrowid
            db.execute("INSERT INTO memberships(user_id,site_id,local_admin,online_access) VALUES (?,?,1,'approved') ON CONFLICT(user_id,site_id) DO UPDATE SET local_admin=1,online_access='approved'",(uid,site_id))
            db.execute("DELETE FROM sessions WHERE user_id=?",(uid,))
        return uid

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def throttle(self, key, limit=10):
        now = time.time()
        with self.lock:
            hits = [t for t in self.attempts.pop(key, []) if now - t < 300]
            if len(hits) >= limit:
                self.attempts[key] = hits
                raise HTTPException(429, "Too many attempts. Try again in five minutes.")
            self.attempts[key] = hits + [now]
            while len(self.attempts) > 2048:
                self.attempts.popitem(last=False)

    def session(self, request):
        raw = request.cookies.get(cookie_name(request.scope), "")
        if not raw:
            return None
        with self.db() as db:
            row = db.execute("SELECT u.*,s.csrf,s.channel,s.expires,s.site_id,m.local_admin,m.online_access FROM sessions s JOIN users u ON u.id=s.user_id LEFT JOIN memberships m ON m.user_id=u.id AND m.site_id=s.site_id WHERE s.token=? AND s.expires>?", (digest(raw), time.time())).fetchone()
        if row and row["channel"] == channel(request.scope):
            result=dict(row)
            result["access"]=("admin" if row["local_admin"] else "revoked") if row["channel"]=="local" else (row["online_access"] or "unlinked")
            return result
        return None

    def touch(self, user_id, site_id=None, monitoring=False):
        now = time.time()
        col = "monitoring" if monitoring else "last_seen"
        with self.db() as db:
            db.execute("UPDATE memberships SET " + col + "=? WHERE user_id=? AND site_id=? AND " + col + "<?", (now, user_id,site_id, now-15))

    def create_session(self, request, user_id, mode, site_id=None):
        raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            # Keep bounded server-side state even if a user signs in repeatedly.
            db.execute("DELETE FROM sessions WHERE user_id=? AND channel=?", (user_id,mode))
            db.execute("INSERT INTO sessions(token,user_id,csrf,channel,expires,site_id) VALUES (?,?,?,?,?,?)", (digest(raw), user_id, csrf, mode, time.time()+TTL,site_id))
        cookie = cookie_name(request.scope)
        request.scope["headers"] = [(k,v) for k,v in request.scope["headers"] if k != b"cookie"] + [(b"cookie", (cookie+"="+raw).encode())]
        request._cookies = {cookie: raw}
        response = JSONResponse(self.dto(request))
        secure = request.url.scheme == "https" or (mode == "online" and bool(self.public_origin))
        response.set_cookie(cookie, raw, max_age=TTL, httponly=True, secure=secure, samesite="strict", path="/")
        return response

    def dto(self, request):
        session = self.session(request)
        if not session:
            return {"authenticated": False, "channel": channel(request.scope)}
        self.touch(session["id"],session["site_id"])
        return {"authenticated": True, "user": {key: session[key] for key in ("id", "username", "phone", "full_name", "role")},
                "channel": session["channel"], "access": session["access"], "csrf_token": session["csrf"],"site":self.site(session["site_id"])}


def csrf_check(request, session=None, public_origin=""):
    origin = request.headers.get("origin")
    expected = str(request.base_url).rstrip("/")
    if channel(request.scope) == "online":
        if public_origin:
            expected = public_origin
        elif request.url.hostname not in ("localhost","127.0.0.1","::1"):
            raise HTTPException(403,"Configure the HTTPS public origin before remote access")
    if not origin or origin != expected:
        raise HTTPException(403, "Cross-origin request refused")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site request refused")
    token = request.headers.get("x-gg-csrf", "")
    if not hmac.compare_digest(token.encode(), (session["csrf"] if session else "1").encode()):
        raise HTTPException(403, "CSRF check failed")


def require_admin(request):
    session = request.app.state.auth_store.session(request)
    if not session:
        raise HTTPException(401, "Sign in required")
    if channel(request.scope) != "local" or session["channel"] != "local" or session["access"] != "admin":
        raise HTTPException(403, "Pi-local administrator required")
    if session["site_id"] != request.app.state.site_id:
        raise HTTPException(403,"Site permission required")
    return session


class AccessMiddleware:
    def __init__(self, app, store,site_id):
        self.app, self.store,self.site_id = app, store,site_id

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path, method = scope["path"], scope["method"]
        async def reply(status, detail):
            await JSONResponse({"detail": detail}, status_code=status, headers={"Cache-Control": "no-store"})(scope, receive, send)
        try:
            session = self.store.session(request)
            if method not in ("GET", "HEAD", "OPTIONS"):
                # Read the (capped) body before any accept/reject decision: answering a POST with unread body bytes
                # resets the connection and the client gets a network error instead of the 401/403.
                size = 0
                chunks = []
                while True:
                    msg = await receive()
                    if msg["type"] == "http.disconnect":
                        return
                    size += len(msg.get("body", b""))
                    if size > 16384:
                        return await reply(413, "Request too large")
                    chunks.append(msg)
                    if not msg.get("more_body"):
                        break
                async def replay():
                    return chunks.pop(0) if chunks else {"type": "http.request", "body": b""}
                receive = replay
                csrf_check(request, session if path not in ("/auth/login", "/auth/signup") else None, self.store.public_origin)
            if path == "/" and (not session or session["access"] not in ("admin","approved")):
                from fastapi.responses import RedirectResponse
                await RedirectResponse("/login/"+channel(scope)+".html", status_code=303)(scope,receive,send)
                return
            if path.startswith(("/api/", "/local-api/")):
                if not session:
                    return await reply(401, "Sign in required")
                if session["access"] not in ("admin", "approved"):
                    return await reply(403, "Local approval required")
                if session["site_id"]!=self.site_id:
                    return await reply(403,"Site permission required")
                if method not in ("GET", "HEAD", "OPTIONS"):
                    if channel(scope) != "local" or session["channel"] != "local" or session["access"] != "admin":
                        return await reply(403, "Pi-local administrator required")
                elif path.startswith("/api/"):
                    self.store.touch(session["id"],session["site_id"], monitoring=True)
            async def secure_send(message):
                if message["type"] == "http.response.start":
                    message["headers"] = [(k,v) for k,v in message["headers"] if k.lower() != b"cache-control"] + [(b"cache-control",b"no-store"),(b"x-content-type-options",b"nosniff"),(b"referrer-policy",b"same-origin"),(b"x-frame-options",b"DENY")]
                await send(message)
            await self.app(scope, receive, secure_send)
        except HTTPException as exc:
            await reply(exc.status_code, exc.detail)


def install_auth(app, cfg, auth_store=None,site_id="pumpkintec"):
    store = auth_store if auth_store is not None else AuthStore(cfg.data_dir)
    app.state.auth_store = store
    app.state.site_id=site_id
    app.add_middleware(AccessMiddleware, store=store,site_id=site_id)

    def mode_for(request, body):
        mode = body.get("channel", channel(request.scope))
        if mode not in ("local", "online"):
            raise HTTPException(422, "Invalid channel")
        if mode != channel(request.scope):
            raise HTTPException(403, "Use the matching local or online listener")
        return mode

    def body_text(body, key, minimum, maximum):
        value = body.get(key)
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
            raise HTTPException(422, "Invalid " + key)
        return value.strip()

    @app.get("/auth/session")
    def auth_session(request: Request):
        return store.dto(request)

    @app.post("/auth/signup")
    def signup(body: dict, request: Request):
        store.throttle((request.client.host, "signup"), 5)
        mode = mode_for(request, body)
        username = body_text(body, "username", 4, 32).lower()
        phone = body_text(body, "phone", 8, 20)
        full_name = body_text(body, "full_name", 2, 100)
        role = body.get("role")
        password = body.get("password")
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{3,31}", username):
            raise HTTPException(422, "Invalid username or phone")
        phone = re.sub(r"[ -]", "", phone)
        if phone.startswith("+66"):
            phone = "0" + phone[3:]
        if not re.fullmatch(r"0[0-9]{8,9}", phone) or len(full_name.split()) < 2 or any(ord(c)<32 for c in full_name):
            raise HTTPException(422, "Invalid phone or full_name")
        if role not in ("entrepreneur", "employee") or not isinstance(password, str) or not 8 <= len(password) <= 128 or password != body.get("confirm_password"):
            raise HTTPException(422, "Invalid role or password (8–128 characters; confirmation must match)")
        salt = secrets.token_hex(16)
        hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
        with store.lock, store.db() as db:
            if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 500:
                raise HTTPException(409, "Account limit reached")
            site_id=None
            if mode=="local":
                if db.execute("SELECT 1 FROM memberships WHERE local_admin=1").fetchone():
                    site_id=require_admin(request)["site_id"]
                else:
                    site_id="pumpkintec"
            try:
                cursor = db.execute("INSERT INTO users(username,phone,full_name,role,salt,password,account_channel,access) VALUES (?,?,?,?,?,?,?,?)", (username,phone,full_name,role,salt,hashed,mode,"admin" if mode == "local" else "unlinked"))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Username or phone is already registered")
            user_id = cursor.lastrowid
            if mode == "local":
                db.execute("INSERT INTO memberships(user_id,site_id,local_admin,online_access) VALUES (?,?,1,'unlinked')",(user_id,site_id))
        return store.create_session(request, user_id, mode,site_id)

    @app.post("/auth/login")
    def login(body: dict, request: Request):
        store.throttle((request.client.host, "login"))
        mode = mode_for(request, body)
        identifier = body_text(body, "identifier", 1, 80).lower()
        password = body.get("password", "")
        if not isinstance(password, str) or len(password) > 128:
            raise HTTPException(422, "Invalid password")
        phone_identifier = re.sub(r"[ -]", "",identifier)
        if phone_identifier.startswith("+66"):
            phone_identifier = "0" + phone_identifier[3:]
        with store.db() as db:
            user = db.execute("SELECT * FROM users WHERE username=? OR phone=?", (identifier,phone_identifier)).fetchone()
        salt = bytes.fromhex(user["salt"]) if user else b"\0"*16
        hashed = hashlib.pbkdf2_hmac("sha256",password.encode(),salt,ITERATIONS).hex()
        if not user or not hmac.compare_digest(hashed,user["password"]) or user["account_channel"] not in (mode,"both"):
            raise HTTPException(401,"Invalid credentials")
        with store.db() as db:
            memberships=db.execute("SELECT * FROM memberships WHERE user_id=? ORDER BY site_id",(user["id"],)).fetchall()
        selected=next((m for m in memberships if mode=="online" or m["local_admin"]),None)
        if mode=="local" and not selected:
            raise HTTPException(403,"No local administration permission")
        return store.create_session(request,user["id"],mode,selected["site_id"] if selected else None)

    @app.post("/auth/logout")
    def logout(request: Request):
        with store.db() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (digest(request.cookies.get(cookie_name(request.scope),"")),))
        response = JSONResponse({"ok":True})
        response.delete_cookie(cookie_name(request.scope),path="/")
        return response

    @app.post("/auth/join")
    def join(body: dict, request: Request):
        session = store.session(request)
        if not session:
            raise HTTPException(401,"Sign in required")
        if session["channel"] != "online":
            raise HTTPException(403,"Online account required")
        store.throttle((session["id"],"join"),5)
        code = body_text(body,"code",1,100)
        with store.lock,store.db() as db:
            # Re-read after taking the shared lock: simultaneous code requests
            # cannot attach one previously unlinked session to two sites.
            session=store.session(request)
            if not session or session["channel"]!="online":
                raise HTTPException(401,"Sign in required")
            sites=db.execute("SELECT id,invite_code FROM sites").fetchall()
            row=next((s for s in sites if hmac.compare_digest(code.encode(),s["invite_code"].encode())),None)
            if not row:
                raise HTTPException(400,"Invalid code")
            site_id=row["id"]
            if session["site_id"] and session["site_id"]!=site_id:
                raise HTTPException(409,"Account is linked to another site")
            if session["access"] == "revoked":
                raise HTTPException(403,"Access revoked. Contact the local administrator.")
            if session["access"] == "unlinked":
                db.execute("INSERT INTO memberships(user_id,site_id,local_admin,online_access) VALUES (?,?,0,'pending') ON CONFLICT(user_id,site_id) DO UPDATE SET online_access='pending'",(session["id"],site_id))
                db.execute("UPDATE sessions SET site_id=? WHERE token=?",(site_id,digest(request.cookies.get(cookie_name(request.scope),""))))
        return store.dto(request)

    @app.get("/auth/access")
    def access(request: Request):
        admin=require_admin(request)
        with store.db() as db:
            code = db.execute("SELECT invite_code FROM sites WHERE id=?",(admin["site_id"],)).fetchone()
            users = db.execute("SELECT u.id,u.username,u.phone,u.full_name,u.role,m.online_access AS access,m.last_seen,m.monitoring FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.site_id=? AND m.local_admin=0 ORDER BY u.id DESC LIMIT 500",(admin["site_id"],)).fetchall()
        return {"code":code[0] if code else None,"site":store.site(admin["site_id"]),"users":[{**{k:u[k] for k in ("id","username","phone","full_name","role","access","last_seen")},"monitoring":u["access"] == "approved" and time.time()-u["monitoring"]<45} for u in users]}

    def change_access(user_id, request, value):
        admin=require_admin(request)
        with store.db() as db:
            user = db.execute("SELECT online_access AS access FROM memberships WHERE user_id=? AND site_id=? AND local_admin=0",(user_id,admin["site_id"])).fetchone()
            if not user:
                raise HTTPException(404,"Online user not found")
            if value == "approved" and user[0] not in ("pending","revoked","approved"):
                raise HTTPException(409,"User has not requested access")
            db.execute("UPDATE memberships SET online_access=? WHERE user_id=? AND site_id=?",(value,user_id,admin["site_id"]))
        return {"ok":True,"access":value}

    @app.post("/auth/access/{user_id}/approve")
    def approve(user_id: int,request: Request):
        return change_access(user_id,request,"approved")

    @app.post("/auth/access/{user_id}/revoke")
    def revoke(user_id: int,request: Request):
        return change_access(user_id,request,"revoked")

    @app.post("/auth/code/rotate")
    def rotate(request: Request):
        admin=require_admin(request)
        code = secrets.token_urlsafe(18)
        with store.lock,store.db() as db:
            db.execute("UPDATE sites SET invite_code=? WHERE id=?",(code,admin["site_id"]))
            db.execute("UPDATE memberships SET online_access='unlinked' WHERE online_access='pending' AND site_id=?",(admin["site_id"],))
        return {"code":code}
