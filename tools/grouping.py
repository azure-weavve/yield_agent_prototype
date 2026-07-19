"""대상 정규화 계층 (결정론 — LLM 불개입).

status 입력 재설계(2026-07-18 문서 3절)의 두 입력 형태를 한 형태로 맞춘다:
  - 한 장 입력 → EDS 형제 묶기 (컷오프 config.SIBLING_MIN_SIMILARITY 고정, 전 lot 탐색)
  - 그룹 입력 → 그대로 target_group
대조군은 형제 각자의 lot 내 합집합(1단계). 부족하면 확장하지 않고 정직 보고한다.
defect 라벨은 판정 기준이 아니라 참고 정보다 (6절 3번 — 유사맵이 이긴다).
"""

import config
from tools import yield_tools as yt
from tools.eds_search import get_searcher

_searcher = None  # hnswlib 인덱스 로드는 무거우므로 최초 사용 시 1회만


def _searcher_lazy():
    global _searcher
    if _searcher is None:
        _searcher = get_searcher()
    return _searcher


def normalize_target(wafers: list[str]) -> dict:
    known = {r["wafer_id"] for r in yt.get_wafers(wafers)}
    unknown = [w for w in wafers if w not in known]
    mode = "single" if len(wafers) == 1 else "group"
    target, siblings, isolated = list(wafers), [], False

    if mode == "single" and not unknown:
        cands = _searcher_lazy().search(wafers[0], k=config.SIBLING_SEARCH_K)
        siblings = [c for c in cands if c["similarity"] >= config.SIBLING_MIN_SIMILARITY]
        target = wafers + [s["wafer_id"] for s in siblings]   # 입력 선두 + 유사도 내림차순
        isolated = not siblings

    return {
        "mode": mode,
        "target_group": target,
        "siblings": siblings,
        "unknown_wafers": unknown,
        "isolated": isolated,
        "label_counts": yt.aggregate_defects(target) if not unknown else [],
    }


def select_control(target_group: list[str]) -> dict:
    lots = sorted({r["lot_id"] for r in yt.get_wafers(target_group)})
    targets = set(target_group)
    sources = {}
    for lot in lots:
        cands = [w for w in yt.find_normal_wafers(lot) if w not in targets]
        if cands:
            sources[lot] = cands
    control = sorted({w for ws in sources.values() for w in ws})
    # 2단계(같은 root_lot 의 다른 양산랏 확장)는 lot_type 컬럼(ETL 이후) 전제 —
    # 규칙만 확정된 상태라 자리만 남긴다 (재설계 문서 7절).
    return {
        "control_group": control,
        "sources": sources,
        "stage": 1,
        "insufficient": len(control) < config.CONTROL_MIN_SIZE,
    }
