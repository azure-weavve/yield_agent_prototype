# 그룹 대조 분석 (불량 그룹 vs 정상 그룹) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분석 대상을 "wafer 1장"에서 "유사 불량 wafer 그룹 vs 같은 lot 정상 wafer 대조 그룹"으로 확장해, 엔지니어의 실제 분석 방식(그룹 대조로 원인 공정/장비 특정)을 재현한다.

**Architecture:** 그래프 골격(status → analyze⇄tools → report)은 그대로 둔다. status 노드(고정 골격)가 결정론적 규칙(defect_type 일치)으로 불량/대조 그룹을 묶고, 새 tool `compare_process_logs` 가 두 그룹의 공정 로그를 수치로 대조한다. LLM 은 여전히 "어떤 분석을 할지"만 판단하고, 그룹 판정과 비교 수치는 전부 코드가 계산한다.

**Tech Stack:** Python, LangGraph, SQLite, hnswlib (기존과 동일 — 신규 의존성 없음)

## Global Constraints

- 그룹 판정 기준은 **defect_type 일치** (사용자 승인). 임베딩 클러스터링은 쓰지 않는다.
- 수치는 tool(`tools/yield_tools.py`)에서만 나온다. LLM/mock 은 tool 결과를 인용만 한다.
- `config.MAX_LOOPS = 6`, `config.CONFIDENCE_THRESHOLD = 0.8`, `config.YIELD_THRESHOLD = 90.0`, `SEED = 42` 는 변경 금지.
- 상태 키는 `target_wafer: str` 를 **제거**하고 `target_group: list[str]` / `control_group: list[str]` 로 대체한다 (하위 호환 별칭 금지 — 단일 소스).
- 더미 데이터의 그룹 대조 무대: `LOT2406` 에 불량 그룹 `W2406_02, W2406_04, W2406_06` (defect `center_spot`, 원인 장비 `ETCH-9`) + 대조 그룹 `W2406_01, W2406_03, W2406_05` (defect `none`). 불량 그룹 수율은 `uniform(76.0, 82.0)`, 대조 그룹은 `uniform(93.0, 97.0)` — 이 범위여야 lot 평균이 어떤 난수에서도 90 미만으로 보장된다((82+97)/2 = 89.5).
- 주석·문서·커밋 메시지는 기존 스타일대로 한국어. 커밋 prefix 는 `feat:`/`fix:`/`docs:`/`test:`.
- 각 Task 종료 시 `python -m pytest tests/ -q` 전체 green 이어야 한다.
- Windows 콘솔에서 데모 실행 시 `PYTHONUTF8=1` 환경 변수 필요 (PowerShell: `$env:PYTHONUTF8="1"; python main.py`).

## File Structure

- `data/generate_dummy.py` — 수정: LOT2406 을 그룹 대조 시나리오로 재구성 (Task 1)
- `tools/yield_tools.py` — 수정: `find_defect_group`, `compare_process_logs` 추가 (Task 2)
- `tools/agent_tools.py` — 수정: `compare_process_logs` @tool 래퍼 추가 (Task 3)
- `graph/state.py`, `graph/build.py`, `graph/nodes.py`, `llm/client.py`, `main.py` — 수정: 그룹 전환 통합 (Task 4)
- 테스트: `tests/test_dummy_data.py`, `tests/test_yield_tools.py`, `tests/test_agent_tools.py`, `tests/test_graph_nodes.py`, `tests/test_build.py`, `tests/test_mock_llm.py`, `tests/test_e2e.py`
- 변경 없음: `config.py`, `tools/eds_search.py`, `tests/test_eds_search.py`, `tests/test_state.py`, `graph/state.py` 의 누적 reducer 구조

---

### Task 1: 더미 데이터 재구성 — LOT2406 그룹 대조 시나리오

`LOT2406` 을 "불량 그룹 3장(짝수 번호, center_spot, ETCH-9 공유) + 대조 그룹 3장(홀수 번호, 정상)"으로 재구성한다. 기존 4개 패턴 그룹은 전부 과거 wafer 로 남겨 `search_similar` 의 유사 사례 풀을 유지하고, center_spot 그룹은 불량 그룹과 같은 임베딩 중심을 공유한다. **이 Task 는 기존 단일-wafer 흐름과 하위 호환이다** (worst wafer 가 여전히 `W2406_` 으로 시작하고 ETCH-9 스펙 이탈을 가지므로 기존 e2e 가 계속 통과한다).

**Files:**
- Modify: `data/generate_dummy.py`
- Modify: `tests/test_dummy_data.py`, `tests/test_yield_tools.py`, `tests/test_agent_tools.py`, `tests/test_graph_nodes.py` (사라지는 wafer id `W2406_cen0` → `W2406_02` 교체)
- 재생성 산출물: `data/yield.db`, `data/embeddings/index.bin`, `data/embeddings/labels.json` (git 추적 중 — 함께 커밋)

**Interfaces:**
- Produces: DB 에 `LOT2406` = {`W2406_01`(none), `W2406_02`(center_spot), `W2406_03`(none), `W2406_04`(center_spot), `W2406_05`(none), `W2406_06`(center_spot)}. 불량 3장은 수율 76~82 + Etch 단계 `ETCH-9` 스펙 초과, 정상 3장은 수율 93~97 + 전 공정 스펙 내. Task 2~4 의 테스트가 이 wafer id 들을 그대로 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성 — LOT2406 그룹 구성 검증**

`tests/test_dummy_data.py` 상단 import 에 `config` 는 이미 있다. 파일 끝에 추가:

```python
def test_recent_lot_has_group_and_control():
    """그룹 대조 시나리오: LOT2406 = 불량 그룹(짝수, center_spot) + 대조 그룹(홀수, 정상)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT wafer_id, yield, defect_type FROM yield WHERE lot_id = 'LOT2406' ORDER BY wafer_id"
        ).fetchall()
        by_id = {r["wafer_id"]: r for r in rows}
        assert set(by_id) == {
            "W2406_01", "W2406_02", "W2406_03", "W2406_04", "W2406_05", "W2406_06",
        }
        for wid in ("W2406_02", "W2406_04", "W2406_06"):
            assert by_id[wid]["defect_type"] == "center_spot"
            assert by_id[wid]["yield"] < config.YIELD_THRESHOLD
        for wid in ("W2406_01", "W2406_03", "W2406_05"):
            assert by_id[wid]["defect_type"] == "none"
            assert by_id[wid]["yield"] >= config.YIELD_THRESHOLD
        # lot 평균이 임계 미만이어야 시나리오 1(find_low_yield_lots)에 잡힌다
        avg = sum(r["yield"] for r in rows) / len(rows)
        assert avg < config.YIELD_THRESHOLD
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_dummy_data.py::test_recent_lot_has_group_and_control -q`
Expected: FAIL (`W2406_01` 등이 존재하지 않음)

- [ ] **Step 3: `data/generate_dummy.py` 수정**

(a) 모듈 상수 — 기존 `PATTERN_GROUPS` 정의(36~41행)를 아래로 교체:

```python
# 그룹 대조 시나리오 (RECENT_LOT): 짝수 번호 3장이 같은 불량(불량 그룹),
# 홀수 번호 3장은 정상(대조 그룹) — "유사 불량을 묶어 정상과 대조"의 데모 무대.
# 수율 범위는 lot 평균 < YIELD_THRESHOLD(90) 를 난수와 무관하게 보장한다: (82+97)/2 = 89.5.
FEATURED_DEFECT = "center_spot"
FEATURED_PROCESS = "Etch"
GROUP_WAFERS = ["W2406_02", "W2406_04", "W2406_06"]    # 불량 그룹 (수율 낮음)
CONTROL_WAFERS = ["W2406_01", "W2406_03", "W2406_05"]  # 대조 그룹 (정상)

# 패턴 그룹: 전부 과거 wafer — search_similar 의 유사 사례 풀.
# center_spot 그룹은 GROUP_WAFERS 와 같은 임베딩 중심을 공유한다.
PATTERN_GROUPS = [
    {"defect": "edge_ring", "process": "Diffusion", "n_past": 5},
    {"defect": "center_spot", "process": "Etch", "n_past": 4},
    {"defect": "scratch", "process": "CMP", "n_past": 4},
    {"defect": "donut", "process": "Photo", "n_past": 4},
]
```

(b) `generate()` — 기존 "패턴 그룹: … 최근 1 + 과거 n" 블록(97~129행) 전체를 아래로 교체:

```python
    # ---------------- 그룹 대조 시나리오: 불량 그룹 3장 + 대조 그룹 3장 (RECENT_LOT)
    centers = {g["defect"]: _unit(rng.standard_normal(DIM)) for g in PATTERN_GROUPS}

    for wid in GROUP_WAFERS:
        rows.append({
            "wafer_id": wid,
            "lot_id": RECENT_LOT,
            "yield": round(float(rng.uniform(76.0, 82.0)), 1),
            "defect_type": FEATURED_DEFECT,
            "process_step": FEATURED_PROCESS,
            "date": RECENT_DATE,
        })
        vectors.append(_make_member(centers[FEATURED_DEFECT], rng))
        wafer_ids.append(wid)

    for wid in CONTROL_WAFERS:
        rows.append({
            "wafer_id": wid,
            "lot_id": RECENT_LOT,
            "yield": round(float(rng.uniform(93.0, 97.0)), 1),
            "defect_type": "none",
            "process_step": "Normal",
            "date": RECENT_DATE,
        })
        vectors.append(_unit(rng.standard_normal(DIM)))
        wafer_ids.append(wid)

    # ---------------- 패턴 그룹 (과거 유사 사례): 그룹 중심 + noise, 같은 defect 공유
    for g_idx, grp in enumerate(PATTERN_GROUPS):
        center = centers[grp["defect"]]
        tag = grp["defect"][:3]                   # wafer_id 가독성용 접두
        for p in range(grp["n_past"]):
            past_wid = f"W24{g_idx}{p}_{tag}{p + 1}"
            rows.append({
                "wafer_id": past_wid,
                "lot_id": NORMAL_LOTS[(g_idx + p) % len(NORMAL_LOTS)],
                "yield": round(float(rng.uniform(85.0, 92.0)), 1),
                "defect_type": grp["defect"],
                "process_step": grp["process"],
                "date": PAST_DATES[p % len(PAST_DATES)],
            })
            vectors.append(_make_member(center, rng))
            wafer_ids.append(past_wid)
```

(c) 모듈 docstring 의 "핵심 = 유사 그룹 심기" 문단 끝에 한 줄 추가:

```
  추가로 RECENT_LOT 은 그룹 대조 시나리오 무대다: 짝수 번호 3장이 같은
  defect(center_spot)·같은 이상 장비(ETCH-9)를 공유하고, 홀수 번호 3장은 정상.
```

(d) `_report()` — 마지막 블록(228~231행)을 아래로 교체:

```python
    print(f"\n[{RECENT_LOT} 그룹 대조 시나리오]")
    for r in rows:
        if r["lot_id"] == RECENT_LOT:
            print(f"  {r['wafer_id']}  yield={r['yield']}  defect={r['defect_type']}")
```

- [ ] **Step 4: 데이터 재생성**

Run: `python data/generate_dummy.py`
Expected: 총 wafer 103장 (정상 80 + LOT2406 6 + 과거 패턴 17), "[lot 평균 수율 낮은 순 상위 3]" 에 LOT2406 이 1위(평균 < 90), "[LOT2406 그룹 대조 시나리오]" 에 6장 출력.

- [ ] **Step 5: 사라진 wafer id 참조 교체 (`W2406_cen0` → `W2406_02`)**

각 파일에서 문자열 `W2406_cen0` 을 `W2406_02` 로 교체:
- `tests/test_dummy_data.py` — `test_pattern_wafer_has_single_anomaly_at_its_step` 의 쿼리와 주석 (주석 "center_spot 그룹 최근 wafer" → "불량 그룹 wafer")
- `tests/test_yield_tools.py` — `test_get_process_log_returns_4_steps_with_in_spec`, `test_pattern_wafer_anomaly_flagged`
- `tests/test_agent_tools.py` — `test_get_process_log_tool_invokes`, `test_aggregate_defects_tool_invokes`
- `tests/test_graph_nodes.py` — `test_tools_node_executes_and_records_finding` 의 args

(`tests/test_mock_llm.py` 의 `W2406_cen0` 은 DB 를 조회하지 않는 가짜 id 이므로 이 Task 에서는 건드리지 않는다 — Task 4 에서 파일 전체가 재작성된다.)

- [ ] **Step 6: 전체 테스트 통과 확인**

Run: `python -m pytest tests/ -q`
Expected: 전체 PASS (기존 e2e 포함 — worst wafer 가 `W2406_` 으로 시작하고 ETCH-9 이탈을 가지므로 단일-wafer 흐름이 그대로 성립한다)

- [ ] **Step 7: Commit**

```bash
git add data/generate_dummy.py data/yield.db data/embeddings/ tests/test_dummy_data.py tests/test_yield_tools.py tests/test_agent_tools.py tests/test_graph_nodes.py
git commit -m "feat: 더미 데이터를 그룹 대조 시나리오(LOT2406 불량 3 + 정상 3)로 재구성"
```

---

### Task 2: yield_tools — find_defect_group + compare_process_logs

그룹 대조 분석의 결정론적 수치 계산 2개를 추가한다. LLM 이 끼어들지 않는 영역.

**Files:**
- Modify: `tools/yield_tools.py` (파일 끝에 함수 2개 추가)
- Test: `tests/test_yield_tools.py`

**Interfaces:**
- Produces: `find_defect_group(lot_id: str, threshold: float = config.YIELD_THRESHOLD) -> dict` — 반환 `{"lot_id": str, "defect_type": str, "target_group": list[str], "control_group": list[str]}`. 그룹 없으면 `defect_type=""`, `target_group=[]`.
- Produces: `compare_process_logs(group_ids: list[str], control_ids: list[str]) -> dict` — 반환 `{"suspect_equipment": list[dict], "equipment_usage": list[dict], "group_spec_violations": list[dict]}`. usage 행은 `{"process_step", "equipment_id", "group_count", "control_count"}`, violation 행은 `{"wafer_id", "process_step", "equipment_id", "param_name", "param_value", "spec_low", "spec_high"}`.
- Task 3 의 @tool 래퍼와 Task 4 의 status_node/mock 이 이 시그니처를 그대로 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_yield_tools.py` 끝에 추가:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_yield_tools.py -q`
Expected: 신규 4건 FAIL (`AttributeError: ... has no attribute 'find_defect_group'`)

- [ ] **Step 3: 구현**

`tools/yield_tools.py` 끝에 추가:

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_yield_tools.py -q`
Expected: 전체 PASS

- [ ] **Step 5: Commit**

```bash
git add tools/yield_tools.py tests/test_yield_tools.py
git commit -m "feat: 그룹 대조 수치 계산 추가 (find_defect_group, compare_process_logs)"
```

---

### Task 3: agent_tools — compare_process_logs @tool 래퍼

LLM 이 호출할 수 있도록 tool 로 노출한다. docstring 이 곧 LLM 의 tool 선택 판단 재료다.

**Files:**
- Modify: `tools/agent_tools.py`
- Test: `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: `yt.compare_process_logs(group_ids, control_ids)` (Task 2)
- Produces: `ANALYSIS_TOOLS` / `TOOLS_BY_NAME` 에 `compare_process_logs` 포함 — Task 4 의 tools 노드가 이름으로 실행하고, mock 이 이 이름으로 tool call 을 낸다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent_tools.py` 의 `test_tool_names` 기대 집합에 `"compare_process_logs"` 를 추가하고, 파일 끝에 추가:

```python
def test_compare_process_logs_tool_invokes():
    res = at.TOOLS_BY_NAME["compare_process_logs"].invoke({
        "group_ids": ["W2406_02", "W2406_04", "W2406_06"],
        "control_ids": ["W2406_01", "W2406_03", "W2406_05"],
    })
    assert any(r["equipment_id"] == "ETCH-9" for r in res["suspect_equipment"])
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_agent_tools.py -q`
Expected: `test_tool_names`, `test_compare_process_logs_tool_invokes` FAIL

- [ ] **Step 3: 구현**

`tools/agent_tools.py` 의 `get_process_log` 정의 다음에 추가:

```python
@tool
def compare_process_logs(group_ids: list[str], control_ids: list[str]) -> dict:
    """불량 그룹과 대조 그룹(정상 wafer)의 공정 로그를 대조해, 불량 그룹만
    공통으로 거친 장비(suspect_equipment)와 불량 그룹의 스펙 이탈
    (group_spec_violations)을 찾는다. 그룹 간 차이로 원인 공정/장비를 좁힐 때 사용."""
    return yt.compare_process_logs(group_ids, control_ids)
```

그리고 `ANALYSIS_TOOLS` 를 갱신:

```python
ANALYSIS_TOOLS = [get_wafer, search_similar, aggregate_defects, get_process_log,
                  compare_process_logs]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_agent_tools.py -q`
Expected: 전체 PASS

- [ ] **Step 5: Commit**

```bash
git add tools/agent_tools.py tests/test_agent_tools.py
git commit -m "feat: compare_process_logs 를 분석 tool 로 노출"
```

---

### Task 4: 그룹 전환 통합 — state/build/nodes/llm/main + e2e

상태·그래프·프롬프트·mock·출력을 단일 wafer 에서 그룹으로 한 번에 전환한다 (인터페이스 플립이라 쪼갤 수 없다). 완료 시 데모가 그룹 대조 흐름으로 완주한다.

**Files:**
- Modify: `graph/state.py`, `graph/build.py`, `graph/nodes.py`, `llm/client.py`, `main.py`
- Test: `tests/test_graph_nodes.py`, `tests/test_build.py`, `tests/test_mock_llm.py`, `tests/test_e2e.py`

**Interfaces:**
- Consumes: `yt.find_defect_group` (Task 2), `TOOLS_BY_NAME["compare_process_logs"]` (Task 3), 더미 데이터의 LOT2406 그룹 (Task 1)
- Produces: 상태 키 `target_group: list[str]`, `control_group: list[str]` (`target_wafer` 제거). `LLMClient.generate_report(question, target_group: list[str], status_summary, findings, hypothesis, confidence)`. mock 시나리오: `aggregate_defects → finalize(0.6, 반려) → compare_process_logs → finalize(0.9, 승인)`.

- [ ] **Step 1: 실패하는 테스트 작성 — 4개 테스트 파일 갱신**

(a) `tests/test_graph_nodes.py` — `test_status_node_sets_target_and_seed_messages` 를 교체하고 `test_report_node_produces_report` 의 인자를 바꾼다:

```python
def test_status_node_sets_groups_and_seed_messages():
    out = nodes.status_node({"question": "원인 분석해줘"})
    assert out["target_group"] == ["W2406_02", "W2406_04", "W2406_06"]
    assert out["control_group"] == ["W2406_01", "W2406_03", "W2406_05"]
    assert "불량 그룹 (center_spot)" in out["messages"][-1].content
    assert "대조 그룹 (정상)" in out["messages"][-1].content
    assert out["findings"][0]["loop"] == 0                   # 현황파악도 감사 기록에 남는다
    assert out["findings"][0]["tool"] == "find_low_yield_lots"
    assert out["findings"][1]["tool"] == "find_defect_group"  # 그룹 묶기도 감사 기록에
```

`test_report_node_produces_report` 는 `"target_wafer": "W2406_cen0"` 를 `"target_group": ["W2406_02", "W2406_04", "W2406_06"]` 로 교체 (나머지 동일).

(b) `tests/test_build.py` — import 에 `_after_status` 를 추가하고 파일 끝에 추가:

```python
def test_status_with_group_goes_analyze():
    assert _after_status({"target_group": ["W2406_02"]}) == "analyze"


def test_status_without_group_goes_report():
    # 이상 lot 이 없거나 defect 그룹을 못 묶으면 분석 루프를 건너뛴다
    assert _after_status({"target_group": []}) == "report"
```

(c) `tests/test_mock_llm.py` — 파일 전체를 아래로 교체:

```python
"""ScriptedMockLLMClient: 그룹 대조 시나리오 순서·파싱·finalize 인자 검증.

mock 은 tools 노드가 만들 ToolMessage(name=..., content=json)를 보고
다음 tool 을 결정한다 — 여기서는 그 ToolMessage 를 손으로 만들어 단계를 진행시킨다.
"""

import json

from langchain_core.messages import HumanMessage, ToolMessage

from llm.client import ScriptedMockLLMClient

HUMAN = HumanMessage(
    "현황: ...\n\n불량 그룹 (center_spot): W2406_02, W2406_04, W2406_06\n"
    "대조 그룹 (정상): W2406_01, W2406_03, W2406_05\n질문: 원인 분석해줘"
)
TARGET = ["W2406_02", "W2406_04", "W2406_06"]
CONTROL = ["W2406_01", "W2406_03", "W2406_05"]


def _tm(name, payload):
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ToolMessage(content, tool_call_id=f"call_{name}", name=name)


def test_scripted_sequence():
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]

    # 1) 불량 그룹의 defect 공유 확인부터
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "aggregate_defects"
    assert ai.tool_calls[0]["args"]["wafer_ids"] == TARGET
    assert ai.content  # thought(가설 서술)가 감사 기록 재료로 반드시 존재
    msgs += [ai, _tm("aggregate_defects", [{"defect_type": "center_spot", "count": 3}])]

    # 2) 조기 finalize (낮은 확신도 → 게이트 반려 시연용)
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] < 0.8
    msgs += [ai, _tm("finalize", "반려: 확신도 0.60 < 0.8. 근거를 좁힐 tool 을 더 호출하라.")]

    # 3) 그룹 대조로 원인 공정/장비를 좁힌다
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "compare_process_logs"
    assert ai.tool_calls[0]["args"] == {"group_ids": TARGET, "control_ids": CONTROL}
    msgs += [ai, _tm("compare_process_logs", {
        "suspect_equipment": [{"process_step": "Etch", "equipment_id": "ETCH-9",
                               "group_count": 3, "control_count": 0}],
        "equipment_usage": [],
        "group_spec_violations": [
            {"wafer_id": w, "process_step": "Etch", "equipment_id": "ETCH-9",
             "param_name": "rf_power", "param_value": 570.0,
             "spec_low": 450.0, "spec_high": 550.0}
            for w in TARGET
        ],
    })]

    # 4) 최종 finalize — 스펙 이탈 장비를 가설에 명시
    ai = llm.analyze_step(msgs)
    call = ai.tool_calls[0]
    assert call["name"] == "finalize"
    assert call["args"]["confidence"] >= 0.8
    assert "ETCH-9" in call["args"]["hypothesis"]


def test_generate_report_contains_findings_and_conclusion():
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        question="원인 분석해줘",
        target_group=TARGET,
        status_summary="LOT2406 평균 84.8",
        findings=[{"loop": 1, "tool": "aggregate_defects", "args": {"wafer_ids": TARGET},
                   "result": [], "thought": "불량 유형 공유 확인"}],
        hypothesis="Etch 공정 ETCH-9 장비 rf_power 스펙 이탈이 원인",
        confidence=0.9,
    )
    assert "W2406_02" in report
    assert "aggregate_defects" in report
    assert "ETCH-9" in report


def test_generate_report_handles_no_hypothesis():
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        question="q", target_group=["W1"], status_summary="s",
        findings=[], hypothesis=None, confidence=None,
    )
    assert "미확정" in report
```

(d) `tests/test_e2e.py` — 파일 전체를 아래로 교체:

```python
"""End-to-End: mock 그룹 대조 루프가 현황→순환(반려 포함)→승인→리포트까지 완주하는지."""

from graph.build import build_graph


def test_full_loop_reaches_report_with_audit_trail():
    state = build_graph().invoke(
        {"question": "이번 배치에서 수율 이상 wafer 의 불량 원인을 분석해줘"}
    )

    # 골격: 현황파악이 불량/대조 그룹을 묶고, 리포트로 끝난다
    assert state["target_group"] == ["W2406_02", "W2406_04", "W2406_06"]
    assert state["control_group"] == ["W2406_01", "W2406_03", "W2406_05"]
    assert state["report"]

    # 게이트: 조기 finalize 는 반려됐고, 최종 finalize 는 승인됐다
    gate_results = [f["result"] for f in state["findings"] if f["tool"] == "finalize"]
    assert any("반려" in r for r in gate_results)
    assert any("승인" in r for r in gate_results)
    assert state["finalize_accepted"] is True
    assert "ETCH-9" in state["final_hypothesis"]    # 그룹 공유 이상 장비까지 좁혔다

    # 감사 기록: 고정 골격 + 그룹 대조 시나리오의 tool 이 남았다
    tools_used = [f["tool"] for f in state["findings"]]
    assert tools_used[0] == "find_low_yield_lots"   # loop 0 = 고정 골격
    assert tools_used[1] == "find_defect_group"     # loop 0 = 그룹 묶기도 골격
    for expected in ("aggregate_defects", "compare_process_logs"):
        assert expected in tools_used
    assert all("thought" in f for f in state["findings"])

    # 가드레일 안에서 끝났다
    assert state["loop_count"] <= 6


def test_no_low_yield_lots_short_circuits_to_report(monkeypatch):
    """수율 이상 lot 이 없으면 크래시 없이 '이상 없음' 리포트로 조기 종료한다."""
    from graph import nodes

    monkeypatch.setattr(nodes.yt, "find_low_yield_lots", lambda: [])
    state = build_graph().invoke({"question": "이번 배치 수율 이상 분석해줘"})

    assert state["report"]                       # 크래시 없이 리포트 도달
    assert state["target_group"] == []           # 분석 대상 없음
    assert "없음" in state["status_summary"]      # "수율 임계 미만인 lot 없음."
    # 분석 루프는 돌지 않았다 — 감사 기록은 현황 파악뿐
    assert [f["tool"] for f in state["findings"]] == ["find_low_yield_lots"]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_graph_nodes.py tests/test_build.py tests/test_mock_llm.py tests/test_e2e.py -q`
Expected: 다수 FAIL (`target_group` 키 부재, mock 시나리오 불일치 등)

- [ ] **Step 3: `graph/state.py` — 상태 키 교체**

`target_wafer: str` 줄을 아래 두 줄로 교체:

```python
    target_group: list[str]                         # 현황파악이 묶은 불량 그룹 (유사 불량 wafer)
    control_group: list[str]                        # 같은 lot 의 정상 wafer (대조 그룹)
```

- [ ] **Step 4: `graph/build.py` — 라우팅 갱신**

`_after_status` 를 교체:

```python
def _after_status(state: dict) -> str:
    # 불량 그룹을 못 묶으면 분석 루프를 건너뛰고 바로 리포팅 (빈 lots/빈 그룹 크래시 방지)
    return "analyze" if state.get("target_group") else "report"
```

- [ ] **Step 5: `graph/nodes.py` — 프롬프트 + status_node + report_node**

(a) `ANALYZE_SYSTEM_PROMPT` 를 교체:

```python
ANALYZE_SYSTEM_PROMPT = """너는 반도체 수율 분석 전문가다. 불량 그룹(유사 불량 wafer 들)과 대조 그룹(같은 lot 의 정상 wafer 들)을 비교해, 불량 그룹만의 공통 원인을 특정 공정 단계(가능하면 장비)까지 좁혀라.

규칙:
- 매 단계, 지금까지의 tool 결과로 원인을 확신할 수 있는지 스스로 평가하라.
- 확신이 부족하면 근거를 좁힐 tool 을 하나 더 호출하라. 그룹 간 차이(장비·파라미터)가 핵심 근거다 — compare_process_logs 로 두 그룹을 대조하라. tool 호출 시 현재 가설과 이 tool 을 부르는 이유를 한두 문장으로 함께 서술하라 (분석 기록으로 남는다).
- 원인을 좁혔고 근거가 충분하면 finalize(hypothesis, confidence) 로 종료를 제안하라. 확신도가 낮으면 반려된다.
- 수치는 tool 결과를 그대로 인용하고 절대 임의로 만들지 마라."""
```

(b) `status_node` 를 교체:

```python
def status_node(state: dict) -> dict:
    lots = yt.find_low_yield_lots()
    summary = _summarize_lots(lots)
    findings = [{
        "loop": 0, "tool": "find_low_yield_lots", "args": {},
        "result": lots, "thought": "현황 파악 (고정 골격)",
    }]
    if not lots:  # 이상 lot 없음 → 분석 루프 없이 리포팅으로 (build 의 _after_status)
        return {"target_group": [], "control_group": [],
                "status_summary": summary, "findings": findings}

    grp = yt.find_defect_group(lots[0]["lot_id"])
    findings.append({
        "loop": 0, "tool": "find_defect_group", "args": {"lot_id": lots[0]["lot_id"]},
        "result": grp, "thought": "그룹 대조 대상 묶기 (고정 골격)",
    })
    if not grp["target_group"]:  # 임계 미만 defect wafer 를 못 묶음 → 분석 루프 생략
        return {"target_group": [], "control_group": grp["control_group"],
                "status_summary": summary, "findings": findings}

    seed = [
        SystemMessage(content=ANALYZE_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"현황:\n{summary}\n\n"
            f"불량 그룹 ({grp['defect_type']}): {', '.join(grp['target_group'])}\n"
            f"대조 그룹 (정상): {', '.join(grp['control_group'])}\n"
            f"질문: {state['question']}"
        )),
    ]
    return {
        "messages": seed,
        "target_group": grp["target_group"],
        "control_group": grp["control_group"],
        "status_summary": summary,
        "findings": findings,
    }
```

(c) `report_node` 의 `target_wafer=state["target_wafer"],` 를 `target_group=state["target_group"],` 로 교체.

(d) 모듈 docstring 첫 줄의 "현황파악(고정)" 뒤 설명은 그대로 두되, 필요 시 "그룹 대조" 언급을 한 줄 추가해도 좋다 (선택).

- [ ] **Step 6: `llm/client.py` — 인터페이스 + mock 시나리오 교체**

(a) `LLMClient.generate_report` 추상 메서드 시그니처에서 `target_wafer: str` 를 `target_group: list[str]` 로 교체 (docstring 동일).

(b) `ScriptedMockLLMClient` 의 클래스 docstring 을 교체:

```python
    """사내망 밖 데모용. 그룹 대조 시나리오를 따라가는 결정론적 스크립트.

    aggregate_defects(불량 그룹) → finalize(0.6, 게이트가 반려)
    → compare_process_logs(불량 vs 대조) → finalize(0.9, 승인) 순서로 진행하며,
    각 단계 인자는 seed 메시지의 그룹 라인과 직전 ToolMessage(json) 를 파싱해 이어받는다.
    """
```

(c) `analyze_step` 을 교체:

```python
    def analyze_step(self, messages: list) -> AIMessage:
        target, control = self._groups(messages)
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        done = [m.name for m in tool_msgs]

        if "aggregate_defects" not in done:
            return self._call(
                "aggregate_defects", {"wafer_ids": target},
                "불량 그룹이 같은 불량 유형을 공유하는지 먼저 집계한다.")

        if "finalize" not in done:
            top = self._result(tool_msgs, "aggregate_defects")[0]["defect_type"]
            return self._call(
                "finalize",
                {"hypothesis": f"불량 그룹 {len(target)}장이 모두 {top} — 공통 원인 존재 추정",
                 "confidence": 0.6},
                "불량 유형은 좁혔지만 공정 근거가 아직 없다. 이 정도로 종료를 제안해 본다.")

        if "compare_process_logs" not in done:
            return self._call(
                "compare_process_logs", {"group_ids": target, "control_ids": control},
                "종료 제안이 반려됐다. 그룹 대조로 원인 공정/장비를 좁힌다.")

        cmp = self._result(tool_msgs, "compare_process_logs")
        bad = cmp["group_spec_violations"][0]
        hyp = (f"{bad['process_step']} 공정 {bad['equipment_id']} 장비의 "
               f"{bad['param_name']} 스펙 이탈(불량 그룹 {len(cmp['group_spec_violations'])}장 공통, "
               f"스펙 {bad['spec_low']}~{bad['spec_high']}, 측정 {bad['param_value']})이 원인")
        return self._call(
            "finalize", {"hypothesis": hyp, "confidence": 0.9},
            "그룹 대조에서 불량 그룹만 공유하는 스펙 이탈 장비를 특정했다. 근거가 충분하다.")
```

(d) `_target` 정적 메서드를 `_groups` 로 교체:

```python
    @staticmethod
    def _groups(messages) -> tuple[list[str], list[str]]:
        text = "\n".join(getattr(m, "content", "") or "" for m in messages
                         if isinstance(m, HumanMessage))
        t = re.search(r"불량 그룹 \([^)]*\): (.+)", text)
        c = re.search(r"대조 그룹 \(정상\): (.+)", text)
        if not (t and c):
            raise ValueError("messages 에서 불량/대조 그룹 라인을 찾지 못했다")
        return ([w.strip() for w in t.group(1).split(",")],
                [w.strip() for w in c.group(1).split(",")])
```

(e) mock `generate_report` — 시그니처의 `target_wafer` 를 `target_group` 로 바꾸고 첫 줄을 교체:

```python
            f"[분석 대상] 불량 그룹: {', '.join(target_group) or '없음'}",
```

(f) `OpenAILLMClient.generate_report` — 시그니처의 `target_wafer` 를 `target_group` 로 바꾸고, user 프롬프트의 `대상 wafer: {target_wafer}` 를 `불량 그룹: {', '.join(target_group)}` 로 교체.

- [ ] **Step 7: `main.py` — 출력 갱신**

`run()` 의 `[분석 대상]` 출력 줄을 교체:

```python
    tg = state["target_group"]
    if tg:
        print(f"[분석 대상] 불량 그룹 {', '.join(tg)}  /  대조 그룹 {', '.join(state['control_group'])}\n")
    else:
        print("[분석 대상] 없음 (수율 이상 lot 없음)\n")
```

모듈 docstring 의 "하이브리드 분석 루프" 는 그대로 두되 필요 시 "그룹 대조" 한 단어를 덧붙여도 좋다 (선택).

- [ ] **Step 8: 전체 테스트 통과 확인**

Run: `python -m pytest tests/ -q`
Expected: 전체 PASS

- [ ] **Step 9: 데모 실행 확인**

Run (PowerShell): `$env:PYTHONUTF8="1"; python main.py`
Expected: `[분석 대상] 불량 그룹 W2406_02, W2406_04, W2406_06 / 대조 그룹 W2406_01, W2406_03, W2406_05`, 감사 기록에 aggregate_defects → finalize 반려 → compare_process_logs → finalize 승인, 결론에 ETCH-9 명시.

- [ ] **Step 10: Commit**

```bash
git add graph/state.py graph/build.py graph/nodes.py llm/client.py main.py tests/test_graph_nodes.py tests/test_build.py tests/test_mock_llm.py tests/test_e2e.py
git commit -m "feat: 분석 대상을 그룹 대조(불량 그룹 vs 정상 대조 그룹)로 전환"
```
