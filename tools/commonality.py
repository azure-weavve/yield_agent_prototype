"""설비/챔버 commonality 분석 (결정론적). 2단 깔때기의 1단.
 
목적: 수만~수십만 개 센서를 보기 전에, **어느 스텝의 어느 설비/챔버가 의심스러운지**를
설비 이력(step_history)만으로 좁힌다. 특징 차원이 스텝 수(~1000) 수준이라 싸다.
 
핵심 계산 — 후보 (스텝, 설비/챔버) 마다 2x2:
 
                통과    미통과
    target       a       b        coverage_target  = a / (a+b)
    control      c       d        coverage_control = c / (c+d)
                                  score = coverage_target - coverage_control
 
score = 1.0 이면 타깃 전원이 거쳤고 대조군은 아무도 안 거친 완전 분리 신호.
 
설계 원칙:
- **p-value 를 계산하지 않는다.** 후보가 수천 개라 다중비교로 유의성 주장이 불가능하다.
  원시 카운트(a/b/c/d)를 그대로 실어, "결론이 아니라 후보"임이 드러나게 한다.
- **root_lot 별 층화.** 대조군은 항상 타깃과 같은 root_lot 에서 나온다(route/시간 교락 차단).
  타깃이 여러 root_lot 에 걸치면(EDS 확장 케이스) stratum 별로 세고 카운트를 합산한다.
- **분모는 그 질문에 답할 수 있는 wafer 만.** 후보 (레벨, 스텝) 마다 "그 스텝에 이력이
  있고 그 레벨 컬럼이 결측이 아닌 wafer" 를 분모로 쓴다. 스텝을 안 지난 wafer 를
  '미통과' 로 세면 score 가 챔버 분리도가 아니라 스텝 통과 여부를 반영한다.
  예외는 step_passage — 모든 wafer 가 "지났는가" 에 답할 수 있어 legend 에
  denominator: all 을 단다. 이력이 아예 없는 wafer 는 missing_history 로 따로 보고한다.
- **lot_type 은 필터가 아니라 컨텍스트.** 평가랏에는 설비 작업 후 검증랏이 섞여 있어
  배제하면 단서를 버린다. 분포만 meta 에 싣는다.
 
의존 테이블 (ETL 선적재 대상):
    step_history(wafer_id, step_seq, eqp_id, ch_id·ppid NULL 허용, timestamp)
    yield(wafer_id, ..., root_lot_id, lot_type)
"""
 
import sqlite3
from contextlib import contextmanager
 
import ya_config
 
# config 에 없으면 쓰는 기본값 (실데이터 보고 조정 — 지금 못 박지 않는다)
MIN_TARGET = getattr(ya_config, "COMMONALITY_MIN_TARGET", 2)
TOP_K = getattr(ya_config, "COMMONALITY_TOP_K", 20)
MIN_SCORE = getattr(ya_config, "COMMONALITY_MIN_SCORE", 0.0)

# 계산 자체가 성립하지 않은 상태들. **legend 와 무관한 그룹 수준 사실**이라 다른
# legend 로 다시 돌려도 같은 답이 나온다 — 게이트(graph/nodes.py)가 "남은 가설을 더
# 돌려라" 대신 그 자리에서 사유를 밝히고 끝내는 근거다. 아래 find_commonality 의
# status 서술이 원본이고, 여기는 그중 '계산 불가' 만 추린 것이다.
NO_DATA_STATUSES = frozenset({"insufficient_group", "no_paired_stratum"})

# 기본 legend — EQP_CH (legend 인자 없으면 이 동작). 레벨 순서 = 롤업(설비) → 세부(챔버).
EQP_CH_LEGEND = [
    {"level": "equipment", "columns": ["eqp_id"]},
    {"level": "chamber", "columns": ["eqp_id", "ch_id"]},
]

# legend 컬럼값이 이 토큰이면 결측(NULL/빈문자열과 동일 취급) — ch_id·ppid 등 챔버·PPID
# 개념이 없는 스텝에서 흔히 쓰는 결측 토큰. 2·3단계(metro) 분모도 같은 집합을 쓴다.
MISSING_TOKENS = frozenset({"-"})


@contextmanager
def _conn():
    conn = sqlite3.connect(ya_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
 
 
def _wafer_meta(conn, wafer_ids: list[str]) -> dict[str, dict]:
    """wafer_id -> {root_lot_id, lot_type}. ID 를 파싱하지 않고 yield 테이블에서 읽는다."""
    if not wafer_ids:
        return {}
    ph = ",".join("?" * len(wafer_ids))
    rows = conn.execute(
        f"SELECT wafer_id, root_lot_id, lot_type FROM yield WHERE wafer_id IN ({ph})",
        wafer_ids,
    ).fetchall()
    return {r["wafer_id"]: {"root_lot_id": r["root_lot_id"], "lot_type": r["lot_type"]}
            for r in rows}
 
 
def _legend_columns(legend) -> list[str]:
    """legend 전 레벨의 컬럼 순서 있는 합집합."""
    cols = []
    for lvl in legend:
        for col in lvl["columns"]:
            if col not in cols:
                cols.append(col)
    return cols


def _history(conn, wafer_ids: list[str], legend) -> list[sqlite3.Row]:
    if not wafer_ids:
        return []
    table_cols = {r["name"] for r in conn.execute("PRAGMA table_info(step_history)")}
    need = _legend_columns(legend)
    missing = [c for c in need if c not in table_cols]
    if missing:
        raise ValueError(f"legend 컬럼 {missing} 이 step_history 에 없음. "
                         f"가능한 컬럼: {', '.join(sorted(table_cols))}")
    sel = ", ".join(["wafer_id", "step_seq", "timestamp", *need])
    ph = ",".join("?" * len(wafer_ids))
    return conn.execute(
        f"SELECT {sel} FROM step_history WHERE wafer_id IN ({ph})", wafer_ids
    ).fetchall()


def _keys(row, legend) -> list[tuple]:
    """한 이력 행이 기여하는 후보 키들. 각 항목 = (level, step, keystr, colvals).

    레벨 컬럼이 하나라도 NULL/빈문자열/MISSING_TOKENS 면 그 레벨은 건너뛴다(가짜 키
    금지 — ch_id 없는 단일 챔버 설비/챔버 개념 없는 스텝의 챔버 레벨이 자연히 빠진다).
    """
    step = row["step_seq"]
    out = []
    for lvl in legend:
        vals = [row[col] for col in lvl["columns"]]
        if any(v is None or str(v).strip() == "" or str(v).strip() in MISSING_TOKENS
               for v in vals):
            continue
        keystr = "_".join(str(v) for v in vals)
        colvals = dict(zip(lvl["columns"], vals))
        out.append((lvl["level"], step, keystr, colvals))
    return out


def _count_stratum(rows, wafers: set[str], legend) -> tuple[dict, dict, set, dict]:
    """stratum 내 집계.

    passed  후보키 -> 그 키를 거친 wafer 집합
    answer  (레벨, 스텝) -> **그 질문에 답할 수 있는** wafer 집합 = 분모
    seen    이력이 하나라도 있는 wafer (missing_history 보고용)
    colmap  후보키 -> legend 컬럼값

    answer 를 따로 세는 이유: `_keys` 가 결측 레벨을 이미 건너뛰므로, 거기서 나온
    (레벨, 스텝) 이 곧 "이 wafer 는 그 질문에 답할 수 있다" 는 뜻이다. seen 을
    분모로 쓰면 그 스텝을 안 지난 wafer 와 컬럼이 결측인 wafer 가 '미통과' 로 섞인다.
    """
    passed: dict[tuple, set] = {}
    answer: dict[tuple, set] = {}
    seen: set[str] = set()
    colmap: dict[tuple, dict] = {}
    for r in rows:
        wid = r["wafer_id"]
        if wid not in wafers:
            continue
        seen.add(wid)
        for level, step, keystr, colvals in _keys(r, legend):
            answer.setdefault((level, step), set()).add(wid)
            key = (level, step, keystr)
            passed.setdefault(key, set()).add(wid)
            colmap.setdefault(key, colvals)
    return passed, answer, seen, colmap
 
 
def find_commonality(target_wafers: list[str], control_wafers: list[str],
                     legend: list[dict] | None = None,
                     top_k: int | None = None) -> dict:
    """타깃 그룹이 공유하는데 대조군은 거치지 않은 (스텝, 설비/챔버) 후보를 찾는다.
 
    반환 status:
      - "insufficient_group": 타깃이 너무 적어 commonality 가 정의상 무의미
      - "no_paired_stratum" : 타깃과 대조군이 같은 root_lot 에서 짝지어지지 않음
      - "no_signal"         : 계산은 됐으나 분리되는 후보가 없음
                              → 원인 없음이 아니라 **lot 내부 대조로는 안 보임**.
                                원인이 root_lot 전체에 걸리면 타깃·대조군이 같은 챔버를
                                거치므로 score 가 전부 0 이 된다. lot 밖 대조군이 필요하다는
                                신호이며, 향후 대조군 확장(b/c 방식)의 트리거다.
      - "ok"
    """
    legend = EQP_CH_LEGEND if legend is None else legend
    top_k = TOP_K if top_k is None else top_k
    targets = sorted(set(target_wafers or []))
    controls = sorted(set(control_wafers or []) - set(targets))
 
    if len(targets) < MIN_TARGET:
        return {
            "status": "insufficient_group",
            "n_target": len(targets), "n_control": len(controls),
            "candidates": [],
            "note": (f"타깃 {len(targets)}장 < 최소 {MIN_TARGET}장. "
                     f"단일 wafer 는 정의상 모든 경로가 '공통'이라 분석 불가 - "
                     f"EDS 유사 wafer 로 타깃을 확장해야 한다."),
        }
 
    with _conn() as conn:
        meta = _wafer_meta(conn, targets + controls)
        t_rows = _history(conn, targets, legend)
        c_rows = _history(conn, controls, legend)
 
    # ---- root_lot 별 층화 (대조군이 타깃과 같은 route/시기에서 나오도록) ----
    strata: dict[str, dict] = {}
    for wid in targets:
        rl = meta.get(wid, {}).get("root_lot_id")
        strata.setdefault(rl, {"target": set(), "control": set()})["target"].add(wid)
    for wid in controls:
        rl = meta.get(wid, {}).get("root_lot_id")
        if rl in strata:                      # 짝 없는 대조군 root_lot 은 버린다
            strata[rl]["control"].add(wid)
 
    paired = {rl: s for rl, s in strata.items() if s["target"] and s["control"]}
    if not paired:
        return {
            "status": "no_paired_stratum",
            "n_target": len(targets), "n_control": len(controls),
            "candidates": [],
            "note": ("타깃과 같은 root_lot 에 속한 대조군 wafer 가 없다. "
                     "route/시간 교락 없이 비교할 짝이 없어 계산을 중단했다."),
        }
 
    # ---- stratum 별 2x2 집계 후 카운트 합산 ----
    # denominator: all 인 레벨은 모든 wafer 가 답할 수 있다 (step_passage).
    universal = {lvl["level"] for lvl in legend if lvl.get("denominator") == "all"}
    agg: dict[tuple, dict] = {}
    colmap_all: dict[tuple, dict] = {}
    strata_report, missing = [], []
    t_seen_all, c_seen_all = set(), set()

    for rl, s in sorted(paired.items(), key=lambda kv: (kv[0] is None, kv[0])):
        t_passed, t_answer, t_seen, t_colmap = _count_stratum(t_rows, s["target"], legend)
        c_passed, c_answer, c_seen, c_colmap = _count_stratum(c_rows, s["control"], legend)
        colmap_all.update(t_colmap)
        colmap_all.update(c_colmap)
        t_seen_all |= t_seen
        c_seen_all |= c_seen
        missing += sorted((s["target"] | s["control"]) - t_seen - c_seen)

        # 이력이 아예 없는 쪽이 있으면 이 stratum 은 비교가 성립하지 않는다
        if not t_seen or not c_seen:
            continue
        strata_report.append({"root_lot_id": rl,
                              "n_target": len(t_seen), "n_control": len(c_seen)})

        for key in set(t_passed) | set(c_passed):
            level, step, _keystr = key
            if level in universal:
                nt, nc = len(t_seen), len(c_seen)
            else:
                nt = len(t_answer.get((level, step), ()))
                nc = len(c_answer.get((level, step), ()))
            # 한쪽이 그 질문에 아무도 답하지 못하면 대비할 짝이 없다.
            # (예: 대조군이 그 스텝에 아예 안 갔다 → step_passage 축이 잡을 일이다)
            if nt == 0 or nc == 0:
                continue
            e = agg.setdefault(key, {"a": 0, "b": 0, "c": 0, "d": 0, "strata": 0})
            a = len(t_passed.get(key, ()))
            c_ = len(c_passed.get(key, ()))
            e["a"] += a
            e["b"] += nt - a
            e["c"] += c_
            e["d"] += nc - c_
            e["strata"] += 1
 
    if not strata_report:
        return {
            "status": "no_paired_stratum",
            "n_target": len(targets), "n_control": len(controls),
            "candidates": [], "missing_history": sorted(set(missing)),
            "note": "step_history 가 있는 타깃/대조군 짝이 없다 (이력 결측 확인 필요).",
        }
 
    # ---- score 계산 + 절단 ----
    all_cols = _legend_columns(legend)
    candidates = []
    for (level, step, keystr), e in agg.items():
        nt_tot, nc_tot = e["a"] + e["b"], e["c"] + e["d"]
        if nt_tot == 0 or nc_tot == 0:
            continue
        cov_t = e["a"] / nt_tot
        cov_c = e["c"] / nc_tot
        score = cov_t - cov_c
        if score <= MIN_SCORE:
            continue
        colvals = colmap_all.get((level, step, keystr), {})
        cand = {
            "level": level,
            "step_seq": step,
            "key": keystr,
            # 원시 카운트 — score 만 보면 6/6 과 2/2 를 구분할 수 없다
            "target_pass": e["a"], "target_total": nt_tot,
            "control_pass": e["c"], "control_total": nc_tot,
            "coverage_target": round(cov_t, 3),
            "coverage_control": round(cov_c, 3),
            "score": round(score, 3),
            "n_strata": e["strata"],
        }
        for col in all_cols:               # legend 컬럼값을 이름별로 (미해당은 None)
            cand[col] = colvals.get(col)
        candidates.append(cand)
 
    candidates.sort(key=lambda r: (-r["score"], -r["coverage_target"],
                                   -r["target_pass"], r["step_seq"], r["key"]))
    truncated = max(0, len(candidates) - top_k)
    candidates = candidates[:top_k]
 
    def _ts(rows, wafers):
        vals = [r["timestamp"] for r in rows
                if r["wafer_id"] in wafers and r["timestamp"] is not None]
        return {"min": min(vals), "max": max(vals)} if vals else None
 
    def _lt(wafers):
        dist: dict[str, int] = {}
        for w in wafers:
            lt = meta.get(w, {}).get("lot_type") or "unknown"
            dist[lt] = dist.get(lt, 0) + 1
        return dist
 
    result = {
        "status": "ok" if candidates else "no_signal",
        "n_target": len(t_seen_all), "n_control": len(c_seen_all),
        "strata": strata_report,
        "candidates": candidates,
        "truncated": truncated,
        "meta": {
            # 시간 교락 진단용 — 두 그룹의 처리 시기가 어긋나면 '공통 설비'가 허상일 수 있다
            "target_time_range": _ts(t_rows, t_seen_all),
            "control_time_range": _ts(c_rows, c_seen_all),
            # 평가랏에는 설비 작업 후 검증랏이 섞인다 — 배제하지 않고 해석 재료로 넘긴다
            "target_lot_types": _lt(t_seen_all),
            "control_lot_types": _lt(c_seen_all),
            "missing_history": sorted(set(missing)),
        },
        "note": ("후보는 결론이 아니다. 표본이 작아 우연한 분리가 흔하므로 "
                 "원시 카운트(target_pass/target_total)를 반드시 함께 판단하고, "
                 "지목된 스텝의 센서 비교로 검증해야 한다."),
    }
    if not candidates:
        result["note"] = (
            "타깃만 거친 설비/챔버가 없다. **원인 없음이 아니라 lot 내부 대조로는 "
            "보이지 않는다는 뜻**이다 - 원인이 root_lot 전체에 걸리면 타깃과 대조군이 "
            "같은 경로를 거치므로 분리가 나타나지 않는다. lot 밖 대조군이 필요하다.")
    return result