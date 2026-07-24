"""인과 가설 비교타입 + 판별 계층 (결정론적, 개발자 영역).

각 비교타입은 (group_ids, control_ids, column, spec) -> list[Candidate].
판별(passes)은 비교타입별 어울리는 잣대만 본다 (spec §5).
"""

import sqlite3
import statistics
from contextlib import contextmanager

import config

DEFAULT_MIN_SPECIFICITY = 0.8
DEFAULT_MIN_EFFECT_SIZE = 0.8
DEFAULT_MAX_COUNTEREXAMPLE_RATE = 0.2


@contextmanager
def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _assert_column(conn, column):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(process_log)")}
    if column not in cols:
        raise ValueError(f"컬럼 '{column}' 없음 (process_log). 가능한 컬럼: {', '.join(sorted(cols))}")


def _usage(conn, ids, column):
    """(process_step, column값) -> 통과 wafer 수. 값이 NULL/빈 문자열이면 제외."""
    _assert_column(conn, column)
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT process_step, {column} AS val, COUNT(DISTINCT wafer_id) AS n "
        f"FROM process_log WHERE wafer_id IN ({ph}) "
        f"AND {column} IS NOT NULL AND {column} != '' "
        f"GROUP BY process_step, {column}", ids).fetchall()
    return {(r["process_step"], r["val"]): r["n"] for r in rows}


def _counterexamples(column, value, process_step, defect_type):
    """가설 '(process_step, column=value) 가 defect_type 의 원인'의 반례 (전수 데이터).

    - passed_but_normal_rate: 그 값을 거쳤지만 정상(defect none)인 wafer 비율
    - defect_without_cause_rate: 그 값 없이 같은 defect 가 난 wafer 비율
    (기존 find_counterexamples 를 임의 컬럼으로 일반화)
    """
    with _conn() as conn:
        _assert_column(conn, column)
        users = conn.execute(
            f"SELECT DISTINCT y.wafer_id, y.defect_type FROM process_log p "
            f"JOIN yield y ON y.wafer_id = p.wafer_id "
            f"WHERE p.process_step = ? AND p.{column} = ?",
            (process_step, value)).fetchall()
        defects = conn.execute(
            "SELECT wafer_id FROM yield WHERE defect_type = ?", (defect_type,)).fetchall()
    user_ids = {u["wafer_id"] for u in users}
    passed_but_normal = [u for u in users if u["defect_type"] == "none"]
    defect_without = [d for d in defects if d["wafer_id"] not in user_ids]
    return {
        "passed_but_normal_rate": round(len(passed_but_normal) / len(users), 3) if users else 0.0,
        "defect_without_cause_rate": round(len(defect_without) / len(defects), 3) if defects else 0.0,
        "equipment_wafers": len(users), "defect_wafers": len(defects),
    }


def group_only_categorical(group_ids, control_ids, column, spec):
    min_spec = spec.get("min_specificity", DEFAULT_MIN_SPECIFICITY)
    n_group = len(group_ids)
    with _conn() as conn:
        g, c = _usage(conn, group_ids, column), _usage(conn, control_ids, column)
    cands = []
    for key in sorted(set(g) | set(c)):
        gc, cc = g.get(key, 0), c.get(key, 0)
        specificity = round(gc / n_group, 3) if (cc == 0 and n_group) else 0.0
        cands.append({
            "value": [key[0], key[1]], "specificity": specificity,
            "counterexamples": {}, "effect_size": None, "spec_violation_rate": None,
            "n_group": gc, "n_control": cc,
            "passes": specificity >= min_spec,
            "reject_reason": None if specificity >= min_spec
            else f"특이성 {specificity} < {min_spec}",
        })
    cands.sort(key=lambda x: -x["specificity"])
    return cands


def _cohens_d(g_vals, c_vals):
    n1, n2 = len(g_vals), len(c_vals)
    if n1 + n2 < 3:
        return None
    var1 = statistics.variance(g_vals) if n1 >= 2 else 0.0
    var2 = statistics.variance(c_vals) if n2 >= 2 else 0.0
    pooled = (((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)) ** 0.5
    if pooled == 0:
        return None
    return round((statistics.fmean(g_vals) - statistics.fmean(c_vals)) / pooled, 3)


def _numeric_rows(conn, ids, column):
    _assert_column(conn, column)
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT process_step, param_name, {column} AS val, spec_low, spec_high "
        f"FROM process_log WHERE wafer_id IN ({ph})", ids).fetchall()
    by = {}
    for r in rows:
        by.setdefault((r["process_step"], r["param_name"]), []).append(r)
    return by


def _spec_violation_rate(rows):
    spec_rows = [r for r in rows if r["spec_low"] is not None or r["spec_high"] is not None]
    if not spec_rows:
        return None
    v = sum(1 for r in spec_rows
            if (r["spec_low"] is not None and r["val"] < r["spec_low"])
            or (r["spec_high"] is not None and r["val"] > r["spec_high"]))
    return round(v / len(spec_rows), 3)


def numeric_distribution_shift(group_ids, control_ids, column, spec):
    min_eff = spec.get("min_effect_size", DEFAULT_MIN_EFFECT_SIZE)
    max_ce = spec.get("max_counterexample_rate", DEFAULT_MAX_COUNTEREXAMPLE_RATE)
    with _conn() as conn:
        g = _numeric_rows(conn, group_ids, column)
        c = _numeric_rows(conn, control_ids, column)
    cands = []
    for key in sorted(set(g) | set(c)):
        g_rows, c_rows = g.get(key, []), c.get(key, [])
        g_vals = [r["val"] for r in g_rows]
        c_vals = [r["val"] for r in c_rows]
        effect = _cohens_d(g_vals, c_vals) if g_vals and c_vals else None
        sv_rate = _spec_violation_rate(g_rows)
        # 반례: 대조군 중 불량군 범위(min~max)에 드는 비율 = 분포 겹침
        overlap = 0.0
        if g_vals and c_vals:
            lo, hi = min(g_vals), max(g_vals)
            overlap = round(sum(1 for v in c_vals if lo <= v <= hi) / len(c_vals), 3)
        passes = effect is not None and abs(effect) >= min_eff and overlap <= max_ce
        cands.append({
            "value": [key[0], key[1]], "specificity": None,
            "counterexamples": {"control_overlap_rate": overlap},
            "effect_size": effect, "spec_violation_rate": sv_rate,
            "n_group": len(g_vals), "n_control": len(c_vals),
            "passes": passes,
            "reject_reason": None if passes else "효과크기 부족 또는 분포 겹침",
        })
    cands.sort(key=lambda x: (x["effect_size"] is None, -abs(x["effect_size"] or 0.0)))
    return cands


def evaluate(spec, group_ids, control_ids):
    fn = COMPARISONS[spec["comparison"]]
    candidates = fn(group_ids, control_ids, spec["column"], spec)
    return {"hypothesis_id": spec["id"], "comparison": spec["comparison"],
            "column": spec["column"], "candidates": candidates}


COMPARISONS = {"group_only_categorical": group_only_categorical,
               "numeric_distribution_shift": numeric_distribution_shift}
