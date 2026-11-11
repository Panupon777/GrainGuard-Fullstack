"""HTTP API added in protocol v1.1: /api/errors, /api/errors/catalog, screen lifecycle, alarm labels (no MQTT needed:
the hub is started with the broker bridge off and telemetry is fed straight into the engine with the real clock)."""
import datetime as dt
import json
import time

import pytest

from conftest import free_port, http_json
from auth_client import LocalAccountClient
from grainguard_hub.app import Hub
from grainguard_hub.config import Config
from grainguard_hub.uplink import Uplink

MAC = "a4cf12ab3411"


@pytest.fixture
def api(tmp_path):
    cfg = Config(data_dir=str(tmp_path / "d"), mqtt_enabled=False, http_host="127.0.0.1", http_port=0,
                 flatline_s=2.0, flatline_clear_s=1.0, boot_grace_s=0, integrity_first_s=0, screen_jobs=True)
    hub = Hub(cfg, mqtt_enabled=False)
    # HTTP/error-contract tests use synthetic telemetry; the developer disk
    # must not inject an unrelated E501 into their expected Hub state.
    hub.selfcheck.disk_fn = lambda: 10.0
    hub.start()
    base = "http://127.0.0.1:%d" % hub.http_port

    class A:
        pass
    a = A()
    a.hub, a.cfg, a.base = hub, cfg, base
    a.client = LocalAccountClient(base)
    a.get = lambda p: a.client.request(p)[1]
    a.post = lambda p, body=None, headers=None: a.client.request(p, body,"POST",headers=headers)
    yield a
    hub.stop()


def feed(hub, mac, seconds, **kw):
    for _ in range(int(seconds * 2)):
        f = {"v": 1, "seq": int(time.time() * 10) % 10 ** 9, "up": 100, "st": "RUN", "mode": "ALARM_ON", "env": 150, "base": 150,
             "ratio": 1.0, "act": 90, "sat": 0, "flat": 0, "vin": 24.0, "tc": 40.0, "fw": "1.0.0", "ack": 0}
        f.update(kw)
        hub.engine.on_tele(mac, f)
        time.sleep(0.5)


def test_catalog_endpoint(api):
    c = api.get("/api/errors/catalog")
    codes = {x["code"]: x for x in c["codes"]}
    assert len(codes) >= 24 and {"E101", "E301", "E310", "E501", "E508", "E900"} <= set(codes)
    assert codes["E301"]["th"] and codes["E301"]["causes"] and "สวิตช์" in codes["E301"]["where"]
    assert c["sev_th"]["fault"] == "ขัดข้อง"


def test_errors_endpoint_active_history_diagnosis_and_count(api):
    st, _ = api.post("/api/node/3/assign", {"mac": MAC, "label": "ขัด 3"})
    assert st == 200
    feed(api.hub, MAC, 1)
    feed(api.hub, MAC, 4, flat=1)                                   # flatline_s=2 in this test
    e = api.get("/api/errors")
    act = [a for a in e["active"] if a["code"] == "E101"]
    assert len(act) == 1
    a = act[0]
    assert a["n"] == 3 and a["label"] == "ขัด 3" and a["sev"] == "fault" and a["count_today"] == 1
    assert a["th"] and a["where"] and len(a["causes"]) >= 3 and a["duration_s"] >= 0
    d3 = [d for d in e["diagnosis"] if d["n"] == 3][0]
    assert d3["codes"] == ["E101"] and d3["text"].startswith("ขัด 3: E101 ") and "ลองเช็ค" in d3["text"]
    assert len(e["diagnosis"]) == 7 and e["diagnosis"][-1]["label"] == "ฮับ"
    assert [d for d in e["diagnosis"] if d["n"] == 1][0]["empty"] is True
    assert any(h["code"] == "E101" and h["open"] for h in e["history"])
    # /api/nodes + heartbeat + event filter
    node = api.get("/api/nodes")["nodes"][2]
    assert node["codes"] == ["E101"] and node["errors"][0]["since"] > 0
    hb = Uplink(api.cfg, api.hub.store, api.hub.engine.snapshot, None).build_heartbeat()
    assert [n for n in hb["nodes"] if n["n"] == 3][0]["codes"] == ["E101"] and hb["hub_codes"] == []
    evs = api.get("/api/events?codes=E101")["events"]
    assert evs and all(x["code"] == "E101" for x in evs)
    # clears and stays in the history
    feed(api.hub, MAC, 4, flat=0)
    e = api.get("/api/errors")
    assert not [a for a in e["active"] if a["code"] == "E101"]
    h = [h for h in e["history"] if h["code"] == "E101"][0]
    assert h["open"] is False and h["ts_clear"] > h["ts_set"] and h["duration_s"] >= 1   # real clock: stay tolerant when the machine is busy


def test_hub_codes_appear_in_errors_and_heartbeat(api):
    api.hub.engine.set_hub_code("E501", True, time.time(), {"disk_pct": 91}, "ใช้ไปแล้ว 91%")
    e = api.get("/api/errors")
    a = [x for x in e["active"] if x["code"] == "E501"][0]
    assert a["scope"] == "hub" and a["label"].startswith("ฮับ") and a["detail"]["disk_pct"] == 91
    assert e["diagnosis"][-1]["codes"] == ["E501"]
    assert api.get("/api/nodes")["hub"]["codes"] == ["E501"]
    q = api.hub.store.q("SELECT type, code FROM cloud_queue WHERE code='E501'")
    assert q and q[0]["type"] == "HEALTH"


def test_lifecycle_endpoints_entry_flow(api):
    api.post("/api/node/2/assign", {"mac": "a4cf12ab3422", "label": "ขัด 2"})
    today = dt.date.today()
    d10 = (today - dt.timedelta(days=10)).isoformat()
    st, r = api.post("/api/lifecycle/2/change", {"date": d10, "reason": "scheduled", "note": "ตามรอบ"})
    assert st == 200 and r["entry"]["reason"] == "scheduled"
    o = api.get("/api/lifecycle")
    m = o["machines"][1]
    assert m["label"] == "ขัด 2" and m["entries"][0]["note"] == "ตามรอบ" and m["has_start"]
    assert m["state"]["stage"] == 1 and 25 < m["state"]["used_pct"] < 40 and m["state"]["conf_th"] == "ต่ำ"
    assert m["state"]["stage_th"] == "ตามเวลา 30 วัน" and m["start_date"].endswith(str(today.year + 543))
    assert o["machines"][0]["state"] is None and o["reasons"]["broke"] == "ขาดจริง"
    # validation
    assert api.post("/api/lifecycle/2/change", {"date": (today + dt.timedelta(days=2)).isoformat()})[0] == 400
    assert api.post("/api/lifecycle/2/change", {"date": "11/11/2569"})[0] == 400
    assert api.post("/api/lifecycle/2/change", {"date": d10, "reason": "nope"})[0] == 400
    assert api.post("/api/lifecycle/2/change", {"date": (today - dt.timedelta(days=20)).isoformat()})[0] == 400
    assert api.post("/api/lifecycle/9/change", {})[0] == 404
    # change today (default date) -> now; edit the last entry; undo
    st, r = api.post("/api/lifecycle/2/change", {"reason": "broke"})
    assert st == 200
    m = api.get("/api/lifecycle")["machines"][1]
    assert len(m["entries"]) == 2 and m["state"]["days"] < 0.1 and m["state"]["used_pct"] < 1
    assert len(m["cycles"]) == 1 and m["cycles"][0]["outcome"] == "broke"
    st, r = api.post("/api/lifecycle/2/last", {"reason": "other", "note": "แก้"})
    assert st == 200 and r["entry"]["reason"] == "other" and r["entry"]["note"] == "แก้"
    assert api.get("/api/lifecycle")["machines"][1]["cycles"][0]["outcome"] == "other"
    st, r = api.post("/api/lifecycle/2/undo")
    assert st == 200 and len(api.get("/api/lifecycle")["machines"][1]["entries"]) == 1
    assert api.post("/api/lifecycle/3/undo")[0] == 404                 # nothing to undo on an untouched machine
    tr = api.get("/api/lifecycle/2/trend")
    assert tr["n"] == 2 and tr["current"]["start"] > 0 and len(tr["features"]) == 5
    # the entry also shows up in the event list
    assert any(e["type"] == "SCREEN_CHANGE" for e in api.get("/api/events?limit=50")["events"])


def test_alarm_label_endpoint_and_events_listing(api):
    eng = api.hub.engine
    now = time.time()
    eng._event(now, 4, None, "ALARM_ON", "ขัด 4: ALARM", {}, cloud="ALARM_ON")
    eng._event(now, 4, None, "BOOT", "ขัด 4: รีบูต", {})
    evs = api.get("/api/events?limit=10&n=4")["events"]
    alarm = [e for e in evs if e["type"] == "ALARM_ON"][0]
    boot = [e for e in evs if e["type"] == "BOOT"][0]
    assert alarm["alarm_label"] is None
    assert api.post("/api/events/%d/label" % alarm["id"], {"label": "real", "note": "เจอรอย"})[0] == 200
    got = [e for e in api.get("/api/events?limit=10&n=4")["events"] if e["id"] == alarm["id"]][0]
    assert got["alarm_label"] == "real" and got["label_note"] == "เจอรอย"
    assert api.post("/api/events/%d/label" % alarm["id"], {"label": "maybe"})[0] == 400
    assert api.post("/api/events/%d/label" % boot["id"], {"label": "real"})[0] == 404
    assert api.post("/api/events/%d/label" % alarm["id"], {"label": None})[0] == 200
    got = [e for e in api.get("/api/events?limit=10&n=4")["events"] if e["id"] == alarm["id"]][0]
    assert got["alarm_label"] is None


def test_advisory_90_percent_goes_to_the_cloud_queue_as_info(api):
    api.post("/api/node/5/assign", {"mac": "a4cf12ab3455", "label": "ขัด 5"})
    d = (dt.date.today() - dt.timedelta(days=28)).isoformat()            # 28/30 days = 93 %
    assert api.post("/api/lifecycle/5/change", {"date": d, "reason": "other"})[0] == 200
    rows = api.hub.store.q("SELECT type, text, data, code FROM cloud_queue WHERE type='HEALTH' ORDER BY seq")
    adv = [r for r in rows if "screen_life_90" in (r["data"] or "")]
    assert len(adv) == 1 and "ใกล้ถึงอายุตะแกรง" in adv[0]["text"] and adv[0]["code"] is None
    body = Uplink.event_body("mill-1", dict(api.hub.store.q("SELECT * FROM cloud_queue WHERE type='HEALTH' ORDER BY seq")[-1]))
    assert "code" not in body and json.loads(json.dumps(body))["data"]["advisory"] is True
    api.hub.lifecycle.update_all(time.time())                             # recomputing does not repeat it
    assert len([r for r in api.hub.store.q("SELECT data FROM cloud_queue") if "screen_life_90" in (r["data"] or "")]) == 1


def test_sessions_guard_the_new_endpoints_and_legacy_token_cannot_bypass(tmp_path):
    cfg = Config(data_dir=str(tmp_path / "d"), mqtt_enabled=False, http_host="127.0.0.1", http_port=0, admin_token="s3cret")
    hub = Hub(cfg, mqtt_enabled=False)
    hub.start()
    try:
        base = "http://127.0.0.1:%d" % hub.http_port
        assert http_json(base + "/api/lifecycle/1/change", {}, method="POST")[0] == 403
        assert http_json(base + "/api/lifecycle/1/undo", {}, method="POST")[0] == 403
        assert http_json(base + "/api/events/1/label", {"label": "real"}, method="POST")[0] == 403
        assert http_json(base + "/api/lifecycle/1/change", {}, method="POST", headers={"X-Admin-Token": "s3cret"})[0] == 403
        assert http_json(base + "/api/lifecycle")[0] == 401 and http_json(base + "/api/errors")[0] == 401
        client = LocalAccountClient(base)
        assert client.request("/api/lifecycle/1/change",{},"POST")[0] == 200
        assert client.request("/api/lifecycle")[0] == 200 and client.request("/api/errors")[0] == 200
    finally:
        hub.stop()


def test_rejected_post_reads_the_body_before_answering(tmp_path):
    # A 403 sent before the request body is read leaves unread bytes in the socket; closing it then resets the
    # connection (always on Windows, sometimes on Linux) and the client sees a network error instead of the 403.
    import socket
    cfg = Config(data_dir=str(tmp_path / "d"), mqtt_enabled=False, http_host="127.0.0.1", http_port=0, admin_token="s3cret")
    hub = Hub(cfg, mqtt_enabled=False)
    hub.start()
    try:
        with socket.create_connection(("127.0.0.1", hub.http_port), timeout=5) as s:
            s.sendall(b"POST /api/lifecycle/1/undo HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                      b"Content-Length: 2\r\nConnection: close\r\n\r\n")
            s.settimeout(0.5)
            with pytest.raises(socket.timeout):                     # no early answer while the body is still on its way
                s.recv(1)
            s.settimeout(5)
            s.sendall(b"{}")
            reply = b""
            while chunk := s.recv(4096):
                reply += chunk
        assert reply.startswith(b"HTTP/1.1 403")
    finally:
        hub.stop()


def test_clean_stop_marks_run_state_and_unclean_start_raises_E506(tmp_path):
    import sqlite3
    cfg = Config(data_dir=str(tmp_path / "d"), mqtt_enabled=False)
    h1 = Hub(cfg, mqtt_enabled=False, http_enabled=False)
    h1.start()
    assert h1.store.meta_get("run_state") == "running"
    h1.stop()
    assert h1.store.meta_get("run_state") == "stopped"
    h2 = Hub(cfg, mqtt_enabled=False, http_enabled=False)
    h2.start()
    assert h2.engine.snapshot()["hub"]["codes"] == []                     # restart after a clean stop is not an error
    h2.stop()
    c = sqlite3.connect(cfg.db())                                         # emulate a crash / power cut: 'running' never cleared
    c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('run_state','running')")
    c.commit()
    c.close()
    h3 = Hub(cfg, mqtt_enabled=False, http_enabled=False)
    h3.start()
    try:
        assert h3.engine.snapshot()["hub"]["codes"] == ["E506"]
        ev = h3.store.list_events(20, types=["HEALTH"])
        assert ev and ev[0]["code"] == "E506" and ev[0]["data"]["what"] == "hub-core"
        assert h3.store.list_events(20, types=["HUB_BOOT"])[0]["data"]["unclean_previous_stop"] is True
    finally:
        h3.stop()
