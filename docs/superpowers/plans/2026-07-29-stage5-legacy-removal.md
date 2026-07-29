# Stage 5 — `process_log`·레거시 도구 삭제 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실데이터에 존재하지 않는 `process_log` 와 그것에 묶인 도구·함수·더미 테이블을 지워 스키마를 `yield`·`step_history`·`sensor_log` 3개로 확정한다.

**Architecture:** 삭제만 하는 작업이고 새 기능이 없다. 순서가 전부다 — 도구 노출(1) → 함수(2) → 데이터(3) → 계약(4) → 문서(5). 반대로 가면 중간 커밋에서 살아 있는 함수가 없는 테이블을 조회해 스위트가 빨개진다. 유일한 실질 작업은 Task 3 의 **불변식 재작성**이다: 더미의 "심은 이상은 심은 곳에만" 이 `process_log` 의 스펙 이탈로만 표현돼 있어 `step_history` 로 표현 가능한 범위(챔버 배타성)로 좁혀 다시 쓴다.

**Tech Stack:** Python 3, sqlite3, numpy, hnswlib, pytest

설계 문서: `docs/superpowers/specs/2026-07-29-stage5-legacy-removal-design.md`

## Global Constraints

- 작업 디렉터리는 `prototype/`. 모든 명령은 여기서 실행한다.
- 전체 테스트: `python -m pytest -q`. **착수 시점 기준선은 166 passed.**
- **테스트 수가 줄어드는 것이 정상이다** (166 → 139). 지워지는 코드를 검증하던 테스트다.
  > **실행 중 보정 (Task 2):** 플랜은 `test_yield_tools.py` 를 26개로 셌으나 실제는 25개였다.
  > 삭제는 21개가 아니라 20개이고, Task 2 이후 수치가 전부 1씩 올라간다
  > (142 → 137 → 139). 아래 각 Task 의 Expected 는 보정된 값이다.
  각 Task 에 예상 증감을 적어 두었다. **실제와 다르면 멈추고 이유를 확인한 뒤 진행한다.**
- **데모 경로는 한 글자도 바뀌지 않는다.** `process_log` 는 현재 분석 경로가 쓰지 않는다.
  `tests/test_e2e.py` 와 Task 3 의 DB 스냅샷 비교가 감시자다.
- 커밋 메시지는 한국어. 마지막 줄에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- 브랜치 `stage-5-legacy-removal` 에서 작업한다 (이미 생성됨). **병합은 사용자가 결정한다.**
- 삭제하다 "이건 살려야 하나?" 싶은 것이 나오면 **멈추고 물어본다.** 설계 문서의 대체 매핑
  표에 없는 기능이 나왔다는 뜻이다.

---

## File Structure

| 파일 | 이 작업에서의 책임 | Task |
|---|---|---|
| `tools/agent_tools.py` | 레거시 tool 래퍼 3개·`_LEGACY_TOOLS` 삭제 → 노출 도구 집합 확정 | 1 |
| `config.py` | `LEGACY_TOOLS_ENABLED` 삭제 | 1 |
| `tests/test_agent_tools.py` | 레거시 관련 4개 삭제 | 1 |
| `tools/yield_tools.py` | `process_log` 계열 5함수 삭제 (381줄 → 약 100줄) | 2 |
| `tests/test_yield_tools.py` | 26개 중 21개 삭제 | 2 |
| `data/generate_dummy.py` | `PROCESS_FLOW`·`_make_process_logs`·챔버 상수 3개·`process_log` DDL/INSERT 삭제 | 3 |
| `tests/test_dummy_data.py` | 7개 삭제 + 불변식 2개 신규 | 3 |
| `tests/test_schema_contract.py` | `yield` DDL 동결 2개 신규 | 4 |
| 문서 5종 | 스펙 이탈 서술 정리 · Stage 5 완료 표기 | 5 |

---

### Task 1: 레거시 도구 노출 제거 + 플래그 삭제

**Files:**
- Modify: `tools/agent_tools.py:45-69`(래퍼 3개), `:90-103`(목록)
- Modify: `config.py:41-45`
- Modify: `tests/test_agent_tools.py:21-53`, `:66-101`

**Interfaces:**
- Consumes: 없음 (이 Task 가 시작점)
- Produces: `agent_tools.ANALYSIS_TOOLS` = `_BASE_TOOLS + _HYPOTHESIS_TOOLS`.
  `config.LEGACY_TOOLS_ENABLED` 는 **더 이상 존재하지 않는다** — 이후 Task 에서 참조 금지.

**배경 (구현자용):** `get_process_log`·`validate_data_completeness`·`find_counterexamples` 는
`config.LEGACY_TOOLS_ENABLED`(기본 False)가 False 면 LLM 에게 아예 안 보인다. 즉 **지금도
분석 경로가 쓰지 않는다.** 이 Task 는 그 죽은 분기와 플래그를 없앤다. `yield_tools` 쪽 함수
본체는 Task 2 에서 지운다(여기서 같이 지우면 import 오류로 중간 커밋이 빨개진다).

- [ ] **Step 1: `tools/agent_tools.py` 에서 래퍼 3개 삭제**

`get_process_log`·`validate_data_completeness`·`find_counterexamples` 세 `@tool` 함수 정의를
통째로 지운다 (`get_wafer`·`search_similar` 와 `compare_sensor_distribution` 사이의 세 블록).

- [ ] **Step 2: 목록과 import 정리**

파일 끝을 아래로 바꾼다:

```python
_HYPOTHESIS_TOOLS = registry.build_tools(registry.load_hypotheses())

_BASE_TOOLS = [get_wafer, search_similar, compare_sensor_distribution]

ANALYSIS_TOOLS = [*_BASE_TOOLS, *_HYPOTHESIS_TOOLS]
ALL_TOOLS = ANALYSIS_TOOLS + [finalize]
TOOLS_BY_NAME = {t.name: t for t in ANALYSIS_TOOLS}
```

파일 상단의 `import config` 는 이제 쓰이지 않는다 — 지운다. `from tools import yield_tools as yt`
는 `get_wafer` 가 아직 쓰므로 **남긴다.**

- [ ] **Step 3: `config.py` 에서 플래그 삭제**

`LEGACY_TOOLS_ENABLED = ...` 한 줄과 그 위 설명 주석 4줄(`# 옛 process_log 스키마에 묶인 …
# 도구와 이 플래그의 삭제는 Stage 5.`)을 지운다.

- [ ] **Step 4: `tests/test_agent_tools.py` 에서 4개 삭제**

`test_get_process_log_tool_invokes` · `test_validate_data_completeness_tool_invokes` ·
`test_legacy_tools_hidden_when_flag_off` · `test_legacy_tools_are_off_by_default` 를
통째로 지운다. **`test_tool_names` 는 그대로 둔다** — 이미 정확한 도구 집합을 단언하므로
이 Task 의 회귀 감시자다.

- [ ] **Step 5: 검증**

Run: `python -m pytest -q`
Expected: **162 passed** (166 − 4)

Run: `python -c "import config; print(hasattr(config, 'LEGACY_TOOLS_ENABLED'))"`
Expected: `False`

- [ ] **Step 6: 커밋**

```bash
git add tools/agent_tools.py config.py tests/test_agent_tools.py
git commit -F - <<'EOF'
refactor(stage5): 레거시 도구 노출 경로와 LEGACY_TOOLS_ENABLED 삭제

플래그가 기본 OFF 라 분석 경로는 이미 이 도구들을 쓰지 않았다. 죽은 분기와
플래그를 없앤다. yield_tools 의 함수 본체는 다음 커밋에서 지운다
(여기서 같이 지우면 import 오류로 중간 커밋이 깨진다).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: `yield_tools` 의 `process_log` 계열 5함수 삭제

**Files:**
- Modify: `tools/yield_tools.py:102-113`, `:116-168`, `:171-236`, `:239-325`, `:328-381`
- Modify: `tests/test_yield_tools.py` (26개 중 21개 삭제)

**Interfaces:**
- Consumes: Task 1 이 tool 래퍼를 지웠으므로 이 함수들의 호출부는 테스트뿐이다.
- Produces: `tools/yield_tools.py` 는 `find_low_yield_lots` · `get_wafer` · `get_wafers` ·
  `find_control_candidates` 4개만 남는다.

**배경 (구현자용):** 5개 중 `compare_process_logs` 와 `compare_parameter_distribution` 은
tool 로 등록된 적도 없는 **완전한 죽은 코드**다. 나머지 3개는 Task 1 이 래퍼를 지워 호출부가
없어졌다. 대체 매핑은 설계 문서의 표를 볼 것 — 기능 유실이 없음을 이미 확인했다.

- [ ] **Step 1: 함수 5개 삭제**

`tools/yield_tools.py` 에서 아래를 통째로 지운다:
`get_process_log` · `compare_process_logs` · `validate_data_completeness` ·
`compare_parameter_distribution` · `find_counterexamples`.

남는 것은 `_conn` · `find_low_yield_lots` · `get_wafer` · `get_wafers` ·
`find_control_candidates` 다.

- [ ] **Step 2: 죽은 import 정리**

`import statistics` 는 `compare_parameter_distribution` 만 쓰던 것이다 — 지운다.
`import sqlite3`·`from contextlib import contextmanager`·`import config` 는 `_conn` 이 쓰므로 남긴다.

확인: `python -c "import ast,sys; src=open('tools/yield_tools.py',encoding='utf-8').read(); print('statistics' in src)"`
Expected: `False`

- [ ] **Step 3: `tests/test_yield_tools.py` 에서 21개 삭제**

**남기는 5개**(이것 말고 전부 지운다):
- `test_get_wafers_returns_rows_for_known_ids_only`
- `test_find_control_candidates_includes_low_yield_unlabeled_wafer`
- `test_find_control_candidates_spans_split_lots_of_one_root_lot`
- `test_find_control_candidates_empty_root_lots`
- `test_find_low_yield_lots_threshold_binds_at_runtime`

지우는 것에는 `_make_db` 헬퍼(`:88`)와 그것을 쓰는 tmp_path 테스트들도 포함된다 —
`_make_db` 는 `process_log` 를 만드는 fixture 라 남길 이유가 없다. `import sqlite3` 도
`_make_db` 만 쓰던 것이면 함께 지운다(남은 테스트가 쓰는지 확인할 것).

모듈 docstring 이 `process_log` 를 언급하면 남은 함수에 맞게 고친다.

- [ ] **Step 4: 검증**

Run: `python -m pytest -q`
Expected: **142 passed** (162 − 20)

- [ ] **Step 5: 커밋**

```bash
git add tools/yield_tools.py tests/test_yield_tools.py
git commit -F - <<'EOF'
refactor(stage5): yield_tools 의 process_log 계열 5함수 삭제

get_process_log · compare_process_logs · validate_data_completeness ·
compare_parameter_distribution · find_counterexamples. 뒤의 둘은 tool 로 등록된
적도 없는 죽은 코드였다. 대체는 spec 의 매핑 표 참조 — 품질 검사는
load_internal.validate() 와 commonality 의 missing_history 가, 반례는
commonality 2x2 의 control_pass 가, 파라미터 비교는 센서 2단이 가져갔다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: 더미에서 `process_log` 삭제 + 불변식 재작성

**Files:**
- Modify: `data/generate_dummy.py:74-88`(상수), `:306`·`:311`(호출), `:316-353`(생성기), `:531-546`(DDL/INSERT)
- Modify: `tests/test_dummy_data.py` (7개 삭제 + 2개 신규)

**Interfaces:**
- Consumes: Task 2 가 조회 함수를 지웠으므로 이 테이블을 읽는 코드는 테스트뿐이다.
- Produces: `_write_sqlite(rows, steps, sensors)` — **`logs` 인자가 사라진다.**
  더미 DB 의 테이블은 `yield`·`step_history`·`sensor_log` 3개가 된다.

**배경 (구현자용) — 이 Task 에서 가장 중요한 사실:**

`_make_process_logs(rows, rng)` 는 **공유 `rng` 의 마지막 소비자**다. 그 뒤의
`_make_step_history` 는 `SEED+1`, `_make_sensor_log` 는 `SEED+2` 의 **전용 rng** 를 쓰고,
`_augment_yield`·`_make_adversarial_steps`·`_make_split_lot_steps` 는 난수를 쓰지 않는다.
따라서 **이 함수를 지워도 나머지 더미 데이터는 바이트 단위로 그대로**여야 한다.
Step 1 의 스냅샷이 그것을 증명한다 — 다르면 멈추고 원인을 찾는다.

- [ ] **Step 1: 삭제 전 DB 스냅샷을 뜬다**

```bash
SNAP="$TMPDIR/stage5"; mkdir -p "$SNAP"     # 저장소 밖에 둔다 (Windows 는 $TEMP)
python - <<'PY' > "$SNAP/before.txt"
import sqlite3, config
conn = sqlite3.connect(config.DB_PATH)
for t in ("yield", "step_history", "sensor_log"):
    for row in conn.execute(f"SELECT * FROM {t} ORDER BY 1,2,3"):
        print(t, row)
PY
```

**저장소 안에 임시 파일을 만들지 않는다.** `data/yield.db` 는 gitignore 대상이라
DB 자체는 커밋되지 않지만, 스냅샷 텍스트는 `git status` 를 더럽힌다.

- [ ] **Step 2: 생성기에서 `process_log` 를 걷어낸다**

`data/generate_dummy.py` 에서:

1. `PROCESS_FLOW` 정의(그 위 주석 3줄 포함)와 `DECOY_CHAMBER`·`REAL_CHAMBER`·
   `CONTROL_ETCH_CHAMBER` 세 상수를 지운다. **`DECOY_STEP` 도 지운다** — 네 상수 모두
   `_make_process_logs` 안에서만 쓰인다(전수 확인 완료).
2. `_make_process_logs` 함수를 통째로 지운다.
3. `generate()` 안의 `logs = _make_process_logs(rows, rng)` 줄을 지우고,
   `_write_sqlite(rows, logs, steps, sensors)` 를 `_write_sqlite(rows, steps, sensors)` 로 바꾼다.
4. `_write_sqlite` 시그니처를 `def _write_sqlite(rows, steps, sensors):` 로 바꾸고,
   `CREATE TABLE process_log (...)` 와 그 `executemany` INSERT 블록을 지운다.
5. 남은 서술 정리: 모듈 docstring 의 `process_log` 언급, `rows` 딕셔너리 주석의
   `"_truth_step": "Normal",   # process_log 를 전부 스펙 내로 유지` 2곳(`:281`·`:298`)에서
   `process_log` 부분을 뺀다(`# 심어둔 이상 없음` 정도로).
   `_make_step_history` 위의 `# step_history 용 설비/챔버/PPID (process_log 와 느슨하게 공존).`
   에서 괄호 부분을 뺀다.

- [ ] **Step 3: 더미 DB 재생성**

Run: `python data/generate_dummy.py`
Expected: 오류 없이 완료. 출력의 wafer 수·lot 평균이 이전과 같다.

- [ ] **Step 4: 나머지 데이터가 불변임을 증명한다**

```bash
python - <<'PY' > "$SNAP/after.txt"
import sqlite3, config
conn = sqlite3.connect(config.DB_PATH)
for t in ("yield", "step_history", "sensor_log"):
    for row in conn.execute(f"SELECT * FROM {t} ORDER BY 1,2,3"):
        print(t, row)
PY
diff "$SNAP/before.txt" "$SNAP/after.txt" && echo "IDENTICAL"
```

Expected: `IDENTICAL` (diff 출력 없음)

**다르면 멈춘다.** `_make_process_logs` 가 rng 의 마지막 소비자라는 전제가 깨진 것이므로,
어느 생성기가 공유 `rng` 를 쓰는지 다시 확인해야 한다.

- [ ] **Step 5: `tests/test_dummy_data.py` 에서 7개 삭제**

`test_process_log_table_exists_with_4_rows_per_wafer` ·
`test_pattern_wafer_has_single_anomaly_at_its_step` ·
`test_anomaly_equipment_is_always_the_shared_minus9` ·
`test_only_planted_pattern_wafers_have_anomalies` ·
`test_hole_case_unlabeled_low_yield_wafer_passed_etch9_in_spec` ·
`test_process_log_has_eq_chamber` · `test_control_shares_equipment_not_chamber`

모듈 docstring 도 바꾼다:

```python
"""더미 데이터 검증 — step_history·sensor_log·yield 가 데모 성립 조건을 만족하는지.

데모 성립 조건: 심어둔 챔버(ETCH9_B)는 불량 그룹 wafer 에만 있고, 대조군은 같은
설비(ETCH9)를 쓰되 챔버가 다르다 → 설비 롤업은 눌리고 챔버에서만 갈린다.
"""
```

import 도 정리한다 — `PATTERN_GROUPS` 는 지워지는 테스트만 쓰므로 빼고, `CONTROL_WAFERS` 를
넣는다:

```python
from data.generate_dummy import CONTROL_WAFERS, GROUP_WAFERS
```

- [ ] **Step 6: 불변식 2개를 새로 쓴다**

`tests/test_dummy_data.py` 에 추가:

```python
def test_planted_chamber_is_exclusive_to_the_group_wafers():
    """심은 챔버(ETCH9_B)를 거친 wafer 는 더미 전체에서 GROUP_WAFERS 뿐이다.

    옛 버전은 process_log 의 스펙 이탈로 '이상은 심은 곳에만' 을 단언했다. 파라미터가
    사라졌으므로 step_history 로 표현 가능한 형태 — 챔버 배타성 — 으로 좁혔다.
    과거 패턴 wafer 에는 애초에 step_history 신호가 없다 (데모가 타깃 7장 중
    '불량군 3장 전용' 이라고 말하는 이유). 챔버 B 를 쓰는 다른 케이스는 설비가 다르다:
    적대적 lot 은 ETCH1/2/3, 분할 lot 은 ETCH5.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT wafer_id FROM step_history "
            "WHERE eqp_id = 'ETCH9' AND ch_id = 'B'"
        ).fetchall()
    assert {r["wafer_id"] for r in rows} == set(GROUP_WAFERS)


def test_control_shares_equipment_but_not_chamber():
    """대조군은 Etch 에서 같은 설비(ETCH9)를 쓰되 챔버가 다르다.

    설비 레벨 롤업이 눌리고 챔버 레벨에서만 갈리는 것이 이 시나리오의 핵심이다.
    (옛 버전은 process_log 의 equipment_id/eq_chamber 로 같은 것을 봤다.)
    """
    ph = ",".join("?" * len(CONTROL_WAFERS))
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT eqp_id, ch_id FROM step_history "
            f"WHERE process_step = 'Etch' AND wafer_id IN ({ph})",
            CONTROL_WAFERS,
        ).fetchall()
    assert len(rows) == len(CONTROL_WAFERS)
    assert all(r["eqp_id"] == "ETCH9" for r in rows)
    assert all(r["ch_id"] != "B" for r in rows)
```

- [ ] **Step 7: 검증**

Run: `python -m pytest -q`
Expected: **137 passed** (142 − 7 + 2)

Run: `python main.py`
Expected: 결론이 `Etch 공정 ETCH9_B 편중(분리 점수 1.0, 불량군 3장 전용)이 원인 —
rf_power_steady_avg 효과크기 2.573`, 형제 7장, 대조군 78장 — `README.md` 데모 블록과 일치.

- [ ] **Step 8: 커밋**

`data/yield.db` 는 **gitignore 대상이라 커밋하지 않는다** (README 대로 재생성한다).

```bash
git add data/generate_dummy.py tests/test_dummy_data.py
git status --short          # 저장소에 임시 파일이 없는지 확인
git commit -F - <<'EOF'
refactor(stage5): 더미에서 process_log 삭제 + 불변식 재작성

_make_process_logs 는 공유 rng 의 마지막 소비자라, 지워도 step_history·sensor_log·
yield 는 바이트 단위로 그대로다 (스냅샷 diff 로 확인).

불변식 3개가 스펙 이탈로만 표현돼 있었다. step_history 는 과거 패턴 wafer 에 신호를
심지 않으므로(데모가 '3장 전용' 인 이유) 그대로 옮길 수 없다 — 챔버 배타성과
'같은 설비 다른 챔버' 로 좁혀 다시 썼다. 구멍 케이스 (가)의 '스펙 안으로 통과' 는
측정값이 사라져 후속이 없다. 그 wafer 가 지금 하는 일(저수율 무라벨이 대조군에
섞임)은 test_grouping·test_e2e 가 이미 고정한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: `yield` 테이블 DDL 계약 동결

**Files:**
- Modify: `tests/test_schema_contract.py` (헬퍼 2개 + 테스트 2개 추가)

**Interfaces:**
- Consumes: `load_internal.DDL`(`yield` 포함), 더미 DB 의 `yield` 테이블.
- Produces: 없음 (최종 Task 의 전 단계)

**배경 (구현자용):** `docs/stages.md:148-151` 이 Stage 5 작업으로 지정한 항목이다. 지금
계약 테스트는 `step_history` 만 얼린다. Stage 4 에서 더미의 `yield` 는
`defect_type TEXT NOT NULL` 인데 로더만 nullable 이라 **NULL 기록이 한동안 실패한 일이 실제로
있었다.** 두 스키마를 같은 방식으로 비교해 조용히 갈라지지 않게 한다.

현재 두 정의는 컬럼이 같다(8개: `wafer_id`·`lot_id`·`yield`·`defect_type`·`process_step`·
`date`·`root_lot_id`·`lot_type`). 따라서 `ALLOWED` 는 비어 있다.

- [ ] **Step 1: 실패를 먼저 본다 (헬퍼만 넣고 일부러 틀린 기대값으로)**

이 Task 는 "새 동작"이 아니라 "동결"이라 실패-먼저가 어색하다. 대신 **동결이 실제로
작동하는지**를 확인한다: 아래 테스트를 넣기 전에, 더미 DDL 의 `lot_type` 을 임시로
`lot_type2` 로 바꿔 DB 를 재생성하고 새 테스트가 실패하는지 본 뒤 되돌린다.
(되돌린 뒤 `python data/generate_dummy.py` 재실행을 잊지 말 것.)

- [ ] **Step 2: `tests/test_schema_contract.py` 에 헬퍼 2개 추가**

`_dummy_step_cols` 아래에 넣는다:

```python
def _internal_yield_cols() -> set[str]:
    from data import load_internal
    return _cols_from_ddl(load_internal.DDL, "yield")


def _dummy_yield_cols() -> set[str]:
    conn = sqlite3.connect(config.DB_PATH)
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(yield)")}
    finally:
        conn.close()
```

- [ ] **Step 3: 테스트 2개 추가**

파일 끝에 넣는다:

```python
def test_internal_and_dummy_yield_do_not_diverge_silently():
    """yield 스키마도 두 곳에서 갈리지 않는다 (Stage 5).

    Stage 4 에서 더미의 yield 는 defect_type NOT NULL 인데 로더만 nullable 이라
    NULL 기록이 한동안 실패했다. step_history 만 얼려 두면 이 부류가 또 숨는다.
    """
    ALLOWED: set[str] = set()      # 알려진 차이 (없는 것이 목표)
    diff = _internal_yield_cols() ^ _dummy_yield_cols()
    assert diff <= ALLOWED, (
        f"yield 스키마가 두 곳에서 갈렸다: {sorted(diff - ALLOWED)}. "
        f"의도된 차이면 ALLOWED 에 이유와 함께 추가하라."
    )


def test_dummy_db_has_exactly_the_three_tables():
    """단일 스키마 완성 (Stage 5): 더미 테이블은 yield·step_history·sensor_log 뿐이다.

    process_log 가 되살아나면 여기서 먼저 걸린다.
    """
    conn = sqlite3.connect(config.DB_PATH)
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")}
    finally:
        conn.close()
    assert names == {"yield", "step_history", "sensor_log"}
```

모듈 docstring 의 "세 정의원" 설명에 `yield` 도 얼린다는 것을 한 줄 덧붙이고,
**`sensor_log` 는 `load_internal.py` 에 대응물이 없어(사내는 FDC HTTP) 얼리지 않는다**는
사실도 적는다.

- [ ] **Step 4: 검증**

Run: `python -m pytest tests/test_schema_contract.py -q`
Expected: 5 passed (기존 3 + 신규 2)

Run: `python -m pytest -q`
Expected: **139 passed** (137 + 2)

- [ ] **Step 5: 커밋**

```bash
git add tests/test_schema_contract.py
git commit -F - <<'EOF'
test(stage5): yield DDL 계약 동결 + 테이블 집합 고정

docs/stages.md 가 Stage 5 로 지정한 항목. step_history 만 얼려 둬서 Stage 4 때
더미(defect_type NOT NULL)와 로더(nullable)가 조용히 갈렸고 NULL 기록이 한동안
실패했다. 같은 방식으로 yield 도 얼리고, 더미 테이블이 정확히 3개(단일 스키마)
임을 고정해 process_log 부활을 막는다.

sensor_log 는 load_internal 에 대응물이 없어(사내는 FDC HTTP) 얼리지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 5: 문서 정리 — 스펙 이탈 개념과 Stage 5 완료 표기

**Files:**
- Modify: `README.md`, `docs/stages.md`, `docs/internal-data-integration.md`,
  `docs/사내-데이터-변환시-할일.md`, `docs/deferred-internal-integration.md`

**Interfaces:**
- Consumes: Task 1~4 의 결과.
- Produces: 없음 (마지막 Task)

**배경 (구현자용):** 사용자가 고른 범위가 "전부 + spec 이탈 개념 정리" 다. `spec_low`·
`spec_high`·`param_value`·`in_spec` 은 이제 저장소 어디에도 **동작하는 코드로는** 없다.
문서에 남은 서술이 그것을 살아 있는 기능처럼 말하면 안 된다. 과거 plans/specs 는
역사 기록이므로 건드리지 않는다.

- [ ] **Step 1: 남은 언급을 전수 조사한다**

```bash
grep -rn "process_log\|spec_low\|spec_high\|param_value\|in_spec" \
  --include="*.md" --include="*.py" . | grep -v "docs/superpowers/"
```

나온 것을 하나씩 판단한다: **사내 스키마 설명**(`internal-data-integration.md` 의 ETL
목표 스키마 등)은 사내 원천 데이터를 말하는 것일 수 있으니 문맥을 보고 남길지 정한다.
프로토타입의 살아 있는 기능처럼 서술한 것만 고친다.

- [ ] **Step 2: `README.md` 정리**

더미 설계 절의 "옛 `process_log` 에는 `ETCH-9` 의 `rf_power` 스펙 이탈이, 사내 스키마와 같은
모양의 `step_history` 에는 …" 서술에서 **process_log 층을 걷어낸다.** 원인 신호가 이제
`step_history`(챔버·PPID)와 `sensor_log`(값) 두 층이라는 서술로 바꾼다.
도구 목록·아키텍처 설명에 레거시 도구가 남아 있으면 지운다.

- [ ] **Step 3: `docs/stages.md` 갱신**

"현재 위치" 블록의 `Stage 5 ⬜ …` 를 `Stage 5 ✅ 완료 (2026-07-29) — process_log·레거시 도구
삭제 = 단일 스키마 완성` 으로 바꾼다. `### Stage 5 — 삭제` 절은 **삭제 전 확인 사항**에서
**한 것**으로 다시 쓴다: 대체 매핑 확인 결과(기능 유실 없음), 불변식 재작성 결정과 그 근거
(과거 패턴 wafer 에 step_history 신호가 없다), `yield` DDL 동결 완료, `sensor_log` 는
대응물이 없어 미룸.

- [ ] **Step 4: 나머지 문서 3종**

- `docs/사내-데이터-변환시-할일.md`: §2 의 "목표 스키마: `yield`·`process_log` 2테이블" 을
  실제(`yield`·`step_history`)로 고친다. `spec_low/spec_high` NULL 완화 항목은 이제
  프로토타입에 그 컬럼이 없으므로 취소선 + 사유를 단다.
  §0 표의 "spec NULL 크래시 3건" 은 역사 기록이므로 그대로 둔다.
- `docs/internal-data-integration.md`: §2 의 목표 스키마 서술을 같은 이유로 고친다.
- `docs/deferred-internal-integration.md`: `process_log` 를 언급하는 항목이 있으면
  해당 코드가 사라졌음을 표기한다.

- [ ] **Step 5: 검증**

Run: `python -m pytest -q`
Expected: **139 passed** (문서만 고쳤으므로 변화 없음)

Run: Step 1 의 grep 재실행
Expected: 남은 것이 **과거 plans/specs 와 사내 원천 스키마 설명뿐**임을 눈으로 확인

- [ ] **Step 6: 커밋**

```bash
git add README.md docs/
git commit -F - <<'EOF'
docs(stage5): 스펙 이탈 개념 정리 + Stage 5 완료 표기

spec_low/spec_high/param_value/in_spec 은 이제 동작하는 코드로 존재하지 않는다.
프로토타입의 살아 있는 기능처럼 서술한 곳을 고치고, 원인 신호가 step_history(챔버·
PPID)와 sensor_log(값) 두 층이라는 현재 구조로 다시 썼다. 과거 plans/specs 는
역사 기록이라 건드리지 않았다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## 완료 확인 (전 Task 종료 후)

- [ ] `python -m pytest -q` → **139 passed**
- [ ] `python main.py` 출력이 `README.md` 데모 블록과 일치 (결론·형제 7장·대조군 78장)
- [ ] 더미 DB 테이블이 정확히 `yield`·`step_history`·`sensor_log` 3개
- [ ] `git log --oneline main..HEAD` → spec 1 + 플랜 1 + 구현 5 = 커밋 7개
- [ ] `git status --short` 가 비어 있다 (스냅샷 임시 파일이 저장소에 안 남았다)
- [ ] 병합하지 않는다. 사용자에게 리뷰/병합 여부를 묻는다.
