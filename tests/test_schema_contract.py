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

import ya_config
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
    conn = sqlite3.connect(ya_config.DB_PATH)
    try:
        return _read_cols(conn, table, with_null)
    finally:
        conn.close()


def _legend_cols_by_table() -> dict[str, set[str]]:
    """가설이 요구하는 컬럼을 **그 가설이 읽는 테이블별로** 모은다.

    metro 가 생기기 전에는 전 가설이 step_history 를 읽어서 집합 하나면 됐다.
    이제는 도구마다 소스가 다르므로 테이블을 갈라야 한다 — 안 가르면 metro 의
    `item` 을 step_history 에서 찾다가 엉뚱한 곳이 빨간불이 된다.
    """
    from domain import engine

    out: dict[str, set[str]] = {}
    for spec in registry.load_hypotheses():
        table = engine.TOOL_TABLES[spec.get("tool", "step_history")]
        out.setdefault(table, set()).update(cm._legend_columns(spec["legend"]))
        # where 절이 거르는 컬럼도 그 테이블에 있어야 한다. 없으면 sqlite3.Row 조회가
        # KeyError 로 죽는데, 그건 legend 를 고친 사람이 아니라 실행자가 만난다.
        for lvl in spec["legend"]:
            out[table].update(lvl.get("where") or {})
    return out


def test_legend_columns_exist_in_internal_schema():
    """가설이 요구하는 컬럼이 사내 적재 스키마에 다 있어야 한다.

    실패하면: 해당 legend 는 실데이터에서 ValueError 로 죽는다.
    load_internal 에 컬럼을 추가하거나(사내 _extract() 계약 협의 필요),
    해당 가설을 hypotheses.yaml 에서 빼야 한다.
    """
    for table, cols in _legend_cols_by_table().items():
        if table in NOT_YET_IN_INTERNAL_LOADER:
            continue
        missing = cols - _internal_cols(table)
        assert not missing, (
            f"legend 컬럼 {sorted(missing)} 이 load_internal.py 의 {table} 에 없다. "
            f"실데이터에서 해당 가설 도구는 호출 즉시 ValueError. "
            f"docs/2026-07-25-dummy-first-stage-reorder.md Task 2 참조."
        )


# 사내 적재기에 아직 없는 소스. **비어 있는 것이 목표다.**
# metro 는 실제 테이블·컬럼 이름을 아직 못 받았다 (설계 §6 "아직 정해야 하는 것" 5번).
# 더미로 3단계를 선행 구현했으므로 도구·가설은 있는데 로더가 없는 상태다.
NOT_YET_IN_INTERNAL_LOADER = {"metro"}


def test_the_internal_loader_gap_is_declared_not_forgotten():
    """위에서 건너뛴 소스가 **실제로 아직 없는지** 확인한다.

    예외 목록은 잊히기 쉽다. 누군가 load_internal 에 metro 를 넣으면 여기가 빨간불이
    되어 NOT_YET_IN_INTERNAL_LOADER 에서 빼도록 강제한다 — 그래야 위 계약이 다시
    metro 에도 걸린다.
    """
    from data import load_internal

    for table in NOT_YET_IN_INTERNAL_LOADER:
        assert f"CREATE TABLE {table}" not in load_internal.DDL, (
            f"load_internal 에 {table} 이 생겼다. NOT_YET_IN_INTERNAL_LOADER 에서 "
            f"빼서 스키마 계약이 다시 걸리게 하라.")


def test_legend_columns_exist_in_dummy_schema():
    for table, cols in _legend_cols_by_table().items():
        missing = cols - _dummy_cols(table)
        assert not missing, f"legend 컬럼 {sorted(missing)} 이 더미 {table} 에 없다."


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


def test_dummy_db_has_exactly_the_expected_tables():
    """단일 스키마 완성 (Stage 5): 더미 테이블 목록을 통째로 잠근다.

    process_log 가 되살아나면 여기서 먼저 걸린다. **테이블이 조용히 느는 것을 막는
    것이 이 테스트의 전부**라, 새 테이블을 더할 때는 여기를 고치는 것이 정상 절차다
    (metro 는 3단계에서 그렇게 더했다 — 2026-08-12).
    """
    conn = sqlite3.connect(ya_config.DB_PATH)
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")}
    finally:
        conn.close()
    assert names == {"yield", "step_history", "sensor_log", "metro"}
