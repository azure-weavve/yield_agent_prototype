"""실행 진입점.

기본: 시나리오 1→2 대화를 같은 thread 로 연속 실행 (End-to-End 시연).
단일 질문: python main.py "질문"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph.build import build_graph  # noqa: E402

DEMO_CONVERSATION = [
    "이번 배치에서 수율 떨어진 lot 있어?",
    "그 wafer 불량 맵 패턴이 과거 어떤 사례랑 비슷해?",
]


def _print_turn(question: str, state: dict) -> None:
    print(f"[질문] {question}")
    print(f"[의도] {state.get('intent')}")
    print(f"[답변]\n{state.get('answer')}\n")


def run_conversation(questions: list[str], thread_id: str = "demo") -> None:
    app = build_graph()
    cfg = {"configurable": {"thread_id": thread_id}}  # 같은 thread = 멀티턴 상태 유지
    for q in questions:
        state = app.invoke({"question": q}, cfg)
        _print_turn(q, state)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_conversation([" ".join(sys.argv[1:])])
    else:
        run_conversation(DEMO_CONVERSATION)
