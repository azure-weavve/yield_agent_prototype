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


def find_low_yield_lots(threshold: float | None = None) -> list[dict]:
    """평균 수율이 threshold 미만인 lot 을 낮은 순으로 반환.

    각 lot 에 대해 가장 수율 낮은 wafer(worst_wafer) 를 함께 담아,
    자동 대상 선정(tools/target_selection.py)의 재료로 쓴다.
    """
    threshold = config.YIELD_THRESHOLD if threshold is None else threshold
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
                SELECT wafer_id, yield, defect_type, step_seq, date
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


def get_wafers(wafer_ids: list[str]) -> list[dict]:
    """여러 wafer 의 yield 행 반환 (존재하는 것만, wafer_id 순 — 입력 검증·소속 lot 조회용)."""
    if not wafer_ids:
        return []
    placeholders = ",".join("?" * len(wafer_ids))
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM yield WHERE wafer_id IN ({placeholders}) ORDER BY wafer_id",
            wafer_ids,
        ).fetchall()
        return [dict(r) for r in rows]


def find_control_candidates(root_lot_ids: list[str], exclude: set[str]) -> list[str]:
    """주어진 root_lot 들의 비타깃 wafer 전원 (수율·라벨·lot_type 조건 없음).

    사내 defect_type 은 대부분 NULL 이라 '정상' 을 판정할 방법이 없다. 저수율 피해
    wafer 가 대조군에 섞이는 것을 **막지 않고 보이게 한다** — commonality 의 2x2
    (control_pass)와 select_control 의 yield_summary 가 그 자리다.
    수율 임계로 거르면 임의 수치가 계산에 들어간다 (spec 2026-07-25 §1).
    """
    if not root_lot_ids:
        return []
    placeholders = ",".join("?" * len(root_lot_ids))
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT wafer_id FROM yield WHERE root_lot_id IN ({placeholders}) "
            f"ORDER BY wafer_id",
            list(root_lot_ids),
        ).fetchall()
    return [r["wafer_id"] for r in rows if r["wafer_id"] not in exclude]
