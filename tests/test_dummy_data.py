"""process_log 더미 데이터 검증.

데모 성립 조건: 패턴 그룹 wafer 는 자기 그룹의 공정 단계에서만
'공유 이상 장비(-9) + 스펙 초과'를 갖고, 정상 wafer 는 전부 스펙 내.
"""

import sqlite3

import config


def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_process_log_table_exists_with_4_rows_per_wafer():
    with _conn() as conn:
        wafers = conn.execute("SELECT COUNT(*) FROM yield").fetchone()[0]
        logs = conn.execute("SELECT COUNT(*) FROM process_log").fetchone()[0]
        assert logs == wafers * 4


def test_pattern_wafer_has_single_anomaly_at_its_step():
    with _conn() as conn:
        # center_spot 그룹 최근 wafer — 그룹 공정은 Etch
        rows = conn.execute(
            "SELECT * FROM process_log WHERE wafer_id = 'W2406_cen0'"
        ).fetchall()
        bad = [r for r in rows if not (r["spec_low"] <= r["param_value"] <= r["spec_high"])]
        assert len(bad) == 1
        assert bad[0]["process_step"] == "Etch"
        assert bad[0]["equipment_id"] == "ETCH-9"


def test_group_members_share_anomaly_equipment():
    with _conn() as conn:
        members = [
            r["wafer_id"]
            for r in conn.execute(
                "SELECT wafer_id FROM yield WHERE defect_type = 'center_spot'"
            ).fetchall()
        ]
        assert len(members) >= 2
        for wid in members:
            bad = conn.execute(
                """
                SELECT equipment_id FROM process_log
                WHERE wafer_id = ? AND NOT (spec_low <= param_value AND param_value <= spec_high)
                """,
                (wid,),
            ).fetchall()
            assert [r["equipment_id"] for r in bad] == ["ETCH-9"]


def test_normal_wafer_all_in_spec():
    with _conn() as conn:
        bad = conn.execute(
            """
            SELECT COUNT(*) FROM process_log p
            JOIN yield y ON y.wafer_id = p.wafer_id
            WHERE y.defect_type = 'none'
              AND NOT (p.spec_low <= p.param_value AND p.param_value <= p.spec_high)
            """
        ).fetchone()[0]
        assert bad == 0
