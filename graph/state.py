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
    target_wafers: list[str]                        # 분석 대상 입력 (lot_wafer 결합 형태)
    target_source: str                              # 입력 출처: manual | auto
    messages: Annotated[list, add_messages]         # LLM 대화 누적 (루프의 문맥)
    findings: Annotated[list[dict], operator.add]   # 감사 기록 누적 (분석 근거)
    target_group: list[str]                         # 정규화 계층이 확정한 불량 그룹
    control_group: list[str]                        # 형제 lot 합집합 대조 그룹
    status_summary: str                             # 현황파악 요약 (리포트 재료)
    loop_count: int                                 # 순환 횟수 (가드레일)
    finalize_accepted: bool                         # 게이트 승인 여부
    finalize_status: str    # confirmed | no_signal | no_comparable_data | inconclusive | no_anomaly | unknown_target | isolated | control_insufficient | eds_lookup_failed | llm_call_failed
    final_hypothesis: str                           # 승인된 원인 가설 (LLM 서술)
    final_confidence: float                         # 승인 시 확신도
    # 승인된 근거 **목록** (게이트가 접고 줄 세운 것). 예전에는 dict 하나였고, 그래서
    # 축이 여럿일 때 LLM 이 고른 것 말고는 리포트에 도달하지 못했다. 각 항목은 대표
    # claim + `confounded_with`(같은 wafer 를 가리키는 다른 이름들) + `picked_by_llm`.
    final_claims: list[dict]
    # 어디까지 봤는가: {"ran": [...], "unrun": [...], "no_data": [...]}. 전축 실행이
    # no_signal 의 **전제 조건**이던 것을 걷어낸 대가로, 부분 커버리지 사실이 결론과
    # 함께 나가야 사유가 틀린 보고("안 본 축까지 없다")를 막는다.
    coverage: dict
    report: str                                     # 최종 리포트
