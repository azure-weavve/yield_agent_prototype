# metro 계측 commonality 구현 계획 (3단계, 더미 선행)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** metro 계측값(두께·CD 등)을 commonality 후보로 낸다. 후보 하나는 **(스텝, item, 분할점, 방향)** 이고, 조합마다 분할점을 탐색해 `coverage_target - coverage_control` 이 가장 큰 칼 하나를 고른다. 탐색이 점수를 얼마나 부풀리는지는 2단계의 순열검정이 그대로 잰다.

**실데이터가 없으므로 더미로 선행한다.** 사내 metro 테이블·컬럼 이름은 아직 없지만 행 모양은 확정됐다(§6). 이 계획의 진짜 산출물 두 가지는 (1) 실데이터가 오면 어댑터만 갈아끼우면 되는 구현, (2) **lot 당 3장 샘플링에서 이 분석이 실제로 신호를 잡는가**에 대한 실측 답이다.

**Architecture:** **별도 도구** `tools/metro_commonality.py` + 가설 `metro_commonality` 신설 (2026-08-12 결정). 순열/FDR 기계는 `tools/commonality.py` 에서 꺼내 쓴다.

- **왜 별도 도구인가.** ① 게이트가 "같은 도구 안 최고 점수" 를 비교하므로 metro 후보와 챔버 후보를 한 목록에 섞으면 서로를 눌러 한쪽만 승인된다 — `step_passage` 를 별도 도구로 뺀 것과 같은 논리다(`hypotheses.yaml` 의 그 가설 설명에 근거가 적혀 있다). ② 후보 생성 모델이 근본적으로 다르다(아래).
- **왜 `passed` 비트마스크를 그대로 못 쓰는가.** `_build_index` 는 "이 키를 거친 wafer 마스크" 를 **라벨과 무관하게** 미리 만들어 두고 회차마다 popcount 만 다시 센다(`commonality.py:194`). metro 의 분할점은 **라벨에 따라 다시 골라야 한다** — 그게 순열검정이 재려는 대상 자체다. 따라서 회차마다 스윕을 다시 돌린다.
- **그래도 불변식은 지킨다.** "실제와 귀무가 같은 함수 하나를 탄다"(`_aggregate` docstring). 값 정렬은 라벨과 무관하니 **미리 한 번만** 하고, 라벨마다 그 정렬을 훑는다. 조합당 O(계측된 wafer 수)이고 lot 당 3장이라 그 수가 작다.

**Tech Stack:** Python 3.11, 표준 라이브러리만. 새 의존성 없음.

## Global Constraints

- 설계 근거: `docs/superpowers/specs/2026-08-08-metro-commonality-design.md` §1(분할점)·§6(데이터 모양·샘플링)·§9(테스트)
- 브랜치: `main`(`91dc94d`)에서 `feat/metro-commonality` 로 분기
- 주석·docstring·테스트 이름 설명은 **한국어**. 기존 파일 문체를 그대로 따른다
- 콘솔이 cp949 라 파이썬 실행은 항상 `python -X utf8` 로 한다
- 테스트: `python -X utf8 -m pytest -q`. **기준선 233 passed** (`main`, `91dc94d`)
- **게이트는 바꾸지 않는다.** p 는 판단 재료로 싣기만 한다 (2단계와 같은 원칙)
- **1차는 `AVG` 하나만.** 포인트별 세부는 범위 밖(§8). 다만 통계 토큰은 **5종 집합**으로 못 박는다
- 순열은 **root_lot 안에서만** 섞는다. 실제와 귀무에 **같은 절단**(`MIN_SCORE`)·**같은 작은 조각 제외**(`MIN_TARGET`)를 건다
- **분모는 (A) wafer 단위** — 그 (스텝, item) 에 계측값이 있는 wafer 만. lot 대표값으로 퍼뜨리지 않는다 (아래 "알려진 제약" 참고)

## 알려진 제약 (이번에 고치지 않는다)

1. **crude pooling / 심슨 역설.** `_score_map` 은 stratum 별 a·b·c·d 를 합산한 뒤 한 번에 나눈다. metro 도 같은 식을 쓰므로 같은 제약을 물려받는다. `docs/2026-08-07-commonality-설계검토.md` 결함 3 으로 **여전히 열려 있는 별건**이다. 여기서 다르게 하면 metro 만 다른 척도가 되어 더 나쁘다.
2. **lot 대표값 경로 (B) 는 만들지 않는다.** metro 값이 lot 단위 상수가 되면 `root_lot` 층화 순열에서 라벨을 섞어도 coverage 가 변하지 않아 `p` 가 항상 1.0 이 된다(파워 0). 층화 축은 1단계가 교락 차단으로 세운 벽이라 여기서 건드릴 문제가 아니다.
3. **재작업 회차 처리 없음.** metro 에는 재작업이 없다(2026-08-12 확인). `(wafer_id, step_seq, item, subitem_id)` 유일성을 **적재 검증으로 못 박는** 것으로 갈음한다.

---

## Task 1: metro 테이블 + 더미 생성기

**목표:** 실데이터가 오기 전에 얹을 수 있는 테이블과, 신호를 심은 더미를 만든다.

행 모양은 §6 에서 확정된 것을 그대로 쓴다.

```sql
CREATE TABLE metro (
    wafer_id    TEXT NOT NULL,
    step_seq    TEXT NOT NULL,
    item        TEXT NOT NULL,     -- 계측 항목 (THK, CD ...)
    subitem_id  TEXT NOT NULL,     -- 측정 포인트 또는 통계값 (AVG/MAX/MIN/STD/RANGE)
    value       REAL,
    tkin_time   TEXT,              -- 스텝 진입
    tkout_time  TEXT               -- 스텝 진출 (회차 정렬 기준)
);
```

**더미가 반드시 담아야 하는 것** (하나라도 빠지면 뒤 Task 의 테스트가 공허해진다):

- **통계 토큰 5종 + 개별 포인트.** `AVG`·`MAX`·`MIN`·`STD`·`RANGE` 와 `P01`~`P05`. 거르기가 실제로 일하는지 보려면 개별 포인트가 **avg 와 상관된 채로** 있어야 한다 (안 그러면 필터를 꺼도 top_k 가 안 잠식돼 변별력 테스트가 통과해 버린다)
- **계측 결측 조합 하나.** 메인 더미는 **전수 계측**으로 둔다 — 17 wafer 짜리 무대에 lot 당 3장을 걸면 남는 것이 6장뿐이라 파이프라인 데모도 스윕 테스트도 못 한다. 대신 조합 하나만 일부 wafer 를 빼서 **분모가 "계측된 wafer" 인지**를 잠근다. lot 당 3장 샘플링의 파워 실측은 Task 6 의 파라미터화된 합성 입력에서 한다 (거기서는 wafer 수를 마음대로 키울 수 있다)
- **심어둔 신호.** 한 (스텝, item) 에서 타깃의 avg 가 두껍다. 정답지는 `_truth_metro` 로만 들고 **DB 에 안 나간다** (기존 `_truth_*` 관행)
- **얇은 쪽 신호 하나** — 양방향(`le`) 후보가 나오는지 볼 무대
- **lot 효과만 있는 조합 하나** — root_lot 별로 값이 통째로 다르지만 불량과는 무관. 층화 섞기가 이걸 올바르게 기각해야 한다 (설계 §2-2 의 예)
- **동점 값이 뭉친 조합 하나** — 분할점을 동점 사이에 놓지 않는지 볼 무대

- [ ] 1.1 `data/generate_dummy.py` 에 `metro` 테이블 DDL 과 생성 로직 추가
- [ ] 1.2 `tests/test_schema_contract.py:126` 의 3-테이블 고정을 4개로 갱신 (이 테스트는 "테이블이 조용히 늘어나는 것" 을 막으려고 있는 장치다 — 이유를 주석에 남긴다)
- [ ] 1.3 더미 검증 테스트: 심어둔 신호가 데이터에 실제로 있는가, 샘플링률이 의도대로인가, 토큰 5종과 포인트가 다 있는가

**verify:** `python -X utf8 data/generate_dummy.py` 후 `python -X utf8 -m pytest -q tests/test_dummy_data.py tests/test_schema_contract.py` 통과

---

## Task 2: 분할점 스윕 (라벨의 순수 함수)

**목표:** 값이 정렬된 조합 하나와 라벨을 받아 최적의 (분할점, 방향, score) 를 낸다.

```
  입력   rows = [(value, wafer_bit), ...]  값 내림차순, 라벨과 무관 (미리 정렬)
         t_mask, c_mask, nt, nc
  출력   (score, split_value, direction)   direction ∈ {"ge", "le"}
```

- 값 내림차순으로 훑으며 `a`(타깃 누적)·`c`(대조군 누적)를 증분 갱신하고 매 경계에서 `a/nt - c/nc` 를 본다
- **분할점은 서로 다른 값 사이에만.** 동점 구간은 통째로 넘긴 뒤에 평가한다
- **양방향은 공짜다.** 여집합의 score 는 부호만 뒤집힌 값이라(설계 §1) 훑으면서 **최댓값과 최솟값을 같이 기록**하면 끝난다. 최솟값 쪽이 `le` 방향 후보가 된다
- **작은 조각 제외.** `ge` 방향은 `a < MIN_TARGET` 인 경계를, `le` 방향은 `nt - a < MIN_TARGET` 인 경계를 **탐색 범위에서 뺀다.** 귀무에도 똑같이 걸린다

- [ ] 2.1 `_sweep()` 구현
- [ ] 2.2 테스트 (설계 §9 "분할점 탐색" 5건): 심어둔 분할점을 경계값까지 정확히 찾는가 / 동점 사이에는 안 놓는가 / 얇은 쪽 신호에서 `le` 가 나오는가 / 타깃 1장짜리 조각이 후보로 안 나오는가 / **조합 하나가 후보를 하나만 내는가**

**verify:** 위 5건 통과

---

## Task 3: metro 색인 + 집계

**목표:** 라벨만 바꿔 다시 부를 수 있는 집계 함수를 만든다. 실제와 귀무가 이 함수 하나를 같이 탄다.

- `_build_metro_index(rows, bits)` → `(step, item)` → 값 내림차순 `[(value, bit)]`, 그리고 `answer` 마스크(= 그 조합에 계측값이 있는 wafer). **정렬은 여기서 한 번만** 한다
- `_aggregate_metro(strata_masks, index)` → 조합키 → `(score, split, direction, a, nt, c, nc)`
- **분모 = `answer` 마스크 ∩ 그 stratum** — "그 질문에 답할 수 있는 wafer"(1단계 원칙). 계측 안 된 wafer 는 '미통과' 가 아니라 분모 밖이다
- 한쪽이 그 조합에 아무도 답하지 못하면(`nt == 0` 또는 `nc == 0`) 후보를 내지 않는다

- [ ] 3.1 `_build_metro_index()` 구현
- [ ] 3.2 `_aggregate_metro()` 구현 (stratum 별로 세어 합산 — 기존 `_aggregate` 와 같은 crude pooling)
- [ ] 3.3 테스트: **계측 안 된 wafer 가 분모에서 빠지는가**(가장 중요) / 짝 없는 stratum 이 스킵되는가 / 라벨만 바꿔 부르면 결과가 라벨에만 의존하는가

**verify:** 위 3건 + Task 2 통과

---

## Task 4: 순열검정 + FDR 배선

**목표:** 2단계 기계를 metro 에 붙인다. **새로 만들지 않고 꺼내 쓴다.**

`commonality.py` 에서 그대로 재사용: `_iter_label_sets`, `_n_permutations_total`, `_bits_of`, `_fdr_table`, `_family_wise_p`, `PERM_EXHAUSTIVE_MAX`, `PERM_SEED`, `FDR_THRESHOLDS`. 이들은 **라벨과 점수 목록만 다루지 후보의 생김새를 모른다** — 그래서 재사용이 성립한다.

metro 전용으로 새로 쓰는 것은 회차 루프 하나뿐이다(`_aggregate` 대신 `_aggregate_metro` 를 부른다).

- [ ] 4.1 재사용을 위한 최소 정리 — `commonality.py` 에서 가져다 쓰되 **동작은 한 줄도 바꾸지 않는다**. 233 passed 가 그대로여야 한다
- [ ] 4.2 `_permutation_stats_metro()` 구현
- [ ] 4.3 테스트 (설계 §9 "순열검정"): **신호 없는 데이터에서 p 가 큰가**(가장 중요) / lot 효과만 있는 조합을 층화 섞기가 올바르게 기각하는가 + **전체 섞기로 바꾸면 거짓 양성이 나는가**(변별력) / 소표본에서 `p_min_possible` 이 실리는가 / 한 회차에 같은 라벨이 전 조합에 쓰이는가

**verify:** 위 + 기존 233 passed 무변동

---

## Task 5: legend 행 거르기 + 도구·가설 배선

**목표:** `AVG` 행만 후보가 되게 하고, 결과를 LLM 이 읽는 자리까지 잇는다.

```yaml
legend:
  - {level: metro, columns: [step_seq, item], where: {subitem_id: AVG}}
```

- `STAT_TOKENS = frozenset({"AVG", "MAX", "MIN", "STD", "RANGE"})` — 1차는 `AVG` 만 쓰지만 **집합으로** 못 박는다. "이 5종이 통계값, 나머지가 개별 포인트" 라는 완전한 분류가 있어야 §8 에서 포인트 레벨을 얹을 때 통계값이 포인트인 척 안 섞인다
- 비교 전에 **대소문자·공백을 정규화**한다. 고정폭 CHAR 잔재가 `step_seq` 를 두 군으로 쪼갠 전례가 있다(`load_internal.py:155`)
- **모르는 토큰이 들어오면 드러난다.** 조용히 개별 포인트로 취급하면 사내 데이터에서 통계값이 포인트인 척 섞인다 — 결과 `meta` 에 미상 토큰 목록을 싣는다
- 공개 함수 `find_metro_commonality(target_wafers, control_wafers, legend=None, top_k=None, n_permutations=None)` — 반환 계약은 `find_commonality` 와 같은 모양에 `split_value`·`split_direction` 두 키가 추가된다
- `domain/engine.py` 어댑터와 `domain/hypotheses.yaml` 에 `metro_commonality` 추가. **2단계에서 잘려 나갔던 필드(`p_min_possible`·`fdr_table`·`p_family_wise` 계열)가 처음부터 다 통과하는지 확인한다** — 그때 터진 것과 같은 자리다

- [ ] 5.1 legend 행 거르기 + `STAT_TOKENS`
- [ ] 5.2 `find_metro_commonality()` 공개 함수
- [ ] 5.3 engine 어댑터 + `hypotheses.yaml`
- [ ] 5.4 테스트 (설계 §9 "subitem 거르기"): avg 행만 후보가 되는가 / **거르지 않으면 한 item 이 `top_k` 를 잠식하는가**(변별력 — 이걸 안 보면 필터가 일하는지 알 수 없다) / 모르는 토큰이 조용히 안 섞이는가 / **LLM 이 읽는 dict 에 약속한 필드가 다 있는가**

**verify:** 위 + 전체 스위트 통과

---

## Task 6: 파워·성능 실측 (이 계획의 두 번째 산출물)

**목표:** "lot 당 3장 계측에서 이 분석이 쓸모가 있는가" 에 숫자로 답한다. 코드가 아니라 **답**이 산출물이다.

- [ ] 6.1 **파워:** 같은 심어둔 신호를 (a) 전수 계측 (b) lot 당 3장 계측 두 더미에서 돌려 `score`·`p_permutation`·`p_min_possible` 을 나란히 적는다. **타깃 계측이 0장인 조합의 비율**도 센다
- [ ] 6.2 **성능:** 조합 5,000개(스텝 1,000 x item 5) 규모 합성 입력으로 실제 소요를 잰다. 설계서 §6 의 9초 추정은 조합당 popcount 하나를 가정한 것이라 **스윕이 들어간 실제와 다를 수 있다** — 그 차이를 측정해 적는다
- [ ] 6.3 결과를 `tools/metro_commonality.py` 상단 docstring 과 설계서 §6 에 적는다 (2단계가 실측을 모듈 docstring 에 남긴 것과 같은 방식)

**verify:** 실측 수치가 문서에 적혔고, 파워가 부족하다는 결론이면 그 사실이 명시적으로 적혔다

---

## 완료 조건

- 전체 스위트 통과, 기존 233건 무변동
- Task 6 의 파워 실측 답이 문서에 있다
- 실데이터가 오면 **바꿀 곳이 어댑터 한 곳**이라는 것이 코드에서 보인다
