# 더미 우선 Stage 재배열 + 안전장치 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

작성일: 2026-07-25
선행: `docs/superpowers/specs/2026-07-24-registry-commonality-realignment-design.md` §12 (Stage 표)

**Goal:** Stage 1(실데이터)을 뒤로 미루고 Stage 2→5 를 더미 위에서 구현하는 순서 변경을 확정하고, 그 순서가 만드는 두 위험(스키마 계약 어긋남·정답지 없음)을 막는 안전장치를 먼저 심는다.

**Architecture:** 그래프 골격·commonality 엔진·레지스트리는 손대지 않는다. 이 계획은 (1) 세 곳에 흩어진 스키마 정의가 어긋나면 더미 단계에서 빨간불이 켜지게 하고, (2) 더미 데이터를 "정답을 심어둔 데모"에서 "적대적 평가셋"으로 승격시키고, (3) 실데이터에서 못 도는 레거시 도구를 LLM 노출에서 플래그로 격리한다. 전부 기존 테스트 green 유지 전제의 부가 작업이다.

**Tech Stack:** Python 3.11, sqlite3, pytest, PyYAML, LangChain `@tool`.

---

## 0. 배경 — 왜 순서를 바꾸는가

원래 Stage 표는 `Stage 1(실데이터 적재·commonality 1회 검증)` 을 2~5 앞에 둔다. 그런데 착수 직전 확인에서 두 가지가 드러났다.

1. **Stage 1 은 Stage 2 없이 완주할 수 없다.** commonality 는 `(target, control)` 을 받는데, 대조군을 만드는 `find_normal_wafers` 가 `defect_type = 'none'` 에 의존한다. 사내 `defect_type` 은 nullable 이라 실데이터에서 대조군이 비고, `no_paired_stratum` 으로 끝난다. 대조군 재작성이 곧 Stage 2 다.
2. **Stage 1 에 합격 기준이 없다.** "실데이터로 commonality 1회 검증" 에서 무엇을 보면 통과인지가 정의되지 않았다. 실데이터에는 정답지가 없어서, 후보가 나와도 맞는지 알 방법이 없다. 현재 정의로는 스모크 테스트다.

또한 `_extract()` 는 사내에서 작성 중이라 이 저장소의 작업 범위 밖이다.

### 결정

**Stage 1 을 Stage 5.5 로 미루고, Stage 2→3→4→5 를 더미 위에서 구현한다.**

근거: Stage 2~5 의 내용은 대부분 배선·계약·구조 문제이고, 수치 임계는 이미 `config` 상수 + "실데이터 보고 조정" 으로 분리하는 관행이 있다. Stage 2 의 root_lot 확장도 07-18 문서에서 「규칙만 확정, 활성화는 사내 연동 후」로 이미 못 박혀 있다. 구조를 먼저 짜고 상수를 나중에 맞추는 것은 원래 설계 의도다.

### 이 결정이 만드는 위험과 완화책

| 위험 | 실증 | 완화 |
|---|---|---|
| **더미가 정답을 심어둔 데이터** — green 이 실력인지 데이터가 착한 건지 구분 불가 | 07-18 리뷰: 「더미 데이터가 너무 착해서 안 드러난다… pytest 가 전부 green 이라 손댈 근거가 없다」. 사내 LLM 연동 시 반례 양방향 0 은 `center_spot ↔ ETCH-9` 1:1 배치 탓 | **Task 4** — 적대적 케이스 심기 |
| **스키마 계약 어긋남이 Stage 5 까지 숨는다** | `generate_dummy.py` 에는 `ppid` 가 있고 `load_internal.py` 에는 없다 → `hyp_ppid_commonality` 는 더미에서 green, 실데이터에서 즉시 `ValueError`. **이미 벌어진 일** | **Task 1·2** — 계약 동결 테스트 |

---

## 1. 개정 Stage 표

```
Stage 0    ✅ 완료 (2026-07-24) — 레지스트리를 commonality(step_history) 위에
Stage 1    ⏸  Stage 5.5 로 이동 (실데이터 · _extract() 사내 작업 대기)
Stage A    ← 이 문서. 안전장치 + 계약 동결 + 적대적 더미
Stage 2    find_normal_wafers → root_lot 기반 대조군 (B-3)
Stage 3    sensor_log + SensorStore, parameter_drift 부활  ⚠ 서브시스템 규모
Stage 4    defect_type 그룹핑 → EDS top-k, status_node 재설계 (A-3)
Stage 5    process_log · 레거시 도구 삭제 = 단일 스키마 완성
Stage 5.5  구 Stage 1 — 실데이터 적재 · 검증 · 임계 튜닝
```

**Stage 2·3·4 는 각자 별도 spec/plan 이 필요하다. 이 문서 범위 밖이다.** 각 Stage 진입 전 확인 사항만 §4 에 남긴다.

> **주의: Stage 3 은 규모가 다르다.** `sensor_log` + `SensorStore` + 캐시 DB + 온디맨드 fetch/무효화 + `compare_parameter_distribution` 재설계 + `parameter_drift` 부활. Stage 2·4 가 파일 한두 개 규모인데 Stage 3 만 서브시스템 신설이다. 일정 산정 시 분리할 것. 2단 깔때기가 완성되는 것도 Stage 3 이므로, 그전까지 시스템은 "어느 챔버가 의심된다" 까지만 말하고 "왜" 는 못 말한다.

---

## Global Constraints

- **기존 테스트 green 유지.** 각 Task 종료 시 `python -m pytest -q` 전체 통과. 현재 기준선을 Task 0 에서 먼저 기록한다.
- **난수열 보존.** `generate_dummy.py` 에 신호를 추가할 때 기존 난수 소비 순서를 깨지 않는다(기존 관행 — 파일 주석 참조). 임베딩 그룹 응집이 깨지면 EDS 형제 묶기 테스트가 연쇄 실패한다.
- **기존 wafer 를 변형하지 않고 신규 lot 을 추가한다.** `W2406_*`·`W2407_*`·패턴 그룹은 기존 테스트의 기대값이므로 건드리지 않는다. 적대적 케이스는 새 lot 으로 넣는다.
- **레거시 도구를 삭제하지 않는다.** 이 문서는 노출만 막는다. 삭제는 Stage 5.
- **`data/load_internal.py` 수정은 Task 2 의 결정 게이트를 통과한 뒤에만.** Stage 0 이 source of truth 로 동결해 둔 파일이고, `_extract()` 입력 계약이 사내 작업과 맞물려 있다.
- 주석·docstring·테스트 이름은 기존 코드처럼 한국어 유지.
- 커밋 메시지는 기존 히스토리 스타일(`feat:`/`fix:`/`test:`/`docs:` + 한국어 요약)을 따르고, 말미에 기존 관행대로 `Co-Authored-By` 트레일러를 붙인다.

---

## File Structure

- `tests/test_schema_contract.py` (신규) — 세 스키마 정의원의 일치 검증
- `config.py` (수정) — `LEGACY_TOOLS_ENABLED` 추가
- `tools/agent_tools.py` (수정) — 레거시 도구 노출을 플래그로 게이팅
- `data/generate_dummy.py` (수정) — 적대적 lot 추가
- `tests/test_adversarial_dummy.py` (신규) — 적대적 케이스가 의도대로 동작하는지
- `README.md` (수정) — 코드 현실과 동기화
- `data/load_internal.py` (조건부 수정 — Task 2 결정 후)

---

### Task 0: 기준선 기록

**Files:** 없음 (조사만)

- [x] **Step 1: 현재 테스트 수·통과 상태 기록**

Run: `python -m pytest -q`
기대: 전체 PASS. **통과 개수를 이 문서 하단 §5 에 기록한다.** 이후 모든 Task 의 회귀 판정 기준선이다.

- [x] **Step 2: Stage 0 실제 병합 범위 확인**

Run:
```bash
git log --oneline -20
git grep -n "hyp_eqp_ch_commonality\|hyp_ppid_commonality" -- '*.py' '*.yaml'
git grep -n "compare_process_logs" -- '*.py'
```
확인할 것: Stage 0 의 7개 Task 가 전부 병합됐는지, `compare_process_logs` 가 `ANALYSIS_TOOLS` 에서 빠졌는지. **문서보다 코드가 앞서 있는 것이 이 저장소의 관행이므로 반드시 코드로 확인한다.**

- [x] **Step 3: 세 스키마 정의원의 컬럼을 직접 나열**

```bash
git grep -n "CREATE TABLE step_history" -A 10 -- data/
git grep -n "INSERT INTO step_history" -A 3 -- data/
cat domain/hypotheses.yaml
```
`load_internal.py` DDL·INSERT / `generate_dummy.py` DDL·INSERT / `hypotheses.yaml` legend 컬럼, 세 목록을 적어 비교한다. Task 1 테스트가 이 비교를 자동화한다.

---

### Task 1: 스키마 계약 동결 테스트

세 곳에 흩어진 `step_history` 스키마 정의가 어긋나면 **더미 단계에서** 빨간불이 켜지게 한다. 이 계획의 유일한 구조적 위험을 테스트 하나로 막는 것이 목적이다.

**Files:**
- Create: `tests/test_schema_contract.py`

**Interfaces:**
- Consumes: `data/load_internal.py`(DDL 상수), `data/generate_dummy.py`(DDL), `domain/registry.load_hypotheses`, `tools/commonality._legend_columns`
- Produces: 없음 (테스트만)

**설계 메모:** 세 정의원을 **문자열 파싱이 아니라 각 모듈이 실제로 쓰는 값**에서 뽑는다. `load_internal` 은 DDL 상수를 in-memory sqlite 에 실행해 `PRAGMA table_info` 로 읽고, 더미는 생성된 `yield.db` 에서 읽고, legend 는 `load_hypotheses()` → `_legend_columns()` 로 읽는다. 파싱을 피해야 DDL 포맷이 바뀌어도 테스트가 살아 있다.

- [x] **Step 1: 테스트 작성**

`tests/test_schema_contract.py` 신규:

```python
"""스키마 계약 동결 — step_history 정의가 세 곳에서 일치하는지.

이 테스트가 존재하는 이유:
  generate_dummy.py 에는 ppid 가 있고 load_internal.py 에는 없어서,
  hyp_ppid_commonality 가 더미에서 green 인데 실데이터에서 ValueError 로 죽는 일이
  실제로 발생했다. 더미 우선 개발(2026-07-25 결정)에서는 이런 어긋남이 Stage 5 까지
  숨을 수 있으므로, 계약을 테스트로 동결한다.

세 정의원:
  1) data/load_internal.py  — 사내 적재 스키마 (source of truth)
  2) data/generate_dummy.py — 더미 스키마 (개발·테스트가 실제로 밟는 것)
  3) domain/hypotheses.yaml — legend 가 요구하는 컬럼
계약: 3 ⊆ 1  AND  3 ⊆ 2  (가설이 요구하는 컬럼은 양쪽 스키마에 다 있어야 한다)
"""

import sqlite3

import config
from domain import registry
from tools import commonality as cm


def _cols_from_ddl(ddl: str, table: str) -> set[str]:
    """DDL 을 in-memory sqlite 에 실행해 컬럼명을 읽는다 (문자열 파싱 회피)."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(ddl)
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _internal_step_cols() -> set[str]:
    from data import load_internal
    return _cols_from_ddl(load_internal.DDL, "step_history")


def _dummy_step_cols() -> set[str]:
    conn = sqlite3.connect(config.DB_PATH)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(step_history)")}
    finally:
        conn.close()


def _legend_cols() -> set[str]:
    cols = set()
    for spec in registry.load_hypotheses():
        cols |= set(cm._legend_columns(spec["legend"]))
    return cols


def test_legend_columns_exist_in_internal_schema():
    """가설이 요구하는 컬럼이 사내 적재 스키마에 다 있어야 한다.

    실패하면: 해당 legend 는 실데이터에서 ValueError 로 죽는다.
    load_internal 에 컬럼을 추가하거나(사내 _extract() 계약 협의 필요),
    해당 가설을 hypotheses.yaml 에서 빼야 한다.
    """
    missing = _legend_cols() - _internal_step_cols()
    assert not missing, (
        f"legend 컬럼 {sorted(missing)} 이 load_internal.py 의 step_history 에 없다. "
        f"실데이터에서 해당 가설 도구는 호출 즉시 ValueError. "
        f"docs/superpowers/plans/2026-07-25-dummy-first-stage-reorder.md Task 2 참조."
    )


def test_legend_columns_exist_in_dummy_schema():
    missing = _legend_cols() - _dummy_step_cols()
    assert not missing, f"legend 컬럼 {sorted(missing)} 이 더미 step_history 에 없다."


def test_internal_and_dummy_step_history_do_not_diverge_silently():
    """두 스키마 차이를 '알려진 차이' 로만 허용한다.

    ALLOWED 를 늘릴 때는 그 차이가 왜 안전한지 주석으로 남긴다.
    비어 있는 것이 최선이다.
    """
    ALLOWED: set[str] = set()      # 알려진 차이 (없는 것이 목표)
    diff = _internal_step_cols() ^ _dummy_step_cols()
    assert diff <= ALLOWED, (
        f"step_history 스키마가 두 곳에서 갈렸다: {sorted(diff - ALLOWED)}. "
        f"의도된 차이면 ALLOWED 에 이유와 함께 추가하라."
    )
```

- [x] **Step 2: 실패 확인 — 이것이 이 Task 의 산출물이다**

Run: `python -m pytest tests/test_schema_contract.py -v`
기대: `test_legend_columns_exist_in_internal_schema` **FAIL** — `{'ppid'}` 가 빠졌다고 나와야 한다.

실행 결과(2026-07-25): **2 failed, 1 passed** — `..._internal_schema` 와
`..._do_not_diverge_silently` 가 `{'ppid'}` 로 FAIL, 더미 쪽만 PASS. 예측대로다.
`load_internal.DDL` 은 모듈 상수로 존재해 `_internal_step_cols()` 를 고칠 필요 없었다.

`load_internal.py` 에 `DDL` 이라는 이름의 모듈 상수가 없으면(내부 변수·다른 이름) `_internal_step_cols()` 를 실제 구조에 맞게 고친다. 파일 자체는 아직 수정하지 않는다.

세 테스트가 전부 통과하면 ppid 어긋남이 이미 해소된 것이므로 Task 2 는 건너뛰고 Step 4 로 간다.

- [x] **Step 3: Task 2 로 이동** — 빨간불의 해소는 결정이 필요하다.

- [x] **Step 4: 커밋** (Task 2 해소 후 함께 green 으로 커밋)

```
test: step_history 스키마 계약 동결 테스트 (ppid 어긋남 가시화)

세 정의원(load_internal DDL / generate_dummy DDL / hypotheses.yaml legend)의
컬럼 집합 일치를 검증한다. 더미 우선 개발에서 스키마 어긋남이 Stage 5 까지
숨는 것을 막는다.
```

---

### Task 2: ppid 계약 어긋남 해소 — 결정 게이트 ⚠

**⚠ 이 Task 는 사용자 판단이 필요하다. Claude Code 는 여기서 멈추고 물어본다.**

**문제:** `hyp_ppid_commonality` 의 legend 는 `columns: [ppid]` 를 요구하고 `commonality._history()` 는 요청 컬럼이 `step_history` 에 없으면 `ValueError` 를 던진다. `load_internal.py` 의 INSERT 는 `(wafer_id, process_step, eqp_id, ch_id, timestamp)` 로 ppid 가 없다. `_extract()` 입력 계약 docstring 의 `step_records` 에도 없다.

즉 **PPID 가설(2차 legend, "EQP_CH 로 안 갈릴 때" 의 주력)은 실데이터에서 죽어 있다.** 더미에는 ppid 가 있어 테스트가 green 이라 지금까지 안 드러났다.

**옵션 A — `load_internal.py` 에 ppid 추가 (권장)**
- DDL·INSERT·`transform_steps` 에 `ppid` 를 nullable 로 추가
- `_extract()` 입력 계약 docstring 의 `step_records` 에 `ppid(optional)` 추가
- ⚠ **사내에서 `_extract()` 를 작성 중이므로 오늘 알려야 한다.** 나중에 알리면 계약 재협의 + 재작업
- Stage 0 의 "load_internal 수정 금지" 동결을 해제해야 함 → 사용자 승인 필요

**옵션 B — `ppid_commonality` 를 실데이터 미지원으로 명시**
- `hypotheses.yaml` 에서 주석 처리하거나 `enabled: false` 필드 추가
- Task 1 테스트는 green 이 되지만 **2차 legend 능력을 포기**하는 것
- ppid 를 실을 수 없는 사내 사정이 확인된 경우에만

- [x] **Step 1: 사용자에게 옵션 A/B 를 제시하고 결정을 받는다.** 결정 없이 진행하지 않는다.

**결정 (2026-07-25): 옵션 A.** 사내 `_extract()` 에 ppid 를 싣는 것으로 사용자가 확정.
저장소 쪽 컬럼은 nullable 이라 사내 반영을 기다리지 않고 먼저 뚫는다 — ppid 가 아직
안 실려도 commonality 가 그 레벨을 건너뛰므로(`_candidate_keys`) 무해하다.

- [x] **Step 2: 결정에 따라 구현** — 옵션 A 면 `load_internal.py` 4곳(DDL·INSERT·`transform_steps`·`_extract()` docstring), 옵션 B 면 `hypotheses.yaml` + `registry.py` 검증.

실제 수정한 곳(입력 계약은 `_extract()` 자체 docstring 이 아니라 **모듈 docstring** 에 있다):
1. 모듈 docstring 입력 계약 — `step_records` 에 `ppid(optional)` + **grain 경고**
   (wafer×스텝 단위. lot/recipe 단위로 넣으면 에러 없이 틀린 집계가 난다)
2. `transform_steps()` — `"ppid": _text(r.get("ppid"))`
3. `DDL` step_history — `ppid TEXT` (더미와 같은 자리: ch_id 다음)
4. INSERT 컬럼·바인딩

계획 밖 추가 2건(사용자 승인):
5. `validate()`/`_print()` 에 `ppid_null_rate` — 전부 NULL 이면 `hyp_ppid_commonality`
   가 **에러 없이 후보 0** 으로 끝나, 이 값이 없으면 "PPID 로도 안 갈린다" 와
   "PPID 가 안 실렸다" 를 구분할 수 없다. `ch_id_null_rate` 와 대칭.
6. `tools/commonality.py` 모듈 docstring 의 의존 테이블 컬럼 목록 드리프트 정정.

- [x] **Step 3: Task 1 테스트 green 확인**

Run: `python -m pytest tests/test_schema_contract.py -v` → 3 PASS ✅

- [x] **Step 4: 전체 회귀**

Run: `python -m pytest -q` → Task 0 기준선과 동일 + 신규 3

결과: **123 passed** (120 + 3). 추가로 `load()` 자체를 도는 테스트가 저장소에 없어
임시 DB 스모크로 확인 — ppid 있는 행은 적재, 없는 행은 NULL, 결측률 0.333 출력.
(`load_internal` 무테스트 상태는 이 계획 범위 밖이나 기록해 둔다.)

- [x] **Step 5: 커밋** (Task 1 Step 4 와 함께)

---

### Task 3: 레거시 도구 노출을 플래그로 게이팅

실데이터에서 못 도는 도구가 LLM 도구 목록에 있으면, 실제 LLM 이 그것을 고르고 루프 예산(`MAX_LOOPS=6`)을 오류 복구에 태운다. 삭제(Stage 5)는 아직 못 하니 **노출만** 막는다.

**Files:**
- Modify: `config.py`
- Modify: `tools/agent_tools.py`
- Test: `tests/test_agent_tools.py`

**설계 메모:** 도구를 `ANALYSIS_TOOLS` 에서 그냥 빼면 `test_agent_tools.py`·`test_graph_nodes.py`(`get_process_log` 를 `TOOLS_BY_NAME` 으로 실행하는 케이스가 있다)·mock 시나리오가 깨진다. 그래서 **기본값 켜짐 플래그**로 게이팅한다 — 더미/테스트는 현행 그대로, 실데이터 실행만 끈다. Stage 5 에서 이 플래그와 도구를 함께 지운다.

- [x] **Step 1: `config.py` 에 플래그 추가**

`COMMONALITY_PASS_MIN_TARGET` 아래에 추가:

```python
# 옛 process_log 스키마에 묶인 레거시 도구를 LLM 에 노출할지.
# 더미에서는 동작하므로 기본 켜짐. 실데이터(step_history)에서는 못 도니 끈다 —
# 켜둔 채로 실데이터를 돌리면 LLM 이 죽은 도구를 골라 루프 예산을 태운다.
# Stage 5 에서 도구와 이 플래그를 함께 삭제한다.
LEGACY_TOOLS_ENABLED = os.getenv("LEGACY_TOOLS_ENABLED", "1") == "1"
```

- [x] **Step 2: 실패 테스트 추가**

⚠️ 아래 원안의 `finally` 는 `LEGACY_TOOLS_ENABLED` 를 **True 로 고정 복원**한다. 환경변수로
플래그를 끈 채 테스트를 돌리면 config 와 모듈 상태가 어긋난다. 실제로는 `monkeypatch.undo()`
후 reload 하도록 바꿔, 원래 값과 무관하게 정확히 되돌린다.

`tests/test_agent_tools.py` 끝에 추가:

```python
def test_legacy_tools_hidden_when_flag_off(monkeypatch):
    """실데이터 모드에서는 process_log 기반 레거시 도구가 LLM 에 노출되지 않는다."""
    import importlib

    import config
    from tools import agent_tools

    monkeypatch.setattr(config, "LEGACY_TOOLS_ENABLED", False)
    importlib.reload(agent_tools)
    try:
        names = {t.name for t in agent_tools.ANALYSIS_TOOLS}
        assert not (names & {"get_process_log", "find_counterexamples",
                             "validate_data_completeness"})
        assert any(n.startswith("hyp_") for n in names)      # 가설 도구는 남는다
        assert "finalize" in {t.name for t in agent_tools.ALL_TOOLS}
    finally:
        monkeypatch.setattr(config, "LEGACY_TOOLS_ENABLED", True)
        importlib.reload(agent_tools)                         # 다른 테스트에 누수 방지
```

- [x] **Step 3: 실패 확인** — Run: `python -m pytest tests/test_agent_tools.py -v` → FAIL
      (`AttributeError: config has no attribute 'LEGACY_TOOLS_ENABLED'`)

- [x] **Step 4: 구현**

`tools/agent_tools.py` 의 `ANALYSIS_TOOLS` 조립부를 교체. **실제 현재 목록을 먼저 읽고**, 레거시로 분류된 것만 플래그 뒤로 옮긴다:

```python
_LEGACY_TOOLS = [get_process_log, find_counterexamples, validate_data_completeness]
_BASE_TOOLS = [get_wafer, search_similar, aggregate_defects]

ANALYSIS_TOOLS = [
    *_BASE_TOOLS,
    *(_LEGACY_TOOLS if config.LEGACY_TOOLS_ENABLED else []),
    *_HYPOTHESIS_TOOLS,
]
ALL_TOOLS = ANALYSIS_TOOLS + [finalize]
TOOLS_BY_NAME = {t.name: t for t in ANALYSIS_TOOLS}
```

`aggregate_defects` 는 `yield.defect_type` 에 의존하므로 실데이터(nullable)에서 의미가 약하지만, Stage 4(defect_type→EDS)의 소관이라 여기서는 건드리지 않는다. `_BASE_TOOLS` 에 둔다.

- [x] **Step 5: 전체 회귀** — Run: `python -m pytest -q` → 기준선 + 신규

결과: **126 passed**. 추가 확인 2건 —
`LEGACY_TOOLS_ENABLED=0` 환경변수 경로로 `ANALYSIS_TOOLS` 가
`{get_wafer, search_similar, aggregate_defects, hyp_eqp_ch_commonality, hyp_ppid_commonality}`
로 줄고, 그 상태로 `python main.py W2406_02` 가 **정상 완주**(레거시 도구 없이
aggregate_defects → hyp_eqp_ch_commonality 로 ETCH9_B 결론, 게이트 반려→승인 유지).

구현 시 `_LEGACY_TOOLS` 순서는 원안(`get_process_log, find_counterexamples,
validate_data_completeness`)이 아니라 기존 `ANALYSIS_TOOLS` 등장 순서를 유지했다.

- [x] **Step 6: 커밋**

```
feat: 레거시 도구 노출을 LEGACY_TOOLS_ENABLED 로 게이팅

process_log 기반 도구는 실데이터에서 못 돈다. 삭제(Stage 5) 전까지
노출만 막아 실데이터 E2E 에서 LLM 이 죽은 도구에 루프 예산을 태우지 않게 한다.
기본 켜짐 — 더미·테스트 동작은 불변.
```

---

### Task 4: 더미를 적대적 평가셋으로 승격

**이 Task 가 이 계획의 본체다.** 더미 우선 개발의 유일한 진짜 대가는 "정답지 없음" 이고, 이것이 그 절반을 메운다. 여기서 만든 케이스가 그대로 평가셋의 씨앗이 된다.

**Files:**
- Modify: `data/generate_dummy.py`
- Create: `tests/test_adversarial_dummy.py`
- Regenerate: `data/yield.db`, `data/embeddings/`

**설계 메모 — 왜 신규 lot 으로 넣는가:** 기존 `W2406_*`·`W2407_*`·패턴 그룹은 다수 테스트의 기대값이고, 임베딩 그룹 응집은 난수열에 민감하다. 기존 lot 을 변형하면 연쇄 실패가 난다. 적대적 케이스는 **신규 lot(`LOT2414` 이후)** 으로 추가하고, `step_history` 생성도 독립 rng 로 격리한다.

심을 케이스 5종:

| # | 케이스 | 심는 방법 | 시험하는 것 |
|---|---|---|---|
| 1 | **반례 살아있음** | 진짜 원인 챔버를 거쳤는데 정상인 wafer 를 대조군에 1~2장 | `score < 1.0`. 임계 경계에서 `passes` 판정이 흔들리는지. 지금 더미는 1:1 이라 항상 1.0 |
| 2 | **근접 미끼** | 진짜(score 1.0)와 가까운 후보(score 0.7~0.85) 하나 | 순위가 뒤집히지 않는지. 게이트가 미끼를 결론으로 승인하지 않는지 |
| 3 | **결측** | `step_history` 없는 wafer 1장, `ch_id` NULL 인 행 몇 개 | `missing_history` 에 분리되는지. 챔버 레벨이 조용히 스킵되고 가짜 키가 안 생기는지. 결측이 분모를 오염시키지 않는지 |
| 4 | **"모른다" 가 정답** | 원인이 root_lot 전원에 걸린 lot — 타깃·대조군이 같은 경로 | `status == "no_signal"`, 후보 0, note 가 "원인 없음이 아니라 lot 내부 대조로는 안 보인다" 를 반환. 게이트가 확정 결론을 내지 않는지. **가장 중요한 케이스** |
| 5 | **대조군 부족** | 기존 `LOT2407` 로 이미 존재 | `control_insufficient` 조기 출구 유지 (회귀 방어) |

**범위 밖:** 다인성(독립 원인 2개가 타깃을 절반씩 설명)은 게이트·리포트가 병렬 원인을 어떻게 표현할지 설계가 필요하다. 별도 작업으로 분리.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_adversarial_dummy.py` 신규. 케이스별로 하나씩. 예:

```python
"""적대적 더미 케이스 — 더미가 착해서 안 드러나던 것들.

2026-07-25 더미 우선 개발 결정의 안전장치. 각 케이스는 평가셋 항목이기도 하다.
"""

from tools import commonality as cm


def test_case4_cause_spanning_whole_root_lot_yields_no_signal():
    """원인이 root_lot 전원에 걸리면 후보가 없어야 한다 ('모른다' 가 정답).

    lot 내부 대조로는 구조적으로 안 보이는 케이스. 후보를 억지로 내면 허위 확정이다.
    """
    res = cm.find_commonality(SPAN_TARGET, SPAN_CONTROL)
    assert res["status"] == "no_signal"
    assert res["candidates"] == []
    assert "lot 내부 대조" in res["note"]


def test_case1_counterexample_lowers_score_below_one():
    res = cm.find_commonality(CE_TARGET, CE_CONTROL)
    top = res["candidates"][0]
    assert top["control_pass"] > 0        # 반례 존재
    assert top["score"] < 1.0
```

wafer ID 상수는 Step 2 에서 심는 값으로 채운다.

- [ ] **Step 2: 실패 확인** — Run: `python -m pytest tests/test_adversarial_dummy.py -v` → FAIL (해당 lot 없음)

- [ ] **Step 3: `generate_dummy.py` 에 적대적 lot 추가**

기존 `_make_step_history` 패턴을 따라 신규 lot 을 추가한다. 제약: 기존 난수열 미변경, 기존 lot 미변형.

- [ ] **Step 4: 더미 재생성 + 통과 확인**

Run: `python data/generate_dummy.py && python -m pytest -q`
기대: 신규 테스트 PASS + **기존 전체 PASS**(Task 0 기준선). 기존이 깨지면 난수열·임베딩을 건드린 것이니 되돌린다.

- [ ] **Step 5: 게이트까지 확인 — 케이스 4 는 E2E 로**

케이스 4 대상으로 `python main.py <해당 wafer>` 를 돌려, 리포트가 확정 결론이 아니라 미확정/분석 미수행 톤으로 나오는지 눈으로 확인한다. `no_signal` 인데 확정 결론이 나오면 **게이트 결함**이므로 별도 이슈로 기록한다.

- [ ] **Step 6: 커밋**

```
test: 적대적 더미 케이스 5종 (반례·근접 미끼·결측·no_signal·대조군 부족)

더미가 착해서 안 드러나던 실패 모드를 심는다. 특히 '원인이 root_lot 전원에
걸려 모른다가 정답' 케이스 — 물러설 줄 아는지를 시험한다.
평가셋의 씨앗.
```

---

### Task 5: README 코드 현실과 동기화

README 의 데모 출력·도구 목록이 Stage 0 이전(`compare_process_logs`, `ETCH-9 rf_power`)이다. 코드·테스트는 `hyp_eqp_ch_commonality`·`ETCH9_B` 로 넘어갔다. 시연 리스크가 크고 비용이 낮다.

**Files:** Modify: `README.md`

- [ ] **Step 1: 데모 출력 블록을 실제 실행 결과로 교체**

Run: `PYTHONUTF8=1 python main.py W2406_02` → 출력을 그대로 붙인다. **손으로 쓰지 말고 실제 출력을 쓴다.**

- [ ] **Step 2: "분석 루프" 절의 도구 목록을 실제 `ANALYSIS_TOOLS` 와 일치시킨다**

`compare_process_logs`·`compare_parameter_distribution` 서술을 legend 기반 `hyp_*` 로 교체. `LEGACY_TOOLS_ENABLED`(Task 3)를 한 줄 언급.

- [ ] **Step 3: 시연 서사 정정**

「반려→재시도→승인 순환이 End-to-End 의 핵심」은 mock 각본에서만 보인다. 실제 사내 LLM 은 근거를 먼저 쌓고 finalize 하므로 반려가 안 나타난다(정상 동작). 문구를 "게이트가 근거 없는 결론을 반려한다" 로 낮추고, 순환 자체를 볼거리로 내세우지 않는다.

- [ ] **Step 4: 빠른 시작 절** — `pytest` → `python -m pytest`, `config.py` 손수정 전제 → 환경변수/`.env` 방식으로 갱신.

- [ ] **Step 5: 커밋** — `docs: README 를 Stage 0 이후 코드 현실과 동기화`

---

### Task 6: Stage 표를 독립 문서로 승격

현재 Stage 표는 Stage 0 설계 문서 §12 의 "(참고)" 절에 얹혀 있고, 참조하는 `docs/2026-07-24-domain-corrections.md`(A-3·B-3·§E)는 저장소에 없다. 재배열까지 반영된 표가 찾기 쉬운 곳에 있어야 한다.

**Files:**
- Create: `docs/stages.md`
- Modify: `docs/superpowers/specs/2026-07-24-registry-commonality-realignment-design.md` (§12 에 포인터 한 줄)

- [ ] **Step 1: `docs/stages.md` 작성** — §1 개정 표 + 각 Stage 의 진입 조건(§4) + 현재 위치. 단일 출처로 삼는다.
- [ ] **Step 2: 누락 문서 기록** — `domain-corrections.md` 부재와 A-3/B-3/§E 라벨이 그것을 가리킨다는 사실을 명시. 복원 필요 항목으로 남긴다.
- [ ] **Step 3: §12 에 포인터 추가** — `> 재배열 반영 최신판: docs/stages.md (2026-07-25)`
- [ ] **Step 4: 커밋** — `docs: Stage 표를 docs/stages.md 로 승격 (재배열 반영)`

---

## 4. 각 Stage 진입 전 확인 사항 (이 문서 범위 밖)

각 Stage 는 별도 spec/plan 을 쓴다. 착수 시 아래를 먼저 확인한다.

**Stage 2 (대조군)** — 07-18 문서 §7 의 3단계 규칙(형제 lot 내 합집합 → 같은 root_lot 양산랏 확장 → 정직 보고)이 확정 상태다. 새로 정할 것은 `defect_type` 의존 제거 방법. 라벨 없이 "정상" 을 어떻게 정의하는가(수율 임계만? EDS 비유사성?)가 핵심 결정.

**Stage 3 (센서)** — 착수 전 규모를 분리 산정할 것. 아래 계약 3건은 이미 정해진
제약이므로 spec 에 그대로 옮기고, 결정 항목은 spec 초반에 답을 정한다.

*계약 (어기면 분석이 성립하지 않는다):*

1. **fetch 단위는 (지목된 스텝 × 타깃+대조군 전원).** 챔버 단위로 당기면 안 된다 —
   1단이 그 챔버를 지목한 근거가 "대조군은 안 거쳤다"(score=1.0 이면 control_pass=0)
   이므로, 지목된 챔버만 뽑으면 대조군 표본이 0 이라 비교 자체가 성립하지 않는다.
2. **tool 반환은 집계값만** (표본 수·평균·표준편차·효과크기·이탈률). 원본 트레이스는
   `sensor_cache.db` 에 두고 ToolMessage 에 싣지 않는다. 분석당 수만 행이라 한 번만
   어겨도 컨텍스트가 터진다. 반환은 효과크기 top-K 로 절단해 fetch 량과 무관하게
   유계로 만든다 (commonality 의 `top_k`·`truncated` 와 같은 구조).
3. **2단 출력은 후보이지 결론이 아니다.** p-value 컷이 아니라 효과크기 랭킹.
   스텝당 센서 수백 개라 α=0.05 면 우연히 수십 개가 유의하다. tool 결과 `note` 에
   명시한다 (1단과 같은 원칙 — B-1).

*결정 항목:*

4. **기준선을 그룹 대조로 할지 시간 대조로 할지.** 그룹 대조 = 같은 스텝의 다른 챔버,
   시간 대조 = 그 챔버의 과거 정상 구간. 둘은 다른 원인에 반응한다 — PM·부품 교체는
   시간 대조로만 잡힌다. `parameter_drift 부활` 이 후자를 암시하나 명시된 적이 없다.
   둘 다 하면 규모가 다시 는다.

*기존 항목 보강:*

5. **캐시 무효화 정책·`sensor_cache.db` 수명 주기·온디맨드 fetch 실패 처리가 미설계.**
   특히 수명 주기는 성능이 아니라 **감사 추적** 문제다 — 반환이 집계값만이면 `findings`
   에도 집계값만 남고, 캐시가 비워진 뒤에는 리포트의 효과크기 3.6 이 어디서 나왔는지
   재현할 수 없다. 리포트 보존 기간만큼 캐시를 살리거나, `findings` 에 재fetch 키
   (스텝·wafer 목록·시각 범위)를 남기거나 — 무효화 정책과 함께 정한다.

**Stage 4 (그룹핑)** — `SIBLING_MIN_SIMILARITY` 컷오프가 실데이터 분포에서 타당한지 확인 불가(Stage 5.5 로 이월). 컷오프를 못 정한 채 구조만 짜는 것을 감수한다.

**Stage 5 (삭제)** — **삭제 전 대체 매핑을 명시적으로 확인한다.** 레거시 도구 중 `validate_data_completeness`·`find_counterexamples` 는 레거시가 아니라 기능이다. 설계상 반례는 commonality 2×2 의 b·c 셀이, 품질 검사는 `load_internal.validate()` + `missing_history`/`no_paired_stratum` 이 흡수한 것으로 보이지만, 확인 없이 지우면 기능이 조용히 빠진다.

**Stage 5.5 (구 Stage 1)** — 합격 기준을 착수 전에 정의한다. 현재 "commonality 1회 검증" 은 기준이 없다. 최소:
1. `load_internal.validate()` 리포트에 fatal 없음
2. 적대적 케이스 5종의 판정이 실데이터에서도 유지
3. **과거에 원인이 확정된 사례 3~5건에서 Top-3 안에 정답이 들어오는지** ← 이것이 진짜 검증. 사내 사례 확보가 전제
4. 임계(`COMMONALITY_PASS_MIN_SCORE`·`MIN_TARGET`·`SIBLING_MIN_SIMILARITY`·`YIELD_THRESHOLD`)를 실분포로 조정

3번이 확보되지 않으면 Stage 5.5 는 "에러 없이 돈다" 수준의 스모크임을 문서에 정직하게 남긴다.

---

## 5. 완료 기준

1. `python -m pytest -q` 전체 green. Task 0 기준선 + 신규(계약 3 + 레거시 1 + 적대적 5 내외).
2. **`test_schema_contract.py` 3케이스 green** — ppid 어긋남이 해소되거나 명시적으로 문서화됨.
3. `LEGACY_TOOLS_ENABLED=0` 으로 실행 시 `ANALYSIS_TOOLS` 에 레거시 도구 없음, 가설 도구는 존재.
4. 적대적 케이스 4(`no_signal`)가 확정 결론을 내지 않음 — E2E 눈 확인 포함.
5. README 데모 출력이 실제 실행 결과와 일치.
6. `docs/stages.md` 존재, Stage 0 설계 문서 §12 가 그것을 가리킴.

**Task 0 기준선 기록:** `python -m pytest -q` = **120 passed** (2026-07-25, Stage 0 직후)

착수 시 확인한 것:
- Stage 0 배선 정상 — `hyp_eqp_ch_commonality`·`hyp_ppid_commonality` 라이브,
  `compare_process_logs` 는 `tools/yield_tools.py` 에 남아 있으나 `ANALYSIS_TOOLS` 에서 빠짐(미노출).
- 세 정의원 컬럼 비교 결과 **`legend - internal = ['ppid']`** — Task 2 가 지목한 어긋남 확인.
  `legend - dummy` 는 공집합(더미에는 ppid 있음)이라 기존 테스트가 green 이었던 것도 확인.

---

## Self-Review

**이 계획이 다루지 않는 것 (의도적):**
- Stage 2·3·4·5 의 실제 구현 — 각자 별도 plan
- EvidenceBundle 게이트 강화 — 게이트가 여전히 문자열 매칭이라 LLM 이 통과 토큰만 문장에 끼워 넣으면 승인된다. `evidence_based_analysis_roadmap.md` Phase 1 의 남은 항목이며 Stage 축과 별개
- 시간축(장비 이벤트·PM·recipe 이력) — Phase 2
- 사람 검토 폐루프 — Phase 3
- 다인성 처리

**두 로드맵의 관계 (기록):** Stage 축은 "실데이터에서 돌게 만든다", Phase 축은 "믿을 만하게 만든다" 다. 서로를 참조하지 않는다. **Stage 5 를 다 끝내도 결론 정확도를 측정할 수단은 없다.** Task 4 의 적대적 케이스가 Phase 축으로 넘어가는 첫 다리다.

**가장 큰 잔여 위험:** 과거 원인 확정 사례(정답지)를 확보하지 못하면 Stage 5.5 이후에도 시스템의 신뢰도를 모른다. 사내 사례 확보는 코드 작업이 아니라 조직 작업이므로, 지금부터 병행해서 요청해 두는 것이 좋다.
