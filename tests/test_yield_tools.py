"""get_process_log: 공정 로그 조회 + in_spec 파생 필드."""

from tools import yield_tools as yt


def test_get_process_log_returns_4_steps_with_in_spec():
    logs = yt.get_process_log("W2406_02")
    assert len(logs) == 4
    assert all("in_spec" in r for r in logs)


def test_pattern_wafer_anomaly_flagged():
    logs = yt.get_process_log("W2406_02")
    bad = [r for r in logs if not r["in_spec"]]
    assert len(bad) == 1
    assert bad[0]["process_step"] == "Etch"
    assert bad[0]["equipment_id"] == "ETCH-9"


def test_unknown_wafer_returns_empty():
    assert yt.get_process_log("W_NOPE") == []
