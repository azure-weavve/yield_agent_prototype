"""설비/챔버 commonality 분석 (결정론적). 2단 깔때기의 1단.
 
목적: 수만~수십만 개 센서를 보기 전에, **어느 스텝의 어느 설비/챔버가 의심스러운지**를
설비 이력(step_history)만으로 좁힌다. 특징 차원이 스텝 수(~1000) 수준이라 싸다.
 
핵심 계산 — 후보 (스텝, 설비/챔버) 마다 2x2:
 
                통과    미통과
    target       a       b        coverage_target  = a / (a+b)
    control      c       d        coverage_control = c / (c+d)
                                  score = coverage_target - coverage_control
 
score = 1.0 이면 타깃 전원이 거쳤고 대조군은 아무도 안 거친 완전 분리 신호.
 
설계 원칙:
- **p-value 를 계산하지 않는다.** 후보가 수천 개라 다중비교로 유의성 주장이 불가능하다.
  원시 카운트(a/b/c/d)를 그대로 실어, "결론이 아니라 후보"임이 드러나게 한다.
- **root_lot 별 층화.** 대조군은 항상 타깃과 같은 root_lot 에서 나온다(route/시간 교락 차단).
  타깃이 여러 root_lot 에 걸치면(EDS 확장 케이스) stratum 별로 세고 카운트를 합산한다.
- **분모는 그 질문에 답할 수 있는 wafer 만.** 후보 (레벨, 스텝) 마다 "그 스텝에 이력이
  있고 그 레벨 컬럼이 결측이 아닌 wafer" 를 분모로 쓴다. 스텝을 안 지난 wafer 를
  '미통과' 로 세면 score 가 챔버 분리도가 아니라 스텝 통과 여부를 반영한다.
  예외는 step_passage — 모든 wafer 가 "지났는가" 에 답할 수 있어 legend 에
  denominator: all 을 단다. 이력이 아예 없는 wafer 는 missing_history 로 따로 보고한다.
- **lot_type 은 필터가 아니라 컨텍스트.** 평가랏에는 설비 작업 후 검증랏이 섞여 있어
  배제하면 단서를 버린다. 분포만 meta 에 싣는다.
 
의존 테이블 (ETL 선적재 대상):
    step_history(wafer_id, step_seq, eqp_id, ch_id·ppid NULL 허용, timestamp)
    yield(wafer_id, ..., root_lot_id, lot_type)
"""
 
import itertools
import math
import random
import sqlite3
from contextlib import contextmanager
 
import ya_config
 
# config 에 없으면 쓰는 기본값 (실데이터 보고 조정 — 지금 못 박지 않는다)
MIN_TARGET = getattr(ya_config, "COMMONALITY_MIN_TARGET", 2)
TOP_K = getattr(ya_config, "COMMONALITY_TOP_K", 20)
MIN_SCORE = getattr(ya_config, "COMMONALITY_MIN_SCORE", 0.0)

# 순열검정 반복 횟수. 0 이면 순열을 돌리지 않는다 (기존 동작).
N_PERMUTATIONS = getattr(ya_config, "COMMONALITY_PERMUTATIONS", 1000)
# 층화 경우의 수가 이 이하면 전수 열거한다 — 정확하고 더 빠르다.
PERM_EXHAUSTIVE_MAX = 10000
# 고정 시드. 같은 입력이 같은 p 를 내야 테스트도 감사도 성립한다.
PERM_SEED = 20260809
# FDR 표의 임계값 사다리. 실데이터를 보고 조정한다 — 지금 못 박지 않는다.
FDR_THRESHOLDS = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4)

# 계산 자체가 성립하지 않은 상태들. **legend 와 무관한 그룹 수준 사실**이라 다른
# legend 로 다시 돌려도 같은 답이 나온다 — 게이트(graph/nodes.py)가 "남은 가설을 더
# 돌려라" 대신 그 자리에서 사유를 밝히고 끝내는 근거다. 아래 find_commonality 의
# status 서술이 원본이고, 여기는 그중 '계산 불가' 만 추린 것이다.
NO_DATA_STATUSES = frozenset({"insufficient_group", "no_paired_stratum"})

# 기본 legend — EQP_CH (legend 인자 없으면 이 동작). 레벨 순서 = 롤업(설비) → 세부(챔버).
EQP_CH_LEGEND = [
    {"level": "equipment", "columns": ["eqp_id"]},
    {"level": "chamber", "columns": ["eqp_id", "ch_id"]},
]

# legend 컬럼값이 이 토큰이면 결측(NULL/빈문자열과 동일 취급) — ch_id·ppid 등 챔버·PPID
# 개념이 없는 스텝에서 흔히 쓰는 결측 토큰. 2·3단계(metro) 분모도 같은 집합을 쓴다.
# 판정은 legend 의 모든 컬럼에 걸리지만 eqp_id 는 해당 없다 — 사내에서 스킵은 MSKIP1
# 이라는 실제 설비 코드로 기록하기로 약속돼 있어 eqp_id 에 "-" 가 들어오지 않는다
# (2026-08-09 확인). 그 약속이 바뀌면 무엇이 무너지는지는
# tests/test_commonality.py::test_missing_token_on_eqp_id_also_excludes_equipment_denominator
# 에 적어 뒀다.
MISSING_TOKENS = frozenset({"-"})


@contextmanager
def _conn():
    conn = sqlite3.connect(ya_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
 
 
def _wafer_meta(conn, wafer_ids: list[str]) -> dict[str, dict]:
    """wafer_id -> {root_lot_id, lot_type}. ID 를 파싱하지 않고 yield 테이블에서 읽는다."""
    if not wafer_ids:
        return {}
    ph = ",".join("?" * len(wafer_ids))
    rows = conn.execute(
        f"SELECT wafer_id, root_lot_id, lot_type FROM yield WHERE wafer_id IN ({ph})",
        wafer_ids,
    ).fetchall()
    return {r["wafer_id"]: {"root_lot_id": r["root_lot_id"], "lot_type": r["lot_type"]}
            for r in rows}
 
 
def _legend_columns(legend) -> list[str]:
    """legend 전 레벨의 컬럼 순서 있는 합집합."""
    cols = []
    for lvl in legend:
        for col in lvl["columns"]:
            if col not in cols:
                cols.append(col)
    return cols


def _history(conn, wafer_ids: list[str], legend) -> list[sqlite3.Row]:
    if not wafer_ids:
        return []
    table_cols = {r["name"] for r in conn.execute("PRAGMA table_info(step_history)")}
    need = _legend_columns(legend)
    missing = [c for c in need if c not in table_cols]
    if missing:
        raise ValueError(f"legend 컬럼 {missing} 이 step_history 에 없음. "
                         f"가능한 컬럼: {', '.join(sorted(table_cols))}")
    sel = ", ".join(["wafer_id", "step_seq", "timestamp", *need])
    ph = ",".join("?" * len(wafer_ids))
    return conn.execute(
        f"SELECT {sel} FROM step_history WHERE wafer_id IN ({ph})", wafer_ids
    ).fetchall()


def _keys(row, legend) -> list[tuple]:
    """한 이력 행이 기여하는 후보 키들. 각 항목 = (level, step, keystr, colvals).

    레벨 컬럼이 하나라도 NULL/빈문자열/MISSING_TOKENS 면 그 레벨은 건너뛴다(가짜 키
    금지 — ch_id 없는 단일 챔버 설비/챔버 개념 없는 스텝의 챔버 레벨이 자연히 빠진다).
    """
    step = row["step_seq"]
    out = []
    for lvl in legend:
        vals = [row[col] for col in lvl["columns"]]
        if any(v is None or str(v).strip() == "" or str(v).strip() in MISSING_TOKENS
               for v in vals):
            continue
        keystr = "_".join(str(v) for v in vals)
        colvals = dict(zip(lvl["columns"], vals))
        out.append((lvl["level"], step, keystr, colvals))
    return out


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


def _bits_of(mask: int) -> list[int]:
    """마스크를 개별 비트 목록으로. 순열이 이 목록에서 뽑는다."""
    out = []
    while mask:
        low = mask & -mask
        out.append(low)
        mask ^= low
    return out


def _n_permutations_total(strata_masks, seen: int) -> int:
    """층화 섞기의 경우의 수 = stratum 별 조합 수의 곱.

    lot 을 가로질러 섞지 않으므로 전체 섞기(n! 급)보다 훨씬 작다. 이 값이 작다는
    것 자체가 "이 데이터로는 p 를 그 아래로 못 내린다" 는 뜻이라 결과에 싣는다.

    풀을 `seen` 으로 걸러낸다 — 이력이 아예 없는 wafer 는 `_aggregate` 에서 a/c_/
    분모 어디에도 기여하지 않는 불활성 wafer 라 섞어도 agg 가 안 바뀐다. 안 걸러
    내면 경우의 수만 부풀어 p_min_possible(=1/(n_used+1))이 실제로 달성 불가능한
    값이 된다.
    """
    total = 1
    for _rl, t_mask, c_mask in strata_masks:
        pool = ((t_mask | c_mask) & seen).bit_count()
        k = (t_mask & seen).bit_count()
        total *= math.comb(pool, k)
    return total


def _iter_label_sets(strata_masks, n_total: int, n_iter: int, rng, seen: int):
    """회차마다 [(rl, t_mask, c_mask), ...] 를 내놓는다.

    **stratum 안에서만 섞는다.** lot 을 가로지르면 lot 효과가 신호로 잡힌다.
    lot A 에 언제나 타깃 8장이 남아야, "두께 상위에 타깃이 몰린다" 는 lot 효과가
    귀무에도 그대로 남아 올바르게 기각된다 (설계 §2-2).

    이력 없는 wafer(`seen` 밖)는 섞지 않고 원래 쪽에 고정한다 — 불활성이라
    `_n_permutations_total` 도 같은 기준으로 걸러낸다(그 함수 docstring 참고).
    라벨의 t|c 합집합은 원래 t_mask|c_mask 와 항상 같아야 한다 — "그 wafer 가
    사라졌다" 가 아니라 "섞을 후보에서만 뺐다" 는 뜻이어야 하기 때문이다.

    경우의 수가 적으면 전수 열거한다 — 정확하고 더 빠르다. 그때 **관측 라벨은
    건너뛴다.** 관측을 귀무 표본에 넣으면 "넘은 횟수" 가 항상 1 이상이 되어
    p_min_possible 이 절대 달성되지 않고, 공간 부족을 읽을 수 없게 된다.
    """
    pools = [(rl, _bits_of((t_mask | c_mask) & seen), (t_mask & seen).bit_count(),
              t_mask, c_mask, t_mask & ~seen)
             for rl, t_mask, c_mask in strata_masks]

    if n_total <= PERM_EXHAUSTIVE_MAX:
        per_stratum = [list(itertools.combinations(pool, k))
                       for _rl, pool, k, _t, _c, _fixed_t in pools]
        for combo in itertools.product(*per_stratum):
            labels, is_observed = [], True
            for (rl, _pool, _k, t_mask, c_mask, fixed_t), picked in zip(pools, combo):
                t = fixed_t
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
            for rl, pool, k, t_mask, c_mask, fixed_t in pools:
                t = fixed_t
                for b in rng.sample(pool, k):
                    t |= b
                labels.append((rl, t, (t_mask | c_mask) ^ t))
            yield labels


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
    n_total = _n_permutations_total(strata_masks, seen)
    exhaustive = n_total <= PERM_EXHAUSTIVE_MAX
    n_used = (n_total - 1) if exhaustive else n_iter
    if n_used <= 0:
        return None                    # 섞을 수 있는 다른 배치가 없다

    rng = random.Random(seed)
    exceed = {k: 0 for k in observed}
    null_counts = {t: 0 for t in FDR_THRESHOLDS}
    null_max: list[float] = []

    for labels in _iter_label_sets(strata_masks, n_total, n_iter, rng, seen):
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


def _names(mask: int, bits: dict[str, int]) -> list[str]:
    """비트마스크를 wafer id 목록으로 되돌린다 (보고용)."""
    return sorted(w for w, b in bits.items() if mask & b)


def find_commonality(target_wafers: list[str], control_wafers: list[str],
                     legend: list[dict] | None = None,
                     top_k: int | None = None,
                     n_permutations: int | None = None) -> dict:
    """타깃 그룹이 공유하는데 대조군은 거치지 않은 (스텝, 설비/챔버) 후보를 찾는다.
 
    반환 status:
      - "insufficient_group": 타깃이 너무 적어 commonality 가 정의상 무의미
      - "no_paired_stratum" : 타깃과 대조군이 같은 root_lot 에서 짝지어지지 않음
      - "no_signal"         : 계산은 됐으나 분리되는 후보가 없음
                              → 원인 없음이 아니라 **lot 내부 대조로는 안 보임**.
                                원인이 root_lot 전체에 걸리면 타깃·대조군이 같은 챔버를
                                거치므로 score 가 전부 0 이 된다. lot 밖 대조군이 필요하다는
                                신호이며, 향후 대조군 확장(b/c 방식)의 트리거다.
      - "ok"
    """
    legend = EQP_CH_LEGEND if legend is None else legend
    top_k = TOP_K if top_k is None else top_k
    n_permutations = N_PERMUTATIONS if n_permutations is None else n_permutations
    targets = sorted(set(target_wafers or []))
    controls = sorted(set(control_wafers or []) - set(targets))
 
    if len(targets) < MIN_TARGET:
        return {
            "status": "insufficient_group",
            "n_target": len(targets), "n_control": len(controls),
            "candidates": [],
            "note": (f"타깃 {len(targets)}장 < 최소 {MIN_TARGET}장. "
                     f"단일 wafer 는 정의상 모든 경로가 '공통'이라 분석 불가 - "
                     f"EDS 유사 wafer 로 타깃을 확장해야 한다."),
        }
 
    with _conn() as conn:
        meta = _wafer_meta(conn, targets + controls)
        rows = _history(conn, targets + controls, legend)
 
    # ---- root_lot 별 층화 (대조군이 타깃과 같은 route/시기에서 나오도록) ----
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
        return {
            "status": "no_paired_stratum",
            "n_target": len(targets), "n_control": len(controls),
            "candidates": [],
            "note": ("타깃과 같은 root_lot 에 속한 대조군 wafer 가 없다. "
                     "route/시간 교락 없이 비교할 짝이 없어 계산을 중단했다."),
        }
 
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

    if not strata_report:
        return {
            "status": "no_paired_stratum",
            "n_target": len(targets), "n_control": len(controls),
            "candidates": [], "missing_history": sorted(set(missing)),
            "note": "step_history 가 있는 타깃/대조군 짝이 없다 (이력 결측 확인 필요).",
        }
 
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
        if perm:
            cand["p_permutation"] = round(perm["p"][key], 4)
            cand["p_min_possible"] = round(perm["p_min_possible"], 4)
            cand["n_permutations_total"] = perm["n_permutations_total"]
        for col in all_cols:               # legend 컬럼값을 이름별로 (미해당은 None)
            cand[col] = colvals.get(col)
        candidates.append(cand)
 
    candidates.sort(key=lambda r: (-r["score"], -r["coverage_target"],
                                   -r["target_pass"], r["step_seq"], r["key"]))
    truncated = max(0, len(candidates) - top_k)
    candidates = candidates[:top_k]
 
    def _ts(rows, wafers):
        vals = [r["timestamp"] for r in rows
                if r["wafer_id"] in wafers and r["timestamp"] is not None]
        return {"min": min(vals), "max": max(vals)} if vals else None
 
    def _lt(wafers):
        dist: dict[str, int] = {}
        for w in wafers:
            lt = meta.get(w, {}).get("lot_type") or "unknown"
            dist[lt] = dist.get(lt, 0) + 1
        return dist
 
    result = {
        "status": "ok" if candidates else "no_signal",
        "n_target": len(t_seen_all), "n_control": len(c_seen_all),
        "strata": strata_report,
        "candidates": candidates,
        "truncated": truncated,
        "meta": {
            # 시간 교락 진단용 — 두 그룹의 처리 시기가 어긋나면 '공통 설비'가 허상일 수 있다
            "target_time_range": _ts(rows, t_seen_all),
            "control_time_range": _ts(rows, c_seen_all),
            # 평가랏에는 설비 작업 후 검증랏이 섞인다 — 배제하지 않고 해석 재료로 넘긴다
            "target_lot_types": _lt(t_seen_all),
            "control_lot_types": _lt(c_seen_all),
            "missing_history": sorted(set(missing)),
        },
        "note": ("후보는 결론이 아니다. 표본이 작아 우연한 분리가 흔하므로 "
                 "원시 카운트(target_pass/target_total)를 반드시 함께 판단하고, "
                 "지목된 스텝의 센서 비교로 검증해야 한다. target_total 은 그 질문에 "
                 "답할 수 있는 wafer 수이지 타깃 그룹 크기(n_target)가 아니다. "
                 "p_permutation 은 라벨을 root_lot 안에서 섞었을 때 이만한 분리가 "
                 "나오는 비율이다. p_min_possible 이 크면(예: 0.1 이상) 표본이 작아 "
                 "p 를 그 아래로 내릴 수 없다는 뜻이지 신호가 약하다는 뜻이 아니다."),
    }
    if not candidates:
        result["note"] = (
            "타깃만 거친 설비/챔버가 없다. **원인 없음이 아니라 lot 내부 대조로는 "
            "보이지 않는다는 뜻**이다 - 원인이 root_lot 전체에 걸리면 타깃과 대조군이 "
            "같은 경로를 거치므로 분리가 나타나지 않는다. lot 밖 대조군이 필요하다.")
    return result