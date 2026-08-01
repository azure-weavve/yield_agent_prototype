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
from tools.eds_search import get_searcher    # 캐시는 그쪽 모듈에 하나만 있다


@tool
def get_wafer(wafer_id: str, reason: str = "") -> dict | None:
    """wafer 1장의 수율·소속 lot·날짜를 조회한다 (defect_type·step_seq 은 항상 NULL).
    대상 wafer 의 기본 정보가 필요할 때 사용.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.get_wafer(wafer_id)


@tool
def search_similar(wafer_id: str, k: int = 5, reason: str = "") -> list[dict]:
    """불량 맵 패턴이 유사한 과거 wafer 를 찾는다.
    과거 사례와 비교해 원인 단서를 얻으려면 가장 먼저 사용.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return get_searcher().search(wafer_id, k=k)


@tool
def compare_sensor_distribution(step_seq: str, group_ids: list[str],
                                control_ids: list[str], reason: str = "") -> dict:
    """가설 도구(hyp_*)가 지목한 공정 스텝에서 두 그룹의 센서 통계값 분포를 비교한다.
    효과크기가 큰 센서 top-K 를 낸다 — 어느 챔버인지까지 좁힌 뒤 '왜' 를 보는 2단이다.
    후보는 결론이 아니다: 표본 수(n_target/n_control)를 함께 보고 판단하라.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return sc.compare_sensor_distribution(step_seq, group_ids, control_ids)


@tool
def finalize(claim_id: str = "", hypothesis: str = "", confidence: float = 0.0) -> str:
    """원인을 특정 후보까지 좁혔고 근거가 충분하다고 판단될 때만 호출해 분석 종료를 제안한다.

    claim_id: 가설 도구(hyp_*) 결과의 후보에 실려 온 claim_id 를 **그대로** 옮긴다.
      이것이 승인 판정의 유일한 근거다. 지어내면 반려된다. 지목할 근거가 없어
      물러설 때는 빈 문자열로 둔다.
    hypothesis: 현장 엔지니어가 읽을 원인 서술. 판정에는 쓰이지 않는다.
    confidence: 0~1 확신도. 확신도만 높고 claim_id 가 없으면 반려된다."""
    return "finalize 는 게이트가 처리한다"  # 직접 실행되지 않음


_HYPOTHESIS_TOOLS = registry.build_tools(registry.load_hypotheses())

_BASE_TOOLS = [get_wafer, search_similar, compare_sensor_distribution]

ANALYSIS_TOOLS = [*_BASE_TOOLS, *_HYPOTHESIS_TOOLS]
ALL_TOOLS = ANALYSIS_TOOLS + [finalize]
TOOLS_BY_NAME = {t.name: t for t in ANALYSIS_TOOLS}
