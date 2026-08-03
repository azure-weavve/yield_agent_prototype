"""실행 진입점.

수동 모드: python main.py W2406_02 [W2406_04 ...]
  - 인자 = 분석 대상 wafer (lot_wafer 결합 형태 {root_lot_id}_{wafer_id}, 예: A45Z4_13)
  - 1장이면 EDS 형제 묶기, 여러 장이면 그 그룹 그대로 분석
자동 모드(데모): 인자 없이 실행 — 대상 선정 앞단이 최악 lot 의 최저 wafer 를 고른다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ya_console import say                        # noqa: E402
from graph.build import build_graph            # noqa: E402
from tools import target_selection             # noqa: E402


def run(target_wafers: list[str], source: str) -> None:
    app = build_graph()
    state = app.invoke({"target_wafers": target_wafers, "target_source": source})

    # 출력은 전부 `say` 로 한다 — 그래프를 다 돌린 **뒤** 라서, print 한 줄이 콘솔
    # 인코딩에 걸려 죽으면 분석 결과를 통째로 잃는다 (ya_console.py 참조).
    say(f"[분석 대상 입력] ({source}) {', '.join(target_wafers) or '없음'}\n")
    say(f"[현황 파악 — 고정 골격]\n{state['status_summary']}\n")
    tg = state["target_group"]
    if tg and not state.get("finalize_status"):
        say(f"[분석 그룹] 불량 {', '.join(tg)}  /  대조 {', '.join(state['control_group'])}\n")

    say("[분석 루프 — 감사 기록]")
    for f in state["findings"]:
        if f["loop"] == 0:
            continue  # 현황파악은 위에서 출력
        say(f"  {f['loop']}. {f['tool']}  args={f['args']}")
        if f.get("thought"):
            say(f"     판단: {f['thought']}")
        if f["tool"] == "finalize":
            say(f"     게이트: {f['result']}")
    say()
    say(f"[리포트 — 고정 골격]\n{state['report']}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(sys.argv[1:], "manual")
    else:
        run(target_selection.auto_select_targets(), "auto")
