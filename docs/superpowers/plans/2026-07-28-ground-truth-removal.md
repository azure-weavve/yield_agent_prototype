# 정답지 컬럼 제거 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

작성일: 2026-07-28
spec: `docs/superpowers/specs/2026-07-28-ground-truth-removal-design.md`

**Goal:** 더미 `yield` 테이블에서 실데이터에 없는 정답지 두 컬럼(`defect_type`·`process_step`)을 NULL 로 만들고, 그 위에서 무너지는 라벨 의존을 걷어낸다.

**Architecture:** 라벨을 없애는 것이 마지막 Task 다. 그 앞의 Task 들이 먼저 라벨 의존을 제거해, 각 Task 가 끝날 때마다 전체 테스트가 green 을 유지한다. 순서를 바꾸면 중간에 수십 개가 동시에 깨진다.

**Tech Stack:** Python 3.11, sqlite3, pytest, LangChain `@tool`.

## Global Constraints

- **각 Task 종료 시 `PYTHONUTF8=1 python -m pytest -q` 전체 통과.** 현재 기준선 = **158 passed**.
- **난수열 보존.** `generate_dummy.py` 의 난수 소비 순서를 바꾸지 않는다. 이 플랜은 행의 **키 이름**만 바꾸고 값 생성 로직은 건드리지 않는다.
- **컬럼을 지우지 않는다.** `yield.defect_type`·`yield.process_step` 은 스키마에 남는다 (A-3 의 nullable 메타데이터). 값만 NULL 이다.
- **레거시 도구를 삭제하지 않는다.** 이 플랜은 노출만 끈다. 삭제는 Stage 5.
- 주석·docstring·테스트 이름은 기존 코드처럼 한국어 유지.
- 커밋 메시지는 기존 스타일(`feat:`/`fix:`/`test:`/`refactor:`/`docs:` + 한국어 요약) + `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Windows 환경이라 테스트·실행은 `PYTHONUTF8=1` 을 앞에 붙인다.

---

## File Structure

| 파일 | 변경 |
|---|---|
| `tests/test_yield_tools.py` | Task 1 — `find_counterexamples` 테스트 3건을 `_make_db` fixture 로 |
| `tools/yield_tools.py` | Task 2 — `aggregate_defects` 삭제 |
| `tools/agent_tools.py` | Task 2 — tool 래퍼 삭제, `_BASE_TOOLS` 축소 |
| `tools/grouping.py` | Task 2 — `label_counts` 삭제 |
| `graph/nodes.py` | Task 2 — `label` 변수·`defect 라벨` 요약 줄 삭제 |
| `llm/client.py` | Task 2 — mock 각본 4수로 재작성 (2단 포함) |
| `config.py` | Task 3 — `LEGACY_TOOLS_ENABLED` 기본값 `1`→`0` |
| `data/generate_dummy.py` | Task 4 — `_truth_*` 키 분리, `INSERT` 에 NULL |
| `tests/test_dummy_data.py` | Task 4 — 라벨 없이 같은 성질 단언 + 신규 회귀 테스트 |
| `README.md`·`docs/stages.md` | Task 5 |

**Task 순서의 이유:** Task 4(라벨 NULL)가 마지막인 것이 핵심이다. Task 1 이 `find_counterexamples` 테스트를 자체 fixture 로 옮겨 두지 않으면 Task 4 에서 5건이 한꺼번에 깨지고, Task 2 가 `aggregate_defects` 를 지워 두지 않으면 Task 4 에서 각본·E2E 가 함께 깨진다.

---

### Task 1: `find_counterexamples` 테스트를 자체 fixture 로

라벨을 없애기 전에 라벨 의존 테스트를 먼저 격리한다. 이 Task 는 **동작을 바꾸지 않는다** — 테스트가 더미 DB 대신 자기 fixture 를 보게만 한다.

`find_counterexamples` 는 Stage 5 까지 살아 있어야 한다(삭제 전 대체 매핑 확인이 전제). 이 함수의 입력 계약이 "라벨이 있다" 이므로, 라벨 있는 작은 DB 로 시험하는 것이 정직하다.

**Files:**
- Modify: `tests/test_yield_tools.py` (188~220 의 테스트 3건)

**Interfaces:**
- Consumes: 같은 파일에 이미 있는 `_make_db(tmp_path, monkeypatch, rows, logs)` 헬퍼.
  - `rows` 튜플 순서: `(wafer_id, lot_id, yield, defect_type, process_step, date)`
  - `logs` 튜플 순서: `(wafer_id, process_step, equipment_id, param_name, param_value, spec_low, spec_high)`

- [ ] **Step 1: fixture 상수와 새 테스트 3건 작성**

`tests/test_yield_tools.py` 의 `# ---- find_counterexamples` 주석 아래 기존 테스트 3개
(`test_find_counterexamples_one_for_etch9_hypothesis`,
`test_find_counterexamples_found_for_normal_equipment`,
`test_find_counterexamples_unknown_equipment`)를 **통째로 아래로 교체**한다.
`test_find_counterexamples_null_spec_in_spec_none` 은 이미 `_make_db` 를 쓰므로 그대로 둔다.

```python
# ------------------------------------------------ find_counterexamples
# 이 함수는 라벨(defect_type)이 있다는 전제 위에서만 성립한다. 더미는 실데이터를
# 모사하느라 라벨이 전원 NULL 이므로, 여기서는 라벨을 가진 자체 fixture 로 검증한다.
# 함수 자체는 Stage 5 에서 대체 매핑을 확인한 뒤 삭제한다.
_CX_ROWS = [
    ("T1", "L1", 80.0, "center_spot", None, "2024-06-01"),   # 불량 + ETCH-9
    ("T2", "L1", 81.0, "center_spot", None, "2024-06-01"),   # 불량 + ETCH-9
    ("N1", "L1", 95.0, "none",        None, "2024-06-01"),   # 정상 + ETCH-9 (반례)
    ("N2", "L1", 96.0, "none",        None, "2024-06-01"),   # 정상 + ETCH-9 (반례)
    ("D1", "L1", 82.0, "center_spot", None, "2024-06-01"),   # 불량인데 ETCH-9 미사용
    ("N3", "L1", 97.0, "none",        None, "2024-06-01"),   # 정상 + ETCH-1
]
_CX_LOGS = [
    ("T1", "Etch", "ETCH-9", "rf_power", 500.0, 450.0, 550.0),
    ("T2", "Etch", "ETCH-9", "rf_power", 500.0, 450.0, 550.0),
    ("N1", "Etch", "ETCH-9", "rf_power", 500.0, 450.0, 550.0),
    ("N2", "Etch", "ETCH-9", "rf_power", 500.0, 450.0, 550.0),
    ("D1", "Etch", "ETCH-1", "rf_power", 500.0, 450.0, 550.0),
    ("N3", "Etch", "ETCH-1", "rf_power", 500.0, 450.0, 550.0),
]


def _cx_db(tmp_path, monkeypatch):
    _make_db(tmp_path, monkeypatch, rows=_CX_ROWS, logs=_CX_LOGS)


def test_find_counterexamples_reports_both_kinds(tmp_path, monkeypatch):
    """'ETCH-9 가 center_spot 의 원인' 가설의 반례 두 종류를 모두 센다.

    passed_but_normal      = ETCH-9 를 거쳤는데 정상 (N1, N2)
    defect_without_equipment = ETCH-9 없이 같은 불량 (D1)
    """
    _cx_db(tmp_path, monkeypatch)
    res = yt.find_counterexamples("ETCH-9", "Etch", "center_spot")
    assert res["equipment_wafers"] == 4                      # T1 T2 N1 N2
    assert [r["wafer_id"] for r in res["passed_but_normal"]] == ["N1", "N2"]
    assert all(r["in_spec"] is True for r in res["passed_but_normal"])
    assert res["passed_but_normal_rate"] == 0.5              # 2/4
    assert res["defect_wafers"] == 3                         # T1 T2 D1
    assert [r["wafer_id"] for r in res["defect_without_equipment"]] == ["D1"]
    assert res["defect_without_equipment_rate"] == round(1 / 3, 3)


def test_find_counterexamples_wrong_hypothesis_has_many(tmp_path, monkeypatch):
    """가설이 틀리면 반례가 많이 잡힌다 — ETCH-1 은 원인이 아니다."""
    _cx_db(tmp_path, monkeypatch)
    res = yt.find_counterexamples("ETCH-1", "Etch", "center_spot")
    assert res["equipment_wafers"] == 2                      # D1 N3
    assert [r["wafer_id"] for r in res["passed_but_normal"]] == ["N3"]
    # center_spot 3장 중 2장(T1,T2)이 ETCH-1 없이 발생
    assert res["defect_without_equipment_rate"] == round(2 / 3, 3)


def test_find_counterexamples_unknown_equipment(tmp_path, monkeypatch):
    """존재하지 않는 장비 — 0 으로 나누지 않고 조용히 0.0 을 낸다."""
    _cx_db(tmp_path, monkeypatch)
    res = yt.find_counterexamples("ETCH-99", "Etch", "center_spot")
    assert res["equipment_wafers"] == 0
    assert res["passed_but_normal"] == []
    assert res["passed_but_normal_rate"] == 0.0
    assert res["defect_without_equipment_rate"] == 1.0       # 전원이 이 장비 없이 발생
```

- [ ] **Step 2: 실행**

Run: `PYTHONUTF8=1 python -m pytest tests/test_yield_tools.py -q`
Expected: PASS. 기대값이 어긋나면 **fixture 를 다시 세어 본다** — `passed_but_normal` 은
`defect_type == 'none'` 인 장비 사용자, `defect_without_equipment` 는 같은 라벨을 가졌지만
그 장비를 안 쓴 wafer 다.

- [ ] **Step 3: 전체 회귀**

Run: `PYTHONUTF8=1 python -m pytest -q`
Expected: **158 passed** (교체이므로 수 불변).

- [ ] **Step 4: 커밋**

```
test: find_counterexamples 검증을 자체 fixture 로 이전

이 함수는 라벨이 있다는 전제 위에서만 성립한다. 더미가 실데이터를 모사해
라벨을 버리기 전에, 라벨을 가진 작은 DB 로 검증을 옮겨 둔다. 함수 삭제는
Stage 5 그대로.
```

---

### Task 2: 라벨 의존 제거 (`aggregate_defects`·`label_counts`·mock 각본)

**Files:**
- Modify: `tools/yield_tools.py`, `tools/agent_tools.py`, `tools/grouping.py`, `graph/nodes.py`, `llm/client.py`
- Modify: `tests/test_agent_tools.py`, `tests/test_grouping.py`, `tests/test_graph_nodes.py`, `tests/test_mock_llm.py`, `tests/test_e2e.py`

**Interfaces:**
- Removes: `yield_tools.aggregate_defects`, `agent_tools.aggregate_defects`, `grouping.normalize_target()` 반환의 `label_counts` 키.
- Produces: mock 각본의 새 순서 — `finalize(0.6)` → `hyp_eqp_ch_commonality` → `compare_sensor_distribution` → `finalize(0.9)`.

- [ ] **Step 1: 실패 테스트부터 — mock 각본 테스트를 새 순서로**

`tests/test_mock_llm.py` 의 `test_scripted_sequence` 를 아래로 교체한다. HUMAN 상수의
`불량 그룹 (center_spot):` 도 `불량 그룹:` 으로 바꾼다 (각본은 GROUPS_JSON 만 파싱하므로
동작에는 영향이 없지만, 라벨이 사라진 프롬프트와 맞춘다).

```python
def test_scripted_sequence():
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]

    # 1) 근거 없이 조기 finalize (낮은 확신도 → 게이트 반려 시연용)
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] < 0.8
    assert ai.content  # thought(가설 서술)가 감사 기록 재료로 반드시 존재
    msgs += [ai, _tm("finalize", "반려: 확신도 0.60 < 0.8. 근거를 좁힐 tool 을 더 호출하라.")]

    # 2) 1단 — 챔버 편중 가설
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "hyp_eqp_ch_commonality"
    assert ai.tool_calls[0]["args"]["group_ids"] == TARGET
    assert ai.tool_calls[0]["args"]["control_ids"] == CONTROL
    msgs += [ai, _tm("hyp_eqp_ch_commonality", {"candidates": [
        {"level": "chamber", "key": "ETCH9_B", "value": ["Etch", "ETCH9_B"],
         "process_step": "Etch", "score": 1.0, "target_pass": 3, "passes": True},
    ]})]

    # 3) 2단 — 지목된 스텝의 센서 분포
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "compare_sensor_distribution"
    assert ai.tool_calls[0]["args"]["process_step"] == "Etch"
    msgs += [ai, _tm("compare_sensor_distribution", {"status": "ok", "candidates": [
        {"sensor_name": "rf_power_steady_avg", "effect_size": 14.99},
    ]})]

    # 4) 근거를 갖춘 finalize (승인)
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] >= 0.8
    hyp = ai.tool_calls[0]["args"]["hypothesis"]
    assert "ETCH9_B" in hyp
    assert "rf_power_steady_avg" in hyp       # 2단 근거가 결론에 실린다
```

같은 파일의 `test_report_*` 계열에서 `findings` 스텁의 `"tool": "aggregate_defects"` 를
`"tool": "hyp_eqp_ch_commonality"` 로, `assert "aggregate_defects" in report` 를
`assert "hyp_eqp_ch_commonality" in report` 로 바꾼다.

- [ ] **Step 2: 실패 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_mock_llm.py -q`
Expected: FAIL — 1수가 여전히 `aggregate_defects` 라 `assert ... == "finalize"` 가 깨진다.

- [ ] **Step 3: mock 각본 재작성**

`llm/client.py` 의 `ScriptedMockLLMClient` docstring 과 `analyze_step` 을 교체한다.

docstring:

```python
    """사내망 밖 데모용. 그룹 대조 시나리오를 따라가는 결정론적 스크립트.

    finalize(0.6, 게이트가 반려) → hyp_eqp_ch_commonality(1단: 어느 챔버)
    → compare_sensor_distribution(2단: 왜) → finalize(0.9, 승인) 순서로 진행하며,
    각 단계 인자는 seed 메시지의 GROUPS_JSON 과 직전 ToolMessage(json) 를 파싱해 이어받는다.

    라벨(defect_type)을 쓰지 않는다 — 실데이터에 없기 때문이다.
    """
```

`analyze_step` 의 `if "aggregate_defects" not in done:` 블록과 그 다음
`if "finalize" not in done:` 블록을 아래 하나로 교체한다:

```python
        if "finalize" not in done:
            return self._call(
                "finalize",
                {"hypothesis": f"불량 그룹 {len(target)}장이 한 사건으로 묶였다 — "
                               f"공통 원인 존재 추정",
                 "confidence": 0.6},
                "그룹은 묶였지만 공정 근거가 아직 없다. 이 정도로 종료를 제안해 본다.")
```

그리고 `top = passing[0]` 아래, 마지막 `finalize` 앞에 2단 호출을 끼워 넣는다:

```python
        top = passing[0]

        if "compare_sensor_distribution" not in done:
            return self._call(
                "compare_sensor_distribution",
                {"process_step": top["process_step"],
                 "group_ids": target, "control_ids": control},
                "챔버까지 좁혔다. 그 스텝의 센서 분포로 '왜' 를 본다.")

        sensor = self._result(tool_msgs, "compare_sensor_distribution")
        val = top["value"][-1]
        hyp = (f"{top['value'][0]} 공정 {val} 편중(분리 점수 {top.get('score')}, "
               f"불량군 {top['target_pass']}장 전용)이 원인")
        if sensor.get("candidates"):
            c = sensor["candidates"][0]
            hyp += f" — {c['sensor_name']} 효과크기 {c['effect_size']}"
        return self._call(
            "finalize", {"hypothesis": hyp, "confidence": 0.9},
            "챔버 편중에 센서 근거까지 붙었다. 근거 충분.")
```

기존의 `top = passing[0]` 이후 `val`/`hyp`/`return` 줄은 위 블록으로 대체되므로 지운다.
`if not passing:` 분기(확신도 0.2)는 그대로 둔다.

- [ ] **Step 4: mock 테스트 통과 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_mock_llm.py -q`
Expected: PASS.

- [ ] **Step 5: `aggregate_defects` 삭제**

`tools/yield_tools.py` 의 `aggregate_defects` 함수 전체(정의부터 `return [dict(r) for r in rows]` 까지)를 지운다.

`tools/agent_tools.py`:
- `@tool def aggregate_defects(...)` 블록 전체 삭제
- `_BASE_TOOLS` 를 교체:

```python
_BASE_TOOLS = [get_wafer, search_similar, compare_sensor_distribution]
```

- `_LEGACY_TOOLS` 위의 주석에서 `aggregate_defects 는 yield.defect_type 에 묶여 있어
  실데이터에서 의미가 약하지만, 그 처리는 Stage 4 소관이라 여기 두지 않는다.` 문장을 지운다
  (Stage 4 에서 처리했으므로).

- [ ] **Step 6: `label_counts` 삭제**

`tools/grouping.py` 의 `normalize_target` 반환 dict 에서 아래 줄을 지운다:

```python
        "label_counts": yt.aggregate_defects(target) if not unknown else [],
```

모듈 docstring 의 `defect 라벨은 판정 기준이 아니라 참고 정보다 (6절 3번 — 유사맵이 이긴다).`
를 아래로 바꾼다:

```
라벨(defect_type)은 쓰지 않는다 — 실데이터에 없다. 묶는 것은 EDS 뿐이다.
```

`graph/nodes.py`:
- `label = norm["label_counts"][0]["defect_type"] if norm["label_counts"] else "미상"` 줄 삭제
- 프롬프트의 `f"불량 그룹 ({label}): {', '.join(norm['target_group'])}\n"` 을
  `f"불량 그룹: {', '.join(norm['target_group'])}\n"` 으로
- `_summarize_target` 의 아래 두 줄 삭제:

```python
    labels = ", ".join(f"{c['defect_type']} {c['count']}장" for c in norm["label_counts"])
    lines.append(f"defect 라벨 (참고): {labels}")
```

- [ ] **Step 7: 남은 테스트 조정**

- `tests/test_agent_tools.py`
  - `test_tool_names` 의 집합에서 `"aggregate_defects"` 제거
  - `test_aggregate_defects_tool_invokes` 함수 전체 삭제
  - `test_reason_is_optional_and_ignored` 를 `get_wafer` 로 교체:

```python
def test_reason_is_optional_and_ignored():
    # reason 은 감사 기록용 — 있어도 없어도 결과는 같다
    args = {"wafer_id": "W2406_02"}
    assert (at.TOOLS_BY_NAME["get_wafer"].invoke(args)
            == at.TOOLS_BY_NAME["get_wafer"].invoke({**args, "reason": "테스트"}))
```

- `tests/test_grouping.py` — `assert res["label_counts"][0]["defect_type"] == "center_spot"` 과
  그 위 주석(`# defect 라벨은 참고 정보로만 …`) 삭제
- `tests/test_graph_nodes.py`
  - `:102` 근처 스텁 dict 의 `"label_counts": [{"defect_type": "center_spot", "count": 2}]` 삭제
  - `:237` 의 `{"name": "aggregate_defects", "args": {"wafer_ids": "W2406_02"}, "id": "c1"}` 를
    `{"name": "get_wafer", "args": {"wafer_id": "W2406_02"}, "id": "c1"}` 로 교체
- `tests/test_e2e.py:30` — `assert "aggregate_defects" in tools_used` 를
  `assert "compare_sensor_distribution" in tools_used` 로 교체 (새 각본이 2단을 부르므로
  E2E 가 2단까지 도는 것을 여기서 고정한다)

- [ ] **Step 8: 전체 회귀**

Run: `PYTHONUTF8=1 python -m pytest -q`
Expected: **157 passed** (158 − `test_aggregate_defects_tool_invokes` 1건).

`test_graph_nodes` 에서 `label_counts` KeyError 가 나면 `_summarize_target` 에 지우지 못한
참조가 남은 것이다.

- [ ] **Step 9: 데모 확인**

Run: `PYTHONUTF8=1 python main.py`
확인할 것: 결론이 `ETCH9_B` 이고, **분석 과정에 `compare_sensor_distribution` 이 나온다.**
출력 문구는 이전과 달라진다 — 이번 Stage 는 그것을 감수한다.

- [ ] **Step 10: 커밋**

```
refactor: 라벨 의존 제거 — aggregate_defects 삭제, mock 각본 재작성

라벨(defect_type)은 실데이터에 없으므로 그것을 집계하는 도구와 그 결과를
프롬프트·요약에 싣던 경로를 지운다. mock 각본은 라벨 대신 근거 없는 조기
finalize 로 게이트 반려를 시연하고, 1단(챔버) 뒤에 2단(센서)을 붙인다 —
Stage 3 의 2단이 데모에 처음 나온다. 데모 출력 문구는 바뀐다.
```

---

### Task 3: 레거시 도구 기본 OFF

`find_counterexamples` 는 라벨이 없으면 두 반례 목록이 **모두 비고**, 그것은 docstring 대로면
「가설의 특이성이 확인됨」으로 읽힌다. 데이터가 없어서 빈 것을 "반례 없음" 으로 보고하는
조용한 오확증이다. Task 4 에서 라벨이 사라지기 전에 노출을 끈다.

**Files:**
- Modify: `config.py`, `tests/test_agent_tools.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_agent_tools.py` 의 `test_legacy_tools_hidden_when_flag_off` 아래에 추가:

```python
def test_legacy_tools_are_off_by_default():
    """기본값이 OFF 다 — 라벨 없는 데이터에서 find_counterexamples 는 '반례 없음' 을
    조용히 참으로 보고한다(데이터가 없어서 빈 것을 특이성으로 읽는다). 삭제는 Stage 5.
    """
    import config

    assert config.LEGACY_TOOLS_ENABLED is False
    assert not ({t.name for t in at.ANALYSIS_TOOLS}
                & {"get_process_log", "find_counterexamples", "validate_data_completeness"})
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_agent_tools.py -q`
Expected: FAIL — 기본값이 아직 `True`.

- [ ] **Step 3: 기본값 뒤집기**

`config.py` 의 해당 줄과 주석을 교체한다:

```python
# 옛 process_log 스키마에 묶인 레거시 도구를 LLM 에 노출할지. **기본 꺼짐.**
# find_counterexamples 는 defect_type 으로 '정상' 을 판정하는데, 라벨이 없으면 반례
# 목록이 비고 그것이 "특이성 확인됨" 으로 읽힌다 — 조용히 틀리느니 안 도는 게 낫다.
# 도구와 이 플래그의 삭제는 Stage 5.
LEGACY_TOOLS_ENABLED = os.getenv("LEGACY_TOOLS_ENABLED", "0") == "1"
```

- [ ] **Step 4: 기본값 OFF 로 깨지는 테스트 정리**

`tests/test_agent_tools.py`:
- `test_tool_names` 의 집합에서 `"get_process_log"`, `"validate_data_completeness"`,
  `"find_counterexamples"` 를 뺀다. 남는 집합:

```python
    assert {t.name for t in at.ALL_TOOLS} == {
        "get_wafer", "search_similar", "compare_sensor_distribution",
        "hyp_eqp_ch_commonality", "hyp_ppid_commonality",
        "finalize",
    }
```

- `test_validate_data_completeness_tool_invokes` 를 플래그를 켠 창 안에서 돌게 바꾼다
  (같은 파일 `test_legacy_tools_hidden_when_flag_off` 의 reload 패턴을 뒤집은 것):

```python
def test_validate_data_completeness_tool_invokes(monkeypatch):
    """레거시 도구는 코드에 남아 있다 — 플래그를 켜면 여전히 돈다 (삭제는 Stage 5)."""
    import importlib

    import config
    from tools import agent_tools

    monkeypatch.setattr(config, "LEGACY_TOOLS_ENABLED", True)
    importlib.reload(agent_tools)
    try:
        res = agent_tools.TOOLS_BY_NAME["validate_data_completeness"].invoke(
            {"wafer_ids": ["W2406_02"]})
        assert res["status"] == "good"
    finally:
        monkeypatch.undo()
        importlib.reload(agent_tools)
```

- `test_find_counterexamples_tool_invokes` 함수 전체 삭제. 이유: 함수 동작은 Task 1 의
  fixture 테스트 3건이 덮고, 노출 여부는 위 두 플래그 테스트가 덮는다. 더미 DB 위에서
  이 도구를 부르는 테스트는 Task 4 이후 의미를 잃는다.

- [ ] **Step 5: 전체 회귀**

Run: `PYTHONUTF8=1 python -m pytest -q`
Expected: **157 passed** (`test_legacy_tools_are_off_by_default` +1,
`test_find_counterexamples_tool_invokes` −1).

- [ ] **Step 6: 데모 확인**

Run: `PYTHONUTF8=1 python main.py`
확인할 것: 결론이 여전히 `ETCH9_B`. 레거시 도구는 mock 각본이 부르지 않으므로 무영향이어야 한다.

- [ ] **Step 7: 커밋**

```
fix: 레거시 도구를 기본 OFF 로 (조용한 오확증 차단)

find_counterexamples 는 defect_type 으로 '정상' 을 판정한다. 라벨이 없으면
반례 목록이 비고, 그것이 "가설의 특이성이 확인됨" 으로 읽힌다 — 데이터가 없어서
빈 것을 근거로 삼는 셈이다. 조용히 틀리느니 안 도는 게 낫다. 삭제는 Stage 5.
```

---

### Task 4: 더미에서 정답지 걷어내기

**Files:**
- Modify: `data/generate_dummy.py`
- Modify: `tests/test_dummy_data.py`
- Regenerate: `data/yield.db`

**Interfaces:**
- Produces: `yield` 테이블의 `defect_type`·`process_step` 이 **전 행 NULL**.
  행 dict 의 키는 `_truth_defect`·`_truth_step` (DB 에 안 들어간다).

- [ ] **Step 1: 실패 테스트 작성 — 회귀 방어선**

`tests/test_dummy_data.py` 맨 아래에 추가:

```python
def test_ground_truth_columns_are_null():
    """정답지 컬럼은 DB 에 값이 없다 (A-2·A-3).

    '어느 스텝이 원인인가'·'무슨 불량인가' 는 시스템이 추론할 결론이지 입력이 아니다.
    실데이터 적재기(load_internal)가 이미 NULL 을 강제하므로 더미도 같아야 한다.
    누가 더미에 라벨을 다시 채우면 이 테스트가 먼저 깨진다.
    """
    with _conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM yield "
            "WHERE defect_type IS NOT NULL OR process_step IS NOT NULL"
        ).fetchone()[0]
    assert n == 0
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_dummy_data.py::test_ground_truth_columns_are_null -q`
Expected: FAIL — 현재 전 행에 값이 있으므로 `n` 이 149.

- [ ] **Step 3: 행 리터럴의 키 개명**

`data/generate_dummy.py` 의 `generate()` 안 `rows.append({...})` **8군데**에서
`"defect_type"` → `"_truth_defect"`, `"process_step"` → `"_truth_step"` 로 바꾼다.
값은 그대로 둔다. 대상 줄(현재 번호):

| 위치 | 현재 값 |
|---|---|
| 정상 wafer | `"none"` / `"Normal"` |
| 불량 그룹 | `FEATURED_DEFECT` / `FEATURED_PROCESS` |
| 대조 그룹 | `"none"` / `"Normal"` |
| 패턴 그룹 (과거) | `grp["defect"]` / `grp["process"]` |
| 구멍 (가) `UNLABELED_LOW_WAFER` | `"none"` / `"Normal"` |
| 구멍 (나) `UNGROUPED_WAFERS` | `"none"` / `"Normal"` |
| 적대적 lot | `"none"` / `"Normal"` |
| 분할 lot | `"none"` / `"Normal"` |

적대적 lot·분할 lot 의 기존 주석(`# 라벨 없음 — 실데이터와 같은 조건`,
`# process_log 를 전부 스펙 내로 유지`)은 그대로 둔다. 뒤 주석은 여전히 맞다 —
`_make_process_logs` 가 `_truth_step` 을 보고 이상을 심기 때문이다.

`SPLIT_WAFERS` 아래 센서 상수 블록 위에 설명을 추가한다:

```python
# ---------------------------------------------------------------- 정답지 (DB 에 안 들어감)
# `_truth_*` 는 **생성기 내부 정답지**다. 어느 스텝에 이상을 심을지 정하는 데만 쓰고
# yield 테이블에는 NULL 로 들어간다 (A-2·A-3: 실데이터에 이 두 값은 없다).
# 키 이름을 DB 컬럼과 다르게 둔 이유는, 행을 읽는 사람이 "DB 에도 값이 있겠구나" 로
# 오해하거나 _write_sqlite 가 실수로 쓰는 경로를 아예 없애기 위해서다.
```

- [ ] **Step 4: 읽는 곳과 쓰는 곳 고치기**

`_make_process_logs` 의 조건을 바꾼다:

```python
            if r["_truth_step"] == step:
```

`_write_sqlite` 의 `INSERT INTO yield` 를 바꾼다 (두 컬럼에 리터럴 NULL — 행에 그 키가
없으므로 named 파라미터를 그대로 두면 실행이 실패한다):

```python
    conn.executemany(
        "INSERT INTO yield VALUES (:wafer_id, :lot_id, :yield, NULL, NULL, "
        ":date, :root_lot_id, :lot_type)", rows)
```

`_report` 의 마지막 출력 줄을 바꾼다:

```python
            print(f"  {r['wafer_id']}  yield={r['yield']}  "
                  f"defect={r['_truth_defect']} (정답지 — DB 에는 NULL)")
```

- [ ] **Step 5: 라벨을 단언하던 더미 테스트 5건 교체**

`tests/test_dummy_data.py` 상단 import 에 추가:

```python
from data.generate_dummy import (CONTROL_WAFERS, GROUP_WAFERS, PATTERN_GROUPS,
                                 UNGROUPED_LOT, UNLABELED_LOW_WAFER)
```

**(1) `test_group_members_share_anomaly_equipment`** — 라벨로 그룹을 찾던 것을,
"이상 장비는 전부 `-9` 다" 라는 라벨 없는 성질로 바꾼다. 커버 범위가 오히려 넓어진다
(패턴 그룹 전원 포함):

```python
def test_anomaly_equipment_is_always_the_shared_minus9():
    """스펙 이탈은 항상 그룹 공유 이상 장비(-9)에서만 난다.

    옛 버전은 defect_type='center_spot' 으로 그룹을 찾았다. 라벨이 사라졌으므로
    '이상이 있는 wafer 는 전부 -9 를 거쳤다' 로 같은 성질을 라벨 없이 단언한다.
    """
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT equipment_id FROM process_log
            WHERE NOT (spec_low <= param_value AND param_value <= spec_high)
            """
        ).fetchall()
    assert rows
    assert all(r["equipment_id"].endswith("-9") for r in rows)
```

**(2) `test_normal_wafer_all_in_spec`** — "정상 wafer 는 전부 스펙 내" 를, 이상을 가진
wafer 수가 심어둔 패턴 wafer 수와 정확히 같은지로 바꾼다:

```python
def test_only_planted_pattern_wafers_have_anomalies():
    """이상을 가진 wafer 수 = 심어둔 패턴 wafer 수. 그 밖은 전부 스펙 내다."""
    expected = len(GROUP_WAFERS) + sum(g["n_past"] for g in PATTERN_GROUPS)
    with _conn() as conn:
        n = conn.execute(
            """
            SELECT COUNT(DISTINCT wafer_id) FROM process_log
            WHERE NOT (spec_low <= param_value AND param_value <= spec_high)
            """
        ).fetchone()[0]
    assert n == expected
```

**(3) `test_recent_lot_has_group_and_control`** — 라벨 단언만 빼고 수율 단언은 남긴다.
`SELECT` 에서 `defect_type` 을 빼고, 두 `for` 루프의 `assert by_id[wid]["defect_type"] == ...`
줄을 지운다. docstring 의 `(짝수, center_spot)` 은 `(짝수 = GROUP_WAFERS)` 로,
`W2406_07(저수율인데 defect 라벨 없음)` 은 `W2406_07(저수율 비타깃)` 으로 바꾼다.

**(4) `test_hole_case_unlabeled_low_yield_wafer_passed_etch9_in_spec`** —
`SELECT yield, defect_type` 을 `SELECT yield` 로, `assert r["defect_type"] == "none"` 을 지운다.
docstring 을 바꾼다:

```python
    """구멍 (가): W2406_07 은 저수율인데 이상 장비 ETCH-9 를 '스펙 안으로' 통과했다.

    라벨이 전원 없어진 지금은 "라벨이 없다" 가 이 wafer 만의 특징이 아니다. 남은
    성질은 '수율은 낮은데 측정값은 스펙 내' 이고, 그것이 대조군에 섞였을 때
    suspect_equipment 를 희석한다.
    """
```

**(5) `test_hole_case_ungrouped_low_yield_lot`** — `SELECT yield, defect_type` → `SELECT yield`,
`assert all(r["defect_type"] == "none" for r in rows)` 삭제. docstring 의
`전 wafer 가 'none' 이라 defect 패턴으로는 그룹을 못 묶는다` 를
`라벨이 없어 defect 패턴으로는 그룹을 못 묶는다` 로 바꾼다.

- [ ] **Step 6: 더미 재생성 + 전체 회귀**

Run: `PYTHONUTF8=1 python data/generate_dummy.py && PYTHONUTF8=1 python -m pytest -q`
Expected: **158 passed** (157 + 신규 회귀 테스트 1건).

`sqlite3.ProgrammingError: You did not supply a value for binding parameter :defect_type`
가 나면 Step 4 의 `INSERT` 를 안 고친 것이다.

- [ ] **Step 7: 데모 확인**

Run: `PYTHONUTF8=1 python main.py`
확인할 것: **결론이 여전히 `ETCH9_B`.** 라벨 없이도 EDS 형제 묶기 → root_lot 대조군 →
1단 → 2단 이 끝까지 도는지가 이 Stage 의 핵심 증명이다. 여기서 `isolated` 나
`control_insufficient` 로 빠지면 멈추고 원인을 찾는다 (라벨은 그룹핑에 안 쓰이므로
정상적으로는 영향이 없어야 한다).

- [ ] **Step 8: 커밋**

```
feat(dummy): 정답지 컬럼을 실데이터처럼 NULL 로

yield.defect_type·process_step 은 실데이터에 없다. 적재기는 이미 NULL 을
강제하는데 더미만 값을 채워, 같은 컬럼을 두고 둘이 반대로 행동하고 있었다.
생성기 내부 정답지는 _truth_* 로 분리해 DB 에 들어갈 경로를 없앤다.

라벨을 단언하던 더미 테스트는 같은 성질을 라벨 없이 단언하도록 바꿨고,
두 컬럼이 전원 NULL 인지 보는 회귀 테스트를 추가했다.
```

---

### Task 5: 문서 반영

**Files:**
- Modify: `README.md`, `docs/stages.md`

- [ ] **Step 1: README 도구 목록**

`README.md:102` 의 `analyze 노드에서 Agent 는 get_wafer, search_similar, aggregate_defects, …`
에서 `aggregate_defects, ` 를 지운다.

- [ ] **Step 2: README 데모 출력 갱신**

`README.md:29` 부근의 분석 과정 예시가 `1. aggregate_defects args=…` 로 시작한다.
Task 4 Step 7 에서 실제로 돌린 `python main.py` 출력으로 그 블록을 교체한다.
**손으로 지어내지 말고 실제 출력을 붙인다.**

- [ ] **Step 3: `docs/stages.md` 갱신**

`현재 위치` 표의 Stage 4 줄을 바꾼다:

```
Stage 4    ✅ 완료 (2026-07-28) — 더미에서 정답지 컬럼(defect_type·process_step) 제거
```

`### Stage 4 — 그룹핑` 절을 아래로 교체한다:

```markdown
### Stage 4 — 정답지 제거 (완료)

spec `superpowers/specs/2026-07-28-ground-truth-removal-design.md`,
플랜 `superpowers/plans/2026-07-28-ground-truth-removal.md`.

**원래 Stage 4(`defect_type` 그룹핑 → EDS)는 Stage 2 가 흡수해 이미 끝나 있었다.**
A-3 이 지정한 코드 영향 3건(status_node 그룹핑 폐기·find_normal_wafers 재작성·형제
그룹핑 방법 확정)이 전부 완료 상태였다.

진짜 남은 문제는 **더미가 실데이터에 없는 정답지 두 컬럼을 값으로 들고 있다**는
것이었다. 적재기는 `yield.process_step` 에 NULL 을 강제하는데 더미는 `"Etch"` 를
채워 넣어, 같은 컬럼을 두고 둘이 반대로 행동했다. 라벨이 있으면 그룹핑이 라벨로도
되고 EDS 로도 되므로, EDS 경로가 실제로 성립하는지를 더미가 증명해 주지 못했다.

**한 것:** 생성기 정답지를 `_truth_*` 로 분리하고 두 컬럼을 NULL 로,
`aggregate_defects` 와 `label_counts` 삭제, 레거시 도구 기본 OFF(조용한 오확증 차단),
mock 각본을 라벨 없이 재작성하며 2단을 데모에 넣었다.

**`SIBLING_MIN_SIMILARITY` 컷오프는 여전히 미검증** — 실데이터 분포가 필요하다
(Stage 5.5). 컷오프를 못 정한 채 구조만 두는 것을 계속 감수한다.
```

- [ ] **Step 4: 전체 회귀 후 커밋**

Run: `PYTHONUTF8=1 python -m pytest -q` → **158 passed**

```
docs: Stage 4 반영 (README·stages)

원래 Stage 4 는 Stage 2 가 흡수해 이미 끝나 있었고, 실제로 한 일은 더미에서
정답지 컬럼을 걷어낸 것임을 stages.md 에 남긴다.
```

---

## 완료 기준

1. `SELECT COUNT(*) FROM yield WHERE defect_type IS NOT NULL OR process_step IS NOT NULL` = **0**
2. 라벨 없이 EDS 묶기 → root_lot 대조군 → 1단 → 2단 이 끝까지 돈다 (`test_e2e`).
3. `python main.py` 의 수렴 결론이 여전히 `ETCH9_B`. **출력 문구는 바뀐다.**
4. `LEGACY_TOOLS_ENABLED` 기본이 `0` 이고, 켜면 레거시 도구가 여전히 돈다.
5. 전체 회귀 **158 passed**.

Task 별 예상 수: Task 1 → 158, Task 2 → 157, Task 3 → 157, Task 4 → 158, Task 5 → 158.
수가 다르면 멈추고 어느 테스트가 빠졌는지 확인한다.

## 비목표

- `SIBLING_MIN_SIMILARITY` 컷오프 검증 (Stage 5.5)
- 레거시 도구·`process_log` **삭제** (Stage 5) — 이 플랜은 노출만 끈다
- 라벨이 일부만 있는 중간 상태 대응
