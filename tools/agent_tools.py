"""분석 루프용 tool-calling 래퍼.

LLM 이 읽는 것은 함수의 이름·docstring·인자 스키마다 — 여기 docstring 이
곧 LLM 의 tool 선택 판단 재료이므로 '언제 쓰는지'를 명확히 적는다.

finalize 는 실행되는 tool 이 아니라 "분석 종료 제안" 신호다.
graph/nodes.py 의 tools 노드(게이트)가 confidence 를 검사해 승인/반려하므로
TOOLS_BY_NAME 에는 넣지 않는다.
"""

from langchain_core.tools import tool

from domain import registry
from tools import sensor_compare as sc
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
    """wafer 1장의 수율·소속 lot·날짜를 조회한다 (defect_type·process_step 은 항상 NULL).
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
def compare_sensor_distribution(process_step: str, group_ids: list[str],
                                control_ids: list[str], reason: str = "") -> dict:
    """가설 도구(hyp_*)가 지목한 공정 스텝에서 두 그룹의 센서 통계값 분포를 비교한다.
    효과크기가 큰 센서 top-K 를 낸다 — 어느 챔버인지까지 좁힌 뒤 '왜' 를 보는 2단이다.
    후보는 결론이 아니다: 표본 수(n_target/n_control)를 함께 보고 판단하라.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return sc.compare_sensor_distribution(process_step, group_ids, control_ids)


@tool
def finalize(hypothesis: str, confidence: float) -> str:
    """원인을 특정 공정/장비까지 좁혔고 근거가 충분하다고 판단될 때만 호출해
    분석 종료를 제안한다. hypothesis=원인 가설(공정·장비·파라미터 명시),
    confidence=0~1 확신도. 확신도가 낮으면 반려되고 추가 분석을 지시받는다."""
    return "finalize 는 게이트가 처리한다"  # 직접 실행되지 않음


_HYPOTHESIS_TOOLS = registry.build_tools(registry.load_hypotheses())

_BASE_TOOLS = [get_wafer, search_similar, compare_sensor_distribution]

ANALYSIS_TOOLS = [*_BASE_TOOLS, *_HYPOTHESIS_TOOLS]
ALL_TOOLS = ANALYSIS_TOOLS + [finalize]
TOOLS_BY_NAME = {t.name: t for t in ANALYSIS_TOOLS}
