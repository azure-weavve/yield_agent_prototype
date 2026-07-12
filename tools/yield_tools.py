"""수율 조회·집계 함수 (결정론적). LLM 이 끼어들지 않는 영역.

모든 함수는 plain dict/list 를 반환한다 (이후 LLM 답변 생성 노드가 소비).
"""

import sqlite3
from contextlib import contextmanager

import config


@contextmanager
def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def find_low_yield_lots(threshold: float = config.YIELD_THRESHOLD) -> list[dict]:
    """평균 수율이 threshold 미만인 lot 을 낮은 순으로 반환 (시나리오 1).

    각 lot 에 대해 가장 수율 낮은 wafer(worst_wafer) 를 함께 담아,
    시나리오 2(그 wafer 로 유사 검색)로 자연스럽게 이어지게 한다.
    """
    with _conn() as conn:
        lots = conn.execute(
            """
            SELECT lot_id, ROUND(AVG(yield), 1) AS avg_yield, COUNT(*) AS wafer_count
            FROM yield
            GROUP BY lot_id
            HAVING AVG(yield) < ?
            ORDER BY avg_yield ASC
            """,
            (threshold,),
        ).fetchall()

        result = []
        for lot in lots:
            worst = conn.execute(
                """
                SELECT wafer_id, yield, defect_type, process_step, date
                FROM yield WHERE lot_id = ? ORDER BY yield ASC LIMIT 1
                """,
                (lot["lot_id"],),
            ).fetchone()
            result.append({
                "lot_id": lot["lot_id"],
                "avg_yield": lot["avg_yield"],
                "wafer_count": lot["wafer_count"],
                "worst_wafer": dict(worst),
            })
        return result


def get_wafer(wafer_id: str) -> dict | None:
    """단일 wafer 의 수율 행 반환."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM yield WHERE wafer_id = ?", (wafer_id,)
        ).fetchone()
        return dict(row) if row else None


def aggregate_defects(wafer_ids: list[str]) -> list[dict]:
    """주어진 wafer 들의 defect_type 분포 집계 (시나리오 3: 원인 추정)."""
    if not wafer_ids:
        return []
    placeholders = ",".join("?" * len(wafer_ids))
    with _conn() as conn:
        rows = conn.execute(
            f"""
            SELECT defect_type, COUNT(*) AS count
            FROM yield WHERE wafer_id IN ({placeholders})
            GROUP BY defect_type ORDER BY count DESC
            """,
            wafer_ids,
        ).fetchall()
        return [dict(r) for r in rows]


def get_process_log(wafer_id: str) -> list[dict]:
    """wafer 의 공정 단계별 장비·파라미터 로그. in_spec 파생 필드 포함."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM process_log WHERE wafer_id = ?", (wafer_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["in_spec"] = bool(d["spec_low"] <= d["param_value"] <= d["spec_high"])
            out.append(d)
        return out


def find_defect_group(lot_id: str, threshold: float = config.YIELD_THRESHOLD) -> dict:
    """lot 내 그룹 대조 분석 입력 (그룹 판정은 코드가 한다 — 결정론적).

    불량 그룹 = 수율 임계 미만이면서 같은 defect_type 을 공유하는 wafer 들
    (여러 유형이면 최대 그룹, 동수면 평균 수율 낮은 쪽).
    대조 그룹 = 같은 lot 의 defect_type='none' wafer 들.
    """
    with _conn() as conn:
        top = conn.execute(
            """
            SELECT defect_type FROM yield
            WHERE lot_id = ? AND yield < ? AND defect_type != 'none'
            GROUP BY defect_type
            ORDER BY COUNT(*) DESC, AVG(yield) ASC
            LIMIT 1
            """,
            (lot_id, threshold),
        ).fetchone()
        defect = top["defect_type"] if top else ""
        target = [] if not defect else [
            r["wafer_id"] for r in conn.execute(
                """
                SELECT wafer_id FROM yield
                WHERE lot_id = ? AND yield < ? AND defect_type = ?
                ORDER BY wafer_id
                """,
                (lot_id, threshold, defect),
            ).fetchall()
        ]
        control = [
            r["wafer_id"] for r in conn.execute(
                "SELECT wafer_id FROM yield WHERE lot_id = ? AND defect_type = 'none' ORDER BY wafer_id",
                (lot_id,),
            ).fetchall()
        ]
        return {"lot_id": lot_id, "defect_type": defect,
                "target_group": target, "control_group": control}


def compare_process_logs(group_ids: list[str], control_ids: list[str]) -> dict:
    """불량 그룹 vs 대조 그룹 공정 로그 대조 (그룹 대조의 수치 계산은 전부 여기서).

    - suspect_equipment: 불량 그룹 전원이 거쳤고 대조 그룹은 안 거친 (공정, 장비)
    - equipment_usage: (공정, 장비)별 두 그룹의 통과 wafer 수 전체 대조표
    - group_spec_violations: 불량 그룹의 스펙 이탈 행 전부
    """
    def _usage(conn, ids):
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"""
            SELECT process_step, equipment_id, COUNT(*) AS n
            FROM process_log WHERE wafer_id IN ({placeholders})
            GROUP BY process_step, equipment_id
            """,
            ids,
        ).fetchall()
        return {(r["process_step"], r["equipment_id"]): r["n"] for r in rows}

    with _conn() as conn:
        g, c = _usage(conn, group_ids), _usage(conn, control_ids)
        usage = [
            {"process_step": step, "equipment_id": equip,
             "group_count": g.get((step, equip), 0),
             "control_count": c.get((step, equip), 0)}
            for step, equip in sorted(set(g) | set(c))
        ]
        usage.sort(key=lambda r: (-r["group_count"], r["control_count"],
                                  r["process_step"], r["equipment_id"]))

        violations = []
        if group_ids:
            placeholders = ",".join("?" * len(group_ids))
            violations = [dict(r) for r in conn.execute(
                f"""
                SELECT wafer_id, process_step, equipment_id, param_name,
                       param_value, spec_low, spec_high
                FROM process_log
                WHERE wafer_id IN ({placeholders})
                  AND NOT (spec_low <= param_value AND param_value <= spec_high)
                ORDER BY wafer_id
                """,
                group_ids,
            ).fetchall()]

    suspects = [r for r in usage
                if group_ids and r["group_count"] == len(group_ids) and r["control_count"] == 0]
    return {"suspect_equipment": suspects,
            "equipment_usage": usage,
            "group_spec_violations": violations}
