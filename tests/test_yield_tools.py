"""tools/yield_tools.py 결정론적 함수 검증 (더미 DB 는 seed 42 고정)."""

import config
from tools import yield_tools as yt


def test_get_wafers_returns_rows_for_known_ids_only():
    rows = yt.get_wafers(["W2406_02", "W_NOPE", "W2406_01"])
    assert [r["wafer_id"] for r in rows] == ["W2406_01", "W2406_02"]  # 미존재는 조용히 제외
    assert rows[1]["lot_id"] == "LOT2406"


def test_find_control_candidates_includes_low_yield_unlabeled_wafer():
    """라벨이 없으면 '정상' 을 판정할 수 없다 — 저수율·무라벨 wafer 도 대조군 후보다.

    W2406_07(88.5, 라벨 없음)은 옛 규칙에서 수율 임계로 걸러졌다. 새 규칙은 걸러내지
    않고 보이게 한다 (spec 2026-07-25 결정 1·2).
    """
    assert yt.find_control_candidates(["LOT2406"], exclude={"W2406_02"}) == [
        "W2406_01", "W2406_03", "W2406_04", "W2406_05", "W2406_06", "W2406_07"]


def test_find_control_candidates_spans_split_lots_of_one_root_lot():
    from data.generate_dummy import SPLIT_TARGETS
    assert yt.find_control_candidates(["R2418"], exclude=set(SPLIT_TARGETS)) == [
        "R2418_05", "R2418_06", "R2418_07", "R2418_08"]


def test_find_control_candidates_empty_root_lots():
    assert yt.find_control_candidates([], exclude=set()) == []


def test_find_low_yield_lots_threshold_binds_at_runtime(monkeypatch):
    # 문제 9: 기본 인자가 import 시점 값으로 굳으면 런타임 변경이 무시된다
    monkeypatch.setattr(config, "YIELD_THRESHOLD", 0.0)
    assert yt.find_low_yield_lots() == []
