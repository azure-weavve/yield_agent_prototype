# 정량 근거 Tool 3종 (validate / distribution / counterexamples) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/evidence_based_analysis_roadmap.md` Phase 1 의 결정론적 분석 Tool 3종 — `validate_data_completeness`(데이터 완전성 검사), `compare_parameter_distribution`(그룹 간 파라미터 분포 비교), `find_counterexamples`(반례 탐색) — 을 구현하고 LLM tool 로 노출한다.

**Architecture:** 기존 역할 분리를 그대로 따른다 — 수치 계산은 `tools/yield_tools.py` 의 결정론적 SQL 함수, LLM 노출은 `tools/agent_tools.py` 의 `@tool` 래퍼(docstring 이 LLM 의 선택 판단 재료). 그래프/게이트/mock 스크립트는 이번 범위에서 변경하지 않는다 (EvidenceBundle 게이트는 로드맵 4번으로 별도 진행).

**Tech Stack:** Python 3.11, sqlite3, statistics(표준 라이브러리), LangChain `@tool`, pytest

## Global Constraints

- Python 3.11, 테스트는 저장소 루트(prototype/)에서 `python -m pytest` 로 실행
- 주석·docstring·테스트 이름은 기존 코드와 같은 한국어 스타일 유지
- 수술적 변경: 각 Task 의 변경 라인은 해당 기능에만 해당 (인접 코드 리팩터링 금지)
- 수치 계산에 외부 통계 라이브러리 금지 — 표준 라이브러리 `statistics` 만 사용 (p-value 는 계산하지 않는다: 표본 3장에서 과신 위험, 로드맵 명시)
- 커밋 메시지는 기존 스타일(`feat:`/`docs:` + 한국어 요약), 말미에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 각 Task 완료 시 `python -m pytest` 전체 통과 (시작 시점 44개 + 신규)

## 검증된 더미 DB 사실 (테스트 단언 근거 — seed 42 고정이라 결정론적)

- ETCH-9(Etch) 통과 wafer = 7장, 전부 defect_type='center_spot' (불량 그룹 3 + 과거 패턴 4)
- center_spot wafer 총 7장, 전부 ETCH-9 통과 → 반례 0
- ETCH-1(Etch) 통과 = 정상(none) 36장 + 타 defect 3장 → 반례 존재 케이스
- 불량 그룹(W2406_02/04/06) rf_power 전원 570.0 (스펙 450~550 상한 20% 초과), Cohen's d=3.6 으로 4개 파라미터 중 압도적 1위 (2위 0.92)

---

### Task 1: `validate_data_completeness` — 데이터 완전성 검사

분석 전제 확인 Tool. 수율 행 누락, 공정 로그 단계 누락, 중복 로그를 검사해
good / warning / blocked 상태를 반환한다. 대조 그룹 로그가 결측이면
`compare_process_logs` 의 suspect 판정(`control_count == 0`)이 허위 양성이
되므로, 이 검사가 그룹 대조의 신뢰 전제다.

**Files:**
- Modify: `tools/yield_tools.py` (파일 끝에 함수 추가)
- Modify: `tools/agent_tools.py` (`@tool` 래퍼 + `ANALYSIS_TOOLS` 등록)
- Test: `tests/test_yield_tools.py`, `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: `yield_tools._conn()` (기존 컨텍스트 매니저), `config.DB_PATH`
- Produces: `validate_data_completeness(wafer_ids: list[str]) -> dict` — 키:
  `checked_wafers`(int), `missing_yield_rows`(list[str]),
  `missing_log_steps`(list[{"wafer_id", "missing_steps"}]),
  `duplicate_logs`(list[{"wafer_id", "process_step", "param_name", "count"}]),
  `status`("good"|"warning"|"blocked"), `warnings`(list[str]).
  Task 2·3 은 이 함수에 의존하지 않는다 (독립).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_yield_tools.py` 상단 import 를 다음으로 바꾸고:

```python
"""tools/yield_tools.py 결정론적 함수 검증 (더미 DB 는 seed 42 고정)."""

import sqlite3

import config
from tools import yield_tools as yt
```

파일 끝에 추가:

```python
# ------------------------------------------------ validate_data_completeness


def _make_db(tmp_path, monkeypatch, rows, logs):
    """검사 시나리오용 임시 DB (실제 스키마와 동일). config.DB_PATH 를 바꿔치기한다."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE yield (
        wafer_id TEXT PRIMARY KEY, lot_id TEXT NOT NULL, yield REAL NOT NULL,
        defect_type TEXT NOT NULL, process_step TEXT, date TEXT NOT NULL)""")
    conn.executemany("INSERT INTO yield VALUES (?,?,?,?,?,?)", rows)
    conn.execute("""CREATE TABLE process_log (
        wafer_id TEXT NOT NULL, process_step TEXT NOT NULL, equipment_id TEXT NOT NULL,
        param_name TEXT NOT NULL, param_value REAL NOT NULL,
        spec_low REAL NOT NULL, spec_high REAL NOT NULL)""")
    conn.executemany("INSERT INTO process_log VALUES (?,?,?,?,?,?,?)", logs)
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)


def test_validate_completeness_good_on_dummy_wafers():
    res = yt.validate_data_completeness(["W2406_02", "W2406_01"])
    assert res["status"] == "good"
    assert res["checked_wafers"] == 2
    assert res["missing_yield_rows"] == []
    assert res["missing_log_steps"] == []
    assert res["duplicate_logs"] == []


def test_validate_completeness_flags_missing_wafer_as_blocked():
    res = yt.validate_data_completeness(["W2406_02", "W_NOPE"])
    assert res["status"] == "blocked"
    assert res["missing_yield_rows"] == ["W_NOPE"]
    # 전체 process_log 에 존재하는 4개 단계가 전부 누락으로 잡힌다
    assert res["missing_log_steps"] == [
        {"wafer_id": "W_NOPE", "missing_steps": ["CMP", "Diffusion", "Etch", "Photo"]}
    ]
    assert res["warnings"]


def test_validate_completeness_flags_duplicates_as_warning(tmp_path, monkeypatch):
    _make_db(
        tmp_path, monkeypatch,
        rows=[("W1", "L1", 95.0, "none", "Normal", "2024-06-01")],
        logs=[("W1", "Etch", "ETCH-1", "rf_power", 500.0, 450.0, 550.0),
              ("W1", "Etch", "ETCH-1", "rf_power", 501.0, 450.0, 550.0)],
    )
    res = yt.validate_data_completeness(["W1"])
    assert res["status"] == "warning"
    assert res["duplicate_logs"] == [
        {"wafer_id": "W1", "process_step": "Etch", "param_name": "rf_power", "count": 2}
    ]


def test_validate_completeness_empty_input_blocked():
    res = yt.validate_data_completeness([])
    assert res["status"] == "blocked"
    assert res["checked_wafers"] == 0
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_yield_tools.py -v -k validate`
Expected: FAIL 4개 — `AttributeError: module 'tools.yield_tools' has no attribute 'validate_data_completeness'`

- [ ] **Step 3: 최소 구현**

`tools/yield_tools.py` 파일 끝에 추가:

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_yield_tools.py -v -k validate`
Expected: PASS 4개

- [ ] **Step 5: `@tool` 래퍼 테스트 작성 (실패 확인 포함)**

`tests/test_agent_tools.py` 의 `test_tool_names` 기대 집합을 다음으로 교체:

```python
def test_tool_names():
    assert {t.name for t in at.ALL_TOOLS} == {
        "get_wafer", "search_similar", "aggregate_defects", "get_process_log",
        "compare_process_logs", "validate_data_completeness", "finalize",
    }
    assert "finalize" not in at.TOOLS_BY_NAME  # finalize 는 게이트가 처리
```

파일 끝에 추가:

```python
def test_validate_data_completeness_tool_invokes():
    res = at.TOOLS_BY_NAME["validate_data_completeness"].invoke(
        {"wafer_ids": ["W2406_02"]}
    )
    assert res["status"] == "good"
```

Run: `python -m pytest tests/test_agent_tools.py -v`
Expected: `test_tool_names` 와 신규 테스트 FAIL

- [ ] **Step 6: `@tool` 래퍼 구현**

`tools/agent_tools.py` 의 `compare_process_logs` 래퍼 아래(= `finalize` 위)에 추가:

```python
@tool
def validate_data_completeness(wafer_ids: list[str]) -> dict:
    """분석 대상 wafer 들의 수율 행 누락·공정 로그 단계 누락·중복 로그를 검사한다.
    그룹 대조(compare_process_logs) 전에 호출해 데이터가 결론에 쓸 만큼 완전한지 확인.
    status=blocked 면 비교 결과를 신뢰하지 말고 리포트에 품질 경고를 남겨야 한다."""
    return yt.validate_data_completeness(wafer_ids)
```

`ANALYSIS_TOOLS` 를 다음으로 교체:

```python
ANALYSIS_TOOLS = [get_wafer, search_similar, aggregate_defects, get_process_log,
                  compare_process_logs, validate_data_completeness]
```

- [ ] **Step 7: 전체 테스트 통과 확인**

Run: `python -m pytest -q`
Expected: 전체 PASS (44 + 신규 5 = 49개)

- [ ] **Step 8: Commit**

```bash
git add tools/yield_tools.py tools/agent_tools.py tests/test_yield_tools.py tests/test_agent_tools.py
git commit -m "feat: validate_data_completeness — 그룹 대조 전 데이터 완전성 검사 tool

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `compare_parameter_distribution` — 그룹 간 파라미터 분포 비교

스펙 이탈(불리언)만 보는 기존 비교를 넘어, (공정, 파라미터) 단위로 두 그룹의
기술통계·평균차·Cohen's d·스펙 이탈률을 계산한다. 스펙 안이지만 그룹 간
체계적으로 다른 파라미터를 잡을 수 있게 된다.

**Files:**
- Modify: `tools/yield_tools.py` (import 에 `statistics` 추가 + 파일 끝에 함수 추가)
- Modify: `tools/agent_tools.py` (`@tool` 래퍼 + `ANALYSIS_TOOLS` 등록)
- Test: `tests/test_yield_tools.py`, `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: `yield_tools._conn()` (기존). Task 1 과 독립 (Task 1 의 함수를 호출하지 않음).
- Produces: `compare_parameter_distribution(group_ids: list[str], control_ids: list[str], process_step: str | None = None, param_name: str | None = None) -> list[dict]` —
  행 키: `process_step`, `param_name`,
  `group`/`control`(각 `{"n", "mean", "median", "std", "min", "max"}`, 값 없으면 n=0 에 나머지 None),
  `mean_diff`(float|None), `effect_size`(Cohen's d, float|None — pooled std 0 이면 None),
  `spec_violation_rate_group`, `spec_violation_rate_control`(float).
  정렬: |effect_size| 내림차순, None 은 마지막.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_yield_tools.py` 끝에 추가:

```python
# ------------------------------------------------ compare_parameter_distribution


def test_compare_parameter_distribution_ranks_rf_power_first():
    rows = yt.compare_parameter_distribution(
        ["W2406_02", "W2406_04", "W2406_06"],
        ["W2406_01", "W2406_03", "W2406_05"],
    )
    assert len(rows) == 4                        # 4개 (공정, 파라미터) 전부
    top = rows[0]                                # |effect_size| 1위 = rf_power (d=3.6)
    assert (top["process_step"], top["param_name"]) == ("Etch", "rf_power")
    assert top["group"]["n"] == 3 and top["control"]["n"] == 3
    assert top["group"]["mean"] == 570.0         # 스펙 상한 20% 초과 고정값
    assert top["group"]["std"] == 0.0            # 3장 전부 동일값
    assert top["mean_diff"] > 0 and top["effect_size"] > 2.0
    assert top["spec_violation_rate_group"] == 1.0
    assert top["spec_violation_rate_control"] == 0.0


def test_compare_parameter_distribution_filters_by_step():
    rows = yt.compare_parameter_distribution(
        ["W2406_02", "W2406_04", "W2406_06"],
        ["W2406_01", "W2406_03", "W2406_05"],
        process_step="Etch",
    )
    assert [(r["process_step"], r["param_name"]) for r in rows] == [("Etch", "rf_power")]


def test_compare_parameter_distribution_one_sided_group():
    # 대조 그룹이 비어도 죽지 않는다 — 통계는 그룹 쪽만, 비교치는 None
    rows = yt.compare_parameter_distribution(["W2406_02"], [])
    assert all(r["control"]["n"] == 0 for r in rows)
    assert all(r["mean_diff"] is None and r["effect_size"] is None for r in rows)


def test_compare_parameter_distribution_empty_inputs():
    assert yt.compare_parameter_distribution([], []) == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_yield_tools.py -v -k distribution`
Expected: FAIL 4개 — `AttributeError: ... has no attribute 'compare_parameter_distribution'`

- [ ] **Step 3: 최소 구현**

`tools/yield_tools.py` 상단 import 블록에 추가 (`import sqlite3` 아래):

```python
import statistics
```

파일 끝에 추가:

```python
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
        violations = sum(
            1 for r in rows
            if not (r["spec_low"] <= r["param_value"] <= r["spec_high"]))
        return ({
            "n": len(values),
            "mean": round(statistics.fmean(values), 3),
            "median": round(statistics.median(values), 3),
            "std": round(statistics.stdev(values), 3) if len(values) >= 2 else 0.0,
            "min": min(values),
            "max": max(values),
        }, round(violations / len(values), 3))

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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_yield_tools.py -v -k distribution`
Expected: PASS 4개

- [ ] **Step 5: `@tool` 래퍼 테스트 작성 (실패 확인 포함)**

`tests/test_agent_tools.py` 의 `test_tool_names` 기대 집합을 다음으로 교체:

```python
def test_tool_names():
    assert {t.name for t in at.ALL_TOOLS} == {
        "get_wafer", "search_similar", "aggregate_defects", "get_process_log",
        "compare_process_logs", "validate_data_completeness",
        "compare_parameter_distribution", "finalize",
    }
    assert "finalize" not in at.TOOLS_BY_NAME  # finalize 는 게이트가 처리
```

파일 끝에 추가:

```python
def test_compare_parameter_distribution_tool_invokes():
    rows = at.TOOLS_BY_NAME["compare_parameter_distribution"].invoke({
        "group_ids": ["W2406_02", "W2406_04", "W2406_06"],
        "control_ids": ["W2406_01", "W2406_03", "W2406_05"],
    })
    assert rows[0]["param_name"] == "rf_power"
```

Run: `python -m pytest tests/test_agent_tools.py -v`
Expected: `test_tool_names` 와 신규 테스트 FAIL

- [ ] **Step 6: `@tool` 래퍼 구현**

`tools/agent_tools.py` 의 `validate_data_completeness` 래퍼 아래에 추가:

```python
@tool
def compare_parameter_distribution(group_ids: list[str], control_ids: list[str],
                                   process_step: str | None = None,
                                   param_name: str | None = None) -> list[dict]:
    """불량 그룹과 대조 그룹의 공정 파라미터 분포(표본 수·평균·표준편차·효과 크기·
    스펙 이탈률)를 (공정, 파라미터) 단위로 비교한다. compare_process_logs 가 지목한
    후보의 정량 검증, 또는 스펙 이탈이 없어도 그룹 간 차이를 찾을 때 사용.
    process_step/param_name 으로 범위를 좁힐 수 있다."""
    return yt.compare_parameter_distribution(group_ids, control_ids,
                                             process_step, param_name)
```

`ANALYSIS_TOOLS` 를 다음으로 교체:

```python
ANALYSIS_TOOLS = [get_wafer, search_similar, aggregate_defects, get_process_log,
                  compare_process_logs, validate_data_completeness,
                  compare_parameter_distribution]
```

- [ ] **Step 7: 전체 테스트 통과 확인**

Run: `python -m pytest -q`
Expected: 전체 PASS (49 + 신규 5 = 54개)

- [ ] **Step 8: Commit**

```bash
git add tools/yield_tools.py tools/agent_tools.py tests/test_yield_tools.py tests/test_agent_tools.py
git commit -m "feat: compare_parameter_distribution — 그룹 간 파라미터 분포·효과 크기 비교 tool

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `find_counterexamples` — 반례 탐색

가설 "(공정, 장비)가 defect 의 원인"에 반하는 사례를 전수 데이터에서 명시적으로
찾는다: 해당 장비를 거쳤지만 정상인 wafer, 장비 없이 같은 defect 가 난 wafer.
반례 0 이면 특이성이 전수 확인된 것 — 확증 편향 방지가 목적.

**Files:**
- Modify: `tools/yield_tools.py` (파일 끝에 함수 추가)
- Modify: `tools/agent_tools.py` (`@tool` 래퍼 + `ANALYSIS_TOOLS` 등록)
- Test: `tests/test_yield_tools.py`, `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: `yield_tools._conn()` (기존). Task 1·2 와 독립.
- Produces: `find_counterexamples(equipment_id: str, process_step: str, defect_type: str) -> dict` — 키:
  `equipment_id`, `process_step`, `defect_type`(입력 반향),
  `equipment_wafers`(int, 해당 장비 통과 총수),
  `passed_but_normal`(list[{"wafer_id", "yield", "in_spec"}]),
  `passed_but_normal_rate`(float, 통과자 중 정상 비율 — 통과자 0 이면 0.0),
  `defect_wafers`(int, 해당 defect 총수),
  `defect_without_equipment`(list[{"wafer_id", "yield"}]),
  `defect_without_equipment_rate`(float — defect 0 이면 0.0)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_yield_tools.py` 끝에 추가:

```python
# ------------------------------------------------ find_counterexamples


def test_find_counterexamples_zero_for_etch9_hypothesis():
    # 더미 DB 사실: ETCH-9 통과 7장 전부 center_spot, center_spot 7장 전부 ETCH-9
    res = yt.find_counterexamples("ETCH-9", "Etch", "center_spot")
    assert res["equipment_wafers"] == 7
    assert res["passed_but_normal"] == []
    assert res["passed_but_normal_rate"] == 0.0
    assert res["defect_wafers"] == 7
    assert res["defect_without_equipment"] == []
    assert res["defect_without_equipment_rate"] == 0.0


def test_find_counterexamples_found_for_normal_equipment():
    # ETCH-1 통과자는 대부분 정상 → 'ETCH-1 이 원인' 가설이면 반례가 다수 잡힌다
    res = yt.find_counterexamples("ETCH-1", "Etch", "center_spot")
    assert res["passed_but_normal"]
    assert 0.0 < res["passed_but_normal_rate"] <= 1.0
    assert all(r["in_spec"] for r in res["passed_but_normal"])
    # center_spot 은 전부 ETCH-9 를 거쳤으므로 'ETCH-1 없이 발생' 비율 100%
    assert res["defect_without_equipment_rate"] == 1.0


def test_find_counterexamples_unknown_equipment():
    res = yt.find_counterexamples("ETCH-99", "Etch", "center_spot")
    assert res["equipment_wafers"] == 0
    assert res["passed_but_normal_rate"] == 0.0
    assert res["defect_without_equipment_rate"] == 1.0
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_yield_tools.py -v -k counterexample`
Expected: FAIL 3개 — `AttributeError: ... has no attribute 'find_counterexamples'`

- [ ] **Step 3: 최소 구현**

`tools/yield_tools.py` 파일 끝에 추가:

```python
def find_counterexamples(equipment_id: str, process_step: str,
                         defect_type: str) -> dict:
    """가설 '(process_step, equipment_id) 가 defect_type 의 원인'의 반례 탐색.

    전수 데이터에서 명시적으로 찾는다 (확증 편향 방지 — 결정론적):
    - passed_but_normal: 해당 장비를 거쳤지만 정상(defect 'none')인 wafer
    - defect_without_equipment: 해당 장비 없이 같은 defect 가 난 wafer
    두 목록이 모두 비면 가설의 특이성이 전수 데이터에서 확인된 것이다.
    """
    with _conn() as conn:
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

    user_ids = {u["wafer_id"] for u in users}
    passed_but_normal = [
        {"wafer_id": u["wafer_id"], "yield": u["yield"],
         "in_spec": bool(u["spec_low"] <= u["param_value"] <= u["spec_high"])}
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_yield_tools.py -v -k counterexample`
Expected: PASS 3개

- [ ] **Step 5: `@tool` 래퍼 테스트 작성 (실패 확인 포함)**

`tests/test_agent_tools.py` 의 `test_tool_names` 기대 집합을 다음으로 교체:

```python
def test_tool_names():
    assert {t.name for t in at.ALL_TOOLS} == {
        "get_wafer", "search_similar", "aggregate_defects", "get_process_log",
        "compare_process_logs", "validate_data_completeness",
        "compare_parameter_distribution", "find_counterexamples", "finalize",
    }
    assert "finalize" not in at.TOOLS_BY_NAME  # finalize 는 게이트가 처리
```

파일 끝에 추가:

```python
def test_find_counterexamples_tool_invokes():
    res = at.TOOLS_BY_NAME["find_counterexamples"].invoke({
        "equipment_id": "ETCH-9", "process_step": "Etch",
        "defect_type": "center_spot",
    })
    assert res["passed_but_normal"] == []
```

Run: `python -m pytest tests/test_agent_tools.py -v`
Expected: `test_tool_names` 와 신규 테스트 FAIL

- [ ] **Step 6: `@tool` 래퍼 구현**

`tools/agent_tools.py` 의 `compare_parameter_distribution` 래퍼 아래에 추가:

```python
@tool
def find_counterexamples(equipment_id: str, process_step: str,
                         defect_type: str) -> dict:
    """가설 '(공정, 장비)가 defect 의 원인'에 반하는 사례를 전수 데이터에서 찾는다:
    해당 장비를 거쳤지만 정상인 wafer, 장비 없이 같은 defect 가 난 wafer.
    finalize 전에 호출해 가설의 특이성(반례 유무)을 확인하고 리포트에 인용."""
    return yt.find_counterexamples(equipment_id, process_step, defect_type)
```

`ANALYSIS_TOOLS` 를 다음으로 교체:

```python
ANALYSIS_TOOLS = [get_wafer, search_similar, aggregate_defects, get_process_log,
                  compare_process_logs, validate_data_completeness,
                  compare_parameter_distribution, find_counterexamples]
```

- [ ] **Step 7: 전체 테스트 통과 확인**

Run: `python -m pytest -q`
Expected: 전체 PASS (54 + 신규 4 = 58개)

- [ ] **Step 8: Commit**

```bash
git add tools/yield_tools.py tools/agent_tools.py tests/test_yield_tools.py tests/test_agent_tools.py
git commit -m "feat: find_counterexamples — 가설 반례 전수 탐색 tool (확증 편향 방지)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 문서 동기화 (README tool 목록 + 로드맵 진행 표시)

**Files:**
- Modify: `README.md` (분석 루프 절의 tool 설명에 신규 3종 추가 — `compare_process_logs` 항목 아래)
- Modify: `docs/evidence_based_analysis_roadmap.md` ("첫 구현 권장 순서" 절에 1~3번 완료 표시)

**Interfaces:**
- Consumes: Task 1~3 이 만든 tool 이름·동작 (문서가 코드 현실과 일치해야 함)
- Produces: 없음 (문서만)

- [ ] **Step 1: README 분석 루프 절에 신규 tool 3종 추가**

`README.md` 의 `- **compare_process_logs**: ...` 항목(95행 부근) 바로 아래에 추가:

```markdown
- **validate_data_completeness**: 그룹 대조 전에 수율 행·공정 로그의 누락과 중복을
  검사합니다. blocked 면 비교 결과를 신뢰하지 않습니다 (허위 suspect 방지).
- **compare_parameter_distribution**: 두 그룹의 파라미터 분포(평균·표준편차·효과 크기·
  스펙 이탈률)를 비교합니다 — 스펙 안이어도 그룹 간 체계적 차이를 잡습니다.
- **find_counterexamples**: 가설에 반하는 사례(장비를 거친 정상 wafer, 장비 없이 난
  동일 불량)를 전수 데이터에서 찾아 가설의 특이성을 확인합니다.
```

또한 92행 부근의 `` `get_process_log`, `compare_process_logs`, `finalize` 등의 tool 을 자율적으로 호출합니다. `` 문장은 그대로 둔다 ("등"이 신규 tool 을 포함).

- [ ] **Step 2: 로드맵에 진행 표시**

`docs/evidence_based_analysis_roadmap.md` 의 "첫 구현 권장 순서" 절 목록(1~3번)을 다음으로 교체:

```markdown
1. ~~`validate_data_completeness`~~ (2026-07-13 구현 완료)
2. ~~`compare_parameter_distribution`~~ (2026-07-13 구현 완료)
3. ~~`find_counterexamples`~~ (2026-07-13 구현 완료)
```

- [ ] **Step 3: 전체 테스트 통과 확인**

Run: `python -m pytest -q`
Expected: 전체 PASS (문서만 변경이므로 회귀 없음)

- [ ] **Step 4: Commit**

```bash
git add README.md docs/evidence_based_analysis_roadmap.md
git commit -m "docs: 정량 근거 tool 3종을 README·로드맵에 반영

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## 범위 밖 (의도적 미룸)

- **EvidenceBundle / evidence score 게이트** (로드맵 4번): 이 3종 tool 의 출력을 조립하는 후속 작업.
- **mock 스크립트에 신규 tool 데모 추가**: `ScriptedMockLLMClient` 의 시나리오가 현재 5턴으로 MAX_LOOPS(6) 경계에 가까워, 턴 추가는 e2e·README 출력 연쇄 수정이 필요. 별도 작업으로 분리.
- **더미 데이터에 결측·스펙 내 이상 시나리오 추가**: 로드맵 평가셋 요구와 함께 진행.
