"""스키마 계약 동결 — step_history 정의가 세 곳에서 일치하는지.

이 테스트가 존재하는 이유:
  generate_dummy.py 에는 ppid 가 있고 load_internal.py 에는 없어서,
  hyp_ppid_commonality 가 더미에서 green 인데 실데이터에서 ValueError 로 죽는 일이
  실제로 발생했다. 더미 우선 개발(2026-07-25 결정)에서는 이런 어긋남이 Stage 5 까지
  숨을 수 있으므로, 계약을 테스트로 동결한다.

세 정의원:
  1) data/load_internal.py  — 사내 적재 스키마 (source of truth)
  2) data/generate_dummy.py — 더미 스키마 (개발·테스트가 실제로 밟는 것)
  3) domain/hypotheses.yaml — legend 가 요구하는 컬럼
계약: 3 ⊆ 1  AND  3 ⊆ 2  (가설이 요구하는 컬럼은 양쪽 스키마에 다 있어야 한다)

Stage 5 에서 `yield` 도 같은 방식으로 얼렸다 — Stage 4 때 더미(defect_type NOT NULL)와
로더(nullable)가 조용히 갈려 NULL 기록이 한동안 실패했기 때문이다.
`sensor_log` 는 얼리지 않는다: load_internal.py 에 대응물이 없다(사내는 FDC HTTP 조회)
— 비교 대상이 성립하지 않는다.
"""

import sqlite3

import config
from domain import registry
from tools import commonality as cm


def _read_cols(conn, table: str, with_null: bool):
    """PRAGMA table_info 에서 컬럼 정보를 읽는다 (문자열 파싱 회피).

    with_null=True 면 (이름, NOT NULL 여부) 쌍을 낸다 — 갈림 검사는 이쪽을 쓴다.
    이름만 비교하면 Stage 4 의 그 사고(더미는 NOT NULL, 로더는 nullable)를 못 잡는다.
    """
    rows = conn.execute(f"PRAGMA table_info({table})")
    return {(r[1], r[3]) if with_null else r[1] for r in rows}


def _internal_cols(table: str, with_null: bool = False):
    """사내 적재 스키마(load_internal.DDL)의 컬럼."""
    from data import load_internal

    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(load_internal.DDL)
        return _read_cols(conn, table, with_null)
    finally:
        conn.close()


def _dummy_cols(table: str, with_null: bool = False):
    """더미 DB 의 컬럼 (개발·테스트가 실제로 밟는 것)."""
    conn = sqlite3.connect(config.DB_PATH)
    try:
        return _read_cols(conn, table, with_null)
    finally:
        conn.close()


def _legend_cols() -> set[str]:
    cols = set()
    for spec in registry.load_hypotheses():
        cols |= set(cm._legend_columns(spec["legend"]))
    return cols


def test_legend_columns_exist_in_internal_schema():
    """가설이 요구하는 컬럼이 사내 적재 스키마에 다 있어야 한다.

    실패하면: 해당 legend 는 실데이터에서 ValueError 로 죽는다.
    load_internal 에 컬럼을 추가하거나(사내 _extract() 계약 협의 필요),
    해당 가설을 hypotheses.yaml 에서 빼야 한다.
    """
    missing = _legend_cols() - _internal_cols("step_history")
    assert not missing, (
        f"legend 컬럼 {sorted(missing)} 이 load_internal.py 의 step_history 에 없다. "
        f"실데이터에서 해당 가설 도구는 호출 즉시 ValueError. "
        f"docs/2026-07-25-dummy-first-stage-reorder.md Task 2 참조."
    )


def test_legend_columns_exist_in_dummy_schema():
    missing = _legend_cols() - _dummy_cols("step_history")
    assert not missing, f"legend 컬럼 {sorted(missing)} 이 더미 step_history 에 없다."


def test_internal_and_dummy_step_history_do_not_diverge_silently():
    """두 스키마 차이를 '알려진 차이' 로만 허용한다. 컬럼 이름과 NULL 허용 여부 둘 다 본다.

    ALLOWED 를 늘릴 때는 그 차이가 왜 안전한지 주석으로 남긴다.
    비어 있는 것이 최선이다.
    """
    ALLOWED: set = set()           # 알려진 차이 (없는 것이 목표)
    diff = _internal_cols("step_history", True) ^ _dummy_cols("step_history", True)
    assert diff <= ALLOWED, (
        f"step_history 스키마가 두 곳에서 갈렸다: {sorted(diff - ALLOWED)}. "
        f"의도된 차이면 ALLOWED 에 이유와 함께 추가하라."
    )


def test_internal_and_dummy_yield_do_not_diverge_silently():
    """yield 스키마도 두 곳에서 갈리지 않는다 — 이름과 NULL 허용 여부 둘 다 (Stage 5).

    Stage 4 에서 더미의 yield 는 defect_type NOT NULL 인데 로더만 nullable 이라
    NULL 기록이 한동안 실패했다. 이름만 비교하면 바로 그 사고를 못 잡는다.
    """
    ALLOWED: set = set()           # 알려진 차이 (없는 것이 목표)
    diff = _internal_cols("yield", True) ^ _dummy_cols("yield", True)
    assert diff <= ALLOWED, (
        f"yield 스키마가 두 곳에서 갈렸다: {sorted(diff - ALLOWED)}. "
        f"의도된 차이면 ALLOWED 에 이유와 함께 추가하라."
    )


def test_dummy_db_has_exactly_the_three_tables():
    """단일 스키마 완성 (Stage 5): 더미 테이블은 yield·step_history·sensor_log 뿐이다.

    process_log 가 되살아나면 여기서 먼저 걸린다.
    """
    conn = sqlite3.connect(config.DB_PATH)
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")}
    finally:
        conn.close()
    assert names == {"yield", "step_history", "sensor_log"}
