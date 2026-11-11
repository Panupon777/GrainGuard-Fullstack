"""REST API + dashboard for the hub (FastAPI)."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import tempfile
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import __version__
from . import errors as E
from .lifecycle import LABELS, REASONS
from .uplink import read_cpu_temp
from .auth import install_auth, require_admin

if TYPE_CHECKING:  # pragma: no cover
    from .app import Hub

MAC_RE = re.compile(r"^[0-9a-f]{12}$")
EVENT_TYPES_USER = None


class AssignBody(BaseModel):
    mac: Optional[str] = None
    label: Optional[str] = None
    unassign: bool = False
    expected_source_machine: Optional[int] = None
    expected_target_mac: Optional[str] = None


class ChangeBody(BaseModel):
    date: Optional[str] = None            # YYYY-MM-DD (local); default today
    reason: Optional[str] = None          # broke | scheduled | other
    note: Optional[str] = None


class LabelBody(BaseModel):
    label: Optional[str] = None           # real | false | unsure | null (= remove)
    note: Optional[str] = None


class CalBody(BaseModel):
    operator: str                         # who is pressing the button (audit trail, DF-53) - 2..40 characters
    reason: Optional[str] = None


class CmdBody(BaseModel):
    cmd: str
    mode: Optional[str] = None
    what: Optional[str] = None


def norm_mac(s: str) -> str:
    return re.sub(r"[^0-9a-f]", "", s.strip().lower())


def find_dashboard(cfg_path: str) -> Optional[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [cfg_path] if cfg_path else []
    cands += [os.path.join(here, "..", "..", "dashboard", "index.html"),
              os.path.join(here, "..", "dashboard", "index.html"),
              "/app/dashboard/index.html", "dashboard/index.html"]
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def create_app(hub: "Hub", auth_store=None,site_id="pumpkintec") -> FastAPI:
    app = FastAPI(title="GrainGuard HUB", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    cfg, eng, store = hub.cfg, hub.engine, hub.store
    install_auth(app, cfg,auth_store=auth_store,site_id=site_id)
    dashboard_config_path = os.path.join(cfg.data_dir, "dashboard-config.json")
    dashboard_config_lock = threading.RLock()

    def clean_dashboard_config(body: Dict[str, Any]) -> Dict[str, Any]:
        # The current Hub supports six machine slots. The UI starts with one
        # visible slot and an administrator can reveal the remaining slots.
        slots = body.get("visible_slots", [1])
        discovery, offline = body.get("discovery", "review"), body.get("offline", "keep")
        if (not isinstance(slots, list) or
                any(type(n) is not int or not 1 <= n <= 6 for n in slots)):
            raise ValueError("visible_slots must contain machine numbers 1..6")
        if discovery not in ("review", "temporary") or offline not in ("keep", "group"):
            raise ValueError("Unknown dashboard display policy")
        return {"visible_slots": sorted(set(slots)), "discovery": discovery, "offline": offline}

    def auth(request: Request) -> None:
        # Shared legacy tokens cannot bypass channel/session authorization.
        require_admin(request)

    def node_or_404(n: int) -> int:
        if not 1 <= n <= 6:
            raise HTTPException(404, "machine must be 1..6")
        return n

    @app.get("/local-api/status")
    def dashboard_status():
        return {"bridge": "grainguard-pi-native", "live": True, "default_visible_slots": [1]}

    @app.post("/local-api/auth", dependencies=[Depends(auth)])
    def dashboard_auth():
        return {"ok": True, "role": "admin"}

    @app.get("/local-api/config")
    def dashboard_config():
        with dashboard_config_lock:
            try:
                with open(dashboard_config_path, "r", encoding="utf-8") as fh:
                    return clean_dashboard_config(json.load(fh))
            except (OSError, ValueError, AttributeError, TypeError):
                return {"visible_slots": [1], "discovery": "review", "offline": "keep"}

    @app.post("/local-api/config", dependencies=[Depends(auth)])
    def save_dashboard_config(body: Dict[str, Any]):
        try:
            value = clean_dashboard_config(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        # Store beside the database, outside the dashboard's static directory.
        # Replace atomically so a power loss cannot leave partially written JSON.
        with dashboard_config_lock:
            tmp = None
            try:
                os.makedirs(cfg.data_dir, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cfg.data_dir,
                                                 prefix="dashboard-config-", suffix=".tmp", delete=False) as fh:
                    tmp = fh.name
                    json.dump(value, fh, ensure_ascii=False)
                    fh.write("\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.chmod(tmp, 0o600)
                os.replace(tmp, dashboard_config_path)
                tmp = None
            except OSError:
                raise HTTPException(503, "Cannot save dashboard configuration")
            finally:
                if tmp:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
        return value

    def prepare_dashboard_config(value: Dict[str, Any]) -> str:
        """Preflight a durable temporary file before changing the registry."""
        os.makedirs(cfg.data_dir, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cfg.data_dir,
                                             prefix="dashboard-config-", suffix=".tmp", delete=False) as fh:
                tmp = fh.name
                json.dump(value, fh, ensure_ascii=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            return tmp
        except BaseException:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise

    @app.get("/", response_class=HTMLResponse)
    def index():
        p = find_dashboard(cfg.dashboard_path)
        if not p:
            return HTMLResponse("<h1>GrainGuard HUB</h1><p>dashboard/index.html not found</p>", status_code=500)
        with open(p, "rb") as fh:
            return HTMLResponse(fh.read().decode("utf-8"), headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health():
        age = hub.tick_age()
        db_ok = True
        try:
            store.q1("SELECT 1 AS x")
        except Exception:
            db_ok = False
        ok = db_ok and age < 10
        body = {"ok": ok, "tick_age_s": round(age, 1), "db": db_ok, "mqtt": eng.mqtt_ok, "version": __version__}
        return JSONResponse(body, status_code=200 if ok else 503)

    @app.get("/api/nodes")
    def nodes():
        snap = eng.snapshot()
        hubd = snap["hub"]
        try:
            du = shutil.disk_usage(cfg.data_dir if os.path.isdir(cfg.data_dir) else ".")
            disk = int(round(100.0 * du.used / du.total))
        except Exception:
            disk = -1
        hubd.update({"version": __version__, "internet": hub.uplink.status(), "disk_pct": disk,
                     "cpu_temp": hub.cpu_temp(), "hub_ok": hub.tick_age() < 10, "server_ts": snap["now"]})
        return snap

    @app.get("/api/node/{n}/history")
    def history(n: int, minutes: int = Query(60, ge=1, le=7 * 1440)):
        node_or_404(n)
        h = store.history(n, minutes, eng.clock())
        mac = eng.slot_mac(n)
        h["mac"] = mac
        return h

    @app.get("/api/events")
    def events(limit: int = Query(50, ge=1, le=500), n: Optional[int] = None, before_id: Optional[int] = None,
               types: Optional[str] = None, hours: Optional[float] = None, codes: Optional[str] = None):
        tl = [t for t in (types or "").upper().split(",") if t] or None
        cl = [c for c in (codes or "").upper().split(",") if c] or None
        since = eng.clock() - hours * 3600 if hours else None
        rows = store.list_events(limit, n, before_id, tl, since, cl)
        by_mac = {s.mac: s for s in eng.states.values()}
        for r in rows:
            r["label"] = (eng.label_of(by_mac[r["mac"]]) if r["mac"] in by_mac and r["n"] and by_mac[r["mac"]].machine == r["n"] else
                          (eng.default_label(r["n"]) if r["n"] else "ฮับ"))
        return {"events": rows}

    # ------------------------------------------------------------ error codes
    @app.get("/api/errors/catalog")
    def errors_catalog():
        return {"codes": E.catalog_list(), "sev_th": E.SEV_TH, "scope_th": E.SCOPE_TH}

    @app.get("/api/errors")
    def errors_view(days: int = Query(30, ge=1, le=400)):
        now = eng.clock()
        day0 = store.day_bounds(store.date_of(now))[0]
        counts = store.err_counts(day0)
        with eng.lock:
            who = {s.mac: (s.machine or 0, eng.label_of(s)) for s in eng.states.values()}
            slot = {s.machine: s.mac for s in eng.states.values() if s.assigned}
            by_key = {k: eng.errors.entries(k) for k in set(list(who) + [E.HUB_KEY])}

        def label_of(key: str, n: int) -> str:
            if key == E.HUB_KEY:
                return "ฮับ / ทั้งโรงสี"
            current = who.get(key)
            return current[1] if current and current[0] == n else eng.default_label(n)

        def deco(code: str) -> Dict[str, Any]:
            i = E.info(code)
            return {"code": code, "sev": i.get("sev"), "scope": i.get("scope"), "th": i.get("th"),
                    "where": i.get("where"), "causes": i.get("causes", [])}

        active = []
        for a in eng.errors.all_active():
            d = deco(a["code"])
            d.update({"key": a["key"], "n": a["n"], "label": label_of(a["key"], a["n"]), "since": int(a["since"]),
                      "duration_s": int(now - a["since"]), "count_today": counts.get((a["code"], a["key"]), 1),
                      "detail": a.get("detail") or {}})
            active.append(d)
        active.sort(key=lambda d: (E.sev_key(d["code"]), d["since"]))
        history = []
        for r in store.err_rows(now - days * 86400, 600):
            d = deco(r["code"])
            d.update({"id": r["id"], "key": r["key"], "n": r["n"], "label": label_of(r["key"], r["n"]),
                      "ts_set": r["ts_set"], "ts_clear": r["ts_clear"],
                      "duration_s": int((r["ts_clear"] or now) - r["ts_set"]), "open": r["ts_clear"] is None,
                      "detail": r["detail"]})
            history.append(d)
        diag = []
        for n in range(1, 7):
            mac = slot.get(n)
            lab = who[mac][1] if mac else eng.default_label(n)
            if not mac:
                diag.append({"n": n, "label": lab, "codes": [], "text": "%s: ยังไม่ได้ตั้งค่าโหนด" % lab, "empty": True})
                continue
            codes = [e["code"] for e in by_key.get(mac, [])]
            diag.append({"n": n, "label": lab, "codes": codes, "text": E.diagnosis_line(lab, codes)})
        hub_codes = [e["code"] for e in by_key.get(E.HUB_KEY, [])]
        diag.append({"n": 0, "label": "ฮับ", "codes": hub_codes, "text": E.diagnosis_line("ฮับ / ทั้งโรงสี", hub_codes)})
        return {"now": now, "active": active, "history": history, "diagnosis": diag, "days": days}

    # --------------------------------------------------------- screen lifecycle
    lc = hub.lifecycle

    def date_to_ts(date: Optional[str], keep_ts: Optional[float] = None) -> float:
        now = eng.clock()
        if not date:
            return now
        try:
            d = dt.date.fromisoformat(date)
        except ValueError:
            raise HTTPException(400, "วันที่ต้องอยู่ในรูป ปี-เดือน-วัน เช่น 2026-10-04")
        if keep_ts is not None and store.date_of(keep_ts) == date:
            return keep_ts
        today = store.date_of(now)
        if date == today:
            return now
        if date > today:
            raise HTTPException(400, "วันที่เปลี่ยนตะแกรงอยู่ในอนาคตไม่ได้")
        return float(store.day_bounds(d.isoformat())[0] + 12 * 3600)

    def lc_call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except LookupError as e:
            raise HTTPException(404, str(e))

    @app.get("/api/lifecycle")
    def lifecycle_view():
        o = lc.overview(eng.clock())
        with eng.lock:
            for m in o["machines"]:
                mac = eng.slot_mac(m["n"])
                m["label"] = eng.label_of(eng.states[mac]) if mac else eng.default_label(m["n"])
                m["has_node"] = bool(mac)
        return o

    @app.get("/api/lifecycle/{n}/trend")
    def lifecycle_trend(n: int):
        node_or_404(n)
        return lc.trend(n, eng.clock())

    @app.post("/api/lifecycle/{n}/change", dependencies=[Depends(auth)])
    def lifecycle_change(n: int, body: ChangeBody):
        node_or_404(n)
        ts = date_to_ts(body.date)
        e = lc_call(lc.add_change, n, ts, body.reason or "other", body.note or "", eng.clock())
        eng._event(eng.clock(), n, eng.slot_mac(n), "SCREEN_CHANGE",
                   "%s: บันทึกการเปลี่ยนตะแกรง %s (%s)" % (eng.default_label(n) if not eng.slot_mac(n) else
                                                          eng.label_of(eng.states[eng.slot_mac(n)]),
                                                          lc.fmt_date(ts), REASONS.get(e["reason"], "")),
                   {"ts_change": ts, "reason": e["reason"]}, src="dashboard")
        return {"ok": True, "entry": e}

    @app.post("/api/lifecycle/{n}/last", dependencies=[Depends(auth)])
    def lifecycle_edit(n: int, body: ChangeBody):
        node_or_404(n)
        es = lc.entries(n)
        keep = es[-1]["ts_change"] if es else None
        ts = date_to_ts(body.date, keep) if body.date else None
        e = lc_call(lc.edit_last, n, ts, body.reason, body.note, eng.clock())
        return {"ok": True, "entry": e}

    @app.post("/api/lifecycle/{n}/undo", dependencies=[Depends(auth)])
    def lifecycle_undo(n: int):
        node_or_404(n)
        e = lc_call(lc.undo_last, n, eng.clock())
        return {"ok": True, "removed": e}

    @app.post("/api/events/{eid}/label", dependencies=[Depends(auth)])
    def label_event(eid: int, body: LabelBody):
        r = lc_call(lc.set_label, eid, body.label or None, body.note or "", eng.clock())
        return {"ok": True, **r}

    @app.get("/api/daily")
    def daily(date: Optional[str] = None, days: Optional[int] = Query(None, ge=1, le=60)):
        now = eng.clock()
        today = store.date_of(now)

        def day_rows(d: str) -> List[Dict[str, Any]]:
            if d >= today:
                return store.compute_daily(d, now, final=False, save=False)
            rows = store.get_daily(d)
            if not rows:
                rows = store.compute_daily(d, now, final=True, save=True)
                rows = store.get_daily(d) or rows
            return rows

        if days:
            base = dt.date.fromisoformat(today)
            out = []
            for i in range(days - 1, -1, -1):
                d = (base - dt.timedelta(days=i)).isoformat()
                out.append({"date": d, "rows": day_rows(d)})
            return {"days": out, "today": today}
        d = date or today
        try:
            dt.date.fromisoformat(d)
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD")
        return {"date": d, "today": today, "rows": day_rows(d), "partial": d >= today}

    @app.post("/api/node/{n}/assign", dependencies=[Depends(auth)])
    def assign(n: int, body: AssignBody):
        node_or_404(n)
        label = (body.label or "").strip()[:40] or None
        fields = getattr(body, "model_fields_set", None)
        if fields is None:
            fields = body.__fields_set__
        # Settings updates and assignments use the same lock order. The source
        # and destination bindings cannot change between guard check and move.
        with dashboard_config_lock, eng.lock:
            cur = eng.slot_mac(n)
            if body.unassign:
                if not cur:
                    raise HTTPException(404, "ช่องนี้ยังว่างอยู่")
                mac, target = cur, None
            elif body.mac:
                mac, target = norm_mac(body.mac), n
                if not MAC_RE.match(mac):
                    raise HTTPException(400, "MAC ต้องเป็นเลขฐานสิบหก 12 ตัว เช่น a4cf12ab34cd")
            elif label and cur:
                mac, target = cur, n
            else:
                raise HTTPException(400, "ต้องระบุ mac หรือ label")
            source = eng.states[mac].machine if mac in eng.states else None
            if "expected_source_machine" in fields and source != body.expected_source_machine:
                raise HTTPException(409, "Node assignment changed. Refresh the machine settings before retrying.")
            if "expected_target_mac" in fields:
                expected = norm_mac(body.expected_target_mac) if body.expected_target_mac else None
                if expected != cur:
                    raise HTTPException(409, "Target machine changed. Refresh the machine settings before retrying.")
            old_config = dashboard_config()
            value = dict(old_config, visible_slots=list(old_config["visible_slots"]))
            if target is None:
                value["visible_slots"] = [slot for slot in value["visible_slots"] if slot != n]
            else:
                if source is not None and source != target:
                    value["visible_slots"] = [slot for slot in value["visible_slots"] if slot != source]
                value["visible_slots"] = sorted(set(value["visible_slots"] + [target]))
            tmp = None
            if value != old_config:
                try:
                    tmp = prepare_dashboard_config(value)
                except OSError:
                    raise HTTPException(503, "Cannot prepare dashboard configuration; assignment was not changed")
            warning = None
            try:
                change = eng.assign(target, mac, label)
                if tmp:
                    try:
                        os.replace(tmp, dashboard_config_path)
                        tmp = None
                    except OSError:
                        # Registry is already committed. Report the true outcome
                        # explicitly rather than suggesting the move failed.
                        warning = "Assignment applied, but dashboard tracking could not be updated. Refresh and save tracking settings."
                result = {"ok": True, "n": n, "mac": mac if target is not None else None,
                          "label": (label or eng.default_label(n)) if target is not None else None,
                          "assignment": change, "config": dashboard_config() if warning else value}
                if warning:
                    result["config_warning"] = warning
                return result
            finally:
                if tmp:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

    @app.post("/api/node/{n}/reset_baseline", dependencies=[Depends(auth)])
    def reset_baseline(n: int):
        node_or_404(n)
        if not eng.reset_baseline(n):
            raise HTTPException(404, "ช่องนี้ยังว่างอยู่")
        return {"ok": True}

    @app.post("/api/node/{n}/cmd", dependencies=[Depends(auth)])
    def cmd(n: int, body: CmdBody):
        node_or_404(n)
        c = body.cmd
        if c == "ack":
            payload: Dict[str, Any] = {"cmd": "ack"}
        elif c == "mode":
            if body.mode not in ("SHADOW", "ALARM_ON", "RECORD"):
                raise HTTPException(400, "mode must be SHADOW|ALARM_ON|RECORD")
            payload = {"cmd": "mode", "mode": body.mode}
        elif c == "test":
            if body.what not in ("lamps", "horn"):
                raise HTTPException(400, "what must be lamps|horn")
            payload = {"cmd": "test", "what": body.what}
        elif c == "reboot":
            payload = {"cmd": "reboot"}
        else:
            raise HTTPException(400, "unknown cmd")
        mac = eng.slot_mac(n)
        if not mac:
            raise HTTPException(404, "ช่องนี้ยังไม่ได้กำหนดโหนด")
        with eng.lock:
            st = eng.states[mac]
            offline = eng._is_offline(st, eng.clock())
            lab = eng.label_of(st)
        if offline:
            raise HTTPException(409, "%s ไม่เชื่อมต่อ ส่งคำสั่งไม่ได้" % lab)
        if not hub.send_cmd(mac, payload):
            raise HTTPException(503, "ส่งคำสั่งไม่สำเร็จ (ตัวกลาง MQTT ไม่พร้อม)")
        eng._event(eng.clock(), n, mac, "CMD", "%s: ส่งคำสั่ง %s จากหน้าจอ" % (lab, c), payload, src="dashboard")
        return {"ok": True, "sent": payload}

    @app.post("/api/node/{n}/cal", dependencies=[Depends(auth)])
    def force_cal(n: int, body: CalBody, request: Request):
        """DF-53: forced CAL ("เรียนรู้ค่าพื้นฐานใหม่") from the hub. Needs the admin token, never while an alarm is open,
        and always leaves an audit event (who, when, from where). The operator should do it while the machine is stopped."""
        node_or_404(n)
        operator = re.sub(r"\s+", " ", (body.operator or "").strip())[:40]
        if len(operator) < 2:
            raise HTTPException(400, "ต้องใส่ชื่อผู้สั่ง (อย่างน้อย 2 ตัวอักษร) เพื่อบันทึกว่าใครสั่ง")
        reason = re.sub(r"\s+", " ", (body.reason or "").strip())[:120]
        mac = eng.slot_mac(n)
        if not mac:
            raise HTTPException(404, "ช่องนี้ยังไม่ได้กำหนดโหนด")
        now = eng.clock()
        with eng.lock:
            st = eng.states[mac]
            lab = eng.label_of(st)
            offline = eng._is_offline(st, now)
            busy = st.alarm_active or st.last.get("st") == "ALARM"
        who = {"operator": operator, "ip": request.client.host if request.client else None, "reason": reason}
        if offline:
            raise HTTPException(409, "%s ไม่เชื่อมต่อ ส่งคำสั่งไม่ได้" % lab)
        if busy:
            eng._event(now, n, mac, "CAL_FORCED", "%s: ปฏิเสธคำสั่งเรียนรู้ใหม่ (CAL) จาก %s — กำลังเตือนค้างอยู่" % (lab, operator),
                       {**who, "result": "refused_alarm"}, src="dashboard")
            raise HTTPException(409, "%s กำลังเตือนค้างอยู่ — สั่งเรียนรู้ใหม่ไม่ได้ (กดรับทราบและรอให้เหตุจบก่อน)" % lab)
        if not hub.send_cmd(mac, {"cmd": "cal"}):
            raise HTTPException(503, "ส่งคำสั่งไม่สำเร็จ (ตัวกลาง MQTT ไม่พร้อม)")
        eng._event(now, n, mac, "CAL_FORCED", "%s: %s สั่งให้เรียนรู้ค่าพื้นฐานใหม่ (CAL)%s" % (lab, operator, (" — " + reason) if reason else ""),
                   {**who, "result": "sent"}, src="dashboard")
        return {"ok": True, "n": n, "operator": operator}

    @app.get("/{asset_path:path}")
    def dashboard_asset(asset_path: str):
        # Registered last: API routes keep their existing behavior. Serve only
        # browser assets, never the data partition, Python source or secrets.
        if asset_path.startswith(("api/", "local-api/")):
            raise HTTPException(404, "Not found")
        suffix = os.path.splitext(asset_path)[1].lower()
        login_html = asset_path in ("login/local.html", "login/online.html")
        if not login_html and suffix not in (".js", ".css", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".woff2"):
            raise HTTPException(404, "Not found")
        dashboard = find_dashboard(cfg.dashboard_path)
        if not dashboard:
            raise HTTPException(404, "Not found")
        directory = os.path.realpath(os.path.dirname(dashboard))
        candidate = os.path.realpath(os.path.join(directory, asset_path))
        try:
            inside = os.path.commonpath([directory, candidate]) == directory
        except ValueError:
            inside = False
        if not inside or not os.path.isfile(candidate):
            raise HTTPException(404, "Not found")
        return FileResponse(candidate, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return app
