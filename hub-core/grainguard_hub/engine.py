"""Per-second health engine + node registry state (implements PROTOCOL.md "Health rules" and "Fleet-level").

The engine is purely event driven (on_status / on_tele / on_evt) plus a 1 Hz ``tick``.
All time comes from the injected ``clock`` (or an explicit ``now``) so the rules are
unit-testable with a fake clock.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

from . import errors as E
from .config import Config
from .store import Store

log = logging.getLogger("gg.engine")

CLASSES = ("ok", "alarm", "warn", "offline", "new", "cal", "shadow")
# Modes in which an ALARM is only a "candidate" (horn is silent in the firmware): never pushed to LINE/Telegram.
# RECORD (raw capture, G-B knock tests) must be treated like SHADOW (dashboard banner already says "ไม่แจ้งเตือน").
QUIET_MODES = ("SHADOW", "RECORD")

HEALTH_TEXT = {
    "flatline": "สัญญาณนิ่งผิดปกติ (เซนเซอร์/สายอาจเสีย)",
    "saturation": "สัญญาณล้น (เกนสูงเกินหรือช็อต)",
    "flatline_b": "ช่อง B (piezo) สัญญาณนิ่งผิดปกติ (แผ่น piezo/สาย S2 อาจเสีย)",
    "saturation_b": "ช่อง B (piezo) สัญญาณล้น (เกนสูงเกินหรือช็อต)",
    "drift": "ค่าฐานเพี้ยนเทียบกับ 7 วันที่ผ่านมา",
    "vin_low": "แรงดันไฟ 24V ต่ำ",
    "vin_high": "แรงดันไฟ 24V สูง",
    "temp_high": "บอร์ดร้อนเกินไป",
    "reboot_loop": "รีบูตซ้ำๆ",
    "link_loss": "สัญญาณเครือข่ายหลุดบ่อย",
    "fw_mismatch": "เฟิร์มแวร์ไม่ตรงเวอร์ชัน",
    "fault": "โหนดรายงานความผิดพลาด",
    "noisy": "สัญญาณรบกวนสูง",
    "cal_stuck": "เรียนรู้ค่าพื้นฐานไม่จบ (CAL ค้าง)",
    "ack_stuck": "ปุ่ม ACK ค้าง/กดติด",
    "unacked_alarm": "ALARM ดังนานแล้วยังไม่มีใครกดรับทราบ",
}
FLAG_ORDER = list(HEALTH_TEXT)


def _num(d: dict, key: str, default: Optional[float] = 0.0) -> Optional[float]:
    v = d.get(key, default)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


class Cond:
    """Boolean condition with a minimum duration to set and to clear (hysteresis)."""

    def __init__(self, set_s: float, clear_s: float):
        self.set_s, self.clear_s = set_s, clear_s
        self.on = False
        self._t: Optional[float] = None

    def update(self, active: bool, now: float) -> bool:
        if not self.on:
            if active:
                if self._t is None:
                    self._t = now
                if now - self._t >= self.set_s:
                    self.on, self._t = True, None
            else:
                self._t = None
        else:
            if not active:
                if self._t is None:
                    self._t = now
                if now - self._t >= self.clear_s:
                    self.on, self._t = False, None
            else:
                self._t = None
        return self.on

    def reset_timer(self) -> None:
        self._t = None


class NodeState:
    def __init__(self, mac: str, cfg: Config, machine: Optional[int], label: Optional[str]):
        self.mac = mac
        self.machine = machine
        self.label = label
        self.first_seen: Optional[float] = None
        self.last_rx: Optional[float] = None
        self.assignment_since: Optional[float] = None
        self.waiting_for_tele = False
        self.last: Dict[str, Any] = {}
        self.lwt: Optional[str] = None
        self.lwt_t: float = 0.0
        # health
        self.c_flat = Cond(cfg.flatline_s, cfg.flatline_clear_s)
        self.c_flat_b = Cond(cfg.flatline_s, cfg.flatline_clear_s)          # channel B (piezo)
        self.c_vlow = Cond(cfg.vin_s, cfg.vin_clear_s)
        self.c_vhigh = Cond(cfg.vin_s, cfg.vin_clear_s)
        self.c_temp = Cond(cfg.temp_s, cfg.temp_clear_s)
        self.c_fw = Cond(cfg.fw_s, 0.0)
        self.c_fault = Cond(0.0, 0.0)
        self.c_noisy = Cond(cfg.noisy_s, 10.0)
        self.c_cal = Cond(cfg.cal_stuck_s, 5.0)
        self.c_ack = Cond(0.0, 3.0)                 # the node already measures how long the button is held (ackms)
        self.mode: Optional[str] = None         # SHADOW | ALARM_ON | RECORD (from tele / MODE events)
        self.sat_on = False
        self.sat_on_b = False
        self.drift_on = False
        self.link_on = False
        self.flags: Set[str] = set()
        self.flag_info: Dict[str, Any] = {}
        self.fault_evt = False
        self.fault_info: Dict[str, Any] = {}
        self.fault_ch: Dict[str, Dict[str, Any]] = {}         # channel -> FAULT info while the node says that channel is faulted
        # windows
        self.base_samples: Deque[Tuple[float, float]] = deque()
        self.sat_samples: Deque[Tuple[float, int]] = deque()
        self.sat_samples_b: Deque[Tuple[float, int]] = deque()
        self.gap: Deque[Tuple[float, int, int]] = deque()   # (t, missing, got)
        self.last_seq: Optional[int] = None
        self.prev_up: Optional[float] = None
        self.boots: Deque[float] = deque()
        self.last_boot_t: float = -1e9
        self.seen_evt: Deque[tuple] = deque(maxlen=64)       # (key, hub time): QoS1 duplicate filter, 120 s memory
        self.drift_ref: Optional[float] = None
        self.drift_ref_t: float = -1e9
        self.drift_check_t: float = -1e9
        self.drift_med: Optional[float] = None
        # alarm
        self.alarm_active = False
        self.alarm_since = 0.0
        self.alarm_shadow = False      # the active alarm happened in SHADOW mode (candidate only, no push)
        self.alarm_acked = False
        self.alarm_streak = 0
        self.alarm_info: Dict[str, Any] = {}      # last ALARM_ON info (which channel, dec, ratios) for texts / persistence
        self.node_closed_alarm = False
        self.non_alarm_since: Optional[float] = None
        self.evt_hold_until = 0.0
        # class / offline tracking
        self.cls = "offline"
        self.cls_since = 0.0
        self.offline_notified = False
        self.offline_notified_t = 0.0
        # sparkline buckets: bucket index -> [sum, count]; spark_b is channel B (piezo) when the node reports it
        self.spark: Dict[int, List[float]] = {}
        self.spark_b: Dict[int, List[float]] = {}

    @property
    def assigned(self) -> bool:
        return self.machine is not None


class Engine:
    SPARK_BUCKET = 30
    SPARK_SLOTS = 60

    def __init__(self, cfg: Config, store: Store, clock: Callable[[], float] = time.time,
                 on_class_change: Optional[Callable[[], None]] = None,
                 on_event: Optional[Callable[[], None]] = None,
                 carrier_fn: Optional[Callable[[], Optional[bool]]] = None):
        self.cfg = cfg
        self.store = store
        self.clock = clock
        self.on_class_change = on_class_change or (lambda: None)
        self.on_event = on_event or (lambda: None)
        self.carrier_fn = carrier_fn
        self.lock = threading.RLock()
        self.boot_ts = clock()
        self.grace_until = self.boot_ts + cfg.boot_grace_s
        self.mqtt_ok = False
        self.plant_off = False
        self.plant_since = 0.0
        self.plant_reason = ""
        self.plant_restore_t = -1e9
        self.carrier: Optional[bool] = None
        self.errors = E.ErrorBook(store, clock)
        self.errors.start(self.boot_ts)
        self.c_nic = Cond(cfg.nic_a_down_s, 5.0)
        self.restart_until = 0.0
        self._mqtt_was_up = False
        self.states: Dict[str, NodeState] = {}
        self._today_cache: Tuple[float, Dict[str, Any]] = (0.0, {"alarms": {}, "run_s": {}})
        self.counters = {"tele": 0, "evt": 0, "bad": 0}
        for r in store.list_nodes():
            st = NodeState(r["mac"], cfg, r["machine"], r["label"])
            st.first_seen = r["first_seen"]
            st.assignment_since = self.boot_ts
            st.cls_since = self.boot_ts
            self.states[r["mac"]] = st
            self._restore_alarm(st)
        self._seed_spark()

    # ------------------------------------------------- alarm persistence (DF-54)
    def _alarm_key(self, mac: str) -> str:
        return "alarm:" + mac

    def _save_alarm(self, st: NodeState) -> None:
        """An open alarm survives a hub restart: it is written when it opens / is acknowledged and erased when the node closes it."""
        try:
            if st.alarm_active:
                self.store.meta_set(self._alarm_key(st.mac), json.dumps(
                    {"since": st.alarm_since, "shadow": bool(st.alarm_shadow), "acked": bool(st.alarm_acked), "info": st.alarm_info},
                    separators=(",", ":")))
            else:
                self.store.meta_set(self._alarm_key(st.mac), "")
        except Exception:
            log.exception("could not persist alarm state of %s", st.mac)

    def _restore_alarm(self, st: NodeState) -> None:
        try:
            raw = self.store.meta_get(self._alarm_key(st.mac), "") or ""
            if not raw:
                return
            d = json.loads(raw)
            st.alarm_active = True
            st.alarm_since = float(d.get("since") or self.boot_ts)
            st.alarm_shadow = bool(d.get("shadow"))
            st.alarm_acked = bool(d.get("acked"))
            st.alarm_info = d.get("info") if isinstance(d.get("info"), dict) else {}
            log.warning("restored open alarm of %s (since %.0f)", st.mac, st.alarm_since)
        except Exception:
            log.exception("bad persisted alarm state for %s", st.mac)

    # ------------------------------------------------------------ registry
    def default_label(self, n: Optional[int]) -> str:
        return "ขัด %d" % n if n else "โหนดใหม่"

    def label_of(self, st: NodeState) -> str:
        return st.label or self.default_label(st.machine)

    def _state(self, mac: str, now: float, fw: Optional[str] = None) -> NodeState:
        st = self.states.get(mac)
        if st is None:
            st = NodeState(mac, self.cfg, None, None)
            st.first_seen = now
            st.cls_since = now
            self.states[mac] = st
            self.store.ensure_node(mac, now, fw)
            log.info("new node seen: %s", mac)
        return st

    def slot_mac(self, n: int) -> Optional[str]:
        for st in self.states.values():
            if st.machine == n:
                return st.mac
        return None

    def _assignment_context(self, st: NodeState, n: Optional[int], label: Optional[str], now: float) -> NodeState:
        """Discard readings/diagnostic windows attributed to the old location.

        The physical Node's open alarm is preserved until its own clear event
        or normal safety-net confirmation; remapping is not an ALARM_OFF.
        """
        self._drop_node_errors(st, now)
        fresh = NodeState(st.mac, self.cfg, n, label)
        fresh.first_seen, fresh.mode, fresh.cls_since = st.first_seen, st.mode, now
        fresh.assignment_since = now
        fresh.waiting_for_tele = n is not None
        for attr in ("alarm_active", "alarm_since", "alarm_shadow", "alarm_acked", "alarm_info", "evt_hold_until"):
            setattr(fresh, attr, getattr(st, attr))
        self.states[st.mac] = fresh
        return fresh

    def assign(self, n: Optional[int], mac: str, label: Optional[str] = None) -> Dict[str, Any]:
        now = self.clock()
        with self.lock:
            st = self.states.get(mac)
            previous_machine = st.machine if st is not None else None
            # Commit the UNIQUE registry mapping before changing any RAM state.
            # A failed transaction leaves the previous live mapping intact.
            change = self.store.assign(n, mac, label if n is not None and label else None, now)
            if st is None:
                st = NodeState(mac, self.cfg, None, None)
                st.first_seen, st.cls_since = now, now
                self.states[mac] = st
            displaced = self.states.get(change["replaced_mac"])
            if displaced is not None:
                self._refresh_cls(self._assignment_context(displaced, None, None, now), now)
            if previous_machine != n and change["previously_assigned"]:
                st = self._assignment_context(st, n, label if n is not None else None, now)
            st.machine = n
            if previous_machine != n:
                st.assignment_since = now
            st.label = label if n is not None and label else None
            st.offline_notified = False
            self._refresh_cls(st, now)
            self._event(now, n or 0, mac, "ASSIGN",
                        "กำหนดโหนด %s ให้เป็น %s" % (mac, (label or self.default_label(n)) if n else "ไม่ใช้งาน"),
                        {"mac": mac, "machine": n, "previous_machine": change["previous_machine"],
                         "replaced_mac": change["replaced_mac"]})
            self.on_class_change()
            return change

    def reset_baseline(self, n: int) -> bool:
        with self.lock:
            mac = self.slot_mac(n)
            if not mac:
                return False
            now = self.clock()
            self.store.meta_set("drift_ref_from:" + mac, str(int(now)))
            st = self.states[mac]
            st.drift_ref_t = -1e9
            st.drift_on = False
            st.flags.discard("drift")
            return True

    # -------------------------------------------------------------- events
    def _event(self, now: float, n: int, mac: Optional[str], type_: str, text: str, data: Optional[dict] = None,
               cloud: Optional[str] = None, src: str = "hub", code: Optional[str] = None) -> None:
        if code:
            data = dict(data or {})
            data.setdefault("code", code)
        try:
            self.store.add_event(now, n, mac, type_, text, data, src, cloud, self.cfg.queue_max, code)
        except Exception:
            log.exception("failed to store event %s", type_)
            return
        self._today_cache = (0.0, self._today_cache[1])      # counters on the dashboard must not lag behind
        if cloud:
            self.on_event()

    @property
    def mqtt_up(self) -> bool:
        """Broker connection healthy (always True when MQTT is disabled, e.g. in unit tests)."""
        return self.mqtt_ok or not self.cfg.mqtt_enabled

    # ------------------------------------------------------- MQTT inputs
    def set_mqtt(self, ok: bool, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        with self.lock:
            if ok and not self.mqtt_ok:
                # fresh (re)connection: nodes' ages are stale until their next tele arrives
                self.grace_until = max(self.grace_until, now + self.cfg.stale_s + self.cfg.offline_event_s)
                if self._mqtt_was_up:
                    self.note_restart("broker", now, {"what": "mosquitto"})
            if ok:
                self._mqtt_was_up = True
            self.mqtt_ok = ok

    def on_status(self, mac: str, text: str, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        text = (text or "").strip().lower()
        if text not in ("online", "offline"):
            return
        with self.lock:
            st = self._state(mac, now)
            st.lwt, st.lwt_t = text, now
            self._refresh_cls(st, now)

    def on_tele(self, mac: str, d: dict, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        cfg = self.cfg
        with self.lock:
            fw = d.get("fw") if isinstance(d.get("fw"), str) else None
            st = self._state(mac, now, fw)
            self.counters["tele"] += 1
            was_offline = self._is_offline(st, now)
            seq = d.get("seq")
            seq = int(seq) if isinstance(seq, (int, float)) and not isinstance(seq, bool) else None
            up = _num(d, "up", None)
            tl = d.get("tl") if isinstance(d.get("tl"), dict) else {}
            bd = d.get("b") if isinstance(d.get("b"), dict) else None
            bch = None
            if bd is not None:                                   # channel B present (node chb=1)
                bch = {"env": _num(bd, "env"), "base": _num(bd, "base"), "ratio": _num(bd, "ratio"), "act": _num(bd, "act"),
                       "sat": int(_num(bd, "sat", 0) or 0), "flat": int(_num(bd, "flat", 0) or 0), "flt": int(_num(bd, "flt", 0) or 0)}
            t = {
                "st": str(d.get("st", "")).upper(), "mode": d.get("mode"),
                "env": _num(d, "env"), "base": _num(d, "base"), "ratio": _num(d, "ratio"), "act": _num(d, "act"),
                "sat": int(_num(d, "sat", 0) or 0), "flat": int(_num(d, "flat", 0) or 0),
                "vin": _num(d, "vin", None), "tc": _num(d, "tc", None), "fw": fw, "ack": int(_num(d, "ack", 0) or 0),
                "tl": {k: int(bool(tl.get(k, 0))) for k in ("r", "y", "g", "b")}, "up": up, "seq": seq,
                "rst": d.get("rst"), "link": d.get("link"),
                "ackms": int(_num(d, "ackms", 0) or 0),
                "chb": bch is not None, "dec": d.get("dec") if isinstance(d.get("dec"), str) else None,
                "fa": int(_num(d, "fa", 0) or 0), "b": bch,
            }
            m = d.get("mode")
            if isinstance(m, str) and m.strip():
                st.mode = m.strip().upper()
            t["mode"] = st.mode
            if t["ack"] == 1 and st.alarm_active and not st.alarm_acked:
                st.alarm_acked = True
                self._save_alarm(st)
            # sequence-gap accounting (receive-side loss)
            if seq is not None:
                missing = 0
                if st.last_seq is not None:
                    delta = (seq - st.last_seq) & 0xFFFFFFFF
                    if 1 < delta < 1000:
                        missing = delta - 1
                st.last_seq = seq
                st.gap.append((now, missing, 1))
                lo = now - cfg.seqgap_window_s
                while st.gap and st.gap[0][0] < lo:
                    st.gap.popleft()
            # reboot detected from uptime regression (BOOT event may have been lost)
            if up is not None:
                if st.prev_up is not None and up < st.prev_up - 3:
                    self._record_boot(st, now, {"via": "uptime"})
                st.prev_up = up
            # windows
            st.base_samples.append((now, t["base"] or 0.0))
            lo = now - cfg.drift_window_s
            while st.base_samples and st.base_samples[0][0] < lo:
                st.base_samples.popleft()
            st.sat_samples.append((now, 1 if t["sat"] > 0 else 0))
            lo = now - cfg.sat_window_s
            while st.sat_samples and st.sat_samples[0][0] < lo:
                st.sat_samples.popleft()
            if bch is not None:
                st.sat_samples_b.append((now, 1 if bch["sat"] > 0 else 0))
                while st.sat_samples_b and st.sat_samples_b[0][0] < lo:
                    st.sat_samples_b.popleft()
            else:
                st.sat_samples_b.clear()
                st.sat_on_b = False
            b = int(now // self.SPARK_BUCKET)
            sp = st.spark.setdefault(b, [0.0, 0])
            sp[0] += t["ratio"] or 0.0
            sp[1] += 1
            for k in [k for k in st.spark if k < b - self.SPARK_SLOTS]:
                del st.spark[k]
            if bch is not None and bch["ratio"] is not None:
                spb = st.spark_b.setdefault(b, [0.0, 0])
                spb[0] += bch["ratio"]
                spb[1] += 1
            for k in [k for k in st.spark_b if k < b - self.SPARK_SLOTS]:
                del st.spark_b[k]
            # alarm tracking (tele-derived)
            if t["st"] == "ALARM":
                st.alarm_streak += 1
                st.non_alarm_since = None
            else:
                st.alarm_streak = 0
                if st.non_alarm_since is None:
                    st.non_alarm_since = now
            st.last, st.last_rx = t, now
            st.waiting_for_tele = False
            if st.lwt == "offline":
                st.lwt = "online"
            self.store.buffer_tele(int(now), mac, st.machine or 0, t["st"], t["env"], t["base"], t["ratio"],
                                   t["act"], t["sat"], t["flat"], t["vin"], t["tc"], bch)
            # power restored?
            if self.plant_off and self.carrier is not False:
                self._plant_restore(now)
            if was_offline and st.offline_notified and st.assigned:
                gone = now - st.offline_notified_t
                st.offline_notified = False
                self.errors.close(E.OFFLINE_CODE, mac, now)
                self._event(now, st.machine or 0, mac, "NODE_ONLINE",
                            "%s กลับมาเชื่อมต่อแล้ว (หายไป %s)" % (self.label_of(st), _dur_th(gone)),
                            {"offline_s": round(gone)}, cloud="NODE_ONLINE", code=E.OFFLINE_CODE)
            self._refresh_cls(st, now)

    def on_evt(self, mac: str, d: dict, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        typ = str(d.get("type", "")).upper()
        if not typ:
            return
        info = d.get("info") if isinstance(d.get("info"), dict) else {}
        with self.lock:
            st = self._state(mac, now)
            self.counters["evt"] += 1
            # QoS 1 duplicate filter. A node reboot restarts seq and uptime, so "same (type, seq, up)" alone would swallow the
            # next BOOT: a repeat only counts as a duplicate when the whole message is identical AND arrived within 120 s.
            key = (typ, d.get("seq"), d.get("up"), json.dumps(info, sort_keys=True, separators=(",", ":")))
            while st.seen_evt and now - st.seen_evt[0][1] > 120:
                st.seen_evt.popleft()
            if any(k == key for k, _ in st.seen_evt):
                return
            st.seen_evt.append((key, now))
            n = st.machine or 0
            lab = self.label_of(st)
            if typ == "BOOT":
                if not (self.plant_off or now < self.plant_restore_t + 90):
                    self._record_boot(st, now, info)
                else:
                    st.last_boot_t = now
                self._event(now, n, mac, "BOOT", "%s: รีบูต" % lab, info, src="node")
            elif typ == "ALARM_ON":
                st.evt_hold_until = now + 3.0
                st.non_alarm_since = None
                self._alarm_set(st, now, True, info, "node")
            elif typ == "ALARM_OFF":
                st.evt_hold_until = now + 3.0
                st.alarm_streak = 0               # the node says it is over: need fresh ALARM samples to re-arm
                self._alarm_set(st, now, False, info, "node")
            elif typ == "ACK":
                was_acked = st.alarm_acked
                st.alarm_acked = st.alarm_active or st.alarm_acked
                if st.alarm_active and not was_acked:
                    self._save_alarm(st)
                self._event(now, n, mac, "ACK", "%s: กดรับทราบแล้ว (ACK)" % lab, info, src="node")
            elif typ == "MODE":
                m = info.get("mode")
                if isinstance(m, str) and m:
                    st.mode = m.upper()
                self._event(now, n, mac, "MODE", "%s: เปลี่ยนโหมดเป็น %s" % (lab, st.mode or "?"), info, src="node")
            elif typ == "FAULT":
                ch = str(info.get("ch") or "A").upper()                 # P2U-B: the node names the channel; no "ch" = channel A
                st.fault_ch[ch] = info
                st.fault_evt, st.fault_info = True, info
                self._event(now, n, mac, "FAULT", "%s: ความผิดพลาดจากโหนด%s" % (lab, (" (ช่อง %s)" % ch) if "ch" in info else ""),
                            info, src="node")
            elif typ == "FAULT_CLEAR":
                ch = str(info.get("ch") or "A").upper()
                st.fault_ch.pop(ch, None)
                st.fault_evt = bool(st.fault_ch)
                if st.fault_ch:
                    st.fault_info = next(iter(st.fault_ch.values()))
                self._event(now, n, mac, "FAULT_CLEAR", "%s: ความผิดพลาดหายแล้ว%s" % (lab, (" (ช่อง %s)" % ch) if "ch" in info else ""),
                            info, src="node")
            elif typ == "CAL":
                src = str(info.get("src") or "")
                txt = {"start": "เริ่มเรียนรู้ค่าพื้นฐานใหม่ (CAL)", "seed": "เรียนรู้ค่าพื้นฐานเสร็จ (ใช้ค่าที่จำไว้)",
                       "meas": "เรียนรู้ค่าพื้นฐานเสร็จ (ค่าใหม่จากที่วัด)",
                       "rejected": "รีบูตแล้ววัดได้ระดับสูงผิดปกติ — ไม่ยอมรับเป็นค่าพื้นฐาน ใช้ค่าเดิม (ระวัง: เครื่องอาจผิดปกติอยู่)",
                       "refused": "ปฏิเสธคำสั่ง CAL เพราะกำลังเตือนค้างอยู่"}.get(src, "CAL")
                self._event(now, n, mac, "CAL", "%s: %s" % (lab, txt), info, src="node")
            else:
                self._event(now, n, mac, typ, "%s: %s" % (lab, typ), info, src="node")
            self._refresh_cls(st, now)

    # ------------------------------------------------------------- helpers
    def _record_boot(self, st: NodeState, now: float, info: dict) -> None:
        if now - st.last_boot_t < 15:
            return
        if self.plant_off or now < self.plant_restore_t + 90:
            st.last_boot_t = now
            return
        st.last_boot_t = now
        st.boots.append(now)
        lo = now - self.cfg.reboot_window_s
        while st.boots and st.boots[0] < lo:
            st.boots.popleft()

    def _alarm_set(self, st: NodeState, now: float, on: bool, info: dict, via: str) -> None:
        if on == st.alarm_active:
            return
        n = st.machine or 0
        lab = self.label_of(st)
        if on:
            shadow = st.mode in QUIET_MODES       # SHADOW / RECORD: record a candidate, never push
            st.alarm_active, st.alarm_shadow, st.alarm_acked = True, shadow, False
            st.alarm_since = now
            st.alarm_info = {k: v for k, v in info.items() if k in ("ch", "dec", "rb", "ab", "bb", "base", "act", "ratio", "restored")}
            self._save_alarm(st)
            data = {"ratio": st.last.get("ratio"), "via": via}
            data.update({k: v for k, v in info.items() if k not in data})
            who = {"A": " [pickup]", "B": " [piezo]", "AB": " [pickup+piezo]"}.get(str(info.get("ch", "")).upper(), "")
            if shadow:
                data["mode"] = st.mode            # SHADOW or RECORD
                self._event(now, n, st.mac, "SHADOW_ALARM",
                            "%s: [โหมดเงา] พบสัญญาณคล้าย ALARM%s — บันทึกไว้เป็นตัวอย่าง ยังไม่แจ้งเตือน" % (lab, who), data, src=via)
            else:
                self._event(now, n, st.mac, "ALARM_ON", "%s: ALARM เสียงที่ท่อผิดปกติ%s — โปรดไปตรวจตะแกรง" % (lab, who), data, cloud="ALARM_ON",
                            src=via)
        else:
            dur = max(0.0, now - st.alarm_since) if st.alarm_since else 0.0
            shadow = st.alarm_shadow
            st.alarm_active, st.alarm_shadow = False, False
            st.alarm_info = {}
            self._save_alarm(st)
            data = {"duration_s": round(dur), "via": via}
            data.update({k: v for k, v in info.items() if k not in data})
            if shadow:
                self._event(now, n, st.mac, "SHADOW_ALARM_END",
                            "%s: [โหมดเงา] สัญญาณคล้าย ALARM หยุดแล้ว (นาน %s)" % (lab, _dur_th(dur)), data, src=via)
            else:
                self._event(now, n, st.mac, "ALARM_OFF", "%s: ALARM หยุดแล้ว (นาน %s)" % (lab, _dur_th(dur)), data,
                            cloud="ALARM_OFF", src=via)

    def _promote_shadow_alarm(self, st: NodeState, now: float) -> None:
        """Mode switched from SHADOW to ALARM_ON while an alarm is already running: from now on it is a real one."""
        st.alarm_shadow = False
        st.alarm_acked = False
        st.alarm_since = now
        self._event(now, st.machine or 0, st.mac, "ALARM_ON", "%s: ALARM เสียงที่ท่อผิดปกติ — โปรดไปตรวจตะแกรง (เปลี่ยนจากโหมดเงาเป็นโหมดเตือนจริง)"
                    % self.label_of(st), {"ratio": st.last.get("ratio"), "via": "mode_change", "mode": st.mode},
                    cloud="ALARM_ON", src="hub")

    def _is_offline(self, st: NodeState, now: float) -> bool:
        if st.last_rx is None:
            return True
        if now - st.last_rx > self.cfg.stale_s:
            return True
        if st.lwt == "offline" and st.lwt_t >= st.last_rx:
            return True
        return False

    def _compute_cls(self, st: NodeState, now: float) -> str:
        if not st.assigned:
            return "new"
        if self._is_offline(st, now):
            return "offline"
        s = st.last.get("st")
        alarming = st.alarm_active or s == "ALARM"
        shadow_alarm = st.alarm_shadow if st.alarm_active else st.mode in QUIET_MODES
        if alarming and not shadow_alarm:
            return "alarm"
        if st.flags or s == "FAULT":
            return "warn"
        if alarming:
            return "shadow"             # ALARM seen while mode==SHADOW: candidate only, no push
        if s == "CAL":
            return "cal"
        if s == "SHADOW":               # legacy v1 frames (st carried the mode)
            return "shadow"
        return "ok"

    def _refresh_cls(self, st: NodeState, now: float) -> bool:
        c = self._compute_cls(st, now)
        if c != st.cls:
            log.info("%s (%s) %s -> %s", st.mac, self.label_of(st), st.cls, c)
            st.cls, st.cls_since = c, now
            self.on_class_change()
            return True
        return False

    def _seed_spark(self) -> None:
        try:
            seed = self.store.spark_seed(self.boot_ts, self.SPARK_SLOTS * self.SPARK_BUCKET, self.SPARK_BUCKET)
        except Exception:
            return
        for mac, buckets in seed.items():
            st = self.states.get(mac)
            if st is not None:
                cutoff = float(self.store.meta_get("assignment_context_from:" + mac, "0") or 0)
                st.spark = {b: v for b, v in buckets.items() if b * self.SPARK_BUCKET >= cutoff}

    # ---------------------------------------------------------------- tick
    def tick(self, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        with self.lock:
            if self.carrier_fn is not None:
                try:
                    self.carrier = self.carrier_fn()
                except Exception:
                    self.carrier = None
            self._plant_check(now)
            self._eval_nic(now)
            if self.restart_until and now >= self.restart_until:
                self.restart_until = 0.0
                self.set_hub_code("E506", False, now)
            for st in list(self.states.values()):
                if not st.assigned:
                    self._refresh_cls(st, now)
                    continue
                offline = self._is_offline(st, now)
                if offline:
                    self._reset_timers(st)
                else:
                    self._eval_alarm(st, now)
                    self._eval_flags(st, now)
                self._refresh_cls(st, now)
                if offline:
                    self._maybe_offline_event(st, now)

    def _reset_timers(self, st: NodeState) -> None:
        for c in (st.c_flat, st.c_flat_b, st.c_vlow, st.c_vhigh, st.c_temp, st.c_fw, st.c_fault, st.c_noisy, st.c_cal, st.c_ack):
            c.reset_timer()

    def _maybe_offline_event(self, st: NodeState, now: float) -> None:
        if st.offline_notified or self.plant_off or not self.mqtt_up:
            return
        ref = max(st.last_rx if st.last_rx is not None else self.boot_ts, st.assignment_since or self.boot_ts)
        # never alert before the fleet-level (plant power off) rule has had its chance to claim the silence
        delay = max(self.cfg.offline_event_s, self.cfg.stale_s + self.cfg.plant_window_s + 2.0)
        fire_at = max(ref + delay, self.grace_until)
        if now >= fire_at:
            st.offline_notified, st.offline_notified_t = True, ref
            self._event(now, st.machine or 0, st.mac, "NODE_OFFLINE",
                        "%s ไม่เชื่อมต่อ (ไม่มีสัญญาณ %s)" % (self.label_of(st), _dur_th(now - ref)),
                        {"last_seen_s": round(now - ref)}, cloud="NODE_OFFLINE", code=E.OFFLINE_CODE)
            self.errors.open(E.OFFLINE_CODE, st.mac, st.machine or 0, now, {"last_seen_s": round(now - ref)})

    # ------------------------------------------------------------ alarm
    def _eval_alarm(self, st: NodeState, now: float) -> None:
        cfg = self.cfg
        if st.alarm_active and st.alarm_shadow and st.mode not in (None,) + QUIET_MODES:
            self._promote_shadow_alarm(st, now)
        if now < st.evt_hold_until:
            return
        if not st.alarm_active:
            if st.alarm_streak >= cfg.alarm_confirm_samples:
                self._alarm_set(st, now, True, {}, "tele")
        else:
            # DF-54: the alarm is closed by the node's own ALARM_OFF event (on_evt). This tele-based close is only the safety net for
            # an ALARM_OFF that never arrives; it needs a long, uninterrupted run of non-ALARM tele (never counted across a reboot).
            if st.non_alarm_since is not None and now - st.non_alarm_since >= cfg.alarm_clear_s \
                    and st.last.get("st") != "ALARM":
                self._alarm_set(st, now, False, {"lost_off_event": True}, "tele")

    # ------------------------------------------------------- health flags
    def _drift_ref(self, st: NodeState, now: float) -> Optional[float]:
        if now - st.drift_ref_t >= 600:
            st.drift_ref_t = now
            since = float(self.store.meta_get("drift_ref_from:" + st.mac, "0") or 0)
            med, cnt = self.store.base_reference(st.mac, now, self.cfg.drift_ref_days, int(self.cfg.drift_window_s) + 300,
                                                 since)
            st.drift_ref = med if (med and cnt >= self.cfg.drift_min_ref_minutes) else None
        return st.drift_ref

    def _eval_flags(self, st: NodeState, now: float) -> None:
        cfg, L = self.cfg, st.last
        s = L.get("st", "")
        new: Set[str] = set()
        info: Dict[str, Any] = {}

        # flatline: dead sensor / cable / preamp
        if st.c_flat.update(L["flat"] == 1 and s in ("RUN", "REST"), now):
            new.add("flatline")
        # saturation: sat>0 in >= N of last 60 s (hysteresis on count)
        cnt = sum(v for _, v in st.sat_samples)
        if st.sat_on:
            if cnt <= cfg.sat_clear_count:
                st.sat_on = False
        elif cnt >= cfg.sat_count:
            st.sat_on = True
        if st.sat_on:
            new.add("saturation")
            info["saturation"] = {"count": cnt}
        # channel B (piezo), only for nodes that report one
        B = L.get("b")
        if B is not None:
            if st.c_flat_b.update(B["flat"] == 1 and s in ("RUN", "REST"), now):
                new.add("flatline_b")
            cntb = sum(v for _, v in st.sat_samples_b)
            if st.sat_on_b:
                if cntb <= cfg.sat_clear_count:
                    st.sat_on_b = False
            elif cntb >= cfg.sat_count:
                st.sat_on_b = True
            if st.sat_on_b:
                new.add("saturation_b")
                info["saturation_b"] = {"count": cntb}
        else:
            st.c_flat_b.update(False, now)
        # drift: median(base, last 10 min) outside [lo, hi] x 7-day median
        if s != "CAL" and now - st.drift_check_t >= 10:
            st.drift_check_t = now
            ref = self._drift_ref(st, now)
            if ref and len(st.base_samples) >= cfg.drift_min_samples:
                med = statistics.median(v for _, v in st.base_samples)
                st.drift_med = med
                lo, hi = cfg.drift_lo, cfg.drift_hi
                if st.drift_on:
                    st.drift_on = not (ref * lo * 1.1 <= med <= ref * hi / 1.1)
                else:
                    st.drift_on = med < ref * lo or med > ref * hi
                st.flag_info["drift"] = {"median_10m": round(med, 4), "ref_7d": round(ref, 4)}
            elif not ref:
                st.drift_on = False
        if st.drift_on:
            new.add("drift")
            info["drift"] = st.flag_info.get("drift", {})
        # supply / temperature
        vin = L.get("vin")
        if vin is not None:
            if st.c_vlow.update(vin < (cfg.vin_low + 0.5 if st.c_vlow.on else cfg.vin_low), now):
                new.add("vin_low"); info["vin_low"] = {"vin": vin}
            if st.c_vhigh.update(vin > (cfg.vin_high - 0.5 if st.c_vhigh.on else cfg.vin_high), now):
                new.add("vin_high"); info["vin_high"] = {"vin": vin}
        tc = L.get("tc")
        if tc is not None:
            if st.c_temp.update(tc > (cfg.temp_high - cfg.temp_clear_margin if st.c_temp.on else cfg.temp_high), now):
                new.add("temp_high"); info["temp_high"] = {"tc": tc}
        # reboot loop
        lo = now - cfg.reboot_window_s
        while st.boots and st.boots[0] < lo:
            st.boots.popleft()
        if len(st.boots) >= cfg.reboot_count:
            new.add("reboot_loop"); info["reboot_loop"] = {"boots": len(st.boots)}
        # link loss from sequence gaps
        lo = now - cfg.seqgap_window_s
        while st.gap and st.gap[0][0] < lo:
            st.gap.popleft()
        miss = sum(g[1] for g in st.gap)
        got = sum(g[2] for g in st.gap)
        tot = miss + got
        pct = 100.0 * miss / tot if tot else 0.0
        if st.link_on:
            if pct < cfg.seqgap_clear_pct:
                st.link_on = False
        elif tot >= cfg.seqgap_min_samples and pct > cfg.seqgap_pct:
            st.link_on = True
        if st.link_on:
            new.add("link_loss"); info["link_loss"] = {"loss_pct": round(pct, 1)}
        # firmware
        fw = L.get("fw")
        if st.c_fw.update(bool(cfg.expected_fw and fw and fw != cfg.expected_fw), now):
            new.add("fw_mismatch"); info["fw_mismatch"] = {"fw": fw, "expected": cfg.expected_fw}
        # node-reported fault
        if st.c_fault.update(st.fault_evt or s == "FAULT", now):
            new.add("fault"); info["fault"] = st.fault_info
        # CAL that never finishes (E105)
        if st.c_cal.update(s == "CAL", now):
            new.add("cal_stuck"); info["cal_stuck"] = {"since_s": round(cfg.cal_stuck_s)}
        # ACK button stuck (E401): the node reports how long the button has been held down (tele ackms, ms)
        if st.c_ack.update((L.get("ackms") or 0) >= cfg.ack_stuck_s * 1000.0, now):
            new.add("ack_stuck")
        # real alarm nobody acknowledged (E402)
        if st.alarm_active and not st.alarm_shadow and not st.alarm_acked \
                and now - st.alarm_since >= cfg.unacked_alarm_s:
            new.add("unacked_alarm"); info["unacked_alarm"] = {"alarm_min": round((now - st.alarm_since) / 60)}
        # optional noisy rule
        if cfg.noisy_ratio > 0:
            act_ok = cfg.noisy_act_max <= 0 or (L.get("act") or 0) < cfg.noisy_act_max
            if st.c_noisy.update((L.get("ratio") or 0) >= cfg.noisy_ratio and act_ok and s != "ALARM", now):
                new.add("noisy")

        self._apply_flags(st, new, info, now)

    def _apply_flags(self, st: NodeState, new: Set[str], info: Dict[str, Any], now: float) -> None:
        added, removed = new - st.flags, st.flags - new
        st.flags = new
        lab, n = self.label_of(st), st.machine or 0
        for f in sorted(added, key=FLAG_ORDER.index):
            code = E.FLAG_CODE[f]
            self.errors.open(code, st.mac, n, now, info.get(f) or {})
            self._event(now, n, st.mac, "HEALTH", "%s: ผิดปกติ — %s [%s]" % (lab, HEALTH_TEXT[f], code),
                        {"flag": f, "state": "set", **(info.get(f) or {})}, cloud="HEALTH", code=code)
        for f in sorted(removed, key=FLAG_ORDER.index):
            code = E.FLAG_CODE[f]
            self.errors.close(code, st.mac, now)
            self._event(now, n, st.mac, "HEALTH", "%s: หายแล้ว — %s [%s]" % (lab, HEALTH_TEXT[f], code),
                        {"flag": f, "state": "clear"}, cloud="HEALTH", code=code)

    def _drop_node_errors(self, st: NodeState, now: float) -> None:
        """A node that is no longer assigned to a machine carries no diagnosis."""
        st.flags = set()
        st.offline_notified = False
        self.errors.close_key(st.mac, now)

    # -------------------------------------------------------- fleet level
    def _plant_check(self, now: float) -> None:
        if self.plant_off or not self.mqtt_up:
            return
        cfg = self.cfg
        A = [s for s in self.states.values() if s.assigned]
        if self.carrier is False:
            self._plant_trigger(now, "nic_a_down", len(A))
            return
        if len(A) < cfg.plant_min_nodes:
            return
        if not all(self._is_offline(s, now) for s in A):
            return
        seen = [s for s in A if s.last_rx is not None]
        if not seen:
            if now >= self.grace_until:      # hub (re)booted and nobody ever answered
                self._plant_trigger(now, "all_silent", len(A))
            return
        mx = max(s.last_rx for s in seen)
        # "all nodes silent within plant_window_s of each other" (contract: 5 s). Nodes that died long
        # before (already reported offline) are not part of the simultaneous set but must be a minority.
        R = [s for s in seen if mx - s.last_rx <= cfg.plant_window_s]
        if now - mx > cfg.stale_s and len(R) >= cfg.plant_min_nodes and len(R) >= len(A) / 2.0:
            self._plant_trigger(now, "simultaneous_silence", len(R))

    def _plant_trigger(self, now: float, reason: str, count: int) -> None:
        total = sum(1 for s in self.states.values() if s.assigned)
        self.plant_off, self.plant_since, self.plant_reason = True, now, reason
        for s in self.states.values():
            s.offline_notified = False
            self.errors.close(E.OFFLINE_CODE, s.mac, now)       # superseded by the single fleet-level code
        self.errors.open("E310", E.HUB_KEY, 0, now, {"reason": reason, "nodes": total})
        self._event(now, 0, None, "PLANT_POWER_OFF",
                    "ไฟโรงสีถูกถอดปลั๊ก/ไฟดับ — โหนดทั้งหมด (%d ตัว) หยุดส่งสัญญาณพร้อมกัน" % total,
                    {"reason": reason, "nodes": total, "simultaneous": count}, cloud="PLANT_POWER_OFF", code="E310")
        log.warning("PLANT_POWER_OFF (%s)", reason)
        self.on_class_change()

    def _plant_restore(self, now: float) -> None:
        was = now - self.plant_since
        self.plant_off = False
        self.plant_restore_t = now
        self.grace_until = max(self.grace_until, now + self.cfg.boot_grace_s)
        for s in self.states.values():
            s.offline_notified = False
        total = sum(1 for s in self.states.values() if s.assigned)
        self.errors.close("E310", E.HUB_KEY, now)
        self._event(now, 0, None, "NODE_ONLINE",
                    "ไฟโรงสีกลับมาแล้ว (ดับไป %s) — โหนดกำลังกลับมาทำงาน" % _dur_th(was),
                    {"fleet": True, "reason": "plant_power_restored", "off_s": round(was), "nodes_total": total},
                    cloud="NODE_ONLINE", code="E310")
        log.warning("plant power restored after %.0fs", was)
        self.on_class_change()

    # ------------------------------------------------------ hub-level codes
    def set_hub_code(self, code: str, active: bool, now: Optional[float] = None, detail: Optional[dict] = None,
                     note: str = "") -> bool:
        """Open/close a hub or fleet scoped error (E50x ...). Writes one HEALTH event per transition (cloud-queued).
        Returns True when the state changed."""
        now = self.clock() if now is None else now
        flag = E.HUB_FLAG.get(code, code.lower())
        with self.lock:
            if active:
                if not self.errors.open(code, E.HUB_KEY, 0, now, detail or {}):
                    return False
                text = "ฮับ: %s [%s]%s" % (E.title(code), code, (" — " + note) if note else "")
                self._event(now, 0, None, "HEALTH", text, {"flag": flag, "state": "set", **(detail or {})},
                            cloud="HEALTH", code=code)
            else:
                if not self.errors.close(code, E.HUB_KEY, now):
                    return False
                self._event(now, 0, None, "HEALTH", "ฮับ: หายแล้ว — %s [%s]" % (E.title(code), code),
                            {"flag": flag, "state": "clear"}, cloud="HEALTH", code=code)
            self.on_class_change()
            return True

    def note_restart(self, what: str, now: Optional[float] = None, detail: Optional[dict] = None) -> None:
        """E506: hub-core or the broker restarted. Stays visible for restart_sticky_s."""
        now = self.clock() if now is None else now
        with self.lock:
            self.restart_until = max(self.restart_until, now + self.cfg.restart_sticky_s)
            d = dict(detail or {})
            d["what"] = what if "what" not in d else d["what"]
            self.set_hub_code("E506", True, now, d, note={"broker": "ตัวกลาง MQTT (mosquitto) รีสตาร์ท",
                                                          "unclean": "ฮับดับไม่ปกติครั้งก่อน (ไฟตก/ค้าง)"}.get(what, what))

    def _in_power_hours(self, now: float) -> bool:
        spec = (self.cfg.power_hours or "").strip()
        if not spec:
            return True
        try:
            a, b = spec.split("-")
            ah, am = (int(x) for x in a.split(":"))
            bh, bm = (int(x) for x in b.split(":"))
        except ValueError:
            return True
        ld = self.store.local_dt(now)
        cur = ld.hour * 60 + ld.minute
        return ah * 60 + am <= cur < bh * 60 + bm

    def _eval_nic(self, now: float) -> None:
        """E508: hub's NIC-A has no link although the switch should be powered (cable hub-switch / switch dead)."""
        down = self.carrier is False and (not self.plant_off or self._in_power_hours(now))
        on = self.c_nic.update(down, now)
        if on:
            self.set_hub_code("E508", True, now, {"nic": self.cfg.nic_a, "plant_off": self.plant_off})
        else:
            self.set_hub_code("E508", False, now)

    # ----------------------------------------------------------- snapshot
    def _today(self, now: float) -> Dict[str, Any]:
        t, v = self._today_cache
        if now - t >= 10 or t > now:
            day = self.store.date_of(now)
            start, _ = self.store.day_bounds(day)
            try:
                v = self.store.today_stats(start, now)
            except Exception:
                log.exception("today_stats failed")
            self._today_cache = (now, v)
        return v

    def _spark_list(self, st: NodeState, now: float, attr: str = "spark") -> List[Optional[float]]:
        b = int(now // self.SPARK_BUCKET)
        buckets = getattr(st, attr)
        out: List[Optional[float]] = []
        for i in range(b - self.SPARK_SLOTS + 1, b + 1):
            v = buckets.get(i)
            out.append(round(v[0] / v[1], 3) if v and v[1] else None)
        return out

    def _node_dict(self, st: NodeState, now: float, today: Dict[str, Any]) -> Dict[str, Any]:
        L = st.last
        n = st.machine
        offline = st.cls == "offline" or (st.cls == "new" and self._is_offline(st, now))
        waiting = (st.waiting_for_tele and st.last_rx is None and st.assignment_since is not None and
                   now - st.assignment_since < self.cfg.offline_event_s)
        d = {
            "n": n, "mac": st.mac, "label": self.label_of(st),
            "state": ("WAITING" if waiting else "OFFLINE" if offline else L.get("st") or "?"),
            "last_state": L.get("st"), "mode": L.get("mode"),
            "cls": "unknown" if waiting else st.cls, "since": int(st.cls_since), "waiting_for_tele": waiting,
            "last_seen_s": round(now - st.last_rx, 1) if st.last_rx is not None else None,
            "ratio": L.get("ratio"), "env": L.get("env"), "base": L.get("base"), "act": L.get("act"),
            "vin": L.get("vin"), "tc": L.get("tc"), "fw": L.get("fw"), "ack": L.get("ack", 0),
            "sat": L.get("sat"), "flat": L.get("flat"), "tl": L.get("tl"), "up": L.get("up"),
            "chb": bool(L.get("chb")), "dec": L.get("dec"), "fa": L.get("fa", 0), "b": L.get("b"),
            "ratio_b": (L.get("b") or {}).get("ratio") if L.get("b") else None,
            "health": [f for f in FLAG_ORDER if f in st.flags],
            "health_text": [HEALTH_TEXT[f] for f in FLAG_ORDER if f in st.flags],
            "alarm_active": st.alarm_active, "alarm_shadow": bool(st.alarm_active and st.alarm_shadow),
            "codes": self.errors.codes(st.mac), "errors": self.errors.entries(st.mac),
            "spark": self._spark_list(st, now),
            "spark_b": self._spark_list(st, now, "spark_b"),
            # which sensor raised the active alarm, as the node reported it (A pickup, B piezo, AB both); None if unknown
            "alarm_ch": (str(st.alarm_info.get("ch")).upper() if st.alarm_active and st.alarm_info.get("ch") else None),
        }
        if n:
            d["today_alarms"] = int(today["alarms"].get(n, 0))
            d["today_run_min"] = round(today["run_s"].get(n, 0.0) / 60.0, 1)
        return d

    def snapshot(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = self.clock() if now is None else now
        with self.lock:
            today = self._today(now)
            nodes: List[Dict[str, Any]] = []
            by_slot = {s.machine: s for s in self.states.values() if s.assigned}
            for n in range(1, 7):
                st = by_slot.get(n)
                if st is None:
                    nodes.append({"n": n, "mac": None, "label": self.default_label(n), "state": "EMPTY", "cls": "empty",
                                  "last_seen_s": None, "health": [], "health_text": [], "codes": [], "errors": [],
                                  "spark": [None] * self.SPARK_SLOTS, "spark_b": [None] * self.SPARK_SLOTS,
                                  "alarm_ch": None, "today_alarms": 0, "today_run_min": 0.0, "since": int(self.boot_ts)})
                else:
                    nodes.append(self._node_dict(st, now, today))
            new = []
            for st in self.states.values():
                if not st.assigned and st.last_rx is not None and now - st.last_rx <= self.cfg.new_node_visible_s:
                    new.append(self._node_dict(st, now, today))
            return {
                "now": now, "nodes": nodes, "new": new,
                "hub": {
                    "id": self.cfg.hub_id, "boot_ts": self.boot_ts, "up_s": round(now - self.boot_ts),
                    "mqtt": self.mqtt_ok, "plant_power_off": self.plant_off, "plant_since": self.plant_since or None,
                    "plant_reason": self.plant_reason, "nic_a_up": self.carrier, "grace_s": max(0, round(self.grace_until - now)),
                    "tz": self.cfg.tz, "expected_fw": self.cfg.expected_fw,
                    "codes": self.errors.codes(E.HUB_KEY), "errors": self.errors.entries(E.HUB_KEY),
                },
                "today": {"alarms": sum(today["alarms"].get(n, 0) for n in range(1, 7)),
                          "run_min": [round(today["run_s"].get(n, 0.0) / 60.0, 1) for n in range(1, 7)]},
            }


def _dur_th(s: float) -> str:
    s = int(max(0, s))
    if s < 90:
        return "%d วินาที" % s
    if s < 5400:
        return "%d นาที" % round(s / 60)
    return "%.1f ชั่วโมง" % (s / 3600.0)
