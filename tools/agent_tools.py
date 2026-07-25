"""분석 루프용 tool-calling 래퍼.

LLM 이 읽는 것은 함수의 이름·docstring·인자 스키마다 — 여기 docstring 이
곧 LLM 의 tool 선택 판단 재료이므로 '언제 쓰는지'를 명확히 적는다.

finalize 는 실행되는 tool 이 아니라 "분석 종료 제안" 신호다.
graph/nodes.py 의 tools 노드(게이트)가 confidence 를 검사해 승인/반려하므로
TOOLS_BY_NAME 에는 넣지 않는다.
"""

from langchain_core.tools import tool

import config
from domain import registry
from tools import yield_tools as yt
from tools.eds_search import get_searcher

_searcher = None  # hnswlib 인덱스 로드는 무거우므로 최초 사용 시 1회만


def _searcher_lazy():
    global _searcher
    if _searcher is None:
        _searcher = get_searcher()
    return _searcher


@tool
def get_wafer(wafer_id: str, reason: str = "") -> dict | None:
    """wafer 1장의 수율·defect_type·공정·날짜를 조회한다.
    대상 wafer 의 기본 정보가 필요할 때 사용.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.get_wafer(wafer_id)


@tool
def search_similar(wafer_id: str, k: int = 5, reason: str = "") -> list[dict]:
    """불량 맵 패턴이 유사한 과거 wafer 를 찾는다.
    과거 사례와 비교해 원인 단서를 얻으려면 가장 먼저 사용.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return _searcher_lazy().search(wafer_id, k=k)


@tool
def aggregate_defects(wafer_ids: list[str], reason: str = "") -> list[dict]:
    """여러 wafer 의 defect_type 분포를 집계한다.
    유사 wafer 들이 같은 불량 유형을 공유하는지 확인할 때 사용.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.aggregate_defects(wafer_ids)


@tool
def get_process_log(wafer_id: str, reason: str = "") -> list[dict]:
    """wafer 의 공정 단계별 장비·파라미터 로그를 조회한다.
    in_spec=False 인 행이 스펙 이탈. 원인을 특정 공정/장비까지 좁히려면 반드시 확인.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.get_process_log(wafer_id)


@tool
def validate_data_completeness(wafer_ids: list[str], reason: str = "") -> dict:
    """분석 대상 wafer 들의 수율 행 누락·공정 로그 단계 누락·중복 로그를 검사한다.
    그룹 대조(hyp_*) 전에 호출해 데이터가 결론에 쓸 만큼 완전한지 확인.
    status=blocked 면 비교 결과를 신뢰하지 말고 리포트에 품질 경고를 남겨야 한다.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.validate_data_completeness(wafer_ids)


@tool
def find_counterexamples(equipment_id: str, process_step: str,
                         defect_type: str, reason: str = "") -> dict:
    """가설 '(공정, 장비)가 defect 의 원인'에 반하는 사례를 전수 데이터에서 찾는다:
    해당 장비를 거쳤지만 정상인 wafer, 장비 없이 같은 defect 가 난 wafer.
    finalize 전에 호출해 가설의 특이성(반례 유무)을 확인하고 리포트에 인용.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.find_counterexamples(equipment_id, process_step, defect_type)


@tool
def finalize(hypothesis: str, confidence: float) -> str:
    """원인을 특정 공정/장비까지 좁혔고 근거가 충분하다고 판단될 때만 호출해
    분석 종료를 제안한다. hypothesis=원인 가설(공정·장비·파라미터 명시),
    confidence=0~1 확신도. 확신도가 낮으면 반려되고 추가 분석을 지시받는다."""
    return "finalize 는 게이트가 처리한다"  # 직접 실행되지 않음


_HYPOTHESIS_TOOLS = registry.build_tools(registry.load_hypotheses())

# 옛 process_log 스키마에 묶인 도구들 — 실데이터(step_history)에서는 못 돈다.
# 삭제(Stage 5)까지는 노출만 막는다. aggregate_defects 는 yield.defect_type 에
# 묶여 있어 실데이터에서 의미가 약하지만, 그 처리는 Stage 4 소관이라 여기 두지 않는다.
_LEGACY_TOOLS = [get_process_log, validate_data_completeness, find_counterexamples]
_BASE_TOOLS = [get_wafer, search_similar, aggregate_defects]

ANALYSIS_TOOLS = [
    *_BASE_TOOLS,
    *(_LEGACY_TOOLS if config.LEGACY_TOOLS_ENABLED else []),
    *_HYPOTHESIS_TOOLS,
]
ALL_TOOLS = ANALYSIS_TOOLS + [finalize]
TOOLS_BY_NAME = {t.name: t for t in ANALYSIS_TOOLS}