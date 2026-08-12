"""더미 데이터 생성 스크립트.

설계 문서 3.1절 스키마를 따른다.
- yield 테이블 (SQLite): wafer_id, lot_id, yield, defect_type, step_seq, date
  ⚠️ `defect_type`·`step_seq` 은 **전 행 NULL** 이다 (실데이터에 이 라벨이 없다).
     생성기가 어디에 이상을 심었는지는 `_truth_*` 로만 들고 있고 DB 에 안 나간다.
- 512차원 맵 임베딩 인덱스 (hnswlib): wafer_id -> 512d 벡터

핵심 = "유사 그룹 심기":
  정상 다수 + 몇 개의 패턴 그룹.
  각 패턴 그룹은
    (가) 임베딩 공간에서 서로 가깝다 (그룹 중심 벡터 + 작은 noise).
    (나) 같은 불량 유형에서 나왔다 (생성기 내부 `_truth_defect` — 데이터에는 없다).
    (다) date 가 과거~최근에 분포 (그룹당 최근 1장 + 과거 4~5장).
  최근 1장은 시나리오 1에서 수율 낮게 잡힐 wafer,
  나머지 과거 장들은 시나리오 2의 유사 검색 결과가 된다.
  추가로 RECENT_LOT 은 그룹 대조 시나리오 무대다: 짝수 번호 3장이 같은 임베딩 중심과
  같은 이상 챔버(ETCH9_B)를 공유하고, 홀수 번호 3장은 그렇지 않다.
"""

import json
import sqlite3
import sys
from pathlib import Path

import hnswlib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ya_console import say                        # noqa: E402

# ---------------------------------------------------------------- 설정 (문서 9절 기본값)
SEED = 42
DIM = 512  # 실제 시스템과 동일 차원

N_NORMAL = 80  # 정상 wafer 수
# 그룹 응집도. 단위 길이 중심 벡터에 더할 noise 의 대략적 '노름'.
# 512차원에서 그대로 standard_normal 을 쓰면 노름이 sqrt(DIM)~23 으로 커져
# 중심을 압도하므로, 실제 noise 는 1/sqrt(DIM) 로 스케일한다 (_make_member 참고).
# 0.30 -> 그룹 내 코사인 유사도 약 0.95.
GROUP_NOISE = 0.30

# 그룹 대조 시나리오 (RECENT_LOT): 짝수 번호 3장이 같은 불량(불량 그룹),
# 홀수 번호 3장은 정상(대조 그룹) — "유사 불량을 묶어 정상과 대조"의 데모 무대.
# 수율 범위는 lot 평균 < YIELD_THRESHOLD(90) 를 난수와 무관하게 보장한다: (82+97)/2 = 89.5.
FEATURED_DEFECT = "center_spot"
FEATURED_PROCESS = "Etch"      # 정답지용 공정명 (DB 에 안 나간다 — `_truth_step`)

# 공정 경로. 사내 `step_seq` 는 **문자 2자리(제품군) + 숫자 6자리(스텝 순서)** 다
# ("CC001000"). 공정명은 원천에서 별개 컬럼 `area` 로 오므로 더미도 둘을 짝으로 든다.
# 순번에 여유(1000 단위)를 두는 것은 중간 스텝이 끼어도 순서가 유지되게 하는 관행이다.
# 시나리오 코드는 `area`(사람이 읽는 공정명)로 분기하고, DB 에 실리는 스텝 값은 `seq` 다.
ETCH_SEQ = "CC002000"          # 신호를 심는 스텝 (ETCH9_B·PPID_X 가 여기 있다)
SH_STEPS = [("CC001000", "Photo"), (ETCH_SEQ, "Etch"),
            ("CC003000", "Diffusion"), ("CC004000", "CMP")]     # wafer 당 경로
GROUP_WAFERS = ["W2406_02", "W2406_04", "W2406_06"]    # 불량 그룹 (수율 낮음)
CONTROL_WAFERS = ["W2406_01", "W2406_03", "W2406_05"]  # 대조 그룹 (정상)

# 구멍 케이스: 더미가 너무 착해서 안 드러나던 설계 구멍을 데이터로 드러낸다
# (docs/2026-07-18-status-node-review-and-redesign.md 2절·4절).
# (가) UNLABELED_LOW_WAFER: 저수율인데 심어 둔 패턴이 없다 — 대조군 선정에 수율
#     조건이 없으면 대조군에 섞인다. 그 오염이 대조 결과를 희석하는 것을 재현한다.
# (나) UNGROUPED_LOT: 저수율 lot 2개째 — 임베딩이 흩어져 있어 유사도로 그룹을
#     못 묶는 출구 B 의 무대. 평균 89.83 은 임계(90) 미만이되
#     LOT2406 평균의 최대치(89.4)보다 높아 lots[0] 자리는 LOT2406 이 유지한다.
UNLABELED_LOW_WAFER = "W2406_07"
UNLABELED_LOW_YIELD = 88.5
UNGROUPED_LOT = "LOT2407"
UNGROUPED_WAFERS = [("W2407_01", 87.5), ("W2407_02", 89.5), ("W2407_03", 92.5)]

# 패턴 그룹: 전부 과거 wafer — search_similar 의 유사 사례 풀.
# center_spot 그룹은 GROUP_WAFERS 와 같은 임베딩 중심을 공유한다.
PATTERN_GROUPS = [
    {"defect": "edge_ring", "process": "Diffusion", "n_past": 5},
    {"defect": "center_spot", "process": "Etch", "n_past": 4},
    {"defect": "scratch", "process": "CMP", "n_past": 4},
    {"defect": "donut", "process": "Photo", "n_past": 4},
]

RECENT_LOT = "LOT2406"  # "이번 배치" — 최근 패턴 wafer 들이 모이는 lot
RECENT_DATE = "2024-06-15"
PAST_DATES = ["2024-01-15", "2024-02-12", "2024-03-18", "2024-04-22", "2024-05-09"]
NORMAL_LOTS = ["LOT2401", "LOT2402", "LOT2403", "LOT2404", "LOT2405"]

# ---------------------------------------------------------------- 적대적 케이스
# 위 시나리오는 "정답을 심어둔 데이터" 라, 전부 green 이어도 그게 실력인지 데이터가
# 착한 건지 구분할 수 없다 (07-18 리뷰: 「더미 데이터가 너무 착해서 안 드러난다」).
# 아래 4개 lot 은 그 구분을 만들기 위한 실패 모드다. 5번째(대조군 부족)는 LOT2407 로
# 이미 존재한다.
#
# 제약 — 기존 wafer·기존 난수열을 건드리지 않는다. 전부 신규 lot 이고 rows/vectors 의
# 맨 끝에 붙는다. yield 는 **lot 평균이 임계(90) 이상**이 되게 잡아 find_low_yield_lots
# 에 잡히지 않게 한다 (자동 대상 선정 = 데모 흐름을 흔들지 않기 위해).
ADV_COUNTEREX_LOT = "LOT2414"   # 케이스 1: 반례 살아있음 (score < 1.0)
ADV_DECOY_LOT     = "LOT2415"   # 케이스 2: 근접 미끼 (진짜 1.0 옆에 0.75)
ADV_MISSING_LOT   = "LOT2416"   # 케이스 3: 이력 결측 · ch_id NULL
ADV_NOSIGNAL_LOT  = "LOT2417"   # 케이스 4: "모른다" 가 정답 (no_signal)

ADV_CASES = {                    # lot -> (타깃 수, 대조군 수)
    ADV_COUNTEREX_LOT: (4, 5),
    ADV_DECOY_LOT:     (4, 5),
    ADV_MISSING_LOT:   (4, 4),
    ADV_NOSIGNAL_LOT:  (4, 4),
}

# 타깃은 임계 미만(대조군 후보에서 자연히 빠진다), 대조군은 임계 이상.
ADV_TARGET_YIELD, ADV_CONTROL_YIELD = 88.6, 95.8


def adv_group(lot: str) -> tuple[list[str], list[str]]:
    """적대적 lot 의 (타깃, 대조군) wafer id. 테스트가 이 함수를 그대로 쓴다."""
    n_t, n_c = ADV_CASES[lot]
    tag = lot[-4:]
    ids = [f"W{tag}_{i:02d}" for i in range(1, n_t + n_c + 1)]
    return ids[:n_t], ids[n_t:]


ADV_WAFERS = {w for lot in ADV_CASES for grp in adv_group(lot) for w in grp}
ADV_MISSING_WAFER = adv_group(ADV_MISSING_LOT)[0][3]      # step_history 자체가 없는 타깃
ADV_NULL_CH_WAFERS = tuple(adv_group(ADV_MISSING_LOT)[1][:2])  # Etch 행의 ch_id 가 NULL

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

# ---------------------------------------------------------------- 비정규 스텝 케이스
# 사내 step_seq 는 비정규 스텝이면 뒤에 `EC` 가 붙는다("CC002000EC"). 지나는 lot 과
# 안 지나는 lot 이 갈리고, 거기서 문제가 생겨 조치한 이력이 있어 **통과 여부 자체가
# 분석 대상**이다. 그런데 설비/PPID 축은 "그 스텝 안에서 무엇을 썼는가" 만 보므로
# 이 신호를 못 잡는다 — 타깃이 비정규 스텝을 **제각각 다른 설비·PPID 로** 거치면
# 후보가 wafer 수만큼 쪼개져 전부 판별선 아래로 떨어진다.
# 그래서 이 케이스는 step_passage 축이 **아니면 못 잡는다**는 것을 고정한다.
IRREG_ROOT_LOT = "E2419"
IRREG_STEP = ETCH_SEQ + "EC"                                   # "CC002000EC"
IRREG_TARGETS = [f"{IRREG_ROOT_LOT}_{i:02d}" for i in (1, 2, 3, 4)]
IRREG_CONTROLS = [f"{IRREG_ROOT_LOT}_{i:02d}" for i in (5, 6, 7, 8)]
IRREG_WAFERS = set(IRREG_TARGETS + IRREG_CONTROLS)

# ---------------------------------------------------------------- metro 계측 케이스
# 3단계 무대. 계측값은 연속값이라 "거쳤나 예/아니오" 가 성립하지 않고 **분할점을
# 탐색**해야 한다. 후보 하나 = (스텝, item, 분할점, 방향).
#
# **root_lot 이 둘인 것이 핵심이다.** 층화 섞기가 lot 효과를 올바르게 기각하는지
# 보려면 두 lot 의 타깃 비율이 달라야 한다 (설계 §2-2). T2421 은 타깃 4/7, T2422 는
# 1/10 이라 "lot 으로만 갈리는 값" 이 전체 섞기에서는 신호처럼 보인다.
#
# 층화 경우의 수 = C(7,4) x C(10,1) = 350 이라 전수 열거 경로를 타고 p 가 결정론적이다.
METRO_ROOT_LOTS = ("T2421", "T2422")
METRO_TARGETS = ["T2421_01", "T2421_02", "T2421_03", "T2421_04", "T2422_01"]
METRO_CONTROLS = (["T2421_05", "T2421_06", "T2421_07"]
                  + [f"T2422_{i:02d}" for i in range(2, 11)])
METRO_WAFERS = set(METRO_TARGETS + METRO_CONTROLS)

# 계측 스텝. 처리 스텝(SH_STEPS) 사이에 낀다 — 실데이터도 계측 스텝이 이력에 남는다.
METRO_STEPS = ("CC001500", "CC002500", "CC003500")
METRO_ITEMS = ("THK", "CD")

# subitem_id 에는 개별 측정 포인트와 **그 포인트들의 통계값이 섞여** 있고 이름 규칙으로
# 구분한다 (2026-08-12 사내 확인). 1차 분석은 AVG 만 쓰지만, 거르기가 실제로 일하는지
# 보려면 포인트가 **avg 와 상관된 채로** 있어야 한다 — 상관이 없으면 필터를 꺼도
# top_k 가 안 잠식돼서 변별력 테스트가 공허해진다.
METRO_STAT_SUBITEMS = ("AVG", "MAX", "MIN", "STD", "RANGE")
METRO_POINT_SUBITEMS = ("P01", "P02", "P03", "P04", "P05")
# 합이 정확히 0 — AVG 가 진짜로 포인트들의 평균이 된다. 어느 것도 0 이 아니라
# "포인트 하나가 우연히 AVG 와 같은 값" 이 되는 모호한 케이스를 만들지 않는다.
METRO_POINT_OFFSETS = (-0.35, -0.18, 0.07, 0.19, 0.27)

# 조합(스텝 x item)마다 역할을 하나씩 맡긴다. 난수를 쓰지 않는다 — 케이스가 난수에
# 흔들리면 심어둔 분할점을 테스트가 못 잠근다 (_make_adversarial_steps 와 같은 원칙).
METRO_TRUE_GE = (METRO_STEPS[0], "THK")   # 진짜 신호: 타깃이 두껍다 (ge 방향)
METRO_NOISE = (METRO_STEPS[0], "CD")      # 무신호
METRO_TRUE_LE = (METRO_STEPS[1], "THK")   # 얇은 쪽 신호 (le 방향) — 양방향 무대
METRO_TIED = (METRO_STEPS[1], "CD")       # 동점 뭉침: 값이 3종류뿐
METRO_LOT_EFFECT = (METRO_STEPS[2], "THK")  # lot 으로만 갈린다 (불량과 무관)
METRO_PARTIAL = (METRO_STEPS[2], "CD")    # 일부 wafer 만 계측 — 분모 무대

# 심어둔 정답. DB 에 안 나간다 (`_truth_*` 관행과 같은 취급).
METRO_TRUTH_GE_SPLIT = 129.0              # "129.0 이상" 이 최적 분할
METRO_TRUTH_LE_SPLIT = 127.0              # "127.0 이하" 가 최적 분할
# METRO_PARTIAL 에서 계측이 빠지는 대조군. 분모를 "계측된 wafer" 로 안 세면
# 이 wafer 들이 '미통과' 로 섞여 가짜 후보가 뜬다 (1단계가 고친 분모 conflation).
METRO_UNMEASURED = ("T2421_06", "T2421_07",
                    "T2422_07", "T2422_08", "T2422_09", "T2422_10")

# ---------------------------------------------------------------- 센서 (2단 깔때기)
# 트레이스가 아니라 **wafer 1장의 구간 통계값**이다. 구간·통계 종류는 센서 이름에
# 들어 있다(rf_power_steady_avg) — 사내 FDC 추출물 형태.
# 그래서 ..._avg 와 ..._std 가 서로 독립된 센서가 되고, '평균은 같은데 분산만 이동'
# 케이스가 비교 로직의 별도 처리 없이 후보에 오른다.
SENSOR_STEP = ETCH_SEQ                  # 1단이 지목하는 스텝 (ETCH9_B 가 여기 있다)
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

DATA_DIR = Path(__file__).resolve().parent
DB_PATH = DATA_DIR / "yield.db"
EMB_DIR = DATA_DIR / "embeddings"


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-12)


def _make_member(center: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """그룹 중심 근처의 멤버 벡터. noise 를 1/sqrt(DIM) 로 스케일해
    512차원에서도 노름이 GROUP_NOISE 수준에 머물도록 한다."""
    noise = (GROUP_NOISE / np.sqrt(DIM)) * rng.standard_normal(DIM)
    return _unit(center + noise)


def generate():
    rng = np.random.default_rng(SEED)

    rows = []          # yield 테이블 행 (dict)
    vectors = []       # 임베딩 벡터 (np.ndarray)
    wafer_ids = []     # vectors 와 같은 순서의 wafer_id

    # ---------------- 정상 wafer: 무작위 임베딩, 높은 수율, defect 없음
    for i in range(N_NORMAL):
        wid = f"W2401_{i:03d}"
        lot = NORMAL_LOTS[i % len(NORMAL_LOTS)]
        rows.append({
            "wafer_id": wid,
            "lot_id": lot,
            "yield": round(float(rng.uniform(93.0, 99.0)), 1),
            "_truth_defect": "none",
            "_truth_step": "Normal",
            "date": PAST_DATES[i % len(PAST_DATES)],
        })
        vectors.append(_unit(rng.standard_normal(DIM)))
        wafer_ids.append(wid)

    # ---------------- 그룹 대조 시나리오: 불량 그룹 3장 + 대조 그룹 3장 (RECENT_LOT)
    centers = {g["defect"]: _unit(rng.standard_normal(DIM)) for g in PATTERN_GROUPS}

    for wid in GROUP_WAFERS:
        rows.append({
            "wafer_id": wid,
            "lot_id": RECENT_LOT,
            "yield": round(float(rng.uniform(76.0, 82.0)), 1),
            "_truth_defect": FEATURED_DEFECT,
            "_truth_step": FEATURED_PROCESS,
            "date": RECENT_DATE,
        })
        vectors.append(_make_member(centers[FEATURED_DEFECT], rng))
        wafer_ids.append(wid)

    for wid in CONTROL_WAFERS:
        rows.append({
            "wafer_id": wid,
            "lot_id": RECENT_LOT,
            "yield": round(float(rng.uniform(93.0, 97.0)), 1),
            "_truth_defect": "none",
            "_truth_step": "Normal",
            "date": RECENT_DATE,
        })
        vectors.append(_unit(rng.standard_normal(DIM)))
        wafer_ids.append(wid)

    # ---------------- 패턴 그룹 (과거 유사 사례): 그룹 중심 + noise, 같은 defect 공유
    for g_idx, grp in enumerate(PATTERN_GROUPS):
        center = centers[grp["defect"]]
        tag = grp["defect"][:3]                   # wafer_id 가독성용 접두
        for p in range(grp["n_past"]):
            past_wid = f"W24{g_idx}{p}_{tag}{p + 1}"
            rows.append({
                "wafer_id": past_wid,
                "lot_id": NORMAL_LOTS[(g_idx + p) % len(NORMAL_LOTS)],
                "yield": round(float(rng.uniform(85.0, 92.0)), 1),
                "_truth_defect": grp["defect"],
                "_truth_step": grp["process"],
                "date": PAST_DATES[p % len(PAST_DATES)],
            })
            vectors.append(_make_member(center, rng))
            wafer_ids.append(past_wid)

    # ---------------- 구멍 케이스 (기존 난수열 보존을 위해 끝에 추가)
    rows.append({
        "wafer_id": UNLABELED_LOW_WAFER,
        "lot_id": RECENT_LOT,
        "yield": UNLABELED_LOW_YIELD,
        "_truth_defect": "none",
        "_truth_step": "Normal",
        "date": RECENT_DATE,
    })
    vectors.append(_unit(rng.standard_normal(DIM)))
    wafer_ids.append(UNLABELED_LOW_WAFER)

    for wid, y in UNGROUPED_WAFERS:
        rows.append({
            "wafer_id": wid,
            "lot_id": UNGROUPED_LOT,
            "yield": y,
            "_truth_defect": "none",
            "_truth_step": "Normal",
            "date": RECENT_DATE,
        })
        vectors.append(_unit(rng.standard_normal(DIM)))
        wafer_ids.append(wid)

    # ---------------- 적대적 케이스 (신규 lot — 기존 난수열 보존을 위해 끝에 추가)
    # 케이스 4 는 E2E 로도 확인해야 하므로(형제 묶기 → 대조군 선정 → no_signal) 타깃을
    # 임베딩 공간에서 묶어 둔다. 나머지 케이스는 find_commonality 를 직접 부르므로 무작위.
    adv_center = _unit(rng.standard_normal(DIM))
    for lot in ADV_CASES:
        adv_targets, adv_controls = adv_group(lot)
        for wid in adv_targets + adv_controls:
            is_target = wid in adv_targets
            rows.append({
                "wafer_id": wid,
                "lot_id": lot,
                "yield": ADV_TARGET_YIELD if is_target else ADV_CONTROL_YIELD,
                "_truth_defect": "none",      # 라벨 없음 — 실데이터와 같은 조건
                "_truth_step": "Normal",   # 심어둔 이상 없음
                "date": RECENT_DATE,
            })
            vectors.append(_make_member(adv_center, rng)
                           if is_target and lot == ADV_NOSIGNAL_LOT
                           else _unit(rng.standard_normal(DIM)))
            wafer_ids.append(wid)

    # ---------------- 분할 lot (root_lot 하나에 lot 여럿) — 기존 난수열 뒤에 붙인다
    for lot, (nos, lot_type) in SPLIT_LOTS.items():
        for no in nos:
            wid = f"{SPLIT_ROOT_LOT}_{no:02d}"
            rows.append({
                "wafer_id": wid,
                "lot_id": lot,
                "yield": ADV_TARGET_YIELD if wid in SPLIT_TARGETS else ADV_CONTROL_YIELD,
                "_truth_defect": "none",       # 라벨 없음 — 실데이터와 같은 조건
                "_truth_step": "Normal",    # 심어둔 이상 없음
                "date": RECENT_DATE,
                "root_lot_id": SPLIT_ROOT_LOT,   # lot_id 와 다르다 (_augment_yield 가 보존)
                "lot_type": lot_type,
            })
            vectors.append(_unit(rng.standard_normal(DIM)))
            wafer_ids.append(wid)

    # ---------------- 비정규 스텝 lot — 기존 난수열 뒤에 붙인다
    for wid in IRREG_TARGETS + IRREG_CONTROLS:
        rows.append({
            "wafer_id": wid,
            "lot_id": f"{IRREG_ROOT_LOT}.1",
            "yield": ADV_TARGET_YIELD if wid in IRREG_TARGETS else ADV_CONTROL_YIELD,
            "_truth_defect": "none",       # 라벨 없음 — 실데이터와 같은 조건
            "_truth_step": IRREG_STEP,     # 심어둔 정답: 비정규 스텝 통과
            "date": RECENT_DATE,
            "root_lot_id": IRREG_ROOT_LOT,
        })
        vectors.append(_unit(rng.standard_normal(DIM)))
        wafer_ids.append(wid)

    # ---------------- metro 계측 lot (root_lot 둘) — 기존 난수열 뒤에 붙인다
    for wid in METRO_TARGETS + METRO_CONTROLS:
        rows.append({
            "wafer_id": wid,
            "lot_id": f"{wid[:5]}.1",
            "yield": ADV_TARGET_YIELD if wid in METRO_TARGETS else ADV_CONTROL_YIELD,
            "_truth_defect": "none",        # 라벨 없음 — 실데이터와 같은 조건
            "_truth_step": METRO_TRUE_GE[0],   # 심어둔 정답: 계측 스텝의 두께
            "date": RECENT_DATE,
            "root_lot_id": wid[:5],
        })
        vectors.append(_unit(rng.standard_normal(DIM)))
        wafer_ids.append(wid)

    _augment_yield(rows)
    steps = (_make_step_history(rows) + _make_adversarial_steps()
             + _make_split_lot_steps() + _make_irregular_step_steps()
             + _make_metro_steps())
    sensors = _make_sensor_log(rows)
    _write_sqlite(rows, steps, sensors, _make_metro())
    _write_index(vectors, wafer_ids)
    _report(rows, vectors, wafer_ids)


def _augment_yield(rows):
    """commonality 가 요구하는 root_lot_id·lot_type 을 채운다 (rng 미사용).

    **이미 값이 있으면 보존한다** — 분할 lot 케이스는 root_lot_id != lot_id 이고
    lot_type 도 lot 마다 다르다.
    """
    for r in rows:
        r.setdefault("root_lot_id", r["lot_id"])   # 더미 기본: lot_id = root_lot
        r.setdefault("lot_type", "prod")           # 더미 기본: 전부 양산
    return rows


# step_history 용 설비/챔버/PPID.
SH_REAL_EQP, SH_REAL_CH, SH_REAL_PPID = "ETCH9", "B", "PPID_X"    # 불량군 전용
SH_CTRL_EQP, SH_CTRL_PPID = "ETCH9", "PPID_Y"                     # 대조군: 같은 설비 다른 챔버/PPID
# 경로(SH_STEPS)는 SENSOR_STEP 이 참조하므로 파일 위쪽에 있다.


def _make_step_history(rows):
    """wafer×스텝 이력. RECENT_LOT 타깃은 Etch 에서 ETCH9_B·PPID_X 를 공유하고
    대조군은 ETCH9_<번호>·PPID_Y 로 갈린다. 나머지 스텝은 양쪽 공통(미끼)."""
    sh_rng = np.random.default_rng(SEED + 1)
    steps = []
    for r in rows:
        wid = r["wafer_id"]
        if (wid in ADV_WAFERS or wid in SPLIT_WAFERS or wid in IRREG_WAFERS
                or wid in METRO_WAFERS):                          # 전용 생성기
            continue
        for seq, area in SH_STEPS:
            eqp, ch, ppid = f"{area.upper()[:4]}1", "A", "PPID_Z"   # 기본: 공통 경로
            if area == "Etch":
                if wid in GROUP_WAFERS:
                    eqp, ch, ppid = SH_REAL_EQP, SH_REAL_CH, SH_REAL_PPID
                elif wid in CONTROL_WAFERS:
                    eqp, ch, ppid = SH_CTRL_EQP, str(int(sh_rng.integers(1, 9))), SH_CTRL_PPID
                else:
                    eqp, ch, ppid = f"ETCH{int(sh_rng.integers(1, 9))}", "A", "PPID_Z"
            steps.append({
                "wafer_id": wid, "step_seq": seq, "area": area,
                "eqp_id": eqp, "ch_id": ch, "ppid": ppid,
                "timestamp": r["date"] + " 10:00:00",
            })
    return steps


def _make_adversarial_steps():
    """적대적 lot 의 wafer×스텝 이력 (rng 미사용 — 케이스가 난수에 흔들리면 안 된다).

    기본 경로는 타깃·대조군 공통이라 분리 신호가 되지 않는다. 케이스마다 Etch(케이스 2 만
    Photo 도)의 챔버 배정만 달리해서 원하는 실패 모드를 만든다. 설비 레벨은 양쪽이 같은
    설비를 쓰게 두어 롤업 점수가 0 으로 눌리는 것까지 함께 시험한다.
    """
    steps = []
    for lot in ADV_CASES:
        targets, controls = adv_group(lot)
        for wid in targets + controls:
            if wid == ADV_MISSING_WAFER:
                continue                          # 케이스 3: 이력 자체가 없는 타깃
            for seq, area in SH_STEPS:
                eqp, ch, ppid = f"{area.upper()[:4]}1", "A", "PPID_Z"

                if lot == ADV_COUNTEREX_LOT and area == "Etch":
                    # 케이스 1: 대조군 1장이 진짜 원인 챔버를 거쳤는데 정상 (반례)
                    eqp = "ETCH1"
                    ch = "B" if (wid in targets or wid == controls[0]) else "C"
                elif lot == ADV_DECOY_LOT and area == "Etch":
                    eqp, ch = "ETCH2", ("B" if wid in targets else "C")
                elif lot == ADV_DECOY_LOT and area == "Photo":
                    # 케이스 2: 진짜(1.0) 옆의 근접 미끼 — 타깃 4장 중 3장만 거친다
                    eqp, ch = "PHOT2", ("X" if wid in targets[:3] else "A")
                elif lot == ADV_MISSING_LOT and area == "Etch":
                    eqp = "ETCH3"
                    if wid in targets:
                        ch = "B"
                    elif wid in ADV_NULL_CH_WAFERS:
                        ch = None                 # 케이스 3: 챔버 레벨이 조용히 빠져야 한다
                    else:
                        ch = "C"
                elif lot == ADV_NOSIGNAL_LOT and area == "Etch":
                    # 케이스 4: 원인이 root_lot 전원에 걸려 타깃·대조군이 같은 경로
                    eqp, ch = "ETCH4", "A"

                steps.append({
                    "wafer_id": wid, "step_seq": seq, "area": area,
                    "eqp_id": eqp, "ch_id": ch, "ppid": ppid,
                    "timestamp": RECENT_DATE + " 10:00:00",
                })
    return steps


def _make_split_lot_steps():
    """분할 lot 의 wafer×스텝 이력 (rng 미사용). 타깃만 ETCH5_B, 비타깃은 ETCH5_C.

    설비(ETCH5)는 양쪽이 같아 롤업 점수가 0 으로 눌리고, 챔버에서만 갈린다.
    """
    steps = []
    for wid in SPLIT_TARGETS + SPLIT_CONTROLS:
        for seq, area in SH_STEPS:
            eqp, ch, ppid = f"{area.upper()[:4]}1", "A", "PPID_Z"
            if area == "Etch":
                eqp, ch = "ETCH5", ("B" if wid in SPLIT_TARGETS else "C")
            steps.append({
                "wafer_id": wid, "step_seq": seq, "area": area,
                "eqp_id": eqp, "ch_id": ch, "ppid": ppid,
                "timestamp": RECENT_DATE + " 10:00:00",
            })
    return steps


def _make_irregular_step_steps():
    """비정규 스텝 lot 의 wafer×스텝 이력 (rng 미사용).

    정상 4스텝은 타깃·대조군이 **완전히 같게** 돈다(그래서 정상 스텝은 분리 점수 0).
    타깃 4장만 추가로 IRREG_STEP 을 거치는데, **설비도 PPID 도 wafer 마다 다르다** —
    설비/PPID 축에서는 후보가 1/4 씩 쪼개져 판별선(0.5)을 못 넘고, 통과 여부 축에서만
    1.0 으로 갈린다. 이 대비가 이 케이스의 전부다.
    """
    steps = []
    for wid in IRREG_TARGETS + IRREG_CONTROLS:
        for seq, area in SH_STEPS:
            steps.append({
                "wafer_id": wid, "step_seq": seq, "area": area,
                "eqp_id": f"{area.upper()[:4]}1", "ch_id": "A", "ppid": "PPID_Z",
                "timestamp": RECENT_DATE + " 10:00:00",
            })
    for i, wid in enumerate(IRREG_TARGETS, start=1):
        steps.append({
            "wafer_id": wid, "step_seq": IRREG_STEP, "area": "Etch",
            "eqp_id": f"ETCH{i}", "ch_id": "A", "ppid": f"PPID_E{i}",
            "timestamp": RECENT_DATE + " 11:00:00",
        })
    return steps


def _make_metro_steps():
    """metro lot 의 wafer×스텝 이력 (rng 미사용).

    처리 스텝도 계측 스텝도 **타깃·대조군이 완전히 같게** 돈다 — 설비/챔버/PPID 축에서
    분리가 0 이어야 metro 축이 잡는 신호가 다른 축의 부산물이 아님이 분명해진다.
    계측 스텝을 이력에도 싣는 것은 실데이터가 그렇기 때문이다(계측도 스텝이다).
    """
    steps = []
    for wid in METRO_TARGETS + METRO_CONTROLS:
        for seq, area in SH_STEPS:
            steps.append({
                "wafer_id": wid, "step_seq": seq, "area": area,
                "eqp_id": f"{area.upper()[:4]}1", "ch_id": "A", "ppid": "PPID_Z",
                "timestamp": RECENT_DATE + " 10:00:00",
            })
        for i, seq in enumerate(METRO_STEPS, start=1):
            steps.append({
                "wafer_id": wid, "step_seq": seq, "area": "Metrology",
                "eqp_id": f"MEAS{i}", "ch_id": "A", "ppid": "PPID_M",
                "timestamp": RECENT_DATE + " 10:30:00",
            })
    return steps


def _by_rank(order, top, step):
    """값 내림차순 자리 목록 -> {wafer_id: 값}. 1등이 `top`, 한 칸마다 `step` 씩 낮다.

    분할점 탐색은 **순서**만 보므로 값 자체가 아니라 자리로 케이스를 적는 편이
    읽기도 쉽고 심어둔 분할점을 정확히 지목할 수 있다.
    """
    return {wid: round(top - step * i, 3) for i, wid in enumerate(order)}


def _metro_avg_maps():
    """조합 -> {wafer_id: AVG 값}. 조합마다 역할이 하나씩이다 (상수 블록 참조).

    난수를 쓰지 않는다. 심어둔 분할점을 테스트가 잠그려면 값이 고정이어야 한다.
    """
    t1, t2, t3, t4, t5 = METRO_TARGETS                 # T2421_01~04, T2422_01
    c = METRO_CONTROLS                                 # T2421_05~07, T2422_02~10

    # (1) 진짜 ge 신호. 대조군 1장(c[0])을 타깃 사이에 끼워 **완전 분리를 막는다** —
    #     완전 분리면 어느 분할점을 골라도 1.0 이라 "정확히 129.0" 을 못 잠근다.
    #     최적은 "129.0 이상" 에서 타깃 5/5 · 대조군 1/12 = 0.917.
    #     간격(0.4)은 임의가 아니다 — 최하위 타깃이 정확히 METRO_TRUTH_GE_SPLIT 에
    #     떨어지고 대조군 사다리(128.5 시작)와 값이 겹치지 않아야 한다. 겹치면 동점이
    #     되어 그 자리에 분할점을 못 놓고 심어둔 정답이 한 칸 밀린다.
    true_ge = _by_rank([t1, t2, c[0], t3, t4, t5], 131.0, 0.4)
    true_ge.update(_by_rank(c[1:], 128.5, 0.3))
    assert true_ge[t5] == METRO_TRUTH_GE_SPLIT, "심어둔 ge 분할점이 사다리와 어긋났다"

    # (2) 무신호. 타깃을 **맨 아래까지** 흩어 놓는다 — 타깃 전원을 잡으려면 대조군도
    #     전원 잡아야 해서 어느 분할점도 점수가 안 나온다. 타깃을 위쪽에만 흩으면
    #     "전원 포함" 컷이 1.0 - 5/12 = 0.583 을 내서 무신호가 되지 않는다.
    noise_order = [c[0], c[1], t1, c[2], c[3], c[4], t2, c[5], c[6], t3,
                   c[7], c[8], t4, c[9], c[10], c[11], t5]
    noise = _by_rank(noise_order, 60.0, 0.5)

    # (3) 얇은 쪽 신호. "127.0 이하" 에서 타깃 5/5 · 대조군 1/12 = 0.917.
    #     양방향을 안 돌리면 이 조합을 통째로 놓친다.
    true_le = _by_rank(c[1:], 130.5, 0.3)
    true_le.update({t5: METRO_TRUTH_LE_SPLIT, c[0]: 126.2, t4: 126.5,
                    t3: 126.0, t2: 125.5, t1: 125.0})
    assert min(true_le[w] for w in c[1:]) > METRO_TRUTH_LE_SPLIT, \
        "le 사다리의 대조군이 분할점 아래로 내려왔다"

    # (4) 동점 뭉침. 값이 3종류뿐이라 분할점은 45/46, 46/47 사이에만 놓일 수 있다.
    tied = {}
    for wid in (t1, t2, t3, c[0], c[1], c[2]):
        tied[wid] = 45.0
    for wid in (t4, t5, c[3], c[4], c[5], c[6]):
        tied[wid] = 46.0
    for wid in c[7:]:
        tied[wid] = 47.0

    # (5) lot 효과만. T2421 전원이 두껍고 T2422 전원이 얇다 — 불량과는 무관하다.
    #     층화 섞기는 lot 안에서만 섞으므로 a·c 가 안 변해 p = 1.0 (올바른 기각).
    #     전체 섞기로 바꾸면 거짓 양성이 나는 것이 이 조합의 존재 이유다 (설계 §2-2).
    lot_effect = {}
    for i, wid in enumerate(w for w in METRO_TARGETS + METRO_CONTROLS
                            if w.startswith(METRO_ROOT_LOTS[0])):
        lot_effect[wid] = round(135.0 + 0.1 * i, 3)
    for i, wid in enumerate(w for w in METRO_TARGETS + METRO_CONTROLS
                            if w.startswith(METRO_ROOT_LOTS[1])):
        lot_effect[wid] = round(120.0 + 0.1 * i, 3)

    # (6) 일부만 계측. 미계측 대조군 6장을 '미통과' 로 세면 분모가 6 이 아니라 12 가
    #     되어 점수가 0.33 -> 0.67 로 뛴다 (1단계가 고친 분모 conflation 의 재현).
    measured = [w for w in METRO_TARGETS + METRO_CONTROLS
                if w not in METRO_UNMEASURED]
    partial_order = []
    m_t = [w for w in measured if w in METRO_TARGETS]
    m_c = [w for w in measured if w not in METRO_TARGETS]
    for i in range(max(len(m_t), len(m_c))):          # 타깃과 대조군을 번갈아 = 무신호
        if i < len(m_t):
            partial_order.append(m_t[i])
        if i < len(m_c):
            partial_order.append(m_c[i])
    partial = _by_rank(partial_order, 55.0, 0.5)

    return {METRO_TRUE_GE: true_ge, METRO_NOISE: noise, METRO_TRUE_LE: true_le,
            METRO_TIED: tied, METRO_LOT_EFFECT: lot_effect, METRO_PARTIAL: partial}


def _make_metro():
    """wafer×metro스텝×item×subitem 계측 행 (rng 미사용).

    한 (wafer, 스텝, item) 에 subitem 이 여럿 달린다 — 통계값 5종과 측정 포인트 5개다.
    **포인트는 AVG 주변에 놓아 서로 상관시킨다.** 상관이 없으면 subitem 거르기를 꺼도
    top_k 가 안 잠식돼 §9 의 변별력 테스트가 통과해 버린다.
    """
    out = []
    for (step, item), avg_map in _metro_avg_maps().items():
        for wid, avg in avg_map.items():
            vals = {"AVG": avg, "MAX": avg + 1.0, "MIN": avg - 1.0,
                    "STD": 0.5, "RANGE": 2.0}
            for j, off in enumerate(METRO_POINT_OFFSETS, start=1):
                vals[f"P{j:02d}"] = round(avg + off, 3)
            for sub, v in vals.items():
                out.append({
                    "wafer_id": wid, "step_seq": step, "item": item,
                    "subitem_id": sub, "value": round(float(v), 3),
                    "tkin_time": RECENT_DATE + " 10:25:00",
                    "tkout_time": RECENT_DATE + " 10:30:00",
                })
    return out


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
                # spread 는 임의가 아니다: 2단이 매기는 효과크기 = 심은 이동폭 / spread 라
                # 이 값이 곧 센서 순위를 정한다. std 계열의 spread 를 avg 보다 작게 잡으면
                # '분산만 이동'(케이스 1)이 진짜 원인을 앞질러 1등이 되어 버린다.
                # 현재 값 기준 효과크기: 진짜 8.0 > 분산만 5.0 > 공선성 4.0 > 미끼 2.0.
                base, spread = 100.0, 1.5
                if stat == "std":
                    base, spread = 5.0, 1.2

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
                    "step_seq": SENSOR_STEP,
                    "sensor_name": f"{name}_{stat}",
                    "value": round(float(sen_rng.normal(base, spread)), 3),
                    "tkout_time": r["date"] + " 10:00:00",
                })
    return out


def _write_sqlite(rows, steps, sensors, metro):
    # 정답지는 DB 에 안 들어간다. rows 의 `_truth_*` 는 **생성기 내부 정답지**로,
    # 어디에 이상을 심을지 정하는 데만 쓰고 yield 에는 아래 INSERT 의 리터럴 NULL 이
    # 들어간다 (A-2·A-3: 실데이터에 이 두 값은 없다). 키 이름을 DB 컬럼과 다르게 둔 것도
    # 행을 읽는 사람의 오해와, 여기서 실수로 쓰는 경로를 아예 없애기 위해서다.
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE yield (
            wafer_id     TEXT PRIMARY KEY,
            lot_id       TEXT NOT NULL,
            yield        REAL NOT NULL,
            defect_type  TEXT,
            step_seq     TEXT,
            date         TEXT NOT NULL,
            root_lot_id  TEXT NOT NULL,
            lot_type     TEXT NOT NULL
        )
    """)
    conn.executemany(
        "INSERT INTO yield VALUES (:wafer_id, :lot_id, :yield, NULL, NULL, "
        ":date, :root_lot_id, :lot_type)", rows)
    conn.execute("""
        CREATE TABLE step_history (
            wafer_id     TEXT NOT NULL,
            step_seq     TEXT NOT NULL,
            area         TEXT,
            eqp_id       TEXT NOT NULL,
            ch_id        TEXT,
            ppid         TEXT,
            timestamp    TEXT
        )
    """)
    conn.executemany(
        """INSERT INTO step_history VALUES
           (:wafer_id, :step_seq, :area, :eqp_id, :ch_id, :ppid, :timestamp)""", steps)
    conn.execute("""
        CREATE TABLE sensor_log (
            wafer_id     TEXT NOT NULL,
            step_seq     TEXT NOT NULL,
            sensor_name  TEXT NOT NULL,
            value        REAL NOT NULL,
            tkout_time   TEXT
        )
    """)
    conn.execute("CREATE INDEX idx_sensor_step ON sensor_log(step_seq, wafer_id)")
    conn.executemany(
        """INSERT INTO sensor_log VALUES
           (:wafer_id, :step_seq, :sensor_name, :value, :tkout_time)""", sensors)
    # metro = 계측값. sensor_log(FDC 센서)와 다른 테이블이다 — 센서는 처리 중 장비
    # 신호이고 metro 는 처리 결과를 잰 값이라, 축도 분석 도구도 다르다.
    # `subitem_id` 에는 개별 측정 포인트와 그 통계값(AVG 등)이 섞여 있다.
    # tkout_time 은 회차 정렬 기준이다 — metro 에 재작업은 없으므로(2026-08-12 확인)
    # (wafer_id, step_seq, item, subitem_id) 가 유일하고, 그것을 아래 UNIQUE 로 잠근다.
    conn.execute("""
        CREATE TABLE metro (
            wafer_id     TEXT NOT NULL,
            step_seq     TEXT NOT NULL,
            item         TEXT NOT NULL,
            subitem_id   TEXT NOT NULL,
            value        REAL,
            tkin_time    TEXT,
            tkout_time   TEXT,
            UNIQUE (wafer_id, step_seq, item, subitem_id)
        )
    """)
    conn.execute("CREATE INDEX idx_metro_step ON metro(step_seq, item, wafer_id)")
    conn.executemany(
        """INSERT INTO metro VALUES
           (:wafer_id, :step_seq, :item, :subitem_id, :value,
            :tkin_time, :tkout_time)""", metro)
    conn.commit()
    conn.close()


def _write_index(vectors, wafer_ids):
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    data = np.vstack(vectors).astype(np.float32)
    n = data.shape[0]

    index = hnswlib.Index(space="cosine", dim=DIM)
    index.init_index(max_elements=n, ef_construction=200, M=16)
    index.add_items(data, np.arange(n))  # 내부 label = vectors 인덱스
    index.set_ef(50)
    index.save_index(str(EMB_DIR / "index.bin"))

    # label(int) -> wafer_id 매핑 + 메타
    (EMB_DIR / "labels.json").write_text(
        json.dumps({"dim": DIM, "wafer_ids": wafer_ids}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _report(rows, vectors, wafer_ids):
    # DB·임베딩을 다 쓴 **뒤** 라서, print 가 콘솔 인코딩에 걸려 죽으면 산출물은 남고
    # 리포트만 사라진다. 출력은 전부 `say` 로 한다 (ya_console.py 참조).
    say(f"총 wafer: {len(rows)}  (정상 {N_NORMAL} + 패턴 {len(rows) - N_NORMAL})")
    say(f"임베딩: {len(vectors)} x {DIM}d  -> {EMB_DIR / 'index.bin'}")
    say(f"SQLite: {DB_PATH}")
    say("\n[lot 평균 수율 낮은 순 상위 3]")
    by_lot = {}
    for r in rows:
        by_lot.setdefault(r["lot_id"], []).append(r["yield"])
    avg = sorted(((sum(v) / len(v), lot, len(v)) for lot, v in by_lot.items()))
    for a, lot, c in avg[:3]:
        say(f"  {lot}: 평균 {a:.1f}  (wafer {c}장)")
    say(f"\n[{RECENT_LOT} 그룹 대조 시나리오]")
    for r in rows:
        if r["lot_id"] == RECENT_LOT:
            say(f"  {r['wafer_id']}  yield={r['yield']}  "
                f"defect={r['_truth_defect']} (정답지 - DB 에는 NULL)")


if __name__ == "__main__":
    generate()
