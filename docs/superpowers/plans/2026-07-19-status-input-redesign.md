# status 입력 재설계 (question → 분석 대상 wafer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** status 를 "분석 대상은 이미 정해져서 들어온다" 전제로 재구성한다 — 입력을
`question` 문자열에서 **lot_wafer 결합 형태 wafer 목록**(`{root_lot_id}_{wafer_id}`,
예: `A45Z4_13`, 더미 `W2406_02`)으로 바꾸고, 한 장 입력은 EDS 형제 묶기로,
대조군은 형제 lot 합집합으로 확정한다.

**Architecture:** 대상 선정(앞단, `tools/target_selection.py`)과 정규화 계층
(`tools/grouping.py`)을 status 밖으로 분리한다. status_node 는 입력 검증 →
형제 묶기(한 장일 때, EDS 컷오프 고정) → 대조군 선정(1단계: 형제 lot 내 합집합)
→ seed 생성만 한다. 실패는 전부 별도 finalize_status 로 정직 보고한다
(`no_anomaly`/`unknown_target`/`isolated`/`control_insufficient`). mock LLM 의
seed 파싱 계약은 기계용 `GROUPS_JSON=` 라인으로 대체한다.

**Tech Stack:** Python 3.12, LangGraph, hnswlib(EDS local), SQLite, pytest.

**결정 근거:** `docs/2026-07-18-status-node-review-and-redesign.md` 5~7절 (Q1~Q3 확정)
+ 2026-07-19 사용자 확정 4건 (입력=lot_wafer 결합 형태 목록 / 데모=자동 선정 앞단 사용 /
SIBLING_MIN_SIMILARITY=0.8·CONTROL_MIN_SIZE=3 / mock=GROUPS_JSON 라인).

## Global Constraints

- 코드 주석·docstring 은 기존 스타일대로 한국어. 사용자 응대는 한국어 높임말.
- TDD 필수: 테스트 먼저 → 실패 확인 → 최소 구현 → 전체 green → 커밋.
- 결정론 원칙: LLM 은 그룹 판정·수치에 관여하지 않는다. EDS 컷오프는 실행 중 불변 상수.
- 더미 데이터(`data/generate_dummy.py`, seed 42)는 이 계획에서 수정하지 않는다.
- 전체 테스트 실행: `python -m pytest -q` (모든 커밋 시점에 green, 최종적으로 xfail 0개).
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## 더미 데이터 사실 (테스트 기대값의 근거 — seed 42 고정)

- `LOT2406`: 불량 그룹 `W2406_02/04/06` (center_spot, 수율 76~82, Etch ETCH-9 스펙 이탈),
  대조 `W2406_01/03/05` (none, 93~97), 구멍 (가) `W2406_07` (none, **88.5** — 수율 조건에 걸러져야 함).
- 과거 center_spot 형제 4장: `W2410_cen1`, `W2411_cen2`, `W2412_cen3`, `W2413_cen4`
  (lot = LOT2402~LOT2405, 같은 임베딩 중심 공유 → 그룹 내 코사인 ≈0.95 ≥ 0.8).
  전부 Etch ETCH-9 스펙 이탈 로그 보유.
- 따라서 **`W2406_02` 한 장 입력 → 형제 묶기 결과 = 위 7장** (02/04/06 + cen1~4).
- 대조군(형제 lot 합집합) = LOT2406 의 `W2406_01/03/05` + LOT2402~05 의 정상
  wafer(`W2401_xxx`, 93~99)들. `W2406_07`(88.5)은 제외.
- `LOT2407`: `W2407_01`(87.5)/`W2407_02`(89.5)/`W2407_03`(92.5) 전부 none,
  임베딩은 무작위 → 서로 형제 아님. `[W2407_01]` 단독 입력 = isolated 케이스,
  `[W2407_01, W2407_02]` 그룹 입력 = 대조군 1장(<3) → control_insufficient 케이스.
- 인덱스 총 107장 (SIBLING_SEARCH_K=50 < 107 이라 hnswlib k 초과 없음).

## 파일 구조

- Create: `tools/grouping.py` — 정규화 계층 (형제 묶기 + 대조군 선정). 결정론.
- Create: `tools/target_selection.py` — 대상 선정 앞단 (자동 모드 자리, 데모 사용).
- Create: `tests/test_grouping.py`, `tests/test_target_selection.py`
- Modify: `config.py`(상수), `tools/yield_tools.py`(헬퍼 2개·threshold 바인딩·잔재),
  `graph/state.py`, `graph/nodes.py`, `graph/build.py`, `llm/client.py`, `main.py`, `README.md`
- Tests modify: `tests/test_state.py`, `tests/test_graph_nodes.py`, `tests/test_build.py`,
  `tests/test_mock_llm.py`, `tests/test_e2e.py`, `tests/test_yield_tools.py`

finalize_status 최종 어휘: `confirmed | inconclusive | no_anomaly | unknown_target |
isolated | control_insufficient` (기존 `ungrouped` 는 소멸 — 출구 자체가 사라짐).

---

### Task 1: config 상수 3개

**Files:**
- Modify: `config.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `config.SIBLING_MIN_SIMILARITY: float`(기본 0.8, env 오버라이드),
  `config.CONTROL_MIN_SIZE: int`(기본 3, env 오버라이드), `config.SIBLING_SEARCH_K: int`(50, 고정).

- [ ] **Step 1: 실패 테스트** — `tests/test_state.py` 의 `test_loop_config_exists` 에 추가:

```python
def test_loop_config_exists():
    assert config.MAX_LOOPS == 6
    assert config.CONFIDENCE_THRESHOLD == 0.8
    assert config.SIBLING_MIN_SIMILARITY == 0.8
    assert config.CONTROL_MIN_SIZE == 3
    assert config.SIBLING_SEARCH_K == 50
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_state.py -q` → AttributeError 로 FAIL.
- [ ] **Step 3: 구현** — `config.py` 의 EDS 블록 아래에 추가:

```python
# 형제 묶기 (status 입력 재설계): "같은 사건" 판정이라 유사 사례 검색(0.5)보다 높게.
# 실행 중 불변이므로 결정론 원칙과 충돌 없음 (재설계 문서 6절 2번).
SIBLING_MIN_SIMILARITY = float(os.getenv("SIBLING_MIN_SIMILARITY", "0.8"))
SIBLING_SEARCH_K = 50          # 형제 후보 조회 폭 (인덱스 크기 미만이면 됨)
# 대조군 "부족" 판정 최소 크기 (재설계 문서 7절 — 미만이면 확장 대신 정직 보고)
CONTROL_MIN_SIZE = int(os.getenv("CONTROL_MIN_SIZE", "3"))
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_state.py -q` → PASS.
- [ ] **Step 5: 커밋** — `feat: 형제 묶기·대조군 상수 (SIBLING_MIN_SIMILARITY, CONTROL_MIN_SIZE)`

---

### Task 2: yield_tools 헬퍼 + threshold 바인딩 수정 (문제 9·8 일부)

**Files:**
- Modify: `tools/yield_tools.py`
- Test: `tests/test_yield_tools.py`

**Interfaces:**
- Produces: `yt.get_wafers(wafer_ids: list[str]) -> list[dict]` (yield 행들, wafer_id 순),
  `yt.find_normal_wafers(lot_id: str, threshold: float | None = None) -> list[str]`
  (defect 'none' & yield ≥ threshold, wafer_id 순),
  `yt.find_low_yield_lots(threshold: float | None = None)` (기본 인자 런타임 해석).

- [ ] **Step 1: 실패 테스트** — `tests/test_yield_tools.py` 에 추가:

```python
def test_get_wafers_returns_rows_for_known_ids_only():
    rows = yt.get_wafers(["W2406_02", "W_NOPE", "W2406_01"])
    assert [r["wafer_id"] for r in rows] == ["W2406_01", "W2406_02"]  # 미존재는 조용히 제외
    assert rows[1]["lot_id"] == "LOT2406"


def test_find_normal_wafers_applies_yield_threshold():
    # 구멍 (가): W2406_07 은 none 이지만 88.5 < 90 → 대조군 후보에서 제외
    assert yt.find_normal_wafers("LOT2406") == ["W2406_01", "W2406_03", "W2406_05"]


def test_find_low_yield_lots_threshold_binds_at_runtime(monkeypatch):
    # 문제 9: 기본 인자가 import 시점 값으로 굳으면 런타임 변경이 무시된다
    monkeypatch.setattr(config, "YIELD_THRESHOLD", 0.0)
    assert yt.find_low_yield_lots() == []
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_yield_tools.py -q`
  → 앞 2개는 AttributeError, 마지막은 (기본 인자 고정 탓에) assert 실패.
- [ ] **Step 3: 구현** — `find_low_yield_lots` 시그니처를
  `def find_low_yield_lots(threshold: float | None = None) -> list[dict]:` 로 바꾸고
  본문 첫 줄에 `threshold = config.YIELD_THRESHOLD if threshold is None else threshold` 추가.
  docstring 의 "(시나리오 1)" / "시나리오 2(그 wafer 로 유사 검색)" 문구를 현재 용도로 교체
  (문제 8: 죽은 시나리오 언급 제거 — "자동 대상 선정(tools/target_selection.py)의 재료" 로).
  `find_defect_group` 은 이 Task 에서 건드리지 않는다 (Task 6 에서 제거).
  아래 두 함수를 `get_wafer` 뒤에 추가:

```python
def get_wafers(wafer_ids: list[str]) -> list[dict]:
    """여러 wafer 의 yield 행 반환 (존재하는 것만, wafer_id 순 — 입력 검증·소속 lot 조회용)."""
    if not wafer_ids:
        return []
    placeholders = ",".join("?" * len(wafer_ids))
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM yield WHERE wafer_id IN ({placeholders}) ORDER BY wafer_id",
            wafer_ids,
        ).fetchall()
        return [dict(r) for r in rows]


def find_normal_wafers(lot_id: str, threshold: float | None = None) -> list[str]:
    """lot 의 정상 대조군 후보: defect 'none' 이면서 수율 임계 이상 (target 과 대칭 조건)."""
    threshold = config.YIELD_THRESHOLD if threshold is None else threshold
    with _conn() as conn:
        return [r["wafer_id"] for r in conn.execute(
            """
            SELECT wafer_id FROM yield
            WHERE lot_id = ? AND defect_type = 'none' AND yield >= ?
            ORDER BY wafer_id
            """,
            (lot_id, threshold),
        ).fetchall()]
```

- [ ] **Step 4: 통과 확인** — `python -m pytest -q` → 전체 green.
- [ ] **Step 5: 커밋** — `feat: get_wafers·find_normal_wafers 헬퍼 + threshold 런타임 바인딩 (문제 9)`

---

### Task 3: 정규화 계층 `tools/grouping.py`

**Files:**
- Create: `tools/grouping.py`
- Test: `tests/test_grouping.py`

**Interfaces:**
- Consumes: `yt.get_wafers`, `yt.find_normal_wafers`(Task 2),
  `tools.eds_search.get_searcher`, `config.SIBLING_*`, `config.CONTROL_MIN_SIZE`.
- Produces:
  - `normalize_target(wafers: list[str]) -> dict` — 키:
    `mode`("single"|"group"), `target_group: list[str]`,
    `siblings: list[{wafer_id, similarity}]`(single 일 때만, 유사도 내림차순),
    `unknown_wafers: list[str]`, `isolated: bool`,
    `label_counts: list[{defect_type, count}]`(참고 정보 — 판정에 미사용).
  - `select_control(target_group: list[str]) -> dict` — 키:
    `control_group: list[str]`, `sources: dict[lot_id, list[wafer_id]]`,
    `stage: int`(항상 1), `insufficient: bool`.

- [ ] **Step 1: 실패 테스트** — `tests/test_grouping.py` 신규 작성:

```python
"""정규화 계층 검증 — 형제 묶기(EDS)와 대조군 선정(형제 lot 합집합). 더미 DB seed 42 고정."""

from tools import grouping

CEN_SIBLINGS = ["W2410_cen1", "W2411_cen2", "W2412_cen3", "W2413_cen4"]


def test_single_input_expands_to_eds_siblings_across_lots():
    # Q1 확정: 한 장 입력 → EDS 유사맵(컷오프 0.8)으로 형제 묶기, 전 lot 탐색
    res = grouping.normalize_target(["W2406_02"])
    assert res["mode"] == "single"
    assert res["isolated"] is False
    assert set(res["target_group"]) == {"W2406_02", "W2406_04", "W2406_06", *CEN_SIBLINGS}
    assert res["target_group"][0] == "W2406_02"          # 입력 wafer 가 선두
    sims = [s["similarity"] for s in res["siblings"]]
    assert sims == sorted(sims, reverse=True)            # 유사도 내림차순
    assert all(s >= 0.8 for s in sims)
    # defect 라벨은 참고 정보로만 (판정 기준 아님 — 6절 3번)
    assert res["label_counts"][0]["defect_type"] == "center_spot"


def test_group_input_passes_through_without_grouping():
    res = grouping.normalize_target(["W2407_01", "W2407_02"])
    assert res["mode"] == "group"
    assert res["target_group"] == ["W2407_01", "W2407_02"]
    assert res["siblings"] == []


def test_single_input_with_no_siblings_is_isolated():
    # 6절 4번: 형제가 안 잡히면 isolated (자동 분석 범위 밖)
    res = grouping.normalize_target(["W2407_01"])
    assert res["isolated"] is True
    assert res["target_group"] == ["W2407_01"]


def test_unknown_wafer_is_reported():
    res = grouping.normalize_target(["W_NOPE", "W2406_02"])
    assert res["unknown_wafers"] == ["W_NOPE"]


def test_control_is_union_of_sibling_lots_with_yield_condition():
    # 7절 1단계: 형제 각자의 lot 에서 none+수율임계 wafer 합집합. 출처 명시.
    res = grouping.select_control(["W2406_02", "W2410_cen1"])   # LOT2406 + LOT2402
    assert res["stage"] == 1
    assert res["insufficient"] is False
    assert set(res["sources"]) == {"LOT2406", "LOT2402"}
    assert res["sources"]["LOT2406"] == ["W2406_01", "W2406_03", "W2406_05"]
    assert "W2406_07" not in res["control_group"]        # 88.5 < 90 — 오염원 제외 (문제 2)
    assert set(res["control_group"]) == {w for ws in res["sources"].values() for w in ws}


def test_control_excludes_target_members():
    # 대조군 후보 조건을 우연히 만족하는 target 멤버가 있어도 자기 자신과 대조하지 않는다
    res = grouping.select_control(["W2406_01", "W2406_02"])     # W2406_01 은 none·93+
    assert "W2406_01" not in res["control_group"]


def test_control_insufficient_reported_honestly():
    # 7절 3단계: 부족하면 확장하지 않고 정직 보고 (LOT2407 대조군 후보 = W2407_03 뿐)
    res = grouping.select_control(["W2407_01", "W2407_02"])
    assert res["control_group"] == ["W2407_03"]
    assert res["insufficient"] is True
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_grouping.py -q` → ModuleNotFoundError.
- [ ] **Step 3: 구현** — `tools/grouping.py` 신규:

```python
"""대상 정규화 계층 (결정론 — LLM 불개입).

status 입력 재설계(2026-07-18 문서 3절)의 두 입력 형태를 한 형태로 맞춘다:
  - 한 장 입력 → EDS 형제 묶기 (컷오프 config.SIBLING_MIN_SIMILARITY 고정, 전 lot 탐색)
  - 그룹 입력 → 그대로 target_group
대조군은 형제 각자의 lot 내 합집합(1단계). 부족하면 확장하지 않고 정직 보고한다.
defect 라벨은 판정 기준이 아니라 참고 정보다 (6절 3번 — 유사맵이 이긴다).
"""

import config
from tools import yield_tools as yt
from tools.eds_search import get_searcher

_searcher = None  # hnswlib 인덱스 로드는 무거우므로 최초 사용 시 1회만


def _searcher_lazy():
    global _searcher
    if _searcher is None:
        _searcher = get_searcher()
    return _searcher


def normalize_target(wafers: list[str]) -> dict:
    known = {r["wafer_id"] for r in yt.get_wafers(wafers)}
    unknown = [w for w in wafers if w not in known]
    mode = "single" if len(wafers) == 1 else "group"
    target, siblings, isolated = list(wafers), [], False

    if mode == "single" and not unknown:
        cands = _searcher_lazy().search(wafers[0], k=config.SIBLING_SEARCH_K)
        siblings = [c for c in cands if c["similarity"] >= config.SIBLING_MIN_SIMILARITY]
        target = wafers + [s["wafer_id"] for s in siblings]   # 입력 선두 + 유사도 내림차순
        isolated = not siblings

    return {
        "mode": mode,
        "target_group": target,
        "siblings": siblings,
        "unknown_wafers": unknown,
        "isolated": isolated,
        "label_counts": yt.aggregate_defects(target) if not unknown else [],
    }


def select_control(target_group: list[str]) -> dict:
    lots = sorted({r["lot_id"] for r in yt.get_wafers(target_group)})
    targets = set(target_group)
    sources = {}
    for lot in lots:
        cands = [w for w in yt.find_normal_wafers(lot) if w not in targets]
        if cands:
            sources[lot] = cands
    control = sorted({w for ws in sources.values() for w in ws})
    # 2단계(같은 root_lot 의 다른 양산랏 확장)는 lot_type 컬럼(ETL 이후) 전제 —
    # 규칙만 확정된 상태라 자리만 남긴다 (재설계 문서 7절).
    return {
        "control_group": control,
        "sources": sources,
        "stage": 1,
        "insufficient": len(control) < config.CONTROL_MIN_SIZE,
    }
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_grouping.py -q` → PASS, 전체도 green.
- [ ] **Step 5: 커밋** — `feat: 정규화 계층 grouping — EDS 형제 묶기(전 lot) + 대조군 형제 lot 합집합`

---

### Task 4: 대상 선정 앞단 `tools/target_selection.py`

**Files:**
- Create: `tools/target_selection.py`
- Test: `tests/test_target_selection.py`

**Interfaces:**
- Consumes: `yt.find_low_yield_lots`(Task 2 시그니처).
- Produces: `auto_select_targets() -> list[str]` — 자동 모드: 최악 lot 의 최저 수율
  wafer 1장(형제 묶기는 status 몫). 이상 없으면 `[]`.

- [ ] **Step 1: 실패 테스트** — `tests/test_target_selection.py` 신규:

```python
"""대상 선정 앞단 — 자동 모드 자리 (Q3: status 밖으로 분리, 데모가 사용)."""

from tools import target_selection as ts
from tools import yield_tools as yt


def test_auto_select_picks_worst_wafer_of_worst_lot():
    # 더미: 최악 lot = LOT2406, 그 최저 wafer 는 불량 그룹(76~82) 중 하나
    picked = ts.auto_select_targets()
    assert len(picked) == 1
    assert picked[0] in {"W2406_02", "W2406_04", "W2406_06"}
    worst = yt.find_low_yield_lots()[0]["worst_wafer"]["wafer_id"]
    assert picked == [worst]


def test_auto_select_returns_empty_when_no_anomaly(monkeypatch):
    monkeypatch.setattr(yt, "find_low_yield_lots", lambda: [])
    assert ts.auto_select_targets() == []
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_target_selection.py -q` → ModuleNotFoundError.
- [ ] **Step 3: 구현** — `tools/target_selection.py` 신규:

```python
"""대상 선정 앞단 — status 는 "대상은 정해져서 들어온다" (재설계 문서 Q3 확정).

수동 모드: 사용자가 lot_wafer 결합 형태({root_lot_id}_{wafer_id}) 목록을 직접 준다 (main.py).
자동 모드: 이 모듈이 대상을 고른다. 지금은 "최악 lot 의 최저 wafer 1장" 휴리스틱이며,
나중에 붙을 자동 대상 판단 시스템은 이 함수를 같은 인터페이스(-> list[str])로 대체한다.
"""

from tools import yield_tools as yt


def auto_select_targets() -> list[str]:
    lots = yt.find_low_yield_lots()
    if not lots:
        return []
    return [lots[0]["worst_wafer"]["wafer_id"]]
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_target_selection.py -q` → PASS.
- [ ] **Step 5: 커밋** — `feat: 대상 선정 앞단 target_selection (자동 모드 자리, 데모 사용)`

---

### Task 5: 그래프 재배선 — state·status_node·라우팅·LLM 클라이언트 (본체)

가장 큰 작업. state 의 `question` 을 `target_wafers`/`target_source` 로 바꾸면
nodes/build/client/테스트가 함께 움직여야 suite 가 green 이 되므로 한 Task 로 묶는다.

**Files:**
- Modify: `graph/state.py`, `graph/nodes.py`, `graph/build.py`, `llm/client.py`
- Test: `tests/test_graph_nodes.py`, `tests/test_build.py`, `tests/test_mock_llm.py`,
  `tests/test_e2e.py`, `tests/test_state.py`

**Interfaces:**
- Consumes: `grouping.normalize_target`/`select_control`(Task 3).
- Produces:
  - `AgentState`: `question` 제거, `target_wafers: list[str]`·`target_source: str` 추가.
  - seed HumanMessage 마지막 줄 = `GROUPS_JSON={"target": [...], "control": [...]}`
    (json.dumps, ensure_ascii=False — mock 파싱 계약, 문제 7 해소).
  - `LLMClient.generate_report(target_wafers, target_source, target_group,
    status_summary, findings, hypothesis, confidence, finalize_status=None)`
    — `question` 파라미터 제거.
  - `_after_status`: `finalize_status` 유무로 라우팅 (있으면 report).
  - status 감사 기록 tool 이름: `normalize_target`, `select_control` (loop 0).

- [ ] **Step 1: 실패 테스트 일괄 수정.**

`tests/test_graph_nodes.py` — status 관련 5개 테스트 교체 (finalize 게이트·report 테스트는
`question` 키만 제거하면 그대로):

```python
def test_status_node_sets_groups_and_seed_messages():
    out = nodes.status_node({"target_wafers": ["W2406_02"], "target_source": "manual"})
    assert out["target_group"][0] == "W2406_02"
    assert {"W2406_04", "W2406_06"} < set(out["target_group"])   # EDS 형제 (전 lot)
    assert "W2406_07" not in out["control_group"]                # 수율 조건 (문제 2)
    seed = out["messages"][-1].content
    assert "GROUPS_JSON=" in seed                                # mock 파싱 계약 (문제 7)
    assert [f["tool"] for f in out["findings"]] == ["normalize_target", "select_control"]
    assert all(f["loop"] == 0 for f in out["findings"])


def test_status_exit_no_anomaly_when_no_targets():
    # 자동 선정이 빈손이면(이상 lot 없음) 대상 없음 = no_anomaly
    out = nodes.status_node({"target_wafers": [], "target_source": "auto"})
    assert out["target_group"] == []
    assert out["finalize_status"] == "no_anomaly"


def test_status_exit_unknown_target():
    out = nodes.status_node({"target_wafers": ["W_NOPE"], "target_source": "manual"})
    assert out["finalize_status"] == "unknown_target"
    assert "W_NOPE" in out["status_summary"]


def test_status_exit_isolated_when_no_siblings():
    # 6절 4번: 형제 없음 = 고립 패턴, 자동 분석 범위 밖 — 별도 상태로 리포트까지
    out = nodes.status_node({"target_wafers": ["W2407_01"], "target_source": "manual"})
    assert out["finalize_status"] == "isolated"


def test_status_exit_control_insufficient():
    # 7절 3단계: 대조군 부족은 확장하지 않고 정직 보고
    out = nodes.status_node({"target_wafers": ["W2407_01", "W2407_02"],
                             "target_source": "manual"})
    assert out["finalize_status"] == "control_insufficient"
    assert out["target_group"] == ["W2407_01", "W2407_02"]


def test_status_respects_user_specified_target():
    # (구 xfail 소생 — 문제 1) 지정 대상이 그대로 분석 대상이 된다. lots[0] 하이재킹 없음.
    out = nodes.status_node({"target_wafers": ["W2407_01", "W2407_02"],
                             "target_source": "manual"})
    assert out["target_group"] == ["W2407_01", "W2407_02"]
    assert not {"W2406_02", "W2406_04", "W2406_06"} & set(out["target_group"])
```

기존 `test_status_exit_ungrouped_is_distinguishable` 은 삭제 (출구 소멸),
`@pytest.mark.xfail` 데코레이터와 구 본문도 삭제.
`test_report_node_produces_report`/`test_report_node_marks_inconclusive_conclusion` 의
state dict 에서 `"question": "q"` 를
`"target_wafers": ["W2406_02"], "target_source": "manual"` 로 교체.

`tests/test_build.py` — status 라우팅 2개 교체:

```python
def test_status_without_early_exit_goes_analyze():
    assert _after_status({"target_group": ["W2406_02"]}) == "analyze"


def test_status_with_early_exit_status_goes_report():
    # 대상 없음/미지 대상/고립/대조군 부족 — finalize_status 가 찍힌 조기 출구는 전부 report
    assert _after_status({"target_group": [], "finalize_status": "no_anomaly"}) == "report"
    assert _after_status({"target_group": ["W2407_01", "W2407_02"],
                          "finalize_status": "control_insufficient"}) == "report"
```

`tests/test_mock_llm.py` — HUMAN 을 GROUPS_JSON 포함으로 교체, report 호출 시그니처 교체:

```python
HUMAN = HumanMessage(
    "현황: ...\n\n불량 그룹 (center_spot): W2406_02, W2406_04, W2406_06\n"
    "대조 그룹 (정상): W2406_01, W2406_03, W2406_05\n"
    "분석 대상: W2406_02 의 불량 원인 분석\n"
    'GROUPS_JSON={"target": ["W2406_02", "W2406_04", "W2406_06"], '
    '"control": ["W2406_01", "W2406_03", "W2406_05"]}'
)
```

- `test_scripted_sequence` 본문은 그대로 (파싱 소스만 바뀜).
- `generate_report(...)` 호출들의 `question="..."` 를
  `target_wafers=["W2406_02"], target_source="manual"` 로 교체 (전 테스트 동일).
- `test_generate_report_distinguishes_ungrouped_from_no_anomaly` 를 교체:

```python
def test_generate_report_distinguishes_early_exits():
    # 조기 출구 4종이 서로 뭉개지지 않는다 (문제 3 의 일반화)
    llm = ScriptedMockLLMClient()
    kw = dict(target_wafers=["W2407_01"], target_source="manual",
              status_summary="s", findings=[], hypothesis=None, confidence=None)
    isolated = llm.generate_report(target_group=["W2407_01"], finalize_status="isolated", **kw)
    short = llm.generate_report(target_group=["W2407_01"],
                                finalize_status="control_insufficient", **kw)
    unknown = llm.generate_report(target_group=[], finalize_status="unknown_target", **kw)
    no_anomaly = llm.generate_report(target_group=[], finalize_status="no_anomaly", **kw)
    assert "고립" in isolated and "추후 분석" in isolated       # 6절 4번 문구
    assert "대조군 부족" in short                               # 7절 3단계 문구
    assert "찾을 수 없" in unknown
    assert "이상 없음" in no_anomaly
    assert "이상 없음" not in isolated
```

- mock `_groups` 계약 테스트 추가:

```python
def test_groups_parsed_from_machine_line_not_prose():
    # 사람용 문구를 바꿔도 GROUPS_JSON 라인만 있으면 mock 이 안 깨진다 (문제 7)
    llm = ScriptedMockLLMClient()
    msg = HumanMessage('아무 문구나 자유롭게.\nGROUPS_JSON={"target": ["A"], "control": ["B"]}')
    ai = llm.analyze_step([msg])
    assert ai.tool_calls[0]["args"]["wafer_ids"] == ["A"]
```

`tests/test_e2e.py` — 두 테스트 교체:

```python
def test_full_loop_reaches_report_with_audit_trail():
    state = build_graph().invoke(
        {"target_wafers": ["W2406_02"], "target_source": "manual"}
    )
    # 형제 묶기(전 lot): 최근 3장 + 과거 center_spot 4장이 한 사건으로 묶인다
    assert set(state["target_group"]) == {
        "W2406_02", "W2406_04", "W2406_06",
        "W2410_cen1", "W2411_cen2", "W2412_cen3", "W2413_cen4",
    }
    assert "W2406_07" not in state["control_group"]      # 수율 조건 (문제 2)
    assert set(state["control_group"]) >= {"W2406_01", "W2406_03", "W2406_05"}
    assert state["report"]

    gate_results = [f["result"] for f in state["findings"] if f["tool"] == "finalize"]
    assert any("반려" in r for r in gate_results)
    assert any("승인" in r for r in gate_results)
    assert state["finalize_accepted"] is True
    assert "ETCH-9" in state["final_hypothesis"]

    tools_used = [f["tool"] for f in state["findings"]]
    assert tools_used[:2] == ["normalize_target", "select_control"]   # loop 0 골격
    for expected in ("aggregate_defects", "compare_process_logs"):
        assert expected in tools_used
    assert state["loop_count"] <= 6


def test_no_targets_short_circuits_to_report():
    """자동 선정이 빈손(이상 lot 없음)이면 크래시 없이 '이상 없음' 리포트로 조기 종료."""
    state = build_graph().invoke({"target_wafers": [], "target_source": "auto"})
    assert state["report"]
    assert state["target_group"] == []
    assert state["finalize_status"] == "no_anomaly"
    assert state["findings"] == []           # 분석 루프도 그룹 묶기도 돌지 않았다
```

`tests/test_state.py` — invoke 입력을 `{"target_wafers": []}` 로 교체.

- [ ] **Step 2: 실패 확인** — `python -m pytest -q` → 다수 FAIL/ERROR (구현 전이므로 정상.
  새 status 테스트는 KeyError/AssertionError, mock 테스트는 파싱 ValueError 계열).
- [ ] **Step 3: 구현.**

`graph/state.py` — 필드 교체:

```python
class AgentState(TypedDict, total=False):
    target_wafers: list[str]                        # 분석 대상 입력 (lot_wafer 결합 형태)
    target_source: str                              # 입력 출처: manual | auto
    messages: Annotated[list, add_messages]         # LLM 대화 누적 (루프의 문맥)
    findings: Annotated[list[dict], operator.add]   # 감사 기록 누적 (분석 근거)
    target_group: list[str]                         # 정규화 계층이 확정한 불량 그룹
    control_group: list[str]                        # 형제 lot 합집합 대조 그룹
    status_summary: str                             # 현황파악 요약 (리포트 재료)
    loop_count: int                                 # 순환 횟수 (가드레일)
    finalize_accepted: bool                         # 게이트 승인 여부
    finalize_status: str    # confirmed | inconclusive | no_anomaly | unknown_target | isolated | control_insufficient
    final_hypothesis: str                           # 승인된 원인 가설
    final_confidence: float                         # 승인 시 확신도
    report: str                                     # 최종 리포트
```

`graph/nodes.py` — `status_node`/`_summarize_lots` 를 아래로 교체
(`from tools import grouping` import 추가; `yt` import 는 tools_node 가 계속 쓰므로 유지):

```python
def status_node(state: dict) -> dict:
    targets = state.get("target_wafers") or []
    source = state.get("target_source", "manual")
    if not targets:   # 자동 선정이 빈손 = 이상 없음 (수동 모드 빈 입력은 main 이 차단)
        return {"target_group": [], "control_group": [],
                "status_summary": "수율 임계 미만인 lot 없음 (자동 선정 결과 없음).",
                "findings": [], "finalize_status": "no_anomaly"}

    norm = grouping.normalize_target(targets)
    findings = [{"loop": 0, "tool": "normalize_target", "args": {"wafers": targets},
                 "result": norm, "thought": "대상 정규화 (고정 골격)"}]
    if norm["unknown_wafers"]:
        summary = f"입력 wafer 미존재: {', '.join(norm['unknown_wafers'])}"
        return {"target_group": [], "control_group": [], "status_summary": summary,
                "findings": findings, "finalize_status": "unknown_target"}
    if norm["isolated"]:
        summary = (f"분석 대상 입력 ({source}): {', '.join(targets)}\n"
                   f"형제 묶기 (EDS, 컷오프 {config.SIBLING_MIN_SIMILARITY}): 형제 없음 — "
                   f"고립 패턴, 자동 분석 범위 밖.")
        return {"target_group": norm["target_group"], "control_group": [],
                "status_summary": summary, "findings": findings,
                "finalize_status": "isolated"}

    ctrl = grouping.select_control(norm["target_group"])
    findings.append({"loop": 0, "tool": "select_control",
                     "args": {"target_group": norm["target_group"]},
                     "result": ctrl, "thought": "대조군 선정 (고정 골격)"})
    summary = _summarize_target(source, targets, norm, ctrl)
    if ctrl["insufficient"]:
        return {"target_group": norm["target_group"],
                "control_group": ctrl["control_group"],
                "status_summary": summary, "findings": findings,
                "finalize_status": "control_insufficient"}

    label = norm["label_counts"][0]["defect_type"] if norm["label_counts"] else "미상"
    groups_json = json.dumps(
        {"target": norm["target_group"], "control": ctrl["control_group"]},
        ensure_ascii=False)
    seed = [
        SystemMessage(content=ANALYZE_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"현황:\n{summary}\n\n"
            f"불량 그룹 ({label}): {', '.join(norm['target_group'])}\n"
            f"대조 그룹 (정상): {', '.join(ctrl['control_group'])}\n"
            f"분석 대상: {', '.join(targets)} 의 불량 원인 분석\n"
            f"GROUPS_JSON={groups_json}"
        )),
    ]
    return {
        "messages": seed,
        "target_group": norm["target_group"],
        "control_group": ctrl["control_group"],
        "status_summary": summary,
        "findings": findings,
    }


def _summarize_target(source: str, targets: list[str], norm: dict, ctrl: dict) -> str:
    lines = [f"분석 대상 입력 ({source}): {', '.join(targets)}"]
    if norm["mode"] == "single":
        sib = ", ".join(f"{s['wafer_id']}({s['similarity']})" for s in norm["siblings"])
        lines.append(f"형제 묶기 (EDS, 컷오프 {config.SIBLING_MIN_SIMILARITY}): "
                     f"{len(norm['target_group'])}장 — 입력 + {sib}")
    else:
        lines.append(f"그룹 입력: {len(norm['target_group'])}장 그대로 사용 (묶기 생략)")
    labels = ", ".join(f"{c['defect_type']} {c['count']}장" for c in norm["label_counts"])
    lines.append(f"defect 라벨 (참고): {labels}")
    src = ", ".join(f"{lot} {len(ws)}장" for lot, ws in sorted(ctrl["sources"].items()))
    lines.append(f"대조군 ({ctrl['stage']}단계: 형제 lot 내 합집합): "
                 f"{len(ctrl['control_group'])}장 — {src}")
    if ctrl["insufficient"]:
        lines.append(f"대조군 부족: {len(ctrl['control_group'])}장 < "
                     f"{config.CONTROL_MIN_SIZE} (lot 내 대조 한계 — 추후 분석 필요)")
    return "\n".join(lines)
```

`report_node` 교체:

```python
def report_node(state: dict) -> dict:
    report = _llm.generate_report(
        target_wafers=state.get("target_wafers", []),
        target_source=state.get("target_source", "manual"),
        target_group=state["target_group"],
        status_summary=state["status_summary"],
        findings=state["findings"],
        hypothesis=state.get("final_hypothesis"),
        confidence=state.get("final_confidence"),
        finalize_status=state.get("finalize_status"),
    )
    return {"report": report}
```

`graph/build.py` — `_after_status` 교체 (도킹 다이어그램 주석의 "대상 없음" 도 "조기 출구"로):

```python
def _after_status(state: dict) -> str:
    # 조기 출구(no_anomaly/unknown_target/isolated/control_insufficient)는 finalize_status 가
    # 이미 찍혀 있다 — 분석 루프를 건너뛰고 리포팅으로
    return "report" if state.get("finalize_status") else "analyze"
```

`llm/client.py` — 추상 메서드·mock·openai 세 곳 시그니처를
`generate_report(self, target_wafers, target_source, target_group, status_summary,
findings, hypothesis, confidence, finalize_status=None)` 로 교체.
`ScriptedMockLLMClient._groups` 교체 (문제 7 해소):

```python
    @staticmethod
    def _groups(messages) -> tuple[list[str], list[str]]:
        text = "\n".join(getattr(m, "content", "") or "" for m in messages
                         if isinstance(m, HumanMessage))
        m = re.search(r"GROUPS_JSON=(\{.*\})", text)
        if not m:
            raise ValueError("messages 에서 GROUPS_JSON 라인을 찾지 못했다")
        groups = json.loads(m.group(1))
        return groups["target"], groups["control"]
```

mock `generate_report` — 첫 줄과 결론 분기 교체:

```python
        lines = [
            f"[분석 대상 입력] ({target_source}) {', '.join(target_wafers) or '없음'}",
            f"[불량 그룹] {', '.join(target_group) or '없음'}",
            f"[현황] {status_summary}",
            "",
            "[분석 과정]",
        ]
        ...
        if finalize_status == "inconclusive":
            conclusion = f"미확정 (루프 한계 도달) — 유력 가설: {hypothesis or '없음'}"
        elif finalize_status == "no_anomaly":
            conclusion = "이상 없음 — 수율 임계 미만 lot 이 없다."
        elif finalize_status == "unknown_target":
            conclusion = "분석 미수행 — 입력 wafer 를 데이터에서 찾을 수 없다. 입력을 확인하라."
        elif finalize_status == "isolated":
            conclusion = ("분석 미수행 — 고립 패턴: 유사 형제 wafer 가 없어 그룹 대조가 "
                          "불가능하다. 추후 분석 필요.")
        elif finalize_status == "control_insufficient":
            conclusion = ("분석 미수행 — 대조군 부족 (lot 내 대조 한계). "
                          "root_lot 확장은 ETL(lot_type) 이후 활성화. 추후 분석 필요.")
        else:
            conclusion = hypothesis or "원인 미확정"
```

`OpenAILLMClient.generate_report` — user 프롬프트의 `질문: {question}` 을
`f"분석 대상 입력 ({target_source}): {', '.join(target_wafers)}"` 로 교체하고,
sys 프롬프트의 상태 안내를 새 어휘로 교체
(`ungrouped` 문구 삭제, `unknown_target`/`isolated`/`control_insufficient` 서술 추가:
"판정이 isolated/control_insufficient/unknown_target 이면 '분석 미수행'과 그 사유를
명시하고 확정 결론을 쓰지 마라").

- [ ] **Step 4: 통과 확인** — `python -m pytest -q` → 전체 green, **xfail 0** 확인.
- [ ] **Step 5: 커밋** — `feat: status 입력 재설계 — target_wafers 입력, EDS 형제 묶기, 대조군 합집합, 조기출구 4종 (문제 1·2·3·5·6·7 해소)`

---

### Task 6: find_defect_group 제거 (무참조 잔재)

**Files:**
- Modify: `tools/yield_tools.py`, `tests/test_yield_tools.py`

- [ ] **Step 1: 무참조 확인** — `grep -rn "find_defect_group" --include="*.py" .`
  → tests/test_yield_tools.py 와 정의뿐이어야 한다 (docs 는 무관).
- [ ] **Step 2: 제거** — `yield_tools.py` 의 `find_defect_group` 함수와
  `test_yield_tools.py` 의 `test_find_defect_group_*` 3개 테스트 삭제.
- [ ] **Step 3: 통과 확인** — `python -m pytest -q` → green.
- [ ] **Step 4: 커밋** — `refactor: find_defect_group 제거 — 정규화 계층(grouping)이 대체`

---

### Task 7: main.py CLI + README

**Files:**
- Modify: `main.py`, `README.md`

**Interfaces:**
- Consumes: `target_selection.auto_select_targets`(Task 4), 새 state 키(Task 5).
- CLI 계약: `python main.py [WAFER_ID ...]` — 인자 = lot_wafer 결합 형태 목록(수동),
  없으면 자동 선정(데모).

- [ ] **Step 1: 구현** — `main.py` 교체:

```python
"""실행 진입점.

수동 모드: python main.py W2406_02 [W2406_04 ...]
  - 인자 = 분석 대상 wafer (lot_wafer 결합 형태 {root_lot_id}_{wafer_id}, 예: A45Z4_13)
  - 1장이면 EDS 형제 묶기, 여러 장이면 그 그룹 그대로 분석
자동 모드(데모): 인자 없이 실행 — 대상 선정 앞단이 최악 lot 의 최저 wafer 를 고른다.
(Windows 콘솔 한글 깨짐 방지: PYTHONUTF8=1 python main.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph.build import build_graph            # noqa: E402
from tools import target_selection             # noqa: E402


def run(target_wafers: list[str], source: str) -> None:
    app = build_graph()
    state = app.invoke({"target_wafers": target_wafers, "target_source": source})

    print(f"[분석 대상 입력] ({source}) {', '.join(target_wafers) or '없음'}\n")
    print(f"[현황 파악 — 고정 골격]\n{state['status_summary']}\n")
    tg = state["target_group"]
    if tg and not state.get("finalize_status"):
        print(f"[분석 그룹] 불량 {', '.join(tg)}  /  대조 {', '.join(state['control_group'])}\n")

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
    if len(sys.argv) > 1:
        run(sys.argv[1:], "manual")
    else:
        run(target_selection.auto_select_targets(), "auto")
```

- [ ] **Step 2: 데모 검증 (수동 실행)** —
  - `python main.py` → 자동 선정 → 형제 7장 묶임 → ETCH-9 결론 리포트.
  - `python main.py W2406_02` → 위와 동일 그룹.
  - `python main.py W2407_01` → isolated 리포트 ("고립 패턴").
  - `python main.py W2407_01 W2407_02` → control_insufficient 리포트 ("대조군 부족").
  - `python main.py W_NOPE` → unknown_target 리포트.
- [ ] **Step 3: README 사용법 갱신** — `python main.py "질문"` 류 문구를 위 CLI 계약으로
  교체하고, 형제 묶기·대조군 규칙 요약 1~2문장 추가 (README 의 기존 어조 유지, 과장 금지).
- [ ] **Step 4: 전체 확인** — `python -m pytest -q` → green.
- [ ] **Step 5: 커밋** — `feat: CLI 를 대상 wafer 입력으로 전환 (수동/자동 모드) + README 갱신`

---

### Task 8: 문서 정리 — 해소된 미룸 항목 표시

**Files:**
- Modify: `docs/deferred-internal-integration.md`, `docs/2026-07-18-status-node-review-and-redesign.md`

- [ ] **Step 1:** `deferred-internal-integration.md` 8번 항목 중 이번에 해소된 것
  (mock 파싱 계약 ValueError, threshold 바인딩, worst_wafer docstring 잔재)에
  "→ 2026-07-19 status 입력 재설계에서 해소" 표시. 미해소 항목(C-1: finalize 후속 tool
  중단 등)은 그대로 둔다.
- [ ] **Step 2:** 재설계 문서 머리말에 "구현: `docs/superpowers/plans/2026-07-19-status-input-redesign.md` 로 확정 (2026-07-19)" 한 줄 추가.
- [ ] **Step 3: 커밋** — `docs: 입력 재설계 반영 — 미룸 항목 해소 표시`

---

## 완료 기준

1. `python -m pytest -q` 전체 green, **xfail 0** (구 xfail
   `test_status_respects_user_specified_target` 이 정식 테스트로 소생).
2. `python main.py W2406_02` 가 형제 7장을 묶고 ETCH-9 결론 리포트를 낸다.
3. 조기 출구 4종(no_anomaly/unknown_target/isolated/control_insufficient)이
   리포트에서 서로 구분된다.
4. `question` 키가 코드베이스(py)에서 사라진다 (`grep -rn '"question"' --include="*.py" .` 무결과).
