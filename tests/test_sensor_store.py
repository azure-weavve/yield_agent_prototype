"""SensorStore — 가져오기 계층 (EDS 와 같은 local↔http 교체 패턴)."""

import pytest

import config
from data.generate_dummy import GROUP_WAFERS, SENSOR_REAL, SENSOR_STEP
from tools import sensor_store as ss


def test_local_store_fetches_requested_wafers_only():
    rows = ss.LocalSensorStore().fetch(SENSOR_STEP, GROUP_WAFERS)
    assert rows
    assert {r["wafer_id"] for r in rows} <= set(GROUP_WAFERS)
    assert all(r["step_seq"] == SENSOR_STEP for r in rows)
    assert {"wafer_id", "step_seq", "sensor_name", "value", "tkout_time"} == set(rows[0])
    assert any(r["sensor_name"] == f"{SENSOR_REAL}_avg" for r in rows)


def test_local_store_empty_wafer_list():
    assert ss.LocalSensorStore().fetch(SENSOR_STEP, []) == []


def test_get_store_honors_mode(monkeypatch):
    monkeypatch.setattr(config, "SENSOR_MODE", "local")
    assert isinstance(ss.get_store(), ss.LocalSensorStore)
    monkeypatch.setattr(config, "SENSOR_MODE", "nope")
    with pytest.raises(ValueError, match="SENSOR_MODE"):
        ss.get_store()
