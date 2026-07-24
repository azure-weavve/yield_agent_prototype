# 인과 가설 레지스트리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 전문가가 `hypotheses.yaml` 에 인과 가설을 한 줄 선언하면, 결정론 엔진이 실행하고 판별 시험(특이성·반례·효과크기)을 통과한 후보만 결론으로 승인하는 레지스트리를 만든다 — 개발자가 도구를 새로 짜지 않고.

**Architecture:** 신규 `domain/` 패키지(YAML 저작 + 로더 + 엔진). 엔진은 비교타입 3종(`group_only_categorical`/`categorical_concentration`/`numeric_distribution_shift`)과 판별 계층을 결정론적으로 계산한다. 레지스트리가 YAML → LangChain 도구를 동적 생성해 기존 tool-calling 루프에 꽂고, 게이트(`graph/nodes.py`)는 특정 도구 이름 대신 "판별 통과 후보"를 수집하도록 일반화한다. 기존 `compare_process_logs`/`compare_parameter_distribution` 의 인과 계산은 엔진으로 이관·흡수한다.

**Tech Stack:** Python 3, SQLite(stdlib `sqlite3`), `statistics`(stdlib), PyYAML, LangChain `@tool`, pytest. (설계 근거: `docs/superpowers/specs/2026-07-23-causal-hypothesis-registry-design.md`)

## Global Constraints

- **수치는 tool/engine 이 계산한 값만 인용, 임의 생성 절대 금지.** LLM 은 제안, 코드가 결정. (기존 원칙)
- **타입이 다른 잣대를 하나의 숫자로 뭉개지 않는다.** specificity 는 범주형 전용(수치형은 `None`), 순위는 같은 비교타입 안에서만.
- 모든 engine/tool 함수는 plain dict/list 반환 (JSON 직렬화 가능 — findings 감사 기록에 그대로 남음). JSON 직렬화로 tuple 은 list 가 된다.
- 기존 테스트는 이관 후에도 green 유지 (회귀 방어). 각 태스크 종료 시 `pytest` 전체 green.
- 파일 경로는 프로젝트 루트(`prototype/`) 기준.
- 새 의존성 `PyYAML` 은 `requirements.txt` 에 추가한다.
- 커밋 메시지 말미: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## File Structure

- `domain/__init__.py` (신규) — 빈 패키지 마커
- `domain/engine.py` (신규) — 비교타입 3종 + 판별 계층 + `evaluate()` 디스패치. 결정론적, 개발자 영역.
- `domain/registry.py` (신규) — `hypotheses.yaml` 로드 + 스키마 검증 + LangChain 도구 생성.
- `domain/hypotheses.yaml` (신규) — 전문가 저작 영역. 초기 가설 3개.
- `tools/agent_tools.py` (수정) — `compare_process_logs`/`compare_parameter_distribution` 을 레지스트리 생성 도구로 교체, `TOOLS_BY_NAME`/`ALL_TOOLS` 재구성.
- `graph/nodes.py` (수정) — `_collect_suspects` → `_collect_evidence`, 게이트 승인 조건 일반화.
- `data/generate_dummy.py` (수정) — `eq_chamber` 컬럼 추가, 진짜 원인(ETCH9_B)·미끼·대조군 배치.
- `llm/client.py` (수정) — `ScriptedMockLLMClient` 스크립트를 레지스트리 도구 이름·챔버 결론에 맞춰 갱신.
- 테스트: `tests/test_engine.py`(신규), `tests/test_registry.py`(신규), `tests/test_dummy_data.py`(수정), `tests/test_graph_nodes.py`(수정), `tests/test_e2e.py`(수정), `tests/test_yield_tools.py`(수정 — 흡수된 도구 테스트 이전/정리).

## Interfaces (전 태스크 공통 계약)

```python
# domain/engine.py 가 생산하는 형태

HypothesisResult = {
    "hypothesis_id": str,
    "comparison": str,
    "column": str,
    "candidates": list[Candidate],
}
Candidate = {
    "value": str | list,        # 범주형: ['Etch','ETCH9_B'] (공정,값) / 수치형: ['Etch','rf_power']
    "specificity": float | None, # 범주형만. 수치형은 None
    "counterexamples": dict,     # {passed_but_normal_rate, defect_without_cause_rate, ...}
    "effect_size": float | None, # 수치형만
    "spec_violation_rate": float | None,  # 수치형만 (흡수된 스펙 이탈 신호)
    "n_group": int,
    "n_control": int,
    "passes": bool,
    "reject_reason": str | None,
}

# 디스패치 진입점 (registry 가 호출)
def evaluate(spec: dict, group_ids: list[str], control_ids: list[str]) -> HypothesisResult
# 비교타입 3종 (각각 candidates 리스트 반환)
def group_only_categorical(group_ids, control_ids, column, spec) -> list[Candidate]
def categorical_concentration(group_ids, control_ids, column, spec) -> list[Candidate]
def numeric_distribution_shift(group_ids, control_ids, column, spec) -> list[Candidate]
COMPARISONS: dict[str, callable]   # 비교타입명 -> 함수
```

엔진 기본 임계 (spec 에서 override 가능):
```python
DEFAULT_MIN_SPECIFICITY = 0.8
DEFAULT_MIN_EFFECT_SIZE = 0.8      # Cohen's d "큰 효과" 관례
DEFAULT_MAX_COUNTEREXAMPLE_RATE = 0.2
```

---

### Task 1: engine 기반 + `group_only_categorical` (기존 동작 보존)

**Files:**
- Create: `domain/__init__.py`, `domain/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Produces: `evaluate(spec, group_ids, control_ids)`, `group_only_categorical(...)`, `COMPARISONS`, `_counterexamples(column, value, process_step, defect_type)`, 기본 임계 상수.
- Consumes: `config.DB_PATH` 의 `process_log`/`yield` 테이블 (기존 스키마).

**설계 메모:** `group_only_categorical` 은 기존 `compare_process_logs` 의 `suspect_equipment`(불량군 전원 통과 & 대조군 0)를 일반화한다. 후보는 `(process_step, 값)` 쌍. 특이성 = `group_count/n_group` (단 `control_count==0` 일 때, 아니면 0.0). `passes = specificity >= min_specificity`. 이 조건이 기존 suspect 판정(`group_count==n_group and control_count==0`)과 동치가 되도록 기본 `min_specificity=0.8`, n_group=3 기준(3/3=1.0 통과, 2/3=0.67 탈락).

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_engine.py`

```python
"""engine 비교타입·판별 계층 단위 테스트. 픽스처 DB 를 임시 생성해 결정론 검증."""

import sqlite3
import pytest

from domain import engine


@pytest.fixture
def fx_db(tmp_path, monkeypatch):
    """process_log + yield 최소 픽스처. 불량군 3장 전원 Etch=ETCH-9, 대조군 3장은 ETCH-1~3."""
    db = tmp_path / "fx.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE yield (wafer_id TEXT PRIMARY KEY, lot_id TEXT, yield REAL, "
                 "defect_type TEXT, process_step TEXT, date TEXT)")
    conn.execute("CREATE TABLE process_log (wafer_id TEXT, process_step TEXT, equipment_id TEXT, "
                 "eq_chamber TEXT, param_name TEXT, param_value REAL, spec_low REAL, spec_high REAL)")
    group = ["G1", "G2", "G3"]
    control = ["C1", "C2", "C3"]
    for w in group:
        conn.execute("INSERT INTO yield VALUES (?,?,?,?,?,?)", (w, "L", 80.0, "center_spot", "Etch", "d"))
        conn.execute("INSERT INTO process_log VALUES (?,?,?,?,?,?,?,?)",
                     (w, "Etch", "ETCH-9", "ETCH9_B", "rf_power", 570.0, 450.0, 550.0))
    for i, w in enumerate(control):
        conn.execute("INSERT INTO yield VALUES (?,?,?,?,?,?)", (w, "L", 95.0, "none", "Normal", "d"))
        conn.execute("INSERT INTO process_log VALUES (?,?,?,?,?,?,?,?)",
                     (w, "Etch", f"ETCH-{i+1}", f"ETCH{i+1}_A", "rf_power", 500.0, 450.0, 550.0))
    conn.commit(); conn.close()
    monkeypatch.setattr(engine.config, "DB_PATH", str(db))
    return db


def test_group_only_flags_group_exclusive_equipment(fx_db):
    cands = engine.group_only_categorical(["G1", "G2", "G3"], ["C1", "C2", "C3"], "equipment_id", {})
    passing = [c for c in cands if c["passes"]]
    assert len(passing) == 1
    c = passing[0]
    assert c["value"] == ["Etch", "ETCH-9"]
    assert c["specificity"] == 1.0
    assert c["n_group"] == 3 and c["n_control"] == 0


def test_group_only_excludes_shared_equipment(fx_db):
    # 대조군도 쓰는 값은 통과 후보가 아니다
    cands = engine.group_only_categorical(["G1", "G2", "G3"], ["C1", "C2", "C3"], "equipment_id", {})
    assert all(c["value"] != ["Etch", "ETCH-1"] or not c["passes"] for c in cands)
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_engine.py -v` → FAIL (`ModuleNotFoundError: domain`)

- [ ] **Step 3: 최소 구현** — `domain/__init__.py` (빈 파일) + `domain/engine.py`

```python
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


def _usage(conn, ids, column):
    """(process_step, column값) -> 통과 wafer 수. 값이 NULL/빈 문자열이면 제외."""
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
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_engine.py -v` → PASS

- [ ] **Step 5: characterization 테스트 추가** — 실제 더미 DB 에서 `group_only_categorical` 의 통과 후보 장비집합이 기존 `compare_process_logs` 의 `suspect_equipment` 장비집합과 일치하는지 고정.

```python
def test_group_only_matches_legacy_compare_process_logs():
    """이관 안전망: engine 통과 후보의 장비 == 기존 도구 suspect_equipment."""
    from tools import yield_tools as yt
    group = ["W2406_02", "W2406_04", "W2406_06"]
    control = ["W2406_01", "W2406_03", "W2406_05"]
    legacy = {r["equipment_id"] for r in yt.compare_process_logs(group, control)["suspect_equipment"]}
    cands = engine.group_only_categorical(group, control, "equipment_id", {})
    ours = {c["value"][1] for c in cands if c["passes"]}
    assert ours == legacy
```

- [ ] **Step 6: 통과 확인 + 전체 회귀** — Run: `pytest tests/test_engine.py tests/test_yield_tools.py -v` → PASS. (이 시점 더미 DB 는 아직 `eq_chamber` 컬럼이 없으므로 `test_group_only_matches_legacy...` 는 `equipment_id` 만 참조 — OK.)

- [ ] **Step 7: 커밋**

```bash
git add domain/__init__.py domain/engine.py tests/test_engine.py
git commit -m "feat(engine): group_only_categorical + 기존 compare_process_logs 동작 보존 characterization"
```

---

### Task 2: `numeric_distribution_shift` + 스펙 이탈 흡수(파라미터 귀속)

**Files:**
- Modify: `domain/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Produces: `numeric_distribution_shift(group_ids, control_ids, column, spec)`, `_cohens_d(g_vals, c_vals)`.
- Consumes: Task 1 의 `_conn`, 기본 임계.

**설계 메모:** 기존 `compare_parameter_distribution` 의 평균차·Cohen's d·스펙 이탈률을 일반화. 후보 = `(process_step, param_name)`. `specificity=None`. `passes = |effect_size| >= min_effect_size AND passed_but_normal_rate <= max_counterexample`. 스펙 이탈률은 후보의 `spec_violation_rate` 필드로 실려 파라미터에 귀속(장비 귀속 폐기).

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_engine.py` 에 추가. `fx_db` 픽스처를 확장해 수치 드리프트가 있게(불량군 rf_power 570, 대조군 500).

```python
def test_numeric_shift_flags_drifted_parameter(fx_db):
    cands = engine.numeric_distribution_shift(["G1", "G2", "G3"], ["C1", "C2", "C3"], "param_value", {})
    passing = [c for c in cands if c["passes"]]
    assert len(passing) == 1
    c = passing[0]
    assert c["value"] == ["Etch", "rf_power"]
    assert c["specificity"] is None
    assert c["effect_size"] is not None and abs(c["effect_size"]) >= 0.8
    assert c["spec_violation_rate"] == 1.0     # 불량군 3행 전부 스펙 밖 (스펙 이탈 흡수)


def test_numeric_shift_rejects_when_no_drift(fx_db, monkeypatch):
    # 대조군도 570 이면 효과크기 0 → 탈락 (기존 오탐 보정)
    import sqlite3
    conn = sqlite3.connect(fx_db)
    conn.execute("UPDATE process_log SET param_value = 570.0 WHERE wafer_id LIKE 'C%'")
    conn.commit(); conn.close()
    cands = engine.numeric_distribution_shift(["G1", "G2", "G3"], ["C1", "C2", "C3"], "param_value", {})
    assert all(not c["passes"] for c in cands)
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_engine.py::test_numeric_shift_flags_drifted_parameter -v` → FAIL (`AttributeError: numeric_distribution_shift`)

- [ ] **Step 3: 최소 구현** — `domain/engine.py` 에 추가

```python
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


COMPARISONS["numeric_distribution_shift"] = numeric_distribution_shift
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_engine.py -v` → PASS

- [ ] **Step 5: 커밋**

```bash
git add domain/engine.py tests/test_engine.py
git commit -m "feat(engine): numeric_distribution_shift + 스펙 이탈을 파라미터에 귀속(흡수)"
```

---

### Task 3: `categorical_concentration` + 판별 계층(특이성·반례)

**Files:**
- Modify: `domain/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Produces: `categorical_concentration(group_ids, control_ids, column, spec)`.
- Consumes: Task 1 `_usage`, `_counterexamples`, 기본 임계.

**설계 메모:** 신규. 후보 = `(process_step, 값)`. 편중 특이성 = `group_users / (group_users + control_users)` (해당 값을 거친 불량군 대 전체 비율). `passes = specificity >= min_specificity AND passed_but_normal_rate <= max_counterexample`. 미끼(두 그룹 공유 값)는 발화하되 특이성 낮아 탈락.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_engine.py`. `fx_db` 는 불량군 `ETCH9_B`, 대조군 `ETCH{i}_A` (진짜 원인) + 공유 미끼가 필요하므로 픽스처에 미끼 행 추가.

```python
@pytest.fixture
def fx_db_chamber(fx_db):
    """fx_db 에 Depo 공정 공유 챔버(미끼) 추가: 불량군·대조군 모두 DEP1_A 사용."""
    import sqlite3
    conn = sqlite3.connect(fx_db)
    for w in ["G1", "G2", "G3", "C1", "C2", "C3"]:
        conn.execute("INSERT INTO process_log VALUES (?,?,?,?,?,?,?,?)",
                     (w, "Depo", "DEP-1", "DEP1_A", "temp", 300.0, 250.0, 350.0))
    conn.commit(); conn.close()
    return fx_db


def test_concentration_flags_real_chamber_and_rejects_decoy(fx_db_chamber):
    cands = engine.categorical_concentration(["G1", "G2", "G3"], ["C1", "C2", "C3"], "eq_chamber", {})
    by_val = {tuple(c["value"]): c for c in cands}
    real = by_val[("Etch", "ETCH9_B")]
    decoy = by_val[("Depo", "DEP1_A")]
    assert real["passes"] and real["specificity"] == 1.0        # 불량군 전용
    assert not decoy["passes"] and decoy["specificity"] < 0.9   # 공유 → 편중 낮음 → 탈락
    assert decoy["reject_reason"]
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_engine.py::test_concentration_flags_real_chamber_and_rejects_decoy -v` → FAIL

- [ ] **Step 3: 최소 구현** — `domain/engine.py` 에 추가

```python
def categorical_concentration(group_ids, control_ids, column, spec):
    min_spec = spec.get("min_specificity", DEFAULT_MIN_SPECIFICITY)
    max_ce = spec.get("max_counterexample_rate", DEFAULT_MAX_COUNTEREXAMPLE_RATE)
    with _conn() as conn:
        g, c = _usage(conn, group_ids, column), _usage(conn, control_ids, column)
    cands = []
    for key in sorted(set(g) | set(c)):
        gc, cc = g.get(key, 0), c.get(key, 0)
        specificity = round(gc / (gc + cc), 3) if (gc + cc) else 0.0
        ce = _counterexamples(column, key[1], key[0], "center_spot")
        pbn = ce["passed_but_normal_rate"]
        passes = gc > 0 and specificity >= min_spec and pbn <= max_ce
        reasons = []
        if specificity < min_spec:
            reasons.append(f"편중 특이성 {specificity} < {min_spec}")
        if pbn > max_ce:
            reasons.append(f"반례율 {pbn} > {max_ce}")
        cands.append({
            "value": [key[0], key[1]], "specificity": specificity,
            "counterexamples": ce, "effect_size": None, "spec_violation_rate": None,
            "n_group": gc, "n_control": cc, "passes": passes,
            "reject_reason": None if passes else "; ".join(reasons) or "발화 없음",
        })
    cands.sort(key=lambda x: -x["specificity"])
    return cands


COMPARISONS["categorical_concentration"] = categorical_concentration
```

> **주의:** `_counterexamples` 의 `defect_type` 인자는 데모 픽스처가 `center_spot` 고정이라 하드코딩돼 있다. 실제로는 spec 이나 불량군 라벨에서 와야 한다 — Task 4 에서 spec 에 `defect_type` 을 optional 로 받거나, 불량군 최빈 라벨을 조회하도록 확장한다. Task 3 범위에선 `center_spot` 고정으로 데모 성립.

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_engine.py -v` → PASS

- [ ] **Step 5: 커밋**

```bash
git add domain/engine.py tests/test_engine.py
git commit -m "feat(engine): categorical_concentration + 편중 특이성·반례 판별 (미끼 탈락)"
```

---

### Task 4: `registry.py` + `hypotheses.yaml` (로드·검증·도구 생성)

**Files:**
- Create: `domain/registry.py`, `domain/hypotheses.yaml`
- Modify: `requirements.txt` (PyYAML 추가)
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: `load_hypotheses(path=None) -> list[dict]`, `build_tools(specs) -> list[BaseTool]`, `REQUIRED_FIELDS`.
- Consumes: `engine.evaluate`, `engine.COMPARISONS`.

**설계 메모:** YAML 로드 → 스키마 검증(필수 필드·비교타입 유효성) → 가설별로 `(group_ids, control_ids, reason="")` 시그니처의 LangChain 도구를 클로저로 생성. 도구 이름 = `hyp_<id>`. docstring = YAML `description`. 도구 실행 = `engine.evaluate(spec, group_ids, control_ids)`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_registry.py`

```python
"""레지스트리 로더·도구 생성 단위 테스트."""

import pytest
from domain import registry


VALID = [{"id": "chamber_concentration", "name": "챔버 편중",
          "description": "설비·챔버 조합 편중 확인", "comparison": "categorical_concentration",
          "column": "eq_chamber", "min_specificity": 0.9}]


def test_load_valid_yaml(tmp_path):
    import yaml
    p = tmp_path / "h.yaml"
    p.write_text(yaml.safe_dump(VALID, allow_unicode=True), encoding="utf-8")
    specs = registry.load_hypotheses(p)
    assert specs[0]["id"] == "chamber_concentration"


def test_reject_missing_field(tmp_path):
    import yaml
    bad = [{"id": "x", "name": "n", "comparison": "group_only_categorical"}]  # column 없음
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="column"):
        registry.load_hypotheses(p)


def test_reject_unknown_comparison(tmp_path):
    import yaml
    bad = [{"id": "x", "name": "n", "description": "d", "comparison": "bogus", "column": "c"}]
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="bogus"):
        registry.load_hypotheses(p)


def test_build_tools_produces_named_callables():
    tools = registry.build_tools(VALID)
    assert tools[0].name == "hyp_chamber_concentration"
    assert "챔버" in tools[0].description
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_registry.py -v` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 최소 구현** — `domain/registry.py`

```python
"""hypotheses.yaml 로드 + 스키마 검증 + LangChain 도구 동적 생성.

전문가는 YAML 만 편집한다. 여기(개발자 영역)는 그 선언을 실행 가능한 도구로 바꾼다.
"""

from pathlib import Path

import yaml
from langchain_core.tools import StructuredTool

from domain import engine

REQUIRED_FIELDS = ("id", "name", "description", "comparison", "column")
DEFAULT_PATH = Path(__file__).resolve().parent / "hypotheses.yaml"


def load_hypotheses(path=None):
    path = Path(path) if path else DEFAULT_PATH
    specs = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(specs, list):
        raise ValueError(f"{path}: 최상위가 가설 리스트가 아니다")
    for i, s in enumerate(specs):
        for f in REQUIRED_FIELDS:
            if f not in s:
                raise ValueError(f"가설 #{i}: 필수 필드 '{f}' 누락")
        if s["comparison"] not in engine.COMPARISONS:
            raise ValueError(f"가설 '{s['id']}': 미지의 비교타입 '{s['comparison']}'")
    return specs


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

`domain/hypotheses.yaml`:

```yaml
- id: equipment_commonality
  name: 장비 공통성
  description: |
    불량 그룹 전원이 거쳤고 대조군은 안 거친 (공정,장비)를 찾는다.
    특정 장비가 원인으로 의심될 때 사용.
  comparison: group_only_categorical
  column: equipment_id

- id: chamber_concentration
  name: 챔버 편중
  description: 불량 그룹이 특정 설비·챔버 조합(예 ETCH9_B)에 몰려 있는지 확인한다. 챔버 매칭 불량 의심 시 사용.
  comparison: categorical_concentration
  column: eq_chamber
  min_specificity: 0.9

- id: parameter_drift
  name: 파라미터 드리프트
  description: 스펙 내라도 불량군의 파라미터 값이 대조군과 체계적으로 다른지 본다.
  comparison: numeric_distribution_shift
  column: param_value
```

`requirements.txt` 에 `PyYAML` 추가 (없으면).

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_registry.py -v` → PASS. `pip install pyyaml` 필요 시 실행.

- [ ] **Step 5: 커밋**

```bash
git add domain/registry.py domain/hypotheses.yaml requirements.txt tests/test_registry.py
git commit -m "feat(registry): hypotheses.yaml 로드·검증·도구 생성"
```

---

### Task 5: 데이터 — `eq_chamber` 컬럼 + 진짜 원인·미끼·대조군 배치

**Files:**
- Modify: `data/generate_dummy.py`
- Test: `tests/test_dummy_data.py`

**Interfaces:**
- Produces: `process_log.eq_chamber` 컬럼, `ETCH9_B`(진짜)·공유 미끼 챔버.
- Consumes: 없음.

**설계 메모 (핵심):**
- `process_log` 스키마에 `eq_chamber TEXT` 추가.
- 불량군 3장 Etch: `equipment_id='ETCH-9'`, `eq_chamber='ETCH9_B'`.
- **대조군 3장 Etch: `equipment_id='ETCH-9'`(같은 설비!) 이되 `eq_chamber='ETCH9_C'`(다른 챔버).** → `equipment_commonality`(설비)는 대조군도 ETCH-9 를 써서 발화 안 하고, `chamber_concentration` 만 `ETCH9_B` 를 집는다 (설비→챔버로 좁혀짐, 이중보고 없음).
- **미끼:** 별도 공정(예 Photo)에서 불량군·대조군이 **공유하는** eq_chamber 하나(예 `PHOTO1_A`) → 편중 조사에서 발화하지만 특이성 낮아 탈락.
- **회귀 주의:** 기존 mock 은 결론을 `group_spec_violations`(스펙 이탈 rf_power)에서 만든다. 불량군 Etch rf_power 는 여전히 스펙 밖(570)이라, 대조군을 ETCH-9 로 옮겨도 `group_spec_violations` 는 ETCH-9 를 계속 담아 **기존 e2e("ETCH-9" 결론) 는 green 유지**된다. (레지스트리로의 전환은 Task 7.)
- 난수열 보존: `eq_chamber` 는 각 로그 행 생성 시 기존 난수 소비 순서를 바꾸지 않도록 `equipment_id` 결정 직후에 파생한다 (신규 `rng` 호출 금지 — 결정론적 매핑 사용).

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_dummy_data.py` 에 추가 (기존 파일 구조 확인 후 append)

```python
def test_process_log_has_eq_chamber(_regenerated_db):
    import sqlite3, config
    conn = sqlite3.connect(config.DB_PATH); conn.row_factory = sqlite3.Row
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(process_log)")}
    assert "eq_chamber" in cols
    # 진짜 원인: 불량군 3장 전부 Etch 에서 ETCH9_B
    rows = conn.execute("SELECT eq_chamber FROM process_log "
                        "WHERE process_step='Etch' AND wafer_id IN ('W2406_02','W2406_04','W2406_06')").fetchall()
    conn.close()
    assert {r["eq_chamber"] for r in rows} == {"ETCH9_B"}


def test_control_shares_equipment_not_chamber(_regenerated_db):
    import sqlite3, config
    conn = sqlite3.connect(config.DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT equipment_id, eq_chamber FROM process_log "
                        "WHERE process_step='Etch' AND wafer_id IN ('W2406_01','W2406_03','W2406_05')").fetchall()
    conn.close()
    assert all(r["equipment_id"] == "ETCH-9" for r in rows)      # 같은 설비
    assert all(r["eq_chamber"] != "ETCH9_B" for r in rows)       # 다른 챔버
```

> `_regenerated_db` 픽스처는 기존 `tests/test_dummy_data.py` 의 재생성 픽스처 관례를 따른다 (없으면 `data.generate_dummy.generate()` 호출 후 `config.DB_PATH` 를 가리키는 픽스처를 만든다 — 기존 파일 확인).

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_dummy_data.py -v` → FAIL

- [ ] **Step 3: 구현** — `data/generate_dummy.py`

`_make_process_logs` 수정: `equipment_id` 결정 뒤 `eq_chamber` 파생 규칙 추가. 대조군(RECENT_LOT 홀수 3장)의 Etch 를 ETCH-9 / 다른 챔버로 배치. 미끼 공정 추가.

```python
# PROCESS_FLOW 아래 상수 추가
DECOY_STEP = "Photo"
DECOY_CHAMBER = "PHOTO1_A"       # 불량군·대조군 공유 (미끼)
REAL_CHAMBER = "ETCH9_B"         # 진짜 원인 (불량군 전용)
CONTROL_ETCH_CHAMBER = "ETCH9_C" # 대조군: 같은 ETCH-9, 다른 챔버

def _make_process_logs(rows, rng):
    logs = []
    for r in rows:
        for step, param, lo, hi in PROCESS_FLOW:
            if r["process_step"] == step:
                equip = f"{step.upper()}-9"
                value = round(hi + (hi - lo) * 0.2, 2)
                chamber = REAL_CHAMBER if step == "Etch" else f"{equip}_A"
            elif r["wafer_id"] == UNLABELED_LOW_WAFER and step == "Etch":
                equip = "ETCH-9"; value = round(hi - (hi - lo) * 0.02, 2)
                chamber = "ETCH9_D"
            elif r["wafer_id"] in CONTROL_WAFERS and step == "Etch":
                # 대조군: 같은 설비(ETCH-9) 다른 챔버 → equipment_commonality 억제
                equip = "ETCH-9"; value = round(float(rng.uniform(lo, hi)), 2)
                chamber = CONTROL_ETCH_CHAMBER
            else:
                equip = f"{step.upper()}-{int(rng.integers(1, 4))}"
                value = round(float(rng.uniform(lo, hi)), 2)
                chamber = f"{equip}_A"
            # 미끼: RECENT_LOT 불량군+대조군이 Photo 에서 공유 챔버
            if step == DECOY_STEP and r["wafer_id"] in (GROUP_WAFERS + CONTROL_WAFERS):
                chamber = DECOY_CHAMBER
            logs.append({
                "wafer_id": r["wafer_id"], "process_step": step,
                "equipment_id": equip, "eq_chamber": chamber,
                "param_name": param, "param_value": value,
                "spec_low": lo, "spec_high": hi,
            })
    return logs
```

`_write_sqlite` 의 `CREATE TABLE process_log` 에 `eq_chamber TEXT` 추가하고 INSERT 문에 `:eq_chamber` 추가.

- [ ] **Step 4: 재생성 + 통과 확인**

Run: `python data/generate_dummy.py` (더미 재생성)
Run: `pytest tests/test_dummy_data.py -v` → PASS
Run: `pytest tests/test_e2e.py tests/test_yield_tools.py -v` → PASS (기존 e2e 는 group_spec_violations 경로로 ETCH-9 결론 유지)

> 만약 `test_group_only_matches_legacy...`(Task 1) 가 이제 실패하면: 대조군이 ETCH-9 를 쓰게 되어 `suspect_equipment` 가 비고 engine 도 비므로 **양쪽 다 빈 집합 → 여전히 일치**(PASS). 확인만 한다.

- [ ] **Step 5: 커밋**

```bash
git add data/generate_dummy.py tests/test_dummy_data.py
git commit -m "feat(data): eq_chamber 컬럼 + 진짜 원인 ETCH9_B·공유 미끼·대조군 동일설비 배치"
```

---

### Task 6: 게이트 일반화 — `_collect_suspects` → `_collect_evidence`

**Files:**
- Modify: `graph/nodes.py`
- Test: `tests/test_graph_nodes.py`

**Interfaces:**
- Produces: `_collect_evidence(findings) -> set[str]` (판별 통과 후보의 토큰 집합).
- Consumes: HypothesisResult 형태의 finding `result`.

**설계 메모:** `_collect_evidence` 는 finding `result` 가 `candidates` 키를 가진(=레지스트리 도구 결과) 것만 훑어 `passes=True` 후보의 토큰을 모은다. 토큰 = `value[-1]`(list 면 마지막, 아니면 str). 게이트 승인 조건·반려 메시지는 "suspect" 대신 "판별 통과 근거" 용어로 유지하되 로직 동일.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_graph_nodes.py`. 기존 `EVIDENCE_FINDING`(구 형태)을 대체할 신형 finding 을 추가하고, 신 게이트가 이를 근거로 승인하는지 검증.

```python
# 신형(레지스트리) 증거 finding: 챔버 가설이 ETCH9_B 를 통과 판정
EVIDENCE_FINDING_NEW = {
    "loop": 2, "tool": "hyp_chamber_concentration",
    "args": {"group_ids": ["W2406_02", "W2406_04", "W2406_06"],
             "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
    "result": {"hypothesis_id": "chamber_concentration", "comparison": "categorical_concentration",
               "column": "eq_chamber",
               "candidates": [
                   {"value": ["Etch", "ETCH9_B"], "specificity": 1.0, "passes": True,
                    "counterexamples": {}, "effect_size": None, "spec_violation_rate": None,
                    "n_group": 3, "n_control": 0, "reject_reason": None},
                   {"value": ["Photo", "PHOTO1_A"], "specificity": 0.5, "passes": False,
                    "counterexamples": {}, "effect_size": None, "spec_violation_rate": None,
                    "n_group": 3, "n_control": 3, "reject_reason": "편중 특이성 0.5 < 0.9"},
               ]},
    "thought": "챔버 편중",
}


def test_collect_evidence_gathers_passing_tokens():
    tokens = nodes._collect_evidence([EVIDENCE_FINDING_NEW])
    assert tokens == {"ETCH9_B"}          # 통과 후보만, 미끼(PHOTO1_A) 제외


def test_gate_accepts_chamber_hypothesis():
    ai = _ai_finalize(0.9, hypothesis="Etch 공정 ETCH9_B 챔버 편중이 원인")
    out = nodes.tools_node({"messages": [ai], "loop_count": 4, "findings": [EVIDENCE_FINDING_NEW]})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "confirmed"
```

기존 `test_finalize_gate_accepts_high_confidence_with_evidence` 등에서 쓰는 `EVIDENCE_FINDING`(구 형태)도 신 형태로 교체한다 (구 `compare_process_logs` 결과 형태는 이제 게이트가 안 읽음).

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_graph_nodes.py -v` → FAIL

- [ ] **Step 3: 구현** — `graph/nodes.py` 의 `_collect_suspects` 를 교체

```python
def _collect_evidence(findings: list[dict]) -> set[str]:
    """findings 에서 판별 통과 후보의 토큰을 모은다 (LLM 이 만들 수 없는 근거).

    레지스트리 도구 결과(HypothesisResult, candidates 보유)만 훑는다.
    토큰 = value 의 마지막 요소 (범주형 (공정,값)->값, 수치형 (공정,파라미터)->파라미터).
    """
    tokens = set()
    for f in findings:
        result = f.get("result")
        if not isinstance(result, dict) or "candidates" not in result:
            continue
        for c in result["candidates"]:
            if c.get("passes"):
                v = c["value"]
                tokens.add(v[-1] if isinstance(v, (list, tuple)) else str(v))
    return tokens
```

`_finalize_gate` 내부 `suspects = _collect_suspects(findings)` → `suspects = _collect_evidence(findings)`. 반려 메시지의 "compare_process_logs" 안내 문구는 "가설 도구(hyp_*)로 두 그룹을 대조하라" 로 갱신. 나머지 로직 동일.

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/test_graph_nodes.py -v` → PASS

- [ ] **Step 5: 커밋**

```bash
git add graph/nodes.py tests/test_graph_nodes.py
git commit -m "feat(gate): _collect_suspects → _collect_evidence (판별 통과 후보 기반, 도구 이름 비의존)"
```

---

### Task 7: 통합 — 레지스트리 도구 배선 + mock LLM + e2e 전환(챔버 결론)

**Files:**
- Modify: `tools/agent_tools.py`, `llm/client.py`, `tests/test_e2e.py`, `tests/test_agent_tools.py`(있으면)
- Test: `tests/test_e2e.py`

**Interfaces:**
- Consumes: `registry.load_hypotheses`, `registry.build_tools`, engine.
- Produces: 챔버 결론(ETCH9_B)으로 완주하는 e2e.

**설계 메모:** `agent_tools.ANALYSIS_TOOLS` 에서 `compare_process_logs`·`compare_parameter_distribution` 두 `@tool` 을 제거하고, 레지스트리 생성 도구(`hyp_*`)로 대체한다. base 조회 도구(`get_wafer` 등)·`find_counterexamples`·`finalize` 는 유지. mock LLM 스크립트를 `hyp_chamber_concentration` 호출 → 챔버 결론으로 갱신.

- [ ] **Step 1: 실패 테스트 작성/수정** — `tests/test_e2e.py` 의 결론 기대를 ETCH9_B 로 전환

```python
    # (test_full_loop_reaches_report_with_audit_trail 안)
    assert "ETCH9_B" in state["final_hypothesis"]        # ETCH-9 → 챔버로 좁혀진 결론
    tools_used = [f["tool"] for f in state["findings"]]
    assert any(t.startswith("hyp_") for t in tools_used)  # 레지스트리 도구가 실제 호출됨
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/test_e2e.py -v` → FAIL

- [ ] **Step 3: 구현**

`tools/agent_tools.py`:
```python
from domain import registry

# compare_process_logs, compare_parameter_distribution 의 @tool 정의 삭제
_HYPOTHESIS_TOOLS = registry.build_tools(registry.load_hypotheses())

ANALYSIS_TOOLS = [get_wafer, search_similar, aggregate_defects, get_process_log,
                  validate_data_completeness, find_counterexamples, *_HYPOTHESIS_TOOLS]
ALL_TOOLS = ANALYSIS_TOOLS + [finalize]
TOOLS_BY_NAME = {t.name: t for t in ANALYSIS_TOOLS}
```

`llm/client.py` `ScriptedMockLLMClient.analyze_step` 갱신: `aggregate_defects` → `finalize(0.6, 반려)` → `hyp_chamber_concentration(group, control)` → 통과 후보(ETCH9_B)로 `finalize(0.9)`.

```python
        if "hyp_chamber_concentration" not in done:
            return self._call("hyp_chamber_concentration",
                              {"group_ids": target, "control_ids": control},
                              "종료 제안이 반려됐다. 챔버 편중 가설로 두 그룹을 대조한다.")
        res = self._result(tool_msgs, "hyp_chamber_concentration")
        passing = [c for c in res["candidates"] if c["passes"]]
        top = passing[0]
        val = top["value"][-1]
        hyp = (f"{top['value'][0]} 공정 {val} 편중(특이성 {top['specificity']}, "
               f"불량군 {top['n_group']}장 전용)이 원인")
        return self._call("finalize", {"hypothesis": hyp, "confidence": 0.9},
                          "챔버 편중 가설이 불량군 전용 챔버를 특이적으로 집었다. 근거 충분.")
```

(기존 `compare_process_logs` 분기 2개는 위 두 분기로 교체.)

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `pytest tests/test_e2e.py -v` → PASS
Run: `pytest -q` → 전체 PASS. 실패 시: 흡수된 도구(`compare_process_logs`)를 참조하던 잔여 테스트(`test_mock_llm.py` 등)를 신 도구 이름·형태로 갱신.

- [ ] **Step 5: 커밋**

```bash
git add tools/agent_tools.py llm/client.py tests/
git commit -m "feat: 레지스트리 도구 배선 + mock/e2e 를 챔버 결론(ETCH9_B)으로 전환"
```

---

### Task 8: 흡수된 도구 정리 + 전체 회귀 + 문서 반영

**Files:**
- Modify: `tools/yield_tools.py`, `tests/test_yield_tools.py`, `README.md`(해당 시)
- Delete(선택): 없음 — `compare_process_logs`/`compare_parameter_distribution` 은 characterization·다른 참조가 없다면 제거, 있으면 유지.

**설계 메모:** engine 이 인과 계산을 담당하므로 `yield_tools.compare_process_logs`/`compare_parameter_distribution` 은 더 이상 그래프에서 호출되지 않는다. Task 1 characterization 테스트가 아직 이들을 참조하므로 **함수 자체는 남기되**, agent 도구(@tool)로는 노출하지 않는다(Task 7 에서 이미 제거됨). 남은 참조가 characterization 뿐이면 그대로 두고, 없으면 함수·테스트를 정리한다.

- [ ] **Step 1: 미사용 참조 스캔**

Run: `git grep -n "compare_process_logs\|compare_parameter_distribution" -- '*.py'`
남은 참조를 목록화한다 (engine characterization, 혹시 남은 테스트).

- [ ] **Step 2: 전체 테스트**

Run: `pytest -q` → 전체 PASS 확인. 실패 항목을 신 구조로 수정.

- [ ] **Step 3: 앱 스모크 실행**

Run: `python main.py`(또는 프로젝트 실행 관례) 로 `W2406_02` 분석이 크래시 없이 리포트까지 나오고 결론에 `ETCH9_B` 가 나오는지 눈으로 확인.

- [ ] **Step 4: 문서 한 줄 반영** — `README.md` 에 도메인 가설 레지스트리(`domain/hypotheses.yaml` 편집으로 인과 가설 추가) 존재를 한두 줄로 기록 (기존 문서 톤에 맞춰).

- [ ] **Step 5: 커밋**

```bash
git add -A
git commit -m "chore: 흡수 도구 정리 + 레지스트리 문서 반영 + 전체 회귀 green"
```

---

## Self-Review

**1. Spec coverage (spec 절 → 태스크):**
- §2 구조(domain/): Task 1(engine)·4(registry, yaml) ✅
- §3 스키마·초기 3항목: Task 4 (hypotheses.yaml) ✅
- §4 비교타입 3종 + HypothesisResult: Task 1·2·3 ✅
- §5 판별 계층(특이성·반례·효과크기, 타입별 passes): Task 1·2·3 ✅
- §6 게이트 일반화 + 이관 순서 + 스펙 이탈 흡수: Task 6(게이트)·2(스펙 이탈)·7(배선) ✅
- §7 데이터(eq_chamber·진짜·미끼·이중보고 회피): Task 5 ✅
- §8 데이터 흐름·도구 시그니처: Task 4(build_tools 시그니처)·7 ✅
- §9 에러 처리(YAML 위반·미지 타입·없는 컬럼): Task 4 (로더 검증). **컬럼 없음 런타임 처리**는 Task 4 도구가 engine 호출 시 SQLite 에러 → tools_node 의 기존 try/except 로 복구됨(무크래시). 명시 메시지("컬럼 X 없음")까지 원하면 Task 3 `_usage` 에 컬럼 존재 검사 추가 — **범위 내 보강 항목으로 표기**.
- §10 테스트(비교타입/판별/로더/게이트/e2e): Task 1·2·3·4·6·7 ✅
- §12 성공 기준(YAML 한 줄 → ETCH9_B, 미끼 배제, 근거 리포트): Task 7 e2e ✅

**갭/보강:**
- **컬럼 부재 명시 메시지(§9)**: 현재 tools_node try/except 로 무크래시는 되나 "컬럼 X 없음(scope Y)" 명시 메시지는 미구현. Task 3 `_usage` 첫머리에 `PRAGMA table_info` 로 컬럼 검사 후 명시 반환을 추가하면 완성. (경미 — 데모 성립엔 불필요하나 spec 명시 항목이라 Task 3 구현 시 함께 처리 권장.)
- **`_counterexamples` 의 defect_type 하드코딩(center_spot)**: 데모 성립엔 충분하나, 일반화하려면 spec 에 `defect_type` optional 또는 불량군 최빈 라벨 조회. Task 3 주석에 명시됨.
- **리포트가 "왜 미끼가 아니라 이것인지" 인용(§6)**: mock 리포트는 findings 를 그대로 나열하므로 미끼 탈락(reject_reason) 이 findings 에 남아 리포트에 노출됨 — 별도 태스크 불필요.

**2. Placeholder 스캔:** 모든 코드 스텝에 실제 코드 포함. "적절히 처리" 류 없음. ✅

**3. Type 일관성:** `evaluate`/`group_only_categorical`/`categorical_concentration`/`numeric_distribution_shift` 시그니처, Candidate 필드(`value`/`specificity`/`passes`/`effect_size`/`spec_violation_rate`/`counterexamples`/`n_group`/`n_control`/`reject_reason`), 도구 이름 `hyp_<id>`, 토큰 규칙 `value[-1]` 이 Task 1~7 에서 일관. ✅
