"""대상 정규화 계층 (결정론 — LLM 불개입).

status 입력 재설계(2026-07-18 문서 3절)의 두 입력 형태를 한 형태로 맞춘다:
  - 한 장 입력 → EDS 형제 묶기 (컷오프 config.SIBLING_MIN_SIMILARITY 고정, 전 lot 탐색)
  - 그룹 입력 → 그대로 target_group
대조군은 형제 각자의 lot 내 합집합(1단계). 부족하면 확장하지 않고 정직 보고한다.
라벨(defect_type)은 쓰지 않는다 — 실데이터에 없다. 묶는 것은 EDS 뿐이다.
"""

import config
from tools import yield_tools as yt
from tools.eds_search import get_searcher    # 캐시는 그쪽 모듈에 하나만 있다


def normalize_target(wafers: list[str]) -> dict:
    known = {r["wafer_id"] for r in yt.get_wafers(wafers)}
    unknown = [w for w in wafers if w not in known]
    mode = "single" if len(wafers) == 1 else "group"
    target, siblings, isolated = list(wafers), [], False

    unmatched = []
    eds_error = None
    if mode == "single" and not unknown:
        try:
            cands = get_searcher().search(wafers[0], k=config.SIBLING_SEARCH_K)
        except Exception as e:
            # yield DB 엔 있으나 EDS 인덱스엔 없는 wafer (local=KeyError, http=요청 예외).
            # 입력 실수가 아니라 인덱스↔DB 동기화 문제다 — 흐름 판단은 status_node 가 한다.
            cands, eds_error = [], f"{type(e).__name__}: {e}"
        raw = [c for c in cands if c["similarity"] >= config.SIBLING_MIN_SIMILARITY]
        # EDS 인덱스와 yield DB 는 별도 시스템이라 동기화가 어긋날 수 있다.
        # yield DB 에 실재하는 형제만 분석 대상에 넣고, 미확인분은 unmatched_siblings 로 분리한다
        # (없는 wafer 를 target 에 넣으면 뒤 tool 들이 조용히 빈 데이터를 반환해 오분석된다).
        confirmed = {r["wafer_id"] for r in yt.get_wafers([c["wafer_id"] for c in raw])}
        siblings = [c for c in raw if c["wafer_id"] in confirmed]
        unmatched = [c["wafer_id"] for c in raw if c["wafer_id"] not in confirmed]
        target = wafers + [s["wafer_id"] for s in siblings]   # 입력 선두 + 유사도 내림차순
        isolated = not siblings and eds_error is None         # 조회 실패는 '고립' 이 아니다

    return {
        "mode": mode,
        "target_group": target,
        "siblings": siblings,
        "unmatched_siblings": unmatched,
        "unknown_wafers": unknown,
        "isolated": isolated,
        "eds_error": eds_error,
    }


def _yield_summary(control_rows: list[dict]) -> dict | None:
    """대조군 수율 분포 — **판정이 아니라 해석 재료**다 (spec 2026-07-25 결정 2).

    라벨이 없어 저수율 피해 wafer 를 거를 수 없으므로, 걸러내는 대신 분포를 실어
    "이 반례가 진짜인가 피해 wafer 인가" 를 사람·LLM 이 판단할 재료로 넘긴다.
    """
    ys = sorted(r["yield"] for r in control_rows)
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

    control_rows = yt.get_wafers(control)
    sources: dict[str, list[str]] = {}
    for r in control_rows:
        sources.setdefault(r["root_lot_id"], []).append(r["wafer_id"])
    return {
        "control_group": control,
        "sources": {rl: sorted(ws) for rl, ws in sources.items()},
        "insufficient": len(control) < config.CONTROL_MIN_SIZE,
        "yield_summary": _yield_summary(control_rows),
    }
