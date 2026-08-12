"""metro 계측 commonality — 연속값을 분할점으로 잘라 후보를 만든다.

`find_commonality` 가 후보에게 묻는 질문은 "이 wafer 가 키 K 를 거쳤나, 예/아니오"
하나다. 두께 128.3 은 이 질문이 성립하지 않는다. 그래서 **조합마다 분할점을 탐색해**
`coverage_target - coverage_control` 이 가장 큰 칼 하나를 고른다.

    후보 하나 = (스텝, item, 분할점, 방향)
    (CC001500, THK, 129.0, ge)  ->  "STEP CC001500 두께 평균 129.0 이상"

**왜 별도 도구인가** (2026-08-12 결정)

1. 게이트가 "같은 도구 안 최고 점수" 를 비교한다. metro 후보와 챔버 후보를 한 목록에
   섞으면 서로를 눌러 한쪽만 승인된다 — `step_passage` 를 별도 도구로 뺀 것과 같은
   논리다(`domain/hypotheses.yaml` 의 그 가설 설명에 근거가 있다).
2. 후보 생성 모델이 근본적으로 다르다. `commonality._build_index` 는 "이 키를 거친
   wafer 마스크" 를 **라벨과 무관하게** 미리 만들어 두고 회차마다 popcount 만 다시
   센다. metro 의 분할점은 **라벨에 따라 다시 골라야 한다** — 그게 순열검정이 재려는
   대상 자체다. 따라서 회차마다 스윕을 다시 돌린다.

**그래도 불변식은 지킨다.** "실제와 귀무가 같은 함수 하나를 탄다"(`_aggregate`
docstring). 값 정렬은 라벨과 무관하므로 `_build_metro_index` 에서 **한 번만** 하고,
`_aggregate_metro` 가 라벨마다 그 정렬을 훑는다. 조합당 O(계측된 wafer 수)다.

**순열/FDR 기계는 `commonality` 에서 그대로 꺼내 쓴다.** 그쪽 함수들은 라벨과 점수
목록만 다루지 후보의 생김새를 모르기 때문에 재사용이 성립한다. 새로 쓰는 것은 회차
루프 하나뿐이고, 그 안에서 `_aggregate` 대신 `_aggregate_metro` 를 부른다.

**분모는 "그 (스텝, item) 에 계측값이 있는 wafer" 다** (1단계 원칙). 계측 안 된
wafer 는 '미통과' 가 아니라 분모 밖이다. metro 는 몇몇 스텝에서만, 그것도 lot 당
몇 장만 재기 때문에 이 구분이 다른 축보다 훨씬 크게 작용한다.

**알려진 제약** (여기서 고치지 않는다)

- stratum 별 a·b·c·d 를 합산한 뒤 한 번에 나누는 crude pooling 이라 심슨 역설에
  노출된다. `commonality._score_map` 과 **같은 식을 일부러 쓴다** — metro 만 다른
  척도를 쓰면 순위표에 나란히 못 놓는다. 별건으로 열려 있다
  (`docs/2026-08-07-commonality-설계검토.md` 결함 3).
- 계측값을 lot 대표값으로 퍼뜨리는 경로는 만들지 않는다. 값이 lot 단위 상수가 되면
  `root_lot` 층화 순열에서 라벨을 섞어도 coverage 가 안 변해 p 가 항상 1.0 이 된다.

파워 실측 (2026-08-12, 합성 입력)
---------------------------------

**계측 샘플링이 이 도구의 성패를 가른다.** 사내 계측은 lot 당 3장 정도다.

파워를 정하는 것은 계측된 타깃 **장수**가 아니라 **타깃이 계측된 stratum 수 k** 다.
층화 순열의 경우의 수가 stratum 별 조합 수의 **곱**이라, lot 당 3장이면 대략 `3^k` 이고
p 의 바닥이 `1/3^k` 로 정해진다. score 가 1.000(완전 분리)이어도 이 바닥 아래로는
못 내려간다.

```
  타깃 20 / 대조군 80~480, 조합 20개, 신호 하나를 심고 측정

  계측 방식                      유효 stratum   계측 타깃   p 바닥    심은 신호의 p
  ---------------------------------------------------------------------------
  전수 계측                          4/4          20/20     0.0010    0.0010
  lot 당 10장 (고정)                 4/4           6/20     0.0010    0.0010
  lot 당 3장, 스텝마다 다른 wafer    4/4          20/20     0.0010    0.0480
  lot 당 3장, 고정 슬롯 (4 lot)      2/4           3/20     0.1111    0.1111  <- 못 잡음
  lot 당 3장, 고정 슬롯 (20 lot)    2~7/20        2~7/20    0.11~0.0005  seed 의존
```

읽는 법 세 가지.

1. **lot 당 3장 + 고정 슬롯이면 타깃 대부분이 분모에서 사라진다.** 타깃이 lot 당
   1장이면 그 장이 계측 3장에 뽑힐 확률이 3/25 = 12% 다. 20장이 2~3장이 된다.
2. **타깃이 여러 root_lot 에 흩어질수록 유리하다.** 직관과 반대인데, k 가 커져야
   `3^k` 가 커지기 때문이다. 타깃 20장이 4개 lot 에 몰려 있으면 k 는 최대 4(공간
   81)지만, 20개 lot 에 흩어지면 k 가 7까지 가서 공간이 2187 이 된다.
3. **스텝마다 계측 wafer 가 달라지면 살아난다** (위 표 3행). 조합 하나가 보는
   wafer 수는 그대로지만 `seen` 의 합집합이 커져 순열 공간이 회복된다. **사내가
   고정 슬롯을 쓰는지 스텝마다 다른지가 이 도구의 전제다** — 확인이 필요하다.

성능 실측 (2026-08-12, 같은 입력)
---------------------------------

**설계서 §6 의 "조합당 1.8µs" 추정은 metro 에 안 맞는다.** 그 값은 조합당 popcount
하나를 가정한 것인데, 스윕은 조합당 **계측된 wafer 수**만큼 훑는다.

```
  비용 ~ 조합 수 x 회차 수 x 조합당 계측 wafer 수 x 약 0.45µs

  조합 5000(스텝 1000 x item 5), 전수 계측(조합당 100 wafer), 1000 회차 -> 236초
  같은 조합 수, 계측 wafer 가 조합당 12장이면                        -> 약 28초
```

60초 예산을 넘을 수 있다. **회차 수가 노브인데 전수 열거 경로에서는 안 듣는다** —
`n_permutations_total <= PERM_EXHAUSTIVE_MAX` 면 회차가 그 값으로 정해지므로
`COMMONALITY_PERMUTATIONS` 를 낮춰도 안 변한다(2단계에서 확인한 것과 같은 함정).
다만 샘플링이 심할수록 순열 공간도 같이 줄어 회차가 적어지므로, 실제로는 파워가
부족한 경우와 느린 경우가 서로 반대쪽에 있다.
"""

import sqlite3

from tools.commonality import (MIN_SCORE, MIN_TARGET, N_PERMUTATIONS, PERM_SEED,
                               TOP_K, _conn, _family_wise_p, _fdr_table, _names,
                               _null_distribution, _wafer_meta)

# subitem_id 에 섞여 있는 **통계값** 토큰. 나머지는 개별 측정 포인트다
# (2026-08-12 사내 확인). 1차는 AVG 하나만 후보로 쓰지만 상수는 **집합으로** 둔다 —
# "이 5종이 통계값, 나머지가 포인트" 라는 완전한 분류가 있어야, 나중에 포인트 레벨을
# 얹을 때 통계값이 포인트인 척 섞여 들어오지 않는다 (설계 §8).
STAT_TOKENS = frozenset({"AVG", "MAX", "MIN", "STD", "RANGE"})

# 기본 legend. `where` 가 **행을 거른다** — 기존 legend 는 columns 로 키를 만들 뿐
# 행을 안 걸렀다. 이것이 3단계에서 legend 에 새로 들어가는 유일한 기능이다.
METRO_LEGEND = [
    {"level": "metro", "columns": ["step_seq", "item"], "where": {"subitem_id": "AVG"}},
]


def _norm(v) -> str:
    """토큰 비교용 정규화. 원천이 고정폭 CHAR 이면 'AVG ' 가 섞여 들어오는데,
    그대로 비교하면 그 wafer 만 조용히 빠져 분모가 줄고 점수가 부푼다
    (`data/load_internal.py` 가 step_seq 에서 같은 사고를 겪었다)."""
    return str(v).strip().upper()


def _metro_rows(conn, wafer_ids: list[str], legend) -> list[sqlite3.Row]:
    if not wafer_ids:
        return []
    ph = ",".join("?" * len(wafer_ids))
    return conn.execute(
        "SELECT wafer_id, step_seq, item, subitem_id, value FROM metro "
        f"WHERE wafer_id IN ({ph}) AND value IS NOT NULL", wafer_ids
    ).fetchall()


def _build_metro_index(rows, bits: dict[str, int], legend):
    """계측 행 -> (조합별 정렬된 값, 답할 수 있는 wafer 마스크, 본 wafer, 미상 토큰).

    combos  (레벨, 스텝, item) -> [(값, wafer 비트), ...]  **값 내림차순**
    answer  같은 키 -> 그 조합에 계측값이 있는 wafer 마스크 = 분모 재료
    seen    계측 행이 하나라도 있는 wafer 마스크
    unknown 통계 토큰도 아니고 legend 가 고른 것도 아닌 subitem_id (보고용)

    **정렬은 여기서 한 번만 한다.** 라벨과 무관하므로 순열 회차마다 다시 정렬하면
    회차 수만큼 낭비다. 아래 `_aggregate_metro` 는 이 정렬을 훑기만 한다.

    `where` 절이 **행을 거른다.** 후보 키에 `subitem_id` 가 없으므로 이건 선택이
    아니라 전제다 — 안 거르면 한 wafer 가 같은 조합에 subitem 수만큼 들어간다
    (아래 ValueError 참조).
    """
    combos: dict[tuple, list] = {}
    answer: dict[tuple, int] = {}
    seen = 0
    unknown: set[str] = set()

    for r in rows:
        b = bits.get(r["wafer_id"])
        if b is None:
            continue
        seen |= b
        sub = _norm(r["subitem_id"])
        # 모르는 토큰은 **드러낸다.** 조용히 포인트로 취급하면, 사내 데이터에 새
        # 통계 토큰이 생겼을 때 그것이 포인트인 척 섞여도 아무도 모른다.
        if sub not in STAT_TOKENS:
            unknown.add(r["subitem_id"])
        for lvl in legend:
            want = lvl.get("where") or {}
            if any(_norm(r[col]) != _norm(val) for col, val in want.items()):
                continue                       # 이 레벨이 원하는 행이 아니다
            key = (lvl["level"], r["step_seq"], r["item"])
            # 후보 키에 subitem_id 가 없다. 그래서 한 wafer 가 같은 조합에 두 번
            # 들어오면 **스윕이 그 wafer 를 두 번 센다** — a 가 nt 를 넘어 coverage
            # 가 1.0 을 초과하는데, 예외도 안 나고 숫자만 조용히 틀린다. `where` 를
            # 빠뜨린 legend 가 정확히 이 상태를 만든다(subitem 10종이 한 조합에
            # 뭉친다). 조용히 틀린 답이 LLM 까지 흐르느니 여기서 멈춘다.
            if answer.get(key, 0) & b:
                raise ValueError(
                    f"legend 레벨 '{lvl['level']}' 이 wafer {r['wafer_id']} 의 "
                    f"{key[1]}/{key[2]} 에 값을 여러 개 준다 (예: subitem_id "
                    f"{r['subitem_id']}). 후보 키에 subitem_id 가 없으므로 "
                    f"`where` 로 행을 하나만 남겨야 한다 (예: {{'subitem_id': 'AVG'}}).")
            combos.setdefault(key, []).append((r["value"], b))
            answer[key] = answer.get(key, 0) | b

    for key in combos:
        combos[key].sort(key=lambda vb: -vb[0])
    return combos, answer, seen, unknown


def _sweep(rows, t_valid: int, c_valid: int, nt: int, nc: int):
    """값 내림차순 목록을 한 번 훑어 양방향 최적 분할점을 낸다 — 순수 함수.

    반환 {방향: (score, split, 그 조각의 타깃 수, 그 조각의 대조군 수)}.
    한쪽 방향에 쓸 만한 컷이 없으면 그 방향이 통째로 빠진다.
      ge  "split 이상"   — 위쪽 조각이 특성
      le  "split 이하"   — 아래쪽 조각이 특성

    원시 카운트를 함께 내는 이유는 score 만 보면 6/6 과 2/2 를 구분할 수 없기
    때문이다 (`find_commonality` 가 target_pass 를 싣는 것과 같은 이유).

    **양방향은 공짜다.** 여집합의 score 는 부호만 뒤집힌 값이므로
    (`b/(a+b) - d/(c+d) = (1-cov_t) - (1-cov_c) = -score`), 한 번 훑으며 최댓값과
    최솟값을 같이 기록하면 끝난다. 방향을 못 박으면 반대 방향을 통째로 놓친다 —
    두꺼워서 생기는 불량과 얇아서 생기는 불량은 종류가 다르고 어느 쪽인지 미리
    알 수 없다 (설계 §1).

    **분할점은 서로 다른 값 사이에만 놓는다.** 동점은 가를 수 없으므로 같은 값
    덩어리를 통째로 소비한 뒤에 평가한다.

    **작은 조각은 탐색 범위에서 뺀다.** 타깃이 `MIN_TARGET` 미만인 조각은 어차피
    게이트를 못 지나는데, 시도 횟수에 포함시키면 귀무 기준선만 올라가 실제가 손해를
    본다. 귀무도 이 함수를 타므로 같은 제약이 자동으로 걸린다 (설계 §1-4).

    `le` 의 split 으로 **다음 값**을 싣는 이유: "v 이상" 의 여집합은 "v 미만" 인데,
    엔지니어가 읽는 형태는 "127.0 이하" 라 아래쪽 조각의 최댓값을 실어야 한다.
    """
    best: dict[str, tuple] = {}
    a = c = i = 0
    n = len(rows)
    while i < n:
        v = rows[i][0]
        while i < n and rows[i][0] == v:
            b = rows[i][1]
            if b & t_valid:
                a += 1
            elif b & c_valid:
                c += 1
            i += 1
        if i == n:
            break              # 전체를 포함하는 컷은 분리가 아니다 (여집합이 빈다)
        s = a / nt - c / nc
        if a >= MIN_TARGET and (("ge" not in best) or s > best["ge"][0]):
            best["ge"] = (s, v, a, c)
        if nt - a >= MIN_TARGET and (("le" not in best) or -s > best["le"][0]):
            best["le"] = (-s, rows[i][0], nt - a, nc - c)
    return best


def _aggregate_metro(strata_masks, combos, answer, seen) -> tuple[dict, list]:
    """라벨에서 조합별 최적 후보를 낸다 — 순수 함수. 실제와 귀무가 이 함수를 같이 탄다.

    strata_masks = [(root_lot_id, t_mask, c_mask), ...]

    stratum 을 가로질러 a·nt·c·nc 를 합산한 뒤 한 번에 나눈다 — `commonality._aggregate`
    + `_score_map` 과 **같은 crude pooling** 이다. 분할점은 조합 전체에 하나여야
    하므로(stratum 마다 다른 칼을 고르면 그건 다른 후보다) 정렬도 전역으로 훑는다.
    """
    agg: dict[tuple, dict] = {}
    strata_report = []
    valid_strata = []
    for rl, t_mask, c_mask in strata_masks:
        t_seen, c_seen = t_mask & seen, c_mask & seen
        if not t_seen or not c_seen:
            continue           # 계측이 아예 없는 쪽이 있으면 비교가 성립하지 않는다
        strata_report.append({"root_lot_id": rl,
                              "n_target": t_seen.bit_count(),
                              "n_control": c_seen.bit_count()})
        valid_strata.append((t_mask, c_mask))

    for key, rows in combos.items():
        ans = answer.get(key, 0)
        t_valid = c_valid = 0
        n_strata = 0
        for t_mask, c_mask in valid_strata:
            t_i, c_i = ans & t_mask, ans & c_mask
            # 한쪽이 이 조합에 아무도 답하지 못하면 대비할 짝이 없다
            # (계측 wafer 를 lot 당 몇 장만 뽑으면 이 경로로 stratum 이 통째로 빠진다)
            if not t_i or not c_i:
                continue
            t_valid |= t_i
            c_valid |= c_i
            n_strata += 1
        nt, nc = t_valid.bit_count(), c_valid.bit_count()
        if nt == 0 or nc == 0:
            continue
        best = _sweep(rows, t_valid, c_valid, nt, nc)
        for direction, (score, split, a, c) in best.items():
            if score <= MIN_SCORE:
                continue       # 귀무에도 같은 절단을 건다 (설계 §1-4)
            agg[(*key, direction)] = {
                "score": score, "split": split, "a": a, "c": c,
                "nt": nt, "nc": nc, "strata": n_strata,
            }
    return agg, strata_report


def _permutation_stats_metro(strata_masks, combos, answer, seen,
                             observed: dict[tuple, float], n_iter: int, seed: int):
    """metro 축의 귀무 분포. 회차마다 **분할점 탐색을 다시 돌린다.**

    이것이 다른 축과 다른 유일한 지점이다. 다른 축은 키가 라벨과 무관해 미리 만든
    비트마스크를 다시 세기만 하면 되지만, metro 는 라벨이 바뀌면 최적 분할점도
    바뀐다 — "탐색이 점수를 얼마나 부풀리는가" 가 바로 재려는 대상이므로 귀무도
    같은 탐색을 거쳐야 한다. 안 그러면 실제만 탐색의 이득을 보고 귀무는 못 봐서
    p 가 실제보다 작게 나온다.
    """
    def _scores(labels):
        null_agg, _ = _aggregate_metro(labels, combos, answer, seen)
        return {k: v["score"] for k, v in null_agg.items()}

    return _null_distribution(strata_masks, seen, observed, n_iter, seed, _scores)


def find_metro_commonality(target_wafers: list[str], control_wafers: list[str],
                           legend: list[dict] | None = None,
                           top_k: int | None = None,
                           n_permutations: int | None = None) -> dict:
    """타깃 그룹이 공유하는 계측 구간을 찾는다 — (스텝, item, 분할점, 방향).

    반환 status 는 `find_commonality` 와 같은 어휘를 쓴다 (게이트가 그 어휘로
    "계산 불가" 를 판정하므로 갈리면 안 된다):
      - "insufficient_group": 타깃이 너무 적어 commonality 가 정의상 무의미
      - "no_paired_stratum" : 타깃과 대조군이 같은 root_lot 에서 짝지어지지 않음
      - "no_signal"         : 계산은 됐으나 갈리는 구간이 없음
      - "ok"
    """
    legend = METRO_LEGEND if legend is None else legend
    top_k = TOP_K if top_k is None else top_k
    n_permutations = N_PERMUTATIONS if n_permutations is None else n_permutations
    targets = sorted(set(target_wafers or []))
    controls = sorted(set(control_wafers or []) - set(targets))

    def _empty(status, note):
        return {"status": status, "n_target": len(targets), "n_control": len(controls),
                "candidates": [], "fdr_table": [], "p_family_wise": None,
                "p_family_wise_min_possible": None, "note": note}

    if len(targets) < MIN_TARGET:
        return _empty("insufficient_group",
                      f"타깃 {len(targets)}장 < 최소 {MIN_TARGET}장. 단일 wafer 는 "
                      f"정의상 모든 구간이 '공통'이라 분석 불가 - EDS 유사 wafer 로 "
                      f"타깃을 확장해야 한다.")

    with _conn() as conn:
        meta = _wafer_meta(conn, targets + controls)
        rows = _metro_rows(conn, targets + controls, legend)

    strata: dict[str, dict] = {}
    for wid in targets:
        rl = meta.get(wid, {}).get("root_lot_id")
        strata.setdefault(rl, {"target": set(), "control": set()})["target"].add(wid)
    for wid in controls:
        rl = meta.get(wid, {}).get("root_lot_id")
        if rl in strata:                      # 짝 없는 대조군 root_lot 은 버린다
            strata[rl]["control"].add(wid)

    paired = {rl: s for rl, s in strata.items() if s["target"] and s["control"]}
    if not paired:
        return _empty("no_paired_stratum",
                      "타깃과 같은 root_lot 에 속한 대조군 wafer 가 없다. route/시간 "
                      "교락 없이 비교할 짝이 없어 계산을 중단했다.")

    wafers_all = targets + controls
    bits = {w: 1 << i for i, w in enumerate(wafers_all)}
    combos, answer, seen_bits, unknown = _build_metro_index(rows, bits, legend)

    strata_masks = []
    for rl, s in sorted(paired.items(), key=lambda kv: (kv[0] is None, kv[0])):
        t_mask = c_mask = 0
        for w in s["target"]:
            t_mask |= bits[w]
        for w in s["control"]:
            c_mask |= bits[w]
        strata_masks.append((rl, t_mask, c_mask))

    agg, strata_report = _aggregate_metro(strata_masks, combos, answer, seen_bits)

    # 계측 행이 아예 없는 wafer 는 신호가 아니라 보고 대상이다. stratum 이 스킵돼도
    # 집계와 무관하게 세야 하므로 _aggregate_metro 밖에 둔다.
    t_seen_bits = c_seen_bits = missing_bits = 0
    for _rl, t_mask, c_mask in strata_masks:
        t_seen_bits |= t_mask & seen_bits
        c_seen_bits |= c_mask & seen_bits
        missing_bits |= (t_mask | c_mask) & ~seen_bits
    t_seen, c_seen = set(_names(t_seen_bits, bits)), set(_names(c_seen_bits, bits))
    missing = _names(missing_bits, bits)

    if not strata_report:
        return _empty("no_paired_stratum",
                      "계측값이 있는 타깃/대조군 짝이 없다. metro 는 lot 당 몇 장만 "
                      "재므로 이 상태가 흔하다 - 계측 결측 확인이 필요하다.") | {
            "meta": {"missing_metro": sorted(set(missing))}}

    scores = {k: v["score"] for k, v in agg.items()}

    perm = None
    if n_permutations and scores:
        perm = _permutation_stats_metro(strata_masks, combos, answer, seen_bits,
                                        scores, n_permutations, PERM_SEED)

    candidates = []
    for key, e in agg.items():
        level, step, item, direction = key
        sign = ">=" if direction == "ge" else "<="
        cand = {
            "level": level,
            "step_seq": step,
            "item": item,
            # 사람이 읽는 후보 이름. 게이트는 이 문자열을 **파싱하지 않는다**.
            "key": f"{item} {sign} {e['split']}",
            "split_value": e["split"],
            "split_direction": direction,
            # 원시 카운트 - score 만 보면 5/5 와 2/2 를 구분할 수 없다
            "target_pass": e["a"], "target_total": e["nt"],
            "control_pass": e["c"], "control_total": e["nc"],
            "coverage_target": round(e["a"] / e["nt"], 3),
            "coverage_control": round(e["c"] / e["nc"], 3),
            "score": round(e["score"], 3),
            "n_strata": e["strata"],
        }
        if perm:
            cand["p_permutation"] = round(perm["p"][key], 4)
            cand["p_min_possible"] = round(perm["p_min_possible"], 4)
            cand["n_permutations_total"] = perm["n_permutations_total"]
        candidates.append(cand)

    candidates.sort(key=lambda r: (-r["score"], -r["coverage_target"],
                                   -r["target_pass"], r["step_seq"], r["key"]))
    truncated = max(0, len(candidates) - top_k)
    candidates = candidates[:top_k]

    def _lt(wafers):
        dist: dict[str, int] = {}
        for w in wafers:
            lt = meta.get(w, {}).get("lot_type") or "unknown"
            dist[lt] = dist.get(lt, 0) + 1
        return dist

    note = ("후보는 결론이 아니다. 분할점은 **탐색으로 고른 것**이라 신호가 없어도 "
            "어느 정도 점수가 나온다 - p_permutation 이 그 탐색까지 포함해 잰 값이므로 "
            "score 만 보고 판단하면 안 된다. target_total 은 그 (스텝, item) 에 "
            "계측값이 있는 wafer 수이지 타깃 그룹 크기(n_target)가 아니다 - metro 는 "
            "lot 당 몇 장만 재므로 이 둘이 크게 다르다.")
    if perm:
        note += (" p_min_possible 이 크면(예: 0.1 이상) 표본이 작아 p 를 그 아래로 "
                 "내릴 수 없다는 뜻이지 신호가 약하다는 뜻이 아니다.")

    result = {
        "status": "ok" if candidates else "no_signal",
        "n_target": len(t_seen), "n_control": len(c_seen),
        "strata": strata_report,
        "candidates": candidates,
        "truncated": truncated,
        "fdr_table": _fdr_table(scores, perm["null_counts"], perm["n_used"]) if perm else [],
        "p_family_wise": _family_wise_p(scores, perm["null_max"], perm["n_used"]) if perm else None,
        "p_family_wise_min_possible": round(perm["p_min_possible"], 4) if perm else None,
        "meta": {
            "target_lot_types": _lt(t_seen),
            "control_lot_types": _lt(c_seen),
            # 계측 행이 아예 없는 wafer. 다른 축의 missing_history 와 다른 뜻이다 —
            # 이력은 있는데 그 스텝을 안 쟀을 뿐일 수 있다.
            "missing_metro": sorted(set(missing)),
            # 통계 토큰도 legend 선택도 아닌 subitem_id. 사내에 새 통계 토큰이
            # 생기면 여기서 보인다 (조용히 개별 포인트로 섞이지 않는다).
            "unknown_subitems": sorted(unknown),
        },
        "note": note,
    }
    if not candidates:
        result["note"] = (
            "타깃만 갈라내는 계측 구간이 없다. **원인 없음이 아니라 lot 내부 대조로는 "
            "보이지 않는다는 뜻**이다. metro 는 lot 당 몇 장만 재므로 계측 표본 자체가 "
            "작아 그런 것일 수도 있다 - meta.missing_metro 와 각 후보의 target_total 을 "
            "함께 볼 것.")
    return result
