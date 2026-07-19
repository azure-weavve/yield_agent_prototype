"""대상 선정 앞단 — status 는 "대상은 정해져서 들어온다" (재설계 문서 Q3 확정).

수동 모드: 사용자가 lot_wafer 결합 형태({root_lot_id}_{wafer_id}) 목록을 직접 준다 (main.py).
자동 모드: 이 모듈이 대상을 고른다. 지금은 "최악 lot 의 최저 wafer 1장" 휴리스틱이며,
나중에 붙을 자동 대상 판단 시스템은 이 함수를 같은 인터페이스(-> list[str])로 대체한다.
"""

from tools import yield_tools as yt


def auto_select_targets() -> list[str]:
    lots = yt.find_low_yield_lots()
    if not lots:
        return []
    return [lots[0]["worst_wafer"]["wafer_id"]]
