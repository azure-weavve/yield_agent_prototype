"""LangGraph 상태 정의.

last_wafer_id 는 시나리오 1에서 검출한 wafer 를 시나리오 2("그 wafer")가
이어받기 위한 멀티턴 연결 고리다.
"""

from typing import Any, Optional, TypedDict


class AgentState(TypedDict, total=False):
    question: str               # 사용자 질문
    intent: str                 # 의도 파악 결과 (라우팅 레이블)
    tool_result: Any            # 도구 실행 결과 (구조화 dict)
    last_wafer_id: Optional[str]  # 턴 간 이어지는 대상 wafer (시나리오 1→2)
    last_similar_wafers: list[str]  # 직전 유사 검색 결과 (시나리오 2→3 확장용)
    answer: str                 # 최종 자연어 답변
