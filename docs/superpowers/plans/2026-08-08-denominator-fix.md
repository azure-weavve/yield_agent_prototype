# 분모 교정 구현 계획 (metro commonality 1단계)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** commonality 후보의 분모를 "이력 행이 하나라도 있는 wafer" 에서 **"그 질문에 답할 수 있는 wafer"** 로 좁혀, 스텝 통과율 차이와 컬럼 결측이 챔버·PPID 신호로 둔갑하는 것을 막는다.

**Architecture:** `tools/commonality.py` 의 `_count_stratum` 이 `(레벨, 스텝) -> 답할 수 있는 wafer 집합` 을 함께 내고, 집계 루프가 그것을 분모로 쓴다. `_keys()` 가 이미 결측 레벨을 건너뛰므로 "답할 수 있다" 판정이 그 루프에서 그대로 나온다. `step_passage` 는 모든 wafer 가 답할 수 있으므로 legend 에 `denominator: all` 을 달아 예외로 둔다.

**Tech Stack:** Python 3, sqlite3, pytest, PyYAML. 새 의존성 없음.

## Global Constraints

- 설계 근거: `docs/superpowers/specs/2026-08-08-metro-commonality-design.md` §4
- 브랜치: `feat/metro-commonality` (main 에서 분기, docs 커밋 1개 위)
- 주석·docstring·테스트 이름 설명은 **한국어**. 기존 파일 문체를 그대로 따른다
- 콘솔이 cp949 라 파이썬 실행은 항상 `python -X utf8` 로 한다
- 테스트 실행: `python -X utf8 -m pytest -q`
- 이 단계에서 **순열검정·FDR·metro 는 건드리지 않는다** (2·3단계)
- `find_commonality` 의 반환 키를 새로 추가하지 않는다. `target_total`/`control_total` 값만 바뀐다

## 기준선 (2026-08-08 실측)

```
  현재:  200 passed, 1 failed
  실패:  tests/test_schema_contract.py::test_internal_and_dummy_step_history_do_not_diverge_silently
```

이 실패는 **소스 문제가 아니다.** `_dummy_cols()` 가 디스크의 `data/yield.db` 를 읽는데,
그 파일이 `feat/incremental-load` 브랜치 코드로 생성돼 `step_history` 에 `root_lot_id`
컬럼이 들어 있다. 이 브랜치의 `generate_dummy.py` 에는 그 컬럼이 없다. Task 0 에서
더미 DB 를 재생성해 해소한다. `SEED` 고정(`np.random.default_rng(SEED)`)이라 재생성은
결정론적이고, `.db` 파일은 git 추적 대상이 아니다.

```
  Task 0 후:  201 passed
  Task 1 후:  207 passed   (새 테스트 6개. 리뷰에서 늘어날 수 있으니 하한으로 본다)
  Task 2 후:  207 passed
```

## 영향 범위 (2026-08-08 실측)

더미 시나리오에 새 분모를 대입해 미리 계산했다.

| 시나리오 | 도구 | 변화 |
|---|---|---|
| MAIN (`GROUP_WAFERS`/`CONTROL_WAFERS`) | eqp_ch·ppid | **변화 없음.** ETCH9_B 1.0, PPID_X 1.0 그대로 |
| SPLIT (`SPLIT_TARGETS`/`SPLIT_CONTROLS`) | eqp_ch | **변화 없음.** ETCH5_B 1.0 그대로 |
| IRREG (`IRREG_TARGETS`/`IRREG_CONTROLS`) | eqp_ch | 후보 8개 → **0개** (`no_signal`) |
| IRREG | ppid | 후보 4개 → **0개** (`no_signal`) |
| IRREG | step_passage | **변화 없음.** 1.0 그대로 |

IRREG 에서 후보가 사라지는 것은 **의도된 결과**다. 대조군이 비정규 스텝
`CC002000EC` 에 아무도 안 갔으므로 "그 스텝에서 어느 설비를 썼나" 는 대비할 짝이
없다. 예전에는 `1/4 vs 0/4 = 0.250` 짜리 후보 12개가 나왔다가 판별선에서 걸렸는데,
이제는 계산 단계에서 빠진다. 그 신호는 `step_passage` 축이 그대로 잡는다.

**깨지는 기존 테스트는 정확히 2개다.**

1. `tests/test_commonality.py::test_shared_equipment_excluded`
2. `tests/test_irregular_step_dummy.py::test_irregular_step_is_caught_only_by_the_passage_axis`

둘 다 Task 1 에서 갱신한다. 다른 테스트는 손대지 않는다.

## File Structure

| 파일 | 책임 | 이 계획에서 하는 일 |
|---|---|---|
| `tools/commonality.py` | 후보 집계·점수 계산 | `_count_stratum` 반환에 분모 추가, 집계 루프가 사용, docstring 갱신 |
| `domain/hypotheses.yaml` | 가설(legend) 선언 | `step_passage` 레벨에 `denominator: all` |
| `domain/registry.py` | YAML 스키마 검증 | `denominator` 값 검증 추가 |
| `tests/test_commonality.py` | 단위 검증 | 새 테스트 5개, 기존 1개 갱신 |
| `tests/test_registry.py` | YAML 검증 | 새 테스트 1개 (없으면 파일 확인 후 위치 결정) |
| `tests/test_irregular_step_dummy.py` | 더미 시나리오 | 기존 1개 갱신 |

---

## Task 0: 기준선 복구

로컬 더미 DB 가 다른 브랜치 코드로 만들어져 스키마 계약 테스트가 깨져 있다.
소스를 고치는 게 아니라 산출물을 다시 만든다.

**Files:**
- Modify: 없음 (생성물 `data/yield.db`, `data/embeddings/` 만 갱신)

**Interfaces:**
- Consumes: 없음
- Produces: 이후 모든 Task 가 밟는 깨끗한 기준선 (201 passed)

- [ ] **Step 1: 현재 실패를 눈으로 확인**

```bash
python -X utf8 -m pytest tests/test_schema_contract.py -q
```

Expected: `test_internal_and_dummy_step_history_do_not_diverge_silently` FAIL,
메시지에 `[('root_lot_id', 1)]`

- [ ] **Step 2: 더미 DB 재생성**

```bash
python -X utf8 -m data.generate_dummy
```

Expected: 오류 없이 끝나고 `data/yield.db` 가 갱신된다.

- [ ] **Step 3: 전체 테스트로 기준선 확인**

```bash
python -X utf8 -m pytest -q
```

Expected: **201 passed**, 0 failed.

201 이 아니면 멈추고 보고한다. 재생성이 다른 테스트를 깨뜨렸다면 그 자체가
별건이므로 Task 1 로 넘어가지 않는다.

- [ ] **Step 4: 커밋 (소스 변경이 없으므로 커밋할 것이 없다)**

`.db` 는 git 추적 대상이 아니다. `git status --short` 로 확인만 하고 넘어간다.

```bash
git status --short
```

Expected: `docs/2026-08-07-commonality-설계검토.md` 만 미추적으로 남는다
(사용자 소유 문서. 건드리지 않는다).

---

## Task 1: 분모를 "그 질문에 답할 수 있는 wafer" 로 좁힌다

**Files:**
- Modify: `tools/commonality.py:16-28` (docstring), `:126-140` (`_count_stratum`), `:198-227` (집계 루프)
- Modify: `domain/hypotheses.yaml:28`
- Modify: `domain/registry.py:29-33`
- Modify: `tests/test_commonality.py` (새 테스트 5개 + `test_shared_equipment_excluded` 갱신)
- Modify: `tests/test_irregular_step_dummy.py:18-39`

**Interfaces:**
- Consumes: 없음 (기존 `_keys(row, legend) -> list[tuple[str, str, str, dict]]` 를 그대로 쓴다)
- Produces:
  - `_count_stratum(rows, wafers: set[str], legend) -> tuple[dict, dict, set, dict]`
    반환이 3개에서 **4개로 늘어난다**: `(passed, answer, seen, colmap)`.
    `answer` 는 `dict[tuple[str, str], set[str]]` 로 `(레벨, 스텝) -> wafer 집합`.
  - legend 레벨에 선택 키 `denominator: "all" | "answerable"` (기본 `"answerable"`).

- [ ] **Step 1: 버그 재현 테스트를 쓴다**

`tests/test_commonality.py` 의 "결측·NULL" 절 아래에 추가한다.

```python
# ------------------------------------------------------------------ 분모

def test_unequal_step_coverage_no_longer_fakes_a_signal(tmp_path, monkeypatch):
    """스텝 통과율이 그룹마다 다르면 챔버 신호가 없는데도 양의 score 가 나왔다.

    Etch 를 지난 wafer 중 ETCH9_3 을 쓴 비율은 타깃 2/4, 대조군 1/2 로 **똑같다**.
    챔버로는 아무것도 안 갈린다. 그런데 분모가 '이력이 있는 wafer' 면 대조군 분모가
    2 가 아니라 4 로 부풀려져 0.500 - 0.250 = 0.250 짜리 가짜 후보가 만들어졌다.
    """
    t = ["T1", "T2", "T3", "T4"]
    c = ["C1", "C2", "C3", "C4"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Photo", "PHOTO1", "1") for w in t + c]   # 전원이 지나는 스텝
    hs += [_h(w, "Etch", "ETCH9", "3") for w in ["T1", "T2"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["T3", "T4"]]
    hs += [_h("C1", "Etch", "ETCH9", "3"), _h("C2", "Etch", "ETCH8", "1")]
    # C3, C4 는 Etch 를 아예 안 지난다
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert ("chamber", "ETCH9_3") not in _keys(res)
    assert ("equipment", "ETCH9") not in _keys(res)
    assert res["status"] == "no_signal"
```

- [ ] **Step 2: 실패를 확인한다**

```bash
python -X utf8 -m pytest tests/test_commonality.py::test_unequal_step_coverage_no_longer_fakes_a_signal -q
```

Expected: FAIL. `("chamber", "ETCH9_3")` 이 후보에 있다 (score 0.250).

- [ ] **Step 3: legend 에 `denominator` 키를 연다**

`domain/hypotheses.yaml` 의 `step_passage_commonality` legend 를 고친다.

```yaml
  legend:
    - {level: step_passage, columns: [step_seq], denominator: all}
```

같은 항목 description 끝에 한 줄 덧붙인다 (기존 문장은 건드리지 않는다).

```yaml
    분모도 다르다 — "지났는가" 는 모든 wafer 가 답할 수 있으므로 denominator: all 이다.
    다른 축은 그 스텝에 간 wafer 만 분모에 넣는다.
```

`domain/registry.py` 의 legend 검증 루프(`:29-33`)에 값 검증을 더한다.

```python
        for lvl in legend:
            if not isinstance(lvl, dict) or "level" not in lvl or "columns" not in lvl:
                raise ValueError(f"가설 '{s['id']}': 각 legend 레벨은 level·columns 를 가져야 한다")
            if not isinstance(lvl["columns"], list) or not lvl["columns"]:
                raise ValueError(f"가설 '{s['id']}': legend 레벨 columns 는 비어있지 않은 리스트")
            # 분모 규칙. 기본은 "그 질문에 답할 수 있는 wafer 만"(answerable)이고,
            # all 은 step_passage 처럼 모든 wafer 가 답할 수 있는 축에만 쓴다.
            if lvl.get("denominator", "answerable") not in ("answerable", "all"):
                raise ValueError(
                    f"가설 '{s['id']}': legend 레벨 denominator 는 "
                    f"'answerable'(기본) 또는 'all' 이어야 한다")
```

- [ ] **Step 4: `_count_stratum` 이 분모를 함께 내게 한다**

`tools/commonality.py:126-140` 을 통째로 바꾼다.

```python
def _count_stratum(rows, wafers: set[str], legend) -> tuple[dict, dict, set, dict]:
    """stratum 내 집계.

    passed  후보키 -> 그 키를 거친 wafer 집합
    answer  (레벨, 스텝) -> **그 질문에 답할 수 있는** wafer 집합 = 분모
    seen    이력이 하나라도 있는 wafer (missing_history 보고용)
    colmap  후보키 -> legend 컬럼값

    answer 를 따로 세는 이유: `_keys` 가 결측 레벨을 이미 건너뛰므로, 거기서 나온
    (레벨, 스텝) 이 곧 "이 wafer 는 그 질문에 답할 수 있다" 는 뜻이다. seen 을
    분모로 쓰면 그 스텝을 안 지난 wafer 와 컬럼이 결측인 wafer 가 '미통과' 로 섞인다.
    """
    passed: dict[tuple, set] = {}
    answer: dict[tuple, set] = {}
    seen: set[str] = set()
    colmap: dict[tuple, dict] = {}
    for r in rows:
        wid = r["wafer_id"]
        if wid not in wafers:
            continue
        seen.add(wid)
        for level, step, keystr, colvals in _keys(r, legend):
            answer.setdefault((level, step), set()).add(wid)
            key = (level, step, keystr)
            passed.setdefault(key, set()).add(wid)
            colmap.setdefault(key, colvals)
    return passed, answer, seen, colmap
```

- [ ] **Step 5: 집계 루프가 그 분모를 쓰게 한다**

`tools/commonality.py:198-227` 을 바꾼다. `universal` 한 줄이 새로 생기고,
`nt`/`nc` 를 구하는 자리가 stratum 밖에서 후보 안으로 옮겨간다.

```python
    # ---- stratum 별 2x2 집계 후 카운트 합산 ----
    # denominator: all 인 레벨은 모든 wafer 가 답할 수 있다 (step_passage).
    universal = {lvl["level"] for lvl in legend if lvl.get("denominator") == "all"}
    agg: dict[tuple, dict] = {}
    colmap_all: dict[tuple, dict] = {}
    strata_report, missing = [], []
    t_seen_all, c_seen_all = set(), set()

    for rl, s in sorted(paired.items(), key=lambda kv: (kv[0] is None, kv[0])):
        t_passed, t_answer, t_seen, t_colmap = _count_stratum(t_rows, s["target"], legend)
        c_passed, c_answer, c_seen, c_colmap = _count_stratum(c_rows, s["control"], legend)
        colmap_all.update(t_colmap)
        colmap_all.update(c_colmap)
        t_seen_all |= t_seen
        c_seen_all |= c_seen
        missing += sorted((s["target"] | s["control"]) - t_seen - c_seen)

        # 이력이 아예 없는 쪽이 있으면 이 stratum 은 비교가 성립하지 않는다
        if not t_seen or not c_seen:
            continue
        strata_report.append({"root_lot_id": rl,
                              "n_target": len(t_seen), "n_control": len(c_seen)})

        for key in set(t_passed) | set(c_passed):
            level, step, _keystr = key
            if level in universal:
                nt, nc = len(t_seen), len(c_seen)
            else:
                nt = len(t_answer.get((level, step), ()))
                nc = len(c_answer.get((level, step), ()))
            # 한쪽이 그 질문에 아무도 답하지 못하면 대비할 짝이 없다.
            # (예: 대조군이 그 스텝에 아예 안 갔다 → step_passage 축이 잡을 일이다)
            if nt == 0 or nc == 0:
                continue
            e = agg.setdefault(key, {"a": 0, "b": 0, "c": 0, "d": 0, "strata": 0})
            a = len(t_passed.get(key, ()))
            c_ = len(c_passed.get(key, ()))
            e["a"] += a
            e["b"] += nt - a
            e["c"] += c_
            e["d"] += nc - c_
            e["strata"] += 1
```

- [ ] **Step 6: 재현 테스트가 통과하는지 확인**

```bash
python -X utf8 -m pytest tests/test_commonality.py::test_unequal_step_coverage_no_longer_fakes_a_signal -q
```

Expected: PASS

- [ ] **Step 7: 나머지 분모 테스트 4개를 추가한다**

방금 쓴 테스트 바로 아래에 이어 붙인다.

```python
def test_step_denominator_counts_only_wafers_at_that_step(tmp_path, monkeypatch):
    """분모는 그 스텝에 간 wafer 만. 안 간 wafer 는 '다른 챔버를 썼다' 가 아니다."""
    t, c = ["T1", "T2", "T3"], ["C1", "C2", "C3"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Photo", "PHOTO1", "1") for w in t + c]
    hs += [_h(w, "Etch", "ETCH9", "3") for w in ["T1", "T2"]]   # T3 는 Etch 안 감
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["C1", "C2"]]   # C3 는 Etch 안 감
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    ch = _find(res, "chamber", "ETCH9_3")
    assert (ch["target_pass"], ch["target_total"]) == (2, 2)     # 3 이 아니다
    assert (ch["control_pass"], ch["control_total"]) == (0, 2)   # 3 이 아니다
    assert ch["score"] == 1.0
    # n_target 은 '이력이 있는 wafer' 그대로다 — 후보 분모와는 다른 개념이다
    assert res["n_target"] == 3


def test_missing_token_excluded_from_chamber_denominator_only(tmp_path, monkeypatch):
    """ch_id 가 '-' 면 챔버 질문에는 답할 수 없고 설비 질문에는 답할 수 있다."""
    t, c = ["T1", "T2", "T3"], ["C1", "C2", "C3"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h("T1", "Etch", "ETCH9", "3"), _h("T2", "Etch", "ETCH9", "3"),
          _h("T3", "Etch", "ETCH9", "-")]
    hs += [_h("C1", "Etch", "ETCH8", "1"), _h("C2", "Etch", "ETCH8", "1"),
           _h("C3", "Etch", "ETCH8", "-")]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    eq = _find(res, "equipment", "ETCH9")
    assert (eq["target_pass"], eq["target_total"]) == (3, 3)     # T3 도 설비는 안다
    ch = _find(res, "chamber", "ETCH9_3")
    assert (ch["target_pass"], ch["target_total"]) == (2, 2)     # T3 는 빠진다
    assert (ch["control_pass"], ch["control_total"]) == (0, 2)   # C3 도 빠진다
    assert ch["score"] == 1.0


def test_skip_equipment_stays_a_candidate(tmp_path, monkeypatch):
    """스킵이 'MSKPI1 + ch_id 없음' 으로 기록되면 설비 레벨이 그것을 잡는 유일한 자리다.

    이력 행이 있으므로 step_passage 는 '지났다' 로 센다. 설비 레벨에서 빼면
    이 스킵은 아무도 못 잡는다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "MSKPI1", "-") for w in t]      # 타깃은 스킵
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]      # 대조군은 정상 처리
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    eq = _find(res, "equipment", "MSKPI1")
    assert (eq["target_pass"], eq["target_total"]) == (2, 2)
    assert (eq["control_pass"], eq["control_total"]) == (0, 2)
    assert eq["score"] == 1.0
    assert ("chamber", "MSKPI1_-") not in _keys(res)   # 결측 토큰은 키를 안 만든다


STEP_PASSAGE_LEGEND = [{"level": "step_passage", "columns": ["step_seq"],
                        "denominator": "all"}]


def test_step_passage_denominator_is_the_whole_group(tmp_path, monkeypatch):
    """'그 스텝을 지났나' 는 모든 wafer 가 답할 수 있다.

    안 지난 wafer 를 분모에서 빼면 커버리지가 항상 1.0 이 되고 대조군 분모가 0 이라
    후보가 통째로 사라져, 이 축이 아무 일도 못 한다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Photo", "PHOTO1", "1") for w in t + c]
    hs += [_h(w, "IrregEC", "ETCH9", "3") for w in t]   # 타깃만 비정규 스텝
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c, legend=STEP_PASSAGE_LEGEND)
    cand = _find(res, "step_passage", "IrregEC")
    assert (cand["target_pass"], cand["target_total"]) == (2, 2)
    assert (cand["control_pass"], cand["control_total"]) == (0, 2)
    assert cand["score"] == 1.0
```

- [ ] **Step 8: 새 테스트가 다 통과하는지 확인**

```bash
python -X utf8 -m pytest tests/test_commonality.py -q
```

Expected: `test_shared_equipment_excluded` 하나만 FAIL (다음 스텝에서 고친다).
나머지는 전부 PASS.

- [ ] **Step 9: 깨진 기존 테스트 2개를 갱신한다**

`tests/test_commonality.py` 의 `test_shared_equipment_excluded`(`:77-87`) 를
아래로 교체한다.

```python
def test_shared_equipment_excluded(tmp_path, monkeypatch):
    """양쪽 그룹이 똑같이 거친 설비는 후보가 아니다 (score <= 0).

    Etch 쪽도 후보가 아니다 — 대조군이 Etch 에 아무도 안 갔으므로 "Etch 에서 어느
    챔버를 썼나" 는 대비할 짝이 없다. 그 신호는 step_passage 축이 잡는다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Photo", "PHOTO1", "1") for w in t + c]
    hs += [_h(w, "Etch", "ETCH9", "3") for w in t]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert ("chamber", "PHOTO1_1") not in _keys(res)
    assert ("chamber", "ETCH9_3") not in _keys(res)
    assert res["status"] == "no_signal"
```

`tests/test_irregular_step_dummy.py` 의 첫 테스트(`:18-39`) 에서 설비·PPID 축을
확인하는 앞부분(`:25-29`)만 아래로 교체한다. `step_passage` 검증(`:31-39`)은
**그대로 둔다.**

```python
    # 대조군이 비정규 스텝에 아무도 안 갔으므로, 그 스텝의 설비·PPID 후보는
    # 대비할 짝이 없어 계산 단계에서 빠진다. 예전에는 1/4 짜리 후보가 12개
    # 나왔다가 판별선에서 걸렸다 (분모 교정 전 동작).
    for hid in ("eqp_ch_commonality", "ppid_commonality"):
        res = _run(hid)
        assert res["status"] == "no_signal", f"{hid} 가 후보를 내면 안 된다"
        assert res["candidates"] == []
```

docstring 도 한 줄 맞춘다 (`:19-24` 의 마지막 문장).

```python
    """설비·PPID 축은 못 잡고 스텝 통과 축만 잡는다 — 이 가설이 존재하는 이유.

    타깃 4장이 비정규 스텝을 거치고 대조군은 아무도 안 거친다. 설비·PPID 축은
    "그 스텝 안에서 무엇을 썼는가" 만 보는데 대조군에 그 스텝 자체가 없으므로
    비교가 성립하지 않는다. 통과 여부로 보면 타깃 4/4 · 대조군 0/4 로 갈린다.
    """
```

- [ ] **Step 10: registry 검증 테스트를 추가한다**

`tests/test_registry.py` 의 `test_reject_malformed_legend`(`:28-33`) 바로 아래에
붙인다. 그 파일의 기존 형태(`yaml.safe_dump` + 한 줄 write + `pytest.raises`)를
그대로 따른다.

```python
def test_reject_unknown_denominator(tmp_path):
    """denominator 오타가 조용히 무시되면 분모가 말없이 바뀐다."""
    bad = [{"id": "x", "name": "n", "description": "d",
            "legend": [{"level": "eq", "columns": ["eqp_id"],
                        "denominator": "everything"}]}]
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="denominator"):
        registry.load_hypotheses(p)
```

`pytest`·`yaml`·`registry` 는 그 파일이 이미 import 하고 있다.

- [ ] **Step 11: 모듈 docstring 을 새 분모 정의에 맞춘다**

`tools/commonality.py:20-21` 의 항목을 교체한다.

기존:
```
- **결측을 신호로 만들지 않는다.** 분모는 step_history 행이 실제로 있는 wafer 로 한정하고,
  이력이 없는 wafer 는 missing_history 로 따로 보고한다.
```

교체:
```
- **분모는 그 질문에 답할 수 있는 wafer 만.** 후보 (레벨, 스텝) 마다 "그 스텝에 이력이
  있고 그 레벨 컬럼이 결측이 아닌 wafer" 를 분모로 쓴다. 스텝을 안 지난 wafer 를
  '미통과' 로 세면 score 가 챔버 분리도가 아니라 스텝 통과 여부를 반영한다.
  예외는 step_passage — 모든 wafer 가 "지났는가" 에 답할 수 있어 legend 에
  denominator: all 을 단다. 이력이 아예 없는 wafer 는 missing_history 로 따로 보고한다.
```

- [ ] **Step 12: 전체 회귀**

```bash
python -X utf8 -m pytest -q
```

Expected: **207 passed**, 0 failed.

숫자가 다르면 멈추고, 어느 테스트가 늘거나 줄었는지 보고한다.

- [ ] **Step 13: 커밋**

```bash
git add tools/commonality.py domain/hypotheses.yaml domain/registry.py tests/
git commit -m "$(cat <<'EOF'
fix(commonality): 분모를 그 질문에 답할 수 있는 wafer 로 좁힌다

분모가 "이력 행이 하나라도 있는 wafer" 라서, 그 스텝을 안 지났거나 레벨 컬럼이
결측인 wafer 가 '미통과' 로 섞였다. 스텝 통과율이 그룹마다 다르면 챔버 신호가
없는데도 양의 score 가 나온다.

- 분모 = (레벨, 스텝) 마다 "그 스텝에 이력이 있고 그 레벨 컬럼이 결측이 아닌 wafer"
- step_passage 는 예외. legend 에 denominator: all 을 달아 전체를 분모로 둔다
- 한쪽이 그 질문에 아무도 답 못 하면 후보를 내지 않는다 (대비할 짝이 없다)

더미 영향: MAIN·SPLIT 시나리오는 변화 없음. IRREG 는 설비·PPID 후보 12개가
사라지고 step_passage 만 남는다 - 의도된 결과이며 그 축이 원래 담당이다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 분모 정의를 언급한 문서를 맞춘다

코드가 바뀌었으니 같은 내용을 적어둔 문서를 찾아 고친다. 코드 리뷰와 분리해도
되는 별개 산출물이라 Task 를 나눈다.

**Files:**
- Modify: grep 결과에 따라 `README.md`, `docs/*.md` 중 해당 문장만

**Interfaces:**
- Consumes: Task 1 의 새 분모 정의
- Produces: 없음 (문서만)

- [ ] **Step 1: 분모를 설명하는 문장을 찾는다**

```bash
grep -rn "분모" --include=*.md . | grep -v "docs/superpowers/specs/2026-08-08"
```

- [ ] **Step 2: 사실과 어긋난 문장만 고친다**

기준은 하나다. **"분모 = 이력이 있는 wafer" 라고 적힌 곳만** 고친다.
새 정의는 "그 후보 질문에 답할 수 있는 wafer (step_passage 는 전체)" 다.

날짜가 박힌 과거 기록 문서(`docs/2026-07-*.md` 등)는 **그때의 사실**이므로
고치지 않는다. 살아 있는 지침 문서만 고친다. 판단이 애매하면
`docs/README.md` 색인에서 그 문서가 살아 있는 지침인지 확인한다.

- [ ] **Step 3: 고친 게 있으면 전체 테스트로 확인**

```bash
python -X utf8 -m pytest -q
```

Expected: **207 passed** (문서만 고쳤으므로 변화 없어야 한다)

- [ ] **Step 4: 커밋**

고친 문서가 없으면 이 Task 는 커밋 없이 끝난다.

```bash
git add -A -- '*.md'
git commit -m "$(cat <<'EOF'
docs: 분모 정의를 코드와 맞춘다

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## 이 계획에서 하지 않는 것

| 항목 | 어디로 |
|---|---|
| 순열검정·FDR | 2단계 |
| metro 분할점 탐색 | 3단계 (데이터 확보 후) |
| 대조군 오염 가중치 상수 (1 → 1.6) | 실데이터 확인 후 |
| `find_commonality` 이름 변경 | 별건 |
| crude pooling / 심슨 역설 | 미해결. 설계검토 §1-3 |
| 분모 하한 가드 / `target_total` 을 게이트·근거 줄에 노출 | 2단계 (순열검정이 이 자리를 대체할 예정이라 지금 상수를 못 박지 않는다) |
