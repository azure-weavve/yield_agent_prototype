# 순열검정 + FDR 구현 계획 (metro commonality 2단계)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** commonality 후보에 **"이 정도 점수가 아무 신호 없이도 나오는가"** 를 실측해 붙인다. wafer 의 불량/정상 라벨을 root_lot 안에서만 섞어 같은 탐색을 반복하고, 후보별 순열 p 와 임계값별 FDR 표를 결과에 싣는다.

**Architecture:** `find_commonality` 의 집계를 **라벨의 순수 함수**로 분리한다. 이력 행은 한 번만 훑어 wafer 를 비트로 색인하고(`_build_index`), 집계는 그 색인과 stratum 별 (타깃 마스크, 대조군 마스크) 만 받는다(`_aggregate`). 순열 회차는 마스크만 바꿔 **같은 함수**를 다시 호출하므로, 실제와 귀무가 같은 코드 경로를 탄다. 이것이 설계 §1-4 "실제와 귀무가 같은 규칙으로 계산돼야 한다" 를 구조로 보장하는 방법이다.

**Tech Stack:** Python 3.11 (`int.bit_count()` 사용 — 확인됨), 표준 라이브러리 `itertools`·`random`·`math` 만. 새 의존성 없음.

## Global Constraints

- 설계 근거: `docs/superpowers/specs/2026-08-08-metro-commonality-design.md` §2(순열검정)·§3(FDR)·§5(출력 계약)
- 브랜치: `main` 에서 새로 분기한다 (1단계는 이미 main 에 병합됐다)
- 주석·docstring·테스트 이름 설명은 **한국어**. 기존 파일 문체를 그대로 따른다
- 콘솔이 cp949 라 파이썬 실행은 항상 `python -X utf8` 로 한다
- 테스트 실행: `python -X utf8 -m pytest -q`
- **기준선은 208 passed** (`main`, 커밋 `d800218`)
- **게이트는 바꾸지 않는다.** `domain/engine.py` 의 `_passes()` 는 `score` 와 `target_pass` 만 본다. p 는 **판단 재료로 싣기만** 한다 (설계 §2-3: 자동 차단은 나중에 위에 얹을 수 있지만 반대는 안 된다)
- **metro 는 건드리지 않는다** (3단계 몫, 데이터 없음). `split_value`·`split_direction` 키는 이 계획의 범위 밖이다
- 순열은 **root_lot 안에서만** 섞는다. lot 을 가로지르면 lot 효과가 신호로 잡힌다 (설계 §2-2)
- 실제와 귀무에 **같은 절단**(`MIN_SCORE`)을 건다. 게이트를 못 지날 후보를 귀무에 세면 기준선만 올라가 실제가 손해를 본다 (설계 §1-4)
- **한 회차 = 라벨 한 번 섞기 → 전 후보 계산.** 후보마다 따로 섞으면 후보 간 상관이 깨진다 (설계 §2-5)
- 난수는 **고정 시드**를 쓴다. 테스트가 결정론적이어야 한다

## 설계에서 고쳐 쓰는 것 두 가지

계획을 쓰며 설계 문서의 서술 두 곳이 그대로는 안 맞는 것을 발견했다. 근거와 함께 바꿔 적는다.

### (1) 관측 라벨은 귀무 표본에서 뺀다

설계 §2-3 은 타깃 2·대조군 2 에서 `p_min_possible = 1/(6+1) = 0.14` 라고 적었다. 그런데 6가지를 **전수 열거하면 관측 라벨 자체가 그 안에 들어 있다.** 관측은 자기 자신보다 크거나 같으므로 "넘은 횟수" 가 항상 1 이상이 되고, `p` 는 절대 `1/(6+1)` 이 될 수 없다. 그러면 §2-3 이 만들려던 "`p == p_min_possible` 이면 공간 부족" 신호가 죽는다.

**결정: 전수 열거에서 관측 라벨을 건너뛴다.** 무작위 표본은 원래 관측을 포함하지 않는다. 그래서 양쪽 모두 아래 한 식으로 통일된다.

```
  n_used = 실제로 돌린 섞기 횟수  (전수면 n_total - 1, 무작위면 반복 횟수)
  p                    = (귀무 score >= 관측 score 인 횟수 + 1) / (n_used + 1)
  p_min_possible       = 1 / (n_used + 1)
  n_permutations_total = n_total   (층화 경우의 수. 전수 열거면 정확값)
```

2대2 는 `n_total=6`, `n_used=5`, `p_min_possible = 1/6 = 0.167` 이 된다. 설계의 0.14 대신 이 값이 맞다. 이 형태는 순열검정의 표준 형태(Phipson-Smyth)이기도 하다.

### (2) "공간 부족" 신호는 `p == p_min_possible` 이 아니라 `p_min_possible` 이 큰 것이다

`p == p_min_possible` 은 "귀무가 관측을 한 번도 못 넘었다" 는 뜻이다. **표본이 커도 신호가 강하면 그렇게 된다.** 예를 들어 6대6 완전 분리는 `n_total = 924`, `p = 1/924 = 0.001` 로 역시 `p == p_min_possible` 이지만 이건 공간 부족이 아니라 아주 강한 결과다.

**공간이 부족하다는 신호는 `p_min_possible` 자체가 크다는 것이다.** 2대2 는 아무리 완벽해도 `p` 가 0.167 아래로 못 내려간다. 그래서 세 값을 다 싣고, `note` 문자열에 이 읽는 법을 적는다. 자동 차단은 하지 않는다.

## File Structure

| 파일 | 책임 | 이 계획에서 하는 일 |
|---|---|---|
| `tools/commonality.py` | 후보 집계·점수·순열검정 | 집계를 순수 함수로 분리, 순열 루프·p·FDR 추가, 모듈 docstring 원칙 교체 |
| `ya_config.py` | 실행 상수 | `COMMONALITY_PERMUTATIONS` 추가 |
| `domain/engine.py` | 게이트 계약 매핑 | 후보 dict 에 `p_permutation` 통과 (판정엔 안 씀) |
| `graph/evidence.py` | 증거 번들·근거 줄 | `Claim` 에 `p_permutation` 필드, 근거 줄에 표시 |
| `domain/hypotheses.yaml` | 가설 description | 세 도구 description 에 p 의 뜻 |
| `tests/test_commonality.py` | 단위 검증 | 순열·FDR 테스트 (Task 2 에 6개, Task 3 에 5개) |
| `tests/test_engine.py` | 어댑터 검증 | p 통과 테스트 1개 (파일명은 구현자가 확인) |
| `tests/test_evidence.py` | 번들 검증 | 새 키가 들어가도 score 안 죽는지 1개 (파일명은 구현자가 확인) |

## Task 개요

```
  Task 1  집계를 라벨의 순수 함수로 분리   동작 변화 0. 208 passed 유지
  Task 2  순열 라벨 생성 + 후보별 p        새 테스트 7개  -> 215
  Task 3  FDR 표 + family-wise p          새 테스트 5개  -> 220
  Task 4  소비자까지 잇기 (engine/근거 줄)  새 테스트 4개  -> 224
  Task 5  원칙·문서 정합 + 성능 측정        테스트 수 불변 -> 224
```

숫자는 하한이다. 리뷰에서 늘 수 있다.

---

## Task 1: 집계를 라벨의 순수 함수로 분리한다

순열은 라벨만 바꾼다. 그런데 지금 집계는 이력 행을 매번 다시 훑는 구조라, 그대로 1000번 돌리면 행 읽기를 1000번 반복한다. 이력 행을 **한 번만** 훑어 wafer 를 비트로 색인해 두고, 집계는 비트 마스크만 받게 바꾼다.

**이 태스크는 동작을 바꾸지 않는다.** 끝난 뒤에도 208 passed 여야 한다. 그것이 이 리팩터의 유일한 합격 기준이다.

**Files:**
- Modify: `tools/commonality.py` (`_count_stratum` 제거 → `_build_index`·`_aggregate` 신설, `find_commonality` 집계부 교체)

**Interfaces:**
- Consumes: 기존 `_keys(row, legend) -> list[tuple[str, str, str, dict]]` 를 그대로 쓴다
- Produces:
  - `_build_index(rows, bits: dict[str, int], legend) -> tuple[dict, dict, int, dict]`
    반환 `(passed, answer, seen, colmap)`. `passed: dict[tuple[str,str,str], int]` (후보키 → wafer 비트마스크), `answer: dict[tuple[str,str], int]`, `seen: int`, `colmap: dict[tuple, dict]`
  - `_aggregate(strata_masks, passed, answer, seen, universal) -> tuple[dict, list]`
    `strata_masks: list[tuple[str|None, int, int]]` = `[(root_lot_id, t_mask, c_mask), ...]`.
    반환 `(agg, strata_report)`. `agg: dict[tuple, dict]` 값은 `{"a","b","c","d","strata"}`
  - `_score_map(agg) -> dict[tuple, float]` — `MIN_SCORE` 절단을 건 **반올림 안 한** score
  - `_names(mask, bits) -> list[str]` — 비트마스크를 wafer id 목록으로

- [ ] **Step 1: `_count_stratum` 을 `_build_index` 로 교체한다**

`tools/commonality.py` 의 `_count_stratum`(현재 `:133-159`) 을 통째로 아래로 바꾼다.

```python
def _build_index(rows, bits: dict[str, int], legend) -> tuple[dict, dict, int, dict]:
    """이력 행을 한 번만 훑어 wafer 를 비트로 색인한다.

    passed  후보키 -> 그 키를 거친 wafer 비트마스크
    answer  (레벨, 스텝) -> **그 질문에 답할 수 있는** wafer 비트마스크 = 분모 재료
    seen    이력이 하나라도 있는 wafer 비트마스크 (missing_history 보고용)
    colmap  후보키 -> legend 컬럼값

    순열검정은 **라벨만** 바꾸므로 이 색인은 회차마다 다시 만들 필요가 없다. 행을
    다시 훑는 대신 마스크 교집합의 popcount 로 세면 회차당 비용이 행 수가 아니라
    후보 키 수에 비례한다.

    answer 를 따로 세는 이유: `_keys` 가 결측 레벨을 이미 건너뛰므로, 거기서 나온
    (레벨, 스텝) 이 곧 "이 wafer 는 그 질문에 답할 수 있다" 는 뜻이다. seen 을
    분모로 쓰면 그 스텝을 안 지난 wafer 와 컬럼이 결측인 wafer 가 '미통과' 로 섞인다.
    """
    passed: dict[tuple, int] = {}
    answer: dict[tuple, int] = {}
    seen = 0
    colmap: dict[tuple, dict] = {}
    for r in rows:
        b = bits.get(r["wafer_id"])
        if b is None:
            continue
        seen |= b
        for level, step, keystr, colvals in _keys(r, legend):
            answer[(level, step)] = answer.get((level, step), 0) | b
            key = (level, step, keystr)
            passed[key] = passed.get(key, 0) | b
            colmap.setdefault(key, colvals)
    return passed, answer, seen, colmap


def _aggregate(strata_masks, passed, answer, seen, universal) -> tuple[dict, list]:
    """라벨(stratum 별 타깃·대조군 마스크)에서 후보별 2x2 카운트를 낸다 — 순수 함수.

    strata_masks = [(root_lot_id, t_mask, c_mask), ...]

    **실제 데이터와 순열 귀무가 이 함수 하나를 같이 탄다.** 귀무를 다른 코드로 세면
    분모 규칙·절단·stratum 스킵이 갈려, 실제와 다른 것을 재게 된다(설계 §1-4).
    """
    agg: dict[tuple, dict] = {}
    strata_report = []
    for rl, t_mask, c_mask in strata_masks:
        t_seen = t_mask & seen
        c_seen = c_mask & seen
        # 이력이 아예 없는 쪽이 있으면 이 stratum 은 비교가 성립하지 않는다
        if not t_seen or not c_seen:
            continue
        strata_report.append({"root_lot_id": rl,
                              "n_target": t_seen.bit_count(),
                              "n_control": c_seen.bit_count()})
        for key, p_bits in passed.items():
            a = (p_bits & t_mask).bit_count()
            c_ = (p_bits & c_mask).bit_count()
            if a == 0 and c_ == 0:
                continue                  # 이 stratum 에 이 키가 없다
            level, step, _keystr = key
            if level in universal:
                nt, nc = t_seen.bit_count(), c_seen.bit_count()
            else:
                ans = answer.get((level, step), 0)
                nt = (ans & t_mask).bit_count()
                nc = (ans & c_mask).bit_count()
            # 한쪽이 그 질문에 아무도 답하지 못하면 대비할 짝이 없다.
            # (예: 대조군이 그 스텝에 아예 안 갔다 -> step_passage 축이 잡을 일이다)
            if nt == 0 or nc == 0:
                continue
            e = agg.setdefault(key, {"a": 0, "b": 0, "c": 0, "d": 0, "strata": 0})
            e["a"] += a
            e["b"] += nt - a
            e["c"] += c_
            e["d"] += nc - c_
            e["strata"] += 1
    return agg, strata_report


def _score_map(agg) -> dict[tuple, float]:
    """후보키 -> score. MIN_SCORE 이하는 뺀다. 반올림하지 않는다.

    귀무에도 **같은 절단**을 건다. 게이트를 못 지날 후보를 귀무에 세면 기준선만
    올라가 실제가 손해를 본다(설계 §1-4). 반올림을 안 하는 이유는 귀무와 관측을
    같은 정밀도로 비교하기 위해서다 — 후보에 실리는 값만 마지막에 반올림한다.
    """
    out: dict[tuple, float] = {}
    for key, e in agg.items():
        nt, nc = e["a"] + e["b"], e["c"] + e["d"]
        if nt == 0 or nc == 0:
            continue
        s = e["a"] / nt - e["c"] / nc
        if s > MIN_SCORE:
            out[key] = s
    return out


def _names(mask: int, bits: dict[str, int]) -> list[str]:
    """비트마스크를 wafer id 목록으로 되돌린다 (보고용)."""
    return sorted(w for w, b in bits.items() if mask & b)
```

- [ ] **Step 2: `find_commonality` 의 이력 조회를 한 번으로 합친다**

현재 `t_rows`·`c_rows` 를 따로 가져온다(`:194-195`). 색인은 전체 wafer 를 한 번에 훑어야 하므로 합친다. `_wafer_meta` 호출은 그대로 둔다.

```python
    with _conn() as conn:
        meta = _wafer_meta(conn, targets + controls)
        rows = _history(conn, targets + controls, legend)
```

- [ ] **Step 3: 집계 루프를 새 함수 호출로 바꾼다**

`find_commonality` 의 "stratum 별 2x2 집계" 블록(현재 `:217-258`) 을 통째로 아래로 바꾼다.

```python
    # ---- wafer 를 비트로 색인 (순열이 이 색인을 재사용한다) ----
    wafers_all = targets + controls
    bits = {w: 1 << i for i, w in enumerate(wafers_all)}
    passed, answer, seen_bits, colmap_all = _build_index(rows, bits, legend)

    # denominator: all 인 레벨은 모든 wafer 가 답할 수 있다 (step_passage).
    universal = {lvl["level"] for lvl in legend if lvl.get("denominator") == "all"}

    strata_masks = []
    for rl, s in sorted(paired.items(), key=lambda kv: (kv[0] is None, kv[0])):
        t_mask = 0
        for w in s["target"]:
            t_mask |= bits[w]
        c_mask = 0
        for w in s["control"]:
            c_mask |= bits[w]
        strata_masks.append((rl, t_mask, c_mask))

    agg, strata_report = _aggregate(strata_masks, passed, answer, seen_bits, universal)

    # 이력이 아예 없는 wafer 는 신호가 아니라 보고 대상이다. stratum 이 스킵돼도
    # 집계와 무관하게 세야 하므로 _aggregate 밖에 둔다.
    t_seen_all_bits = c_seen_all_bits = missing_bits = 0
    for _rl, t_mask, c_mask in strata_masks:
        t_seen_all_bits |= t_mask & seen_bits
        c_seen_all_bits |= c_mask & seen_bits
        missing_bits |= (t_mask | c_mask) & ~seen_bits
    t_seen_all = set(_names(t_seen_all_bits, bits))
    c_seen_all = set(_names(c_seen_all_bits, bits))
    missing = _names(missing_bits, bits)
```

- [ ] **Step 4: score 계산부를 `_score_map` 위에 얹는다**

"score 계산 + 절단" 블록(현재 `:268-295`) 에서 score 를 다시 계산하지 말고 `_score_map` 의 값을 쓴다. 나머지(원시 카운트·colvals·정렬·절단)는 그대로 둔다.

```python
    # ---- score 계산 + 절단 ----
    all_cols = _legend_columns(legend)
    scores = _score_map(agg)
    candidates = []
    for key, score in scores.items():
        level, step, keystr = key
        e = agg[key]
        nt_tot, nc_tot = e["a"] + e["b"], e["c"] + e["d"]
        cov_t = e["a"] / nt_tot
        cov_c = e["c"] / nc_tot
        colvals = colmap_all.get(key, {})
        cand = {
            "level": level,
            "step_seq": step,
            "key": keystr,
            # 원시 카운트 — score 만 보면 6/6 과 2/2 를 구분할 수 없다
            "target_pass": e["a"], "target_total": nt_tot,
            "control_pass": e["c"], "control_total": nc_tot,
            "coverage_target": round(cov_t, 3),
            "coverage_control": round(cov_c, 3),
            "score": round(score, 3),
            "n_strata": e["strata"],
        }
        for col in all_cols:               # legend 컬럼값을 이름별로 (미해당은 None)
            cand[col] = colvals.get(col)
        candidates.append(cand)
```

- [ ] **Step 5: 시간 범위 계산이 합쳐진 rows 를 쓰게 한다**

`_ts(t_rows, t_seen_all)` / `_ts(c_rows, c_seen_all)` 이 이제 없는 변수를 참조한다. `_ts` 는 이미 wafer 집합으로 거르므로 인자만 바꾼다.

```python
            "target_time_range": _ts(rows, t_seen_all),
            "control_time_range": _ts(rows, c_seen_all),
```

`n_target`/`n_control` 도 집합 길이로 바꾼다.

```python
        "n_target": len(t_seen_all), "n_control": len(c_seen_all),
```

- [ ] **Step 6: 전체 회귀 — 동작 변화가 0 인지 확인**

```bash
python -X utf8 -m pytest -q
```

Expected: **208 passed**, 0 failed.

숫자가 다르면 **멈춘다.** 이 태스크는 동작을 바꾸지 않는 리팩터이고, 하나라도 깨졌다면 등가 변환이 아니었다는 뜻이다. 어느 테스트가 어떻게 깨졌는지 보고한다.

- [ ] **Step 7: 커밋**

```bash
git add tools/commonality.py
git commit -m "$(cat <<'EOF'
refactor(commonality): 집계를 라벨의 순수 함수로 분리한다

순열검정은 라벨만 바꾼다. 그런데 집계가 이력 행을 매번 훑는 구조라 그대로
1000번 돌리면 행 읽기를 1000번 반복한다.

- 이력 행을 한 번만 훑어 wafer 를 비트로 색인한다 (_build_index)
- 집계는 stratum 별 (타깃 마스크, 대조군 마스크) 만 받는 순수 함수가 된다 (_aggregate)
- 회차당 비용이 행 수가 아니라 후보 키 수에 비례하고, popcount 는 C 속도다
- 실제와 귀무가 같은 함수를 타므로 규칙이 갈릴 수 없다 (설계 1-4)

동작 변화 없음. 208 passed 그대로.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 순열 라벨을 만들고 후보별 p 를 붙인다

**Files:**
- Modify: `ya_config.py` (상수 1개 추가)
- Modify: `tools/commonality.py` (상수 4개, `_iter_label_sets`·`_permutation_stats` 신설, `find_commonality` 시그니처·본문)
- Modify: `tests/test_commonality.py` (새 테스트 7개)

**Interfaces:**
- Consumes: Task 1 의 `_build_index`·`_aggregate`·`_score_map`
- Produces:
  - `find_commonality(..., n_permutations: int | None = None)` — `None` 이면 config 기본값, `0` 이면 순열을 아예 돌리지 않는다(새 키도 안 생긴다)
  - `_iter_label_sets(strata_masks, n_total, n_iter, rng)` — 회차마다 `[(rl, t_mask, c_mask), ...]` 를 내놓는 제너레이터
  - `_permutation_stats(strata_masks, passed, answer, seen, universal, observed, n_iter, seed) -> dict | None`
    반환 `{"p": dict[key, float], "p_min_possible": float, "n_permutations_total": int, "n_used": int, "null_counts": dict[float, int], "null_max": list[float]}`
  - 후보 dict 에 `p_permutation`·`p_min_possible`·`n_permutations_total` 추가

- [ ] **Step 1: config 상수를 추가한다**

`ya_config.py` 의 `COMMONALITY_PASS_MIN_TARGET`(현재 `:52`) 바로 아래에 붙인다. 그 파일의 기존 형태(`os.getenv` + 형변환)를 그대로 따른다.

```python
COMMONALITY_PERMUTATIONS = int(os.getenv("COMMONALITY_PERMUTATIONS", "1000"))
```

- [ ] **Step 2: 모듈 상수 4개를 추가한다**

`tools/commonality.py` 의 `MIN_SCORE`(현재 `:41`) 아래에 붙인다.

```python
# 순열검정 반복 횟수. 0 이면 순열을 돌리지 않는다 (기존 동작).
N_PERMUTATIONS = getattr(ya_config, "COMMONALITY_PERMUTATIONS", 1000)
# 층화 경우의 수가 이 이하면 전수 열거한다 — 정확하고 더 빠르다.
PERM_EXHAUSTIVE_MAX = 10000
# 고정 시드. 같은 입력이 같은 p 를 내야 테스트도 감사도 성립한다.
PERM_SEED = 20260809
# FDR 표의 임계값 사다리. 실데이터를 보고 조정한다 — 지금 못 박지 않는다.
FDR_THRESHOLDS = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4)
```

파일 상단 import 에 세 줄을 더한다.

```python
import itertools
import math
import random
```

- [ ] **Step 3: 라벨 생성기를 쓴다**

`_score_map` 아래에 붙인다.

```python
def _bits_of(mask: int) -> list[int]:
    """마스크를 개별 비트 목록으로. 순열이 이 목록에서 뽑는다."""
    out = []
    while mask:
        low = mask & -mask
        out.append(low)
        mask ^= low
    return out


def _n_permutations_total(strata_masks) -> int:
    """층화 섞기의 경우의 수 = stratum 별 조합 수의 곱.

    lot 을 가로질러 섞지 않으므로 전체 섞기(n! 급)보다 훨씬 작다. 이 값이 작다는
    것 자체가 "이 데이터로는 p 를 그 아래로 못 내린다" 는 뜻이라 결과에 싣는다.
    """
    total = 1
    for _rl, t_mask, c_mask in strata_masks:
        pool = (t_mask | c_mask).bit_count()
        total *= math.comb(pool, t_mask.bit_count())
    return total


def _iter_label_sets(strata_masks, n_total: int, n_iter: int, rng):
    """회차마다 [(rl, t_mask, c_mask), ...] 를 내놓는다.

    **stratum 안에서만 섞는다.** lot 을 가로지르면 lot 효과가 신호로 잡힌다.
    lot A 에 언제나 타깃 8장이 남아야, "두께 상위에 타깃이 몰린다" 는 lot 효과가
    귀무에도 그대로 남아 올바르게 기각된다 (설계 §2-2).

    경우의 수가 적으면 전수 열거한다 — 정확하고 더 빠르다. 그때 **관측 라벨은
    건너뛴다.** 관측을 귀무 표본에 넣으면 "넘은 횟수" 가 항상 1 이상이 되어
    p_min_possible 이 절대 달성되지 않고, 공간 부족을 읽을 수 없게 된다.
    """
    pools = [(rl, _bits_of(t_mask | c_mask), t_mask.bit_count(), t_mask, c_mask)
             for rl, t_mask, c_mask in strata_masks]

    if n_total <= PERM_EXHAUSTIVE_MAX:
        per_stratum = [list(itertools.combinations(pool, k))
                       for _rl, pool, k, _t, _c in pools]
        for combo in itertools.product(*per_stratum):
            labels, is_observed = [], True
            for (rl, _pool, _k, t_mask, c_mask), picked in zip(pools, combo):
                t = 0
                for b in picked:
                    t |= b
                if t != t_mask:
                    is_observed = False
                labels.append((rl, t, (t_mask | c_mask) ^ t))
            if is_observed:
                continue
            yield labels
    else:
        for _ in range(n_iter):
            labels = []
            for rl, pool, k, t_mask, c_mask in pools:
                t = 0
                for b in rng.sample(pool, k):
                    t |= b
                labels.append((rl, t, (t_mask | c_mask) ^ t))
            yield labels
```

- [ ] **Step 4: 귀무 분포를 재는 함수를 쓴다**

바로 아래에 붙인다. FDR 재료(`null_counts`)와 family-wise 재료(`null_max`)도 여기서 같이 모은다. 회차를 두 번 돌 이유가 없다.

```python
def _permutation_stats(strata_masks, passed, answer, seen, universal,
                       observed: dict[tuple, float], n_iter: int, seed: int):
    """라벨을 섞어 귀무 분포를 재고 후보별 p 를 낸다.

    **한 회차 = 라벨 한 번 섞기 -> 전 후보 계산.** 후보마다 따로 섞으면 후보 간
    상관이 깨진다. 같은 라벨을 쓰면 "같은 스텝의 키들이 함께 움직인다" 는 성질이
    귀무에도 남아, 상관 때문에 가짜가 무더기로 나오는 현상이 기준선에 자동
    반영된다 (설계 §2-5).

    p = (귀무가 관측 이상인 횟수 + 1) / (섞은 횟수 + 1). 1을 더하는 이유는 0번
    넘었다고 p = 0 이 될 수는 없기 때문이다.
    """
    n_total = _n_permutations_total(strata_masks)
    exhaustive = n_total <= PERM_EXHAUSTIVE_MAX
    n_used = (n_total - 1) if exhaustive else n_iter
    if n_used <= 0:
        return None                    # 섞을 수 있는 다른 배치가 없다

    rng = random.Random(seed)
    exceed = {k: 0 for k in observed}
    null_counts = {t: 0 for t in FDR_THRESHOLDS}
    null_max: list[float] = []

    for labels in _iter_label_sets(strata_masks, n_total, n_iter, rng):
        null_agg, _ = _aggregate(labels, passed, answer, seen, universal)
        null_scores = _score_map(null_agg)
        for key, obs in observed.items():
            if null_scores.get(key, float("-inf")) >= obs:
                exceed[key] += 1
        vals = list(null_scores.values())
        for t in FDR_THRESHOLDS:
            null_counts[t] += sum(1 for v in vals if v >= t)
        null_max.append(max(vals) if vals else 0.0)

    return {
        "p": {k: (n + 1) / (n_used + 1) for k, n in exceed.items()},
        "p_min_possible": 1 / (n_used + 1),
        "n_permutations_total": n_total,
        "n_used": n_used,
        "null_counts": null_counts,
        "null_max": null_max,
    }
```

- [ ] **Step 5: `find_commonality` 가 순열을 돌리고 후보에 p 를 붙인다**

시그니처에 인자를 더한다.

```python
def find_commonality(target_wafers: list[str], control_wafers: list[str],
                     legend: list[dict] | None = None,
                     top_k: int | None = None,
                     n_permutations: int | None = None) -> dict:
```

본문 맨 앞의 기본값 처리 옆에 한 줄 더한다.

```python
    n_permutations = N_PERMUTATIONS if n_permutations is None else n_permutations
```

Task 1 Step 4 가 만든 "score 계산 + 절단" 블록의 순서를 아래로 바꾼다. `scores` 가 순열 블록보다 먼저 있어야 하고, 후보가 하나도 없으면 잴 것이 없으므로 건너뛴다.

```python
    # ---- score 계산 + 절단 ----
    all_cols = _legend_columns(legend)
    scores = _score_map(agg)

    # ---- 순열검정 (라벨을 섞어 "탐색만으로 얼마나 좋아 보이는가" 를 실측) ----
    perm = None
    if n_permutations and scores:
        perm = _permutation_stats(strata_masks, passed, answer, seen_bits,
                                  universal, scores, n_permutations, PERM_SEED)

    candidates = []
    for key, score in scores.items():
        ...   # (Task 1 Step 4 의 루프 본문 그대로)
```

후보 생성 루프 안에서 p 를 붙인다 — `cand` dict 를 만든 직후, `for col in all_cols:` 앞에 넣는다.

```python
        if perm:
            cand["p_permutation"] = round(perm["p"][key], 4)
            cand["p_min_possible"] = round(perm["p_min_possible"], 4)
            cand["n_permutations_total"] = perm["n_permutations_total"]
```

- [ ] **Step 6: `note` 에 p 읽는 법을 적는다**

`ok` 경로의 `note` 문자열 끝에 이어 붙인다 (기존 문장은 건드리지 않는다).

```python
                 "p_permutation 은 라벨을 root_lot 안에서 섞었을 때 이만한 분리가 "
                 "나오는 비율이다. p_min_possible 이 크면(예: 0.1 이상) 표본이 작아 "
                 "p 를 그 아래로 내릴 수 없다는 뜻이지 신호가 약하다는 뜻이 아니다."
```

- [ ] **Step 7: 순열 테스트 7개를 쓴다**

`tests/test_commonality.py` 맨 아래에 붙인다. 파일 상단 import 에 `itertools`·`random` 이 없으면 더한다.

```python
# --------------------------------------------------------------- 순열검정

def test_permutation_p_is_deterministic(tmp_path, monkeypatch):
    """같은 입력이 같은 p 를 내야 한다 — 시드가 고정돼 있다.

    감사 기록에 실리는 값이라 실행마다 흔들리면 안 된다.
    """
    t, c = ["T1", "T2", "T3"], ["C1", "C2", "C3"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    first = cm.find_commonality(t, c)
    second = cm.find_commonality(t, c)
    assert [x["p_permutation"] for x in first["candidates"]] == \
           [x["p_permutation"] for x in second["candidates"]]


def test_small_group_cannot_reach_a_small_p(tmp_path, monkeypatch):
    """2대2 는 완전 분리여도 p 를 0.167 아래로 못 내린다 — 공간이 없다.

    4장 중 2장을 타깃으로 고르는 경우의 수가 6이고 관측 라벨을 빼면 5회다.
    p 는 아무리 좋아도 1/(5+1) = 0.167 이다. 이것이 "2대2 의 score 1.0" 이
    확신이 아니라는 것을 숫자로 말하는 자리다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    eq = _find(res, "equipment", "ETCH9")
    assert eq["score"] == 1.0                      # 완전 분리인데도
    assert eq["n_permutations_total"] == 6
    assert eq["p_min_possible"] == 0.1667
    assert eq["p_permutation"] == 0.1667           # 최소값에 닿았다 = 귀무가 못 넘었다


def test_larger_group_with_the_same_separation_gets_a_much_smaller_p(tmp_path, monkeypatch):
    """같은 score 1.0 이라도 표본이 크면 p 가 훨씬 작다 — 이것이 순열검정의 일이다.

    6대6 은 경우의 수가 924 라 p 가 0.001 수준까지 내려간다. score 만 보면
    2대2 와 6대6 이 똑같이 1.0 인데, p 가 그 둘을 갈라놓는다.
    """
    t = [f"T{i}" for i in range(1, 7)]
    c = [f"C{i}" for i in range(1, 7)]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    eq = _find(res, "equipment", "ETCH9")
    assert eq["score"] == 1.0
    assert eq["n_permutations_total"] == 924
    assert eq["p_permutation"] < 0.01


def test_shuffling_keeps_each_lot_target_count(tmp_path, monkeypatch):
    """섞기는 root_lot 안에서만 한다 — lot 별 타깃 수가 회차마다 그대로여야 한다.

    lot 을 가로질러 섞으면 lot 효과가 신호로 잡힌다(설계 §2-2). 그 방어가
    실제로 작동하는지는 여기서만 볼 수 있다 - 결과 dict 에는 안 드러난다.
    """
    rng = random.Random(0)
    # lot A: 타깃 2 대조군 1,  lot B: 타깃 1 대조군 2
    strata = [("A", 0b000011, 0b000100), ("B", 0b001000, 0b110000)]
    n_total = cm._n_permutations_total(strata)
    seen_any = False
    for labels in cm._iter_label_sets(strata, n_total, 50, rng):
        seen_any = True
        for (rl, t, c), (_rl0, t0, c0) in zip(labels, strata):
            assert t.bit_count() == t0.bit_count()      # 타깃 수 보존
            assert t | c == t0 | c0                     # 같은 wafer 풀
            assert t & c == 0                           # 겹치지 않는다
    assert seen_any


def test_observed_labeling_is_not_part_of_the_null(tmp_path, monkeypatch):
    """전수 열거에서 관측 라벨을 뺀다 — 안 빼면 최소 p 에 절대 못 닿는다.

    관측은 자기 자신 이상이므로 귀무에 넣으면 '넘은 횟수' 가 늘 1 이상이 되고,
    p_min_possible 이 달성 불가능한 값이 되어 공간 부족을 읽을 수 없게 된다.
    """
    rng = random.Random(0)
    strata = [("A", 0b0011, 0b1100)]                    # 타깃 2 대조군 2 -> 6가지
    n_total = cm._n_permutations_total(strata)
    assert n_total == 6
    label_sets = list(cm._iter_label_sets(strata, n_total, 0, rng))
    assert len(label_sets) == 5                         # 관측 하나가 빠졌다
    assert all(labels[0][1] != 0b0011 for labels in label_sets)


def test_permutation_can_be_turned_off(tmp_path, monkeypatch):
    """n_permutations=0 이면 순열을 아예 안 돌리고 키도 안 생긴다.

    비용이 드는 계산이라 끌 수 있어야 하고, 껐을 때 결과는 순열 도입 전과 같아야
    한다 - 껐다 켜는 것이 다른 답을 내면 둘 중 하나는 틀린 것이다.
    """
    t, c = ["T1", "T2", "T3"], ["C1", "C2", "C3"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    off = cm.find_commonality(t, c, n_permutations=0)
    on = cm.find_commonality(t, c)
    assert "p_permutation" not in off["candidates"][0]
    assert "p_permutation" in on["candidates"][0]
    strip = lambda r: [{k: v for k, v in x.items() if not k.startswith(("p_", "n_perm"))}
                       for x in r["candidates"]]
    assert strip(off) == strip(on)          # 순열은 후보 자체를 바꾸지 않는다


def test_enumeration_and_sampling_agree(tmp_path, monkeypatch):
    """전수 열거와 무작위 표본이 같은 결론을 내야 한다 (설계 검증 목록).

    같은 데이터를 두 경로로 돌린다. 6대6 은 경우의 수가 924 라 기본값이면 전수
    열거를 타는데, 열거 상한을 낮춰 무작위 표본 경로로 강제한다. 두 p 가 크게
    벌어지면 둘 중 하나가 틀린 것이다 - 표본이 편향됐거나 열거가 빠뜨렸거나다.
    """
    t = [f"T{i}" for i in range(1, 7)]
    c = [f"C{i}" for i in range(1, 7)]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    exhaustive = _find(cm.find_commonality(t, c), "equipment", "ETCH9")
    assert exhaustive["n_permutations_total"] == 924        # 전수 경로였다

    monkeypatch.setattr(cm, "PERM_EXHAUSTIVE_MAX", 10)      # 무작위 표본으로 강제
    sampled = _find(cm.find_commonality(t, c), "equipment", "ETCH9")
    assert sampled["n_permutations_total"] == 924           # 경우의 수는 그대로 보고
    assert abs(sampled["p_permutation"] - exhaustive["p_permutation"]) < 0.01
```

- [ ] **Step 8: 테스트를 돌린다**

```bash
python -X utf8 -m pytest tests/test_commonality.py -q
```

Expected: 전부 PASS.

`test_small_group_cannot_reach_a_small_p` 의 기대값 `0.1667` 이 안 맞으면 **멈추고 보고한다.** `1/6 = 0.16666...` 이 `round(x, 4)` 로 `0.1667` 이 되는지는 구현자가 실측으로 확인한다. 반올림 자릿수를 바꾸는 것도 방법이지만, 기대값과 구현 중 어느 쪽을 고칠지는 임의로 정하지 말고 보고한다.

- [ ] **Step 9: 전체 회귀**

```bash
python -X utf8 -m pytest -q
```

Expected: **215 passed**, 0 failed.

기존 208개 중 하나라도 깨지면 멈추고 보고한다. 순열이 기본으로 켜져 있으므로 기존 테스트도 순열을 돌린다 — 깨진다면 후보 dict 에 키가 늘어난 것을 견디지 못하는 단언이 있다는 뜻이고, 그 자체가 보고할 사실이다.

- [ ] **Step 10: 커밋**

```bash
git add ya_config.py tools/commonality.py tests/test_commonality.py
git commit -m "$(cat <<'EOF'
feat(commonality): 순열검정으로 후보별 p 를 낸다

score 는 "얼마나 갈렸나" 만 말하고 "우연일 수 있나" 는 말하지 않는다. 분모를
좁힌 뒤로 2대2 의 score 1.0 이 게이트를 통과하게 돼 이 구분이 더 급해졌다.

- 라벨을 root_lot 안에서만 섞는다. 가로지르면 lot 효과가 신호로 잡힌다
- 경우의 수가 적으면 전수 열거하고, 관측 라벨은 귀무에서 뺀다
- p = (넘은 횟수 + 1) / (섞은 횟수 + 1), p_min_possible 과 경우의 수를 함께 싣는다
- 한 회차 = 라벨 한 번 섞기 -> 전 후보 계산 (후보 간 상관을 귀무에도 남긴다)
- n_permutations=0 으로 끌 수 있다. 껐을 때 후보는 도입 전과 같다

게이트는 바꾸지 않았다. p 는 판단 재료로 싣기만 한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: FDR 표와 family-wise p 를 낸다

후보를 여러 개 내면 그중 몇 개가 가짜인지 말해야 한다. 공식(Benjamini-Hochberg 등)은 후보 간 독립이나 양의 상관을 가정하는데 여기는 상관이 크다. **대신 섞은 데이터에서 가짜가 몇 개 나오는지 직접 센다.** 재료는 Task 2 가 이미 모아 뒀다.

**Files:**
- Modify: `tools/commonality.py` (`_fdr_table` 신설, 결과 dict 에 `fdr_table`·`p_family_wise`)
- Modify: `tests/test_commonality.py` (새 테스트 5개)

**Interfaces:**
- Consumes: Task 2 의 `_permutation_stats` 반환 중 `null_counts`·`null_max`·`n_used`
- Produces:
  - `_fdr_table(scores, null_counts, n_used) -> list[dict]` — 각 행 `{"threshold", "n_observed", "n_null_mean", "fdr"}`
  - 결과 최상위 `fdr_table: list[dict]`, `p_family_wise: float | None`

- [ ] **Step 1: FDR 표 함수를 쓴다**

`_permutation_stats` 아래에 붙인다.

```python
def _fdr_table(scores: dict, null_counts: dict, n_used: int) -> list[dict]:
    """임계값별로 "이 목록에 가짜가 몇 개 섞여 있나" 를 센다.

    공식도 가정도 없다. 실제에서 임계를 넘은 후보 수와, 라벨을 섞었을 때 같은
    임계를 넘은 후보 수의 평균을 나란히 놓는다. 출력이 "5개 중 0.6개쯤이 가짜"
    라서 엔지니어가 p 값 해석 없이 바로 쓴다 (설계 §3).

    후보가 하나도 없는 임계는 싣지 않는다 - 읽을 것이 없다.
    """
    vals = list(scores.values())
    table = []
    for t in FDR_THRESHOLDS:
        n_obs = sum(1 for v in vals if v >= t)
        if n_obs == 0:
            continue
        n_null = null_counts.get(t, 0) / n_used
        table.append({
            "threshold": t,
            "n_observed": n_obs,
            "n_null_mean": round(n_null, 3),
            "fdr": round(min(1.0, n_null / n_obs), 3),
        })
    return table
```

- [ ] **Step 2: family-wise p 를 낸다**

바로 아래에 붙인다.

```python
def _family_wise_p(scores: dict, null_max: list[float], n_used: int) -> float | None:
    """1등이 우연일 확률. 회차별 최댓값 분포에 관측 1등을 대본다.

    재료(null_max)를 순열 루프에서 이미 모았으므로 계산을 다시 하지 않는다.
    후보별 p 는 "이 후보 하나" 를, 이 값은 "전체를 통틀어 최고" 를 말한다.
    """
    if not scores or not null_max:
        return None
    best = max(scores.values())
    exceed = sum(1 for v in null_max if v >= best)
    return round((exceed + 1) / (n_used + 1), 4)
```

- [ ] **Step 3: 결과 dict 에 싣는다**

`find_commonality` 의 `result = {...}` 안, `"truncated": truncated,` 다음 줄에 추가한다.

```python
        "fdr_table": _fdr_table(scores, perm["null_counts"], perm["n_used"]) if perm else [],
        "p_family_wise": _family_wise_p(scores, perm["null_max"], perm["n_used"]) if perm else None,
```

**주의:** `fdr_table` 은 `top_k` 로 자르기 **전**의 `scores` 를 센다. 잘린 뒤를 세면 "몇 개가 가짜인가" 의 분모가 표시 개수에 좌우돼 뜻이 달라진다.

- [ ] **Step 4: FDR 테스트 5개를 쓴다**

`tests/test_commonality.py` 맨 아래에 붙인다.

```python
# -------------------------------------------------------------------- FDR

def _noise_db(tmp_path, monkeypatch, n_steps=10):
    """신호가 없는데 후보는 많이 나오는 데이터.

    6장을 3장씩 나누는 방법이 20가지인데, 스텝마다 서로 다른 3장 조합이 ETCH9 를
    쓰게 한다. 어느 스텝 하나는 우연히 타깃과 정확히 일치해 score 1.0 이 된다.
    실제 원인은 없고 '많이 시도했다' 는 것뿐이다 - FDR 이 잡아야 하는 상황이다.
    """
    wafers = ["T1", "T2", "T3", "C1", "C2", "C3"]
    subsets = list(itertools.combinations(wafers, 3))[:n_steps]
    ys = [_y(w, "A45Z5") for w in wafers]
    hs = []
    for i, sub in enumerate(subsets):
        for w in wafers:
            eqp = "ETCH9" if w in sub else "ETCH8"
            hs.append(_h(w, f"S{i:02d}", eqp, "1"))
    _make_db(tmp_path, monkeypatch, ys, hs)
    return ["T1", "T2", "T3"], ["C1", "C2", "C3"]


def test_fdr_table_has_the_expected_shape(tmp_path, monkeypatch):
    """표의 각 행은 임계·실제 개수·귀무 평균·추정 가짜 비율 넷을 담는다."""
    t, c = _noise_db(tmp_path, monkeypatch)
    res = cm.find_commonality(t, c)
    assert res["fdr_table"]
    for row in res["fdr_table"]:
        assert set(row) == {"threshold", "n_observed", "n_null_mean", "fdr"}
        assert row["n_observed"] > 0
        assert 0.0 <= row["fdr"] <= 1.0
    thresholds = [r["threshold"] for r in res["fdr_table"]]
    assert thresholds == sorted(thresholds, reverse=True)


def test_pure_noise_gets_a_high_fdr(tmp_path, monkeypatch):
    """많이 시도해서 얻은 score 1.0 은 귀무에서도 그만큼 나온다.

    원인이 없는데 후보가 나온 상황이다. 표가 "이 목록은 거의 다 가짜" 라고
    말해야 한다 - 이걸 못 하면 FDR 을 넣은 의미가 없다.
    """
    t, c = _noise_db(tmp_path, monkeypatch)
    res = cm.find_commonality(t, c)
    top = res["fdr_table"][0]
    assert top["threshold"] == 0.9
    assert top["n_observed"] >= 1
    assert top["fdr"] >= 0.5


def test_real_signal_in_a_large_group_gets_a_low_fdr(tmp_path, monkeypatch):
    """진짜 신호는 귀무가 못 따라온다. 대조군이다."""
    t = [f"T{i}" for i in range(1, 7)]
    c = [f"C{i}" for i in range(1, 7)]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    top = res["fdr_table"][0]
    assert top["threshold"] == 0.9
    assert top["fdr"] < 0.05


def test_family_wise_p_is_carried(tmp_path, monkeypatch):
    """1등이 우연일 확률. 잡음에서는 크고 진짜 신호에서는 작아야 한다."""
    t, c = _noise_db(tmp_path, monkeypatch)
    noisy = cm.find_commonality(t, c)

    t2 = [f"T{i}" for i in range(1, 7)]
    c2 = [f"C{i}" for i in range(1, 7)]
    ys = [_y(w, "A45Z5") for w in t2 + c2]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t2]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c2]
    _make_db(tmp_path, monkeypatch, ys, hs)
    strong = cm.find_commonality(t2, c2)

    assert strong["p_family_wise"] < noisy["p_family_wise"]


def test_no_fdr_table_when_permutation_is_off(tmp_path, monkeypatch):
    """순열을 끄면 셀 재료가 없다. 빈 표를 내되 키는 유지한다."""
    t, c = _noise_db(tmp_path, monkeypatch)
    res = cm.find_commonality(t, c, n_permutations=0)
    assert res["fdr_table"] == []
    assert res["p_family_wise"] is None
```

- [ ] **Step 5: 테스트를 돌린다**

```bash
python -X utf8 -m pytest tests/test_commonality.py -q
```

Expected: 전부 PASS.

`test_pure_noise_gets_a_high_fdr` 의 `>= 0.5` 나 `test_real_signal...` 의 `< 0.05` 가 안 맞으면 **멈추고 실제 값을 보고한다.** 기준선을 임의로 완화하지 마라 — 값이 예상과 다르면 계산이 틀렸을 가능성이 먼저다.

- [ ] **Step 6: 전체 회귀**

```bash
python -X utf8 -m pytest -q
```

Expected: **220 passed**, 0 failed.

- [ ] **Step 7: 커밋**

```bash
git add tools/commonality.py tests/test_commonality.py
git commit -m "$(cat <<'EOF'
feat(commonality): 임계값별 FDR 표와 family-wise p 를 낸다

후보를 여러 개 내면 그중 몇 개가 가짜인지 말해야 한다. 공식은 후보 간 독립을
가정하는데 여기는 상관이 크므로, 섞은 데이터에서 가짜가 몇 개 나오는지 직접 센다.

- 임계값별로 실제 후보 수와 귀무 평균을 나란히 실어 추정 가짜 비율을 낸다
- 회차별 최댓값을 모아 "1등이 우연일 확률" 을 계산 없이 추가로 낸다
- 표는 top_k 로 자르기 전 후보를 센다 (분모가 표시 개수에 좌우되면 뜻이 달라진다)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: p 를 소비자까지 잇는다

값을 계산만 하고 리포트에 안 내보내면 아무도 못 본다. **게이트 판정에는 쓰지 않는다.** `domain/engine.py` 의 `_passes()` 는 손대지 않는다.

**Files:**
- Modify: `domain/engine.py` (후보 dict 에 키 1개)
- Modify: `graph/evidence.py` (`Claim` 필드 1개, `build_bundle` 1줄, `format_evidence_line` 1줄)
- Modify: `tests/test_evidence.py` (새 테스트 3개 + `asdict` import)
- Modify: `tests/test_engine.py` (새 테스트 1개)

**Interfaces:**
- Consumes: Task 2 의 후보 dict `p_permutation`
- Produces: `Claim.p_permutation: float | None`, 근거 줄 끝에 `· 순열 p {값}`

- [ ] **Step 1: engine 이 p 를 통과시킨다**

`domain/engine.py` 의 후보 매핑(현재 `:50-51` 의 `coverage_control` 다음)에 한 줄 더한다.

```python
            # 게이트는 이 값을 **판정에 쓰지 않는다**(_passes 참조). 리포트와 감사
            # 기록에 흐르게 하는 것이 목적이다 - 자동 차단은 실데이터를 본 뒤에 얹는다.
            "p_permutation": cand.get("p_permutation"),
```

- [ ] **Step 2: `Claim` 에 필드를 더한다**

`graph/evidence.py` 의 `Claim` 마지막 필드(`control_total`) 아래에 붙인다. **기본값이 있어야** 기존 생성 호출이 안 깨진다.

```python
    p_permutation: float | None = None
```

`build_bundle` 의 `Claim(...)` 호출(현재 `:100` 의 `control_total` 다음)에 한 줄 더한다.

```python
                p_permutation=c.get("p_permutation"),
```

- [ ] **Step 3: 근거 줄에 싣는다**

`format_evidence_line` 을 바꾼다. p 가 없으면(순열을 껐거나 옛 결과) 줄 모양이 예전 그대로여야 한다.

```python
def format_evidence_line(claim: dict) -> str:
    """Claim 사전(`asdict(Claim)` 결과)을 사람이 읽는 근거 한 줄로 렌더링한다.

    게이트 승인 verdict(`graph/nodes.py`)와 리포트 `[근거]` 줄(`report_node`)이
    같은 본문을 문자 그대로 복제하던 것을 여기 하나로 모았다.
    """
    line = (f"{claim['claim_id']} · 분리 점수 {claim['score']} · "
            f"타깃 {claim['target_pass']}/{claim['target_total']} 통과 · "
            f"대조군 {claim['control_pass']}/{claim['control_total']} 통과")
    p = claim.get("p_permutation")
    if p is not None:
        line += f" · 순열 p {p}"
    return line
```

- [ ] **Step 4: 기존 테스트에서 근거 줄을 단언하는 곳을 찾는다**

```bash
python -X utf8 -m pytest -q
```

깨진 테스트가 `format_evidence_line` 결과 문자열을 단언하는 것이면, **기대 문자열에 `· 순열 p ...` 를 더해 갱신한다.** 다른 이유로 깨졌으면 멈추고 보고한다.

- [ ] **Step 5: 새 테스트 3개를 쓴다**

`tests/test_evidence.py` 맨 아래에 붙인다. 그 파일에는 이미 `_finding(tool, hypothesis_id, status, candidates)` 헬퍼와 `CAND_PASS` 픽스처(`:17-20`)가 있으니 그대로 쓴다. 파일 상단에 `from dataclasses import asdict` 를 더한다.

```python
def test_permutation_p_survives_the_bundle():
    """순열 p 가 후보 dict 에서 Claim 까지 살아 간다.

    score 단언이 함께 있는 이유: build_bundle 이 .get() 기본값을 쓰므로 후보에
    키가 늘 때 매핑이 어긋나면 score 가 조용히 0 이 된다. 실데이터에서 게이트가
    통째로 침묵하는 경로라 같이 못 박는다 (설계 §5).
    """
    cand = {**CAND_PASS, "p_permutation": 0.0123}
    b = evidence.build_bundle([_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                                        "ok", [cand])])
    c = b.claims[CAND_PASS["claim_id"]]
    assert c.p_permutation == 0.0123
    assert c.score == 1.0


def test_missing_permutation_p_is_none_not_zero():
    """순열을 껐거나 옛 결과면 p 가 없다. 0.0 으로 뭉개면 안 된다.

    p = 0.0 은 "우연일 리 없다" 로 읽힌다. 없는 것과 아주 유의한 것을 같은 값으로
    적으면 정확히 반대 방향의 오독이 된다.
    """
    b = evidence.build_bundle([_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                                        "ok", [CAND_PASS])])
    assert b.claims[CAND_PASS["claim_id"]].p_permutation is None


def test_evidence_line_carries_p_only_when_present():
    """근거 줄에 p 를 싣되, 없으면 예전 모양 그대로여야 한다."""
    with_p = evidence.build_bundle([_finding(
        "hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok",
        [{**CAND_PASS, "p_permutation": 0.0123}])])
    line = evidence.format_evidence_line(asdict(with_p.claims[CAND_PASS["claim_id"]]))
    assert line.endswith("· 순열 p 0.0123")

    without = evidence.build_bundle([_finding(
        "hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS])])
    line2 = evidence.format_evidence_line(asdict(without.claims[CAND_PASS["claim_id"]]))
    assert "순열 p" not in line2
    assert line2.endswith("대조군 0/6 통과")
```

- [ ] **Step 6: engine 통과 테스트를 쓴다**

`tests/test_engine.py` 맨 아래에 붙인다. 그 파일의 `fx_db` 픽스처(`:14-41`)를 그대로 쓴다. 불량군 3장·대조군 3장이 한 root_lot(`R1`)에 있으므로 경우의 수는 `C(6,3) = 20`, 관측을 뺀 19회, 최소 p 는 `1/20 = 0.05` 다.

```python
def test_evaluate_carries_permutation_p_without_using_it_in_the_verdict(fx_db):
    """p 는 실려 나가되 판정에는 안 쓴다.

    3대3 은 6장 중 3장을 고르는 20가지뿐이라 완전 분리여도 p 가 0.05 아래로
    못 내려간다. passes 는 그와 무관하게 score·target_pass 로만 정해진다 -
    자동 차단은 실데이터를 본 뒤에 얹는다(설계 §2-3).
    """
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH},
                          ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    ch = {c["key"]: c for c in res["candidates"]}["ETCH9_B"]
    assert ch["p_permutation"] == 0.05
    assert ch["passes"] is True          # p 가 최소값이어도 판정은 그대로
```

- [ ] **Step 7: 전체 회귀**

```bash
python -X utf8 -m pytest -q
```

Expected: **224 passed**, 0 failed.

- [ ] **Step 8: 커밋**

```bash
git add domain/engine.py graph/evidence.py tests/
git commit -m "$(cat <<'EOF'
feat(evidence): 순열 p 를 근거 줄까지 흘린다

계산만 하고 안 내보내면 아무도 못 본다. Claim 에 실어 리포트와 감사 기록에
같이 남긴다.

- engine 이 p_permutation 을 통과시킨다. 게이트 판정에는 쓰지 않는다
- Claim 에 기본값 있는 필드로 더해 기존 생성 호출을 안 깬다
- 근거 줄은 p 가 없으면 예전 모양 그대로다

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 뒤집힌 설계 원칙을 다시 쓰고 성능을 측정한다

`tools/commonality.py:16` 에 **"p-value 를 계산하지 않는다"** 가 설계 원칙으로 박혀 있다. 이 계획이 그것을 정면으로 뒤집는다. 조용히 바꾸면 다음 사람이 원칙이 언제 왜 바뀌었는지 못 찾는다.

**Files:**
- Modify: `tools/commonality.py` (모듈 docstring)
- Modify: `domain/hypotheses.yaml` (세 가설 description)
- Modify: `docs/superpowers/specs/2026-08-08-metro-commonality-design.md` (§2-3 의 두 서술 정정)

**Interfaces:**
- Consumes: Task 2·3 의 출력 계약
- Produces: 없음 (문서만)

- [ ] **Step 1: 모듈 docstring 의 원칙을 교체한다**

`tools/commonality.py:16-17` 의 항목을 아래로 바꾼다.

기존:
```
- **p-value 를 계산하지 않는다.** 후보가 수천 개라 다중비교로 유의성 주장이 불가능하다.
  원시 카운트(a/b/c/d)를 그대로 실어, "결론이 아니라 후보"임이 드러나게 한다.
```

교체:
```
- **p 를 낸다 — 단, 공식이 아니라 직접 세기로.** 예전에는 "후보가 수천 개라 다중비교로
  유의성 주장이 불가능하다" 는 이유로 p 를 내지 않았다. 순열 기반 FDR 이 그 전제를
  없앴다. 공식(BH 등)의 독립 가정에 기대는 대신, 라벨을 섞은 데이터에서 가짜가 몇 개
  나오는지 실측해 임계값별로 싣는다. 원시 카운트(a/b/c/d)는 그대로 함께 실어,
  "결론이 아니라 후보"임이 계속 드러나게 한다.
- **섞기는 root_lot 안에서만.** 집계가 층화돼 있으므로 귀무도 같은 축으로 섞어야
  lot 효과가 신호로 둔갑하지 않는다.
```

- [ ] **Step 2: 가설 description 에 p 의 뜻을 적는다**

`domain/hypotheses.yaml` 의 세 가설(`eqp_ch_commonality`:3-8·`ppid_commonality`:15-20·`step_passage_commonality`:26-36) description 각각의 **맨 끝에** 아래 세 줄을 그대로 이어 붙인다. 셋 다 같은 문장을 쓴다 — 세 도구의 계약이 같기 때문이다. **LLM 에 그대로 나가는 텍스트**이므로 문구를 바꾸지 마라. 기존 문장은 건드리지 않는다.

```yaml
    p_permutation 은 라벨을 root_lot 안에서 섞었을 때 이만한 분리가 나오는 비율이다.
    p_min_possible 이 크면(예: 0.1 이상) 표본이 작아 p 를 그 아래로 내릴 수 없다는
    뜻이지 신호가 약하다는 뜻이 아니다. 결과 최상위의 fdr_table 은 임계값별로 "이
    목록에 가짜가 몇 개 섞여 있는가" 를 센 것이다.
```

들여쓰기는 각 description 의 기존 본문과 같은 4칸이다 (`|` 블록 스칼라 안이라 들여쓰기가 틀리면 YAML 이 깨지거나 문장이 잘린다).

- [ ] **Step 3: 설계 문서의 두 서술을 정정한다**

이 계획 맨 위 "설계에서 고쳐 쓰는 것 두 가지" 를 설계 문서에 반영한다. 설계 문서는 3단계에서 다시 읽히는 **살아 있는 문서**라 틀린 채로 두면 안 된다.

1. §2-3 의 `1/(6+1) = 0.14` 를 `1/6 = 0.167` 로 고치고, 관측 라벨을 귀무에서 빼는 이유를 한 줄로 남긴다
2. §2-3 의 "`p_min_possible` 과 같으면 공간 부족" 서술을 "**`p_min_possible` 자체가 크면** 공간 부족" 으로 고친다. 표본이 커도 신호가 강하면 `p == p_min_possible` 이 되므로 그 자체는 공간 부족 신호가 아니다

- [ ] **Step 4: 성능을 측정해 기록한다**

사용자가 실데이터 규모를 모른다고 했으므로 **지금 아는 수치를 남긴다.** 나중에 느리다는 말이 나오면 이 숫자가 기준선이 된다.

```bash
python -X utf8 -m pytest -q --durations=10
```

그리고 더미 DB 전체로 한 번 잰다.

```bash
python -X utf8 -c "
import time, sqlite3, ya_config
from tools import commonality as cm
conn = sqlite3.connect(ya_config.DB_PATH)
ws = [r[0] for r in conn.execute('select wafer_id from yield').fetchall()]
t, c = ws[:10], ws[10:60]
for n in (0, 1000):
    s = time.perf_counter()
    res = cm.find_commonality(t, c, n_permutations=n)
    print(f'n_permutations={n:5d}  {time.perf_counter()-s:6.2f}s  '
          f'status={res[\"status\"]}  후보={len(res[\"candidates\"])}')
"
```

`ya_config.DB_PATH` 이름이 다르면 그 파일을 열어 실제 이름을 쓴다. 두 숫자(끈 것 / 1000회)를 보고서에 적는다.

**1000회가 30초를 넘으면 멈추고 보고한다.** 대화형 분석이라 그 이상은 쓸 수 없고, 그때는 기본 반복 횟수를 낮출지 최적화를 더 할지 사람이 정해야 한다.

- [ ] **Step 5: 전체 회귀**

```bash
python -X utf8 -m pytest -q
```

Expected: **224 passed** (문서만 고쳤으므로 변화 없어야 한다)

- [ ] **Step 6: 커밋**

```bash
git add tools/commonality.py domain/hypotheses.yaml "docs/superpowers/specs/2026-08-08-metro-commonality-design.md"
git commit -m "$(cat <<'EOF'
docs(commonality): 뒤집힌 설계 원칙을 다시 쓴다

"p-value 를 계산하지 않는다" 가 모듈 docstring 에 설계 원칙으로 박혀 있었다.
이번 변경이 그것을 뒤집으므로, 언제 왜 바뀌었는지를 같은 자리에 남긴다.

- 원칙을 "공식이 아니라 직접 세기로 p 를 낸다" 로 교체하고 근거를 적는다
- 가설 description 에 p 와 fdr_table 읽는 법을 적는다 (LLM 이 읽는다)
- 설계 문서의 p_min_possible 계산과 "공간 부족" 판독법 두 곳을 정정한다

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## 이 계획에서 하지 않는 것

| 항목 | 어디로 |
|---|---|
| metro 분할점 탐색·`split_value`·`split_direction` | 3단계 (데이터 확보 후) |
| 게이트가 p 를 판정에 쓰기 (자동 차단) | 실데이터 확인 후. 지금 임계를 못 박을 근거가 없다 |
| 대조군 오염 가중치 상수 (1 → 1.6) | 실데이터 확인 후 |
| crude pooling / 심슨 역설 | 미해결. 설계검토 §1-3 |
| 1단계에서 보류한 문구 4건 (`n_target` 정의 등) | 이 계획 중 손대는 자리가 겹치면 그때 같이 정리 |
