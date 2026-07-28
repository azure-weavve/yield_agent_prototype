"""수율 조회·집계 함수 (결정론적). LLM 이 끼어들지 않는 영역.

모든 함수는 plain dict/list 를 반환한다 (이후 LLM 답변 생성 노드가 소비).
"""

import sqlite3
import statistics
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


def find_low_yield_lots(threshold: float | None = None) -> list[dict]:
    """평균 수율이 threshold 미만인 lot 을 낮은 순으로 반환.

    각 lot 에 대해 가장 수율 낮은 wafer(worst_wafer) 를 함께 담아,
    자동 대상 선정(tools/target_selection.py)의 재료로 쓴다.
    """
    threshold = config.YIELD_THRESHOLD if threshold is None else threshold
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


def get_wafers(wafer_ids: list[str]) -> list[dict]:
    """여러 wafer 의 yield 행 반환 (존재하는 것만, wafer_id 순 — 입력 검증·소속 lot 조회용)."""
    if not wafer_ids:
        return []
    placeholders = ",".join("?" * len(wafer_ids))
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM yield WHERE wafer_id IN ({placeholders}) ORDER BY wafer_id",
            wafer_ids,
        ).fetchall()
        return [dict(r) for r in rows]


def find_control_candidates(root_lot_ids: list[str], exclude: set[str]) -> list[str]:
    """주어진 root_lot 들의 비타깃 wafer 전원 (수율·라벨·lot_type 조건 없음).

    사내 defect_type 은 대부분 NULL 이라 '정상' 을 판정할 방법이 없다. 저수율 피해
    wafer 가 대조군에 섞이는 것을 **막지 않고 보이게 한다** — commonality 의 2x2
    (control_pass)와 select_control 의 yield_summary 가 그 자리다.
    수율 임계로 거르면 임의 수치가 계산에 들어간다 (spec 2026-07-25 §1).
    """
    if not root_lot_ids:
        return []
    placeholders = ",".join("?" * len(root_lot_ids))
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT wafer_id FROM yield WHERE root_lot_id IN ({placeholders}) "
            f"ORDER BY wafer_id",
            list(root_lot_ids),
        ).fetchall()
    return [r["wafer_id"] for r in rows if r["wafer_id"] not in exclude]


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
                  AND ((spec_low IS NOT NULL AND param_value < spec_low)
                       OR (spec_high IS NOT NULL AND param_value > spec_high))
                ORDER BY wafer_id
                """,
                group_ids,
            ).fetchall()]

    suspects = [r for r in usage
                if group_ids and r["group_count"] == len(group_ids) and r["control_count"] == 0]
    return {"suspect_equipment": suspects,
            "equipment_usage": usage,
            "group_spec_violations": violations}


def validate_data_completeness(wafer_ids: list[str]) -> dict:
    """분석 대상 wafer 들의 데이터 완전성 검사 (분석 전제 확인 — 결정론적).

    대조 그룹 로그가 결측이면 compare_process_logs 의 suspect 판정
    (control_count == 0)이 허위 양성이 되므로, 그룹 대조 전에 이 검사로 막는다.
    - blocked: 수율 행 누락 또는 공정 로그 단계 누락 (비교 결과 신뢰 불가)
    - warning: 중복 로그만 존재 (집계가 부풀 수 있음)
    - good: 문제 없음
    """
    result = {
        "checked_wafers": len(wafer_ids),
        "missing_yield_rows": [],
        "missing_log_steps": [],
        "duplicate_logs": [],
        "status": "good",
        "warnings": [],
    }
    if not wafer_ids:
        result["status"] = "blocked"
        result["warnings"].append("검사할 wafer 가 없다.")
        return result

    placeholders = ",".join("?" * len(wafer_ids))
    with _conn() as conn:
        have_yield = {r["wafer_id"] for r in conn.execute(
            f"SELECT wafer_id FROM yield WHERE wafer_id IN ({placeholders})",
            wafer_ids,
        ).fetchall()}
        # 기대 단계 = 전체 process_log 에 존재하는 단계 집합 (스키마가 아닌 데이터 기준)
        expected_steps = {r["process_step"] for r in conn.execute(
            "SELECT DISTINCT process_step FROM process_log"
        ).fetchall()}
        step_rows = conn.execute(
            f"""
            SELECT wafer_id, process_step, param_name, COUNT(*) AS n
            FROM process_log WHERE wafer_id IN ({placeholders})
            GROUP BY wafer_id, process_step, param_name
            ORDER BY wafer_id, process_step
            """,
            wafer_ids,
        ).fetchall()

    result["missing_yield_rows"] = sorted(set(wafer_ids) - have_yield)

    steps_by_wafer: dict[str, set] = {}
    for r in step_rows:
        steps_by_wafer.setdefault(r["wafer_id"], set()).add(r["process_step"])
        if r["n"] > 1:
            result["duplicate_logs"].append({
                "wafer_id": r["wafer_id"], "process_step": r["process_step"],
                "param_name": r["param_name"], "count": r["n"],
            })
    for wid in wafer_ids:
        missing = sorted(expected_steps - steps_by_wafer.get(wid, set()))
        if missing:
            result["missing_log_steps"].append(
                {"wafer_id": wid, "missing_steps": missing})

    if result["missing_yield_rows"] or result["missing_log_steps"]:
        result["status"] = "blocked"
        result["warnings"].append(
            "수율 행 또는 공정 로그 누락 — 그룹 대조 결과를 신뢰할 수 없다.")
    elif result["duplicate_logs"]:
        result["status"] = "warning"
        result["warnings"].append("중복 로그 존재 — 집계 수치가 부풀 수 있다.")
    return result


def compare_parameter_distribution(group_ids: list[str], control_ids: list[str],
                                   process_step: str | None = None,
                                   param_name: str | None = None) -> list[dict]:
    """두 그룹의 공정 파라미터 분포 비교 (효과 크기 포함 — 결정론적).

    (process_step, param_name) 단위로 기술통계·평균차·Cohen's d·스펙 이탈률을
    계산해 |effect_size| 내림차순으로 반환한다. 스펙 안이어도 그룹 간 체계적
    차이를 잡는 것이 목적. 표본이 작으므로 p-value 는 계산하지 않는다
    (효과 크기·이탈률·표본 수를 함께 제시 — 로드맵 원칙).
    """
    def _rows(conn, ids):
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        sql = (f"SELECT process_step, param_name, param_value, spec_low, spec_high "
               f"FROM process_log WHERE wafer_id IN ({placeholders})")
        args = list(ids)
        if process_step:
            sql += " AND process_step = ?"
            args.append(process_step)
        if param_name:
            sql += " AND param_name = ?"
            args.append(param_name)
        return conn.execute(sql, args).fetchall()

    def _bucket(rows):
        by_key = {}
        for r in rows:
            by_key.setdefault((r["process_step"], r["param_name"]), []).append(r)
        return by_key

    def _stats(rows):
        values = [r["param_value"] for r in rows]
        if not values:
            return ({"n": 0, "mean": None, "median": None, "std": None,
                     "min": None, "max": None}, 0.0)
        spec_rows = [r for r in rows if r["spec_low"] is not None or r["spec_high"] is not None]
        violations = sum(
            1 for r in spec_rows
            if (r["spec_low"] is not None and r["param_value"] < r["spec_low"])
            or (r["spec_high"] is not None and r["param_value"] > r["spec_high"]))
        violation_rate = round(violations / len(spec_rows), 3) if spec_rows else None
        return ({
            "n": len(values),
            "mean": round(statistics.fmean(values), 3),
            "median": round(statistics.median(values), 3),
            "std": round(statistics.stdev(values), 3) if len(values) >= 2 else None,
            "min": min(values),
            "max": max(values),
        }, violation_rate)

    def _cohens_d(g_vals, c_vals):
        n1, n2 = len(g_vals), len(c_vals)
        if n1 + n2 < 3:  # 자유도(n1+n2-2) 확보 불가
            return None
        var1 = statistics.variance(g_vals) if n1 >= 2 else 0.0
        var2 = statistics.variance(c_vals) if n2 >= 2 else 0.0
        pooled = (((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)) ** 0.5
        if pooled == 0:
            return None
        return round((statistics.fmean(g_vals) - statistics.fmean(c_vals)) / pooled, 3)

    with _conn() as conn:
        g_by_key = _bucket(_rows(conn, group_ids))
        c_by_key = _bucket(_rows(conn, control_ids))

    out = []
    for key in sorted(set(g_by_key) | set(c_by_key)):
        g_rows, c_rows = g_by_key.get(key, []), c_by_key.get(key, [])
        g_stats, g_viol = _stats(g_rows)
        c_stats, c_viol = _stats(c_rows)
        mean_diff = effect = None
        if g_stats["n"] and c_stats["n"]:
            g_vals = [r["param_value"] for r in g_rows]
            c_vals = [r["param_value"] for r in c_rows]
            mean_diff = round(statistics.fmean(g_vals) - statistics.fmean(c_vals), 3)
            effect = _cohens_d(g_vals, c_vals)
        out.append({
            "process_step": key[0], "param_name": key[1],
            "group": g_stats, "control": c_stats,
            "mean_diff": mean_diff, "effect_size": effect,
            "spec_violation_rate_group": g_viol,
            "spec_violation_rate_control": c_viol,
        })
    out.sort(key=lambda r: (r["effect_size"] is None,
                            -abs(r["effect_size"] or 0.0)))
    return out


def find_counterexamples(equipment_id: str, process_step: str,
                         defect_type: str) -> dict:
    """가설 '(process_step, equipment_id) 가 defect_type 의 원인'의 반례 탐색.

    전수 데이터에서 명시적으로 찾는다 (확증 편향 방지 — 결정론적):
    - passed_but_normal: 해당 장비를 거쳤지만 정상(defect 'none')인 wafer
    - defect_without_equipment: 해당 장비 없이 같은 defect 가 난 wafer
    두 목록이 모두 비면 가설의 특이성이 전수 데이터에서 확인된 것이다.
    """
    with _conn() as conn:
        # 가정: (wafer, step) 당 로그 1행 — 다중 파라미터 스키마가 되면 wafer 수가 중복 집계된다
        users = conn.execute(
            """
            SELECT y.wafer_id, y.yield, y.defect_type,
                   p.param_value, p.spec_low, p.spec_high
            FROM process_log p JOIN yield y ON y.wafer_id = p.wafer_id
            WHERE p.process_step = ? AND p.equipment_id = ?
            ORDER BY y.wafer_id
            """,
            (process_step, equipment_id),
        ).fetchall()
        defects = [dict(r) for r in conn.execute(
            "SELECT wafer_id, yield FROM yield WHERE defect_type = ? ORDER BY wafer_id",
            (defect_type,),
        ).fetchall()]

    def _in_spec(u):
        if u["spec_low"] is None and u["spec_high"] is None:
            return None
        low_ok = u["spec_low"] is None or u["spec_low"] <= u["param_value"]
        high_ok = u["spec_high"] is None or u["param_value"] <= u["spec_high"]
        return bool(low_ok and high_ok)

    user_ids = {u["wafer_id"] for u in users}
    passed_but_normal = [
        {"wafer_id": u["wafer_id"], "yield": u["yield"], "in_spec": _in_spec(u)}
        for u in users if u["defect_type"] == "none"
    ]
    defect_without_equipment = [d for d in defects if d["wafer_id"] not in user_ids]

    return {
        "equipment_id": equipment_id,
        "process_step": process_step,
        "defect_type": defect_type,
        "equipment_wafers": len(users),
        "passed_but_normal": passed_but_normal,
        "passed_but_normal_rate":
            round(len(passed_but_normal) / len(users), 3) if users else 0.0,
        "defect_wafers": len(defects),
        "defect_without_equipment": defect_without_equipment,
        "defect_without_equipment_rate":
            round(len(defect_without_equipment) / len(defects), 3) if defects else 0.0,
    }
