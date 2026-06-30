"""수율 조회·집계 함수 (결정론적). LLM 이 끼어들지 않는 영역.

모든 함수는 plain dict/list 를 반환한다 (이후 LLM 답변 생성 노드가 소비).
"""

import sqlite3
from contextlib import contextmanager

import config


@contextmanager
def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def find_low_yield_lots(threshold: float = config.YIELD_THRESHOLD) -> list[dict]:
    """평균 수율이 threshold 미만인 lot 을 낮은 순으로 반환 (시나리오 1).

    각 lot 에 대해 가장 수율 낮은 wafer(worst_wafer) 를 함께 담아,
    시나리오 2(그 wafer 로 유사 검색)로 자연스럽게 이어지게 한다.
    """
    with _conn() as conn:
        lots = conn.execute(
            """
            SELECT lot_id, ROUND(AVG(yield), 1) AS avg_yield, COUNT(*) AS wafer_count
            FROM yield
            GROUP BY lot_id
            HAVING AVG(yield) < ?
            ORDER BY avg_yield ASC
            """,
            (threshold,),
        ).fetchall()

        result = []
        for lot in lots:
            worst = conn.execute(
                """
                SELECT wafer_id, yield, defect_type, process_step, date
                FROM yield WHERE lot_id = ? ORDER BY yield ASC LIMIT 1
                """,
                (lot["lot_id"],),
            ).fetchone()
            result.append({
                "lot_id": lot["lot_id"],
                "avg_yield": lot["avg_yield"],
                "wafer_count": lot["wafer_count"],
                "worst_wafer": dict(worst),
            })
        return result


def get_wafer(wafer_id: str) -> dict | None:
    """단일 wafer 의 수율 행 반환."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM yield WHERE wafer_id = ?", (wafer_id,)
        ).fetchone()
        return dict(row) if row else None


def aggregate_defects(wafer_ids: list[str]) -> list[dict]:
    """주어진 wafer 들의 defect_type 분포 집계 (시나리오 3: 원인 추정)."""
    if not wafer_ids:
        return []
    placeholders = ",".join("?" * len(wafer_ids))
    with _conn() as conn:
        rows = conn.execute(
            f"""
            SELECT defect_type, COUNT(*) AS count
            FROM yield WHERE wafer_id IN ({placeholders})
            GROUP BY defect_type ORDER BY count DESC
            """,
            wafer_ids,
        ).fetchall()
        return [dict(r) for r in rows]
