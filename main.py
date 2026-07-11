"""실행 진입점.

기본: 데모 질문 1건으로 하이브리드 분석 루프 End-to-End 시연.
단일 질문: python main.py "질문"
(Windows 콘솔 한글 깨짐 방지: PYTHONUTF8=1 python main.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph.build import build_graph  # noqa: E402

DEMO_QUESTION = "이번 배치에서 수율 이상 wafer 의 불량 원인을 분석해줘"


def run(question: str) -> None:
    app = build_graph()
    state = app.invoke({"question": question})

    print(f"[질문] {question}\n")
    print(f"[현황 파악 — 고정 골격]\n{state['status_summary']}\n")
    print(f"[분석 대상] {state['target_wafer'] or '없음 (수율 이상 lot 없음)'}\n")

    print("[분석 루프 — 감사 기록]")
    for f in state["findings"]:
        if f["loop"] == 0:
            continue  # 현황파악은 위에서 출력
        print(f"  {f['loop']}. {f['tool']}  args={f['args']}")
        if f.get("thought"):
            print(f"     판단: {f['thought']}")
        if f["tool"] == "finalize":
            print(f"     게이트: {f['result']}")
    print()
    print(f"[리포트 — 고정 골격]\n{state['report']}")


if __name__ == "__main__":
    run(" ".join(sys.argv[1:]) if len(sys.argv) > 1 else DEMO_QUESTION)
