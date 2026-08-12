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
"""

import sqlite3

from tools.commonality import MIN_SCORE, MIN_TARGET

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

    `where` 절이 **행을 거른다.** 거르지 않으면 한 item 의 AVG 와 그 구성 포인트가
    한 목록에서 겨루어 top_k 를 잠식한다 — 순열검정이 상관을 자동 반영하므로
    통계적으로 틀리지는 않지만, 다른 스텝의 진짜 신호가 목록 밖으로 밀린다.
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
