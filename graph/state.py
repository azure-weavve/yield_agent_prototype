"""LangGraph 상태 정의 (누적형).

분석 루프는 "현재까지 결과를 보고" 다음 분석을 판단하므로,
messages/findings 는 덮어쓰기가 아니라 reducer 로 누적한다.
findings 는 감사(audit) 기록 — 매 tool 실행의 {loop, tool, args, result, thought}
가 쌓여 리포트의 분석 근거가 된다.
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    question: str                                   # 사용자 질문
    messages: Annotated[list, add_messages]         # LLM 대화 누적 (루프의 문맥)
    findings: Annotated[list[dict], operator.add]   # 감사 기록 누적 (분석 근거)
    target_group: list[str]                         # 현황파악이 묶은 불량 그룹 (유사 불량 wafer)
    control_group: list[str]                        # 같은 lot 의 정상 wafer (대조 그룹)
    status_summary: str                             # 현황파악 요약 (리포트 재료)
    loop_count: int                                 # 순환 횟수 (가드레일)
    finalize_accepted: bool                         # 게이트 승인 여부
    finalize_status: str                            # 종료 판정 구분: confirmed | inconclusive | no_anomaly | ungrouped
    final_hypothesis: str                           # 승인된 원인 가설
    final_confidence: float                         # 승인 시 확신도
    report: str                                     # 최종 리포트
