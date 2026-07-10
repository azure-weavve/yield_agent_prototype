# 하이브리드 분석 루프 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 고정 경로 프로토타입을 하이브리드 분석 Agent로 교체한다 — 골격(현황파악→리포팅)은 고정 엣지, 중간 분석은 LLM 주도 tool-calling 순환 루프(finalize 게이트 + 감사 기록).

**Architecture:** `status(고정) → analyze(LLM) ⇄ tools(실행+기록+게이트) → report(고정)`. LLM은 `bind_tools`로 분석 tool 4개 + `finalize(hypothesis, confidence)`를 받고, tool 호출 = 순환, finalize 호출 = 코드가 confidence≥0.8 검사 후 승인/반려. 모든 tool 실행은 tools 노드가 `findings`에 감사 기록으로 남긴다. 상태는 누적형(`add_messages` + `operator.add`).

**Tech Stack:** Python 3.11, langgraph 1.2.6, langchain-core(@tool, messages), hnswlib, SQLite, pytest

## Global Constraints

- **LLM은 숫자를 만들지 않는다**: 모든 수치는 결정론적 tool(SQLite/hnswlib)이 산출. LLM은 판단·표현만.
- **사내망 밖 데모 성립**: `LLM_MODE="mock"`(스크립트형 mock)으로 전체 루프가 End-to-End로 돌아야 한다. OpenAI 호환 구현도 함께 유지.
- **더미 데이터는 seed=42 결정론**: `data/generate_dummy.py` 재실행 시 항상 같은 결과.
- **기존 고정 경로(intent→tool→answer)는 대체**: `classify_intent`/`ROUTE_*`/기존 노드·라우팅은 제거한다 (사용자 결정).
- **주석·docstring은 한국어**, 기존 코드 스타일(설명형 모듈 docstring + 섹션 주석) 유지.
- 실행 시 한글 깨짐 방지: `PYTHONUTF8=1` (README 유지 사항).

## 파일 구조

| 파일 | 처리 | 책임 |
|------|------|------|
| `data/generate_dummy.py` | 수정 | process_log 테이블 추가 생성 (패턴 그룹에 "이상 장비 -9" 심기) |
| `tools/yield_tools.py` | 수정 | `get_process_log()` 추가 (기존 함수 유지) |
| `tools/agent_tools.py` | 신규 | @tool 래퍼 5개 (분석 4 + finalize), LLM이 읽는 스키마 |
| `config.py` | 수정 | `MAX_LOOPS`, `CONFIDENCE_THRESHOLD` 추가 |
| `graph/state.py` | 재작성 | 누적형 상태 (messages reducer, findings, loop_count 등) |
| `llm/client.py` | 재작성 | `analyze_step`/`generate_report` 인터페이스, ScriptedMock + OpenAI |
| `graph/nodes.py` | 재작성 | status / analyze / tools(게이트+감사기록) / report 노드 |
| `graph/build.py` | 재작성 | 순환 그래프 조립 + 조건부 엣지 |
| `main.py` | 재작성 | 단일 질문 실행 + 감사 기록 출력 |
| `tests/` | 신규 | pytest 테스트 일체 |
| `README.md` | 수정 | 새 흐름/실행법 반영 |

**감사 기록(findings) 항목 규격** (모든 태스크가 공유하는 계약):

```python
{
    "loop": int,        # 몇 번째 순환에서 나왔나 (0 = 고정 골격 현황파악)
    "tool": str,        # 실행된 tool 이름 ("finalize" 포함)
    "args": dict,       # tool 인자
    "result": Any,      # tool 반환값 그대로 (finalize 는 게이트 판정 문자열)
    "thought": str,     # 그 시점 LLM 의 가설/이유 (AIMessage.content)
}
```

---

### Task 1: 테스트 환경 구축 + 공정 로그 더미 데이터

**Files:**
- Modify: `requirements.txt`
- Create: `tests/conftest.py`
- Modify: `data/generate_dummy.py`
- Test: `tests/test_dummy_data.py`

**Interfaces:**
- Produces: SQLite `process_log` 테이블 — 컬럼 `(wafer_id TEXT, process_step TEXT, equipment_id TEXT, param_name TEXT, param_value REAL, spec_low REAL, spec_high REAL)`. wafer당 4행(Photo/Etch/Diffusion/CMP). 패턴 그룹 wafer는 자기 그룹의 process_step에서 장비 `{STEP대문자}-9` + 스펙 상한 초과 값, 나머지는 전부 스펙 내.

- [ ] **Step 1: pytest 의존성 추가**

`requirements.txt` 끝에 추가:

```
pytest==8.3.4
```

Run: `pip install pytest==8.3.4`

- [ ] **Step 2: tests/conftest.py 작성 (프로젝트 루트 import 경로)**

```python
"""pytest 공통 설정: 프로젝트 루트를 import 경로에 추가."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 3: 실패하는 테스트 작성**

`tests/test_dummy_data.py`:

```python
"""process_log 더미 데이터 검증.

데모 성립 조건: 패턴 그룹 wafer 는 자기 그룹의 공정 단계에서만
'공유 이상 장비(-9) + 스펙 초과'를 갖고, 정상 wafer 는 전부 스펙 내.
"""

import sqlite3

import config


def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_process_log_table_exists_with_4_rows_per_wafer():
    with _conn() as conn:
        wafers = conn.execute("SELECT COUNT(*) FROM yield").fetchone()[0]
        logs = conn.execute("SELECT COUNT(*) FROM process_log").fetchone()[0]
        assert logs == wafers * 4


def test_pattern_wafer_has_single_anomaly_at_its_step():
    with _conn() as conn:
        # center_spot 그룹 최근 wafer — 그룹 공정은 Etch
        rows = conn.execute(
            "SELECT * FROM process_log WHERE wafer_id = 'W2406_cen0'"
        ).fetchall()
        bad = [r for r in rows if not (r["spec_low"] <= r["param_value"] <= r["spec_high"])]
        assert len(bad) == 1
        assert bad[0]["process_step"] == "Etch"
        assert bad[0]["equipment_id"] == "ETCH-9"


def test_group_members_share_anomaly_equipment():
    with _conn() as conn:
        members = [
            r["wafer_id"]
            for r in conn.execute(
                "SELECT wafer_id FROM yield WHERE defect_type = 'center_spot'"
            ).fetchall()
        ]
        assert len(members) >= 2
        for wid in members:
            bad = conn.execute(
                """
                SELECT equipment_id FROM process_log
                WHERE wafer_id = ? AND NOT (spec_low <= param_value AND param_value <= spec_high)
                """,
                (wid,),
            ).fetchall()
            assert [r["equipment_id"] for r in bad] == ["ETCH-9"]


def test_normal_wafer_all_in_spec():
    with _conn() as conn:
        bad = conn.execute(
            """
            SELECT COUNT(*) FROM process_log p
            JOIN yield y ON y.wafer_id = p.wafer_id
            WHERE y.defect_type = 'none'
              AND NOT (p.spec_low <= p.param_value AND p.param_value <= p.spec_high)
            """
        ).fetchone()[0]
        assert bad == 0
```

- [ ] **Step 4: 테스트 실패 확인**

Run: `pytest tests/test_dummy_data.py -v`
Expected: FAIL — `no such table: process_log`

- [ ] **Step 5: generate_dummy.py 에 process_log 생성 추가**

`data/generate_dummy.py` 의 `NORMAL_LOTS` 정의 아래에 추가:

```python
# 공정 로그: wafer 마다 4개 공정 단계 각 1행.
# 패턴 그룹 wafer 는 자기 그룹의 process_step 에서 "공유 이상 장비(-9)" +
# 스펙 상한 초과 값을 갖는다 → 루프가 원인을 공정/장비까지 좁히는 근거.
PROCESS_FLOW = [
    # (step, param, spec_low, spec_high)
    ("Photo",     "focus_offset", 0.0,   10.0),
    ("Etch",      "rf_power",     450.0, 550.0),
    ("Diffusion", "furnace_temp", 950.0, 1000.0),
    ("CMP",       "pad_pressure", 3.0,   5.0),
]
```

`generate()` 안, `_write_sqlite(rows)` 호출을 다음으로 교체:

```python
    logs = _make_process_logs(rows, rng)
    _write_sqlite(rows, logs)
```

새 함수 추가 (`_write_sqlite` 위):

```python
def _make_process_logs(rows, rng):
    """wafer 별 공정 로그. 패턴 wafer 의 원인 공정(r['process_step'])만 이상 처리.
    정상 wafer 는 process_step='Normal' 이라 어떤 step 과도 일치하지 않는다."""
    logs = []
    for r in rows:
        for step, param, lo, hi in PROCESS_FLOW:
            if r["process_step"] == step:
                equip = f"{step.upper()}-9"                # 그룹 공유 이상 장비
                value = round(hi + (hi - lo) * 0.2, 2)     # 스펙 상한 20% 초과
            else:
                equip = f"{step.upper()}-{int(rng.integers(1, 4))}"
                value = round(float(rng.uniform(lo, hi)), 2)
            logs.append({
                "wafer_id": r["wafer_id"],
                "process_step": step,
                "equipment_id": equip,
                "param_name": param,
                "param_value": value,
                "spec_low": lo,
                "spec_high": hi,
            })
    return logs
```

`_write_sqlite` 를 다음으로 교체:

```python
def _write_sqlite(rows, logs):
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
            date         TEXT NOT NULL
        )
    """)
    conn.executemany(
        "INSERT INTO yield VALUES (:wafer_id, :lot_id, :yield, :defect_type, :process_step, :date)",
        rows,
    )
    conn.execute("""
        CREATE TABLE process_log (
            wafer_id     TEXT NOT NULL,
            process_step TEXT NOT NULL,
            equipment_id TEXT NOT NULL,
            param_name   TEXT NOT NULL,
            param_value  REAL NOT NULL,
            spec_low     REAL NOT NULL,
            spec_high    REAL NOT NULL
        )
    """)
    conn.executemany(
        """INSERT INTO process_log VALUES
           (:wafer_id, :process_step, :equipment_id, :param_name, :param_value, :spec_low, :spec_high)""",
        logs,
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 6: 더미 데이터 재생성**

Run: `PYTHONUTF8=1 python data/generate_dummy.py`
Expected: 기존 리포트 출력 + 에러 없음 (총 wafer 101장 동일 — seed 42 결정론이므로 yield/임베딩도 기존과 동일하게 재생성됨)

- [ ] **Step 7: 테스트 통과 확인**

Run: `pytest tests/test_dummy_data.py -v`
Expected: 4 PASS

- [ ] **Step 8: 커밋**

```bash
git add requirements.txt tests/conftest.py tests/test_dummy_data.py data/generate_dummy.py data/yield.db data/embeddings
git commit -m "feat: 공정 로그 더미 데이터 + pytest 도입 (분석 루프 근거 데이터)"
```

---

### Task 2: get_process_log 조회 함수

**Files:**
- Modify: `tools/yield_tools.py` (끝에 함수 추가)
- Test: `tests/test_yield_tools.py`

**Interfaces:**
- Consumes: Task 1 의 `process_log` 테이블
- Produces: `get_process_log(wafer_id: str) -> list[dict]` — process_log 행 dict 에 `in_spec: bool` 파생 필드를 더해 반환. LLM 이 스펙 이탈을 바로 읽을 수 있게 하는 것이 목적.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_yield_tools.py`:

```python
"""get_process_log: 공정 로그 조회 + in_spec 파생 필드."""

from tools import yield_tools as yt


def test_get_process_log_returns_4_steps_with_in_spec():
    logs = yt.get_process_log("W2406_cen0")
    assert len(logs) == 4
    assert all("in_spec" in r for r in logs)


def test_pattern_wafer_anomaly_flagged():
    logs = yt.get_process_log("W2406_cen0")
    bad = [r for r in logs if not r["in_spec"]]
    assert len(bad) == 1
    assert bad[0]["process_step"] == "Etch"
    assert bad[0]["equipment_id"] == "ETCH-9"


def test_unknown_wafer_returns_empty():
    assert yt.get_process_log("W_NOPE") == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_yield_tools.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'get_process_log'`

- [ ] **Step 3: 구현**

`tools/yield_tools.py` 끝에 추가:

```python
def get_process_log(wafer_id: str) -> list[dict]:
    """wafer 의 공정 단계별 장비·파라미터 로그. in_spec 파생 필드 포함."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM process_log WHERE wafer_id = ?", (wafer_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["in_spec"] = bool(d["spec_low"] <= d["param_value"] <= d["spec_high"])
            out.append(d)
        return out
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_yield_tools.py -v`
Expected: 3 PASS

- [ ] **Step 5: 커밋**

```bash
git add tools/yield_tools.py tests/test_yield_tools.py
git commit -m "feat: get_process_log 공정 로그 조회 함수"
```

---

### Task 3: tool-calling 래퍼 (agent_tools.py)

**Files:**
- Create: `tools/agent_tools.py`
- Test: `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: `yield_tools.get_wafer/aggregate_defects/get_process_log`, `eds_search.get_searcher`
- Produces (이후 모든 태스크가 의존):
  - `ANALYSIS_TOOLS: list` — 실행 가능한 분석 tool 4개
  - `ALL_TOOLS: list` — 분석 4개 + `finalize` (LLM 에 bind 할 전체 목록)
  - `TOOLS_BY_NAME: dict[str, BaseTool]` — 분석 tool 이름→객체 (finalize 제외; 게이트가 별도 처리)
  - tool 이름 문자열: `"get_wafer"`, `"search_similar"`, `"aggregate_defects"`, `"get_process_log"`, `"finalize"`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_agent_tools.py`:

```python
"""@tool 래퍼: 이름·스키마·실행 검증."""

from tools import agent_tools as at


def test_tool_names():
    assert {t.name for t in at.ALL_TOOLS} == {
        "get_wafer", "search_similar", "aggregate_defects", "get_process_log", "finalize",
    }
    assert "finalize" not in at.TOOLS_BY_NAME  # finalize 는 게이트가 처리


def test_docstrings_exist():
    # docstring 이 곧 LLM 의 tool 선택 판단 재료
    assert all(t.description for t in at.ALL_TOOLS)


def test_get_process_log_tool_invokes():
    rows = at.TOOLS_BY_NAME["get_process_log"].invoke({"wafer_id": "W2406_cen0"})
    assert len(rows) == 4


def test_aggregate_defects_tool_invokes():
    rows = at.TOOLS_BY_NAME["aggregate_defects"].invoke(
        {"wafer_ids": ["W2406_cen0"]}
    )
    assert rows[0]["defect_type"] == "center_spot"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_agent_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.agent_tools'`

- [ ] **Step 3: 구현**

`tools/agent_tools.py`:

```python
"""분석 루프용 tool-calling 래퍼.

LLM 이 읽는 것은 함수의 이름·docstring·인자 스키마다 — 여기 docstring 이
곧 LLM 의 tool 선택 판단 재료이므로 '언제 쓰는지'를 명확히 적는다.

finalize 는 실행되는 tool 이 아니라 "분석 종료 제안" 신호다.
graph/nodes.py 의 tools 노드(게이트)가 confidence 를 검사해 승인/반려하므로
TOOLS_BY_NAME 에는 넣지 않는다.
"""

from langchain_core.tools import tool

from tools import yield_tools as yt
from tools.eds_search import get_searcher

_searcher = None  # hnswlib 인덱스 로드는 무거우므로 최초 사용 시 1회만


def _searcher_lazy():
    global _searcher
    if _searcher is None:
        _searcher = get_searcher()
    return _searcher


@tool
def get_wafer(wafer_id: str) -> dict | None:
    """wafer 1장의 수율·defect_type·공정·날짜를 조회한다.
    대상 wafer 의 기본 정보가 필요할 때 사용."""
    return yt.get_wafer(wafer_id)


@tool
def search_similar(wafer_id: str, k: int = 5) -> list[dict]:
    """불량 맵 패턴이 유사한 과거 wafer 를 찾는다.
    과거 사례와 비교해 원인 단서를 얻으려면 가장 먼저 사용."""
    return _searcher_lazy().search(wafer_id, k=k)


@tool
def aggregate_defects(wafer_ids: list[str]) -> list[dict]:
    """여러 wafer 의 defect_type 분포를 집계한다.
    유사 wafer 들이 같은 불량 유형을 공유하는지 확인할 때 사용."""
    return yt.aggregate_defects(wafer_ids)


@tool
def get_process_log(wafer_id: str) -> list[dict]:
    """wafer 의 공정 단계별 장비·파라미터 로그를 조회한다.
    in_spec=False 인 행이 스펙 이탈. 원인을 특정 공정/장비까지 좁히려면 반드시 확인."""
    return yt.get_process_log(wafer_id)


@tool
def finalize(hypothesis: str, confidence: float) -> str:
    """원인을 특정 공정/장비까지 좁혔고 근거가 충분하다고 판단될 때만 호출해
    분석 종료를 제안한다. hypothesis=원인 가설(공정·장비·파라미터 명시),
    confidence=0~1 확신도. 확신도가 낮으면 반려되고 추가 분석을 지시받는다."""
    return "finalize 는 게이트가 처리한다"  # 직접 실행되지 않음


ANALYSIS_TOOLS = [get_wafer, search_similar, aggregate_defects, get_process_log]
ALL_TOOLS = ANALYSIS_TOOLS + [finalize]
TOOLS_BY_NAME = {t.name: t for t in ANALYSIS_TOOLS}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_agent_tools.py -v`
Expected: 4 PASS

- [ ] **Step 5: 커밋**

```bash
git add tools/agent_tools.py tests/test_agent_tools.py
git commit -m "feat: 분석 루프용 @tool 래퍼 (분석 4개 + finalize 신호)"
```

---

### Task 4: 누적형 상태 + 루프 설정

**Files:**
- Modify: `config.py` (끝에 추가)
- Rewrite: `graph/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces (이후 태스크가 의존하는 상태 키):
  - `AgentState`: `question, messages(add_messages), findings(operator.add), target_wafer, status_summary, loop_count, finalize_accepted, final_hypothesis, final_confidence, report`
  - `config.MAX_LOOPS = 6`, `config.CONFIDENCE_THRESHOLD = 0.8`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_state.py`:

```python
"""누적형 상태: messages/findings 가 덮어쓰이지 않고 쌓이는지 검증."""

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

import config
from graph.state import AgentState


def test_loop_config_exists():
    assert config.MAX_LOOPS == 6
    assert config.CONFIDENCE_THRESHOLD == 0.8


def test_messages_and_findings_accumulate():
    def n1(state):
        return {"messages": [HumanMessage("a")], "findings": [{"loop": 0}]}

    def n2(state):
        return {"messages": [HumanMessage("b")], "findings": [{"loop": 1}]}

    g = StateGraph(AgentState)
    g.add_node("n1", n1)
    g.add_node("n2", n2)
    g.set_entry_point("n1")
    g.add_edge("n1", "n2")
    g.add_edge("n2", END)
    out = g.compile().invoke({"question": "q"})

    assert [m.content for m in out["messages"]] == ["a", "b"]   # 누적 (덮어쓰기 아님)
    assert [f["loop"] for f in out["findings"]] == [0, 1]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_state.py -v`
Expected: FAIL — `MAX_LOOPS` 없음 / messages 가 리스트 병합이 아니라 덮어쓰기됨

- [ ] **Step 3: config.py 에 루프 설정 추가**

`config.py` 끝에 추가:

```python
# 분석 루프 통제 (analysis_loop_design.md 부품 4b)
MAX_LOOPS = 6              # 가드레일: 최대 순환 횟수 (무한루프 차단)
CONFIDENCE_THRESHOLD = 0.8 # finalize 승인 임계 확신도
```

- [ ] **Step 4: graph/state.py 재작성**

```python
"""LangGraph 상태 정의 (누적형).

분석 루프는 "현재까지 결과를 보고" 다음 분석을 판단하므로,
messages/findings 는 덮어쓰기가 아니라 reducer 로 누적한다.
findings 는 감사(audit) 기록 — 매 tool 실행의 {loop, tool, args, result, thought}
가 쌓여 리포트의 분석 근거가 된다.
"""

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    question: str                                   # 사용자 질문
    messages: Annotated[list, add_messages]         # LLM 대화 누적 (루프의 문맥)
    findings: Annotated[list[dict], operator.add]   # 감사 기록 누적 (분석 근거)
    target_wafer: str                               # 현황파악이 지목한 분석 대상
    status_summary: str                             # 현황파악 요약 (리포트 재료)
    loop_count: int                                 # 순환 횟수 (가드레일)
    finalize_accepted: bool                         # 게이트 승인 여부
    final_hypothesis: str                           # 승인된 원인 가설
    final_confidence: float                         # 승인 시 확신도
    report: str                                     # 최종 리포트
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_state.py -v`
Expected: 2 PASS

- [ ] **Step 6: 커밋**

```bash
git add config.py graph/state.py tests/test_state.py
git commit -m "feat: 누적형 상태(reducer) + 루프 가드레일 설정"
```

---

### Task 5: LLM 계층 개편 (ScriptedMock + OpenAI)

**Files:**
- Rewrite: `llm/client.py`
- Test: `tests/test_mock_llm.py`

**Interfaces:**
- Consumes: `tools/agent_tools.ALL_TOOLS` (OpenAI bind 용)
- Produces (graph 노드가 의존):
  - `LLMClient.analyze_step(messages: list) -> AIMessage` — tool_calls 포함 가능한 응답
  - `LLMClient.generate_report(question: str, target_wafer: str, status_summary: str, findings: list[dict], hypothesis: str | None, confidence: float | None) -> str`
  - `get_llm() -> LLMClient` (config.LLM_MODE: "mock" → ScriptedMock, "openai" → OpenAI)
- 계약: analyze 노드가 만드는 HumanMessage 에 `"대상 wafer: {id}"` 라인이 있어야 mock 이 대상을 파싱한다 (Task 6 이 이 형식을 지킨다). tools 노드는 ToolMessage 에 `name=<tool이름>` 을 지정하고 content 는 `json.dumps(결과, ensure_ascii=False)` 로 넣는다 (finalize 반려/승인 문구는 평문).

**Mock 시나리오 (결정론):**
1. `search_similar(target)` — "유사 사례부터 확인"
2. `aggregate_defects([target]+유사)` — "불량 유형 공유 확인"
3. `finalize(confidence=0.6)` — 공정 근거 없이 조기 종료 시도 → **게이트가 반려** (게이트 시연)
4. `get_process_log(target)` — "반려됨, 공정 로그 확인"
5. `finalize(confidence=0.9, 가설=스펙 이탈 장비)` — **승인**

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_mock_llm.py`:

```python
"""ScriptedMockLLMClient: 시나리오 순서·파싱·finalize 인자 검증.

mock 은 tools 노드가 만들 ToolMessage(name=..., content=json)를 보고
다음 tool 을 결정한다 — 여기서는 그 ToolMessage 를 손으로 만들어 단계를 진행시킨다.
"""

import json

from langchain_core.messages import HumanMessage, ToolMessage

from llm.client import ScriptedMockLLMClient

HUMAN = HumanMessage("현황: ...\n\n대상 wafer: W2406_cen0\n질문: 원인 분석해줘")


def _tm(name, payload):
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ToolMessage(content, tool_call_id=f"call_{name}", name=name)


def test_scripted_sequence():
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]

    # 1) 유사 검색부터
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "search_similar"
    assert ai.tool_calls[0]["args"]["wafer_id"] == "W2406_cen0"
    assert ai.content  # thought(가설 서술)가 감사 기록 재료로 반드시 존재
    msgs += [ai, _tm("search_similar", [{"wafer_id": "W2411_cen2", "similarity": 0.92}])]

    # 2) defect 집계 (유사 wafer id 를 이어받는다)
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "aggregate_defects"
    assert ai.tool_calls[0]["args"]["wafer_ids"] == ["W2406_cen0", "W2411_cen2"]
    msgs += [ai, _tm("aggregate_defects", [{"defect_type": "center_spot", "count": 2}])]

    # 3) 조기 finalize (낮은 확신도 → 게이트 반려 시연용)
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] < 0.8
    msgs += [ai, _tm("finalize", "반려: 확신도 0.60 < 0.8. 근거를 좁힐 tool 을 더 호출하라.")]

    # 4) 공정 로그 확인
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "get_process_log"
    msgs += [ai, _tm("get_process_log", [
        {"process_step": "Etch", "equipment_id": "ETCH-9", "param_name": "rf_power",
         "param_value": 570.0, "spec_low": 450.0, "spec_high": 550.0, "in_spec": False},
        {"process_step": "CMP", "equipment_id": "CMP-1", "param_name": "pad_pressure",
         "param_value": 4.0, "spec_low": 3.0, "spec_high": 5.0, "in_spec": True},
    ])]

    # 5) 최종 finalize — 스펙 이탈 장비를 가설에 명시
    ai = llm.analyze_step(msgs)
    call = ai.tool_calls[0]
    assert call["name"] == "finalize"
    assert call["args"]["confidence"] >= 0.8
    assert "ETCH-9" in call["args"]["hypothesis"]


def test_generate_report_contains_findings_and_conclusion():
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        question="원인 분석해줘",
        target_wafer="W2406_cen0",
        status_summary="LOT2406 평균 84.8",
        findings=[{"loop": 1, "tool": "search_similar", "args": {"wafer_id": "W2406_cen0"},
                   "result": [], "thought": "유사 사례 확인"}],
        hypothesis="Etch 공정 ETCH-9 장비 rf_power 스펙 이탈이 원인",
        confidence=0.9,
    )
    assert "W2406_cen0" in report
    assert "search_similar" in report
    assert "ETCH-9" in report


def test_generate_report_handles_no_hypothesis():
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        question="q", target_wafer="W1", status_summary="s",
        findings=[], hypothesis=None, confidence=None,
    )
    assert "미확정" in report
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_mock_llm.py -v`
Expected: FAIL — `ImportError: cannot import name 'ScriptedMockLLMClient'`

- [ ] **Step 3: llm/client.py 재작성**

```python
"""LLM 클라이언트 인터페이스 + 구현(스크립트형 mock / 사내 OpenAI 호환).

분석 루프의 두 LLM 호출 지점을 단일 인터페이스로 추상화한다:
  - analyze_step     : 누적 messages -> tool call 또는 finalize 를 담은 AIMessage
  - generate_report  : 감사 기록(findings) -> 원인 리포트 (수치는 tool 결과 그대로)

수치 계산은 도구 계층이 담당하고, LLM 은 "어떤 분석을 할지 판단"과 표현만 맡는다.
"""

import json
import re
from abc import ABC, abstractmethod

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import config


class LLMClient(ABC):
    @abstractmethod
    def analyze_step(self, messages: list) -> AIMessage:
        """누적 대화를 보고 다음 행동(tool call / finalize)을 결정."""
        ...

    @abstractmethod
    def generate_report(
        self,
        question: str,
        target_wafer: str,
        status_summary: str,
        findings: list[dict],
        hypothesis: str | None,
        confidence: float | None,
    ) -> str:
        """감사 기록을 근거로 원인 리포트 생성."""
        ...


class ScriptedMockLLMClient(LLMClient):
    """사내망 밖 데모용. 시나리오를 따라가는 결정론적 스크립트.

    search_similar → aggregate_defects → finalize(0.6, 게이트가 반려)
    → get_process_log → finalize(0.9, 승인) 순서로 진행하며,
    각 단계 인자는 직전 ToolMessage(json) 를 파싱해 이어받는다.
    """

    def __init__(self):
        self._seq = 0

    # -------------------------------------------------- analyze
    def analyze_step(self, messages: list) -> AIMessage:
        target = self._target(messages)
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        done = [m.name for m in tool_msgs]

        if "search_similar" not in done:
            return self._call(
                "search_similar", {"wafer_id": target},
                f"{target} 의 불량 맵과 유사한 과거 사례부터 확인한다.")

        if "aggregate_defects" not in done:
            sims = [r["wafer_id"] for r in self._result(tool_msgs, "search_similar")]
            return self._call(
                "aggregate_defects", {"wafer_ids": [target] + sims},
                "유사 wafer 들이 같은 불량 유형을 공유하는지 집계한다.")

        if "finalize" not in done:
            top = self._result(tool_msgs, "aggregate_defects")[0]["defect_type"]
            return self._call(
                "finalize",
                {"hypothesis": f"유사 사례가 모두 {top} — 공통 원인 존재 추정",
                 "confidence": 0.6},
                "불량 유형은 좁혔지만 공정 근거가 아직 없다. 이 정도로 종료를 제안해 본다.")

        if "get_process_log" not in done:
            return self._call(
                "get_process_log", {"wafer_id": target},
                "종료 제안이 반려됐다. 원인 공정을 좁히기 위해 공정 로그를 확인한다.")

        logs = self._result(tool_msgs, "get_process_log")
        bad = next(r for r in logs if not r["in_spec"])
        hyp = (f"{bad['process_step']} 공정 {bad['equipment_id']} 장비의 "
               f"{bad['param_name']} 스펙 이탈({bad['param_value']}, "
               f"스펙 {bad['spec_low']}~{bad['spec_high']})이 원인")
        return self._call(
            "finalize", {"hypothesis": hyp, "confidence": 0.9},
            "공정 로그에서 스펙 이탈 장비를 특정했다. 근거가 충분하다.")

    # -------------------------------------------------- report
    def generate_report(self, question, target_wafer, status_summary,
                        findings, hypothesis, confidence) -> str:
        lines = [
            f"[분석 대상] {target_wafer}",
            f"[현황] {status_summary}",
            "",
            "[분석 과정]",
        ]
        for f in findings:
            lines.append(f"  {f['loop']}. {f['tool']}({f['args']})")
            if f.get("thought"):
                lines.append(f"     - 판단: {f['thought']}")
            if f["tool"] == "finalize":
                lines.append(f"     - 게이트: {f['result']}")
        conclusion = hypothesis or "원인 미확정 (최대 분석 횟수 도달)"
        conf = f" (확신도 {confidence})" if confidence is not None else ""
        lines += ["", f"[결론] {conclusion}{conf}"]
        return "\n".join(lines)

    # -------------------------------------------------- 내부
    @staticmethod
    def _target(messages) -> str:
        for m in messages:
            found = re.search(r"대상 wafer: (\S+)", getattr(m, "content", "") or "")
            if found:
                return found.group(1)
        raise ValueError("messages 에서 '대상 wafer:' 라인을 찾지 못했다")

    @staticmethod
    def _result(tool_msgs, name):
        msg = next(m for m in reversed(tool_msgs) if m.name == name)
        return json.loads(msg.content)

    def _call(self, name, args, thought) -> AIMessage:
        self._seq += 1
        return AIMessage(
            content=thought,
            tool_calls=[{"name": name, "args": args, "id": f"call_{self._seq}"}],
        )


class OpenAILLMClient(LLMClient):
    """운영용. 사내 OpenAI 호환 서빙에 base_url 만 지정해 연결."""

    def __init__(self):
        from langchain_openai import ChatOpenAI

        from tools.agent_tools import ALL_TOOLS

        self.llm = ChatOpenAI(
            base_url=config.LLM_BASE_URL,
            api_key=config.LLM_API_KEY,
            model=config.LLM_MODEL,
            temperature=0,
        )
        self.analyzer = self.llm.bind_tools(ALL_TOOLS)

    def analyze_step(self, messages: list) -> AIMessage:
        return self.analyzer.invoke(messages)

    def generate_report(self, question, target_wafer, status_summary,
                        findings, hypothesis, confidence) -> str:
        sys = (
            "현장 반도체 엔지니어에게 한국어 높임말로 원인 분석 리포트를 쓴다. "
            "분석 과정(findings)의 수치는 절대 임의로 바꾸지 말고 그대로 인용하라. "
            "구성: 분석 대상/현황 → 분석 과정 요약 → 결론(원인 가설과 근거)."
        )
        user = (
            f"질문: {question}\n대상 wafer: {target_wafer}\n현황: {status_summary}\n\n"
            f"분석 기록(JSON):\n{json.dumps(findings, ensure_ascii=False, default=str)}\n\n"
            f"결론 가설: {hypothesis or '미확정 (최대 분석 횟수 도달)'} / 확신도: {confidence}"
        )
        resp = self.llm.invoke([SystemMessage(content=sys), HumanMessage(content=user)])
        return resp.content.strip()


def get_llm() -> LLMClient:
    if config.LLM_MODE == "mock":
        return ScriptedMockLLMClient()
    if config.LLM_MODE == "openai":
        return OpenAILLMClient()
    raise ValueError(f"알 수 없는 LLM_MODE: {config.LLM_MODE}")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_mock_llm.py -v`
Expected: 3 PASS

- [ ] **Step 5: 커밋**

```bash
git add llm/client.py tests/test_mock_llm.py
git commit -m "feat: LLM 계층 개편 — analyze_step/generate_report + 스크립트형 mock"
```

---

### Task 6: 그래프 노드 (status / analyze / tools 게이트 / report)

**Files:**
- Rewrite: `graph/nodes.py`
- Test: `tests/test_graph_nodes.py`

**Interfaces:**
- Consumes: `agent_tools.TOOLS_BY_NAME`, `llm.client.get_llm()`, `yield_tools.find_low_yield_lots`, `config.MAX_LOOPS/CONFIDENCE_THRESHOLD`, findings 항목 규격
- Produces (build.py 가 의존):
  - `status_node(state) -> dict` — `messages`(System+Human, "대상 wafer: {id}" 라인 포함), `target_wafer`, `status_summary`, `findings`(loop=0 현황 기록)
  - `analyze_node(state) -> dict` — `messages`([AIMessage]), `loop_count` 증가
  - `tools_node(state) -> dict` — tool 실행 + ToolMessage(name/json) + findings 기록. finalize 는 게이트: 승인 시 `finalize_accepted/final_hypothesis/final_confidence` 설정, 미달 시 반려 ToolMessage
  - `report_node(state) -> dict` — `report`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_graph_nodes.py`:

```python
"""노드 단위 검증 — 특히 tools 노드의 finalize 게이트(승인/반려)와 감사 기록."""

from langchain_core.messages import AIMessage, ToolMessage

from graph import nodes


def _ai_finalize(confidence):
    return AIMessage(
        content="종료 제안",
        tool_calls=[{"name": "finalize",
                     "args": {"hypothesis": "Etch ETCH-9 원인", "confidence": confidence},
                     "id": "call_f"}],
    )


def test_status_node_sets_target_and_seed_messages():
    out = nodes.status_node({"question": "원인 분석해줘"})
    assert out["target_wafer"].startswith("W2406_")          # 최근 배치의 worst wafer
    assert f"대상 wafer: {out['target_wafer']}" in out["messages"][-1].content
    assert out["findings"][0]["loop"] == 0                   # 현황파악도 감사 기록에 남는다
    assert out["findings"][0]["tool"] == "find_low_yield_lots"


def test_tools_node_executes_and_records_finding():
    ai = AIMessage(
        content="유사 사례 확인",
        tool_calls=[{"name": "get_process_log",
                     "args": {"wafer_id": "W2406_cen0"}, "id": "call_1"}],
    )
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    tm = out["messages"][0]
    assert isinstance(tm, ToolMessage) and tm.name == "get_process_log"
    f = out["findings"][0]
    assert (f["loop"], f["tool"], f["thought"]) == (1, "get_process_log", "유사 사례 확인")
    assert len(f["result"]) == 4                             # 결과 원본이 그대로 남는다
    assert "finalize_accepted" not in out


def test_finalize_gate_rejects_low_confidence():
    out = nodes.tools_node({"messages": [_ai_finalize(0.6)], "loop_count": 3})
    assert "finalize_accepted" not in out
    assert "반려" in out["messages"][0].content
    assert out["findings"][0]["tool"] == "finalize"          # 반려도 감사 기록에 남는다


def test_finalize_gate_accepts_high_confidence():
    out = nodes.tools_node({"messages": [_ai_finalize(0.9)], "loop_count": 4})
    assert out["finalize_accepted"] is True
    assert out["final_hypothesis"] == "Etch ETCH-9 원인"
    assert out["final_confidence"] == 0.9
    assert "승인" in out["messages"][0].content


def test_finalize_gate_accepts_at_max_loops_even_if_low():
    out = nodes.tools_node({"messages": [_ai_finalize(0.5)], "loop_count": 6})
    assert out["finalize_accepted"] is True                  # 한계 도달 시 강제 승인


def test_report_node_produces_report():
    out = nodes.report_node({
        "question": "q", "target_wafer": "W2406_cen0", "status_summary": "요약",
        "findings": [], "final_hypothesis": "Etch ETCH-9 원인", "final_confidence": 0.9,
    })
    assert "ETCH-9" in out["report"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_graph_nodes.py -v`
Expected: FAIL — `AttributeError: module 'graph.nodes' has no attribute 'status_node'`

- [ ] **Step 3: graph/nodes.py 재작성**

```python
"""LangGraph 노드: 현황파악(고정) / 분석(LLM) / 도구 실행+게이트 / 리포팅(고정).

- 골격(status, report)은 고정 — 순서는 개발자가 못박는다.
- analyze ⇄ tools 순환 구간만 LLM 이 자율 판단한다.
- tools 노드는 세 가지를 한다:
    (1) 분석 tool 실행 (수치는 여기서만 나온다)
    (2) 감사 기록: 매 실행을 findings 에 {loop, tool, args, result, thought} 로 남긴다
    (3) finalize 게이트: LLM 의 종료 제안을 confidence 로 승인/반려 (LLM 은 제안, 코드가 결정)
"""

import json

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

import config
from llm.client import get_llm
from tools import yield_tools as yt
from tools.agent_tools import TOOLS_BY_NAME

_llm = get_llm()

ANALYZE_SYSTEM_PROMPT = """너는 반도체 수율 분석 전문가다. 대상 wafer 의 불량 원인을 특정 공정 단계(가능하면 장비)까지 좁혀라.

규칙:
- 매 단계, 지금까지의 tool 결과로 원인을 확신할 수 있는지 스스로 평가하라.
- 확신이 부족하면 근거를 좁힐 tool 을 하나 더 호출하라. tool 호출 시 현재 가설과 이 tool 을 부르는 이유를 한두 문장으로 함께 서술하라 (분석 기록으로 남는다).
- 원인을 좁혔고 근거가 충분하면 finalize(hypothesis, confidence) 로 종료를 제안하라. 확신도가 낮으면 반려된다.
- 수치는 tool 결과를 그대로 인용하고 절대 임의로 만들지 마라."""


# ------------------------------------------------ 고정 골격: 현황 파악
def status_node(state: dict) -> dict:
    lots = yt.find_low_yield_lots()
    target = lots[0]["worst_wafer"]["wafer_id"]
    summary = _summarize_lots(lots)
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
        "findings": [{
            "loop": 0, "tool": "find_low_yield_lots", "args": {},
            "result": lots, "thought": "현황 파악 (고정 골격)",
        }],
    }


def _summarize_lots(lots: list[dict]) -> str:
    if not lots:
        return "수율 임계 미만인 lot 없음."
    lines = []
    for lot in lots:
        w = lot["worst_wafer"]
        lines.append(
            f"- {lot['lot_id']}: 평균 수율 {lot['avg_yield']} ({lot['wafer_count']}장), "
            f"최저 wafer {w['wafer_id']} (수율 {w['yield']}, 불량 {w['defect_type']})"
        )
    return "\n".join(lines)


# ------------------------------------------------ 자유 루프: 분석 (LLM)
def analyze_node(state: dict) -> dict:
    ai = _llm.analyze_step(state["messages"])
    return {"messages": [ai], "loop_count": state.get("loop_count", 0) + 1}


# ------------------------------------------------ 자유 루프: 도구 실행 + 게이트
def tools_node(state: dict) -> dict:
    ai = state["messages"][-1]
    loop = state["loop_count"]
    out_msgs, findings, update = [], [], {}

    for call in ai.tool_calls:
        if call["name"] == "finalize":
            verdict = _finalize_gate(call["args"], loop, update)
            out_msgs.append(ToolMessage(verdict, tool_call_id=call["id"], name="finalize"))
            findings.append({
                "loop": loop, "tool": "finalize", "args": call["args"],
                "result": verdict, "thought": ai.content or "",
            })
        else:
            result = TOOLS_BY_NAME[call["name"]].invoke(call["args"])
            out_msgs.append(ToolMessage(
                json.dumps(result, ensure_ascii=False),
                tool_call_id=call["id"], name=call["name"],
            ))
            findings.append({
                "loop": loop, "tool": call["name"], "args": call["args"],
                "result": result, "thought": ai.content or "",
            })

    return {"messages": out_msgs, "findings": findings, **update}


def _finalize_gate(args: dict, loop: int, update: dict) -> str:
    """LLM 의 종료 제안을 코드가 최종 판정한다 (부품 4b)."""
    conf = float(args.get("confidence", 0.0))
    if conf >= config.CONFIDENCE_THRESHOLD or loop >= config.MAX_LOOPS:
        update["finalize_accepted"] = True
        update["final_hypothesis"] = args.get("hypothesis", "")
        update["final_confidence"] = conf
        reason = "확신도 충족" if conf >= config.CONFIDENCE_THRESHOLD else "최대 횟수 도달"
        return f"승인 ({reason}): 리포팅으로 진행한다."
    return (f"반려: 확신도 {conf:.2f} < {config.CONFIDENCE_THRESHOLD}. "
            f"근거를 좁힐 tool 을 더 호출하라.")


# ------------------------------------------------ 고정 골격: 리포팅
def report_node(state: dict) -> dict:
    report = _llm.generate_report(
        question=state["question"],
        target_wafer=state["target_wafer"],
        status_summary=state["status_summary"],
        findings=state["findings"],
        hypothesis=state.get("final_hypothesis"),
        confidence=state.get("final_confidence"),
    )
    return {"report": report}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_graph_nodes.py -v`
Expected: 6 PASS

- [ ] **Step 5: 커밋**

```bash
git add graph/nodes.py tests/test_graph_nodes.py
git commit -m "feat: 분석 루프 노드 — finalize 게이트 + 감사 기록(findings)"
```

---

### Task 7: 그래프 조립 (순환 엣지 + 조건부 종료)

**Files:**
- Rewrite: `graph/build.py`
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: Task 6 의 4개 노드, `config.MAX_LOOPS`
- Produces: `build_graph() -> CompiledGraph` — `invoke({"question": str})` 로 실행. 라우팅 함수 `_after_analyze(state) -> "tools"|"report"`, `_after_tools(state) -> "analyze"|"report"` 도 테스트를 위해 모듈 수준에 둔다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_build.py`:

```python
"""라우팅 함수(순환/종료 판단) 검증. E2E 는 tests/test_e2e.py 에서."""

from langchain_core.messages import AIMessage

from graph.build import _after_analyze, _after_tools


def _ai(with_call: bool):
    calls = [{"name": "get_wafer", "args": {"wafer_id": "W"}, "id": "c1"}] if with_call else []
    return AIMessage(content="생각", tool_calls=calls)


def test_analyze_with_tool_call_continues():
    assert _after_analyze({"messages": [_ai(True)], "loop_count": 2}) == "tools"


def test_analyze_without_tool_call_exits():
    # tool 도 finalize 도 없이 텍스트만 낸 이탈 케이스 → 리포팅으로 (안전망)
    assert _after_analyze({"messages": [_ai(False)], "loop_count": 2}) == "report"


def test_analyze_over_max_loops_forced_to_report():
    assert _after_analyze({"messages": [_ai(True)], "loop_count": 7}) == "report"


def test_tools_accepted_goes_report():
    assert _after_tools({"finalize_accepted": True}) == "report"


def test_tools_not_accepted_loops_back():
    assert _after_tools({}) == "analyze"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_build.py -v`
Expected: FAIL — `ImportError: cannot import name '_after_analyze'`

- [ ] **Step 3: graph/build.py 재작성**

```python
"""그래프 조립 — 하이브리드 분석 루프.

  status ──▶ analyze ──(tool call)──▶ tools ──(반려/계속)──▶ analyze   ← 순환
   (고정)        │                      │
                 └─(호출 없음/한계)      └─(finalize 승인)
                        ▼                      ▼
                      report ◀────────────────┘
                       (고정)

골격(status→…→report)은 고정 엣지, analyze ⇄ tools 만 LLM 자율 순환.
종료는 tools 노드의 finalize 게이트(확신도)와 MAX_LOOPS 가드레일이 통제한다.
"""

from langgraph.graph import END, StateGraph

import config
from graph import nodes
from graph.state import AgentState


def _after_analyze(state: dict) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        if state["loop_count"] > config.MAX_LOOPS:  # 가드레일: 무한루프 차단
            return "report"
        return "tools"
    return "report"  # tool 호출 없이 텍스트만 = 이탈 케이스 → 리포팅 (안전망)


def _after_tools(state: dict) -> str:
    return "report" if state.get("finalize_accepted") else "analyze"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("status", nodes.status_node)
    g.add_node("analyze", nodes.analyze_node)
    g.add_node("tools", nodes.tools_node)
    g.add_node("report", nodes.report_node)

    g.set_entry_point("status")                    # 고정: 반드시 현황파악 먼저
    g.add_edge("status", "analyze")
    g.add_conditional_edges("analyze", _after_analyze, ["tools", "report"])
    g.add_conditional_edges("tools", _after_tools, ["analyze", "report"])
    g.add_edge("report", END)                      # 고정: 반드시 리포팅으로 끝

    return g.compile()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_build.py -v`
Expected: 5 PASS

- [ ] **Step 5: 커밋**

```bash
git add graph/build.py tests/test_build.py
git commit -m "feat: 순환 그래프 조립 — 고정 골격 + analyze⇄tools 루프"
```

---

### Task 8: 진입점 + E2E 검증 + README

**Files:**
- Rewrite: `main.py`
- Modify: `README.md` (흐름/실행법 절 갱신)
- Test: `tests/test_e2e.py`

**Interfaces:**
- Consumes: `build_graph()`, mock 시나리오 전체
- Produces: `python main.py` 데모 (질문 → 현황 → 감사 기록 → 리포트 출력)

- [ ] **Step 1: 실패하는 E2E 테스트 작성**

`tests/test_e2e.py`:

```python
"""End-to-End: mock 루프가 현황→순환(반려 포함)→승인→리포트까지 완주하는지."""

from graph.build import build_graph


def test_full_loop_reaches_report_with_audit_trail():
    state = build_graph().invoke(
        {"question": "이번 배치에서 수율 이상 wafer 의 불량 원인을 분석해줘"}
    )

    # 골격: 현황파악이 대상 wafer 를 지목하고, 리포트로 끝난다
    assert state["target_wafer"].startswith("W2406_")
    assert state["report"]

    # 게이트: 조기 finalize 는 반려됐고, 최종 finalize 는 승인됐다
    gate_results = [f["result"] for f in state["findings"] if f["tool"] == "finalize"]
    assert any("반려" in r for r in gate_results)
    assert any("승인" in r for r in gate_results)
    assert state["finalize_accepted"] is True
    assert "-9" in state["final_hypothesis"]        # 이상 장비까지 좁혔다

    # 감사 기록: 시나리오의 분석 tool 이 순서대로 남았다
    tools_used = [f["tool"] for f in state["findings"]]
    assert tools_used[0] == "find_low_yield_lots"   # loop 0 = 고정 골격
    for expected in ("search_similar", "aggregate_defects", "get_process_log"):
        assert expected in tools_used
    assert all("thought" in f for f in state["findings"])

    # 가드레일 안에서 끝났다
    assert state["loop_count"] <= 6
```

- [ ] **Step 2: 테스트 실행 — 이 시점에는 통과해야 정상**

Run: `pytest tests/test_e2e.py -v`
Expected: PASS (Task 1~7 이 완성됐다면 E2E 는 이미 성립. 실패 시 앞 태스크의 계약 위반이므로 원인 파악 후 수정)

- [ ] **Step 3: main.py 재작성**

```python
"""실행 진입점.

기본: 데모 질문 1건으로 하이브리드 분석 루프 End-to-End 시연.
단일 질문: python main.py "질문"
(Windows 콘솔 한글 깨짐 방지: PYTHONUTF8=1 python main.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph.build import build_graph  # noqa: E402

DEMO_QUESTION = "이번 배치에서 수율 이상 wafer 의 불량 원인을 분석해줘"


def run(question: str) -> None:
    app = build_graph()
    state = app.invoke({"question": question})

    print(f"[질문] {question}\n")
    print(f"[현황 파악 — 고정 골격]\n{state['status_summary']}\n")
    print(f"[분석 대상] {state['target_wafer']}\n")

    print("[분석 루프 — 감사 기록]")
    for f in state["findings"]:
        if f["loop"] == 0:
            continue  # 현황파악은 위에서 출력
        print(f"  {f['loop']}. {f['tool']}  args={f['args']}")
        if f.get("thought"):
            print(f"     판단: {f['thought']}")
        if f["tool"] == "finalize":
            print(f"     게이트: {f['result']}")
    print()
    print(f"[리포트 — 고정 골격]\n{state['report']}")


if __name__ == "__main__":
    run(" ".join(sys.argv[1:]) if len(sys.argv) > 1 else DEMO_QUESTION)
```

- [ ] **Step 4: 데모 실행 확인**

Run: `PYTHONUTF8=1 python main.py`
Expected: 현황(LOT2406) → 루프 5순환(search_similar → aggregate_defects → finalize 반려 → get_process_log → finalize 승인) → "-9" 장비를 지목하는 리포트 출력, 에러 없음

- [ ] **Step 5: 전체 테스트 통과 확인**

Run: `pytest -v`
Expected: 전체 PASS (누적 약 23개)

- [ ] **Step 6: README 갱신**

`README.md` 에서 그래프 흐름/실행법을 설명하는 절을 새 구조로 교체 (기존 문구 스타일 유지):

- 흐름 다이어그램을 `status → analyze ⇄ tools → report` 로 교체
- "분석 루프" 절 추가: finalize 게이트(확신도 0.8, 최대 6회), 감사 기록(findings)
- 실행법에 `pytest` 추가
- 기존 시나리오 1→2 멀티턴 설명 제거 (대체됨)

- [ ] **Step 7: 커밋**

```bash
git add main.py README.md tests/test_e2e.py
git commit -m "feat: 하이브리드 분석 루프 E2E — 진입점/README 교체"
```

---

## 검증 요약

| 검증 | 방법 |
|------|------|
| 더미 데이터에 원인이 심어졌다 | test_dummy_data (이상 장비 -9, 그룹 공유) |
| 감사 기록이 남는다 | test_graph_nodes (findings 규격), test_e2e (thought 존재) |
| 게이트가 반려/승인한다 | test_graph_nodes (0.6 반려 / 0.9 승인 / 한계 강제승인) |
| 무한루프가 없다 | test_build (MAX_LOOPS 강제 report), test_e2e (loop_count ≤ 6) |
| 사내망 밖에서 돈다 | mock 으로 test_e2e + `python main.py` 완주 |
| 수치는 tool 이 만든다 | findings.result 에 tool 반환 원본 보존, 리포트는 이를 인용 |
