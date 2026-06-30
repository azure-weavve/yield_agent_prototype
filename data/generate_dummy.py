"""더미 데이터 생성 스크립트.

설계 문서 3.1절 스키마를 따른다.
- yield 테이블 (SQLite): wafer_id, lot_id, yield, defect_type, process_step, date
- 512차원 맵 임베딩 인덱스 (hnswlib): wafer_id -> 512d 벡터

핵심 = "유사 그룹 심기":
  정상 다수 + 몇 개의 패턴 그룹.
  각 패턴 그룹은
    (가) 임베딩 공간에서 서로 가깝다 (그룹 중심 벡터 + 작은 noise).
    (나) 같은 defect_type 을 공유한다.
    (다) date 가 과거~최근에 분포 (그룹당 최근 1장 + 과거 4~5장).
  최근 1장은 시나리오 1에서 수율 낮게 잡힐 wafer,
  나머지 과거 장들은 시나리오 2의 유사 검색 결과가 된다.
"""

import json
import sqlite3
from pathlib import Path

import hnswlib
import numpy as np

# ---------------------------------------------------------------- 설정 (문서 9절 기본값)
SEED = 42
DIM = 512  # 실제 시스템과 동일 차원

N_NORMAL = 80  # 정상 wafer 수
# 그룹 응집도. 단위 길이 중심 벡터에 더할 noise 의 대략적 '노름'.
# 512차원에서 그대로 standard_normal 을 쓰면 노름이 sqrt(DIM)~23 으로 커져
# 중심을 압도하므로, 실제 noise 는 1/sqrt(DIM) 로 스케일한다 (_make_member 참고).
# 0.30 -> 그룹 내 코사인 유사도 약 0.95.
GROUP_NOISE = 0.30

# 패턴 그룹: 그룹당 (최근 1 + 과거 n_past) 장, 같은 defect_type 공유
PATTERN_GROUPS = [
    {"defect": "edge_ring", "process": "Diffusion", "n_past": 5},
    {"defect": "center_spot", "process": "Etch", "n_past": 4},
    {"defect": "scratch", "process": "CMP", "n_past": 4},
    {"defect": "donut", "process": "Photo", "n_past": 4},
]

RECENT_LOT = "LOT2406"  # "이번 배치" — 최근 패턴 wafer 들이 모이는 lot
RECENT_DATE = "2024-06-15"
PAST_DATES = ["2024-01-15", "2024-02-12", "2024-03-18", "2024-04-22", "2024-05-09"]
NORMAL_LOTS = ["LOT2401", "LOT2402", "LOT2403", "LOT2404", "LOT2405"]

DATA_DIR = Path(__file__).resolve().parent
DB_PATH = DATA_DIR / "yield.db"
EMB_DIR = DATA_DIR / "embeddings"


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-12)


def _make_member(center: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """그룹 중심 근처의 멤버 벡터. noise 를 1/sqrt(DIM) 로 스케일해
    512차원에서도 노름이 GROUP_NOISE 수준에 머물도록 한다."""
    noise = (GROUP_NOISE / np.sqrt(DIM)) * rng.standard_normal(DIM)
    return _unit(center + noise)


def generate():
    rng = np.random.default_rng(SEED)

    rows = []          # yield 테이블 행 (dict)
    vectors = []       # 임베딩 벡터 (np.ndarray)
    wafer_ids = []     # vectors 와 같은 순서의 wafer_id

    # ---------------- 정상 wafer: 무작위 임베딩, 높은 수율, defect 없음
    for i in range(N_NORMAL):
        wid = f"W2401_{i:03d}"
        lot = NORMAL_LOTS[i % len(NORMAL_LOTS)]
        rows.append({
            "wafer_id": wid,
            "lot_id": lot,
            "yield": round(float(rng.uniform(93.0, 99.0)), 1),
            "defect_type": "none",
            "process_step": "Normal",
            "date": PAST_DATES[i % len(PAST_DATES)],
        })
        vectors.append(_unit(rng.standard_normal(DIM)))
        wafer_ids.append(wid)

    # ---------------- 패턴 그룹: 그룹 중심 + noise, 같은 defect, 최근 1 + 과거 n
    for g_idx, grp in enumerate(PATTERN_GROUPS):
        center = _unit(rng.standard_normal(DIM))  # 그룹 중심 벡터
        tag = grp["defect"][:3]                   # wafer_id 가독성용 접두

        # (최근) 시나리오 1에서 잡힐 wafer — 수율 낮음, RECENT_LOT 소속
        recent_wid = f"W2406_{tag}0"
        rows.append({
            "wafer_id": recent_wid,
            "lot_id": RECENT_LOT,
            "yield": round(float(rng.uniform(82.0, 88.0)), 1),
            "defect_type": grp["defect"],
            "process_step": grp["process"],
            "date": RECENT_DATE,
        })
        vectors.append(_make_member(center, rng))
        wafer_ids.append(recent_wid)

        # (과거) 시나리오 2의 유사 검색 결과가 될 wafer 들.
        # 정상 lot 에 섞어 넣어 lot 평균은 높게 유지(>임계) → 시나리오 1을 어지럽히지 않음.
        # (유사 검색은 wafer 단위라 lot 배치와 무관.)
        for p in range(grp["n_past"]):
            past_wid = f"W24{g_idx}{p}_{tag}{p + 1}"
            rows.append({
                "wafer_id": past_wid,
                "lot_id": NORMAL_LOTS[(g_idx + p) % len(NORMAL_LOTS)],
                "yield": round(float(rng.uniform(85.0, 92.0)), 1),
                "defect_type": grp["defect"],
                "process_step": grp["process"],
                "date": PAST_DATES[p % len(PAST_DATES)],
            })
            vectors.append(_make_member(center, rng))
            wafer_ids.append(past_wid)

    _write_sqlite(rows)
    _write_index(vectors, wafer_ids)
    _report(rows, vectors, wafer_ids)


def _write_sqlite(rows):
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE yield (
            wafer_id     TEXT PRIMARY KEY,
            lot_id       TEXT NOT NULL,
            yield        REAL NOT NULL,
            defect_type  TEXT NOT NULL,
            process_step TEXT,
            date         TEXT NOT NULL
        )
    """)
    conn.executemany(
        "INSERT INTO yield VALUES (:wafer_id, :lot_id, :yield, :defect_type, :process_step, :date)",
        rows,
    )
    conn.commit()
    conn.close()


def _write_index(vectors, wafer_ids):
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    data = np.vstack(vectors).astype(np.float32)
    n = data.shape[0]

    index = hnswlib.Index(space="cosine", dim=DIM)
    index.init_index(max_elements=n, ef_construction=200, M=16)
    index.add_items(data, np.arange(n))  # 내부 label = vectors 인덱스
    index.set_ef(50)
    index.save_index(str(EMB_DIR / "index.bin"))

    # label(int) -> wafer_id 매핑 + 메타
    (EMB_DIR / "labels.json").write_text(
        json.dumps({"dim": DIM, "wafer_ids": wafer_ids}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _report(rows, vectors, wafer_ids):
    print(f"총 wafer: {len(rows)}  (정상 {N_NORMAL} + 패턴 {len(rows) - N_NORMAL})")
    print(f"임베딩: {len(vectors)} x {DIM}d  -> {EMB_DIR / 'index.bin'}")
    print(f"SQLite: {DB_PATH}")
    print("\n[lot 평균 수율 낮은 순 상위 3]")
    by_lot = {}
    for r in rows:
        by_lot.setdefault(r["lot_id"], []).append(r["yield"])
    avg = sorted(((sum(v) / len(v), lot, len(v)) for lot, v in by_lot.items()))
    for a, lot, c in avg[:3]:
        print(f"  {lot}: 평균 {a:.1f}  (wafer {c}장)")
    print("\n[최근 패턴 wafer (시나리오 1 검출 대상)]")
    for r in rows:
        if r["lot_id"] == RECENT_LOT:
            print(f"  {r['wafer_id']}  yield={r['yield']}  defect={r['defect_type']}")


if __name__ == "__main__":
    generate()
