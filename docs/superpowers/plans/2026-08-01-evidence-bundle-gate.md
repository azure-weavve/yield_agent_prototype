# 게이트 강화 (EvidenceBundle) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 게이트가 도구 결과를 구조화된 증거(EvidenceBundle)로 받게 만들어, `no_signal` 을 루프 한계와 구분해 보고하고 승인 판정을 자유 텍스트 substring 매칭에서 claim_id 조회로 바꾼다.

**Architecture:** 도구(`domain/engine.py`)가 후보마다 `claim_id` 를 발급해 결과에 싣는다. 새 순수 함수 `graph/evidence.py::build_bundle(findings)` 가 감사 기록을 `Claim` 사전으로 투영한다 — 판별자는 `hypothesis_id` 키의 유무이고, 상태를 따로 저장하지 않는다. 게이트(`graph/nodes.py::_finalize_gate`)는 그 번들만 조회해 4줄짜리 판정표로 결정한다.

**Tech Stack:** Python 3, LangGraph, LangChain core(`AIMessage`/`ToolMessage`), pytest, sqlite3

설계 문서: `docs/superpowers/specs/2026-08-01-evidence-bundle-gate-design.md`

## Global Constraints

- 작업 디렉터리는 `prototype/`. 모든 명령은 여기서 실행한다.
- 전체 테스트: `python -m pytest -q`. **착수 시점 기준선은 163 passed** — 어느 Task 도 이 수를 줄이지 않는다. 기존 테스트를 고치는 Task(4)는 그 사실을 커밋 메시지에 남긴다.
- **TDD 강제.** 각 Task 는 실패하는 테스트를 먼저 쓰고, 실패를 눈으로 확인한 뒤 구현한다.
- 브랜치 `feat/evidence-bundle-gate` 에서 작업한다 (이미 생성됨, 스펙 커밋 `57678aa` 포함). **main 병합은 사용자가 결정한다** — 임의로 병합하거나 push 하지 않는다.
- 커밋 메시지는 한국어. 마지막 줄에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` 를 넣는다.
- **콘솔이 cp949 다.** 새로 쓰는 사용자 노출 문자열에 em-dash(`—`)를 넣지 않는다. 죽지는 않지만 `?` 로 깨진다. 코드 주석과 마크다운 문서에는 써도 된다.
- **범위 밖(스펙 11절)**: 2단 센서를 confirmed 필수 조건으로 만들지 않는다. `evidence_score` 가중합을 만들지 않는다. 시간축·사람 검토 폐루프·다인성은 손대지 않는다.
- `graph/nodes.py:18` 의 `from tools import yield_tools as yt` 는 이 작업 전부터 쓰이지 않는 import 다. **내 변경이 만든 것이 아니므로 지우지 않는다.**

---

## File Structure

| 파일 | 이 작업에서의 책임 | Task |
|---|---|---|
| `domain/engine.py` | 후보마다 `claim_id` 발급 (게이트가 조회할 키의 유일한 발급처) | 1 |
| `graph/evidence.py` | **신규.** findings -> `Bundle` 투영. 판정하지 않고 사실만 모은다 | 2 |
| `llm/client.py` | mock 각본의 claim_id 제출·ppid 폴백 · `no_signal` 리포트 문구 · `[근거]` 줄 · 운영 프롬프트 | 3, 4, 5 |
| `graph/nodes.py` | 게이트 판정표 · `ANALYZE_SYSTEM_PROMPT` claim_id 규칙 · `report_node` 의 claim 전달 | 4, 5 |
| `graph/state.py` | `final_claim` 상태 키 추가 | 4 |
| `tools/agent_tools.py` | `finalize(claim_id, hypothesis, confidence)` 시그니처와 docstring | 4 |
| `graph/build.py` | 모듈 docstring 문구만 (라우팅 코드 불변) | 8 |
| `tests/test_engine.py` | claim_id 발급 계약 | 1 |
| `tests/test_evidence.py` | **신규.** 번들 투영 단위 검증 | 2 |
| `tests/test_mock_llm.py` | 각본의 claim_id·ppid 폴백 · `no_signal` 리포트 · `[근거]` 줄 | 3, 4, 5 |
| `tests/test_graph_nodes.py` | 게이트 판정표 4줄 전부 | 4, 5 |
| `tests/test_adversarial_dummy.py` | 적대적 케이스 4종의 최종 판정 | 4, 6 |
| `README.md`·`docs/stages.md` | `finalize_status` 어휘 | 8 |

**Task 순서의 이유:** 3(mock)이 4(게이트)보다 앞이다. mock 이 `claim_id` 를 제출하고 ppid 폴백을 돌아도 **옛 게이트는 그 인자를 무시**하므로 스위트가 초록으로 유지된다. 반대 순서면 게이트가 claim_id 를 요구하는데 mock 이 안 보내는 구간이 생겨 E2E 가 통째로 빨개진다.

---

### Task 1: 후보마다 claim_id 발급

**Files:**
- Modify: `domain/engine.py:34-46` (`evaluate` 의 `candidates.append`)
- Test: `tests/test_engine.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: 없음 (첫 Task)
- Produces: `engine.evaluate()` 결과의 각 후보에 `claim_id: str` 키. 형식은 `f"{spec['id']}:{step_seq}:{key}"`. Task 2·3·4 가 이 키를 읽는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_engine.py` 파일 끝에 추가한다. `fx_db` 픽스처는 이미 파일 상단에 있다 (불량군 3장 전원 `Etch`=`ETCH9_B`, 대조군은 `ETCH8`).

```python
def test_evaluate_issues_claim_id_per_candidate(fx_db):
    """claim_id 는 게이트가 조회할 유일한 키다 — 도구가 발급해 결과에 실어 보낸다."""
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH},
                          ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    by_key = {c["key"]: c for c in res["candidates"]}
    assert by_key["ETCH9_B"]["claim_id"] == "eqp_ch:Etch:ETCH9_B"
    # 모든 후보가 발급받는다 (통과 여부와 무관 — 반려 사유를 돌려주려면 미통과도 조회돼야 한다)
    assert all(c["claim_id"] for c in res["candidates"])


def test_claim_id_is_namespaced_by_hypothesis(fx_db):
    """legend 가 다른 두 도구가 같은 (step, key) 를 내도 claim_id 는 충돌하지 않는다."""
    a = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    b = engine.evaluate({"id": "ppid", "legend": PPID}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    assert not ({c["claim_id"] for c in a["candidates"]} &
                {c["claim_id"] for c in b["candidates"]})
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_engine.py -k claim_id -v`
Expected: FAIL — `KeyError: 'claim_id'`

- [ ] **Step 3: 최소 구현**

`domain/engine.py` 의 `candidates.append({` 블록 첫 줄에 한 줄을 넣는다.

```python
        candidates.append({
            # 게이트가 조회할 유일한 키. 게이트는 이 문자열을 **파싱하지 않는다** —
            # 사전 조회에만 쓰므로 구분자가 값에 섞여도 안전하다. 콜론 형식을 쓰는
            # 이유는 감사 기록에서 사람이 읽을 수 있다는 것뿐이다.
            "claim_id": f"{spec['id']}:{cand['step_seq']}:{cand['key']}",
            "value": [cand["step_seq"], cand["key"]],
            "passes": passes,
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_engine.py -v`
Expected: 전부 PASS (기존 테스트는 후보 키를 집합으로 단언하지 않으므로 추가 키에 안전하다)

- [ ] **Step 5: 전체 회귀**

Run: `python -m pytest -q`
Expected: 165 passed (163 + 신규 2)

- [ ] **Step 6: 커밋**

```bash
git add domain/engine.py tests/test_engine.py
git commit -m "$(cat <<'EOF'
feat(engine): 후보마다 claim_id 발급

게이트가 자유 텍스트 대신 조회할 키. hypothesis_id 로 네임스페이스를
나눠 legend 가 다른 두 도구가 같은 (step, key) 를 내도 충돌하지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: EvidenceBundle 투영 (순수 함수)

**Files:**
- Create: `graph/evidence.py`
- Test: `tests/test_evidence.py` (신규)

**Interfaces:**
- Consumes: Task 1 의 `claim_id` 키.
- Produces:
  - `evidence.Claim` — frozen dataclass. 필드: `claim_id: str`, `tool: str`, `hypothesis_id: str`, `step_seq: str`, `key: str`, `level: str`, `passes: bool`, `reject_reason: str | None`, `score: float`, `target_pass: int`, `target_total: int`, `control_pass: int`, `control_total: int`
  - `evidence.Bundle` — frozen dataclass. 필드: `claims: dict[str, Claim]`, `statuses: dict[str, str]`, `ran: set[str]`. 메서드: `passing() -> list[Claim]`, `top_score(tool: str) -> float | None`
  - `evidence.build_bundle(findings: list[dict]) -> Bundle`
  - Task 4 의 게이트가 이 셋을 쓴다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_evidence.py` 를 새로 만든다.

```python
"""EvidenceBundle — findings 를 게이트가 읽는 구조화된 증거로 투영한다.

판정하지 않는다. 사실만 모은다. 판정은 graph/nodes.py 의 게이트가 한다.
"""

from graph import evidence


def _finding(tool, hypothesis_id, status, candidates, result=None):
    return {"loop": 1, "tool": tool, "args": {},
            "result": result if result is not None else {
                "hypothesis_id": hypothesis_id, "status": status,
                "candidates": candidates},
            "thought": "t"}


CAND_PASS = {"claim_id": "eqp_ch_commonality:CC002000:ETCH9_B", "level": "chamber",
             "step_seq": "CC002000", "key": "ETCH9_B", "passes": True,
             "reject_reason": None, "score": 1.0,
             "target_pass": 3, "target_total": 3, "control_pass": 0, "control_total": 6}
CAND_FAIL = {"claim_id": "eqp_ch_commonality:CD004000:PHOT2_X", "level": "chamber",
             "step_seq": "CD004000", "key": "PHOT2_X", "passes": False,
             "reject_reason": "분리 점수 0.3 < 0.5", "score": 0.3,
             "target_pass": 3, "target_total": 4, "control_pass": 2, "control_total": 5}


def test_build_bundle_collects_claims_and_status():
    b = evidence.build_bundle([_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                                        "ok", [CAND_PASS, CAND_FAIL])])
    assert set(b.claims) == {CAND_PASS["claim_id"], CAND_FAIL["claim_id"]}
    assert b.statuses == {"hyp_eqp_ch_commonality": "ok"}
    assert b.ran == {"hyp_eqp_ch_commonality"}
    # 미통과 후보도 담는다 — 게이트가 reject_reason 을 그대로 돌려주려면 조회돼야 한다
    assert b.claims[CAND_FAIL["claim_id"]].reject_reason == "분리 점수 0.3 < 0.5"
    assert [c.claim_id for c in b.passing()] == [CAND_PASS["claim_id"]]


def test_sensor_result_is_not_evidence():
    """센서 결과에도 candidates 키가 있다 — 덕타이핑이면 여기로 딸려 들어온다.

    판별자는 hypothesis_id 의 유무이지 candidates 의 유무가 아니다.
    """
    sensor = {"status": "ok", "candidates": [
        {"sensor_name": "rf_power_steady_avg", "effect_size": 14.99, "passes": True}]}
    b = evidence.build_bundle([{"loop": 1, "tool": "compare_sensor_distribution",
                                "args": {}, "result": sensor, "thought": "t"}])
    assert b.claims == {}
    assert b.ran == set()


def test_tool_error_string_does_not_count_as_ran():
    """'불렀다' 와 '근거를 냈다' 는 다르다 — 인자 오류로 실패한 도구는 ran 이 아니다."""
    b = evidence.build_bundle([_finding("hyp_ppid_commonality", None, None, None,
                                        result="오류: 실행 실패 (KeyError: 'legend')")])
    assert b.ran == set()
    assert b.statuses == {}


def test_no_signal_status_is_recorded_without_candidates():
    b = evidence.build_bundle([_finding("hyp_ppid_commonality", "ppid_commonality",
                                        "no_signal", [])])
    assert b.statuses == {"hyp_ppid_commonality": "no_signal"}
    assert b.ran == {"hyp_ppid_commonality"}
    assert b.passing() == []


def test_rerun_replaces_previous_claims_of_the_same_tool():
    """같은 도구를 다시 돌리면 앞 결과는 버린다 — 그룹이 바뀐 재실행이면 옛 후보는 거짓이다."""
    stale = {**CAND_PASS, "claim_id": "eqp_ch_commonality:CC002000:ETCH1_A", "key": "ETCH1_A"}
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [stale]),
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS]),
    ])
    assert set(b.claims) == {CAND_PASS["claim_id"]}


def test_top_score_is_per_tool():
    """legend 가 다른 두 도구의 점수는 비교 대상이 아니다."""
    ppid = {"claim_id": "ppid_commonality:CC002000:PPID_X", "level": "ppid",
            "step_seq": "CC002000", "key": "PPID_X", "passes": True,
            "reject_reason": None, "score": 0.6,
            "target_pass": 3, "target_total": 3, "control_pass": 2, "control_total": 5}
    decoy = {**CAND_PASS, "claim_id": "eqp_ch_commonality:CD004000:PHOT2_X",
             "key": "PHOT2_X", "score": 0.75}
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS, decoy]),
        _finding("hyp_ppid_commonality", "ppid_commonality", "ok", [ppid]),
    ])
    assert b.top_score("hyp_eqp_ch_commonality") == 1.0
    assert b.top_score("hyp_ppid_commonality") == 0.6
    assert b.top_score("hyp_nothing_ran") is None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_evidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graph.evidence'`

- [ ] **Step 3: 구현**

`graph/evidence.py` 를 새로 만든다.

```python
"""도구 결과를 게이트가 읽는 구조화된 증거로 투영한다 (EvidenceBundle).

게이트가 findings 를 덕타이핑으로 훑던 것을 대체한다. **판별자는 `hypothesis_id`
키의 유무**다 — `domain/engine.py` 의 결과에는 있고 `tools/sensor_compare.py` 의
결과에는 없다. 예전 판별자였던 `"candidates" in result` 는 센서 결과에도 걸린다.

여기는 판정하지 않는다. 사실만 모으고, 판정은 `graph/nodes.py` 의 게이트가 한다.
상태를 저장하지 않는 순수 함수이므로 감사 기록(findings)이 유일한 출처로 남는다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Claim:
    """도구가 발급한 후보 하나. LLM 이 만들어낼 수 없는 값들이다."""
    claim_id: str
    tool: str                 # findings 의 tool 이름 (hyp_eqp_ch_commonality)
    hypothesis_id: str
    step_seq: str
    key: str
    level: str
    passes: bool
    reject_reason: str | None
    score: float
    target_pass: int
    target_total: int
    control_pass: int
    control_total: int


@dataclass(frozen=True)
class Bundle:
    claims: dict[str, Claim]      # claim_id -> Claim (미통과 후보도 담는다)
    statuses: dict[str, str]      # tool 이름 -> 마지막 실행의 status
    ran: set[str]                 # 유효한 결과를 낸 hyp_* 도구 이름

    def passing(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.passes]

    def top_score(self, tool: str) -> float | None:
        """그 도구 안에서 통과 후보의 최고 점수. legend 가 다르면 비교 대상이 아니다."""
        scores = [c.score for c in self.claims.values() if c.tool == tool and c.passes]
        return max(scores) if scores else None


def _is_hypothesis_result(result) -> bool:
    return (isinstance(result, dict)
            and "hypothesis_id" in result and "candidates" in result)


def build_bundle(findings: list[dict]) -> Bundle:
    """감사 기록에서 가설 도구의 결과만 골라 Claim 사전으로 투영한다.

    `ran` 은 "호출됐다" 가 아니라 **"유효한 결과를 냈다"** 다. 인자 오류로 실패한
    도구는 결과가 dict 가 아니라 오류 문자열이므로 들어오지 않는다 — 게이트는
    그 도구를 계속 요구하고, 무한 재시도는 루프 한계가 잡는다.
    """
    claims: dict[str, Claim] = {}
    statuses: dict[str, str] = {}
    ran: set[str] = set()

    for f in findings:
        result = f.get("result")
        if not _is_hypothesis_result(result):
            continue
        tool = f.get("tool", "")
        ran.add(tool)
        statuses[tool] = result.get("status", "")
        # 재실행이면 앞 결과를 버린다 — 그룹이 바뀐 재실행에서 옛 후보는 거짓이다
        claims = {k: v for k, v in claims.items() if v.tool != tool}
        for c in result["candidates"]:
            claim_id = c.get("claim_id")
            if not claim_id:                       # claim_id 없는 후보는 지목 불가
                continue
            claims[claim_id] = Claim(
                claim_id=claim_id,
                tool=tool,
                hypothesis_id=result["hypothesis_id"],
                step_seq=c.get("step_seq", ""),
                key=c.get("key", ""),
                level=c.get("level", ""),
                passes=bool(c.get("passes")),
                reject_reason=c.get("reject_reason"),
                score=float(c.get("score") or 0.0),
                target_pass=int(c.get("target_pass") or 0),
                target_total=int(c.get("target_total") or 0),
                control_pass=int(c.get("control_pass") or 0),
                control_total=int(c.get("control_total") or 0),
            )
    return Bundle(claims=claims, statuses=statuses, ran=ran)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_evidence.py -v`
Expected: 6 passed

- [ ] **Step 5: 전체 회귀**

Run: `python -m pytest -q`
Expected: 171 passed (165 + 신규 6). 게이트는 아직 이 모듈을 쓰지 않으므로 다른 테스트에 영향이 없다.

- [ ] **Step 6: 커밋**

```bash
git add graph/evidence.py tests/test_evidence.py
git commit -m "$(cat <<'EOF'
feat(evidence): findings 를 Claim 사전으로 투영하는 순수 함수

판별자를 "candidates 키 유무"(센서 결과에도 걸린다)에서 hypothesis_id 로
바꿨다. ran 은 "불렀다" 가 아니라 "유효한 결과를 냈다" 를 뜻한다.
게이트는 아직 이 모듈을 쓰지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: mock 각본 — claim_id 제출과 ppid 폴백

**Files:**
- Modify: `llm/client.py:59-116` (`ScriptedMockLLMClient.analyze_step`)
- Test: `tests/test_mock_llm.py:29-64` (`test_scripted_sequence` 픽스처), `tests/test_mock_llm.py:126-147` (`test_scripted_survives_tool_error_string`), 파일 끝에 신규 2건

**Interfaces:**
- Consumes: Task 1 의 `claim_id`.
- Produces: mock 의 `finalize` tool_call args 가 `{"claim_id": str, "hypothesis": str, "confidence": float}` 형태가 된다. 근거가 없을 때 `claim_id` 는 빈 문자열 `""`. Task 4 의 게이트가 이 계약을 읽는다.

**이 Task 는 옛 게이트 아래에서도 초록이어야 한다.** 게이트는 아직 `claim_id` 를 무시하고, `hypothesis` 문자열에 여전히 `ETCH9_B` 가 들어 있어 substring 매칭이 성립한다. 케이스 4 도 ppid 를 한 번 더 돌 뿐 결국 확신도 0.2 로 반려되다 루프 한계에서 `inconclusive` 로 끝난다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

먼저 기존 픽스처를 고친다. `tests/test_mock_llm.py:45-48` 의 1단 결과 payload 에 `claim_id` 를 넣는다 (mock 이 그것을 읽어야 하므로).

```python
    msgs += [ai, _tm("hyp_eqp_ch_commonality", {"hypothesis_id": "eqp_ch_commonality",
                                                "status": "ok", "candidates": [
        {"level": "chamber", "key": "ETCH9_B", "value": ["Etch", "ETCH9_B"],
         "claim_id": "eqp_ch_commonality:Etch:ETCH9_B",
         "step_seq": "Etch", "score": 1.0, "target_pass": 3, "passes": True},
    ]})]
```

같은 테스트의 마지막 단언(현재 62-64행) 뒤에 한 줄을 더한다.

```python
    assert ai.tool_calls[0]["args"]["claim_id"] == "eqp_ch_commonality:Etch:ETCH9_B"
```

그리고 파일 끝에 신규 2건을 추가한다.

```python
def test_scripted_falls_back_to_ppid_when_eqp_ch_is_silent():
    """EQP_CH 로 안 갈리면 2차 legend(PPID)를 돌린다 — YAML 이 선언한 폴백 순서다.

    첫 no_signal 로 물러서면 등록된 가설 하나를 안 써보고 포기하는 셈이다.
    """
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]
    msgs += [llm.analyze_step(msgs), _tm("finalize", "반려")]          # 1) 조기 finalize
    ai = llm.analyze_step(msgs)                                        # 2) 1단 EQP_CH
    assert ai.tool_calls[0]["name"] == "hyp_eqp_ch_commonality"
    msgs += [ai, _tm("hyp_eqp_ch_commonality", {"hypothesis_id": "eqp_ch_commonality",
                                                "status": "no_signal", "candidates": []})]

    ai = llm.analyze_step(msgs)                                        # 3) 폴백 PPID
    assert ai.tool_calls[0]["name"] == "hyp_ppid_commonality"
    assert ai.tool_calls[0]["args"]["group_ids"] == TARGET
    assert ai.tool_calls[0]["args"]["control_ids"] == CONTROL
    msgs += [ai, _tm("hyp_ppid_commonality", {"hypothesis_id": "ppid_commonality",
                                              "status": "no_signal", "candidates": []})]

    ai = llm.analyze_step(msgs)                                        # 4) 물러선다
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] == 0.2
    assert ai.tool_calls[0]["args"]["claim_id"] == ""    # 지목할 근거가 없다


def test_scripted_uses_ppid_claim_when_eqp_ch_is_silent():
    """PPID 로 갈리면 그 claim_id 를 지목한다 — 폴백이 장식이 아니라 경로다."""
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]
    msgs += [llm.analyze_step(msgs), _tm("finalize", "반려")]
    msgs += [llm.analyze_step(msgs), _tm("hyp_eqp_ch_commonality",
                                         {"hypothesis_id": "eqp_ch_commonality",
                                          "status": "no_signal", "candidates": []})]
    ai = llm.analyze_step(msgs)
    msgs += [ai, _tm("hyp_ppid_commonality", {"hypothesis_id": "ppid_commonality",
                                              "status": "ok", "candidates": [
        {"level": "ppid", "key": "PPID_X", "value": ["CC002000", "PPID_X"],
         "claim_id": "ppid_commonality:CC002000:PPID_X", "step_seq": "CC002000",
         "score": 1.0, "target_pass": 3, "passes": True}]})]

    ai = llm.analyze_step(msgs)                          # 2단 센서로 넘어간다
    assert ai.tool_calls[0]["name"] == "compare_sensor_distribution"
    assert ai.tool_calls[0]["args"]["step_seq"] == "CC002000"
```

마지막으로 `test_scripted_survives_tool_error_string` 을 고친다. 오류 문자열도 "통과 후보 없음" 이므로 이제 폴백을 한 번 거친다. 현재 144-147행을 아래로 바꾼다.

```python
    ai = llm.analyze_step(msgs)                      # 3) 죽지 않고 폴백을 돈다
    assert ai.tool_calls[0]["name"] == "hyp_ppid_commonality"
    msgs += [ai, _tm("hyp_ppid_commonality",
                     json.dumps("오류: hyp_ppid_commonality 실행 실패 "
                                "(KeyError: 'legend'). 인자를 확인하고 다시 호출하라.",
                                ensure_ascii=False))]

    ai = llm.analyze_step(msgs)                      # 4) 그래도 죽지 않고 물러선다
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] == 0.2   # '후보 없음' 후퇴 분기
    assert ai.content
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_mock_llm.py -v`
Expected: FAIL — 신규 2건은 3단계에서 `finalize` 가 나와 `hyp_ppid_commonality` 단언이 깨지고, `test_scripted_sequence` 는 `KeyError: 'claim_id'` 로 죽는다.

- [ ] **Step 3: 구현**

`llm/client.py` 의 `analyze_step` 에서 1단 결과를 읽는 부분(현재 77-96행)을 아래로 바꾼다.

```python
        res = self._result(tool_msgs, "hyp_eqp_ch_commonality")
        passing = [c for c in res.get("candidates", []) if c["passes"]]
        if not passing:
            # EQP_CH 로 안 갈렸다. YAML 이 2차 legend 로 선언한 PPID 를 먼저 써 본다 -
            # 첫 no_signal 로 물러서면 등록된 가설 하나를 안 써보고 포기하는 셈이다.
            if "hyp_ppid_commonality" not in done:
                return self._call(
                    "hyp_ppid_commonality", {"group_ids": target, "control_ids": control},
                    "EQP_CH 로는 두 그룹이 안 갈렸다. 2차 legend(PPID)로 대조한다.")
            res = self._result(tool_msgs, "hyp_ppid_commonality")
            passing = [c for c in res.get("candidates", []) if c["passes"]]

        if not passing:
            # 등록 가설을 다 돌렸는데 분리되는 후보가 없다 - **원인 없음이 아니라 lot
            # 내부 대조로는 안 보인다**는 뜻. 억지로 후보를 집으면 허위 확정이므로
            # 지목 없이 물러선다(게이트가 no_signal 로 판정한다).
            return self._call(
                "finalize",
                {"claim_id": "",
                 "hypothesis": "lot 내부 대조로는 타깃만 거친 설비/챔버/PPID 가 없다 - "
                               "원인이 root_lot 전체에 걸렸을 수 있어 lot 밖 대조군이 필요하다",
                 "confidence": 0.2},
                "등록 가설을 다 돌렸으나 분리되는 후보가 없다. 확정할 근거가 없으므로 물러선다.")
        top = passing[0]
```

이어지는 두 `finalize` 호출에 `claim_id` 를 넣는다 (현재 106-116행).

```python
        if sensor.get("status") != "ok":
            return self._call(
                "finalize",
                {"claim_id": top["claim_id"],
                 "hypothesis": hyp + " - 다만 2단 센서 근거는 확보하지 못했다",
                 "confidence": 0.5},
                f"1단은 갈렸지만 2단이 근거를 못 냈다(status={sensor.get('status')}). "
                f"'왜' 없이 확정하지 않는다.")
        c = sensor["candidates"][0]
        hyp += f" - {c['sensor_name']} 효과크기 {c['effect_size']}"
        return self._call(
            "finalize",
            {"claim_id": top["claim_id"], "hypothesis": hyp, "confidence": 0.9},
            "챔버 편중에 센서 근거까지 붙었다. 근거 충분.")
```

첫 조기 finalize(현재 64-70행)에도 `"claim_id": ""` 를 넣는다.

```python
        if "finalize" not in done:
            return self._call(
                "finalize",
                {"claim_id": "",
                 "hypothesis": f"불량 그룹 {len(target)}장이 한 사건으로 묶였다 - "
                               f"공통 원인 존재 추정",
                 "confidence": 0.6},
                "그룹은 묶였지만 공정 근거가 아직 없다. 이 정도로 종료를 제안해 본다.")
```

기존 문자열의 em-dash 를 `-` 로 바꾼 것에 주의한다. 이 문구들은 감사 기록을 거쳐 cp949 콘솔에 출력된다.

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_mock_llm.py -v`
Expected: 전부 PASS

- [ ] **Step 5: 전체 회귀 — 옛 게이트 아래에서도 초록인지**

Run: `python -m pytest -q`
Expected: 173 passed (171 + 신규 2). E2E 와 적대적 케이스가 그대로 통과해야 한다. 깨진다면 mock 이 옛 게이트 계약을 어긴 것이므로 게이트가 아니라 mock 을 고친다.

- [ ] **Step 6: 커밋**

```bash
git add llm/client.py tests/test_mock_llm.py
git commit -m "$(cat <<'EOF'
feat(mock): claim_id 제출 + EQP_CH 침묵 시 PPID 폴백

각본이 finalize 에 claim_id 를 실어 보내고, 1단이 안 갈리면 2차 legend 를
돌린 뒤에야 물러선다. 게이트는 아직 claim_id 를 무시하므로 판정은 그대로다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 게이트 판정표 교체

**Files:**
- Modify: `graph/nodes.py:198-256` (`_finalize_gate`·`_collect_evidence`), `graph/nodes.py:36-43` (`ANALYZE_SYSTEM_PROMPT`)
- Modify: `graph/state.py:25-27` (`finalize_status` 주석, `final_claim` 추가)
- Modify: `tools/agent_tools.py:45-50` (`finalize` 시그니처)
- Modify: `llm/client.py:134-151` (`generate_report` 의 `no_signal` 분기), `llm/client.py:204-213` (운영 시스템 프롬프트)
- Test: `tests/test_graph_nodes.py` (게이트 테스트 전면), `tests/test_adversarial_dummy.py:94-114` (케이스 4)

**Interfaces:**
- Consumes: Task 2 의 `evidence.build_bundle`·`Bundle.passing`·`Bundle.top_score`, Task 3 의 mock claim_id 계약.
- Produces: `finalize_status` 에 `"no_signal"` 이 추가된다. 승인 시 `state["final_claim"]` 에 승인된 Claim 의 `dataclasses.asdict()` 결과(dict)가 담긴다 — Task 5 의 리포트가 읽는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다 (1) 게이트 단위**

`tests/test_graph_nodes.py` 를 고친다. 먼저 헬퍼와 픽스처.

```python
def _ai_finalize(confidence, hypothesis="Etch ETCH-9 원인", claim_id="eqp_ch_commonality:Etch:ETCH-9"):
    return AIMessage(
        content="종료 제안",
        tool_calls=[{"name": "finalize",
                     "args": {"claim_id": claim_id, "hypothesis": hypothesis,
                              "confidence": confidence},
                     "id": "call_f"}],
    )
```

`EVIDENCE_FINDING` 의 후보에 `claim_id`·`score`·총계를 넣는다.

```python
EVIDENCE_FINDING = {
    "loop": 2, "tool": "hyp_eqp_ch_commonality",
    "args": {"group_ids": ["W2406_02", "W2406_04", "W2406_06"],
             "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
    "result": {"hypothesis_id": "eqp_ch_commonality",
               "legend": [{"level": "chamber", "columns": ["eqp_id", "ch_id"]}],
               "status": "ok",
               "candidates": [
                   {"claim_id": "eqp_ch_commonality:Etch:ETCH-9",
                    "value": ["Etch", "ETCH-9"], "passes": True,
                    "level": "chamber", "key": "ETCH-9", "step_seq": "Etch", "score": 1.0,
                    "target_pass": 3, "target_total": 3,
                    "control_pass": 0, "control_total": 3, "reject_reason": None},
               ]},
    "thought": "그룹 대조",
}
```

`EVIDENCE_FINDING_NEW` 의 두 후보에도 같은 형식으로 `claim_id`·`step_seq`·`score`·총계를 넣는다. 통과 후보는 `"eqp_ch_commonality:CC002000:ETCH9_B"`(score 1.0), 미끼는 `"eqp_ch_commonality:CD004000:PHOTO1_A"`(score 0.0, `passes: False`)로 한다.

`test_collect_evidence_gathers_passing_tokens`(74-76행)를 삭제하고 — `_collect_evidence` 가 사라진다 — 대신 게이트 판정표 4줄을 덮는 테스트를 쓴다. `PPID_SILENT` 는 "등록 가설을 다 돌렸다" 를 만드는 재료다.

```python
# 등록 가설이 둘이므로, no_signal 종료를 시험하려면 PPID 도 돌아야 한다
PPID_SILENT = {
    "loop": 3, "tool": "hyp_ppid_commonality", "args": {},
    "result": {"hypothesis_id": "ppid_commonality", "status": "no_signal",
               "candidates": []},
    "thought": "2차 legend",
}
EQP_CH_SILENT = {
    "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
    "result": {"hypothesis_id": "eqp_ch_commonality", "status": "no_signal",
               "candidates": []},
    "thought": "1차 legend",
}


def test_gate_rejects_text_only_claim():
    """claim_id 없이 hypothesis 문자열만으로는 절대 승인되지 않는다.

    옛 게이트는 `any(eq in hypothesis for eq in suspects)` 였다 - 그래서
    "ETCH-9 는 원인이 아니다" 도 토큰이 들어 있다는 이유로 승인됐다.
    """
    ai = _ai_finalize(0.9, hypothesis="Etch ETCH-9 원인", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING]})
    assert "finalize_accepted" not in out
    assert "반려" in out["messages"][0].content
    assert "eqp_ch_commonality:Etch:ETCH-9" in out["messages"][0].content   # 지목할 대상을 알려준다


def test_gate_rejects_negation_when_claim_id_is_absent():
    """부정문이라도 게이트는 문장을 읽지 않는다 - 판정은 claim_id 조회로만 한다."""
    ai = _ai_finalize(0.9, hypothesis="ETCH-9 는 원인이 아니다", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING]})
    assert "finalize_accepted" not in out


def test_gate_rejects_unknown_claim_id():
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:Etch:CVD-3")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING]})
    assert "finalize_accepted" not in out
    assert "CVD-3" in out["messages"][0].content


def test_gate_rejects_claim_that_did_not_pass():
    """미통과 후보를 지목하면 도구가 낸 reject_reason 을 그대로 돌려준다."""
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:CD004000:PHOTO1_A")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING_NEW]})
    assert "finalize_accepted" not in out
    assert "분리 없음" in out["messages"][0].content


def test_gate_rejects_lower_scored_claim_and_names_the_stronger_one():
    """근접 미끼: 통과했더라도 더 강한 후보가 있으면 승인하지 않는다."""
    decoy = {
        "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"claim_id": "eqp_ch_commonality:CC002000:ETCH2_B", "step_seq": "CC002000",
             "key": "ETCH2_B", "level": "chamber", "passes": True, "reject_reason": None,
             "score": 1.0, "target_pass": 4, "target_total": 4,
             "control_pass": 0, "control_total": 5},
            {"claim_id": "eqp_ch_commonality:CD004000:PHOT2_X", "step_seq": "CD004000",
             "key": "PHOT2_X", "level": "chamber", "passes": True, "reject_reason": None,
             "score": 0.75, "target_pass": 4, "target_total": 4,
             "control_pass": 1, "control_total": 5},
        ]},
        "thought": "미끼 포함",
    }
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:CD004000:PHOT2_X")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": [decoy]})
    assert "finalize_accepted" not in out
    assert "eqp_ch_commonality:CC002000:ETCH2_B" in out["messages"][0].content


def test_gate_accepts_tied_top_score():
    """설비 롤업과 챔버가 동점이면 더 구체적인 쪽을 지목해도 승인한다.

    타깃 전원이 거친 설비를 대조군이 아무도 안 거치면 두 레벨이 같은 점수가 되고,
    정렬은 문자열순이라 덜 구체적인 설비 롤업이 앞선다. 동점을 막으면 챔버 지목이 반려된다.
    """
    tied = {
        "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"claim_id": "eqp_ch_commonality:CC002000:ETCH9", "step_seq": "CC002000",
             "key": "ETCH9", "level": "equipment", "passes": True, "reject_reason": None,
             "score": 1.0, "target_pass": 3, "target_total": 3,
             "control_pass": 0, "control_total": 6},
            {"claim_id": "eqp_ch_commonality:CC002000:ETCH9_B", "step_seq": "CC002000",
             "key": "ETCH9_B", "level": "chamber", "passes": True, "reject_reason": None,
             "score": 1.0, "target_pass": 3, "target_total": 3,
             "control_pass": 0, "control_total": 6},
        ]},
        "thought": "동점",
    }
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:CC002000:ETCH9_B")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": [tied]})
    assert out["finalize_status"] == "confirmed"


def test_gate_records_the_approved_claim():
    """승인 시 근거 수치가 상태에 남는다 - 리포트가 LLM 문장에 의존하지 않게."""
    out = nodes.tools_node({"messages": [_ai_finalize(0.9)], "loop_count": 4,
                            "findings": [EVIDENCE_FINDING]})
    assert out["finalize_status"] == "confirmed"
    assert out["final_claim"]["claim_id"] == "eqp_ch_commonality:Etch:ETCH-9"
    assert out["final_claim"]["score"] == 1.0
    assert (out["final_claim"]["target_pass"], out["final_claim"]["control_pass"]) == (3, 0)


def test_gate_asks_for_the_unrun_hypothesis_before_declaring_no_signal():
    """EQP_CH 하나가 조용하다고 신호가 없다고 선언하지 않는다."""
    ai = _ai_finalize(0.2, hypothesis="분리되는 후보가 없다", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": [EQP_CH_SILENT]})
    assert "finalize_accepted" not in out
    assert "hyp_ppid_commonality" in out["messages"][0].content


def test_gate_declares_no_signal_after_all_hypotheses_are_silent():
    """등록 가설을 다 돌렸는데 통과 후보가 없으면 no_signal 로 종료한다.

    확신도는 보지 않는다 - 물러섬 선언에 높은 확신도를 요구하면 모순이다.
    루프 한계보다 먼저 걸려야 한다(loop 2 에서 종료).
    """
    ai = _ai_finalize(0.2, hypothesis="lot 내부 대조로는 안 보인다", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": [EQP_CH_SILENT, PPID_SILENT]})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "no_signal"
    assert "신호 없음" in out["messages"][0].content


def test_gate_no_signal_beats_max_loops():
    """루프 한계에 닿아도 사유가 분명하면 no_signal 로 보고한다 (inconclusive 아님)."""
    ai = _ai_finalize(0.2, claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 6,
                            "findings": [EQP_CH_SILENT, PPID_SILENT]})
    assert out["finalize_status"] == "no_signal"
```

기존 게이트 테스트 중 아래 둘은 **삭제한다** — 판정 근거가 문자열 매칭이라는 전제 위에 있다.

- `test_finalize_gate_rejects_hypothesis_not_backed_by_evidence` (189-197행) → `test_gate_rejects_unknown_claim_id` 가 대체
- `test_collect_evidence_gathers_passing_tokens` (74-76행) → `tests/test_evidence.py` 가 대체

나머지 기존 테스트는 **의미가 그대로 유효하지만 인자를 손봐야 한다.** 반려 문구가 상황별로 갈리게 되었으므로, 각 테스트가 자기가 노리는 분기에 실제로 도달하는지 확인해야 한다. 아래 다섯은 반드시 고친다.

| 테스트 | 고칠 것 | 안 고치면 |
|---|---|---|
| `test_gate_accepts_chamber_hypothesis` | `claim_id="eqp_ch_commonality:CC002000:ETCH9_B"` 명시 | 기본 claim_id 가 `EVIDENCE_FINDING_NEW` 와 안 맞아 반려 |
| `test_finalize_gate_sees_evidence_from_same_message` | finalize args 에 `"claim_id": "eqp_ch_commonality:CC002000:ETCH9_B"` | 같은 이유로 반려 |
| `test_finalize_gate_rejects_low_confidence` | `findings=[EVIDENCE_FINDING]` 을 주고 단언을 `"확신도" in content` 로 강화 | findings 가 비면 "claim_id 가 없다" 로 반려돼 **확신도 분기를 전혀 안 탄다** (통과는 하지만 공허하다) |
| `test_finalize_gate_rejects_high_confidence_without_evidence` | `claim_id=""` 를 넘긴다 | "조사 없이 결론" 이 아니라 "지어낸 claim_id" 를 시험하게 되고, 단언 `"hyp_" in content` 가 깨진다 |
| `test_finalize_gate_handles_non_numeric_confidence` | `"claim_id": "eqp_ch_commonality:Etch:ETCH-9"` 와 `findings=[EVIDENCE_FINDING]` 을 준다 | 확신도 분기에 도달하지 못해 안내 문구(`숫자가 아니다`)가 안 나오고 단언이 깨진다 |

```python
def test_finalize_gate_rejects_low_confidence():
    out = nodes.tools_node({"messages": [_ai_finalize(0.6)], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING]})
    assert "finalize_accepted" not in out
    assert "확신도" in out["messages"][0].content     # 근거는 맞는데 확신도가 모자란 경우
    assert out["findings"][0]["tool"] == "finalize"   # 반려도 감사 기록에 남는다


def test_finalize_gate_rejects_high_confidence_without_evidence():
    # (a) 조사 없이 결론: confidence 0.9 라도 그룹 대조 근거가 없으면 반려
    out = nodes.tools_node({"messages": [_ai_finalize(0.9, claim_id="")],
                            "loop_count": 1, "findings": []})
    assert "finalize_accepted" not in out
    assert "hyp_" in out["messages"][0].content       # 무엇을 하라는지 안내


def test_finalize_gate_handles_non_numeric_confidence():
    ai = AIMessage(content="종료 제안", tool_calls=[
        {"name": "finalize", "args": {"claim_id": "eqp_ch_commonality:Etch:ETCH-9",
                                      "hypothesis": "Etch ETCH-9 원인",
                                      "confidence": "high"}, "id": "cf"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING]})
    assert "finalize_accepted" not in out
    assert "숫자" in out["messages"][0].content
```

`test_tools_node_skips_calls_after_finalize_accepted`(275-282행)도 finalize args 에 `"claim_id": "eqp_ch_commonality:CC002000:ETCH9_B"` 를 넣어야 승인이 유지된다. `test_rejected_finalize_does_not_stop_following_calls`(300-305행)는 확신도 0.3 에 근거도 없어 어느 경로로든 반려되므로 그대로 둔다.

`test_finalize_gate_accepts_high_confidence_with_evidence` 와 `test_finalize_gate_marks_inconclusive_at_max_loops` 는 수정 없이 통과한다 (전자는 기본 claim_id 가 `EVIDENCE_FINDING` 과 맞고, 후자는 `no_signal` status 가 없어 루프 한계 분기로 간다).

- [ ] **Step 2: 실패하는 테스트를 쓴다 (2) 적대적 케이스 4**

`tests/test_adversarial_dummy.py:94-114` 의 E2E 를 바꾼다.

```python
def test_case4_end_to_end_reports_no_signal_not_loop_exhaustion():
    """no_signal 케이스가 그래프 전체를 지나도 **확정 결론이 되면 안 된다**.

    그리고 사유가 정확해야 한다 - "루프를 다 썼다"(inconclusive)와 "lot 내부
    대조로는 신호가 없다"(no_signal)는 사람이 할 조치가 다르다. 전자는 재시도,
    후자는 대조군을 lot 밖으로 넓히는 일이다.
    """
    from graph.build import build_graph

    targets, _ = adv_group(ADV_NOSIGNAL_LOT)
    state = build_graph().invoke({"target_wafers": [targets[0]], "target_source": "manual"})

    assert state["report"]
    assert state["finalize_status"] == "no_signal"
    assert "신호 없음" in state["report"]
    assert "lot 밖 대조군" in state["report"]
    # 도구가 1회차에 아는 사실이므로 루프를 다 태우지 않는다
    assert state["loop_count"] < 6
    # 게이트가 이 가설을 승인한 적이 없어야 한다
    gate = [f["result"] for f in state["findings"] if f["tool"] == "finalize"]
    assert not any("승인" in r for r in gate)
    # 등록 가설을 둘 다 돌린 뒤에 판정했다
    tools_used = [f["tool"] for f in state["findings"]]
    assert "hyp_eqp_ch_commonality" in tools_used and "hyp_ppid_commonality" in tools_used
```

- [ ] **Step 3: 실패를 확인한다**

Run: `python -m pytest tests/test_graph_nodes.py tests/test_adversarial_dummy.py -v`
Expected: FAIL — 신규 게이트 테스트는 `KeyError: 'final_claim'` 또는 승인/반려 판정 불일치로, 케이스 4 는 `assert 'inconclusive' == 'no_signal'` 로 죽는다.

- [ ] **Step 4: 구현 (1) finalize 시그니처**

`tools/agent_tools.py` 의 `finalize` 를 바꾼다.

```python
@tool
def finalize(claim_id: str = "", hypothesis: str = "", confidence: float = 0.0) -> str:
    """원인을 특정 후보까지 좁혔고 근거가 충분하다고 판단될 때만 호출해 분석 종료를 제안한다.

    claim_id: 가설 도구(hyp_*) 결과의 후보에 실려 온 claim_id 를 **그대로** 옮긴다.
      이것이 승인 판정의 유일한 근거다. 지어내면 반려된다. 지목할 근거가 없어
      물러설 때는 빈 문자열로 둔다.
    hypothesis: 현장 엔지니어가 읽을 원인 서술. 판정에는 쓰이지 않는다.
    confidence: 0~1 확신도. 확신도만 높고 claim_id 가 없으면 반려된다."""
    return "finalize 는 게이트가 처리한다"  # 직접 실행되지 않음
```

`claim_id` 를 필수 인자로 만들지 않는 이유는, LLM 이 빠뜨렸을 때 스키마 오류로 죽어 게이트가 안내 문구를 돌려줄 기회를 잃기 때문이다.

- [ ] **Step 5: 구현 (2) 게이트**

`graph/nodes.py` 상단 import 에 한 줄을 더한다.

```python
from dataclasses import asdict

from graph import evidence
```

`_finalize_gate` 와 `_collect_evidence`(198-256행)를 통째로 아래로 바꾼다.

```python
def _finalize_gate(args: dict, loop: int, update: dict, findings: list[dict]) -> str:
    """LLM 의 종료 제안을 코드가 최종 판정한다 (부품 4b).

    승인 실권은 confidence 자기 신고도, LLM 이 쓴 문장도 아니라 **EvidenceBundle
    조회 결과**에 있다. LLM 은 도구가 발급한 claim_id 를 지목하고, 게이트는 그
    claim 이 판별선을 넘었는지와 같은 도구 안에서 최고 점수인지를 확인한다.

    판정은 위에서부터 처음 걸리는 줄로 결정된다:
      (1) 지목한 claim 이 통과 + 최고 점수 + 확신도 충족 -> confirmed
      (2) 등록 가설을 다 돌렸는데 통과 후보 0 + no_signal 있음 -> no_signal
      (3) 루프 한계 -> inconclusive (승인이 아니라 '미확정')
      (4) 그 외 -> 반려. 무엇이 모자란지 그대로 돌려준다.
    """
    bundle = evidence.build_bundle(findings)
    conf, conf_note = _confidence(args.get("confidence", 0.0))
    hypothesis = args.get("hypothesis", "")
    claim_id = (args.get("claim_id") or "").strip()
    claim = bundle.claims.get(claim_id)
    registered = {n for n in TOOLS_BY_NAME if n.startswith("hyp_")}
    unrun = sorted(registered - bundle.ran)

    # (1) 승인
    if (claim is not None and claim.passes
            and claim.score >= bundle.top_score(claim.tool)
            and conf >= config.CONFIDENCE_THRESHOLD):
        update["finalize_accepted"] = True
        update["finalize_status"] = "confirmed"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        update["final_claim"] = asdict(claim)
        return (f"승인 (근거 확인): {claim.claim_id} · 분리 점수 {claim.score} · "
                f"타깃 {claim.target_pass}/{claim.target_total} 통과 · "
                f"대조군 {claim.control_pass}/{claim.control_total} 통과. "
                f"리포팅으로 진행한다.")

    # (2) 신호 없음 - 등록 가설을 다 돌렸는데 통과 후보가 하나도 없다.
    #     확신도를 보지 않는다: 물러섬 선언에 높은 확신도를 요구하면 모순이다.
    #     루프 한계(3)보다 **먼저** 판정해야 사유가 정확해진다.
    if not bundle.passing() and not unrun and "no_signal" in bundle.statuses.values():
        update["finalize_accepted"] = True
        update["finalize_status"] = "no_signal"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        return ("신호 없음 (등록 가설 전부 대조 완료, 분리되는 후보 없음): "
                "lot 내부 대조로는 원인을 좁힐 수 없다. 리포팅으로 진행한다.")

    # (3) 루프 한계 도달 강제 종료는 승인이 아니라 '미확정'
    if loop >= config.MAX_LOOPS:
        update["finalize_accepted"] = True
        update["finalize_status"] = "inconclusive"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        return "미확정 (루프 한계 도달): 확정 근거 없이 리포팅으로 진행한다."

    # (4) 반려
    return _gate_rejection(claim_id, claim, bundle, unrun, conf, conf_note)


def _confidence(raw) -> tuple[float, str]:
    try:
        return float(raw), ""
    except (TypeError, ValueError):
        return 0.0, (f" (confidence 로 받은 '{raw}' 은 숫자가 아니다 - "
                     f"0~1 사이 숫자로 다시 제출하라)")


def _gate_rejection(claim_id, claim, bundle, unrun, conf, conf_note) -> str:
    """왜 승인하지 않았는지를 LLM 이 다음 행동으로 옮길 수 있게 돌려준다."""
    if claim_id and claim is None:
        valid = sorted(bundle.claims)
        avail = ("유효한 claim_id: " + ", ".join(valid)) if valid else "아직 유효한 claim 이 없다"
        return f"반려: claim_id '{claim_id}' 는 도구 결과에 없다. {avail}."

    if claim is not None:
        if not claim.passes:
            return (f"반려: {claim.claim_id} 는 판별선을 넘지 못했다 ({claim.reject_reason}). "
                    f"통과한 후보를 지목하라.")
        top = bundle.top_score(claim.tool)
        if claim.score < top:
            best = max((c for c in bundle.passing() if c.tool == claim.tool),
                       key=lambda c: c.score)
            return (f"반려: {claim.claim_id}(점수 {claim.score}) 보다 강한 후보가 있다: "
                    f"{best.claim_id}(점수 {best.score}). 근거가 가장 강한 후보를 지목하라.")
        return (f"반려: 확신도 {conf:.2f} < {config.CONFIDENCE_THRESHOLD}.{conf_note} "
                f"근거를 좁힐 tool 을 더 호출하라.")

    # claim_id 미제출
    valid = sorted(c.claim_id for c in bundle.passing())
    if valid:
        return (f"반려: claim_id 를 제출하지 않았다. 결론은 도구가 발급한 claim_id 로 "
                f"지목해야 한다. 통과 후보: {', '.join(valid)}.")
    if unrun:
        return (f"반려: 통과한 후보가 없다. 아직 실행하지 않은 가설 도구가 있다: "
                f"{', '.join(unrun)}. 먼저 호출하라.")
    if bundle.ran:
        return ("반려: 등록 가설을 다 돌렸으나 판별선을 넘은 후보가 없다. "
                "2단 센서로 근거를 더 좁히거나 대조군을 다시 보라.")
    return "반려: 그룹 대조 근거가 없다. 가설 도구(hyp_*)로 두 그룹을 먼저 대조하라."
```

- [ ] **Step 6: 구현 (3) 프롬프트와 상태**

`graph/nodes.py` 의 `ANALYZE_SYSTEM_PROMPT` 규칙 목록에서 finalize 줄을 바꾼다.

```
- 원인을 좁혔고 근거가 충분하면 finalize(claim_id, hypothesis, confidence) 로 종료를 제안하라. claim_id 는 가설 도구 결과의 후보에 실려 온 값을 **그대로** 옮겨야 한다 - 지어내거나 문장으로 대신하면 반려된다. 지목할 근거가 없어 물러설 때는 claim_id 를 비우고 낮은 확신도로 제출하라.
```

`graph/state.py` 에 상태 키를 추가하고 주석을 갱신한다.

```python
    finalize_status: str    # confirmed | no_signal | inconclusive | no_anomaly | unknown_target | isolated | control_insufficient | eds_lookup_failed
    final_hypothesis: str                           # 승인된 원인 가설 (LLM 서술)
    final_confidence: float                         # 승인 시 확신도
    final_claim: dict                               # 승인된 claim (게이트가 확인한 근거 수치)
```

- [ ] **Step 7: 구현 (4) no_signal 리포트 문구**

`llm/client.py` `ScriptedMockLLMClient.generate_report` 의 분기 사슬에서 `inconclusive` 바로 뒤에 넣는다.

```python
        elif finalize_status == "no_signal":
            conclusion = ("신호 없음 - lot 내부 대조로는 타깃만 거친 설비/챔버/PPID 가 없다. "
                          "원인 없음이 아니라 원인이 root_lot 전체에 걸렸을 수 있다는 뜻이며, "
                          "lot 밖 대조군이 필요하다.")
```

`OpenAILLMClient.generate_report` 의 시스템 프롬프트에도 같은 규칙을 넣는다. mock 만 고치면 정직성 보장이 데모에만 걸린다.

```python
            "판정이 no_signal 이면 '신호 없음'으로 서술하라 - 원인 없음이 아니라 "
            "lot 내부 대조로는 보이지 않는다는 뜻이며 lot 밖 대조군이 필요하다는 "
            "후속 조치를 명시하고, 확정 결론을 쓰지 마라. "
```

- [ ] **Step 8: 통과를 확인한다**

Run: `python -m pytest tests/test_graph_nodes.py tests/test_adversarial_dummy.py tests/test_mock_llm.py -v`
Expected: 전부 PASS

- [ ] **Step 9: 전체 회귀**

Run: `python -m pytest -q`
Expected: 181 passed (173 + 신규 10 − 삭제 2). **`test_sensor_failure_is_not_reported_as_confirmed` 가 여전히 통과하는지 눈으로 확인한다** — 2단이 죽으면 mock 이 0.5 로 물러서고, 새 게이트에서도 확신도 조건에 걸려 반려된 뒤 루프 한계에서 `inconclusive` 로 끝나야 한다.

- [ ] **Step 10: 데모를 사람 눈으로 확인한다**

Run: `python main.py W2406_02`
Expected: `[결론]` 이 `confirmed` 계열이고 `ETCH9_B` 를 지목한다. 게이트를 조였는데 데모가 반려로 바뀌면 규칙이 과하게 조인 것이므로 멈추고 보고한다.

Run: `python main.py W2417_01`
Expected: 결론이 "신호 없음" 이고 "lot 밖 대조군" 이 보인다. (`W2417_01` 은 케이스 4 lot 의 첫 wafer 로 2026-08-01 에 확인한 값이다.)

- [ ] **Step 11: 커밋**

```bash
git add graph/nodes.py graph/state.py tools/agent_tools.py llm/client.py tests/test_graph_nodes.py tests/test_adversarial_dummy.py
git commit -m "$(cat <<'EOF'
feat(gate): 승인을 substring 매칭에서 claim_id 조회로 교체 + no_signal 판정

게이트가 EvidenceBundle 만 조회해 4줄 판정표로 결정한다.
- 승인은 claim_id 가 통과 후보이고 그 도구 안에서 최고 점수일 때만.
  확신도는 필요조건일 뿐 근거가 아니다.
- 등록 가설을 다 돌렸는데 통과 후보가 없으면 no_signal 로 종료한다.
  루프 한계보다 먼저 판정하므로 사유가 "루프를 다 썼다" 로 뭉개지지 않는다.
- 근접 미끼는 최고 점수 규칙이 거른다(동점 허용).

_collect_evidence 삭제. 문자열 매칭 전제 위에 있던 테스트 2건을 대체했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 리포트에 코드가 만드는 `[근거]` 줄

**Files:**
- Modify: `llm/client.py:26-42` (`LLMClient.generate_report` 시그니처), `llm/client.py:119-154` (mock), `llm/client.py:202-222` (openai)
- Modify: `graph/nodes.py:260-271` (`report_node`)
- Test: `tests/test_mock_llm.py` (파일 끝), `tests/test_graph_nodes.py` (파일 끝)

**Interfaces:**
- Consumes: Task 4 의 `state["final_claim"]` (dict).
- Produces: `generate_report(..., claim: dict | None = None)`. 기본값 `None` 이므로 기존 호출부와 테스트가 그대로 동작한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_mock_llm.py` 파일 끝에 추가한다.

```python
def test_report_carries_gate_verified_numbers_not_llm_prose():
    """근거 수치는 LLM 문장이 아니라 게이트가 확인한 claim 에서 나온다.

    운영 LLM 이 수치를 흐리거나 빠뜨려도 감사 기록에 남아야 한다.
    """
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        target_wafers=["W2406_02"], target_source="manual", target_group=TARGET,
        status_summary="s", findings=[], hypothesis="원인은 그 챔버다", confidence=0.9,
        finalize_status="confirmed",
        claim={"claim_id": "eqp_ch_commonality:CC002000:ETCH9_B", "score": 1.0,
               "target_pass": 3, "target_total": 3,
               "control_pass": 0, "control_total": 6},
    )
    assert "[근거]" in report
    assert "eqp_ch_commonality:CC002000:ETCH9_B" in report
    assert "3/3" in report and "0/6" in report


def test_report_without_claim_has_no_evidence_line():
    """확정되지 않은 분석에 근거 줄을 만들어 붙이지 않는다."""
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis=None, confidence=None)
    assert "[근거]" not in report
```

`tests/test_graph_nodes.py` 파일 끝에 배선 테스트를 추가한다.

```python
def test_report_node_passes_the_approved_claim_to_the_report():
    out = nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "manual",
        "target_group": ["W2406_02"], "status_summary": "요약", "findings": [],
        "final_hypothesis": "ETCH9_B 편중", "final_confidence": 0.9,
        "finalize_status": "confirmed",
        "final_claim": {"claim_id": "eqp_ch_commonality:CC002000:ETCH9_B", "score": 1.0,
                        "target_pass": 3, "target_total": 3,
                        "control_pass": 0, "control_total": 6},
    })
    assert "eqp_ch_commonality:CC002000:ETCH9_B" in out["report"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_mock_llm.py tests/test_graph_nodes.py -k "claim or 근거 or evidence_line" -v`
Expected: FAIL — `TypeError: generate_report() got an unexpected keyword argument 'claim'`

- [ ] **Step 3: 구현**

`LLMClient.generate_report` 추상 메서드 시그니처 끝에 `claim: dict | None = None,` 을 더하고, docstring 에 한 줄을 더한다.

```python
        claim 이 있으면 게이트가 확인한 근거 수치다 - 그대로 인용하고 바꾸지 않는다.
```

`ScriptedMockLLMClient.generate_report` 의 시그니처에 `claim=None` 을 더하고, 마지막 `lines +=` 를 바꾼다.

```python
        conf = f" (확신도 {confidence})" if confidence is not None else ""
        lines += ["", f"[결론] {conclusion}{conf}"]
        if claim:
            # 게이트가 확인한 수치. LLM 문장과 나란히 놓아 대조할 수 있게 한다.
            lines.append(
                f"[근거] {claim['claim_id']} · 분리 점수 {claim['score']} · "
                f"타깃 {claim['target_pass']}/{claim['target_total']} 통과 · "
                f"대조군 {claim['control_pass']}/{claim['control_total']} 통과")
        return "\n".join(lines)
```

`OpenAILLMClient.generate_report` 의 시그니처에도 `claim=None` 을 더하고, user 메시지 끝에 붙인다.

```python
        if claim:
            user += (f"\n게이트가 확인한 근거(수치를 그대로 인용하라): "
                     f"{json.dumps(claim, ensure_ascii=False)}")
```

`graph/nodes.py` `report_node` 의 호출에 한 줄을 더한다.

```python
        finalize_status=state.get("finalize_status"),
        claim=state.get("final_claim"),
    )
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_mock_llm.py tests/test_graph_nodes.py -v`
Expected: 전부 PASS

- [ ] **Step 5: 전체 회귀 + 눈 확인**

Run: `python -m pytest -q`
Expected: 184 passed (181 + 신규 3)

Run: `python main.py W2406_02`
Expected: 리포트 마지막에 `[근거] eqp_ch_commonality:CC002000:ETCH9_B · 분리 점수 1.0 · 타깃 3/3 통과 · 대조군 0/6 통과` 가 보인다.

- [ ] **Step 6: 커밋**

```bash
git add llm/client.py graph/nodes.py tests/test_mock_llm.py tests/test_graph_nodes.py
git commit -m "$(cat <<'EOF'
feat(report): 게이트가 확인한 근거 수치를 코드가 리포트에 쓴다

지금까지 근거 수치는 LLM 문장 안에만 있었다. 운영 LLM 이 흐리면 감사
기록에서 사라진다. 승인된 claim 을 report_node 가 그대로 넘겨 코드가 쓴다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 적대적 케이스 1·2·3 의 최종 판정 고정

**Files:**
- Modify: `tests/test_adversarial_dummy.py:48-61` (`test_case2_gate_alone_does_not_reject_the_decoy`)
- Test: `tests/test_adversarial_dummy.py` (파일 끝에 E2E 2건)

**Interfaces:**
- Consumes: Task 4 의 게이트, Task 1 의 claim_id.
- Produces: 없음 (검증 전용)

케이스 4 는 Task 4 에서 이미 고정했다. 여기서는 나머지 세 케이스가 **게이트를 조인 뒤에도 의도한 판정을 내는지**를 못박는다. 스펙 8절의 성공 기준 표가 이 Task 의 명세다.

- [ ] **Step 1: 케이스 2 의 뒤집힌 계약을 쓴다**

`test_case2_gate_alone_does_not_reject_the_decoy` 를 아래로 바꾼다. **engine 단언은 그대로 두고** 게이트 단언을 더한다 — 판별선과 순위는 여전히 다른 층의 일이고, 이제 게이트가 순위를 본다는 것이 달라진 점이다.

```python
def test_case2_decoy_passes_the_discriminator_but_the_gate_rejects_it():
    """미끼도 passes=True 다 - 거르는 것은 판별선이 아니라 **게이트의 최고 점수 규칙**이다.

    engine 의 판별선은 (score >= COMMONALITY_PASS_MIN_SCORE, target_pass >= MIN_TARGET)
    뿐이라 0.75 짜리 미끼도 통과한다. 예전에는 LLM 이 미끼를 골라 결론에 쓰면 게이트가
    승인했다. 지금은 같은 도구 안에서 최고 점수가 아니면 반려한다.
    """
    from graph import nodes

    spec = next(s for s in registry.load_hypotheses() if s["id"] == "eqp_ch_commonality")
    t, c = adv_group(ADV_DECOY_LOT)
    res = engine.evaluate(spec, t, c)
    cands = {x["key"]: x for x in res["candidates"]}
    assert cands["ETCH2_B"]["passes"]
    assert cands["PHOT2_X"]["passes"], "판별선은 여전히 미끼를 통과시킨다"

    finding = {"loop": 1, "tool": "hyp_eqp_ch_commonality", "args": {},
               "result": res, "thought": "대조"}
    ai = AIMessage(content="종료 제안", tool_calls=[{"name": "finalize", "args": {
        "claim_id": cands["PHOT2_X"]["claim_id"],
        "hypothesis": "미끼가 원인", "confidence": 0.9}, "id": "call_f"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": [finding]})
    assert "finalize_accepted" not in out
    assert cands["ETCH2_B"]["claim_id"] in out["messages"][0].content

    # 진짜 원인을 지목하면 승인된다 - 게이트가 과하게 조여진 것이 아님을 함께 고정한다
    ai_ok = AIMessage(content="종료 제안", tool_calls=[{"name": "finalize", "args": {
        "claim_id": cands["ETCH2_B"]["claim_id"],
        "hypothesis": "ETCH2_B 편중이 원인", "confidence": 0.9}, "id": "call_f"}])
    ok = nodes.tools_node({"messages": [ai_ok], "loop_count": 3, "findings": [finding]})
    assert ok["finalize_status"] == "confirmed"
```

파일 상단 import 에 `AIMessage` 를 더한다.

```python
from langchain_core.messages import AIMessage
```

- [ ] **Step 2: 케이스 1·3 의 E2E 를 쓴다**

`tests/test_adversarial_dummy.py` 파일 끝에 추가한다.

**대상은 그룹 전체(`targets`)를 넣는다. wafer 한 장만 넣으면 안 된다.** 케이스 1·3 의 lot 은 EDS 형제가 없어 한 장으로는 `isolated` 조기 출구로 빠진다(2026-08-01 실측). 케이스 4 는 형제가 있어 한 장으로도 돌지만, 그쪽은 기존 테스트가 이미 그 형태다.

```python
def test_case1_counterexample_still_reaches_confirmed_end_to_end():
    """반례가 있어도 판별선을 넘으면 확정한다 - 게이트를 조였다고 과민해지면 안 된다.

    score 0.8 은 '원인 챔버를 거쳤는데 정상인 대조군 wafer 가 1장 있다' 는 뜻이다.
    현실 데이터에서 흔한 모양이므로 여기서 물러서면 아무것도 확정하지 못한다.
    """
    from graph.build import build_graph

    targets, _ = adv_group(ADV_COUNTEREX_LOT)
    state = build_graph().invoke({"target_wafers": targets, "target_source": "manual"})
    assert state["finalize_status"] == "confirmed"
    assert state["final_claim"]["key"] == "ETCH1_B"
    assert state["final_claim"]["control_pass"] == 1        # 반례가 근거에 그대로 남는다


def test_case3_missing_history_still_reaches_confirmed_end_to_end():
    """이력 결측 wafer 가 섞여도 판정이 흔들리지 않는다."""
    from graph.build import build_graph

    targets, _ = adv_group(ADV_MISSING_LOT)
    state = build_graph().invoke({"target_wafers": targets, "target_source": "manual"})
    assert state["finalize_status"] == "confirmed"
    assert state["final_claim"]["key"] == "ETCH3_B"
```

- [ ] **Step 3: 실패를 확인한다**

Run: `python -m pytest tests/test_adversarial_dummy.py -v`
Expected: 케이스 2 는 미끼 지목이 승인돼 FAIL(게이트 구현 전이면), 케이스 1·3 은 `final_claim` 키가 없어 `KeyError`.

**케이스 1·3 이 `confirmed` 에 닿는 것은 2026-08-01 에 실측으로 확인했다** (그룹 전체 입력, 1단 `ok` + 2단 센서 `ok` + 확신도 0.9). 그래도 FAIL 이 나면 기대값을 낮추기 전에 어디서 갈라졌는지부터 본다.

```bash
python -c "
from data.generate_dummy import ADV_COUNTEREX_LOT, adv_group
from graph.build import build_graph
t, _ = adv_group(ADV_COUNTEREX_LOT)
s = build_graph().invoke({'target_wafers': t, 'target_source': 'manual'})
print(s.get('finalize_status'), s.get('final_confidence'))
for f in s['findings']:
    print(' ', f['loop'], f['tool'], str(f['result'])[:160])
"
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_adversarial_dummy.py -v`
Expected: 전부 PASS

- [ ] **Step 5: 전체 회귀**

Run: `python -m pytest -q`
Expected: 186 passed (184 + 신규 2, 케이스 2 는 개명이라 수가 늘지 않는다)

- [ ] **Step 6: 커밋**

```bash
git add tests/test_adversarial_dummy.py
git commit -m "$(cat <<'EOF'
test(adversarial): 적대적 케이스 4종의 게이트 판정을 고정

케이스 2 는 계약이 뒤집혔다 - 판별선은 여전히 미끼를 통과시키지만
이제 게이트가 최고 점수 규칙으로 거른다. 진짜 원인 지목은 승인되는 것을
같이 고정해 과잉 조임이 아님을 보인다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 변이 테스트 (구현 없음, 검증만)

**Files:**
- 임시 수정 후 **전부 되돌린다.** 이 Task 는 커밋을 만들지 않는 것이 정상이다.

**Interfaces:**
- Consumes: Task 4·6 의 테스트.
- Produces: 없음. 테스트 구멍이 발견되면 그 테스트를 고치고 그때만 커밋한다.

구현을 일부러 틀리게 바꿔 **해당 테스트가 단독으로 죽는지** 확인한다. 통과하는 잘못된 구현이 5분 안에 나오면 테스트가 공허한 것이다. **변이가 통과하면 테스트를 의심하기 전에 변이가 진짜 그 버그인지 먼저 확인한다** — 과거에 `MIN(h.ppid)` 변이가 SQLite 의 bare column 동작 때문에 원래 버그를 재현하지 못해 "테스트 구멍" 처럼 보인 적이 있다.

각 변이마다: 고친다 → `python -m pytest -q` → 죽은 테스트 이름을 확인한다 → `git checkout -- <file>` 로 되돌린다.

- [ ] **변이 1: 최고 점수 비교 제거**

`graph/nodes.py` (1)번 조건에서 `and claim.score >= bundle.top_score(claim.tool)` 를 지운다.
Expected: `test_gate_rejects_lower_scored_claim_and_names_the_stronger_one` 과
`test_case2_decoy_passes_the_discriminator_but_the_gate_rejects_it` 가 죽는다. 다른 테스트는 살아 있어야 한다.

- [ ] **변이 2: passes 검사 제거**

(1)번 조건에서 `and claim.passes` 를 지운다.
Expected: `test_gate_rejects_claim_that_did_not_pass` 가 죽는다.

- [ ] **변이 3: "전부 실행" 조건 제거**

(2)번 조건에서 `and not unrun` 을 지운다.
Expected: `test_gate_asks_for_the_unrun_hypothesis_before_declaring_no_signal` 이 죽는다.

- [ ] **변이 4: no_signal 판정을 루프 한계 뒤로 이동**

(2)번 블록을 (3)번 블록 아래로 옮긴다.
Expected: `test_gate_no_signal_beats_max_loops` 가 죽는다. `test_case4_end_to_end_reports_no_signal_not_loop_exhaustion` 도 죽는지 확인한다 — 안 죽으면 E2E 가 루프 한계에 닿기 전에 끝난다는 뜻이므로, 그 사실을 메모하고 넘어간다(E2E 가 이 성질의 감시자가 아니라는 뜻).

- [ ] **변이 5: claim_id 조회를 substring 매칭으로 되돌림**

(1)번 조건의 `claim is not None and claim.passes and ...` 를
`any(c.key in hypothesis for c in bundle.passing())` 로 바꾼다.
Expected: `test_gate_rejects_text_only_claim` 과 `test_gate_rejects_negation_when_claim_id_is_absent` 가 죽는다.

- [ ] **되돌림을 확인한다**

Run: `git status --short`
Expected: 출력 없음 (working tree clean)

Run: `python -m pytest -q`
Expected: Task 6 의 통과 수와 같다

---

### Task 8: 문서 갱신

**Files:**
- Modify: `README.md:133-141` (`finalize_status` 표)
- Modify: `docs/stages.md:210-211` (Phase 축 소관 목록)
- Modify: `graph/build.py:1-12` (모듈 docstring)
- Modify: `docs/superpowers/specs/2026-08-01-evidence-bundle-gate-design.md` (구현 후 정정이 있으면)

**Interfaces:**
- Consumes: Task 1~7 의 결과.
- Produces: 없음.

- [ ] **Step 1: README 의 상태 어휘**

`README.md:141` 의 한 줄을 바꾼다.

```markdown
루프를 돈 뒤의 종료 사유는 셋입니다.

| `finalize_status` | 언제 | 사람이 할 일 |
|---|---|---|
| `confirmed` | 게이트가 claim_id 를 조회해 근거를 확인했다 (통과 후보 + 그 도구 안 최고 점수 + 확신도 충족) | 리포트의 `[근거]` 줄을 보고 현장 확인 |
| `no_signal` | 등록 가설을 전부 대조했으나 타깃만 거친 후보가 없다 | 원인 없음이 아니라 lot 내부 대조의 한계 — 대조군을 lot 밖으로 넓혀야 합니다 |
| `inconclusive` | 루프 한계까지 근거를 좁히지 못했다 | 분석 기록을 보고 사람이 이어받습니다 |
```

- [ ] **Step 2: stages.md 의 Phase 축 목록**

`docs/stages.md:210-211` 에서 완료된 항목을 표시한다.

```markdown
Phase 축 소관(여기서 안 다룸): ~~EvidenceBundle 게이트 강화~~ (2026-08-01 완료 —
`docs/superpowers/specs/2026-08-01-evidence-bundle-gate-design.md`), 시간축(장비 이벤트·PM·recipe 이력),
사람 검토 폐루프, 다인성(독립 원인 2개가 타깃을 절반씩 설명).
```

`docs/stages.md:207-208` 의 "Stage A Task 4 의 적대적 케이스가 Phase 축으로 넘어가는 첫 다리입니다" 는 그대로 둔다 — 여전히 맞는 서술이고, 이번 작업이 실제로 그 다리를 건넌 첫 사례다.

- [ ] **Step 3: build.py docstring**

`graph/build.py:11` 의 한 줄을 바꾼다. 라우팅 코드는 건드리지 않는다.

```python
종료는 tools 노드의 finalize 게이트(claim_id 조회 + 근거 판정)와 _after_tools 의 MAX_LOOPS 가드레일이 통제한다.
```

- [ ] **Step 4: 스펙 정정 블록 (구현 중 달라진 것이 있을 때만)**

구현하면서 스펙과 달라진 결정이 있으면 스펙 문서 상단에 정정 블록을 넣는다. 이 저장소의 관례다 (`docs/superpowers/plans/2026-07-29-post-stage4-small-fixes.md` 의 "실행 후 정정" 블록이 본보기). 달라진 것이 없으면 이 단계는 건너뛴다.

- [ ] **Step 5: 전체 회귀와 커밋**

Run: `python -m pytest -q`
Expected: Task 7 과 같은 수

```bash
git add README.md docs/stages.md graph/build.py docs/superpowers/specs/2026-08-01-evidence-bundle-gate-design.md
git commit -m "$(cat <<'EOF'
docs: no_signal 상태 어휘와 게이트 판정 근거 반영

README 의 종료 사유 표에 no_signal 을 추가하고 confirmed 의 근거를
"확신도" 에서 "claim_id 조회" 로 정정했다. stages.md 의 Phase 축 목록에서
게이트 강화를 완료 표시했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: 최종 확인**

Run: `git log --oneline main..HEAD`
Expected: 스펙 커밋 1개 + Task 1~6·8 커밋 7개 = 8개 안팎

Run: `git status --short`
Expected: 출력 없음

**main 병합은 하지 않는다.** 사용자에게 결과를 보고하고 결정을 받는다.

---

## 완료 기준

1. `python -m pytest -q` 가 착수 기준선 163 이상으로 초록.
2. 스펙 8절 성공 기준 표의 5행이 전부 테스트로 고정됨.
3. 변이 5종이 각각 의도한 테스트만 죽임 (Task 7).
4. `python main.py W2406_02` 가 `confirmed` + `[근거]` 줄, 케이스 4 wafer 가 "신호 없음".
5. 워킹 트리 clean, main 미병합.
