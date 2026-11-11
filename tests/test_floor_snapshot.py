"""Snapshot fields used by the floor dashboard: Piezo sparkline and the alarm channel."""
from conftest import MACS


def test_piezo_sparkline_follows_channel_b_and_stays_empty_without_it(H):
    h = H(assign=2, boot_grace_s=0)
    a, b = MACS[0], MACS[1]
    h.run(3, per=lambda i, m: {"b": {"env": 100.0, "base": 100.0, "ratio": 1.4, "act": 60.0, "sat": 0, "flat": 0}} if m == a else {})
    with_b, without_b = h.node(1), h.node(2)
    assert with_b["chb"] and any(v == 1.4 for v in with_b["spark_b"])
    assert len(with_b["spark_b"]) == len(with_b["spark"])
    assert not without_b["chb"] and all(v is None for v in without_b["spark_b"])
    empty = h.node(3)
    assert empty["cls"] == "empty" and empty["spark_b"] == [None] * len(empty["spark"]) and empty["alarm_ch"] is None


def test_alarm_channel_is_reported_only_while_the_alarm_is_active(H):
    h = H(assign=1, boot_grace_s=0)
    mac = MACS[0]
    h.run(2)
    assert h.node(1)["alarm_ch"] is None
    h.eng.on_evt(mac, {"type": "ALARM_ON", "seq": 1, "up": 200, "info": {"ch": "b", "dec": "B"}}, h.now)
    assert h.node(1)["alarm_ch"] == "B"
    h.eng.on_evt(mac, {"type": "ALARM_OFF", "seq": 2, "up": 201, "info": {}}, h.now + 1)
    assert h.node(1)["alarm_ch"] is None


def test_alarm_without_channel_is_not_guessed(H):
    h = H(assign=1, boot_grace_s=0)
    h.run(1)
    h.eng.on_evt(MACS[0], {"type": "ALARM_ON", "seq": 1, "up": 200, "info": {}}, h.now)
    assert h.node(1)["alarm_ch"] is None
