"""LangGraph 노드: 의도 파악 / 도구 실행(경로별) / 답변 생성.

- 의도 파악·답변 생성 = LLM (해석·표현)
- 도구 실행 = 결정론적 함수 (정확한 수치)
라우팅은 의도 파악 결과를 따라 build.py 의 conditional edge 가 경로별 도구 노드로 분기.
"""

from llm.client import get_llm
from tools import yield_tools as yt
from tools.eds_search import get_searcher

_llm = get_llm()
_searcher = None  # hnswlib 인덱스 로드는 무거우므로 최초 사용 시 1회만


def _searcher_lazy():
    global _searcher
    if _searcher is None:
        _searcher = get_searcher()
    return _searcher


# ---------------------------------------------------------------- 의도 파악 노드 (LLM)
def intent_node(state: dict) -> dict:
    return {"intent": _llm.classify_intent(state["question"])}


# ---------------------------------------------------------------- 도구 노드: 수율 조회 (시나리오 1)
def yield_tool_node(state: dict) -> dict:
    lots = yt.find_low_yield_lots()
    # 가장 수율 낮은 lot 의 worst wafer 를 다음 턴(시나리오 2)으로 넘긴다.
    wafer_id = lots[0]["worst_wafer"]["wafer_id"] if lots else state.get("last_wafer_id")
    return {
        "tool_result": {"kind": "low_yield_lots", "lots": lots},
        "last_wafer_id": wafer_id,
    }


# ---------------------------------------------------------------- 도구 노드: 유사 검색 (시나리오 2)
def similar_tool_node(state: dict) -> dict:
    wafer_id = state.get("last_wafer_id")
    if not wafer_id:
        return {"tool_result": {"kind": "no_target"}}

    results = _searcher_lazy().search(wafer_id, k=5)
    return {
        "tool_result": {"kind": "similar", "wafer_id": wafer_id, "results": results},
        "last_similar_wafers": [r["wafer_id"] for r in results],
    }


# ---------------------------------------------------------------- 답변 생성 노드 (LLM)
def answer_node(state: dict) -> dict:
    context = _serialize(state["tool_result"])
    return {"answer": _llm.generate_answer(state["question"], context)}


def _serialize(tool_result: dict) -> str:
    """도구 결과(구조화 dict) -> LLM 에 넘길 읽기 좋은 문자열."""
    kind = tool_result.get("kind")

    if kind == "low_yield_lots":
        lots = tool_result["lots"]
        if not lots:
            return "수율 임계 미만인 lot 은 없습니다."
        lines = ["수율 임계 미만 lot (낮은 순):"]
        for lot in lots:
            w = lot["worst_wafer"]
            lines.append(
                f"- {lot['lot_id']}: 평균 수율 {lot['avg_yield']} "
                f"({lot['wafer_count']}장), 최저 wafer {w['wafer_id']} "
                f"(수율 {w['yield']}, 불량 {w['defect_type']})"
            )
        return "\n".join(lines)

    if kind == "similar":
        results = tool_result["results"]
        if not results:
            return f"{tool_result['wafer_id']} 와 유사한 과거 사례를 찾지 못했습니다."
        lines = [f"{tool_result['wafer_id']} 와 유사한 과거 wafer (유사도 순):"]
        for r in results:
            lines.append(f"- {r['wafer_id']} (유사도 {r['similarity']})")
        return "\n".join(lines)

    if kind == "no_target":
        return "유사 검색의 기준이 될 wafer 가 없습니다. 먼저 대상 wafer 를 찾아야 합니다."

    return str(tool_result)
