# Stage 4 이후 소품 3건 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 종료 후 tool 실행·EDS 인덱스 미존재 크래시·tool 실패 문자열이라는 세 실패 경로를 막는다. 새 기능은 없다.

**Architecture:** 세 곳이 각자 독립적이다. (1) `graph/nodes.py` `tools_node` 의 for 루프에 종료 플래그를 넣어 승인 후 잔여 호출을 실행하지 않고 응답만 채운다. (2) `tools/grouping.py` 가 EDS 조회 실패를 예외 대신 `eds_error` 사실로 보고하고, `graph/nodes.py` `status_node` 가 그것을 `eds_index_missing` 조기 출구로 판정하며, `llm/client.py` 가 그 사유를 리포트에 쓴다. (3) `llm/client.py` `_result` 가 dict 가 아닌 tool 결과를 `{}` 로 흡수해 이미 있는 후퇴 분기를 타게 한다.

**Tech Stack:** Python 3, LangGraph, LangChain core(`AIMessage`/`ToolMessage`), pytest, sqlite3, hnswlib

설계 문서: `docs/superpowers/specs/2026-07-29-post-stage4-small-fixes-design.md`

## Global Constraints

- 작업 디렉터리는 `prototype/`. 모든 명령은 여기서 실행한다.
- 전체 테스트: `python -m pytest -q`. **착수 시점 기준선은 159 passed** — 어느 Task 도 이 수를 줄이지 않는다.
- **TDD 강제.** 각 Task 는 실패하는 테스트를 먼저 쓰고, 실패를 눈으로 확인한 뒤 구현한다.
- **정상 데모 경로는 한 글자도 바뀌지 않는다.** 전부 실패 경로 방어다. `tests/test_e2e.py::test_full_loop_reaches_report_with_audit_trail` 가 그 감시자다.
- 커밋 메시지는 한국어. 마지막 줄에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` 를 넣는다.
- 브랜치 `post-stage4-small-fixes` 에서 작업한다 (이미 생성됨). main 병합은 사용자가 결정한다 — 임의로 병합하지 않는다.
- **Stage 5 삭제 대상은 건드리지 않는다**: `find_counterexamples`, `validate_data_completeness`, `get_process_log`, `LEGACY_TOOLS_ENABLED`, `tools/yield_tools.py` 의 `process_log` 계열 함수.

---

## File Structure

| 파일 | 이 작업에서의 책임 | Task |
|---|---|---|
| `graph/nodes.py` | `tools_node` 종료 후 잔여 호출 처리 · `status_node` 의 `eds_index_missing` 조기 출구 | 1, 2 |
| `tools/grouping.py` | EDS 조회 실패를 예외가 아닌 `eds_error` 사실로 보고 (흐름 판단은 하지 않음) | 2 |
| `llm/client.py` | `eds_index_missing` 리포트 문구 · `_result` 의 비-dict 방어 | 2, 3 |
| `tests/test_graph_nodes.py` | 노드 단위 검증 (종료 후 잔여 호출) | 1 |
| `tests/test_grouping.py` | 정규화 계층 검증 (EDS 예외 → `eds_error`) | 2 |
| `tests/test_e2e.py` | 그래프 전체가 크래시 없이 리포트로 끝나는지 | 2 |
| `tests/test_mock_llm.py` | 각본이 tool 실패 문자열에 죽지 않는지 | 3 |
| `tools/agent_tools.py` | 파일 끝 개행 1바이트 | 3 |

---

### Task 1: finalize 승인 후 잔여 tool_call 중단

**Files:**
- Modify: `graph/nodes.py:123-159` (`tools_node`)
- Test: `tests/test_graph_nodes.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: `nodes.tools_node(state: dict) -> dict` — 기존 시그니처 그대로.
- Produces: 동작 계약만 바뀐다. 반환 `messages` 길이는 **항상** `len(ai.tool_calls)` 와 같고, 승인 이후의 call 은 실행되지 않은 채 생략 문구로 응답된다.

**배경 (구현자용):** `tools_node` 는 LLM 이 낸 AIMessage 의 `tool_calls` 를 순서대로 실행한다. `finalize` 는 실행되는 tool 이 아니라 종료 제안이고, `_finalize_gate` 가 승인하면 `update["finalize_accepted"] = True` 를 찍는다. 지금은 승인 뒤에도 루프가 계속 돌아 나머지 tool 이 실행된다. LangChain 은 **모든 `tool_call_id` 에 대응하는 ToolMessage** 를 요구하므로, 실행을 건너뛰더라도 응답은 반드시 채워야 한다.

- [ ] **Step 1: 실패하는 테스트 두 개를 쓴다**

`tests/test_graph_nodes.py` 파일 끝에 추가:

```python
def test_tools_node_skips_calls_after_finalize_accepted():
    """승인 뒤 같은 메시지의 잔여 tool 은 실행되지 않는다 — 종료 판정 뒤에 생긴 증거가
    감사 기록에 섞이면 안 된다. 단 ToolMessage 는 tool_call 수만큼 채운다(LangChain 계약)."""
    ai = AIMessage(content="종료 제안", tool_calls=[
        {"name": "finalize",
         "args": {"hypothesis": "Etch 공정 ETCH9_B 챔버 편중이 원인", "confidence": 0.9},
         "id": "cf"},
        {"name": "get_wafer", "args": {"wafer_id": "W2406_02"}, "id": "c1"},
    ])
    out = nodes.tools_node({"messages": [ai], "loop_count": 4,
                            "findings": [EVIDENCE_FINDING_NEW]})

    assert out["finalize_accepted"] is True
    assert len(out["messages"]) == 2                   # 모든 tool_call 에 응답이 있다
    assert "생략" in out["messages"][1].content
    skipped = [f for f in out["findings"] if f["tool"] == "get_wafer"]
    assert len(skipped) == 1
    assert "생략" in skipped[0]["result"]              # 조회 결과(dict)가 아니라 생략 기록
    assert "thought" in skipped[0]                     # 감사 기록 형식은 유지


def test_second_finalize_does_not_overwrite_accepted_hypothesis():
    """한 메시지에 finalize 가 2개면 뒤가 앞의 승인 가설을 덮어썼다."""
    ai = AIMessage(content="종료 제안", tool_calls=[
        {"name": "finalize",
         "args": {"hypothesis": "Etch 공정 ETCH9_B 챔버 편중이 원인", "confidence": 0.9},
         "id": "cf1"},
        {"name": "finalize",
         "args": {"hypothesis": "ETCH9_B 와 무관한 다른 가설", "confidence": 0.95},
         "id": "cf2"},
    ])
    out = nodes.tools_node({"messages": [ai], "loop_count": 4,
                            "findings": [EVIDENCE_FINDING_NEW]})
    assert out["final_hypothesis"] == "Etch 공정 ETCH9_B 챔버 편중이 원인"
    assert len(out["messages"]) == 2
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_graph_nodes.py -q -k "skips_calls_after or second_finalize"`
Expected: 2 failed. 첫째는 `get_wafer` 가 실제로 실행돼 `skipped[0]["result"]` 가 dict 라 `"생략" in ...` 에서 TypeError 또는 AssertionError. 둘째는 `final_hypothesis` 가 `"ETCH9_B 와 무관한 다른 가설"` 로 덮여 AssertionError.

- [ ] **Step 3: 최소 구현**

`graph/nodes.py` 의 `tools_node` 를 아래로 바꾼다 (변경점: `stopped` 플래그, 루프 선두의 생략 처리, finalize 분기 끝의 플래그 세팅):

```python
def tools_node(state: dict) -> dict:
    ai = state["messages"][-1]
    loop = state["loop_count"]
    out_msgs, findings, update = [], [], {}
    stopped = False   # finalize 승인/한계 이후의 잔여 호출은 실행하지 않는다

    for call in ai.tool_calls:
        if stopped:
            # 실행은 건너뛰되 응답은 채운다 — LangChain 은 모든 tool_call_id 에
            # 대응하는 ToolMessage 를 요구한다. 감사 기록에도 생략 사실을 남긴다.
            skipped = "분석 종료로 생략 (finalize 판정 뒤의 잔여 호출)"
            out_msgs.append(ToolMessage(skipped, tool_call_id=call["id"],
                                        name=call["name"]))
            findings.append({
                "loop": loop, "tool": call["name"], "args": call["args"],
                "result": skipped, "thought": ai.content or "",
            })
            continue

        if call["name"] == "finalize":
            # 증거는 누적 findings + 이번 메시지에서 방금 실행된 tool 결과(findings)까지 포함
            verdict = _finalize_gate(call["args"], loop, update,
                                     state.get("findings", []) + findings)
            out_msgs.append(ToolMessage(verdict, tool_call_id=call["id"], name="finalize"))
            findings.append({
                "loop": loop, "tool": "finalize", "args": call["args"],
                "result": verdict, "thought": ai.content or "",
            })
            stopped = bool(update.get("finalize_accepted"))   # 반려는 종료가 아니다
        else:
            tool = TOOLS_BY_NAME.get(call["name"])
            if tool is None:
                result = (f"오류: '{call['name']}' 는 존재하지 않는 tool 이다. "
                          f"사용 가능한 tool: {', '.join(TOOLS_BY_NAME)}. "
                          f"이 중에서 다시 선택해 호출하라.")
            else:
                try:
                    result = tool.invoke(call["args"])
                except Exception as e:  # 인자 스키마 위반·조회 실패 등
                    result = (f"오류: {call['name']} 실행 실패 "
                              f"({type(e).__name__}: {e}). 인자를 확인하고 다시 호출하라.")
            out_msgs.append(ToolMessage(
                json.dumps(result, ensure_ascii=False),
                tool_call_id=call["id"], name=call["name"],
            ))
            findings.append({
                "loop": loop, "tool": call["name"], "args": call["args"],
                "result": result, "thought": ai.content or call["args"].get("reason", ""),
            })

    return {"messages": out_msgs, "findings": findings, **update}
```

`tools_node` 의 docstring 은 건드리지 않는다. 모듈 docstring(`graph/nodes.py:5-8`)의 "tools 노드는 세 가지를 한다" 목록도 그대로 둔다 — 세 가지 책임은 변하지 않았다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_graph_nodes.py -q -k "skips_calls_after or second_finalize"`
Expected: 2 passed

- [ ] **Step 5: 전체 회귀**

Run: `python -m pytest -q`
Expected: 161 passed (159 + 신규 2)

- [ ] **Step 6: 커밋**

```bash
git add graph/nodes.py tests/test_graph_nodes.py
git commit -F - <<'EOF'
fix: finalize 판정 뒤의 잔여 tool 호출 중단 (미룸 5번)

한 AIMessage 에 finalize + 다른 tool 이 오면 승인 뒤에도 나머지가 실행돼
종료 판정 뒤에 생긴 증거가 감사 기록에 섞였다. finalize 가 2개면 뒤가 앞의
승인 가설을 덮었다. 승인/한계 판정 즉시 중단하되, LangChain 계약대로
잔여 tool_call 에는 생략 ToolMessage 를 채워 응답한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: EDS 인덱스에 없는 wafer → `eds_index_missing` 조기 출구

**Files:**
- Modify: `tools/grouping.py:24-50` (`normalize_target`)
- Modify: `graph/nodes.py:42-56` (`status_node` 의 조기 출구 순서)
- Modify: `llm/client.py:134-147` (`generate_report` 의 분기)
- Test: `tests/test_grouping.py` (파일 끝), `tests/test_e2e.py` (파일 끝)

**Interfaces:**
- Consumes: `grouping.normalize_target(wafers: list[str]) -> dict` — 반환 dict 에 **`"eds_error": str | None` 키가 추가된다.** 기존 키(`mode`·`target_group`·`siblings`·`unmatched_siblings`·`unknown_wafers`·`isolated`)는 그대로다.
- Produces: 새 `finalize_status` 값 `"eds_index_missing"`. `generate_report(finalize_status="eds_index_missing", ...)` 는 "분석 미수행 — 입력 wafer 가 EDS 인덱스에 없다" 로 시작하는 결론을 낸다.

**배경 (구현자용):** EDS 유사맵 인덱스(hnswlib)와 yield DB 는 별도 시스템이다. 한 장 입력일 때만 EDS 형제 묶기를 하는데(`normalize_target` 의 `mode == "single"` 분기), 입력 wafer 가 yield DB 에는 있고 EDS 인덱스에는 없으면 `LocalEDSSearcher` 가 `KeyError` 를, `HttpEDSSearcher` 가 requests 예외를 던져 **그래프 전체가 예외 종료**한다. 리포트도 감사 기록도 안 남는다. 역방향(EDS 엔 있고 DB 엔 없는 형제)은 이미 `unmatched_siblings` 로 해소돼 있다.

`normalize_target` 은 결정론적 계산만 하고 그래프 흐름을 모른다 — 그래서 여기서는 **사실만 보고**하고, 조기 출구 판정은 `status_node` 가 한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다 (정규화 계층)**

`tests/test_grouping.py` 파일 끝에 추가:

```python
def test_eds_index_miss_is_reported_not_raised(monkeypatch):
    """yield DB 엔 있지만 EDS 인덱스엔 없는 wafer — 예외가 아니라 사실로 보고한다.

    LocalEDSSearcher 는 KeyError, HttpEDSSearcher 는 requests 예외를 던진다.
    정규화 계층은 흐름을 정하지 않는다(판단은 status_node).
    """
    class _Missing:
        def search(self, wafer_id, k):
            raise KeyError(wafer_id)

    monkeypatch.setattr(grouping, "_searcher", _Missing())
    res = grouping.normalize_target(["W2406_02"])
    assert res["eds_error"] is not None
    assert "KeyError" in res["eds_error"]
    assert res["siblings"] == []
    assert res["isolated"] is False        # '형제 없음' 과 '조회 실패' 는 다르다
    assert res["target_group"] == ["W2406_02"]


def test_normal_path_reports_no_eds_error():
    res = grouping.normalize_target(["W2406_02"])
    assert res["eds_error"] is None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_grouping.py -q -k "eds_index_miss or no_eds_error"`
Expected: 첫 테스트는 `KeyError: 'W2406_02'` 로 에러, 둘째는 `KeyError: 'eds_error'` 로 실패.

- [ ] **Step 3: 최소 구현 (정규화 계층)**

`tools/grouping.py` 의 `normalize_target` 에서 `unmatched = []` 부터 `return` 까지를 아래로 바꾼다:

```python
    unmatched = []
    eds_error = None
    if mode == "single" and not unknown:
        try:
            cands = _searcher_lazy().search(wafers[0], k=config.SIBLING_SEARCH_K)
        except Exception as e:
            # yield DB 엔 있으나 EDS 인덱스엔 없는 wafer (local=KeyError, http=요청 예외).
            # 입력 실수가 아니라 인덱스↔DB 동기화 문제다 — 흐름 판단은 status_node 가 한다.
            cands, eds_error = [], f"{type(e).__name__}: {e}"
        raw = [c for c in cands if c["similarity"] >= config.SIBLING_MIN_SIMILARITY]
        # EDS 인덱스와 yield DB 는 별도 시스템이라 동기화가 어긋날 수 있다.
        # yield DB 에 실재하는 형제만 분석 대상에 넣고, 미확인분은 unmatched_siblings 로 분리한다
        # (없는 wafer 를 target 에 넣으면 뒤 tool 들이 조용히 빈 데이터를 반환해 오분석된다).
        confirmed = {r["wafer_id"] for r in yt.get_wafers([c["wafer_id"] for c in raw])}
        siblings = [c for c in raw if c["wafer_id"] in confirmed]
        unmatched = [c["wafer_id"] for c in raw if c["wafer_id"] not in confirmed]
        target = wafers + [s["wafer_id"] for s in siblings]   # 입력 선두 + 유사도 내림차순
        isolated = not siblings and eds_error is None         # 조회 실패는 '고립' 이 아니다

    return {
        "mode": mode,
        "target_group": target,
        "siblings": siblings,
        "unmatched_siblings": unmatched,
        "unknown_wafers": unknown,
        "isolated": isolated,
        "eds_error": eds_error,
    }
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_grouping.py -q`
Expected: 전부 passed (기존 11 + 신규 2)

- [ ] **Step 5: 실패하는 테스트를 쓴다 (그래프 전체)**

`tests/test_e2e.py` 파일 끝에 추가:

```python
def test_eds_index_miss_ends_with_report_not_crash(monkeypatch):
    """EDS 인덱스에 없는 wafer 를 넣어도 그래프가 예외로 죽지 않는다.

    '입력 wafer 가 없다(unknown_target)' 와 사유가 다르다 — 이쪽은 인덱스↔DB
    동기화 문제라 사람이 할 조치가 다르다.
    """
    from tools import grouping

    class _Missing:
        def search(self, wafer_id, k):
            raise KeyError(wafer_id)

    monkeypatch.setattr(grouping, "_searcher", _Missing())
    state = build_graph().invoke(
        {"target_wafers": ["W2406_02"], "target_source": "manual"}
    )
    assert state["finalize_status"] == "eds_index_missing"
    assert state["report"]
    assert "EDS 인덱스" in state["report"]
    assert state["findings"]                  # 감사 기록이 끊기지 않는다
```

- [ ] **Step 6: 실패를 확인한다**

Run: `python -m pytest tests/test_e2e.py -q -k eds_index_miss`
Expected: FAIL — `KeyError: 'W2406_02'` 가 그래프 밖으로 튀어나온다.

- [ ] **Step 7: 최소 구현 (조기 출구 + 리포트 문구)**

`graph/nodes.py` 의 `status_node` 에서 `unknown_wafers` 분기와 `isolated` 분기 **사이에** 삽입한다:

```python
    if norm["eds_error"]:
        summary = (f"분석 대상 입력 ({source}): {', '.join(targets)}\n"
                   f"EDS 인덱스 조회 실패: {norm['eds_error']} — "
                   f"wafer 는 yield DB 에 있으나 유사맵 인덱스에 없다.")
        return {"target_group": norm["target_group"], "control_group": [],
                "status_summary": summary, "findings": findings,
                "finalize_status": "eds_index_missing"}
```

`llm/client.py` 의 `generate_report` 에서 `elif finalize_status == "unknown_target":` 분기 **바로 뒤에** 삽입한다:

```python
        elif finalize_status == "eds_index_missing":
            conclusion = ("분석 미수행 — 입력 wafer 가 EDS 인덱스에 없다 "
                          "(yield DB 에는 존재). 인덱스와 yield DB 동기화를 확인하라.")
```

- [ ] **Step 8: 통과 확인 + 전체 회귀**

Run: `python -m pytest -q`
Expected: 164 passed (161 + 신규 3)

- [ ] **Step 9: 커밋**

```bash
git add tools/grouping.py graph/nodes.py llm/client.py tests/test_grouping.py tests/test_e2e.py
git commit -F - <<'EOF'
fix: EDS 인덱스에 없는 wafer 로 그래프가 죽던 것 (미룸 9번)

yield DB 엔 있고 EDS 인덱스엔 없는 wafer 를 한 장 넣으면 KeyError(local) /
requests 예외(http)로 그래프 전체가 예외 종료했다. 리포트도 감사 기록도 안 남았다.

normalize_target 이 eds_error 사실만 보고하고(흐름 판단은 status_node),
전용 조기 출구 eds_index_missing 으로 끝낸다 — unknown_target 재사용이 아니다.
'wafer 가 없다' 와 '인덱스에 안 실렸다' 는 사람이 할 조치가 다르다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: mock 각본이 tool 실패 문자열에 죽지 않게

**Files:**
- Modify: `llm/client.py:78` (1단 소비부), `llm/client.py:163-166` (`_result`)
- Modify: `tools/agent_tools.py` (파일 끝 개행)
- Test: `tests/test_mock_llm.py` (파일 끝)

**Interfaces:**
- Consumes: `ScriptedMockLLMClient.analyze_step(messages: list) -> AIMessage`, `_result(tool_msgs, name)` — 시그니처 그대로.
- Produces: `_result` 는 **dict 를 보장한다** (비-dict 은 `{}`). 이후 Task 는 없다.

**배경 (구현자용):** `graph/nodes.py` 의 `tools_node` 는 tool 실행이 실패하면 결과를 **문자열**(`"오류: ... 다시 호출하라."`)로 ToolMessage 에 담는다 — LLM 이 스스로 교정하게 하는 표준 패턴이고 이미 구현된 기능이다(미룸 1번). 그런데 mock 의 `_result` 는 `json.loads` 결과가 dict 라고 가정하고, 호출부가 `res["candidates"]` 로 바로 파고들어 `TypeError` 로 죽는다. 즉 mock 만 그 복구 경로를 못 탄다.

고칠 자리는 두 곳뿐이다. 2단 소비부는 이미 `sensor.get("status") != "ok"` 로 분기하므로 `{}` 를 그대로 흡수한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_mock_llm.py` 파일 끝에 추가:

```python
def test_scripted_survives_tool_error_string():
    """tools 노드는 실행 실패 시 오류 '문자열' 을 담는다 — 각본이 거기서 죽으면 안 된다.

    도구가 실패하면 '분리되는 후보가 없다' 와 같은 경로를 타 낮은 확신도로 물러선다.
    """
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]
    ai = llm.analyze_step(msgs)                      # 1) 조기 finalize
    msgs += [ai, _tm("finalize", "반려")]
    ai = llm.analyze_step(msgs)                      # 2) 1단 호출
    assert ai.tool_calls[0]["name"] == "hyp_eqp_ch_commonality"
    msgs += [ai, _tm("hyp_eqp_ch_commonality",
                     "오류: hyp_eqp_ch_commonality 실행 실패 (KeyError: 'legend'). "
                     "인자를 확인하고 다시 호출하라.")]

    ai = llm.analyze_step(msgs)                      # 3) 죽지 않고 물러선다
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] < 0.8
    assert ai.content
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_mock_llm.py -q -k survives_tool_error`
Expected: FAIL — `TypeError: string indices must be integers` (`res["candidates"]`, `llm/client.py:78`)

- [ ] **Step 3: 최소 구현**

`llm/client.py:78` 을 바꾼다:

```python
        passing = [c for c in res.get("candidates", []) if c["passes"]]
```

`llm/client.py` 의 `_result` 를 바꾼다:

```python
    @staticmethod
    def _result(tool_msgs, name):
        msg = next(m for m in reversed(tool_msgs) if m.name == name)
        res = json.loads(msg.content)
        # tools 노드는 실행 실패 시 오류 '문자열' 을 담는다 (dict 가정이 깨지는 유일한 경로).
        # 각본이 죽는 대신 '결과 없음' 으로 취급해 낮은 확신도 후퇴 분기를 타게 한다.
        return res if isinstance(res, dict) else {}
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_mock_llm.py -q`
Expected: 전부 passed

- [ ] **Step 5: `tools/agent_tools.py` 파일 끝 개행**

파일 마지막 줄 `TOOLS_BY_NAME = {t.name: t for t in ANALYSIS_TOOLS}` 뒤에 개행 하나를 넣는다. 다른 변경은 하지 않는다.

확인: `python -c "print(open('tools/agent_tools.py', encoding='utf-8').read().endswith('\n'))"` → `True`

- [ ] **Step 6: 전체 회귀**

Run: `python -m pytest -q`
Expected: 165 passed (164 + 신규 1)

- [ ] **Step 7: 커밋**

```bash
git add llm/client.py tools/agent_tools.py tests/test_mock_llm.py
git commit -F - <<'EOF'
fix: mock 각본이 tool 실패 문자열에 죽던 것 + 파일 끝 개행

tools 노드는 실행 실패 시 오류 문자열을 ToolMessage 에 담는데(미룸 1번의 복구 경로),
_result 가 dict 를 가정해 각본만 그 경로를 못 타고 TypeError 로 죽었다.
비-dict 은 {} 로 흡수해 '후보 없음' 후퇴 분기(확신도 0.2)를 타게 한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## 완료 확인 (전 Task 종료 후)

- [ ] `python -m pytest -q` → **165 passed**
- [ ] `python main.py` (또는 기존 데모 실행 경로)의 출력이 `README.md` 의 데모 블록과 여전히 일치 — 정상 경로 불변 확인
- [ ] `git log --oneline main..HEAD` → spec 1개 + 구현 3개 = 커밋 4개
- [ ] 병합은 하지 않는다. 사용자에게 리뷰/병합 여부를 묻는다.
