"""대상 선정 앞단 — 자동 모드 자리 (Q3: status 밖으로 분리, 데모가 사용)."""

from tools import target_selection as ts
from tools import yield_tools as yt


def test_auto_select_picks_worst_wafer_of_worst_lot():
    # 더미: 최악 lot = LOT2406, 그 최저 wafer 는 불량 그룹(76~82) 중 하나
    picked = ts.auto_select_targets()
    assert len(picked) == 1
    assert picked[0] in {"W2406_02", "W2406_04", "W2406_06"}
    worst = yt.find_low_yield_lots()[0]["worst_wafer"]["wafer_id"]
    assert picked == [worst]


def test_auto_select_returns_empty_when_no_anomaly(monkeypatch):
    monkeypatch.setattr(yt, "find_low_yield_lots", lambda: [])
    assert ts.auto_select_targets() == []
