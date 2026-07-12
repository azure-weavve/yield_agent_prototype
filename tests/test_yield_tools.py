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


def test_find_defect_group_splits_target_and_control():
    grp = yt.find_defect_group("LOT2406")
    assert grp["defect_type"] == "center_spot"
    assert grp["target_group"] == ["W2406_02", "W2406_04", "W2406_06"]
    assert grp["control_group"] == ["W2406_01", "W2406_03", "W2406_05"]


def test_find_defect_group_unknown_lot_returns_empty():
    grp = yt.find_defect_group("LOT_NOPE")
    assert grp["defect_type"] == ""
    assert grp["target_group"] == []
    assert grp["control_group"] == []


def test_compare_process_logs_finds_suspect_equipment_and_violations():
    res = yt.compare_process_logs(
        ["W2406_02", "W2406_04", "W2406_06"],
        ["W2406_01", "W2406_03", "W2406_05"],
    )
    # 불량 그룹 전원이 거쳤고 대조 그룹은 안 거친 장비에 ETCH-9 가 잡힌다
    suspects = {(r["process_step"], r["equipment_id"]) for r in res["suspect_equipment"]}
    assert ("Etch", "ETCH-9") in suspects
    # 스펙 이탈은 불량 그룹 3장 전부, 모두 ETCH-9
    assert len(res["group_spec_violations"]) == 3
    assert all(v["equipment_id"] == "ETCH-9" for v in res["group_spec_violations"])
    # 대조표에는 두 그룹의 통과 수가 담긴다
    etch9 = next(r for r in res["equipment_usage"]
                 if (r["process_step"], r["equipment_id"]) == ("Etch", "ETCH-9"))
    assert (etch9["group_count"], etch9["control_count"]) == (3, 0)


def test_compare_process_logs_empty_inputs():
    res = yt.compare_process_logs([], [])
    assert res == {"suspect_equipment": [], "equipment_usage": [], "group_spec_violations": []}
