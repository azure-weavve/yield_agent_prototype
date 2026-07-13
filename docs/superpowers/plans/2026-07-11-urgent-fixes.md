# 시급 결함 4건 수정 + 사내 연동 미룸 항목 문서화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 리뷰(Claude + codex)에서 확정된 시급 결함 4건(빈 lot 크래시, HTTP EDS 계약 위반, MAX_LOOPS 가드레일 불일치, README 과장 문구)을 수정하고, 사내 연동 시점으로 미룬 항목을 `docs/deferred-internal-integration.md` 로 정리한다.

**Architecture:** 기존 하이브리드 그래프(status → analyze ⇄ tools → report)의 골격은 유지한다. Task 1 은 status 뒤에 조건부 엣지 하나를 추가해 "이상 없음"을 안전 종료 경로로 만들고, Task 3 은 MAX_LOOPS 가드레일을 `_after_analyze`(analyze 7회 허용 버그)에서 `_after_tools`(정확히 6회)로 옮겨 finalize 게이트의 강제 승인 경로와 일치시킨다. Task 2 는 HTTP 구현이 인터페이스 docstring 계약(자기 자신 제외 + 최소 유사도 필터)을 로컬 구현과 동일하게 지키게 한다.

**Tech Stack:** Python 3.11, LangGraph, pytest, hnswlib(로컬 EDS), requests(HTTP EDS)

## Global Constraints

- Python 3.11, 테스트는 저장소 루트(prototype/)에서 `pytest` 로 실행
- 주석·docstring·테스트 이름은 기존 코드와 같이 한국어 스타일 유지
- 수술적 변경: 각 Task 의 변경 라인은 해당 결함 수정에만 해당해야 함 (인접 코드 리팩터링 금지)
- 커밋 메시지는 기존 히스토리 스타일(`fix:`, `docs:`, `test:` + 한국어 요약)을 따르고, 말미에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 추가
- 각 Task 완료 시 `pytest` 전체가 통과해야 함 (기존 28개 + 신규)

---

### Task 1: 빈 lot 안전 종료 (status_node IndexError 수정)

수율 임계 미만 lot 이 하나도 없으면 `status_node` 가 `lots[0]` 에서 `IndexError` 로 죽는다.
빈 경우 분석 루프를 건너뛰고 "이상 없음" 리포트로 조기 종료하는 경로를 만든다.

**Files:**
- Modify: `graph/nodes.py:32-50` (status_node)
- Modify: `graph/build.py` (`_after_status` 조건부 엣지 추가)
- Modify: `llm/client.py:104` (mock 리포트 결론 fallback 문구 일반화), `llm/client.py:160` (openai 프롬프트 동일)
- Modify: `main.py:24` (대상 없음 출력 처리)
- Test: `tests/test_e2e.py` (신규 테스트 추가)

**Interfaces:**
- Consumes: `yt.find_low_yield_lots() -> list[dict]` (기존)
- Produces: `status_node` 가 lot 부재 시 `{"target_wafer": "", "status_summary": str, "findings": [loop-0 finding]}` 반환. `graph.build._after_status(state) -> "analyze" | "report"`. Task 3 은 이 build.py 를 이어서 수정하므로 함수명 `_after_status` 를 그대로 사용해야 한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_e2e.py` 끝에 추가:

```python
def test_no_low_yield_lots_short_circuits_to_report(monkeypatch):
    """수율 이상 lot 이 없으면 크래시 없이 '이상 없음' 리포트로 조기 종료한다."""
    from graph import nodes

    monkeypatch.setattr(nodes.yt, "find_low_yield_lots", lambda: [])
    state = build_graph().invoke({"question": "이번 배치 수율 이상 분석해줘"})

    assert state["report"]                       # 크래시 없이 리포트 도달
    assert state["target_wafer"] == ""           # 분석 대상 없음
    assert "없음" in state["status_summary"]      # "수율 임계 미만인 lot 없음."
    # 분석 루프는 돌지 않았다 — 감사 기록은 현황 파악뿐
    assert [f["tool"] for f in state["findings"]] == ["find_low_yield_lots"]
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `pytest tests/test_e2e.py::test_no_low_yield_lots_short_circuits_to_report -v`
Expected: FAIL — `IndexError: list index out of range` (graph/nodes.py:34 의 `lots[0]`)

- [ ] **Step 3: status_node 수정**

`graph/nodes.py` 의 `status_node` 를 다음으로 교체:

```python
def status_node(state: dict) -> dict:
    lots = yt.find_low_yield_lots()
    summary = _summarize_lots(lots)
    finding = {
        "loop": 0, "tool": "find_low_yield_lots", "args": {},
        "result": lots, "thought": "현황 파악 (고정 골격)",
    }
    if not lots:  # 이상 lot 없음 → 분석 루프 없이 리포팅으로 (build 의 _after_status)
        return {"target_wafer": "", "status_summary": summary, "findings": [finding]}

    target = lots[0]["worst_wafer"]["wafer_id"]
    seed = [
        SystemMessage(content=ANALYZE_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"현황:\n{summary}\n\n대상 wafer: {target}\n질문: {state['question']}"
        )),
    ]
    return {
        "messages": seed,
        "target_wafer": target,
        "status_summary": summary,
        "findings": [finding],
    }
```

- [ ] **Step 4: build.py 에 조건부 엣지 추가**

`graph/build.py` 의 `_after_analyze` 위에 추가:

```python
def _after_status(state: dict) -> str:
    # 이상 lot 이 없으면 분석 루프를 건너뛰고 바로 리포팅 (빈 lots 크래시 방지)
    return "analyze" if state.get("target_wafer") else "report"
```

`build_graph()` 안의 `g.add_edge("status", "analyze")` 를 다음으로 교체:

```python
    g.add_conditional_edges("status", _after_status, ["analyze", "report"])
```

- [ ] **Step 5: 결론 fallback 문구 일반화**

hypothesis 부재가 "최대 횟수 도달"만이 아니게 되므로 문구를 일반화한다.
`llm/client.py:104`:

```python
        conclusion = hypothesis or "원인 미확정"
```

`llm/client.py:160` (openai 사용자 프롬프트):

```python
            f"결론 가설: {hypothesis or '미확정'} / 확신도: {confidence}"
```

- [ ] **Step 6: main.py 출력 처리**

`main.py:24` 를 다음으로 교체:

```python
    print(f"[분석 대상] {state['target_wafer'] or '없음 (수율 이상 lot 없음)'}\n")
```

- [ ] **Step 7: 전체 테스트 통과 확인**

Run: `pytest -v`
Expected: 전체 PASS (기존 28 + 신규 1). 특히 `test_generate_report_handles_no_hypothesis` 는 `"미확정" in report` 만 확인하므로 문구 일반화 후에도 통과한다.

- [ ] **Step 8: Commit**

```bash
git add graph/nodes.py graph/build.py llm/client.py main.py tests/test_e2e.py
git commit -m "fix: 수율 이상 lot 부재 시 IndexError 대신 '이상 없음' 리포트로 안전 종료

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: HttpEDSSearcher 인터페이스 계약 준수

`EDSSearcher.search` docstring 은 "자기 자신 제외 + `EDS_MIN_SIMILARITY` 미만 제외"를
계약으로 명시하지만 `HttpEDSSearcher` 는 서버 응답을 그대로 반환한다.
로컬 구현과 동일한 필터링을 적용한다 (`score=None` 방어 포함).

**Files:**
- Modify: `tools/eds_search.py:66-83` (HttpEDSSearcher.search)
- Test: `tests/test_eds_search.py` (신규 파일)

**Interfaces:**
- Consumes: `config.EDS_HTTP_URL`, `config.EDS_HTTP_VERIFY`, `config.EDS_MIN_SIMILARITY` (기존, 값 변경 없음)
- Produces: `HttpEDSSearcher.search(wafer_id, k) -> list[{"wafer_id": str, "similarity": float}]` — 자기 자신·`score None`·`EDS_MIN_SIMILARITY` 미만 제외, 최대 k 건 (LocalEDSSearcher 와 동일 계약)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_eds_search.py` 신규 생성:

```python
"""HttpEDSSearcher 가 인터페이스 계약(자기 자신 제외, 최소 유사도 필터)을 지키는지.

LocalEDSSearcher 는 hnswlib 인덱스 생성물이 필요하므로 여기서는 다루지 않고
(E2E 가 커버), 사내 전환 시 달라질 수 있는 HTTP 구현만 가짜 응답으로 검증한다.
"""

import requests

import config
from tools.eds_search import HttpEDSSearcher


class _FakeResp:
    def __init__(self, results):
        self._results = results

    def raise_for_status(self):
        pass

    def json(self):
        return {"results": self._results}


def _patch_post(monkeypatch, results):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _FakeResp(results))


def test_http_search_excludes_self_low_similarity_and_none_score(monkeypatch):
    _patch_post(monkeypatch, [
        {"wafer_id": "W1", "score": 1.0},    # 자기 자신 → 제외
        {"wafer_id": "W2", "score": 0.92},
        {"wafer_id": "W3", "score": 0.10},   # EDS_MIN_SIMILARITY(0.5) 미만 → 제외
        {"wafer_id": "W4", "score": None},   # score 없음 → 제외
        {"wafer_id": "W5", "score": 0.88},
    ])
    out = HttpEDSSearcher().search("W1", k=5)
    assert [r["wafer_id"] for r in out] == ["W2", "W5"]
    assert all(r["similarity"] >= config.EDS_MIN_SIMILARITY for r in out)


def test_http_search_truncates_to_k(monkeypatch):
    _patch_post(monkeypatch, [
        {"wafer_id": f"W{i}", "score": 0.9 - i * 0.01} for i in range(2, 8)
    ])
    out = HttpEDSSearcher().search("W1", k=3)
    assert len(out) == 3
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `pytest tests/test_eds_search.py -v`
Expected: FAIL — 첫 테스트에서 자기 자신(W1)·저유사도(W3)가 결과에 포함되어 assertion 실패

- [ ] **Step 3: HttpEDSSearcher.search 수정**

`tools/eds_search.py` 의 `HttpEDSSearcher.search` 를 다음으로 교체:

```python
    def search(self, wafer_id: str, k: int = 5) -> list[dict]:
        import requests

        resp = requests.post(
            config.EDS_HTTP_URL,
            json={"wafer_id": wafer_id, "k": k + 1},  # 자기 자신 포함 응답 대비 여유분
            verify=config.EDS_HTTP_VERIFY,  # 운영 전환 시 .pem 경로로
            timeout=10,
        )
        resp.raise_for_status()
        # 사내 응답 스키마에 맞춰 매핑 (실제 필드명 확인 후 조정)
        # 인터페이스 계약: 자기 자신 제외 + EDS_MIN_SIMILARITY 미만 제외 (Local 과 동일)
        out = []
        for r in resp.json()["results"]:
            cand, score = r["wafer_id"], r.get("score")
            if cand == wafer_id or score is None:
                continue
            sim = round(float(score), 3)
            if sim < config.EDS_MIN_SIMILARITY:
                continue
            out.append({"wafer_id": cand, "similarity": sim})
            if len(out) == k:
                break
        return out
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `pytest -v`
Expected: 전체 PASS (신규 2개 포함)

- [ ] **Step 5: Commit**

```bash
git add tools/eds_search.py tests/test_eds_search.py
git commit -m "fix: HTTP EDS 구현이 인터페이스 계약(자기 자신·최소 유사도 필터) 준수

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: MAX_LOOPS 가드레일 단일화 (실질 7회 → 정확히 6회)

현재 가드레일이 두 곳에서 다르게 판정된다: `_finalize_gate` 는 `loop >= 6` 강제 승인,
`_after_analyze` 는 `loop_count > 6` 차단 — LLM 이 finalize 를 제안하지 않으면 analyze 가
7번째까지 호출되어 README 의 "기본 6회"와 어긋난다.

**주의:** 단순히 `>` 를 `>=` 로 바꾸면 안 된다 — 그러면 6번째 analyze 의 tool call(finalize
제안 포함)이 실행되지 못하고 버려져, 게이트의 "최대 횟수 도달" 승인 경로가 죽는다.
올바른 수정은 가드레일을 `_after_tools` 로 옮기는 것이다: 6번째 순환의 tool 은 실행되고
(게이트가 finalize 를 강제 승인할 수 있고), finalize 없이 6회를 채우면 리포팅으로 넘어간다.

**Files:**
- Modify: `graph/build.py` (`_after_analyze` 에서 루프 검사 제거, `_after_tools` 로 이동, 모듈 docstring 다이어그램 갱신)
- Modify: `README.md:72-79` (아키텍처 다이어그램의 "한계" 분기 위치 정정)
- Test: `tests/test_build.py` (기존 3개 수정·교체)

**Interfaces:**
- Consumes: `config.MAX_LOOPS` (기존, 값 변경 없음), Task 1 이 추가한 `_after_status` (그대로 유지)
- Produces: `_after_tools(state) -> "report" | "analyze"` — `finalize_accepted` 또는 `loop_count >= MAX_LOOPS` 면 report. `_after_analyze` 는 tool call 유무만 판단.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_build.py` 에서 `test_analyze_over_max_loops_forced_to_report` 를 삭제하고,
기존 `_after_tools` 테스트 2개를 수정, 신규 1개를 추가한다. 최종 파일 전체:

```python
"""라우팅 함수(순환/종료 판단) 검증. E2E 는 tests/test_e2e.py 에서."""

from langchain_core.messages import AIMessage

from graph.build import _after_analyze, _after_tools

import config


def _ai(with_call: bool):
    calls = [{"name": "get_wafer", "args": {"wafer_id": "W"}, "id": "c1"}] if with_call else []
    return AIMessage(content="생각", tool_calls=calls)


def test_analyze_with_tool_call_continues():
    assert _after_analyze({"messages": [_ai(True)], "loop_count": 2}) == "tools"


def test_analyze_without_tool_call_exits():
    # tool 도 finalize 도 없이 텍스트만 낸 이탈 케이스 → 리포팅으로 (안전망)
    assert _after_analyze({"messages": [_ai(False)], "loop_count": 2}) == "report"


def test_tools_accepted_goes_report():
    assert _after_tools({"finalize_accepted": True, "loop_count": 3}) == "report"


def test_tools_not_accepted_loops_back():
    assert _after_tools({"loop_count": 2}) == "analyze"


def test_tools_at_max_loops_forced_to_report():
    # 가드레일: finalize 없이 MAX_LOOPS 를 채우면 강제로 리포팅 (정확히 6회에서 멈춘다)
    assert _after_tools({"loop_count": config.MAX_LOOPS}) == "report"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `pytest tests/test_build.py -v`
Expected: `test_tools_at_max_loops_forced_to_report` FAIL ("analyze" 반환),
`test_tools_not_accepted_loops_back` FAIL (`KeyError: 'loop_count'` 아님 — 현재 구현은 loop_count 를 안 보므로 "analyze" 를 반환해 통과할 수 있음. 신규 테스트 1개의 FAIL 만 확인하면 된다)

- [ ] **Step 3: build.py 라우팅 수정**

`graph/build.py` 의 `_after_analyze`, `_after_tools` 를 다음으로 교체:

```python
def _after_analyze(state: dict) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return "report"  # tool 호출 없이 텍스트만 = 이탈 케이스 → 리포팅 (안전망)


def _after_tools(state: dict) -> str:
    if state.get("finalize_accepted"):
        return "report"
    if state["loop_count"] >= config.MAX_LOOPS:  # 가드레일: 무한루프 차단 (정확히 MAX_LOOPS 회)
        return "report"
    return "analyze"
```

모듈 docstring 의 다이어그램(3~8행)을 다음으로 교체:

```python
"""그래프 조립 — 하이브리드 분석 루프.

  status ──(대상 있음)──▶ analyze ──(tool call)──▶ tools ──(반려/계속)──▶ analyze   ← 순환
   (고정)      │              │                      │
               │              └─(호출 없음)          └─(finalize 승인/한계)
               └─(대상 없음)         ▼                      ▼
                      ▼            report ◀────────────────┘
                      └─────────────▶ (고정)

골격(status→…→report)은 고정 엣지, analyze ⇄ tools 만 LLM 자율 순환.
종료는 tools 노드의 finalize 게이트(확신도)와 _after_tools 의 MAX_LOOPS 가드레일이 통제한다.
"""
```

- [ ] **Step 4: README 다이어그램 정정**

`README.md` 72~79행의 다이어그램을 다음으로 교체 ("한계" 분기를 analyze 쪽에서 tools 쪽으로):

```
status ──▶ analyze ──(tool call)──▶ tools ──(반려/계속)──▶ analyze   ← 순환
 (고정)        │                      │
               └─(호출 없음)           └─(finalize 승인/한계 도달)
                      ▼                      ▼
                    report ◀────────────────┘
                     (고정)
```

- [ ] **Step 5: 전체 테스트 통과 확인**

Run: `pytest -v`
Expected: 전체 PASS. `tests/test_e2e.py` 의 `assert state["loop_count"] <= 6` 도 여전히 통과 (mock 은 5회에 종료).

- [ ] **Step 6: Commit**

```bash
git add graph/build.py tests/test_build.py README.md
git commit -m "fix: MAX_LOOPS 가드레일을 _after_tools 로 단일화 (실질 7회 순환 → 정확히 6회)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: README 과장 문구 정정 + 사내 연동 미룸 항목 문서

openai 모드에서는 리포트 본문을 LLM 이 자유 생성하므로 "환각 수치 구조적 차단"은
mock 모드에만 성립한다 — 주장을 정확하게 낮춘다. 그리고 사내 연동 시점으로 미룬
항목들을 `docs/deferred-internal-integration.md` 로 남긴다.

**Files:**
- Modify: `README.md:84` (구조적 차단 문구), `README.md:86-95` (분석 루프 절에 이상-없음 경로 한 줄), `README.md:141-146` (한계 절에 미룸 문서 링크)
- Create: `docs/deferred-internal-integration.md`

**Interfaces:**
- Consumes: Task 1~3 의 수정 결과 (문서가 코드 현실과 일치해야 함)
- Produces: `docs/deferred-internal-integration.md` — 사내 연동 착수 시 작업 목록의 단일 출처

- [ ] **Step 1: README 구조적 차단 문구 정정**

`README.md` 84행:

```markdown
- **LLM은 판단과 표현만** 담당합니다. 수치는 tool 결과에서만 나오며 — mock 리포트는
  템플릿 렌더링이라 수치 변형이 구조적으로 불가능하고, openai 리포트는 프롬프트로 인용을
  강제하되 감사 기록(findings) 원본이 함께 남아 수치를 대조·검증할 수 있습니다.
```

- [ ] **Step 2: README 분석 루프 절에 이상-없음 경로 추가**

`README.md` "분석 루프" 절의 가드레일 항목 아래에 추가:

```markdown
- **이상 없음 경로**: 수율 임계 미만 lot 이 없으면 분석 루프 없이 "이상 없음" 리포트로
  조기 종료합니다.
```

- [ ] **Step 3: README 한계 절에 미룸 문서 링크 추가**

`README.md` "한계와 다음 단계" 절 마지막에 추가:

```markdown
- 사내 연동 시점으로 미룬 항목(오류 복구, 게이트 증거 조건, TLS 검증 등)은
  [docs/deferred-internal-integration.md](docs/deferred-internal-integration.md) 참고.
```

- [ ] **Step 4: 미룸 항목 문서 작성**

`docs/deferred-internal-integration.md` 신규 생성:

```markdown
# 사내 연동 시 처리할 미룸 항목

2026-07-11 리뷰(Claude + codex 교차 검증)에서 확인했으나, 실행 경로가 사내 연동
(`LLM_MODE=openai` / `EDS_MODE=http`) 전에는 없어 의도적으로 미룬 항목들.
**사내 연동 착수 시 이 문서를 작업 목록으로 사용한다.** 1~2번은 연동 첫날 필수.

## 1. tool 호출 오류를 복구 가능한 ToolMessage 로 변환 (필수)

- 위치: `graph/nodes.py` `tools_node` — `TOOLS_BY_NAME[call["name"]]` 직접 인덱싱, `.invoke()` 무방비
- 문제: 실제 LLM 이 없는 tool 이름을 내거나 인자 스키마를 벗어나면 KeyError/ValidationError 로 그래프 전체가 예외 종료
- 처방: 예외를 잡아 오류 내용을 ToolMessage 로 반환 → LLM 이 다음 analyze 에서 스스로 교정 (tool-calling 루프 표준 패턴)

## 2. finalize confidence 비숫자 방어 (필수)

- 위치: `graph/nodes.py` `_finalize_gate` — `float(args.get("confidence", 0.0))`
- 문제: LLM 이 `"high"` 같은 비숫자를 주면 ValueError 크래시
- 처방: 변환 실패 시 0.0 취급 + 반려 메시지에 "confidence 는 0~1 숫자" 명시

## 3. 게이트에 결정론적 증거 조건 추가 (codex 3번, 설계 개선)

- 위치: `graph/nodes.py` `_finalize_gate`
- 문제: 승인 기준이 LLM 자기 신고 confidence 뿐 — MAX_LOOPS 도달 시엔 근거 품질 무관 승인
- 처방: findings 에서 결정론적 증거(공정 로그 in_spec=False 행 존재, 유사 사례 수 등)를 게이트 조건에 포함. "수치는 결정론, LLM 은 판단" 철학과 일치
- 참고: MAX_LOOPS 강제 종료 시 "승인"이 아니라 "미확정(한계 도달)"으로 구분 기록하는 것도 함께 검토

## 4. TLS 검증 기본값을 켜짐으로 (codex 4번)

- 위치: `config.py` `EDS_HTTP_VERIFY = False`
- 문제: http 모드를 켜는 것만으로 인증서 검증 없이 사내 데이터 전송
- 처방: 사내 루트 인증서(.pem) 확보 → `EDS_HTTP_VERIFY = "인증서경로"` 를 기본값으로, 우회는 개발 환경에서만 명시적으로

## 5. finalize 승인 후 같은 메시지의 후속 tool 실행 중단 (codex 6번)

- 위치: `graph/nodes.py` `tools_node` 의 for 루프
- 문제: 한 AIMessage 에 finalize + 다른 tool 이 오면 승인 후에도 나머지가 실행되고, finalize 2개면 뒤가 앞을 덮어씀
- 처방: 승인 즉시 루프 중단(잔여 call 은 "종료로 생략" ToolMessage 처리) 또는 finalize 는 단독 호출만 허용하도록 사전 검증

## 6. HTTP EDS 응답 스키마 실측 검증

- 위치: `tools/eds_search.py` `HttpEDSSearcher` — 필드명(`wafer_id`/`score`)이 추정값
- 처방: 사내 `/search` 실제 응답으로 매핑 확정 + 오류 응답(4xx/5xx, 타임아웃) 처리 방침 결정

## 7. 실패 경로 테스트 확충 (codex 7번)

- 현재 테스트는 mock 정상 경로 중심. 연동 시 추가할 것: 알 수 없는 tool 이름 복구(1번),
  비숫자 confidence(2번), tool 실행 실패, MAX_LOOPS 강제 종료 시 리포트 내용, HTTP 오류 응답
- 실제 LLM 을 붙인 통합 테스트(별도 마커로 분리) 1본 이상

## 8. 기타 경미 (여유 있을 때)

- `config.py` 상수의 환경변수 오버라이드 (`os.getenv`) — 코드 수정 없는 모드 전환
- `tools/yield_tools.py` `find_low_yield_lots` 기본 인자가 import 시점 바인딩 — 런타임 threshold 변경이 기본값에 반영 안 됨
- `graph/nodes.py` 모듈 레벨 `_llm = get_llm()` — import 시점에 구현 고정, 지연 획득으로 전환하면 테스트·모드 전환 유연
```

- [ ] **Step 5: 전체 테스트 통과 확인**

Run: `pytest -v`
Expected: 전체 PASS (문서만 변경이므로 회귀 없음)

- [ ] **Step 6: Commit**

```bash
git add README.md docs/deferred-internal-integration.md
git commit -m "docs: 수치 차단 주장 정정 + 사내 연동 미룸 항목 문서화

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
