# 축 간 순위 공통 척도 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 축을 가로지르는 순위를 "두 후보가 둘 다 표현할 수 있는 해상도" 에서 매겨,
참조집합이 작은 강한 후보가 참조집합이 큰 약한 후보에게 지는 것을 멈춘다.

**Architecture:** 전순서 키(`_rank_key`)로 우열을 묻던 것을 **지배 관계
(`dominates`) + 층위 순위(`layer_ranks`)** 로 바꾼다. 지배당하지 않은 묶음 전부가
1등 층이고, 걷어내고 반복한다. 전순서 키는 이름만 `_order_key` 로 바꿔 **표시
순서와 대표 선정에만** 남긴다. 게이트 승인은 "1등 층 멤버십" 이 된다.

**Tech Stack:** Python 3.11, pytest, LangGraph. 새 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-08-31-cross-axis-rank-scale-design.md`

## Global Constraints

- **기준선은 422 passed.** 작업 끝에 이 수보다 줄면 안 된다(늘어나는 것은 정상).
- 주석·docstring·커밋 메시지는 **한국어**. 기존 파일의 밀도와 어투를 따른다.
- 콘솔이 cp949 다. **사용자에게 보내는 메시지에 em-dash 를 쓰지 않는다**(파일 안은 무관).
- **surgical**: 요청과 무관한 코드·주석·포매팅을 손대지 않는다.
- 훼손 실험은 Task 5 에서 **반드시** 한다. 끝나면 `git diff` 로 워킹 트리를 확인한다
  (훼손 파일이 다음 실행의 기준선이 된 사고가 있었다).
- 브랜치는 `feat/cross-axis-rank` (이미 있고 스펙 커밋 `1b3ab86` 이 올라가 있다).
- **병합·푸시하지 않는다.** 리뷰는 별도로 요청하고, origin 푸시는 사용자가 보류했다.

## File Structure

| 파일 | 책임 | 이번 변경 |
|---|---|---|
| `graph/evidence.py` | 도구 결과를 게이트가 읽는 증거로 투영 + 순위 | 규칙 신설, 전순서 키 강등 |
| `graph/nodes.py` | 고정 골격 노드 + finalize 게이트 | 승인·반려를 1등 층으로 |
| `domain/hypotheses.yaml` | **LLM 이 읽는 계약 문서** | 순위 규칙 4곳 명시 |
| `tests/test_evidence.py` | 증거 투영·순위 계약 | 규칙 테스트 10건 + 헬퍼 수정 |
| `tests/test_graph_nodes.py` | 게이트 판정 계약 | 게이트 테스트 2건 |
| `tests/test_multi_axis_dummy.py` | 다축 실경로 | `rank_key` 단언 이전 |

---

## Task 1: 등급 판정과 지배 관계

우열을 묻는 새 술어를 만든다. 순위 산출(Task 2)은 전부 이 위에 선다.

**Files:**
- Modify: `graph/evidence.py` (`_rank_key` 아래에 추가)
- Test: `tests/test_evidence.py`

**Interfaces:**
- Consumes: `Claim`, `ClaimGroup` (기존)
- Produces:
  - `_is_statistical(claim: Claim) -> bool`
  - `dominates(a: ClaimGroup, b: ClaimGroup) -> bool`

- [ ] **Step 1: 테스트 헬퍼가 바닥을 싣게 한다**

`tests/test_evidence.py:159` 의 `_cand` 는 `p_permutation` 만 싣고
`p_min_possible` 을 안 싣는다. 새 규칙에서 바닥이 없으면 **비통계 등급**으로
떨어지므로, 이 헬퍼를 쓰는 **41곳이 전부 뜻이 달라진다**. 실도구는 둘을 항상 같이
싣으므로(`domain/engine.py::evaluate`) 헬퍼를 실도구에 맞춘다.

```python
def _cand(claim_id, key, score, p, wafers, level="chamber", step="CC002000",
          floor=0.001):
    return {"claim_id": claim_id, "level": level, "step_seq": step, "key": key,
            "passes": True, "reject_reason": None, "score": score,
            "target_pass": len(wafers), "target_total": 6,
            "control_pass": 0, "control_total": 6,
            "p_permutation": p, "p_min_possible": floor,
            "target_wafers": list(wafers), "control_wafers": []}
```

기본값 `0.001` 은 "참조가 충분해 바닥이 문제되지 않는다" 는 뜻이다. 바닥을 다투는
테스트만 `floor=` 를 명시한다.

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_evidence.py` 의 `_cand` 정의 아래에 넣는다.

```python
def _groups(*cands):
    """후보마다 축을 하나씩 줘서 묶음 목록을 만든다 (접히지 않게 wafer 를 가른다)."""
    return evidence.build_bundle([
        _finding(f"hyp_{i}", f"h{i}", "ok", [c])
        for i, c in enumerate(cands)]).ranked_groups()


def _by_key(groups, key):
    return next(g for g in groups if g.lead.key == key)


def test_candidates_at_their_floor_do_not_lose_to_a_smaller_p():
    """바닥에 걸린 후보는 더 작은 p 에게 지지 않는다.

    X 는 참조가 8회뿐이라 완전 분리인데도 p 0.111 에서 멈춘다. Y 는 참조가 300회라
    더 내려갈 수 있었는데 0.05 에서 멈췄다. 공통 해상도는 거친 쪽인 0.111 이고,
    거기서는 둘 다 "그 이하" 라 갈리지 않는다. 예전 규칙은 Y 가 이겼다고 봤다.
    """
    groups = _groups(
        _cand("x:1", "AT_FLOOR", 1.0, 0.111, ["W1", "W2"], floor=0.111),
        _cand("y:1", "SMALL_P", 0.55, 0.050, ["W3", "W4"], floor=0.003))
    gx, gy = _by_key(groups, "AT_FLOOR"), _by_key(groups, "SMALL_P")
    assert not evidence.dominates(gx, gy)
    assert not evidence.dominates(gy, gx)


def test_a_candidate_that_wins_at_the_shared_resolution_dominates():
    """공통 해상도에서 실제로 갈리면 이긴다. 규칙이 전부를 동점으로 만들면 안 된다."""
    groups = _groups(
        _cand("y:1", "SMALL_P", 0.55, 0.050, ["W3", "W4"], floor=0.003),
        _cand("z:1", "TINY_P", 0.55, 0.002, ["W5", "W6"], floor=0.003))
    gy, gz = _by_key(groups, "SMALL_P"), _by_key(groups, "TINY_P")
    assert evidence.dominates(gz, gy)
    assert not evidence.dominates(gy, gz)


def test_statistical_evidence_beats_evidence_without_statistics():
    """p 없는 증거는 통계 등급 아래다 - 등급이 다르면 값을 안 본다.

    분리 점수 0.99 짜리 무통계 증거가 p 0.40 짜리 통계 증거를 못 이긴다.
    """
    groups = _groups(
        _cand("s:1", "WITH_P", 0.55, 0.40, ["W1", "W2"], floor=0.01),
        _cand("b:1", "NO_P", 0.99, None, ["W3", "W4"], floor=None))
    gs, gb = _by_key(groups, "WITH_P"), _by_key(groups, "NO_P")
    assert evidence.dominates(gs, gb)
    assert not evidence.dominates(gb, gs)


def test_a_floor_of_one_means_no_statistics_at_all():
    """참조 0회(바닥 1.0)는 "우연이다" 가 아니라 "비교할 표본이 없었다" 다.

    통계가 실제로 없으므로 p 를 안 내는 증거와 같은 등급으로 내린다. 분리 점수가
    1.0 이어도 마찬가지다 - 그 숫자를 근거로 설비를 세우면 안 된다.
    """
    groups = _groups(
        _cand("e:1", "NO_REFERENCE", 1.0, 1.0, ["W1", "W2"], floor=1.0),
        _cand("w:1", "WEAK", 0.55, 0.40, ["W3", "W4"], floor=0.01))
    ge, gw = _by_key(groups, "NO_REFERENCE"), _by_key(groups, "WEAK")
    assert evidence.dominates(gw, ge)
    assert not evidence.dominates(ge, gw)


def test_score_breaks_ties_only_inside_one_axis():
    """분리 점수는 축을 가로지르면 안 되는 자다.

    점수는 탐색 폭에 따라 부풀고 그 정도가 축마다 다르다(계측 축은 무신호에서도
    후보의 48.7%가 판별선을 넘는다). p 가 같을 때 축을 넘어 점수로 가르면 탐색이
    넓은 축이 늘 이긴다 - p 를 1순위로 둔 이유가 사라진다.
    """
    same_axis = evidence.build_bundle([
        _finding("hyp_a", "a", "ok", [
            _cand("a:1", "HIGH", 0.90, 0.02, ["W1", "W2"]),
            _cand("a:2", "LOW", 0.60, 0.02, ["W3", "W4"])])]).ranked_groups()
    assert evidence.dominates(_by_key(same_axis, "HIGH"),
                              _by_key(same_axis, "LOW"))

    cross = _groups(_cand("a:1", "HIGH", 0.90, 0.02, ["W1", "W2"]),
                    _cand("b:1", "LOW", 0.60, 0.02, ["W3", "W4"]))
    hi, lo = _by_key(cross, "HIGH"), _by_key(cross, "LOW")
    assert not evidence.dominates(hi, lo)      # 축이 다르면 점수로 못 가른다
    assert not evidence.dominates(lo, hi)
```

- [ ] **Step 3: 실패를 확인한다**

Run: `python -m pytest tests/test_evidence.py -k "floor or statistic or score_breaks or shared_resolution" -v`

Expected: FAIL — `AttributeError: module 'graph.evidence' has no attribute 'dominates'`

- [ ] **Step 4: 최소 구현**

`graph/evidence.py` 의 `_rank_key` 함수 **바로 아래**에 넣는다.

```python
def _is_statistical(claim: Claim) -> bool:
    """이 후보에게 통계적 근거가 있는가. **없으면 순위에서 별도 등급으로 내린다.**

    바닥이 1.0 이라는 것은 참조 회차가 0 이라는 뜻이고, 그것은 "우연이다" 가 아니라
    **"비교할 귀무 표본이 하나도 없었다"** 다
    (`tools/commonality.py::_null_distribution`). 분리 점수가 1.0 이어도 통계적
    근거는 없으므로, p 를 아예 안 내는 증거(2단 센서·잔차)와 같은 등급이다.

    바닥만 없고 p 는 있는 조합은 도구가 둘을 같이 싣기 때문에 실경로에서는 안
    생긴다(`domain/engine.py::evaluate`). 생기면 보수적으로 비통계로 떨어뜨린다.
    """
    if claim.p_permutation is None:
        return False
    floor = claim.p_min_possible if claim.p_min_possible is not None else 1.0
    return floor < 1.0


def dominates(a: ClaimGroup, b: ClaimGroup) -> bool:
    """a 가 b 를 **확실히** 이기는가. 아니면 둘은 갈리지 않는 것이다.

    비교는 두 후보가 **둘 다 표현할 수 있는 해상도**에서만 한다. 순열 p 의 바닥은
    1/(참조회차+1) 이고 참조 회차는 후보마다 다르므로(참조집합을 표본 크기가 같은
    회차로 좁힌 2026-08-29 변경), 거친 쪽 바닥 아래로는 두 후보 모두 말할 수 있는
    것이 없다. 그 아래를 비교하면 순위가 **신호 세기가 아니라 참조집합 크기**를
    따라간다 - 참조 8회의 완전 분리 후보가 참조 300회의 약한 후보에게 진다.

    비통계 쌍은 p 계산을 **건너뛴다.** 없는 값을 1.0 으로 채워 넣으면 "참조 0회라
    p 가 1.0" 인 후보와 "p 를 아예 안 낸" 후보가 같은 값이 되어, 나중에 등급 판정을
    고칠 때 한쪽이 조용히 따라 움직인다.
    """
    x, y = a.lead, b.lead
    sx, sy = _is_statistical(x), _is_statistical(y)
    if sx != sy:
        return sx                      # 통계 등급이 비통계 등급을 이긴다
    if sx:
        floor = max(x.p_min_possible, y.p_min_possible)   # 공통 해상도
        px, py = max(x.p_permutation, floor), max(y.p_permutation, floor)
        if px != py:
            return px < py
    # p 로는 안 갈렸다. 점수는 탐색 폭에 따라 부풀고 그 정도가 축마다 다르므로
    # **같은 축 안에서만** 쓴다 - 축을 넘으면 탐색이 넓은 축이 늘 이긴다.
    return x.hypothesis_id == y.hypothesis_id and x.score > y.score
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python -m pytest tests/test_evidence.py -v`

Expected: 새 테스트 5건 PASS. 기존 테스트도 전부 PASS (Step 1 의 헬퍼 수정 덕분에
`_cand` 로 만든 후보가 계속 통계 등급으로 남는다).

- [ ] **Step 6: 커밋**

```bash
git add graph/evidence.py tests/test_evidence.py
git commit -m "feat(rank): 두 후보가 둘 다 표현할 수 있는 해상도에서만 우열을 가린다"
```

---

## Task 2: 층위 순위

지배 관계를 등수로 바꾼다. 비교 불가가 비이행적이라 정렬로는 안 된다.

**Files:**
- Modify: `graph/evidence.py` (`layer_ranks` 신설, `ranked_groups`, `groups_to_dicts`)
- Test: `tests/test_evidence.py`

**Interfaces:**
- Consumes: `dominates(a, b) -> bool` (Task 1)
- Produces: `layer_ranks(groups: list[ClaimGroup]) -> list[int]`
  — `groups` 와 같은 길이, 1부터 시작하는 등수, 같은 층은 같은 수

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_layers_handle_intransitive_incomparability():
    """비교 불가는 이행적이지 않다 - 그래서 정렬이 아니라 층위여야 한다.

    X~Y, X~Z 인데 Z>Y 다. 비교자로 정렬하면 입력 순서에 따라 답이 달라진다.
    Z 는 아무에게도 안 지므로 1등, X 도 아무에게도 안 지므로 1등, Y 는 Z 에게
    졌으므로 2등이다.
    """
    groups = _groups(
        _cand("x:1", "AT_FLOOR", 1.0, 0.111, ["W1"], floor=0.111),
        _cand("y:1", "SMALL_P", 0.55, 0.050, ["W2"], floor=0.003),
        _cand("z:1", "TINY_P", 0.55, 0.002, ["W3"], floor=0.003))
    ranks = dict(zip((g.lead.key for g in groups), evidence.layer_ranks(groups)))
    assert ranks == {"AT_FLOOR": 1, "TINY_P": 1, "SMALL_P": 2}


def test_evidence_without_statistics_leads_when_nothing_else_ran():
    """통계 후보가 0건이면 p 없는 증거가 1등 층으로 올라온다.

    등급은 절대 순서가 아니라 상대 순서다 - 위가 비면 아래가 1등이다. 이것이
    A 작업(센서·잔차를 claim 으로 승격)에서 그 증거가 리포트에 도달하는 경로다.
    """
    groups = _groups(_cand("b:1", "NO_P", 0.9, None, ["W1"], floor=None),
                     _cand("c:1", "ALSO_NO_P", 0.7, None, ["W2"], floor=None))
    assert evidence.layer_ranks(groups) == [1, 1]


def test_layer_ranks_terminates_when_domination_cycles(monkeypatch):
    """지배가 순환하면 한 층으로 내고 끝낸다 - 안전판이 없으면 무한 루프다.

    설계 문서 §2.1 이 지배 관계의 이행성을 증명하지만 그 증명은 등급·축내 점수
    조건이 섞이지 않은 경우를 다룬다. 증명이 닿지 않는 자리에서 순환이 나면 분석
    전체가 멎으므로, 안전판 자체를 잠근다.
    """
    monkeypatch.setattr(evidence, "dominates", lambda a, b: True)   # 전원이 서로를 이긴다
    groups = _groups(_cand("a:1", "A", 0.9, 0.01, ["W1"]),
                     _cand("b:1", "B", 0.8, 0.02, ["W2"]))
    assert evidence.layer_ranks(groups) == [1, 1]


def test_display_order_follows_the_layer_not_the_raw_p():
    """표시 순서가 등수와 어긋나면 리포트에서 [근거 2] 가 [근거 1] 위에 찍힌다.

    바닥에 걸린 AT_FLOOR 는 p 가 0.111 로 커서 전순서 키로는 맨 뒤인데 등수는
    1등이다. `ranked_groups` 는 등수를 먼저 보고 정렬해야 한다.
    """
    groups = _groups(
        _cand("x:1", "AT_FLOOR", 1.0, 0.111, ["W1"], floor=0.111),
        _cand("y:1", "SMALL_P", 0.55, 0.050, ["W2"], floor=0.003),
        _cand("z:1", "TINY_P", 0.55, 0.002, ["W3"], floor=0.003))
    assert [g.lead.key for g in groups][-1] == "SMALL_P"   # 2등이 맨 뒤
    assert evidence.layer_ranks(groups) == [1, 1, 2]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_evidence.py -k "layer or display_order or without_statistics" -v`

Expected: FAIL — `AttributeError: module 'graph.evidence' has no attribute 'layer_ranks'`

- [ ] **Step 3: `layer_ranks` 를 구현한다**

`graph/evidence.py` 의 `dominates` 바로 아래에 넣는다.

```python
def layer_ranks(groups: list[ClaimGroup]) -> list[int]:
    """각 묶음의 등수. **지배당하지 않은 것 전부가 1등**이고, 걷어내고 반복한다.

    정렬로 못 하는 이유: **비교 불가는 이행적이지 않다.** 바닥 0.111 인 X 와 p
    0.05 인 Y 는 동점인데(공통 해상도 0.111 에서 둘 다 그 이하) Y 는 p 0.002 인
    Z 에게 진다 - X~Y, X~Z 인데 Z>Y 다. 비교자로 정렬하면 입력 순서에 따라 답이
    달라진다.

    지배 관계 자체는 이행적이라 순환이 없지만(설계 문서 §2.1) 안전판을 둔다 -
    증명이 닿지 않는 자리에서 순환이 한 번 나면 무한 루프이고, 그건 분석 전체가
    멎는다는 뜻이다.
    """
    ranks = [0] * len(groups)
    remaining = list(range(len(groups)))
    layer = 1
    while remaining:
        front = [i for i in remaining
                 if not any(dominates(groups[j], groups[i])
                            for j in remaining if j != i)]
        if not front:                       # 안전판: 순환이면 남은 전부를 한 층으로
            front = list(remaining)
        for i in front:
            ranks[i] = layer
        taken = set(front)
        remaining = [i for i in remaining if i not in taken]
        layer += 1
    return ranks
```

- [ ] **Step 4: `ranked_groups` 가 등수 순으로 내놓게 한다**

`graph/evidence.py::Bundle.ranked_groups` 의 마지막 두 줄을 바꾼다.

바꾸기 전:
```python
        groups = [ClaimGroup(claims=tuple(sorted(cs, key=_fold_key)))
                  for cs in buckets.values()]
        return sorted(groups, key=lambda g: g.sort_key)
```

바꾼 뒤:
```python
        groups = [ClaimGroup(claims=tuple(sorted(cs, key=_fold_key)))
                  for cs in buckets.values()]
        groups.sort(key=lambda g: g.sort_key)          # 같은 등수 안의 표시 순서
        # **등수를 먼저 본다.** 표시 순서(전순서 키)와 등수가 어긋나면 리포트에서
        # `[근거 2]` 가 `[근거 1]` 위에 찍힌다 - 바닥에 걸린 후보는 p 가 커서
        # 전순서로는 뒤인데 등수는 1등일 수 있다. 파이썬 정렬은 안정적이라 같은
        # 등수 안에서는 위에서 잡은 표시 순서가 그대로 유지된다.
        ranks = layer_ranks(groups)
        return [g for _, g in sorted(zip(ranks, groups), key=lambda pair: pair[0])]
```

- [ ] **Step 5: `groups_to_dicts` 의 등수 계산을 교체한다**

`graph/evidence.py::groups_to_dicts` 의 본문 첫 덩어리를 바꾼다.

바꾸기 전:
```python
    out: list[dict] = []
    rank, prev = 0, None
    for i, group in enumerate(groups):
        key = group.rank_key              # 우열만. claim_id 는 여기 없다
        if key != prev:
            rank, prev = i + 1, key
        item = group_to_dict(group, picked=(group is picked))
        item["rank"] = rank
        out.append(item)
```

바꾼 뒤:
```python
    out: list[dict] = []
    for group, rank in zip(groups, layer_ranks(groups)):
        item = group_to_dict(group, picked=(group is picked))
        item["rank"] = rank
        out.append(item)
```

같은 함수 docstring 의 마지막 두 줄도 새 규칙에 맞춘다.

바꾸기 전:
```
    추천할 수 있다). 표시 순서를 고정하는 claim_id 는 `sort_key` 에만 있고 `rank_key`
    에는 없다 - 우열을 묻는 자리에 그것이 섞이면 안 된다.
```
바꾼 뒤:
```
    추천할 수 있다). 등수는 `layer_ranks` 가 지배 관계로 매긴다 - 표시 순서를
    고정하는 `sort_key` 는 우열을 묻는 자리에 절대 들어가면 안 된다.
```

- [ ] **Step 6: 통과를 확인한다**

Run: `python -m pytest tests/test_evidence.py -v`

Expected: 새 테스트 4건 포함 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add graph/evidence.py tests/test_evidence.py
git commit -m "feat(rank): 지배당하지 않은 근거 전부를 1등 층으로 낸다"
```

---

## Task 3: 전순서 키 강등과 게이트 전환

`rank_key` 로 우열을 묻는 자리를 전부 없앤다. 하나라도 남으면 새 규칙이 조용히
우회된다.

**Files:**
- Modify: `graph/evidence.py` (`ClaimGroup.rank_key` 제거, `_rank_key` 개명)
- Modify: `graph/nodes.py::_finalize_gate` (승인), `graph/nodes.py::_gate_rejection` (반려)
- Test: `tests/test_graph_nodes.py`, `tests/test_multi_axis_dummy.py`, `tests/test_evidence.py`

**Interfaces:**
- Consumes: `layer_ranks(groups) -> list[int]` (Task 2), `dominates(a, b)` (Task 1)
- Produces: `_gate_rejection(claim_id, claim, bundle, coverage, conf, conf_note, groups, ranks)`
  — 인자가 하나(`ranks: list[int]`) 늘어난다. `_finalize_gate` 만 부른다.

- [ ] **Step 1: 실패하는 게이트 테스트를 쓴다**

`tests/test_graph_nodes.py` 에 넣는다. (이 파일은 `nodes` 를 이미 import 하고 있다.)

```python
def _rank_cand(claim_id, key, step, score, p, floor, wafer):
    return {"claim_id": claim_id, "level": "chamber", "step_seq": step, "key": key,
            "passes": True, "reject_reason": None, "score": score,
            "target_pass": 2, "target_total": 6,
            "control_pass": 0, "control_total": 6,
            "p_permutation": p, "p_min_possible": floor,
            "target_wafers": [wafer], "control_wafers": []}


def _rank_finding(tool, hypothesis_id, cands, loop=1):
    return {"loop": loop, "tool": tool, "args": {}, "thought": "t",
            "result": {"hypothesis_id": hypothesis_id, "status": "ok",
                       "candidates": cands}}


def test_gate_approves_any_member_of_the_first_layer():
    """1등 층 안이면 정렬상 맨 앞이 아니어도 승인한다.

    예전 계약은 `groups[0]` 과 우열 키가 같은지를 물었다. 새 규칙에서는 등수가
    같아도 키가 다를 수 있다 - 바닥이 다른 두 후보는 p 가 달라도 동점이다. 키로
    물으면 동점이라고 리포트에 적어 놓고 게이트는 반려하는 모순이 난다.
    """
    findings = [
        _rank_finding("hyp_a", "a",
                      [_rank_cand("a:1", "TINY_P", "CC001000", 0.55, 0.002, 0.003, "W1")]),
        _rank_finding("hyp_b", "b",
                      [_rank_cand("b:1", "AT_FLOOR", "CC002000", 1.0, 0.111, 0.111, "W2")],
                      loop=2),
    ]
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "b:1", "hypothesis": "바닥에 걸린 쪽", "confidence": 0.9},
        1, update, findings)
    assert update.get("finalize_status") == "confirmed", verdict
    assert any(c.get("picked_by_llm") for c in update["final_claims"])


def test_gate_rejection_names_the_candidate_that_actually_beat_it():
    """반려는 **실제로 이긴 근거**를 대야 한다 - 무조건 1등이 아니라.

    지목한 것이 3등이면 그것을 이긴 것은 2등일 수 있다. 1등을 대면 LLM 은 왜
    졌는지 못 읽는다. 바닥도 함께 인용해야 두 숫자를 같이 읽는다.
    """
    findings = [_rank_finding("hyp_a", "a", [
        _rank_cand("a:1", "TINY_P", "CC001000", 0.55, 0.002, 0.003, "W1"),
        _rank_cand("a:2", "SMALL_P", "CC003000", 0.55, 0.050, 0.003, "W9"),
    ])]
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "a:2", "hypothesis": "약한 쪽", "confidence": 0.9},
        1, update, findings)
    assert "finalize_status" not in update           # 반려는 종료가 아니다
    assert "a:1" in verdict and "바닥" in verdict
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_graph_nodes.py -k "first_layer or actually_beat" -v`

Expected: 첫 테스트가 FAIL — 현재 규칙은 `groups[0]`(TINY_P)과 우열 키가 달라
`b:1` 을 반려하므로 `finalize_status` 가 없다.

- [ ] **Step 3: `_rank_key` 를 `_order_key` 로 개명하고 프로퍼티를 없앤다**

`graph/evidence.py` 에서 다음 네 가지를 한다.

1. `ClaimGroup.rank_key` 프로퍼티를 **통째로 삭제**한다.

```python
    @property
    def rank_key(self) -> tuple:
        """**우열을 가르는 값.** 이게 같으면 동점이고, 동점은 우열이 없다는 뜻이다."""
        return _rank_key(self.lead)
```

2. `def _rank_key(claim: Claim) -> tuple:` 를 `_order_key` 로 바꾸고 docstring 을
   통째로 갈아 끼운다. 기존 docstring 의 "원시 점수를 1순위로 안 쓰는 이유" 문단과
   "열린 한계 (2026-08-29)" 문단은 **지운다** - 앞의 것은 `dominates` 로 옮겨 갔고,
   뒤의 것은 이번 변경이 고친 것이다. 본문(`return` 줄)은 그대로 둔다.

```python
def _order_key(claim: Claim) -> tuple:
    """**표시 순서와 대표 선정에만 쓰는 전순서 키.** 우열은 `dominates` 가 가른다.

    예전에는 이 키가 우열까지 겸했는데, 순열 p 의 바닥이 후보마다 달라지면서
    (2026-08-29) 그 비교가 **신호 세기가 아니라 참조집합 크기**를 재게 됐다.
    우열 판정은 `dominates` 로 옮겼다. 여기 남은 일은 "같은 등수 안에서 매번 같은
    순서로 보여 주는 것" 뿐인데 그것도 필요하다 - 리포트를 실행마다 비교해야 한다.
    """
    p = claim.p_permutation
    return (1.0 if p is None else p, -claim.score)
```

3. `_fold_key` 와 `_sort_key` 의 `_rank_key(claim)` 호출을 `_order_key(claim)` 으로
   바꾼다.

4. `_sort_key` docstring 첫 줄의 `` 우열(`_rank_key`)에 `` 를
   `` 표시 순서(`_order_key`)에 `` 로 바꾼다.

- [ ] **Step 4: 게이트 승인을 1등 층 멤버십으로 바꾼다**

`graph/nodes.py::_finalize_gate` 에서 `groups`/`picked` 를 잡는 두 줄 아래에 등수를
함께 잡는다.

바꾸기 전:
```python
    groups = bundle.ranked_groups()
    picked = evidence.find_group(groups, claim_id) if claim_id else None
```

바꾼 뒤:
```python
    groups = bundle.ranked_groups()
    picked = evidence.find_group(groups, claim_id) if claim_id else None
    # 등수는 목록과 **같은 객체**로 맞춘다. `find_group` 이 목록에서 꺼낸 바로 그
    # 객체를 돌려주므로 `is` 로 찾는다 - 다시 만들면 조용히 어긋난다(그 함수의
    # docstring 이 경고하는 함정이 이것이다).
    ranks = evidence.layer_ranks(groups)
    picked_rank = next((r for g, r in zip(groups, ranks) if g is picked), None)
```

(1) 승인 조건을 바꾼다.

바꾸기 전:
```python
    if (claim is not None and claim.passes
            and picked is not None and picked.rank_key == groups[0].rank_key
            and conf >= ya_config.CONFIDENCE_THRESHOLD):
```
바꾼 뒤:
```python
    if (claim is not None and claim.passes
            and picked_rank == 1
            and conf >= ya_config.CONFIDENCE_THRESHOLD):
```

같은 함수 맨 아래 `_gate_rejection` 호출에 `ranks` 를 넘긴다.

바꾸기 전:
```python
    return _gate_rejection(claim_id, claim, bundle, coverage, conf, conf_note, groups)
```
바꾼 뒤:
```python
    return _gate_rejection(claim_id, claim, bundle, coverage, conf, conf_note,
                           groups, ranks)
```

- [ ] **Step 5: 반려가 실제로 이긴 근거를 대게 한다**

`graph/nodes.py::_gate_rejection` 의 시그니처를 바꾼다.

바꾸기 전:
```python
def _gate_rejection(claim_id, claim, bundle, coverage, conf, conf_note, groups) -> str:
```
바꾼 뒤:
```python
def _gate_rejection(claim_id, claim, bundle, coverage, conf, conf_note,
                    groups, ranks) -> str:
```

같은 함수의 순위 분기를 바꾼다.

바꾸기 전:
```python
        picked = evidence.find_group(groups, claim_id)
        if picked is not None and groups and picked.rank_key != groups[0].rank_key:
            # 순위는 코드가 매긴다. 순열 p 가 먼저이고 동점이면 분리 점수다 —
            # 점수만 보고 고르면 탐색 폭이 넓은 축(계측)이 늘 이긴다.
            best = groups[0].lead
```
바꾼 뒤:
```python
        picked = evidence.find_group(groups, claim_id)
        picked_rank = next((r for g, r in zip(groups, ranks) if g is picked), None)
        if picked is not None and groups and picked_rank != 1:
            # **실제로 이긴 근거**를 댄다. 3등을 지목했으면 그것을 이긴 것은 2등일
            # 수 있고, 그때 1등을 대면 LLM 은 왜 졌는지 못 읽는다.
            best = next((g.lead for g in groups if evidence.dominates(g, picked)),
                        groups[0].lead)
```

이어지는 반환 문구도 새 규칙에 맞춘다.

바꾸기 전:
```python
            return (f"반려: {claim.claim_id}(p {claim.p_permutation}{_floor(claim)}, "
                    f"점수 {claim.score}) 보다 앞선 근거가 있다: {best.claim_id}"
                    f"(p {best.p_permutation}{_floor(best)}, 점수 {best.score}). "
                    f"순위 1등을 서술의 축으로 지목하라 - 나머지 근거는 게이트가 함께 싣는다.")
```
바꾼 뒤:
```python
            return (f"반려: {claim.claim_id}(p {claim.p_permutation}{_floor(claim)}, "
                    f"점수 {claim.score}) 는 {best.claim_id}"
                    f"(p {best.p_permutation}{_floor(best)}, 점수 {best.score}) 에게 "
                    f"두 후보가 **함께 표현할 수 있는 해상도**에서 졌다. p 는 자기 "
                    f"바닥과 함께 읽어야 한다 - 바닥에 걸린 후보는 더 작은 p 에게 "
                    f"지지 않는다. 1등 층의 근거를 서술의 축으로 지목하라, 나머지 "
                    f"근거는 게이트가 함께 싣는다.")
```

- [ ] **Step 6: `rank_key` 를 단언하던 테스트 3곳을 옮겨 쓴다**

**지우지 않는다.** 계약("우열을 묻는 값에 표시용 tie-break 가 섞이면 안 된다")은
살아 있고, 그 계약이 키에서 `dominates` 로 이사한 것뿐이다. 테스트가 사라지면 새
규칙이 그 자리를 안 잠근 채로 남는다.

**(a) `tests/test_multi_axis_dummy.py::test_rank_key_carries_no_display_tiebreak`** —
이름과 마지막 세 줄을 바꾼다.

```python
def test_domination_carries_no_display_tiebreak():
    """우열을 묻는 자리에 표시 순서용 tie-break 가 섞이면 안 된다.

    둘을 한 튜플로 겸하게 두었더니 게이트는 claim_id 까지 넣어 비교하고 등수
    계산은 빼고 비교해서, **동점이라 보고해 놓고 게이트는 반려하는** 상태가 됐다.
    우열이 키에서 `dominates` 로 옮겨 간 지금도 같은 계약이 필요하다.
    """
    from graph import evidence

    groups = evidence.build_bundle([
        {"loop": 1, "tool": f"hyp_{spec['id']}", "args": {},
         "result": engine.evaluate(spec, MULTI_TARGETS, MULTI_CONTROLS), "thought": ""}
        for spec in registry.load_hypotheses()]).ranked_groups()

    assert not evidence.dominates(groups[0], groups[1])   # 우열이 없다
    assert not evidence.dominates(groups[1], groups[0])
    assert groups[0].sort_key != groups[1].sort_key       # 표시 순서만 다르다
    ranks = evidence.layer_ranks(groups)
    assert ranks[0] == ranks[1]                           # 등수도 같다
```

**(b) `tests/test_multi_axis_dummy.py::test_ranking_is_deterministic_when_the_evidence_ties`**
— 마지막 한 줄을 바꾼다.

바꾸기 전:
```python
    assert groups[0].rank_key == groups[1].rank_key   # p·점수가 동점이다
```
바꾼 뒤:
```python
    from graph import evidence
    ranks = evidence.layer_ranks(groups)
    assert ranks[0] == ranks[1]                       # 우열을 못 가린다
```

**(c) `tests/test_evidence.py`** — `REPORT_MAX_EVIDENCE` 상한 테스트의 한 줄을 바꾼다.

바꾸기 전:
```python
    assert len({g.rank_key for g in groups}) == 1, "이 fixture 는 전부 동점이어야 한다"
```
바꾼 뒤:
```python
    assert set(evidence.layer_ranks(groups)) == {1}, "이 fixture 는 전부 동점이어야 한다"
```

- [ ] **Step 7: 통과를 확인하고 남은 `rank_key` 가 없는지 본다**

Run: `python -m pytest -q`

Expected: 422 이상 passed, 0 failed

Run: `grep -rn "\.rank_key" --include=*.py . | grep -v __pycache__`

Expected: **출력 없음.** 프로퍼티를 읽는 자리가 한 줄이라도 남으면 새 규칙을
우회하는 자리가 남은 것이다.

(함수 이름 `_rank_key` 를 언급하는 **주석**은 아직 도구 모듈에 남아 있다 - 그건
Task 4 Step 5 에서 고친다. 여기서 `.` 을 붙여 찾는 이유가 그것이다.)

- [ ] **Step 8: 커밋**

```bash
git add graph/evidence.py graph/nodes.py tests/
git commit -m "feat(gate): 승인을 1등 층 멤버십으로 바꾸고 전순서 키를 표시용으로 강등한다"
```

---

## Task 4: 사람과 LLM 이 읽는 문장

코드는 맞는데 문장이 옛 규칙을 설명하면, 리포트를 읽는 엔지니어와 반려를 읽는
LLM 이 둘 다 틀린 이유를 배운다.

**Files:**
- Modify: `graph/evidence.py::format_group_line` (동점 문장)
- Modify: `domain/hypotheses.yaml` (4가설 전부)
- Modify: `tools/commonality.py`, `tools/metro_commonality.py`,
  `tests/test_metro_commonality.py` (낡은 주석 3곳)
- Test: `tests/test_evidence.py`

**Interfaces:**
- Consumes: `groups_to_dicts`, `format_group_line` (기존)
- Produces: 없음 (문장만 바꾼다)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_tie_line_explains_resolution_not_equal_numbers():
    """동점 문장이 이유를 옛 규칙으로 설명하면 안 된다.

    새 규칙에서는 p 가 0.111 과 0.050 으로 **달라도** 동점이다. "순열 p 와 분리
    점수가 같아" 라고 적으면 바로 옆에 다른 숫자를 찍어 놓고 같다고 말하는 꼴이다.
    """
    groups = _groups(
        _cand("x:1", "AT_FLOOR", 1.0, 0.111, ["W1"], floor=0.111),
        _cand("y:1", "SMALL_P", 0.55, 0.050, ["W2"], floor=0.003))
    dicts = evidence.groups_to_dicts(groups)
    line = evidence.format_group_line(dicts[0])
    assert "해상도" in line
    assert "순열 p 와 분리 점수가 같아" not in line
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_evidence.py -k tie_line_explains -v`

Expected: FAIL — `assert "해상도" in line`

- [ ] **Step 3: 동점 문장을 고친다**

`graph/evidence.py::format_group_line` 의 `tied` 분기를 바꾼다.

바꾸기 전:
```python
    if group.get("tied"):
        # 번호만 보면 앞선 것이 더 강해 보인다. 실제로는 순열 p 도 분리 점수도 같아
        # 우열을 가릴 근거가 없다 - 그 사실이 다음에 무엇을 볼지 정하는 입력이다.
        line += ("\n        같은 등수의 근거가 더 있다 - 순열 p 와 분리 점수가 같아 "
                 "어느 쪽이 유력한지 현재 증거로는 정할 수 없다")
```
바꾼 뒤:
```python
    if group.get("tied"):
        # 번호만 보면 앞선 것이 더 강해 보인다. 실제로는 **이 표본들이 낼 수 있는
        # 해상도에서 갈리지 않는다** - p 숫자가 서로 달라도 그렇다(참조 회차가 적은
        # 후보는 자기 바닥 아래를 말할 수 없다). 그 "못 가린다" 가 다음에 무엇을
        # 볼지 정하는 입력이다.
        line += ("\n        같은 등수의 근거가 더 있다 - 이 표본들이 낼 수 있는 "
                 "해상도에서는 갈리지 않아 어느 쪽이 유력한지 현재 증거로는 "
                 "정할 수 없다")
```

- [ ] **Step 4: `hypotheses.yaml` 4가설에 순위 규칙을 명시한다**

`domain/hypotheses.yaml` 의 각 가설 `description` 에서 `p_min_possible` 바닥을
설명하는 문단(`거꾸로 n_reference 가 작으면 ...` 으로 끝나는 줄) **바로 뒤**에
아래를 넣는다. **4가설 전부에 넣는다** - 통계 해석 문단이 복붙돼 있고, 지난 순열 p
교정 때 리뷰 Important 4건 중 2건이 이 yaml 계약 구멍이었다.

```
    순위는 두 후보가 **둘 다 표현할 수 있는 해상도**에서 매겨진다. 그래서 p 가 자기
    바닥에 걸린 후보는 더 작은 p 를 가진 후보에게 **지지 않는다** - 바닥 0.111 인
    완전 분리 후보와 p 0.05 인 약한 후보는 동점이다. p 하나만 보고 "내가 졌다" 고
    판단하지 마라.
    참조 0회(p 도 바닥도 1.0)인 후보는 통계적 근거가 없는 것으로 취급되어, 통계가
    있는 후보들 뒤로 밀린다.
```

들여쓰기는 그 블록의 다른 줄과 맞춘다(`description: |` 아래 4칸).

- [ ] **Step 5: 낡은 주석 3곳을 고친다**

세 곳 모두 `_rank_key` 를 **"축을 가로지르는 유일한 자"** 로 부른다. 함수 이름이
없어졌고 읽는 법도 바뀌었다. 안 고치면 다음 사람이 없는 함수를 찾는다.

각 위치에서 `` `_rank_key` `` 표기를 `` `dominates` `` 로 바꾸고, "유일한 자다"
취지의 문장 뒤에 다음 한 문장을 덧붙인다.

```
단 p 는 **자기 바닥과 함께** 읽어야 하고, 비교는 두 후보의 공통 해상도에서 이뤄진다.
```

- `tools/commonality.py` (`_rank_key` 를 언급하는 주석)
- `tools/metro_commonality.py` (모듈 docstring)
- `tests/test_metro_commonality.py` (테스트 주석)

정확한 위치는 다음으로 찾는다:
`grep -rn "_rank_key" --include=*.py . | grep -v __pycache__`

- [ ] **Step 6: 통과를 확인한다**

Run: `python -m pytest -q`

Expected: 422 이상 passed, 0 failed

Run: `grep -rn "_rank_key" --include=*.py --include=*.yaml . | grep -v __pycache__`

Expected: 출력 없음

- [ ] **Step 7: 커밋**

```bash
git add graph/evidence.py domain/hypotheses.yaml tools/ tests/
git commit -m "docs(rank): 리포트와 LLM 계약이 새 순위 규칙을 설명하게 한다"
```

---

## Task 5: 훼손 실험과 회귀 확인

테스트가 있어도 훼손 실험 없이는 매번 3건씩 안 잡히고 있었다. 리뷰 5회 연속으로
실재 결함이 나왔고 그 절반이 "고치다 만든 회귀" 였다.

**Files:**
- 변경 없음 (검증만). 안 잡히는 훼손이 나오면 그때만 테스트를 추가한다.

**Interfaces:**
- Consumes: Task 1~4 의 전부
- Produces: 없음

- [ ] **Step 1: 기준선을 확인한다**

Run: `python -m pytest -q`

Expected: 422 이상 passed, 0 failed. **이 수를 적어 둔다.**

- [ ] **Step 2: 훼손 5종을 하나씩 넣고 테스트가 잡는지 본다**

한 번에 하나만 넣고, 확인하면 **즉시 되돌린다.**

| # | 훼손 | 위치 | 잡아야 할 테스트 |
|---|---|---|---|
| 1 | `floor = max(...)` 를 `min(...)` 으로 | `evidence.py::dominates` | `test_candidates_at_their_floor_do_not_lose_to_a_smaller_p` |
| 2 | 등급 판정 `floor < 1.0` 을 `floor <= 1.0` 으로 | `evidence.py::_is_statistical` | `test_a_floor_of_one_means_no_statistics_at_all` |
| 3 | score tie-break 의 `x.hypothesis_id == y.hypothesis_id` 조건을 지운다 | `evidence.py::dominates` | `test_score_breaks_ties_only_inside_one_axis` |
| 4 | `if not front: front = list(remaining)` 안전판을 지운다 | `evidence.py::layer_ranks` | `test_layer_ranks_terminates_when_domination_cycles` |
| 5 | 게이트 승인을 `picked is groups[0]` 로 되돌린다 | `nodes.py::_finalize_gate` | `test_gate_approves_any_member_of_the_first_layer` |

훼손 4번은 **무한 루프**다. 그 테스트만 따로 돌리고 20초 안에 안 끝나면 중단한다:

Run: `python -m pytest tests/test_evidence.py -k cycles -x`

**잡히지 않는 훼손이 있으면** 그 자리를 잠그는 테스트를 추가하고 다시 돌린다.
훼손을 되돌렸는지 매번 확인한다: `git diff --stat` 이 빈 출력이어야 다음으로 간다.

- [ ] **Step 3: 워킹 트리가 깨끗한지 확인한다**

Run: `git diff --stat`

Expected: **출력 없음.** 훼손 루프가 도구 타임아웃에 죽어 훼손 파일이 다음 실행의
기준선이 된 사고가 있었다. 한 줄이라도 남아 있으면 되돌린다.

- [ ] **Step 4: 실경로 회귀를 눈으로 확인한다**

Run: `python -m pytest tests/test_multi_axis_dummy.py tests/test_adversarial_dummy.py -q`

Expected: 전부 PASS. 다축 더미(M2423)에서 근거가 여전히 여러 건 실리는지,
`[근거 N]` 의 N 이 위치가 아니라 등수인지 확인한다.

- [ ] **Step 5: 최종 확인**

Run: `python -m pytest -q`

Expected: Step 1 의 수 이상, 0 failed

```bash
git status --short                      # 깨끗해야 한다
git log --oneline main..HEAD            # 스펙 1 + 구현 4 = 5개
```

훼손 실험에서 테스트를 추가했다면 커밋한다.

```bash
git add tests/
git commit -m "test(rank): 훼손 실험에서 안 잡힌 자리를 잠근다"
```

---

## 완료 조건

- `python -m pytest -q` 가 **422 이상 passed, 0 failed**
- `grep -rn "rank_key" --include=*.py --include=*.yaml . | grep -v __pycache__` 가
  빈 출력 (프로퍼티도 주석도 남지 않는다 - Task 3 이 앞을, Task 4 가 뒤를 치운다)
- 훼손 5종이 전부 테스트에 잡힌다
- `git diff` 가 빈 출력 (훼손 잔재 없음)
- `feat/cross-axis-rank` 에 커밋 5개 이상 (스펙 1 + 구현 4)

**병합하지 않는다.** 이 저장소의 관례는 리뷰 뒤 ff 병합이고 리뷰는 별도로 요청한다.
**origin 푸시도 하지 않는다** (사용자가 보류 지시).

## 범위 밖 (다음 작업)

- **A**: 센서·잔차가 `claim_id` 를 받게 한다 (`_is_hypothesis_result` 판별자)
- **B**: `passes=False` 후보를 잔차로 싣는다 (`passing()` 에 매달린 3곳)
- **D/E**: "구분 불가" 판정 신설, 단수 `final_hypothesis` 분해
