# 2단 센서 비교 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

작성일: 2026-07-25
spec: `docs/superpowers/specs/2026-07-25-sensor-comparison-design.md`

**Goal:** 1단이 지목한 (스텝, 챔버)에 대해 타깃/대조군의 센서 통계값 분포를 비교해, 효과크기 top-K 후보를 내는 2단을 붙인다.

**Architecture:** 가져오기(`SensorStore`, EDS 와 같은 local↔http 교체 패턴)와 계산(`sensor_compare`)을 파일로 분리한다. 캐시 DB 는 만들지 않는다. 반환은 집계값만 top-K 로 절단하고, 재현을 위해 재-fetch 키를 함께 싣는다.

**Tech Stack:** Python 3.11, sqlite3, pytest, numpy(효과크기), LangChain `@tool`.

## Global Constraints

- **기존 테스트 green 유지.** 각 Task 종료 시 `python -m pytest -q` 전체 통과. 현재 기준선 = **140 passed**.
- **난수열 보존.** `generate_dummy.py` 에서 기존 난수 소비 순서를 깨지 않는다. 센서는 **신규 테이블**이고 전용 rng(`np.random.default_rng(SEED + 2)`)로 만든다 — 기존 `rng`·`sh_rng` 를 건드리지 않는다.
- **기존 wafer 를 변형하지 않는다.** `sensor_log` 는 새 테이블이라 기존 테이블은 손대지 않는다.
- **임의 수치 금지.** p-value 컷을 만들지 않는다. 효과크기 랭킹 + 원시 표본 수를 함께 싣는다.
- **wafer 별 원본값을 tool 반환에 싣지 않는다.** 반환 크기는 fetch 량과 무관하게 유계여야 한다.
- 주석·docstring·테스트 이름은 기존 코드처럼 한국어 유지.
- 커밋 메시지는 기존 스타일(`feat:`/`fix:`/`test:`/`docs:` + 한국어 요약) + `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Windows 환경이라 테스트·실행은 `PYTHONUTF8=1` 을 앞에 붙인다.

---

## File Structure

- `data/generate_dummy.py` (수정) — `sensor_log` 테이블·행 생성 (케이스 4종)
- `tests/test_sensor_dummy.py` (신규) — 심은 케이스가 의도대로인지
- `config.py` (수정) — `SENSOR_MODE`, `SENSOR_TOP_K`, `SENSOR_MIN_SAMPLE`
- `tools/sensor_store.py` (신규) — 인터페이스 + local/http, `get_store()`
- `tests/test_sensor_store.py` (신규)
- `tools/sensor_compare.py` (신규) — 집계·효과크기·top-K 절단·재-fetch 키
- `tests/test_sensor_compare.py` (신규)
- `tools/agent_tools.py` (수정) — `compare_sensor_distribution` tool 등록
- `tests/test_agent_tools.py` (수정) — 도구 목록

---

### Task 1: 더미 `sensor_log` + 케이스 4종

이후 모든 Task 가 이 데이터를 대상으로 테스트하므로 먼저 만든다.

**Files:**
- Modify: `data/generate_dummy.py`
- Create: `tests/test_sensor_dummy.py`
- Regenerate: `data/yield.db`

**Interfaces:**
- Produces: 모듈 상수 `SENSOR_STEP`(`"Etch"`), `SENSOR_REAL`(진짜 원인 센서명), `SENSOR_VAR_ONLY`(분산만 이동), `SENSOR_DECOYS`(미끼), `SENSOR_COLLINEAR`(공선성 쌍), `SENSOR_MISSING_WAFER`. 이후 Task 의 테스트가 이 이름을 import 한다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_sensor_dummy.py` 신규:

```python
"""더미 sensor_log — 심어둔 케이스 4종이 의도대로인지.

센서 값은 트레이스가 아니라 wafer 1장의 구간 통계값이고, 구간·통계 종류는
센서 이름에 들어 있다(rf_power_steady_avg). 그래서 ..._avg 와 ..._std 는
서로 독립된 센서로 취급된다 — '분산만 이동' 케이스가 별도 처리 없이 잡히는 이유다.
"""

import sqlite3
import statistics

import config
from data.generate_dummy import (GROUP_WAFERS, CONTROL_WAFERS, SENSOR_COLLINEAR,
                                 SENSOR_DECOYS, SENSOR_MISSING_WAFER, SENSOR_REAL,
                                 SENSOR_STEP, SENSOR_VAR_ONLY)


def _vals(sensor_name, wafer_ids):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        ph = ",".join("?" * len(wafer_ids))
        rows = conn.execute(
            f"SELECT value FROM sensor_log WHERE sensor_name = ? "
            f"AND process_step = ? AND wafer_id IN ({ph})",
            [sensor_name, SENSOR_STEP, *wafer_ids]).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def test_sensor_log_table_exists_with_expected_columns():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sensor_log)")}
    finally:
        conn.close()
    assert cols == {"wafer_id", "process_step", "sensor_name", "value", "tkout_time"}


def test_case1_variance_only_shift_keeps_mean_but_moves_std():
    """평균은 같고 분산만 이동 — avg 만 보는 사고의 사각지대."""
    t_avg = _vals(f"{SENSOR_VAR_ONLY}_avg", GROUP_WAFERS)
    c_avg = _vals(f"{SENSOR_VAR_ONLY}_avg", CONTROL_WAFERS)
    t_std = _vals(f"{SENSOR_VAR_ONLY}_std", GROUP_WAFERS)
    c_std = _vals(f"{SENSOR_VAR_ONLY}_std", CONTROL_WAFERS)
    assert abs(statistics.mean(t_avg) - statistics.mean(c_avg)) < 1.0   # 평균은 사실상 동일
    assert statistics.mean(t_std) > statistics.mean(c_std) * 1.5        # 분산은 확실히 이동


def test_case2_real_cause_separates_more_than_decoys():
    """진짜 원인 센서가 미끼보다 크게 갈린다 (순위가 뒤집히면 안 된다)."""
    real_gap = abs(statistics.mean(_vals(f"{SENSOR_REAL}_avg", GROUP_WAFERS))
                   - statistics.mean(_vals(f"{SENSOR_REAL}_avg", CONTROL_WAFERS)))
    for decoy in SENSOR_DECOYS:
        gap = abs(statistics.mean(_vals(f"{decoy}_avg", GROUP_WAFERS))
                  - statistics.mean(_vals(f"{decoy}_avg", CONTROL_WAFERS)))
        assert gap < real_gap


def test_case3_collinear_sensors_move_together():
    """연동된 센서 둘이 함께 이동한다 — 순위만으로는 못 가리는 상황."""
    a, b = SENSOR_COLLINEAR
    for name in (a, b):
        t = statistics.mean(_vals(f"{name}_avg", GROUP_WAFERS))
        c = statistics.mean(_vals(f"{name}_avg", CONTROL_WAFERS))
        assert abs(t - c) > 0


def test_case4_missing_sensor_rows():
    """일부 wafer 는 센서 행이 아예 없다 — 결측이 분모를 오염시키면 안 된다."""
    assert _vals(f"{SENSOR_REAL}_avg", [SENSOR_MISSING_WAFER]) == []
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_sensor_dummy.py -q`
Expected: FAIL — `ImportError: cannot import name 'SENSOR_REAL' from 'data.generate_dummy'`.

- [ ] **Step 3: 상수 추가**

`data/generate_dummy.py` 의 분할 lot 블록(`SPLIT_WAFERS = ...` 줄) 바로 아래에 추가:

```python
# ---------------------------------------------------------------- 센서 (2단 깔때기)
# 트레이스가 아니라 **wafer 1장의 구간 통계값**이다. 구간·통계 종류는 센서 이름에
# 들어 있다(rf_power_steady_avg) — 사내 FDC 추출물 형태.
# 그래서 ..._avg 와 ..._std 가 서로 독립된 센서가 되고, '평균은 같은데 분산만 이동'
# 케이스가 비교 로직의 별도 처리 없이 후보에 오른다.
SENSOR_STEP = "Etch"                    # 1단이 지목하는 스텝 (ETCH9_B 가 여기 있다)
SENSOR_REAL = "rf_power_steady"         # 진짜 원인 — 불량군에서 평균 이동
SENSOR_VAR_ONLY = "gas_flow_steady"     # 케이스 1: 평균 동일, 분산만 이동
SENSOR_DECOYS = ["chuck_temp_steady", "he_leak_steady"]   # 케이스 2: 우연히 유의한 미끼
SENSOR_COLLINEAR = ("pressure_steady", "throttle_steady") # 케이스 3: 연동되어 함께 이동
SENSOR_QUIET = ["endpoint_steady", "bias_steady"]         # 어느 그룹에서도 안 갈림
SENSOR_STATS = ("avg", "std")

# 케이스 4: 센서 행이 아예 없는 wafer (결측이 분모를 오염시키는지)
# ⚠️ 대조군(CONTROL_WAFERS)에서 고르면 안 된다 — 대조군 3장 중 1장이 빠지면 표본이 2장이
#    되어 주 비교가 불안정해진다. 어느 그룹에도 안 속하는 W2406_07 을 쓴다.
SENSOR_MISSING_WAFER = UNLABELED_LOW_WAFER
```

- [ ] **Step 4: 센서 행 생성 함수 추가**

`data/generate_dummy.py` 의 `_make_split_lot_steps` 함수 바로 아래에 추가:

```python
def _make_sensor_log(rows):
    """wafer×스텝×센서 통계값 (전용 rng — 기존 난수열을 건드리지 않는다).

    지목 스텝(Etch)에만 심는다. 다른 스텝은 2단이 볼 일이 없다.
    불량군(GROUP_WAFERS)에만 신호를 넣고 나머지는 공통 분포를 쓴다.
    """
    sen_rng = np.random.default_rng(SEED + 2)
    all_sensors = ([SENSOR_REAL, SENSOR_VAR_ONLY, *SENSOR_DECOYS,
                    *SENSOR_COLLINEAR, *SENSOR_QUIET])
    out = []
    for r in rows:
        wid = r["wafer_id"]
        if wid == SENSOR_MISSING_WAFER:
            continue                       # 케이스 4: 이 wafer 는 센서 행이 없다
        bad = wid in GROUP_WAFERS
        for name in all_sensors:
            for stat in SENSOR_STATS:
                base, spread = 100.0, 2.0
                if stat == "std":
                    base, spread = 5.0, 0.5

                if name == SENSOR_REAL and stat == "avg" and bad:
                    base += 12.0                      # 진짜 원인: 평균이 크게 이동
                elif name == SENSOR_VAR_ONLY and stat == "std" and bad:
                    base *= 2.2                       # 케이스 1: 분산만 이동
                elif name in SENSOR_DECOYS and stat == "avg" and bad:
                    base += 3.0                       # 케이스 2: 진짜보다 작게 이동
                elif name in SENSOR_COLLINEAR and stat == "avg" and bad:
                    base += 6.0                       # 케이스 3: 둘이 같은 크기로 이동

                out.append({
                    "wafer_id": wid,
                    "process_step": SENSOR_STEP,
                    "sensor_name": f"{name}_{stat}",
                    "value": round(float(sen_rng.normal(base, spread)), 3),
                    "tkout_time": r["date"] + " 10:00:00",
                })
    return out
```

- [ ] **Step 5: 테이블 생성·적재 배선**

`data/generate_dummy.py` 의 `generate()` 에서 steps 조립 줄 아래에 추가하고 `_write_sqlite` 호출을 바꾼다:

```python
    sensors = _make_sensor_log(rows)
    _write_sqlite(rows, logs, steps, sensors)
```

`_write_sqlite` 의 시그니처와 끝부분(`conn.commit()` 직전)을 바꾼다:

```python
def _write_sqlite(rows, logs, steps, sensors):
```

```python
    conn.execute("""
        CREATE TABLE sensor_log (
            wafer_id     TEXT NOT NULL,
            process_step TEXT NOT NULL,
            sensor_name  TEXT NOT NULL,
            value        REAL NOT NULL,
            tkout_time   TEXT
        )
    """)
    conn.execute("CREATE INDEX idx_sensor_step ON sensor_log(process_step, wafer_id)")
    conn.executemany(
        """INSERT INTO sensor_log VALUES
           (:wafer_id, :process_step, :sensor_name, :value, :tkout_time)""", sensors)
    conn.commit()
```

- [ ] **Step 6: 더미 재생성 + 통과 확인**

Run: `PYTHONUTF8=1 python data/generate_dummy.py && PYTHONUTF8=1 python -m pytest -q`
Expected: 신규 5개 PASS, 전체 **145 passed**(기준선 140 + 5). 기존이 깨지면 전용 rng 를 안 쓴 것이니 되돌린다.

- [ ] **Step 7: 커밋**

```
test: 더미 sensor_log + 케이스 4종 (분산만 이동·미끼·공선성·결측)

센서는 트레이스가 아니라 wafer 1장의 구간 통계값이고 구간·통계는 이름에 들어간다.
그래서 ..._avg 와 ..._std 가 독립 센서가 되고 '분산만 이동' 이 별도 처리 없이
후보에 오른다. 전용 rng(SEED+2)라 기존 난수열은 불변.
```

---

### Task 2: `SensorStore` (가져오기 계층)

**Files:**
- Modify: `config.py`
- Create: `tools/sensor_store.py`
- Create: `tests/test_sensor_store.py`

**Interfaces:**
- Produces: `get_store() -> SensorStore`, `SensorStore.fetch(process_step: str, wafer_ids: list[str]) -> list[dict]` — 원소는 `{wafer_id, process_step, sensor_name, value, tkout_time}`. Task 3 이 이것만 호출한다.

- [ ] **Step 1: `config.py` 에 설정 추가**

`LEGACY_TOOLS_ENABLED` 줄 아래에 추가:

```python
# 센서(2단): "local" = yield.db 의 sensor_log, "http" = 사내 FDC
SENSOR_MODE = os.getenv("SENSOR_MODE", "local")
SENSOR_HTTP_URL = os.getenv("SENSOR_HTTP_URL", "https://<사내-fdc-호스트>/sensor")
# 2단 반환 절단 — fetch 량과 무관하게 유계로 만든다 (후보≠결론)
SENSOR_TOP_K = int(os.getenv("SENSOR_TOP_K", "10"))
# 한 그룹의 센서 표본이 이 미만이면 비교하지 않는다 (표본 2장짜리 효과크기는 허상)
SENSOR_MIN_SAMPLE = int(os.getenv("SENSOR_MIN_SAMPLE", "3"))
```

- [ ] **Step 2: 실패 테스트 작성**

`tests/test_sensor_store.py` 신규:

```python
"""SensorStore — 가져오기 계층 (EDS 와 같은 local↔http 교체 패턴)."""

import pytest

import config
from data.generate_dummy import GROUP_WAFERS, SENSOR_REAL, SENSOR_STEP
from tools import sensor_store as ss


def test_local_store_fetches_requested_wafers_only():
    rows = ss.LocalSensorStore().fetch(SENSOR_STEP, GROUP_WAFERS)
    assert rows
    assert {r["wafer_id"] for r in rows} <= set(GROUP_WAFERS)
    assert all(r["process_step"] == SENSOR_STEP for r in rows)
    assert {"wafer_id", "process_step", "sensor_name", "value", "tkout_time"} == set(rows[0])
    assert any(r["sensor_name"] == f"{SENSOR_REAL}_avg" for r in rows)


def test_local_store_empty_wafer_list():
    assert ss.LocalSensorStore().fetch(SENSOR_STEP, []) == []


def test_get_store_honors_mode(monkeypatch):
    monkeypatch.setattr(config, "SENSOR_MODE", "local")
    assert isinstance(ss.get_store(), ss.LocalSensorStore)
    monkeypatch.setattr(config, "SENSOR_MODE", "nope")
    with pytest.raises(ValueError, match="SENSOR_MODE"):
        ss.get_store()
```

- [ ] **Step 3: 실패 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_sensor_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.sensor_store'`.

- [ ] **Step 4: 구현**

`tools/sensor_store.py` 신규:

```python
"""센서 통계값 가져오기.

인터페이스 고정: (스텝, wafer 목록) 입력 -> 센서 통계값 행 반환.
내부 구현만 데모(로컬 sqlite) / 운영(사내 FDC HTTP) 으로 교체한다 — EDS 와 같은 패턴.

⚠️ 값은 트레이스가 아니라 **wafer 1장의 구간 통계값**이다. 구간·통계 종류는 센서
   이름에 들어 있다(rf_power_steady_avg). 이 계층은 이름을 해석하지 않는다.

캐시 DB 는 두지 않는다 — 분석당 수천~수만 행이라 캐시의 근거(트레이스 규모)가
없고, 무효화·수명·용량 정책이라는 새 문제만 생긴다. 사내 조회가 실제로 느린 것이
확인되면 이 계층 **뒤에** 붙인다 (호출부 계약은 그대로다).
"""

import sqlite3
from abc import ABC, abstractmethod

import config

COLUMNS = ("wafer_id", "process_step", "sensor_name", "value", "tkout_time")


class SensorStore(ABC):
    """센서 조회 인터페이스. 2단 계산은 이 타입에만 의존한다."""

    @abstractmethod
    def fetch(self, process_step: str, wafer_ids: list[str]) -> list[dict]:
        """지목된 스텝에서 주어진 wafer 들의 센서 통계값 전부.

        fetch 단위가 (스텝 × wafer 전원)인 이유: 1단이 챔버를 지목한 근거는
        "대조군은 그 챔버를 안 거쳤다" 이므로, 챔버로 좁혀 뽑으면 대조군 표본이
        0 이 되어 비교가 성립하지 않는다.
        """
        ...


class LocalSensorStore(SensorStore):
    """데모용. yield.db 의 sensor_log 에서 조회."""

    def fetch(self, process_step: str, wafer_ids: list[str]) -> list[dict]:
        if not wafer_ids:
            return []
        ph = ",".join("?" * len(wafer_ids))
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"SELECT {', '.join(COLUMNS)} FROM sensor_log "
                f"WHERE process_step = ? AND wafer_id IN ({ph})",
                [process_step, *wafer_ids]).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]


class HttpSensorStore(SensorStore):
    """운영용. 사내 FDC 호출. 응답 스키마는 실측 후 매핑을 맞춘다."""

    def fetch(self, process_step: str, wafer_ids: list[str]) -> list[dict]:
        import requests

        if not wafer_ids:
            return []
        resp = requests.post(
            config.SENSOR_HTTP_URL,
            json={"process_step": process_step, "wafer_ids": wafer_ids},
            verify=config.EDS_HTTP_VERIFY,      # 같은 사내 인증서 정책
            timeout=30,
        )
        resp.raise_for_status()
        # ⚠️ 사내 응답 스키마 미확정 — 실측 후 이 매핑을 맞춘다 (EDS 에서 같은 일이 있었다)
        return [{k: r.get(k) for k in COLUMNS} for r in resp.json().get("rows", [])]


def get_store() -> SensorStore:
    """config.SENSOR_MODE 에 따라 구현 선택."""
    if config.SENSOR_MODE == "local":
        return LocalSensorStore()
    if config.SENSOR_MODE == "http":
        return HttpSensorStore()
    raise ValueError(f"알 수 없는 SENSOR_MODE: {config.SENSOR_MODE}")
```

- [ ] **Step 5: 통과 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_sensor_store.py -q` → 3 PASS

- [ ] **Step 6: 커밋**

```
feat(sensor): SensorStore — 센서 통계값 가져오기 계층

EDS 와 같은 local↔http 교체 패턴. 캐시 DB 는 두지 않는다 — 값이 트레이스가
아니라 wafer 구간 통계값이라 캐시의 근거가 없고, 무효화·수명 정책이라는 새
문제만 생긴다. 필요가 확인되면 이 계층 뒤에 붙인다.
```

---

### Task 3: `sensor_compare` (계산 계층)

**Files:**
- Create: `tools/sensor_compare.py`
- Create: `tests/test_sensor_compare.py`

**Interfaces:**
- Consumes: `sensor_store.get_store()` (Task 2), 더미 상수 (Task 1).
- Produces: `compare_sensor_distribution(process_step: str, group_ids: list[str], control_ids: list[str]) -> dict` — 키는 `status`, `candidates`, `truncated`, `refetch_key`, `note`. Task 4 의 tool 래퍼가 이것을 그대로 반환한다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_sensor_compare.py` 신규:

```python
"""2단 센서 비교 — 효과크기 랭킹, 집계값만 반환, 재현 키."""

import config
from data.generate_dummy import (CONTROL_WAFERS, GROUP_WAFERS, SENSOR_REAL,
                                 SENSOR_STEP, SENSOR_VAR_ONLY)
from tools import sensor_compare as sc


def _run():
    return sc.compare_sensor_distribution(SENSOR_STEP, GROUP_WAFERS, CONTROL_WAFERS)


def test_real_cause_sensor_ranks_first():
    res = _run()
    assert res["status"] == "ok"
    assert res["candidates"][0]["sensor_name"] == f"{SENSOR_REAL}_avg"


def test_variance_only_shift_is_a_candidate():
    """평균은 같고 분산만 이동한 센서도 후보에 오른다.

    ..._std 가 독립된 센서 이름이라 별도 처리 없이 잡힌다 — 이 설계의 핵심 이득.
    """
    names = [c["sensor_name"] for c in _run()["candidates"]]
    assert f"{SENSOR_VAR_ONLY}_std" in names
    assert f"{SENSOR_VAR_ONLY}_avg" not in names[:3]      # 평균은 안 갈린다


def test_return_is_bounded_and_carries_raw_counts():
    """반환은 top-K 로 유계이고, wafer 별 원본값을 싣지 않는다."""
    res = _run()
    assert len(res["candidates"]) <= config.SENSOR_TOP_K
    c = res["candidates"][0]
    assert set(c) == {"sensor_name", "effect_size", "target_mean", "control_mean",
                      "target_std", "control_std", "n_target", "n_control"}
    assert c["n_target"] == len(GROUP_WAFERS)


def test_note_says_candidates_are_not_conclusions():
    assert "후보" in _run()["note"]


def test_refetch_key_reproduces_the_same_numbers():
    """재-fetch 키만으로 같은 집계값을 다시 만들 수 있어야 한다 (감사 추적)."""
    res = _run()
    k = res["refetch_key"]
    again = sc.compare_sensor_distribution(
        k["process_step"], k["target_wafers"], k["control_wafers"])
    assert again["candidates"] == res["candidates"]


def test_quiet_sensors_do_not_reach_the_top():
    """어느 그룹에서도 안 갈리는 센서는 상위에 오지 않는다."""
    from data.generate_dummy import SENSOR_QUIET

    top3 = [c["sensor_name"] for c in _run()["candidates"][:3]]
    assert not any(q in name for q in SENSOR_QUIET for name in top3)


def test_two_normal_groups_do_not_separate():
    """같은 분포에서 나온 두 그룹은 큰 효과크기를 내지 않는다.

    정상 wafer 끼리 갈라 비교한다. 우연한 분리가 없지는 않으므로(센서 수백 개면
    당연하다) 상태가 아니라 **크기**를 본다 — 진짜 원인의 효과크기보다 확실히 작아야 한다.
    """
    a = ["W2401_001", "W2401_002", "W2401_003", "W2401_004"]
    b = ["W2401_006", "W2401_007", "W2401_008", "W2401_009"]
    res = sc.compare_sensor_distribution(SENSOR_STEP, a, b)
    real = _run()["candidates"][0]["effect_size"]
    if res["candidates"]:
        assert res["candidates"][0]["effect_size"] < real


def test_insufficient_sample_is_reported_not_computed():
    res = sc.compare_sensor_distribution(SENSOR_STEP, GROUP_WAFERS[:1], CONTROL_WAFERS)
    assert res["status"] == "insufficient_sample"
    assert res["candidates"] == []
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_sensor_compare.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.sensor_compare'`.

- [ ] **Step 3: 구현**

`tools/sensor_compare.py` 신규:

```python
"""2단 센서 비교 (결정론적). 1단이 지목한 스텝에서 타깃/대조군의 분포를 가른다.

설계 원칙 (1단 commonality 와 같다):
- **p-value 를 쓰지 않는다.** 스텝당 센서가 수백 개라 α=0.05 면 우연히 수십 개가
  유의하다. 효과크기 랭킹 + 원시 표본 수를 실어 "후보이지 결론이 아님" 이 드러나게 한다.
- **wafer 별 원본값을 반환하지 않는다.** 반환은 top-K 절단으로 유계다.
- **결측을 신호로 만들지 않는다.** 센서 행이 없는 wafer 는 그 센서의 분모에서 빠진다.
"""

import statistics

import config
from tools.sensor_store import get_store


def _effect_size(t: list[float], c: list[float]) -> float:
    """표준화 평균차(Cohen's d). 표본이 작으면 커지므로 n 을 함께 실어 보낸다."""
    if len(t) < 2 or len(c) < 2:
        return 0.0
    st, sc_ = statistics.stdev(t), statistics.stdev(c)
    pooled = (((len(t) - 1) * st ** 2 + (len(c) - 1) * sc_ ** 2)
              / (len(t) + len(c) - 2)) ** 0.5
    if pooled == 0:
        return 0.0
    return abs(statistics.mean(t) - statistics.mean(c)) / pooled


def compare_sensor_distribution(process_step: str, group_ids: list[str],
                                control_ids: list[str]) -> dict:
    """지목된 스텝에서 두 그룹의 센서 분포를 비교해 효과크기 top-K 후보를 낸다.

    status:
      - "insufficient_sample" : 한쪽 그룹의 표본이 비교에 못 미침
      - "fetch_failed"        : 원본 조회 실패 (결과 없음과 구분한다)
      - "no_signal"           : 계산은 됐으나 갈리는 센서가 없음
      - "ok"
    """
    targets = sorted(set(group_ids or []))
    controls = sorted(set(control_ids or []) - set(targets))

    base = {"candidates": [], "truncated": 0,
            "refetch_key": {"process_step": process_step,
                            "target_wafers": targets, "control_wafers": controls,
                            "sensors": [], "store_mode": config.SENSOR_MODE}}

    if len(targets) < config.SENSOR_MIN_SAMPLE or len(controls) < config.SENSOR_MIN_SAMPLE:
        return {**base, "status": "insufficient_sample",
                "note": (f"타깃 {len(targets)}장 / 대조군 {len(controls)}장 — "
                         f"최소 {config.SENSOR_MIN_SAMPLE}장 미만이라 비교하지 않는다. "
                         f"표본 2장짜리 효과크기는 허상이다.")}

    try:
        rows = get_store().fetch(process_step, targets + controls)
    except Exception as e:                       # 조회 실패를 '결과 없음' 으로 오해하지 않게
        return {**base, "status": "fetch_failed",
                "note": f"센서 조회 실패: {type(e).__name__}: {e}"}

    tset = set(targets)
    by_sensor: dict[str, tuple[list, list]] = {}
    for r in rows:
        t_vals, c_vals = by_sensor.setdefault(r["sensor_name"], ([], []))
        (t_vals if r["wafer_id"] in tset else c_vals).append(r["value"])

    candidates = []
    for name, (t_vals, c_vals) in by_sensor.items():
        if len(t_vals) < 2 or len(c_vals) < 2:   # 결측으로 분모가 무너진 센서는 건너뛴다
            continue
        d = _effect_size(t_vals, c_vals)
        if d <= 0:
            continue
        candidates.append({
            "sensor_name": name,
            "effect_size": round(d, 3),
            "target_mean": round(statistics.mean(t_vals), 3),
            "control_mean": round(statistics.mean(c_vals), 3),
            "target_std": round(statistics.stdev(t_vals), 3),
            "control_std": round(statistics.stdev(c_vals), 3),
            "n_target": len(t_vals), "n_control": len(c_vals),
        })

    candidates.sort(key=lambda r: (-r["effect_size"], r["sensor_name"]))
    truncated = max(0, len(candidates) - config.SENSOR_TOP_K)
    candidates = candidates[:config.SENSOR_TOP_K]

    base["refetch_key"]["sensors"] = [c["sensor_name"] for c in candidates]
    if not candidates:
        return {**base, "status": "no_signal",
                "note": ("갈리는 센서가 없다. 1단이 지목한 챔버가 센서로는 설명되지 "
                         "않는다는 뜻이며, 원인 없음이 아니다.")}
    return {**base, "candidates": candidates, "truncated": truncated, "status": "ok",
            "note": ("후보는 결론이 아니다. 스텝당 센서가 수백 개라 우연한 분리가 흔하므로 "
                     "표본 수(n_target/n_control)를 반드시 함께 판단하라. "
                     "연동된 센서는 함께 움직이므로 순위만으로 원인을 가릴 수 없다.")}
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_sensor_compare.py -q`
Expected: PASS. 실패하면 **테스트가 아니라 더미 신호 세기를 의심한다** — Task 1 의 `base += 12.0`(진짜) vs `+= 3.0`(미끼) 간격이 충분한지 본다.

- [ ] **Step 5: 커밋**

```
feat(sensor): 2단 비교 — 효과크기 랭킹 + top-K 절단 + 재-fetch 키

p-value 를 쓰지 않는다(센서 수백 개라 다중비교로 유의성 주장 불가). 효과크기
랭킹에 원시 표본 수를 실어 후보≠결론이 드러나게 한다. wafer 별 원본값은 반환에
싣지 않고, findings 에 남는 재-fetch 키로 재현한다.
```

---

### Task 4: tool 등록

**Files:**
- Modify: `tools/agent_tools.py`
- Modify: `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: `sensor_compare.compare_sensor_distribution` (Task 3).

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_agent_tools.py` 의 `test_tool_names` 안 집합에 `"compare_sensor_distribution"` 을 추가하고, 파일 끝에 추가:

```python
def test_compare_sensor_distribution_tool_invokes():
    from data.generate_dummy import CONTROL_WAFERS, GROUP_WAFERS, SENSOR_REAL, SENSOR_STEP

    res = at.TOOLS_BY_NAME["compare_sensor_distribution"].invoke({
        "process_step": SENSOR_STEP,
        "group_ids": GROUP_WAFERS, "control_ids": CONTROL_WAFERS,
    })
    assert res["status"] == "ok"
    assert res["candidates"][0]["sensor_name"] == f"{SENSOR_REAL}_avg"
    assert "refetch_key" in res
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_agent_tools.py -q`
Expected: FAIL — `KeyError: 'compare_sensor_distribution'`.

- [ ] **Step 3: 구현**

`tools/agent_tools.py` 의 `finalize` 정의 위에 추가:

```python
@tool
def compare_sensor_distribution(process_step: str, group_ids: list[str],
                                control_ids: list[str], reason: str = "") -> dict:
    """가설 도구(hyp_*)가 지목한 공정 스텝에서 두 그룹의 센서 통계값 분포를 비교한다.
    효과크기가 큰 센서 top-K 를 낸다 — 어느 챔버인지까지 좁힌 뒤 '왜' 를 보는 2단이다.
    후보는 결론이 아니다: 표본 수(n_target/n_control)를 함께 보고 판단하라.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return sc.compare_sensor_distribution(process_step, group_ids, control_ids)
```

파일 상단 import 에 추가:

```python
from tools import sensor_compare as sc
```

`_BASE_TOOLS` 를 교체 (2단은 레거시가 아니므로 base 에 둔다):

```python
_BASE_TOOLS = [get_wafer, search_similar, aggregate_defects, compare_sensor_distribution]
```

- [ ] **Step 4: 전체 회귀**

Run: `PYTHONUTF8=1 python -m pytest -q`
Expected: **157 passed.** 내역 — 기준선 140, Task 1 +5, Task 2 +3, Task 3 +8, Task 4 +1(`test_tool_names` 는 수정이라 ±0). 수가 다르면 멈추고 어느 테스트가 빠졌는지 확인한다.

- [ ] **Step 5: 데모 확인**

Run: `PYTHONUTF8=1 python main.py`
확인할 것: 결론이 여전히 `ETCH9_B` 인지. mock LLM 은 각본이 고정이라 2단을 부르지 않으므로 **출력이 그대로여야 한다.** 바뀌면 도구 등록이 각본에 영향을 준 것이니 조사한다.

- [ ] **Step 6: 커밋**

```
feat: compare_sensor_distribution 을 LLM 도구로 등록

1단(hyp_*)이 챔버를 지목한 뒤 '왜' 를 보는 2단. 레거시가 아니므로 base 도구에
둔다. mock 각본은 건드리지 않아 데모 출력은 불변.
```

---

### Task 5: 문서 반영

**Files:**
- Modify: `README.md`, `docs/stages.md`

- [ ] **Step 1: README "분석 루프" 절에 2단 추가**

`hyp_ppid_commonality` 설명 아래에 추가:

```markdown
- **compare_sensor_distribution** (2단): 1단이 지목한 스텝에서 두 그룹의 센서 통계값
  분포를 비교해 효과크기 top-K 를 냅니다. 1단이 "어느 챔버" 라면 2단은 "왜" 입니다.
  센서 값은 트레이스가 아니라 wafer 1장의 구간 통계값이며, 구간·통계 종류가 센서
  이름에 들어 있습니다(`rf_power_steady_avg`).
```

- [ ] **Step 2: "한계와 다음 단계" 의 2단 부재 문장을 교체**

기존의 "센서 파라미터 비교(2단)가 붙어야 완성됩니다" 문장을 지우고:

```markdown
- 2단 센서 비교는 **그룹 대조**(같은 스텝의 타깃 vs 대조군)만 합니다. 원인이 전 구간에
  걸리는 경우(PM·부품 교체)는 시간 대조가 필요하며 아직 없습니다.
```

- [ ] **Step 3: `docs/stages.md` 의 Stage 3 을 완료로 갱신** — 구현 커밋과 남은 것(시간 대조)을 적는다.

- [ ] **Step 4: 커밋** — `docs: 2단 센서 비교 반영 (README·stages)`

---

## 완료 기준

1. 1단이 지목한 스텝에 대해 2단이 효과크기 top-K 후보를 낸다.
2. 반환에 wafer 별 원본값이 없고 크기가 `SENSOR_TOP_K` 로 유계다.
3. 재-fetch 키만으로 같은 집계값이 재현된다 (테스트로 확인).
4. 더미 케이스 4종이 의도대로 — 특히 **분산만 이동**이 후보에 오르고 **2단 조용함**이 `no_signal` 로 나온다.
5. `SENSOR_MODE=http` 로 바꿔도 호출부 코드가 그대로다.
6. 전체 회귀 green (157 passed). `python main.py` 출력 불변.
