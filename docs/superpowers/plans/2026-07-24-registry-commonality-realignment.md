# 레지스트리 ↔ commonality 재정렬 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 인과가설 레지스트리를 사내 확정 스키마(step_history) 위의 commonality 엔진에 재정렬한다 — commonality 를 임의 legend(EQP_CH·PPID…)로 일반화하고, engine 을 그 위의 legend 어댑터로 재편한다.

**Architecture:** commonality 가 고정된 "2×2 coverage-diff + root_lot 층화" 엔진을 legend 파라미터로 제공하고, hypotheses.yaml 이 "어느 legend 로 돌릴지"를 선언한다. engine.evaluate 가 commonality 후보를 게이트 계약(passes/value)으로 매핑하고, 게이트(nodes.py)는 무수정으로 유지된다. process_log·레거시 도구·defect_type 그룹핑은 별도 워크스트림으로 손대지 않는다(좁게/surgical).

**Tech Stack:** Python 3, sqlite3, pytest, PyYAML, langchain_core.

## Global Constraints

- `data/load_internal.py` 는 **수정 금지** (source of truth).
- `tools/commonality.py` 는 프리즈 해제하되 **행동보존** — `tests/test_commonality.py` 기존 케이스가 legend 인자 없이 호출되어 그대로 green 이어야 한다.
- Out of scope (손대지 않음): `tools/yield_tools.py` 레거시 도구, `find_normal_wafers` 대조군(B-3), `status_node`·defect_type→EDS 그룹핑(A-3), sensor_log 2단. dummy 의 `process_log` 는 유지.
- commonality 후보 dict 은 `key = "_".join(레벨 컬럼값)` 규칙. 레벨 컬럼이 하나라도 NULL/빈문자열이면 그 레벨 후보를 만들지 않는다(가짜 키 금지).
- 커밋 메시지 말미에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: commonality.py 를 legend 로 일반화 (행동보존)

**Files:**
- Modify: `tools/commonality.py` (`_history`, `_keys`, `_count_stratum`, `find_commonality`)
- Test: `tests/test_commonality.py` (기존 유지 + legend 케이스 추가)

**Interfaces:**
- Produces:
  - `EQP_CH_LEGEND: list[dict]` — `[{"level":"equipment","columns":["eqp_id"]}, {"level":"chamber","columns":["eqp_id","ch_id"]}]`
  - `find_commonality(target_wafers: list[str], control_wafers: list[str], legend: list[dict] | None = None, top_k: int | None = None) -> dict`
    — `legend=None` 이면 `EQP_CH_LEGEND` (현재 동작과 동일). 후보 dict 은 legend 각 컬럼값을 이름별 필드로 싣는다(EQP_CH → `eqp_id`,`ch_id`; PPID → `ppid`), 미해당 컬럼은 `None`.

- [ ] **Step 1: legend 일반화용 실패 테스트 추가**

`tests/test_commonality.py` 끝에 추가. `_make_db` 는 step_history 에 ppid 컬럼이 없으므로, ppid 를 쓰는 legend 테스트용 헬퍼를 함께 추가한다.

```python
# ------------------------------------------------------------------ legend 일반화

PPID_LEGEND = [{"level": "ppid", "columns": ["ppid"]}]


def _make_db_ppid(tmp_path, monkeypatch, yield_rows, history_rows):
    """step_history 에 ppid 컬럼을 포함한 픽스처. history_rows = (wid, step, eqp, ch, ppid, ts)."""
    import sqlite3
    db = tmp_path / "test_ppid.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE yield (
        wafer_id TEXT PRIMARY KEY, lot_id TEXT NOT NULL, yield REAL NOT NULL,
        defect_type TEXT NOT NULL, process_step TEXT, date TEXT NOT NULL,
        root_lot_id TEXT NOT NULL, lot_type TEXT NOT NULL)""")
    conn.executemany("INSERT INTO yield VALUES (?,?,?,?,?,?,?,?)", yield_rows)
    conn.execute("""CREATE TABLE step_history (
        wafer_id TEXT NOT NULL, process_step TEXT NOT NULL, eqp_id TEXT NOT NULL,
        ch_id TEXT, ppid TEXT, timestamp TEXT)""")
    conn.executemany("INSERT INTO step_history VALUES (?,?,?,?,?,?)", history_rows)
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)


def test_ppid_legend_finds_group_exclusive_ppid(tmp_path, monkeypatch):
    """PPID legend: 타깃 전원이 같은 PPID 를 거치고 대조군은 아닌 경우."""
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [(w, "Etch", "ETCH9", "3", "PPID_X", "2026-06-17 10:00:00") for w in t]
    hs += [(w, "Etch", "ETCH8", "1", "PPID_Y", "2026-06-17 10:00:00") for w in c]
    _make_db_ppid(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c, legend=PPID_LEGEND)
    assert res["status"] == "ok"
    assert _keys(res) == {("ppid", "PPID_X")}
    cand = _find(res, "ppid", "PPID_X")
    assert cand["ppid"] == "PPID_X"
    assert (cand["target_pass"], cand["control_pass"]) == (2, 0)


def test_default_legend_matches_eqp_ch(tmp_path, monkeypatch):
    """legend 인자 없이 호출하면 EQP_CH 동작과 동일 (행동보존)."""
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    default = cm.find_commonality(t, c)
    explicit = cm.find_commonality(t, c, legend=cm.EQP_CH_LEGEND)
    assert _keys(default) == _keys(explicit) == {("equipment", "ETCH9"), ("chamber", "ETCH9_3")}


def test_unknown_legend_column_raises(tmp_path, monkeypatch):
    """legend 가 step_history 에 없는 컬럼을 요구하면 명시적 에러."""
    import pytest
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t + c]
    _make_db(tmp_path, monkeypatch, ys, hs)
    with pytest.raises(ValueError, match="bogus"):
        cm.find_commonality(t, c, legend=[{"level": "x", "columns": ["bogus"]}])
```

- [ ] **Step 2: 새 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_commonality.py -k "ppid_legend or default_legend or unknown_legend" -v`
Expected: FAIL — `find_commonality()` 에 `legend` 인자 없음 / `EQP_CH_LEGEND` 없음.

- [ ] **Step 3: commonality.py 일반화 구현**

`tools/commonality.py` 를 아래로 교체(핵심 함수만 — 나머지 층화·score·meta 로직은 불변).

먼저 상수 추가(파일 상단 `MIN_SCORE` 정의 아래):

```python
# 기본 legend — EQP_CH (legend 인자 없으면 이 동작). 레벨 순서 = 롤업(설비) → 세부(챔버).
EQP_CH_LEGEND = [
    {"level": "equipment", "columns": ["eqp_id"]},
    {"level": "chamber", "columns": ["eqp_id", "ch_id"]},
]
```

`_history` 를 legend 컬럼 기반으로 교체:

```python
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
    sel = ", ".join(["wafer_id", "process_step", "timestamp", *need])
    ph = ",".join("?" * len(wafer_ids))
    return conn.execute(
        f"SELECT {sel} FROM step_history WHERE wafer_id IN ({ph})", wafer_ids
    ).fetchall()
```

`_keys` 를 legend 기반으로 교체 — 반환 항목에 컬럼값 매핑을 함께 싣는다:

```python
def _keys(row, legend) -> list[tuple]:
    """한 이력 행이 기여하는 후보 키들. 각 항목 = (level, step, keystr, colvals).

    레벨 컬럼이 하나라도 NULL/빈문자열이면 그 레벨은 건너뛴다(가짜 키 금지 —
    ch_id 없는 단일 챔버 설비/챔버 개념 없는 스텝의 챔버 레벨이 자연히 빠진다).
    """
    step = row["process_step"]
    out = []
    for lvl in legend:
        vals = [row[col] for col in lvl["columns"]]
        if any(v is None or str(v).strip() == "" for v in vals):
            continue
        keystr = "_".join(str(v) for v in vals)
        colvals = dict(zip(lvl["columns"], vals))
        out.append((lvl["level"], step, keystr, colvals))
    return out
```

`_count_stratum` 를 새 키 구조(3-튜플 + colvals)로 교체:

```python
def _count_stratum(rows, wafers: set[str], legend) -> tuple[dict, set, dict]:
    """stratum 내 후보키 -> 그 키를 거친 wafer 집합, 이력 존재 wafer, 키->colvals."""
    passed: dict[tuple, set] = {}
    seen: set[str] = set()
    colmap: dict[tuple, dict] = {}
    for r in rows:
        wid = r["wafer_id"]
        if wid not in wafers:
            continue
        seen.add(wid)
        for level, step, keystr, colvals in _keys(r, legend):
            key = (level, step, keystr)
            passed.setdefault(key, set()).add(wid)
            colmap.setdefault(key, colvals)
    return passed, seen, colmap
```

`find_commonality` 시그니처·호출부·후보 빌드 교체(변경 지점만):

```python
def find_commonality(target_wafers: list[str], control_wafers: list[str],
                     legend: list[dict] | None = None,
                     top_k: int | None = None) -> dict:
    legend = EQP_CH_LEGEND if legend is None else legend
    top_k = TOP_K if top_k is None else top_k
    targets = sorted(set(target_wafers or []))
    controls = sorted(set(control_wafers or []) - set(targets))
    # ... (insufficient_group / no_paired_stratum 분기 불변) ...
    with _conn() as conn:
        meta = _wafer_meta(conn, targets + controls)
        t_rows = _history(conn, targets, legend)
        c_rows = _history(conn, controls, legend)
    # ... (strata 층화 불변) ...
    # stratum 집계 루프에서 _count_stratum 호출을 legend 인자 포함으로:
    #   t_passed, t_seen, t_colmap = _count_stratum(t_rows, s["target"], legend)
    #   c_passed, c_seen, c_colmap = _count_stratum(c_rows, s["control"], legend)
    # colmap 병합: colmap_all.update(t_colmap); colmap_all.update(c_colmap)
    # agg 키는 이제 (level, step, keystr) 3-튜플.
    # 후보 빌드:
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
            "process_step": step,
            "key": keystr,
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
                                   -r["target_pass"], r["process_step"], r["key"]))
    # ... (truncate / meta / note 불변) ...
```

구현 시 주의: 기존 코드의 `agg` 집계 루프에서 `for key in set(t_passed) | set(c_passed):` 의 `key` 는 이제 (level, step, keystr) 3-튜플이다. `colmap_all: dict = {}` 를 stratum 루프 앞에 만들고 각 stratum 의 `t_colmap`/`c_colmap` 을 병합한다.

- [ ] **Step 4: 전체 commonality 테스트 통과 확인 (행동보존 + 신규)**

Run: `python -m pytest tests/test_commonality.py -v`
Expected: PASS — 기존 14케이스 + 신규 3케이스 전부 green.

- [ ] **Step 5: 커밋**

```bash
git add tools/commonality.py tests/test_commonality.py
git commit -m "feat(commonality): legend 파라미터로 임의 축 일반화 (행동보존)

_keys/_history/_count_stratum 을 legend(레벨=컬럼묶음) 기반으로 재작성.
legend 기본값 EQP_CH_LEGEND 로 기존 동작 바이트 보존, PPID 등 새 축 지원.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: engine.py 를 legend 어댑터로 재편

**Files:**
- Modify: `domain/engine.py` (전면 교체 — 비교타입 제거, `evaluate` 신설)
- Modify: `config.py` (판별 임계 상수 2개 추가)
- Test: `tests/test_engine.py` (전면 재작성)

**Interfaces:**
- Consumes: `commonality.find_commonality(target, control, legend, top_k)` (Task 1)
- Produces:
  - `evaluate(spec: dict, group_ids: list[str], control_ids: list[str]) -> dict`
    — 반환 `{"hypothesis_id", "legend", "status", "candidates", "meta", "note"}`.
      각 candidate: `{"value": [process_step, key], "passes": bool, "level", "key",
      "process_step", "score", "target_pass", "target_total", "control_pass",
      "control_total", "coverage_target", "coverage_control", "reject_reason"}`.

- [ ] **Step 1: config 판별 임계 상수 추가**

`config.py` 의 `CONFIDENCE_THRESHOLD` 줄 아래에 추가:

```python
# commonality 후보의 '판별 통과(passes)' 기준 — 게이트 증거로 쓸 최소 신뢰선.
# 후보≠결론 철학상 못 박지 않고 실데이터 보며 조정한다.
COMMONALITY_PASS_MIN_SCORE = float(os.getenv("COMMONALITY_PASS_MIN_SCORE", "0.5"))
COMMONALITY_PASS_MIN_TARGET = int(os.getenv("COMMONALITY_PASS_MIN_TARGET", "2"))
```

- [ ] **Step 2: engine 어댑터 실패 테스트 작성 (test_engine.py 전면 교체)**

`tests/test_engine.py` 전체를 아래로 교체(step_history 픽스처 기반):

```python
"""engine.evaluate — commonality legend 어댑터. 게이트 계약(passes/value) 매핑 검증."""

import sqlite3
import pytest

import config
from domain import engine

EQP_CH = [{"level": "equipment", "columns": ["eqp_id"]},
          {"level": "chamber", "columns": ["eqp_id", "ch_id"]}]
PPID = [{"level": "ppid", "columns": ["ppid"]}]


@pytest.fixture
def fx_db(tmp_path, monkeypatch):
    """step_history 픽스처. 불량군 3장 전원 Etch=ETCH9_B(+PPID_X), 대조군은 ETCH8/PPID_Y.
    Photo 는 양쪽 공유(미끼)."""
    db = tmp_path / "fx.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE yield (wafer_id TEXT PRIMARY KEY, lot_id TEXT, yield REAL,
        defect_type TEXT, process_step TEXT, date TEXT, root_lot_id TEXT, lot_type TEXT)""")
    conn.execute("""CREATE TABLE step_history (wafer_id TEXT, process_step TEXT, eqp_id TEXT,
        ch_id TEXT, ppid TEXT, timestamp TEXT)""")
    group, control = ["G1", "G2", "G3"], ["C1", "C2", "C3"]
    for w in group:
        conn.execute("INSERT INTO yield VALUES (?,?,?,?,?,?,?,?)",
                     (w, "L.1", 80.0, "none", None, "d", "R1", "prod"))
        conn.execute("INSERT INTO step_history VALUES (?,?,?,?,?,?)",
                     (w, "Etch", "ETCH9", "B", "PPID_X", "t"))
        conn.execute("INSERT INTO step_history VALUES (?,?,?,?,?,?)",
                     (w, "Photo", "PHOTO1", "A", "PPID_Z", "t"))
    for i, w in enumerate(control):
        conn.execute("INSERT INTO yield VALUES (?,?,?,?,?,?,?,?)",
                     (w, "L.1", 95.0, "none", None, "d", "R1", "prod"))
        conn.execute("INSERT INTO step_history VALUES (?,?,?,?,?,?)",
                     (w, "Etch", "ETCH8", str(i), "PPID_Y", "t"))
        conn.execute("INSERT INTO step_history VALUES (?,?,?,?,?,?)",
                     (w, "Photo", "PHOTO1", "A", "PPID_Z", "t"))
    conn.commit(); conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)
    return db


def test_evaluate_maps_chamber_to_gate_contract(fx_db):
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    assert res["hypothesis_id"] == "eqp_ch"
    assert res["status"] == "ok"
    by_key = {c["key"]: c for c in res["candidates"]}
    ch = by_key["ETCH9_B"]
    assert ch["value"] == ["Etch", "ETCH9_B"]        # 게이트 토큰 = value[-1]
    assert ch["passes"] is True
    assert (ch["target_pass"], ch["control_pass"]) == (3, 0)
    # 미끼 Photo(PHOTO1_A)는 양쪽 공유 → score 0 → 후보에서 탈락(애초에 안 실림)
    assert "PHOTO1_A" not in by_key


def test_evaluate_ppid_legend(fx_db):
    res = engine.evaluate({"id": "ppid", "legend": PPID}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    by_key = {c["key"]: c for c in res["candidates"]}
    assert by_key["PPID_X"]["passes"] is True
    assert by_key["PPID_X"]["value"] == ["Etch", "PPID_X"]


def test_evaluate_passes_false_below_threshold(fx_db, monkeypatch):
    # 임계를 1.0 초과로 올리면 score 1.0 후보도 passes=False
    monkeypatch.setattr(config, "COMMONALITY_PASS_MIN_SCORE", 1.5)
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    assert all(not c["passes"] for c in res["candidates"])


def test_evaluate_no_signal_status(fx_db, monkeypatch):
    # 대조군도 ETCH9_B 를 거치면 분리 없음 → no_signal, 후보 빈 리스트
    conn = sqlite3.connect(fx_db)
    conn.execute("UPDATE step_history SET eqp_id='ETCH9', ch_id='B' WHERE process_step='Etch'")
    conn.commit(); conn.close()
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    assert res["status"] == "no_signal"
    assert res["candidates"] == []
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `python -m pytest tests/test_engine.py -v`
Expected: FAIL — `engine.evaluate` 새 시그니처/필드 없음, 옛 비교타입 참조 제거 전.

- [ ] **Step 4: engine.py 전면 교체**

`domain/engine.py` 전체를 아래로 교체:

```python
"""legend 어댑터 — commonality 후보를 게이트 계약(passes/value)으로 매핑한다.

commonality 는 판정하지 않는다(후보≠결론). 판별(passes)은 게이트가 suspect 를
모으기 위한 최소 신뢰선일 뿐이며, 반례 판별은 commonality 의 2×2(대조군 카운트)에
이미 내장돼 있다(c = 원인 거쳤는데 정상). 임계는 config 상수(실데이터 보며 조정).
"""

import config
from tools import commonality as cm


def _passes(cand, min_score, min_target):
    reasons = []
    if cand["score"] < min_score:
        reasons.append(f"분리 점수 {cand['score']} < {min_score}")
    if cand["target_pass"] < min_target:
        reasons.append(f"타깃 표본 {cand['target_pass']} < {min_target}")
    return (not reasons), ("; ".join(reasons) or None)


def evaluate(spec: dict, group_ids: list[str], control_ids: list[str]) -> dict:
    """spec['legend'] 로 commonality 실행 후 각 후보를 게이트 계약으로 매핑."""
    min_score = spec.get("min_score", config.COMMONALITY_PASS_MIN_SCORE)
    min_target = spec.get("min_target", config.COMMONALITY_PASS_MIN_TARGET)
    res = cm.find_commonality(group_ids, control_ids, legend=spec["legend"])

    candidates = []
    for cand in res.get("candidates", []):
        passes, reject = _passes(cand, min_score, min_target)
        candidates.append({
            "value": [cand["process_step"], cand["key"]],
            "passes": passes,
            "reject_reason": reject,
            "level": cand["level"],
            "key": cand["key"],
            "process_step": cand["process_step"],
            "score": cand["score"],
            "target_pass": cand["target_pass"], "target_total": cand["target_total"],
            "control_pass": cand["control_pass"], "control_total": cand["control_total"],
            "coverage_target": cand["coverage_target"],
            "coverage_control": cand["coverage_control"],
        })
    return {
        "hypothesis_id": spec["id"],
        "legend": spec["legend"],
        "status": res.get("status"),
        "candidates": candidates,
        "meta": res.get("meta"),
        "note": res.get("note"),
    }
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/test_engine.py -v`
Expected: PASS — 4케이스 green.

- [ ] **Step 6: 커밋**

```bash
git add domain/engine.py config.py tests/test_engine.py
git commit -m "feat(engine): 비교타입 → commonality legend 어댑터로 재편

group_only_categorical/categorical_concentration/numeric_distribution_shift 및
defect_type 기반 _counterexamples 제거. evaluate 가 commonality 후보를
게이트 계약(passes/value)으로 매핑. 판별 임계는 config 상수.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: hypotheses.yaml + registry.py 를 legend 스키마로

**Files:**
- Modify: `domain/hypotheses.yaml` (전면 교체)
- Modify: `domain/registry.py` (`REQUIRED_FIELDS`, `load_hypotheses` 검증)
- Test: `tests/test_registry.py` (legend 스키마로 재작성)

**Interfaces:**
- Consumes: `engine.evaluate(spec, group_ids, control_ids)` (Task 2)
- Produces: `load_hypotheses(path=None) -> list[dict]` (legend 검증), `build_tools(specs) -> list[StructuredTool]` (이름 `hyp_<id>`).

- [ ] **Step 1: registry 테스트 재작성 (실패)**

`tests/test_registry.py` 전체를 아래로 교체:

```python
"""레지스트리 로더·도구 생성 — legend 스키마."""

import pytest
import yaml
from domain import registry

VALID = [{"id": "eqp_ch_commonality", "name": "설비/챔버 공통성",
          "description": "타깃만 거친 (스텝, 설비/챔버)를 찾는다",
          "legend": [{"level": "equipment", "columns": ["eqp_id"]},
                     {"level": "chamber", "columns": ["eqp_id", "ch_id"]}]}]


def test_load_valid_yaml(tmp_path):
    p = tmp_path / "h.yaml"
    p.write_text(yaml.safe_dump(VALID, allow_unicode=True), encoding="utf-8")
    specs = registry.load_hypotheses(p)
    assert specs[0]["id"] == "eqp_ch_commonality"
    assert specs[0]["legend"][0]["level"] == "equipment"


def test_reject_missing_field(tmp_path):
    bad = [{"id": "x", "name": "n", "description": "d"}]  # legend 없음
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="legend"):
        registry.load_hypotheses(p)


def test_reject_malformed_legend(tmp_path):
    bad = [{"id": "x", "name": "n", "description": "d",
            "legend": [{"level": "eq"}]}]  # columns 없음
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="columns"):
        registry.load_hypotheses(p)


def test_build_tools_produces_named_callables():
    tools = registry.build_tools(VALID)
    assert tools[0].name == "hyp_eqp_ch_commonality"
    assert "설비" in tools[0].description


def test_real_yaml_loads_and_builds():
    """저장소의 실제 hypotheses.yaml 이 로드·빌드된다."""
    specs = registry.load_hypotheses()
    ids = {s["id"] for s in specs}
    assert "eqp_ch_commonality" in ids and "ppid_commonality" in ids
    assert {t.name for t in registry.build_tools(specs)} == {f"hyp_{i}" for i in ids}
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_registry.py -v`
Expected: FAIL — `REQUIRED_FIELDS` 가 아직 comparison/column 요구, legend 검증 없음.

- [ ] **Step 3: registry.py 검증 교체**

`domain/registry.py` 의 `REQUIRED_FIELDS` 와 `load_hypotheses` 를 교체:

```python
REQUIRED_FIELDS = ("id", "name", "description", "legend")


def load_hypotheses(path=None):
    path = Path(path) if path else DEFAULT_PATH
    specs = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(specs, list):
        raise ValueError(f"{path}: 최상위가 가설 리스트가 아니다")
    for i, s in enumerate(specs):
        for f in REQUIRED_FIELDS:
            if f not in s:
                raise ValueError(f"가설 #{i}: 필수 필드 '{f}' 누락")
        legend = s["legend"]
        if not isinstance(legend, list) or not legend:
            raise ValueError(f"가설 '{s['id']}': legend 는 비어있지 않은 리스트여야 한다")
        for lvl in legend:
            if not isinstance(lvl, dict) or "level" not in lvl or "columns" not in lvl:
                raise ValueError(f"가설 '{s['id']}': 각 legend 레벨은 level·columns 를 가져야 한다")
            if not isinstance(lvl["columns"], list) or not lvl["columns"]:
                raise ValueError(f"가설 '{s['id']}': legend 레벨 columns 는 비어있지 않은 리스트")
    return specs
```

`domain/registry.py` 최상단 import 에서 `from domain import engine` 는 그대로 두고, `build_tools` 는 변경 불필요(이미 `engine.evaluate(_spec, group_ids, control_ids)` 를 호출한다면). 현행 `build_tools` 가 `engine.evaluate(_spec, group_ids, control_ids)` 를 호출하는지 확인하고, 아니면 아래로 맞춘다:

```python
def build_tools(specs):
    tools = []
    for spec in specs:
        def _run(group_ids, control_ids, reason="", _spec=spec):
            return engine.evaluate(_spec, group_ids, control_ids)
        tools.append(StructuredTool.from_function(
            func=_run, name=f"hyp_{spec['id']}",
            description=(spec["description"].strip() +
                         "\nreason: 이 가설을 확인하는 판단 이유를 한 문장으로 기술한다 (감사 기록)."),
        ))
    return tools
```

- [ ] **Step 4: hypotheses.yaml 교체**

`domain/hypotheses.yaml` 전체를 아래로 교체:

```yaml
- id: eqp_ch_commonality
  name: 설비/챔버 공통성
  description: |
    타깃 전원이 거쳤고 대조군은 안 거친 (공정 스텝, 설비/챔버)를 찾는다.
    1차 legend — 엔지니어가 가장 먼저 돌리는 주 분석. 설비 롤업과 챔버 세부를 함께 낸다.
  legend:
    - {level: equipment, columns: [eqp_id]}
    - {level: chamber, columns: [eqp_id, ch_id]}

- id: ppid_commonality
  name: PPID 공통성
  description: |
    EQP_CH 로 타깃/대조군이 안 갈릴 때, 타깃만 거친 (공정 스텝, PPID)를 찾는다.
    2차 legend — 불량 형태에 따라 선택.
  legend:
    - {level: ppid, columns: [ppid]}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/test_registry.py -v`
Expected: PASS — 5케이스 green.

- [ ] **Step 6: 커밋**

```bash
git add domain/registry.py domain/hypotheses.yaml tests/test_registry.py
git commit -m "feat(registry): legend 스키마 — YAML 로 commonality 축 저작

comparison/column → legend(레벨=컬럼묶음). EQP_CH·PPID 가설 선언.
load_hypotheses 가 legend 구조를 검증.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: generate_dummy.py 에 step_history + yield 스키마 정합

**Files:**
- Modify: `data/generate_dummy.py` (yield 스키마 +2컬럼, step_history 신설)
- Test: `tests/test_dummy_data.py` (step_history·신컬럼 단언 추가)
- Regenerate: `data/yield.db`

**Interfaces:**
- Produces: `data/yield.db` 에 `yield(…, root_lot_id, lot_type)` + `step_history(wafer_id, process_step, eqp_id, ch_id, ppid, timestamp)`. 타깃 `W2406_02/04/06` 이 Etch 에서 `ETCH9_B`·`PPID_X` 를 공유하고 대조군 `W2406_01/03/05` 은 아님.

- [ ] **Step 1: dummy 데이터 실패 테스트 추가**

`tests/test_dummy_data.py` 끝에 추가:

```python
def test_yield_has_root_lot_and_lot_type():
    import sqlite3, config
    conn = sqlite3.connect(config.DB_PATH); conn.row_factory = sqlite3.Row
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(yield)")}
    assert {"root_lot_id", "lot_type"} <= cols
    # RECENT_LOT 타깃·대조군이 같은 root_lot 을 공유(commonality 층화 성립)
    rows = conn.execute(
        "SELECT DISTINCT root_lot_id FROM yield WHERE wafer_id IN "
        "('W2406_02','W2406_04','W2406_06','W2406_01','W2406_03','W2406_05')").fetchall()
    conn.close()
    assert len(rows) == 1


def test_step_history_planted_eqp_ch_and_ppid_separation():
    import config
    from tools import commonality as cm
    t = ["W2406_02", "W2406_04", "W2406_06"]
    c = ["W2406_01", "W2406_03", "W2406_05"]
    res = cm.find_commonality(t, c)               # 기본 EQP_CH legend
    keys = {(x["level"], x["key"]) for x in res["candidates"]}
    assert ("chamber", "ETCH9_B") in keys
    ppid = cm.find_commonality(t, c, legend=[{"level": "ppid", "columns": ["ppid"]}])
    assert ("ppid", "PPID_X") in {(x["level"], x["key"]) for x in ppid["candidates"]}
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_dummy_data.py -k "root_lot or planted" -v`
Expected: FAIL — yield 에 신컬럼 없음, step_history 테이블 없음.

- [ ] **Step 3: generate_dummy.py 수정**

(a) yield 행에 root_lot_id·lot_type 추가 — 순수 함수, rng 미사용(기존 난수열·임베딩 보존). `generate()` 의 `_write_sqlite(rows, logs)` 호출 직전에 rows 를 후처리:

```python
def _augment_yield(rows):
    """commonality 가 요구하는 root_lot_id·lot_type 을 채운다 (rng 미사용)."""
    for r in rows:
        r["root_lot_id"] = r["lot_id"]          # 더미는 lot_id 를 root_lot 으로 취급
        r["lot_type"] = "prod"                   # 더미는 전부 양산으로 단순화
    return rows
```

`generate()` 에서 `logs = _make_process_logs(rows, rng)` 다음 줄에 추가:

```python
    _augment_yield(rows)
    steps = _make_step_history(rows)
```

(b) step_history 생성 — 독립 rng 로 기존 난수열과 격리:

```python
# step_history 용 설비/챔버/PPID (process_log 와 느슨하게 공존).
SH_REAL_EQP, SH_REAL_CH, SH_REAL_PPID = "ETCH9", "B", "PPID_X"    # 불량군 전용
SH_CTRL_EQP, SH_CTRL_PPID = "ETCH9", "PPID_Y"                     # 대조군: 같은 설비 다른 챔버/PPID
SH_STEPS = ["Photo", "Etch", "Diffusion", "CMP"]                  # wafer 당 경로


def _make_step_history(rows):
    """wafer×스텝 이력. RECENT_LOT 타깃은 Etch 에서 ETCH9_B·PPID_X 를 공유하고
    대조군은 ETCH9_<번호>·PPID_Y 로 갈린다. 나머지 스텝은 양쪽 공통(미끼)."""
    sh_rng = np.random.default_rng(SEED + 1)
    steps = []
    for r in rows:
        wid = r["wafer_id"]
        for step in SH_STEPS:
            eqp, ch, ppid = f"{step.upper()[:4]}1", "A", "PPID_Z"   # 기본: 공통 경로
            if step == "Etch":
                if wid in GROUP_WAFERS:
                    eqp, ch, ppid = SH_REAL_EQP, SH_REAL_CH, SH_REAL_PPID
                elif wid in CONTROL_WAFERS:
                    eqp, ch, ppid = SH_CTRL_EQP, str(int(sh_rng.integers(1, 9))), SH_CTRL_PPID
                else:
                    eqp, ch, ppid = f"ETCH{int(sh_rng.integers(1, 9))}", "A", "PPID_Z"
            steps.append({
                "wafer_id": wid, "process_step": step,
                "eqp_id": eqp, "ch_id": ch, "ppid": ppid,
                "timestamp": r["date"] + " 10:00:00",
            })
    return steps
```

(c) `_write_sqlite` 시그니처·스키마 교체 — `_write_sqlite(rows, logs, steps)`:

```python
def _write_sqlite(rows, logs, steps):
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE yield (
            wafer_id     TEXT PRIMARY KEY,
            lot_id       TEXT NOT NULL,
            yield        REAL NOT NULL,
            defect_type  TEXT NOT NULL,
            process_step TEXT,
            date         TEXT NOT NULL,
            root_lot_id  TEXT NOT NULL,
            lot_type     TEXT NOT NULL
        )
    """)
    conn.executemany(
        "INSERT INTO yield VALUES (:wafer_id, :lot_id, :yield, :defect_type, "
        ":process_step, :date, :root_lot_id, :lot_type)", rows)
    conn.execute("""
        CREATE TABLE process_log (
            wafer_id     TEXT NOT NULL,
            process_step TEXT NOT NULL,
            equipment_id TEXT NOT NULL,
            eq_chamber   TEXT,
            param_name   TEXT NOT NULL,
            param_value  REAL NOT NULL,
            spec_low     REAL NOT NULL,
            spec_high    REAL NOT NULL
        )
    """)
    conn.executemany(
        """INSERT INTO process_log VALUES
           (:wafer_id, :process_step, :equipment_id, :eq_chamber, :param_name,
            :param_value, :spec_low, :spec_high)""", logs)
    conn.execute("""
        CREATE TABLE step_history (
            wafer_id     TEXT NOT NULL,
            process_step TEXT NOT NULL,
            eqp_id       TEXT NOT NULL,
            ch_id        TEXT,
            ppid         TEXT,
            timestamp    TEXT
        )
    """)
    conn.executemany(
        """INSERT INTO step_history VALUES
           (:wafer_id, :process_step, :eqp_id, :ch_id, :ppid, :timestamp)""", steps)
    conn.commit()
    conn.close()
```

`generate()` 의 `_write_sqlite(rows, logs)` 호출을 `_write_sqlite(rows, logs, steps)` 로 바꾼다.

- [ ] **Step 4: 더미 DB 재생성**

Run: `python data/generate_dummy.py`
Expected: 정상 종료, "SQLite: …/yield.db" 출력.

- [ ] **Step 5: dummy 테스트 통과 확인**

Run: `python -m pytest tests/test_dummy_data.py -v`
Expected: PASS — 기존 케이스(process_log·임베딩) 유지 + 신규 2케이스 green.

- [ ] **Step 6: 커밋**

```bash
git add data/generate_dummy.py tests/test_dummy_data.py data/yield.db
git commit -m "feat(dummy): step_history(+ppid) 신설 + yield root_lot/lot_type 정합

commonality 가 더미 위에서 end-to-end 동작하도록 step_history 를 심는다
(타깃=ETCH9_B·PPID_X 분리). process_log 는 2단 미리보기용 유지. 독립 rng 로
기존 임베딩·process_log 난수열 보존.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: agent_tools.py — raw find_commonality 제거, hyp_* legend 도구 확인

**Files:**
- Modify: `tools/agent_tools.py` (매달린 `find_commonality` 래퍼 + `cm` import 제거)
- Test: `tests/test_agent_tools.py` (도구 이름·hyp_* invoke 갱신)

**Interfaces:**
- Consumes: `registry.build_tools(registry.load_hypotheses())` → `hyp_eqp_ch_commonality`, `hyp_ppid_commonality` (Task 3), 더미 DB step_history (Task 4).
- Produces: `ALL_TOOLS`, `TOOLS_BY_NAME` — raw `find_commonality` 없음, legend hyp_* 포함.

- [ ] **Step 1: agent_tools 테스트 갱신 (실패)**

`tests/test_agent_tools.py` 의 `test_tool_names` 와 `test_hyp_chamber_concentration_tool_invokes` 를 교체:

```python
def test_tool_names():
    assert {t.name for t in at.ALL_TOOLS} == {
        "get_wafer", "search_similar", "aggregate_defects", "get_process_log",
        "validate_data_completeness", "find_counterexamples",
        "hyp_eqp_ch_commonality", "hyp_ppid_commonality",
        "finalize",
    }
    assert "finalize" not in at.TOOLS_BY_NAME
    assert "find_commonality" not in at.TOOLS_BY_NAME   # raw 래퍼 제거(legend 로 일원화)
```

```python
def test_hyp_eqp_ch_commonality_tool_invokes():
    res = at.TOOLS_BY_NAME["hyp_eqp_ch_commonality"].invoke({
        "group_ids": ["W2406_02", "W2406_04", "W2406_06"],
        "control_ids": ["W2406_01", "W2406_03", "W2406_05"],
    })
    keys = {c["key"] for c in res["candidates"]}
    assert "ETCH9_B" in keys
    assert any(c["passes"] for c in res["candidates"] if c["key"] == "ETCH9_B")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_agent_tools.py -k "tool_names or eqp_ch" -v`
Expected: FAIL — 옛 hyp_ 이름 존재/새 이름 없음.

- [ ] **Step 3: agent_tools.py 에서 raw find_commonality 제거**

`tools/agent_tools.py` 에서 다음을 삭제:
- 상단 `from tools import commonality as cm` import 줄.
- 파일 하단의 `@tool def find_commonality(...)` 함수 전체(현재 `ALL_TOOLS` 정의 뒤 매달린 부분).

`_HYPOTHESIS_TOOLS`·`ANALYSIS_TOOLS`·`ALL_TOOLS`·`TOOLS_BY_NAME` 정의는 그대로 둔다(이제 legend hyp_* 를 생성한다).

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_agent_tools.py -v`
Expected: PASS — 전 케이스 green (레거시 도구 테스트 포함).

- [ ] **Step 5: 커밋**

```bash
git add tools/agent_tools.py tests/test_agent_tools.py
git commit -m "refactor(agent_tools): raw find_commonality 제거, commonality 접근을 legend hyp_* 로 일원화

매달려 있던(미배선) find_commonality 래퍼 제거. EQP_CH commonality 는
hyp_eqp_ch_commonality(게이트 계약 shaped)로 도달한다.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: 게이트 계약 확인 + 전체 회귀 green

**Files:**
- Modify: `tests/test_graph_nodes.py` (mock finding 의 tool 이름·result 형태 갱신)
- Modify: `tests/test_e2e.py`, `tests/test_mock_llm.py` (필요 시 hyp_* 이름·흐름 반영)

**Interfaces:**
- Consumes: 전 Task 산출물. 게이트 `_collect_evidence`/`_finalize_gate` 는 무수정.

- [ ] **Step 1: test_graph_nodes 의 mock finding 갱신**

`tests/test_graph_nodes.py` 의 `EVIDENCE_FINDING_NEW`(및 `EVIDENCE_FINDING` 사용처)에서 tool 이름을 `hyp_eqp_ch_commonality` 로, result dict 에서 `comparison`/`column` 키를 제거하고 `legend` 를 넣는다. `_collect_evidence` 는 `candidates[].passes`·`value` 만 읽으므로 candidate 형태(`value`,`passes`)는 유지한다:

```python
EVIDENCE_FINDING_NEW = {
    "loop": 2, "tool": "hyp_eqp_ch_commonality",
    "args": {"group_ids": ["W2406_02", "W2406_04", "W2406_06"],
             "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
    "result": {"hypothesis_id": "eqp_ch_commonality",
               "legend": [{"level": "chamber", "columns": ["eqp_id", "ch_id"]}],
               "status": "ok",
               "candidates": [
                   {"value": ["Etch", "ETCH9_B"], "passes": True,
                    "level": "chamber", "key": "ETCH9_B",
                    "target_pass": 3, "control_pass": 0, "reject_reason": None},
                   {"value": ["Photo", "PHOTO1_A"], "passes": False,
                    "level": "chamber", "key": "PHOTO1_A",
                    "target_pass": 3, "control_pass": 3, "reject_reason": "분리 없음"},
               ]}}
```

`test_finalize_gate_sees_evidence_from_same_message` 등 `hyp_chamber_concentration` 을 참조하는 mock tool_call 이름도 `hyp_eqp_ch_commonality` 로 바꾼다. `EVIDENCE_FINDING`(구형) 을 쓰던 테스트가 있으면 `EVIDENCE_FINDING_NEW` 로 통일하거나 동일하게 갱신한다.

- [ ] **Step 2: test_graph_nodes 통과 확인**

Run: `python -m pytest tests/test_graph_nodes.py -v`
Expected: PASS — `_collect_evidence` 가 `{"ETCH9_B"}` 수집, 게이트 승인/반려 케이스 green.

- [ ] **Step 3: e2e·mock_llm 갱신 및 확인**

Run: `python -m pytest tests/test_e2e.py tests/test_mock_llm.py -v`
Expected: 실패 시 — mock LLM 이 호출하는 hyp_ 이름을 `hyp_eqp_ch_commonality` 로, finalize 가설 문자열이 `ETCH9_B` 를 포함하도록 갱신. suspect 토큰이 `ETCH9_B`(챔버 key)임에 유의(구형은 `ETCH-9`/`ETCH9_B`). 갱신 후 재실행하여 PASS.

- [ ] **Step 4: 전체 회귀**

Run: `python -m pytest -q`
Expected: PASS — 전체 green. 실패가 남으면 해당 파일의 옛 hyp_ 이름/comparison·column 참조를 legend 계약으로 갱신.

- [ ] **Step 5: 성공 기준 수동 확인**

Run:
```bash
python -c "from tools import agent_tools as at; import json; \
res = at.TOOLS_BY_NAME['hyp_eqp_ch_commonality'].invoke({'group_ids':['W2406_02','W2406_04','W2406_06'],'control_ids':['W2406_01','W2406_03','W2406_05']}); \
print(json.dumps([c for c in res['candidates'] if c['key']=='ETCH9_B'], ensure_ascii=False))"
```
Expected: `ETCH9_B` 후보가 `passes: true`, `target_pass: 3`, `control_pass: 0` 로 출력.

- [ ] **Step 6: 커밋**

```bash
git add tests/test_graph_nodes.py tests/test_e2e.py tests/test_mock_llm.py
git commit -m "test: 게이트·e2e 를 legend hyp_* 계약으로 갱신 (전체 회귀 green)

_collect_evidence 무수정 — candidate value/passes 계약 유지 확인.
mock finding·LLM 흐름을 hyp_eqp_ch_commonality / ETCH9_B 로 정합.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- §4 층 구조 → Task 1(commonality)·2(engine)·3(registry)·게이트 무수정(Task 6 확인). ✓
- §5 legend YAML → Task 3(hypotheses.yaml). ✓
- §6 commonality 일반화(행동보존) → Task 1. ✓
- §7 engine 재편(비교타입·_counterexamples 제거, passes/value) → Task 2. ✓
- §8 registry legend 스키마 → Task 3. ✓
- §9 generate_dummy(step_history+ppid, yield 정합, process_log 유지) → Task 4. ✓
- §10 raw find_commonality 제거 → Task 5. ✓
- §11 테스트 영향(test_yield_tools 무손) → Task 4·5·6 (test_yield_tools 미언급 = 무손). ✓
- §13 성공 기준 1~5 → Task 6 Step 4·5, Task 1 Step 4(행동보존). ✓

**2. Placeholder scan:** "TBD/TODO/적절히" 없음. 모든 코드 스텝에 실제 코드 포함. Task 6 Step 3 은 mock 파일 편집이 파일 내용 의존적이라 "필요 시 갱신" 지시 + 정확한 목표(hyp 이름·ETCH9_B) 명시. ✓

**3. Type consistency:**
- `find_commonality(target, control, legend=None, top_k=None)` — Task 1 정의, Task 2 engine·Task 4 테스트에서 동일 시그니처 사용. ✓
- 후보 필드: Task 1 이 `level/key/process_step/eqp_id/ch_id/ppid/target_pass/…/score` 생성 → Task 2 engine 이 동일 키 소비 → Task 6 게이트 `value`/`passes`. ✓
- `EQP_CH_LEGEND` — Task 1 정의, Task 1 테스트·(engine 은 spec.legend 사용). ✓
- `evaluate(spec, group_ids, control_ids)` — Task 2 정의, Task 3 build_tools 호출. ✓
- hyp 이름 `hyp_eqp_ch_commonality`/`hyp_ppid_commonality` — Task 3 yaml id → Task 5·6 일관. ✓

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-24-registry-commonality-realignment.md`.**
