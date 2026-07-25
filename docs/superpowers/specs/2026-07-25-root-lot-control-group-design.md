# Stage 2 — root_lot 기반 대조군 설계

작성일: 2026-07-25
선행: `docs/stages.md` (Stage 2 진입 조건), `docs/2026-07-24-domain-corrections.md` B-3·B-4
대체: `docs/2026-07-18-status-node-review-and-redesign.md` §7 의 1/2단계 확장 규칙

---

## 0. 문제

대조군을 만드는 `find_normal_wafers` 가 `defect_type = 'none'` 에 의존한다.

```sql
SELECT wafer_id FROM yield
WHERE lot_id = ? AND defect_type = 'none' AND yield >= ?
```

**사내 `defect_type` 은 nullable 이고 대부분 비어 있다** (corrections A-3). 실데이터에서는
이 쿼리가 빈 결과를 내고, 분석이 전부 `no_paired_stratum` 으로 끝난다. Stage 1(실데이터)이
Stage 2 없이 완주할 수 없다고 판단해 순서를 뒤집은 이유가 이것이다.

부차적으로, 현재 규칙은 `lot_id` 기준이라 **같은 root_lot 의 다른 분할 lot 을 못 본다.**
사내에서는 한 root_lot 이 여러 lot 으로 갈리므로, 타깃이 한 분할 lot 에 몰리면 대조군이
0장이 된다.

---

## 1. 결정

| # | 결정 |
|---|---|
| 1 | 대조군 = **타깃과 같은 root_lot 의 비타깃 wafer 전원.** 수율·라벨 조건 없음 |
| 2 | 저수율 혼입은 **필터하지 않고 `meta` 로 보고한다** |
| 3 | **root_lot 단일 단계.** 1/2단계 확장 개념을 폐기한다 |
| 4 | 더미에 **분할 lot 케이스**를 심어 root_lot 기준과 lot 기준의 차이를 테스트로 드러낸다 |

### 문서 관계 (충돌 해소)

07-18 §7 은 「1단계 = 형제 lot 내 `defect 'none'` + 수율 임계 / 2단계 = 같은 root_lot 의 다른
**양산랏**으로 확장 / 3단계 = 정직 보고」였다. 이후 07-24 corrections 가 두 곳을 뒤집었다.

- **B-3 (a)**: 대조군을 처음부터 "같은 root_lot 내 비타깃 wafer" 로 정의 → 단계 개념이 사라진다
- **B-4**: 평가랏은 배제 대상이 아니라 해석 재료 → "양산랏끼리만" 이 철회된다

**이 문서는 07-24 를 따른다.** §7 에서 살아남는 것은 3단계(정직 보고 = `control_insufficient`)와
"리포트에 대조군 출처를 명시한다" 두 가지뿐이다.

### 결정 1 이 눈감는 것 (반드시 인지할 것)

라벨이 없으면 "저수율이지만 타깃 그룹에 안 묶인 wafer" 를 대조군에서 걸러낼 방법이 없다.
그런 wafer 가 실은 같은 원인의 피해자라면, 그 wafer 는 원인 챔버를 거쳤으므로
`control_pass` 를 올리고 **score 를 희석한다** — 진짜 원인이 임계 아래로 내려가 조용히
사라질 수 있다. 더미의 `W2406_07` 이 정확히 이 케이스로 심어져 있다.

우리는 이것을 **막지 않고 보이게 한다** (결정 2). 근거:

- commonality 의 2×2 는 이미 `control_pass` 로 반례를 원시 카운트로 드러낸다. 걸러내면
  오히려 그 정보가 사라진다.
- 수율 임계로 거르면 "임계가 얼마냐" 는 임의 수치가 계산에 들어간다 — 저장소의
  **임의 수치 금지** 원칙과 충돌한다.
- 진짜 판단(이 반례가 진짜인가 피해 wafer 인가)에는 도메인 지식이 필요하다. 그 판단을
  코드가 몰래 내리지 않고 재료를 실어 넘긴다.

---

## 2. 대조군 규칙 (확정)

```
control_group = { w : w ∈ yield
                    ∧ w.root_lot_id ∈ {t.root_lot_id | t ∈ target_group}
                    ∧ w ∉ target_group }
```

- **수율 조건 없음. 라벨 조건 없음. `lot_type` 필터 없음** (평가랏 포함).
- 타깃이 여러 root_lot 에 걸치면 각 root_lot 의 비타깃을 합집합한다.
  commonality 가 root_lot 별로 층화해 세므로 교락은 그쪽에서 통제된다.
- `len(control_group) < config.CONTROL_MIN_SIZE` 면 `insufficient` — 확장하지 않고
  정직 보고한다 (§7 3단계는 유지).

---

## 3. 인터페이스 변경

### 3.1 `tools/yield_tools.py`

`find_normal_wafers(lot_id, threshold)` 를 **삭제**하고 아래로 교체한다.

```python
def find_control_candidates(root_lot_ids: list[str], exclude: set[str]) -> list[str]:
    """주어진 root_lot 들의 비타깃 wafer 전원 (수율·라벨 조건 없음)."""
```

이름을 바꾸는 이유: 이 함수는 더 이상 "정상(normal)" 을 **판정하지 않는다.** 판정이 사라졌으므로
`threshold` 인자도 없앤다. 호출처는 `grouping.select_control` 한 곳뿐이라 교체가 안전하다.

### 3.2 `tools/grouping.py::select_control`

```python
{
    "control_group": [...],          # 정렬된 wafer_id
    "sources": {root_lot_id: [...]}, # 출처 (키가 lot_id → root_lot_id 로 바뀜)
    "insufficient": bool,
    "yield_summary": {               # 결정 2 — 희석을 보이게 하는 자리
        "median": float,
        "n_below_threshold": int,
        "threshold": float,          # config.YIELD_THRESHOLD (판정 아님, 표시 기준)
    } | None,                        # 대조군이 비면 None
}
```

`stage` 키는 **삭제한다** (단계 개념 폐기).

### 3.3 `graph/nodes.py`

- `_summarize_target` 의 대조군 줄을 root_lot 기준으로 바꾸고, 수율 요약을 덧붙인다.

  ```
  대조군 (같은 root_lot 비타깃): 67장 — LOT2402 16장, ... · 수율 중앙값 95.4, 임계 미만 1장
  ```

- `ctrl["stage"]` 참조를 제거한다.
- LLM seed 의 `대조 그룹 (정상):` → **`대조 그룹 (비타깃):`**. 더 이상 정상 판정이 아니므로
  이 단어를 두면 LLM 에게 거짓 전제를 준다.

---

## 4. 더미 — 분할 lot 케이스

사내 ID 관례(root_lot 5자 · `lot_id` 의 `.1`=양산 · `wafer_id = {root_lot}_{no}`)를 쓰는
첫 케이스로 만든다. 기존 더미는 `root_lot_id = lot_id` 1:1 이라 이 축이 무테스트 상태다.

```
root_lot R2418
├─ R2418.1 (prod)   R2418_01~04   타깃 4장   yield 88.6   Etch → ETCH5_B
├─ R2418.2 (eval)   R2418_05,06   비타깃     yield 95.8   Etch → ETCH5_C
└─ R2418.3 (prod)   R2418_07,08   비타깃     yield 95.8   Etch → ETCH5_C
```

**핵심은 `R2418.1` 에 비타깃이 한 장도 없다는 것이다.** 대조군을 `lot_id` 로 찾으면 0장이고,
`root_lot_id` 로 찾아야 `.2`·`.3` 의 4장이 나온다. 수율은 Stage A 의 적대적 lot 과 같은 값을
써서 lot 평균이 임계 이상(92.2)이 되게 한다 — `find_low_yield_lots` 를 흔들지 않기 위해서다.

이 하나가 세 가지를 동시에 시험한다.

1. **`lot_id` 로 묶으면 대조군 0장(`insufficient`), `root_lot_id` 로 묶으면 4장** —
   변경의 효과가 테스트로 드러난다. 테스트는 "같은 `lot_id` 안에 비타깃이 0장" 이라는
   데이터 성질과 "`select_control` 이 4장을 낸다" 는 동작을 각각 확인한다.
2. **평가랏이 대조군에 포함된다** (B-4).
3. **`lot_type` 이 meta 에 `{prod: 2, eval: 2}` 로 실린다** — 필터가 아니라 컨텍스트.

제약은 Stage A 와 같다: 신규 root_lot 만 추가, 기존 wafer·기존 난수열 불변, rows/vectors
맨 끝에 append, lot 평균은 임계 이상으로 잡아 `find_low_yield_lots` 를 흔들지 않는다.

`_augment_yield` 는 현재 `root_lot_id = lot_id`, `lot_type = "prod"` 를 무조건 덮어쓴다.
행에 이미 값이 있으면 보존하도록 바꾼다(`setdefault`).

---

## 5. 기존 계약이 뒤집히는 곳

**`tests/test_e2e.py:15`**

```python
assert "W2406_07" not in state["control_group"]      # 수율 조건 (문제 2)
```

이 단언이 **뒤집힌다.** `W2406_07` 은 "저수율인데 라벨 없는 피해 wafer" 로 심어둔 구멍
케이스이고, 결정 1 에 따라 이제 대조군에 들어간다. 단언을 **지우지 않고 포함되는 것을
확인하는 쪽으로 뒤집고**, 왜 그것이 의도인지 주석으로 남긴다 — 실데이터에서 벌어질 일이
바로 이것이기 때문이다.

`tests/test_grouping.py`·`test_yield_tools.py`·`test_graph_nodes.py` 의 대조군 관련 단언도
새 계약으로 갱신한다.

---

## 6. 테스트 계획

| 테스트 | 확인 |
|---|---|
| `find_control_candidates` 가 수율·라벨 무관하게 비타깃 전원을 낸다 | 결정 1 |
| 저수율·무라벨 wafer(`W2406_07`)가 대조군에 **포함**된다 | 결정 1 (뒤집힌 계약) |
| `yield_summary` 가 임계 미만 장수를 보고한다 | 결정 2 |
| R2418: `select_control` 이 4장을 내고, 같은 `lot_id` 안에는 비타깃이 0장 | 결정 3·4 |
| R2418: 평가랏이 대조군에 포함되고 `lot_type` meta 가 `{prod:2, eval:2}` | B-4 |
| R2418 타깃/대조군 commonality 가 `ETCH5_B` 를 score 1.0 으로 집는다 | 케이스 성립 |
| 대조군이 `CONTROL_MIN_SIZE` 미만이면 `control_insufficient` 유지 | 회귀 |
| 기존 전체 회귀 (기준선 133) | 난수열·데모 보존 |

---

## 7. 위험

**데모 결론이 흔들릴 수 있다.** 대조군이 커지고 저수율 wafer 를 포함하게 된다. 다만 더미의
다른 패턴그룹 wafer 는 `_make_step_history` 에서 Etch 에 `ETCH1~8` 만 받으므로 `ETCH9` 가
나오지 않는다 → `ETCH9_B` 는 score 1.0 을 유지할 것으로 본다. **실행으로 확인**하고, 바뀌면
README 데모 출력도 함께 갱신한다.

**`no_signal` 이 늘어날 수 있다.** 대조군이 넓어지면 타깃만 거친 챔버를 찾기가 더 어려워진다.
이는 결함이 아니라 정직해지는 것이지만, 더미 데모가 밋밋해지면 시연 서사를 다시 봐야 한다.

---

## 8. 범위 밖

- **EDS 비유사성으로 대조군을 거르는 안** — 후보마다 EDS 조회가 붙고 컷오프를 또 정해야
  한다. Stage 4(그룹핑) 소관과 겹치므로 여기서 다루지 않는다.
- **수율 가중 score 보정** — 임의 수치가 계산에 들어가 재현·설명이 어려워진다. 기각.
- **root_lot 밖 확장** (corrections B-3 의 (b)·(c)) — `no_signal` 이 그 트리거이며, 실데이터
  분포를 보고 설계한다 (Stage 5.5 이후).
- `commonality.py`·`engine`·`registry`·게이트는 손대지 않는다.

---

## 9. 완료 기준

1. `defect_type` 이 전부 NULL 이어도 대조군이 정상적으로 만들어진다 (실데이터 전제 충족).
2. R2418 케이스로 root_lot 기준과 lot 기준의 차이가 테스트에 드러난다.
3. 대조군의 수율 분포가 리포트에 보인다.
4. 전체 회귀 green (기준선 133 + 신규).
5. `find_normal_wafers` 가 저장소에서 사라진다 (호출처·테스트 포함).
