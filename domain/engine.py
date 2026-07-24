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


def evaluate(spec, group_ids, control_ids):
    fn = COMPARISONS[spec["comparison"]]
    candidates = fn(group_ids, control_ids, spec["column"], spec)
    return {"hypothesis_id": spec["id"], "comparison": spec["comparison"],
            "column": spec["column"], "candidates": candidates}


COMPARISONS = {"group_only_categorical": group_only_categorical}
