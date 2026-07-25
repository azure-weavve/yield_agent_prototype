# root_lot 기반 대조군 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

작성일: 2026-07-25
spec: `docs/superpowers/specs/2026-07-25-root-lot-control-group-design.md`

**Goal:** 대조군을 "타깃과 같은 root_lot 의 비타깃 wafer 전원"으로 재정의해, `defect_type` 라벨이 없는 사내 실데이터에서도 대조군이 만들어지게 한다.

**Architecture:** 판정(수율·라벨·lot_type 필터)을 대조군 선정에서 걷어내고, 걸러내던 정보를 `yield_summary` 로 실어 리포트까지 보낸다. 범위는 `lot_id` 에서 `root_lot_id` 로 넓히고 1/2단계 확장 개념을 없앤다. 더미에 분할 lot(root_lot 하나에 lot 여럿) 케이스를 심어 이 변경의 효과를 테스트로 드러낸다.

**Tech Stack:** Python 3.11, sqlite3, pytest, numpy/hnswlib(더미 생성), LangGraph.

## Global Constraints

- **기존 테스트 green 유지.** 각 Task 종료 시 `python -m pytest -q` 전체 통과. 현재 기준선 = **133 passed**.
- **난수열 보존.** `generate_dummy.py` 에 wafer 를 추가할 때 기존 난수 소비 순서를 깨지 않는다. 신규 wafer 는 `rows`/`vectors` 맨 끝에 append 한다. 기존 wafer 는 변형하지 않는다.
- **신규 lot 의 평균 수율은 임계(90) 이상**으로 잡아 `find_low_yield_lots` 를 흔들지 않는다 (자동 대상 선정 = 데모 흐름 불변).
- **임의 수치 금지.** 수율 임계는 판정에 쓰지 않고 표시 기준으로만 쓴다.
- 주석·docstring·테스트 이름은 기존 코드처럼 한국어 유지.
- 커밋 메시지는 기존 히스토리 스타일(`feat:`/`fix:`/`test:`/`docs:` + 한국어 요약), 말미에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Windows 환경이라 테스트·실행은 `PYTHONUTF8=1` 을 앞에 붙인다.

---

## File Structure

- `data/generate_dummy.py` (수정) — 분할 lot 케이스 상수·행 생성·step_history, `_augment_yield` 보존 처리
- `tests/test_dummy_data.py` (수정) — 분할 lot 데이터 성질 검증
- `tools/yield_tools.py` (수정) — `find_normal_wafers` 삭제, `find_control_candidates` 신설
- `tests/test_yield_tools.py` (수정) — 위 교체 반영
- `tools/grouping.py` (수정) — `select_control` root_lot 기준 + `yield_summary`
- `tests/test_grouping.py` (수정) — 대조군 계약 갱신
- `graph/nodes.py` (수정) — 요약 줄·seed 문구
- `tests/test_graph_nodes.py`·`tests/test_e2e.py` (수정) — 뒤집히는 단언
- `README.md` (수정) — 데모 출력의 대조군 줄

---

### Task 1: 더미에 분할 lot 케이스 심기

이후 모든 Task 가 이 데이터를 대상으로 테스트하므로 먼저 만든다.

**Files:**
- Modify: `data/generate_dummy.py`
- Test: `tests/test_dummy_data.py`
- Regenerate: `data/yield.db`, `data/embeddings/`

**Interfaces:**
- Produces: 모듈 상수 `SPLIT_ROOT_LOT`(`"R2418"`), `SPLIT_TARGETS`(`list[str]`, 4장), `SPLIT_CONTROLS`(`list[str]`, 4장). 이후 Task 의 테스트가 이 이름을 그대로 import 한다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_dummy_data.py` 끝에 추가:

```python
def test_split_lot_root_lot_spans_multiple_lots():
    """분할 lot: root_lot R2418 이 lot 3개로 갈리고, 타깃 lot 에는 비타깃이 0장이다.

    이 성질이 root_lot 기준과 lot 기준을 가른다 — lot 으로 대조군을 찾으면 0장이다.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT wafer_id, lot_id, lot_type FROM yield "
            "WHERE root_lot_id = 'R2418' ORDER BY wafer_id").fetchall()
    assert len(rows) == 8
    assert {r["lot_id"] for r in rows} == {"R2418.1", "R2418.2", "R2418.3"}
    assert [r["wafer_id"] for r in rows if r["lot_id"] == "R2418.1"] == [
        "R2418_01", "R2418_02", "R2418_03", "R2418_04"]
    # 평가랏이 섞여 있다 — 필터가 아니라 컨텍스트 (corrections B-4)
    assert {r["lot_type"] for r in rows if r["lot_id"] == "R2418.2"} == {"eval"}
    assert {r["lot_type"] for r in rows if r["lot_id"] == "R2418.3"} == {"prod"}


def test_split_lot_signal_is_target_only_chamber():
    """분할 lot 을 하나로 보면 타깃 전용 챔버가 score 1.0 으로 잡힌다."""
    from data.generate_dummy import SPLIT_CONTROLS, SPLIT_TARGETS
    from tools import commonality as cm

    res = cm.find_commonality(SPLIT_TARGETS, SPLIT_CONTROLS)
    top = res["candidates"][0]
    assert top["key"] == "ETCH5_B"
    assert top["score"] == 1.0
    # lot_type 은 배제 대상이 아니라 meta 로 실린다
    assert res["meta"]["control_lot_types"] == {"eval": 2, "prod": 2}
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_dummy_data.py -q`
Expected: FAIL — `assert len(rows) == 8` 에서 `0 == 8`, 그리고 두 번째 테스트는 `ImportError: cannot import name 'SPLIT_CONTROLS'`.

- [ ] **Step 3: 상수 추가**

`data/generate_dummy.py` 의 적대적 케이스 블록(`ADV_NULL_CH_WAFERS = ...` 줄) 바로 아래에 추가:

```python
# ---------------------------------------------------------------- 분할 lot 케이스
# 사내는 root_lot 하나가 여러 lot 으로 갈린다(lot_id 의 '.1' = 양산). 기존 더미는
# root_lot_id = lot_id 1:1 이라 이 축이 무테스트 상태였다.
# 핵심: **R2418.1 에는 비타깃이 한 장도 없다.** lot 으로 대조군을 찾으면 0장이고,
# root_lot 으로 찾아야 .2/.3 의 4장이 나온다. 평가랏(.2)이 대조군에 포함되는 것
# (corrections B-4)도 이 케이스가 함께 시험한다.
# 사내 ID 관례(root_lot 5자 · wafer_id = {root_lot}_{no})를 쓰는 첫 케이스다.
SPLIT_ROOT_LOT = "R2418"
SPLIT_LOTS = {                       # lot_id -> (wafer 번호, lot_type)
    "R2418.1": ([1, 2, 3, 4], "prod"),
    "R2418.2": ([5, 6], "eval"),
    "R2418.3": ([7, 8], "prod"),
}
SPLIT_TARGETS = [f"{SPLIT_ROOT_LOT}_{i:02d}" for i in (1, 2, 3, 4)]
SPLIT_CONTROLS = [f"{SPLIT_ROOT_LOT}_{i:02d}" for i in (5, 6, 7, 8)]
SPLIT_WAFERS = set(SPLIT_TARGETS + SPLIT_CONTROLS)
```

- [ ] **Step 4: 행 생성 추가**

`data/generate_dummy.py` 의 `generate()` 안, 적대적 케이스 for 루프가 끝난 직후이자
`logs = _make_process_logs(rows, rng)` 바로 위에 추가:

```python
    # ---------------- 분할 lot (root_lot 하나에 lot 여럿) — 기존 난수열 뒤에 붙인다
    for lot, (nos, lot_type) in SPLIT_LOTS.items():
        for no in nos:
            wid = f"{SPLIT_ROOT_LOT}_{no:02d}"
            rows.append({
                "wafer_id": wid,
                "lot_id": lot,
                "yield": ADV_TARGET_YIELD if wid in SPLIT_TARGETS else ADV_CONTROL_YIELD,
                "defect_type": "none",       # 라벨 없음 — 실데이터와 같은 조건
                "process_step": "Normal",    # process_log 를 전부 스펙 내로 유지
                "date": RECENT_DATE,
                "root_lot_id": SPLIT_ROOT_LOT,   # lot_id 와 다르다 (_augment_yield 가 보존)
                "lot_type": lot_type,
            })
            vectors.append(_unit(rng.standard_normal(DIM)))
            wafer_ids.append(wid)
```

- [ ] **Step 5: `_augment_yield` 가 기존 값을 보존하게 한다**

`data/generate_dummy.py` 의 `_augment_yield` 를 통째로 교체:

```python
def _augment_yield(rows):
    """commonality 가 요구하는 root_lot_id·lot_type 을 채운다 (rng 미사용).

    **이미 값이 있으면 보존한다** — 분할 lot 케이스는 root_lot_id != lot_id 이고
    lot_type 도 lot 마다 다르다.
    """
    for r in rows:
        r.setdefault("root_lot_id", r["lot_id"])   # 더미 기본: lot_id = root_lot
        r.setdefault("lot_type", "prod")           # 더미 기본: 전부 양산
    return rows
```

- [ ] **Step 6: step_history 생성 추가**

`data/generate_dummy.py` 의 `_make_step_history` 안 skip 줄을 아래로 교체:

```python
        if wid in ADV_WAFERS or wid in SPLIT_WAFERS:   # 전용 생성기가 따로 만든다
            continue
```

그리고 `_make_adversarial_steps` 함수 바로 아래에 신규 함수를 추가:

```python
def _make_split_lot_steps():
    """분할 lot 의 wafer×스텝 이력 (rng 미사용). 타깃만 ETCH5_B, 비타깃은 ETCH5_C.

    설비(ETCH5)는 양쪽이 같아 롤업 점수가 0 으로 눌리고, 챔버에서만 갈린다.
    """
    steps = []
    for wid in SPLIT_TARGETS + SPLIT_CONTROLS:
        for step in SH_STEPS:
            eqp, ch, ppid = f"{step.upper()[:4]}1", "A", "PPID_Z"
            if step == "Etch":
                eqp, ch = "ETCH5", ("B" if wid in SPLIT_TARGETS else "C")
            steps.append({
                "wafer_id": wid, "process_step": step,
                "eqp_id": eqp, "ch_id": ch, "ppid": ppid,
                "timestamp": RECENT_DATE + " 10:00:00",
            })
    return steps
```

`generate()` 의 steps 조립 줄을 교체:

```python
    steps = (_make_step_history(rows) + _make_adversarial_steps()
             + _make_split_lot_steps())
```

- [ ] **Step 7: 더미 재생성 + 통과 확인**

Run: `PYTHONUTF8=1 python data/generate_dummy.py && PYTHONUTF8=1 python -m pytest -q`
Expected: 신규 2개 PASS, 전체 **135 passed**(기준선 133 + 2). 기존이 깨지면 난수열을 건드린 것이니 append 위치를 되돌린다.

`_report` 출력에서 최저 lot 이 여전히 `LOT2406`(87.4) 인지 눈으로 확인한다.

**실행 결과 (2026-07-25): 135 passed.** 제약 하나가 문자 그대로는 어긋났다 —
`R2418.1` 은 타깃 4장만 있어 **lot 평균 88.6 < 임계**라 `find_low_yield_lots` 에 잡힌다
(root_lot 전체 평균은 92.2 지만 그 함수는 `lot_id` 로 묶는다). 제약의 목적인
"자동 대상 선정 불변" 은 지켜졌다 — `LOT2406`(87.4)이 여전히 최저이고
`test_target_selection` 도 green. 타깃 수율을 임계 위로 올리면 '불량' 이라는 성격이
사라지므로 현 상태를 유지한다.

- [ ] **Step 8: 커밋**

```bash
git add data/generate_dummy.py tests/test_dummy_data.py
git commit
```

```
test: 더미에 분할 lot 케이스 (root_lot R2418, lot .1/.2/.3)

기존 더미는 root_lot_id = lot_id 1:1 이라 root_lot 기준과 lot 기준이 구분되지
않았다. R2418.1 에 비타깃을 한 장도 두지 않아, lot 으로 대조군을 찾으면 0장이고
root_lot 으로 찾아야 4장이 나오게 한다. 평가랏(.2)이 대조군에 포함되는 것
(corrections B-4)도 같은 케이스로 시험한다.

사내 ID 관례(root_lot 5자 · wafer_id = {root_lot}_{no})를 쓰는 첫 케이스다.
_augment_yield 가 root_lot_id·lot_type 을 덮어쓰지 않고 보존하도록 바꿨다.
```

---

### Task 2: `find_normal_wafers` → `find_control_candidates` 교체

**Files:**
- Modify: `tools/yield_tools.py:82-93`
- Test: `tests/test_yield_tools.py:33-35`

**Interfaces:**
- Produces: `find_control_candidates(root_lot_ids: list[str], exclude: set[str]) -> list[str]` — `root_lot_id` 가 주어진 값들 중 하나이고 `exclude` 에 없는 wafer_id 를 정렬해 반환. Task 3 의 `select_control` 이 이것만 호출한다.
- Removes: `find_normal_wafers(lot_id, threshold)` — 호출처는 `tools/grouping.py:59` 한 곳이며 Task 3 에서 함께 바뀐다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_yield_tools.py` 의 `test_find_normal_wafers_applies_yield_threshold`(33~35행)를 통째로 교체:

```python
def test_find_control_candidates_includes_low_yield_unlabeled_wafer():
    """라벨이 없으면 '정상' 을 판정할 수 없다 — 저수율·무라벨 wafer 도 대조군 후보다.

    W2406_07(88.5, 라벨 없음)은 옛 규칙에서 수율 임계로 걸러졌다. 새 규칙은 걸러내지
    않고 보이게 한다 (spec 2026-07-25 결정 1·2).
    """
    assert yt.find_control_candidates(["LOT2406"], exclude={"W2406_02"}) == [
        "W2406_01", "W2406_03", "W2406_04", "W2406_05", "W2406_06", "W2406_07"]


def test_find_control_candidates_spans_split_lots_of_one_root_lot():
    from data.generate_dummy import SPLIT_TARGETS
    assert yt.find_control_candidates(["R2418"], exclude=set(SPLIT_TARGETS)) == [
        "R2418_05", "R2418_06", "R2418_07", "R2418_08"]


def test_find_control_candidates_empty_root_lots():
    assert yt.find_control_candidates([], exclude=set()) == []
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_yield_tools.py -q`
Expected: FAIL — `AttributeError: module 'tools.yield_tools' has no attribute 'find_control_candidates'`.

- [ ] **Step 3: 구현**

`tools/yield_tools.py` 의 `find_normal_wafers`(82~93행)를 통째로 교체:

```python
def find_control_candidates(root_lot_ids: list[str], exclude: set[str]) -> list[str]:
    """주어진 root_lot 들의 비타깃 wafer 전원 (수율·라벨·lot_type 조건 없음).

    사내 defect_type 은 대부분 NULL 이라 '정상' 을 판정할 방법이 없다. 저수율 피해
    wafer 가 대조군에 섞이는 것을 **막지 않고 보이게 한다** — commonality 의 2x2
    (control_pass)와 select_control 의 yield_summary 가 그 자리다.
    수율 임계로 거르면 임의 수치가 계산에 들어간다 (spec 2026-07-25 §1).
    """
    if not root_lot_ids:
        return []
    placeholders = ",".join("?" * len(root_lot_ids))
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT wafer_id FROM yield WHERE root_lot_id IN ({placeholders}) "
            f"ORDER BY wafer_id",
            list(root_lot_ids),
        ).fetchall()
    return [r["wafer_id"] for r in rows if r["wafer_id"] not in exclude]
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_yield_tools.py -q`
Expected: 이 파일은 PASS. 전체(`python -m pytest -q`)는 아직 FAIL 이다 — `grouping.py:59` 가 사라진 `find_normal_wafers` 를 부른다. Task 3 에서 이어서 고친다.

- [ ] **Step 5: 커밋하지 않는다** — Task 3 과 함께 green 으로 커밋한다.

---

### Task 3: `select_control` 을 root_lot 기준으로 + `yield_summary`

**Files:**
- Modify: `tools/grouping.py:54-70`
- Test: `tests/test_grouping.py:59-80`

**Interfaces:**
- Consumes: `yt.find_control_candidates(root_lot_ids, exclude)` (Task 2), `yt.get_wafers(wafer_ids) -> list[dict]`(각 dict 에 `wafer_id`·`root_lot_id`·`yield` 포함).
- Produces: `select_control(target_group) -> dict` with keys `control_group: list[str]`, `sources: dict[str, list[str]]`(키 = root_lot_id), `insufficient: bool`, `yield_summary: dict | None`. `stage` 키는 **없앤다.** Task 4 의 `graph/nodes.py` 가 이 키들을 읽는다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_grouping.py` 의 `test_control_is_union_of_sibling_lots_with_yield_condition`(59~67행)을 통째로 교체하고, 그 아래 두 테스트(`test_control_excludes_target_members`, `test_control_insufficient_reported_honestly`)는 **그대로 둔다**(새 규칙에서도 통과한다):

```python
def test_control_is_all_non_targets_in_same_root_lots():
    """대조군 = 타깃과 같은 root_lot 의 비타깃 전원. 출처는 root_lot 단위로 명시한다.

    W2406_04·W2406_06 은 center_spot 불량이지만 이 호출에서는 타깃이 아니므로
    대조군에 들어간다 — 새 규칙에는 라벨 조건이 없다.
    """
    res = grouping.select_control(["W2406_02", "W2410_cen1"])   # LOT2406 + LOT2402
    assert "stage" not in res                                   # 단계 개념 폐기
    assert res["insufficient"] is False
    assert set(res["sources"]) == {"LOT2406", "LOT2402"}
    assert res["sources"]["LOT2406"] == [
        "W2406_01", "W2406_03", "W2406_04", "W2406_05", "W2406_06", "W2406_07"]
    assert set(res["control_group"]) == {w for ws in res["sources"].values() for w in ws}


def test_control_reports_yield_distribution_instead_of_filtering():
    """저수율·무라벨 wafer 를 거르지 않고 yield_summary 로 보인다 (spec 결정 2)."""
    import config

    res = grouping.select_control(["W2406_02", "W2410_cen1"])
    assert "W2406_07" in res["control_group"]          # 88.5 — 옛 규칙에서는 제외됐다
    assert res["yield_summary"]["threshold"] == config.YIELD_THRESHOLD
    assert res["yield_summary"]["n_below_threshold"] >= 1
    assert res["yield_summary"]["median"] > 0


def test_control_spans_split_lots_of_same_root_lot():
    """타깃 lot 안에 비타깃이 0장이어도 같은 root_lot 의 다른 분할 lot 에서 찾는다."""
    from data.generate_dummy import SPLIT_CONTROLS, SPLIT_TARGETS

    res = grouping.select_control(SPLIT_TARGETS)
    assert res["control_group"] == SPLIT_CONTROLS
    assert set(res["sources"]) == {"R2418"}            # 출처는 root_lot 단위
    assert res["insufficient"] is False


def test_control_group_is_empty_when_no_yield_rows():
    res = grouping.select_control(["W_NOPE"])
    assert res["control_group"] == []
    assert res["yield_summary"] is None
    assert res["insufficient"] is True
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_grouping.py -q`
Expected: FAIL — `AttributeError: module 'tools.yield_tools' has no attribute 'find_normal_wafers'`.

- [ ] **Step 3: 구현**

`tools/grouping.py` 의 `select_control`(54~70행)을 통째로 교체:

```python
def _yield_summary(control: list[str]) -> dict | None:
    """대조군 수율 분포 — **판정이 아니라 해석 재료**다 (spec 2026-07-25 결정 2).

    라벨이 없어 저수율 피해 wafer 를 거를 수 없으므로, 걸러내는 대신 분포를 실어
    "이 반례가 진짜인가 피해 wafer 인가" 를 사람·LLM 이 판단할 재료로 넘긴다.
    """
    ys = sorted(r["yield"] for r in yt.get_wafers(control))
    if not ys:
        return None
    mid = len(ys) // 2
    median = ys[mid] if len(ys) % 2 else (ys[mid - 1] + ys[mid]) / 2
    return {
        "median": round(median, 1),
        "n_below_threshold": sum(1 for y in ys if y < config.YIELD_THRESHOLD),
        "threshold": config.YIELD_THRESHOLD,
    }


def select_control(target_group: list[str]) -> dict:
    """대조군 = 타깃과 같은 root_lot 의 비타깃 wafer 전원 (spec 2026-07-25 §2).

    수율·라벨·lot_type 조건이 없다. lot 이 아니라 root_lot 으로 묶으므로 분할 lot 이
    갈려 있어도 대조군을 찾는다. 확장 단계 개념은 없다 — 부족하면 정직 보고한다.
    """
    root_lots = sorted({r["root_lot_id"] for r in yt.get_wafers(target_group)})
    control = yt.find_control_candidates(root_lots, exclude=set(target_group))

    sources: dict[str, list[str]] = {}
    for r in yt.get_wafers(control):
        sources.setdefault(r["root_lot_id"], []).append(r["wafer_id"])
    return {
        "control_group": control,
        "sources": {rl: sorted(ws) for rl, ws in sources.items()},
        "insufficient": len(control) < config.CONTROL_MIN_SIZE,
        "yield_summary": _yield_summary(control),
    }
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_grouping.py tests/test_yield_tools.py -q`
Expected: PASS.

전체(`python -m pytest -q`)는 아직 FAIL 이다 — `graph/nodes.py:107` 이 사라진 `ctrl["stage"]` 를 읽고, `test_graph_nodes.py:69`·`test_e2e.py:15` 가 옛 계약을 단언한다. Task 4 에서 이어서 고친다.

- [ ] **Step 5: 커밋하지 않는다** — Task 4 와 함께 green 으로 커밋한다.

---

### Task 4: 그래프 노드 반영 + 뒤집히는 단언 갱신

**Files:**
- Modify: `graph/nodes.py:77`, `graph/nodes.py:105-111`
- Test: `tests/test_graph_nodes.py:69`, `tests/test_e2e.py:15-16`

**Interfaces:**
- Consumes: `select_control` 의 반환 키 `control_group`·`sources`·`insufficient`·`yield_summary` (Task 3).

- [ ] **Step 1: 뒤집히는 단언을 먼저 고쳐 실패 상태를 만든다**

`tests/test_graph_nodes.py:69` 를 교체:

```python
    assert "W2406_07" in out["control_group"]        # 라벨 없는 저수율 wafer 도 대조군 (spec 결정 1)
```

`tests/test_e2e.py:15-16` 을 교체:

```python
    # 라벨이 없으면 '정상' 을 판정할 수 없다 — W2406_07(88.5, 무라벨)도 대조군에 들어간다.
    # 희석은 막지 않고 yield_summary 로 보인다 (spec 2026-07-25 결정 1·2).
    assert "W2406_07" in state["control_group"]
    assert set(state["control_group"]) >= {"W2406_01", "W2406_03", "W2406_05"}
```

`tests/test_e2e.py` 의 `test_full_loop_reaches_report_with_audit_trail` 끝에 한 줄 추가:

```python
    assert "root_lot" in state["status_summary"]     # 대조군 출처가 root_lot 단위로 보고된다
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONUTF8=1 python -m pytest tests/test_e2e.py tests/test_graph_nodes.py -q`
Expected: FAIL — `KeyError: 'stage'` (`graph/nodes.py:107`).

- [ ] **Step 3: 요약 줄 구현**

`graph/nodes.py` 의 105~111행(`src = ...` 부터 `insufficient` 블록까지)을 교체:

```python
    src = ", ".join(f"{rl} {len(ws)}장" for rl, ws in sorted(ctrl["sources"].items()))
    line = f"대조군 (같은 root_lot 비타깃): {len(ctrl['control_group'])}장 — {src}"
    ys = ctrl["yield_summary"]
    if ys:
        # 라벨이 없어 저수율 wafer 를 거를 수 없다 — 거르는 대신 분포를 보인다
        line += (f" · 수율 중앙값 {ys['median']}, 임계 {ys['threshold']} 미만 "
                 f"{ys['n_below_threshold']}장")
    lines.append(line)
    if ctrl["insufficient"]:
        lines.append(f"대조군 부족: {len(ctrl['control_group'])}장 < "
                     f"{config.CONTROL_MIN_SIZE} (root_lot 내 대조 한계 — 추후 분석 필요)")
```

- [ ] **Step 4: LLM seed 문구 수정**

`graph/nodes.py:77` 을 교체:

```python
            f"대조 그룹 (비타깃): {', '.join(ctrl['control_group'])}\n"
```

이유: 더 이상 정상 판정을 하지 않으므로 "정상" 이라고 넘기면 LLM 에게 거짓 전제를 준다.
(mock LLM 은 `GROUPS_JSON` 을 파싱하므로 이 문구 변경에 영향받지 않는다.)

- [ ] **Step 5: 전체 회귀**

Run: `PYTHONUTF8=1 python -m pytest -q`
Expected: **140 passed.** 내역 — 기준선 133, Task 1 +2, Task 2 교체(−1 +3 = +2), Task 3 교체(−1 +4 = +3), Task 4 는 기존 테스트 수정만(±0). 수가 다르면 어느 테스트가 빠졌는지 확인하고 멈춘다.

- [ ] **Step 6: 데모가 여전히 같은 결론에 닿는지 확인**

Run: `PYTHONUTF8=1 python main.py`
확인할 것: 결론이 여전히 `Etch 공정 ETCH9_B 편중 ... (확신도 0.9)` 인지. 대조군 장수는 늘어난다(패턴그룹 wafer 와 W2406_07 이 들어오므로) — **장수는 바뀌어도 결론은 유지되어야 한다.** 바뀌면 멈추고 원인을 조사한다.

Run: `PYTHONUTF8=1 python main.py R2418_01`
확인할 것: 분할 lot 케이스가 `control_insufficient` 로 끝나지 않고 `ETCH5_B` 결론까지 가는지.

- [ ] **Step 7: 커밋** (Task 2·3·4 를 한 커밋으로)

```bash
git add tools/yield_tools.py tools/grouping.py graph/nodes.py tests/
git commit
```

```
feat: 대조군을 같은 root_lot 의 비타깃 전원으로 재정의

find_normal_wafers 가 defect_type='none' 에 의존해 실데이터(라벨 대부분 NULL)에서
대조군이 비었다. find_control_candidates 로 교체하고 수율·라벨·lot_type 조건을
전부 없앤다. 범위는 lot_id → root_lot_id 로 넓혀 분할 lot 이 갈려 있어도 대조군을
찾는다. 1/2단계 확장 개념(stage 키)은 폐기한다.

거르지 않는 대신 보이게 한다: select_control 이 yield_summary(중앙값·임계 미만
장수)를 실어 status_summary 까지 전달한다. 수율 임계로 거르면 임의 수치가 계산에
들어가고, 2x2 의 control_pass 가 드러내던 반례 정보도 사라진다.

LLM seed 의 '대조 그룹 (정상)' 을 '(비타깃)' 으로 고쳤다 — 정상 판정을 하지 않으므로
그대로 두면 거짓 전제를 준다.

test_e2e·test_graph_nodes 의 'W2406_07 이 대조군에 없다' 단언이 뒤집힌다. 지우지 않고
포함되는 것을 확인하는 쪽으로 바꿔, 실데이터에서 벌어질 일을 테스트가 기술하게 했다.
```

---

### Task 5: README 데모 출력 동기화

Task 4 로 대조군 줄의 문구와 장수가 바뀐다. README 데모는 실제 출력이어야 한다.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 실제 출력 확보**

Run: `PYTHONUTF8=1 python main.py`
출력의 `대조군 (...)` 줄을 그대로 복사한다. **손으로 쓰지 않는다.**

- [ ] **Step 2: 데모 블록 갱신**

`README.md` 데모 블록의 아래 줄을 Step 1 에서 얻은 실제 줄로 교체:

```
대조군 (1단계: 형제 lot 내 합집합): 67장 — LOT2402 16장, LOT2403 16장, LOT2404 16장, LOT2405 16장, LOT2406 3장
```

- [ ] **Step 3: 대조군 설명 추가**

`README.md` 의 "더미 데이터 설계" 절 끝에 추가:

```markdown
대조군은 **타깃과 같은 root_lot 의 비타깃 wafer 전원**입니다 — 수율·라벨 조건이 없습니다.
사내 `defect_type` 이 대부분 비어 있어 "정상" 을 판정할 방법이 없기 때문입니다. 저수율
wafer 가 대조군에 섞이면 진짜 신호가 희석될 수 있는데, 이를 막는 대신 대조군의 수율 분포를
리포트에 함께 실어 판단 재료로 넘깁니다.
```

- [ ] **Step 4: 커밋**

```bash
git add README.md
git commit -m "docs: README 데모의 대조군 줄을 root_lot 기준 실제 출력으로 갱신"
```

---

## 완료 기준

1. `defect_type` 이 전부 NULL 이어도 대조군이 만들어진다 — `find_control_candidates` 에 라벨 조건이 없다.
2. `R2418` 케이스로 root_lot 기준과 lot 기준의 차이가 테스트에 드러난다.
3. 대조군 수율 분포가 `status_summary` 에 보인다.
4. `find_normal_wafers` 가 저장소에서 사라진다 (`git grep find_normal_wafers` 가 빈 결과).
5. 전체 회귀 green. `python main.py` 결론이 `ETCH9_B` 로 유지된다.
