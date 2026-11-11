"""Native multi-file dashboard and persisted Admin display settings (no MQTT)."""
import json
from pathlib import Path
import urllib.error
import urllib.request

import pytest

from conftest import http_json
from auth_client import LocalAccountClient
from grainguard_hub.app import Hub
from grainguard_hub.config import Config

TOKEN = "native-dashboard-test-token"


@pytest.fixture
def native(tmp_path):
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "assets").mkdir()
    (dashboard / "index.html").write_text("<html>Native dashboard</html>", encoding="utf-8")
    (dashboard / "app.js").write_text("console.log('native');", encoding="utf-8")
    (dashboard / "styles.css").write_text("body{color:green}", encoding="utf-8")
    (dashboard / "assets" / "machine.webp").write_bytes(b"example-image-bytes")
    (dashboard / "assets" / "font.woff2").write_bytes(b"example-font-bytes")
    (dashboard / "private.json").write_text('{"secret":"must-not-serve"}', encoding="utf-8")
    (dashboard / "server.py").write_text("# must not serve", encoding="utf-8")
    (tmp_path / "outside.css").write_text("outside{}", encoding="utf-8")
    cfg = Config(data_dir=str(tmp_path / "data"), mqtt_enabled=False, http_host="127.0.0.1", http_port=0,
                 admin_token=TOKEN, dashboard_path=str(dashboard / "index.html"))
    hub = Hub(cfg, mqtt_enabled=False)
    hub.start()

    class N:
        pass
    n = N()
    n.hub, n.cfg, n.dashboard = hub, cfg, dashboard
    n.base = "http://127.0.0.1:%d" % hub.http_port
    n.client = LocalAccountClient(n.base)
    n.get = lambda path: n.client.request(path)
    # TOKEN remains a legacy fixture sentinel selecting the real account client;
    # no token header authenticates a request under the new server policy.
    n.post = lambda path, body=None, token=None: n.client.request(path, body, "POST",
        headers={"X-Admin-Token": token} if token is not None else {}, authenticated=token == TOKEN)
    yield n
    hub.stop()


def raw_get(base, path, opener=None):
    try:
        open_url = opener.open if opener else urllib.request.urlopen
        response = open_url(base + path, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, response.read(), response.headers


def test_default_config_and_native_marker_do_not_change_existing_api(native):
    assert native.get("/local-api/config") == (200, {"visible_slots": [1], "discovery": "review", "offline": "keep"})
    assert native.get("/local-api/status")[1] == {"bridge": "grainguard-pi-native", "live": True,
                                                "default_visible_slots": [1]}
    status, nodes = native.get("/api/nodes")
    assert status == 200 and len(nodes["nodes"]) == 6
    assert native.get("/api/health")[0] == 200
    assert native.get("/api/errors/catalog")[0] == 200
    assert not Path(native.cfg.data_dir, "dashboard-config.json").exists()


def test_admin_auth_and_config_persist_with_no_token_in_file(native):
    body = {"visible_slots": [3, 1, 3], "discovery": "temporary", "offline": "group"}
    assert native.post("/local-api/auth")[0] == 401
    assert native.post("/local-api/auth", token="wrong")[0] == 401
    assert native.post("/local-api/config", body)[0] == 401
    assert native.post("/local-api/config", body, token="wrong")[0] == 401
    assert native.post("/local-api/auth", token=TOKEN) == (200, {"ok": True, "role": "admin"})
    expected = {"visible_slots": [1, 3], "discovery": "temporary", "offline": "group"}
    assert native.post("/local-api/config", body, TOKEN) == (200, expected)
    path = Path(native.cfg.data_dir, "dashboard-config.json")
    text = path.read_text(encoding="utf-8")
    assert json.loads(text) == expected and TOKEN not in text
    assert native.get("/local-api/config") == (200, expected)
    assert not list(Path(native.cfg.data_dir).glob("dashboard-config-*.tmp"))


@pytest.mark.parametrize("body", [
    {"visible_slots": [0]}, {"visible_slots": [7]},
    {"visible_slots": [True]}, {"visible_slots": ["1"]}, {"visible_slots": [1.0]},
    {"discovery": "automatic"}, {"offline": "hide"},
])
def test_invalid_dashboard_policy_is_rejected(native, body):
    assert native.post("/local-api/config", body, TOKEN)[0] == 400
    assert native.get("/local-api/config")[1]["visible_slots"] == [1]


def test_empty_tracking_list_is_valid_after_last_machine_is_removed(native):
    assert native.post("/local-api/config", {"visible_slots": []}, TOKEN)[0] == 200
    assert native.get("/local-api/config")[1]["visible_slots"] == []


def test_static_assets_are_available_but_secrets_and_traversal_are_not(native):
    status, body, headers = raw_get(native.base, "/",native.client.opener)
    assert status == 200 and b"Native dashboard" in body and headers["Cache-Control"] == "no-store"
    for path in ("/app.js", "/styles.css", "/assets/machine.webp", "/assets/font.woff2"):
        status, body, headers = raw_get(native.base, path)
        assert status == 200 and body
        assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
    for path in ("/private.json", "/server.py", "/dashboard-config.json", "/assets/missing.webp",
                 "/..%2Foutside.css", "/assets/..%2F..%2Foutside.css", "/api/missing.js", "/local-api/missing.js"):
        assert raw_get(native.base, path,native.client.opener)[0] == 404, path


def test_atomic_write_failure_keeps_previous_configuration(native, monkeypatch):
    old = {"visible_slots": [1, 2], "discovery": "review", "offline": "keep"}
    assert native.post("/local-api/config", old, TOKEN)[0] == 200
    def cannot_replace(*_args):
        raise OSError("test replacement failure")
    monkeypatch.setattr("grainguard_hub.api.os.replace", cannot_replace)
    assert native.post("/local-api/config", {"visible_slots": [1, 3]}, TOKEN)[0] == 503
    assert native.get("/local-api/config")[1] == old
    assert not list(Path(native.cfg.data_dir).glob("dashboard-config-*.tmp"))
