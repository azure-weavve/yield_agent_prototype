"""사내 실데이터 적재 — yield + step_history (선적재분).

역할 경계:
  [사내 lib 로 추출]  →  (이 스크립트) 변환 + 적재  →  [yield.db]
  추출부는 사내 lib 소관이라 여기 없다. `_extract()` 안에서 연결한다.

범위: **yield 와 step_history 만.**
  sensor_log 는 2단(센서 비교)이 지목된 스텝에 대해서만 온디맨드로 당기며,
  별도 캐시 DB(sensor_cache.db) + SensorStore 계층으로 따로 붙인다. 여기서 다루지 않는다.

────────────────────────────────────────────────────────────────────────
입력 계약 — `_extract()` 가 반환할 형태 (원천 컬럼명 그대로 통과시켜도 된다)

  yield_records : [{root_lot_id, wafer_id, lot_id, yield, date,
                    defect_type(optional)}, ...]                     # wafer 1장당 1행
  step_records  : [{root_lot_id, wafer_id, process_step, eqp_id,
                    ch_id(optional), ppid(optional), timestamp}, ...]  # wafer×스텝당 1행

  ⚠️ ppid 는 **그 wafer 가 그 스텝을 돌 때 쓴 PPID** — wafer×스텝 단위다.
      lot 단위나 recipe 마스터 단위로 넣으면 에러 없이 틀린 집계가 나온다.
      hyp_ppid_commonality(2차 legend)가 이 컬럼 위에서 돈다.
      `validate()` 가 이걸 실제로 검사한다(리포트의 `ppid_grain`, `[grain]` 줄) —
      단 "전 데이터에 반례 0건" 일 때만 의심하는 전역 조건이므로 확정 판정은 아니다.

  ⚠️ **이름 겹침 주의 (이 스크립트에서 가장 헷갈리는 지점)**
      원천의 `wafer_id`  = 두 자리 **순번** ("01", "13", "25")
      타깃의 `wafer_id`  = **합성 조인 키** ("A45Z5_01")
      → 이 스크립트가 root_lot_id + "_" + zero-pad(순번,2) 로 합성해 넣는다.
        yield · step_history · EDS 3곳이 바이트 단위로 일치해야 조인이 성립한다.
        (순번 키를 `wafer_no` 로 넘겨도 받는다 — _wafer_no() 참조)
────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

import config

BATCH = 20_000          # step_history 는 wafer 당 ~1000행이라 배치로 넣는다

# 결측이 이 비율을 넘으면 '경고'가 아니라 '교체 차단'. 소수의 결측은 흔하지만
# 대부분이 결측이면 조인 키가 어긋난 것이고, 그 DB 로는 commonality 가 못 돈다.
ORPHAN_FATAL_RATE = 0.5
NO_HISTORY_FATAL_RATE = 0.5

# --------------------------------------------------------------------------- #
# lot_type 판정 — 격리 함수 (사내에서 실제 규칙으로 교체)
# --------------------------------------------------------------------------- #
# ⚠️ 실제 양산/평가 판정 규칙은 이 저장소에 두지 않는다. 아래는 문서화된 휴리스틱이며
#    사내 배포 시 **이 함수 하나만** 교체하면 된다.
# 주의: lot_type 은 대조군 '필터'가 아니다. 평가랏에는 설비 작업 후 검증랏이 섞여 있어
#      배제하면 오히려 단서를 버린다. commonality 는 이 값을 meta(해석 재료)로만 쓴다.
PROD = "prod"
EVAL = "eval"


def classify_lot_type(lot_id: str) -> str:
    """lot_id 의 '.' 접미로 양산/평가 판정 (휴리스틱, 교체 대상)."""
    suffix = lot_id.split(".", 1)[1] if "." in lot_id else ""
    return PROD if suffix == "1" else EVAL


# --------------------------------------------------------------------------- #
# 조인 키 합성
# --------------------------------------------------------------------------- #
def _wafer_no(rec: dict):
    """원천 순번 꺼내기. 원천 컬럼명이 `wafer_id` 라 `wafer_no` 둘 다 받는다."""
    if "wafer_no" in rec:
        return rec["wafer_no"]
    return rec["wafer_id"]


def build_wafer_id(root_lot_id: str, wafer_no) -> str:
    """root_lot_id + '_' + zero-pad(순번, 2) → 'A45Z5_01'.

    원천이 "01" 로 오더라도 int 캐스팅 후 재포맷한다 — 패딩 관행이 엔지니어마다
    달라 "1"/"01" 이 섞여 들어올 수 있고, 섞이면 조인이 **에러 없이** 깨진다.
    """
    try:
        n = int(wafer_no)
    except (TypeError, ValueError):
        raise ValueError(f"wafer 순번을 정수로 변환 불가: {wafer_no!r} "
                         f"(root_lot={root_lot_id})")
    if not 0 <= n <= 99:
        raise ValueError(f"wafer 순번이 두 자리 범위를 벗어남: {n} "
                         f"(root_lot={root_lot_id})")
    return f"{root_lot_id}_{n:02d}"


def _text(x):
    """빈 문자열을 NULL 로 정규화."""
    if x is None:
        return None
    s = str(x).strip()
    return s or None


# --------------------------------------------------------------------------- #
# 변환 (제너레이터 — 대용량 step_records 를 메모리에 다 올리지 않는다)
# --------------------------------------------------------------------------- #
def transform_yield(records):
    for r in records:
        root = r["root_lot_id"]
        lot_id = r["lot_id"]
        yield {
            "wafer_id": build_wafer_id(root, _wafer_no(r)),
            "lot_id": lot_id,
            "yield": float(r["yield"]),
            # ⚠️ 라벨이 없으면 'none' 이 아니라 NULL. 'none' 을 넣으면 라벨 없는 wafer 가
            #    전부 '정상'으로 둔갑해 대조군에 조용히 섞인다. NULL 이면 눈에 띄게 실패한다.
            "defect_type": _text(r.get("defect_type")),
            # ⚠️ 항상 NULL. 원천에 있어도 넣지 않는다 — '어느 스텝이 원인인가'는
            #    이 시스템이 추론할 결론이지 입력이 아니다(정답 누출).
            #    컬럼 자체는 기존 SQL 호환을 위해 남겨둔다.
            "process_step": None,
            "date": str(r["date"]),
            "root_lot_id": root,
            "lot_type": classify_lot_type(lot_id),
        }


def transform_steps(records):
    for r in records:
        yield {
            "wafer_id": build_wafer_id(r["root_lot_id"], _wafer_no(r)),
            "process_step": str(r["process_step"]),
            "eqp_id": str(r["eqp_id"]),
            # ch_id 는 NULL 허용 (단일 챔버 설비·챔버 개념 없는 스텝).
            # commonality 가 NULL 이면 챔버 레벨을 건너뛰고 설비 레벨만 계산한다.
            "ch_id": _text(r.get("ch_id")),
            # ppid 도 NULL 허용. 원천에 없거나 PPID 개념이 없는 스텝이면 commonality 가
            # 그 레벨을 건너뛴다(ch_id 와 같은 취급).
            "ppid": _text(r.get("ppid")),
            "timestamp": _text(r.get("timestamp")),
        }


# --------------------------------------------------------------------------- #
# 스키마 + 적재
# --------------------------------------------------------------------------- #
DDL = """
DROP TABLE IF EXISTS yield;
DROP TABLE IF EXISTS step_history;

CREATE TABLE yield (
    wafer_id     TEXT PRIMARY KEY,   -- 합성 조인 키 (root_lot_id + '_' + NN)
    lot_id       TEXT NOT NULL,
    yield        REAL NOT NULL,
    defect_type  TEXT,               -- NULL = 라벨 없음 (EDS 유래 메타데이터)
    process_step TEXT,               -- 항상 NULL (정답 누출 방지, 컬럼만 호환 유지)
    date         TEXT NOT NULL,
    root_lot_id  TEXT NOT NULL,
    lot_type     TEXT NOT NULL       -- 필터가 아니라 해석용 컨텍스트
);

CREATE TABLE step_history (
    wafer_id     TEXT NOT NULL,      -- 합성 조인 키
    process_step TEXT NOT NULL,
    eqp_id       TEXT NOT NULL,
    ch_id        TEXT,               -- NULL 허용
    ppid         TEXT,               -- NULL 허용 (2차 legend: hyp_ppid_commonality)
    timestamp    TEXT
);
"""

# 인덱스는 적재 **후에** 만든다 (적재 중 인덱스 유지 비용 회피)
INDEXES = """
CREATE INDEX idx_step_wafer ON step_history(wafer_id);
CREATE INDEX idx_step_step  ON step_history(process_step);
CREATE INDEX idx_yield_root ON yield(root_lot_id);
"""


def _insert_batched(conn, sql, rows_iter):
    n, batch = 0, []
    for row in rows_iter:
        batch.append(row)
        if len(batch) >= BATCH:
            conn.executemany(sql, batch)
            n += len(batch)
            batch = []
    if batch:
        conn.executemany(sql, batch)
        n += len(batch)
    return n


def load(yield_records, step_records, db_path: Path,
         verbose: bool = True, force: bool = False) -> dict:
    """임시 파일에 적재 → 검증 통과 시에만 원자적 교체.

    운영 DB 를 직접 DROP 하면, 추출 실패·프로세스 중단·검증 실패 시 어제까지 멀쩡하던
    데이터가 사라진 채 남는다(분석이 전부 no_paired_stratum 으로 끝나는데 원인이 안 보임).
    그래서 항상 `<db>.tmp` 에 만들고, fatal 이슈가 없을 때만 os.replace 로 갈아끼운다.
    os.replace 는 같은 파일시스템에서 원자적이라 실패해도 기존 DB 가 그대로 남는다.
    """
    db_path = Path(db_path)
    tmp_path = db_path.with_name(db_path.name + ".tmp")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.unlink()                            # 지난 실패의 잔해 제거

    conn = sqlite3.connect(tmp_path)
    try:
        conn.execute("PRAGMA journal_mode=OFF")      # 초기 벌크 적재 — 복구 필요 없음
        conn.execute("PRAGMA synchronous=OFF")
        conn.executescript(DDL)

        n_y = _insert_batched(conn, """
            INSERT INTO yield (wafer_id, lot_id, yield, defect_type, process_step,
                               date, root_lot_id, lot_type)
            VALUES (:wafer_id, :lot_id, :yield, :defect_type, :process_step,
                    :date, :root_lot_id, :lot_type)""", transform_yield(yield_records))

        n_s = _insert_batched(conn, """
            INSERT INTO step_history (wafer_id, process_step, eqp_id, ch_id, ppid, timestamp)
            VALUES (:wafer_id, :process_step, :eqp_id, :ch_id, :ppid, :timestamp)""",
            transform_steps(step_records))

        conn.executescript(INDEXES)
        conn.commit()
        report = validate(conn, n_y, n_s)
    except BaseException:
        conn.close()
        tmp_path.unlink(missing_ok=True)             # 기존 DB 는 건드리지 않는다
        raise
    else:
        conn.close()

    swap = force or not report["fatal"]
    if swap:
        os.replace(tmp_path, db_path)                # 원자적 교체
    else:
        tmp_path.unlink(missing_ok=True)
    report["swapped"] = swap
    report["db_path"] = str(db_path)

    if verbose:
        _print(report)
    return report


# --------------------------------------------------------------------------- #
# 적재 후 정합성 검사
# --------------------------------------------------------------------------- #
_WID = re.compile(r"^.+_\d{2}$")


def validate(conn: sqlite3.Connection, n_yield: int, n_steps: int) -> dict:
    conn.row_factory = sqlite3.Row
    q = lambda sql, *a: conn.execute(sql, a).fetchall()
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

    # fatal = 교체 차단 (이 상태로 갈아끼우면 기존 DB 보다 나쁘다)
    # warn  = 교체는 하되 사람이 봐야 하는 것
    fatal, issues = [], []

    # 0. 빈 추출 — 그대로 교체하면 멀쩡한 DB 를 빈 DB 로 덮어쓴다
    if n_yield == 0:
        fatal.append("yield 0행: 추출 결과가 비었다 (교체 중단)")

    # 1. 조인 키 형식 (…_NN)
    bad = [r["wafer_id"] for r in q("SELECT wafer_id FROM yield")
           if not _WID.match(r["wafer_id"])]
    if bad:
        fatal.append(f"wafer_id 형식 위반 {len(bad)}건 (예: {bad[:3]})")

    # 2. wafer_id 접두 == root_lot_id 교차검증
    mism = q("""SELECT wafer_id FROM yield
                WHERE wafer_id <> root_lot_id || '_' || substr(wafer_id, -2)""")
    if mism:
        fatal.append(f"root_lot_id 불일치 {len(mism)}건 "
                     f"(예: {[r['wafer_id'] for r in mism[:3]]})")

    # 3. step_history 고아 (이력엔 있으나 yield 에 없는 wafer) — 조인 키 불일치의 주 증상
    # 소수면 경고지만, 대부분이 고아면 조인 키 자체가 어긋난 것이므로 교체를 막는다
    n_hist_wafers = one("SELECT COUNT(DISTINCT wafer_id) FROM step_history")
    orphan = q("""SELECT DISTINCT s.wafer_id FROM step_history s
                  LEFT JOIN yield y ON y.wafer_id = s.wafer_id
                  WHERE y.wafer_id IS NULL""")
    if orphan:
        msg = (f"step_history 고아 wafer {len(orphan)}/{n_hist_wafers}건 "
               f"(예: {[r['wafer_id'] for r in orphan[:3]]}): 조인 키 불일치 의심")
        (fatal if len(orphan) > n_hist_wafers * ORPHAN_FATAL_RATE else issues).append(msg)

    # 4. 이력 없는 wafer — commonality 가 분모에서 제외하므로 표본이 조용히 줄어든다.
    #    대부분이 이력 없으면 1단이 아예 못 돌므로 교체를 막는다.
    no_hist = q("""SELECT y.wafer_id FROM yield y
                   LEFT JOIN step_history s ON s.wafer_id = y.wafer_id
                   WHERE s.wafer_id IS NULL""")
    if no_hist:
        msg = (f"step_history 없는 wafer {len(no_hist)}/{n_yield}건 "
               f"(예: {[r['wafer_id'] for r in no_hist[:3]]}): commonality 분모에서 빠짐")
        (fatal if len(no_hist) > n_yield * NO_HISTORY_FATAL_RATE else issues).append(msg)

    # 5. yield 범위
    oor = one("SELECT COUNT(*) FROM yield WHERE yield < 0 OR yield > 100")
    if oor:
        issues.append(f"yield 범위(0~100) 이탈 {oor}건")

    # 6. 중복 이력 (같은 wafer×스텝이 여러 번) — 정상일 수도(재작업), 확인 필요
    dup = one("""SELECT COUNT(*) FROM (SELECT wafer_id, process_step
                 FROM step_history GROUP BY 1,2 HAVING COUNT(*) > 1)""")
    if dup:
        issues.append(f"wafer×스텝 중복 이력 {dup}건: 재작업(rework)인지 확인 필요")

    # 7. ppid grain — 결측률이 못 보는 실패. ppid 를 lot/recipe 마스터에서 조인해 오면
    #    결측률 0.0(초록)인데 lot 전원이 같은 값이 되어 hyp_ppid_commonality 가 에러 없이
    #    틀린 집계를 낸다. 한 lot 이 한 PPID 로 도는 건 정상인 스텝도 많으므로 lot 개별
    #    판정은 오경보가 잦다 — 반례(한 군에서 ppid 2값) 1건이면 wafer 단위가 증명되니
    #    "전 데이터에 반례 0건" 이라는 전역 조건으로만 의심한다.
    #
    #    판정 대상(`checkable`)은 **설비·챔버가 wafer 마다 갈리는 군**으로 좁힌다. 그런
    #    군에서는 원천이 그 스텝에서 wafer 단위 세부를 실제로 주고 있음이 증명되므로,
    #    "챔버는 갈리는데 ppid 는 한 번도 안 갈린다" 가 비로소 의심스러운 조건이 된다.
    #    설비·챔버도 안 갈리는 군(= lot 전원이 같은 장비로 돈 정상 케이스)을 포함하면
    #    정상 데이터에 경고가 뜬다. 좁힌 대가로, 스텝마다 단일 장비만 쓰는 공정에서는
    #    검사가 침묵한다 — 그 경우 원천이 wafer 단위를 주는지 자체가 안 보이므로 정직하다.
    #
    #    ppid·장비 모두 **wafer 단위로 먼저 접는다**(안쪽 GROUP BY). 행 단위로 세면 한
    #    wafer 의 재작업 2행이 값만 다를 때 wafer 간 변이가 0인데도 반례로 잡히고, 판정이
    #    전역이라 그런 행 하나로 검사 전체가 조용히 꺼진다 (검사 #6 참조: 실데이터에
    #    중복 이력은 예상되는 상태다).
    #    `COUNT(DISTINCT tool) > 1` 이 "wafer 2장 이상" 을 함의하므로 별도 조건을 안 둔다.
    gr = q("""SELECT COUNT(*) checkable, COALESCE(SUM(nd > 1), 0) varying FROM (
                  SELECT COUNT(DISTINCT p) nd
                  FROM (SELECT y.lot_id lot, h.process_step step, h.wafer_id w,
                               MIN(h.ppid) p,
                               MIN(h.eqp_id || '|' || IFNULL(h.ch_id, '')) tool
                        FROM step_history h JOIN yield y USING (wafer_id)
                        WHERE h.ppid IS NOT NULL
                        GROUP BY 1, 2, 3)
                  GROUP BY lot, step
                  HAVING COUNT(DISTINCT tool) > 1)""")[0]
    ppid_grain = {"checkable": gr["checkable"], "varying": gr["varying"]}
    if ppid_grain["checkable"] and ppid_grain["varying"] == 0:
        # 확정 판정이 아니라는 것을 **문구 안에** 적는다. 콘솔에서 이 줄을 보는 사람은
        # 이 파일의 docstring 을 읽지 않으므로, 여기 없으면 없는 조인 버그를 쫓게 된다.
        issues.append(
            f"설비·챔버는 wafer 마다 갈리는데 ppid 는 한 번도 안 갈린다 "
            f"(검사 가능 {ppid_grain['checkable']}군). "
            "lot/recipe 마스터 단위 조인 의심 (ppid 는 wafer×스텝 단위여야 한다). "
            "단 한 lot 을 여러 챔버에 걸쳐 같은 레시피로 돌리는 것도 정상이라 확정은 아니다")

    lot_types = {r["lot_type"]: r["c"] for r in
                 q("SELECT lot_type, COUNT(*) c FROM yield GROUP BY 1")}
    if lot_types.get(PROD, 0) == 0:
        issues.append(f"양산({PROD}) lot 0건: classify_lot_type 규칙 확인 필요")

    steps = q("""SELECT MIN(c) lo, MAX(c) hi, AVG(c) avg FROM
                 (SELECT COUNT(*) c FROM step_history GROUP BY wafer_id)""")
    s = steps[0] if steps and steps[0]["lo"] is not None else None

    return {
        "n_yield": n_yield, "n_steps": n_steps,
        "n_wafers_with_history": one("SELECT COUNT(DISTINCT wafer_id) FROM step_history"),
        "n_root_lots": one("SELECT COUNT(DISTINCT root_lot_id) FROM yield"),
        "lot_types": lot_types,
        "defect_labeled": one("SELECT COUNT(*) FROM yield WHERE defect_type IS NOT NULL"),
        "steps_per_wafer": ({"min": s["lo"], "max": s["hi"], "avg": round(s["avg"], 1)}
                            if s else None),
        # ch_id 결측률 — 높으면 commonality 가 챔버 레벨을 거의 못 쓴다(설비 레벨만 남음)
        "ch_id_null_rate": round(
            one("SELECT COUNT(*) FROM step_history WHERE ch_id IS NULL")
            / max(n_steps, 1), 3),
        # ppid 결측률 — 전부 NULL 이면 hyp_ppid_commonality 가 **에러 없이 후보 0** 으로
        # 끝난다. 이 값이 없으면 "PPID 로도 안 갈린다" 와 "PPID 가 안 실렸다" 를 구분 못 한다.
        "ppid_null_rate": round(
            one("SELECT COUNT(*) FROM step_history WHERE ppid IS NULL")
            / max(n_steps, 1), 3),
        # grain 진단 — checkable 0 이면 판정 불가(설비·챔버가 갈리면서 ppid 도 있는 군이 없다)
        "ppid_grain": ppid_grain,
        "fatal": fatal,
        "issues": issues,
    }


def _say(line: str) -> None:
    """콘솔 인코딩이 못 싣는 글자가 있어도 리포트를 잃지 않는다.

    한국어 코드페이지(cp949)에는 em-dash(U+2014)가 없다. 경고 문구에 그 글자가 하나
    있으면 print 가 UnicodeEncodeError 로 죽는데, `_print` 는 os.replace **뒤에**
    불리므로 DB 는 교체된 채 traceback 만 남고 사람이 봐야 할 경고가 사라진다.
    빈 추출·중복 이력처럼 리포트가 가장 필요한 순간이 정확히 이 경로다.
    """
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(line.encode(enc, "replace").decode(enc, "replace"))


def _print(r: dict) -> None:
    _say(f"[적재] yield {r['n_yield']}행 / step_history {r['n_steps']}행")
    _say(f"[구성] root_lot {r['n_root_lots']}개 · 이력 보유 wafer {r['n_wafers_with_history']}장 "
         f"· lot_type {r['lot_types']}")
    _say(f"[이력] wafer 당 스텝 {r['steps_per_wafer']} · ch_id 결측률 {r['ch_id_null_rate']}"
         f" · ppid 결측률 {r['ppid_null_rate']}")
    # 경고가 안 뜬 이유를 구분하려면 숫자가 보여야 한다 (wafer 단위 확인됨 vs 판정 불가)
    g = r["ppid_grain"]
    _say(f"[grain] ppid wafer 단위 증거 {g['varying']}/{g['checkable']}군"
         f"{' (판정 불가: 설비·챔버가 wafer 마다 갈리면서 ppid 도 있는 군이 없다)' if not g['checkable'] else ''}")
    _say(f"[라벨] defect_type 보유 {r['defect_labeled']}건 (없으면 EDS 로 그룹을 만든다)")
    if r["issues"]:
        _say("[정합성 경고]")
        for i in r["issues"]:
            _say(f"  - {i}")
    if r["fatal"]:
        _say("[치명적 오류]")
        for i in r["fatal"]:
            _say(f"  - {i}")
    if not r["issues"] and not r["fatal"]:
        _say("[정합성] 이상 없음")
    if r.get("swapped"):
        _say(f"[교체] {r['db_path']} 갱신 완료")
    else:
        _say(f"[교체 안 함] {r['db_path']} 는 기존 상태 유지 "
             f"(--force 로 무시 가능)")


# --------------------------------------------------------------------------- #
# 진입점
# --------------------------------------------------------------------------- #
def _extract():
    """⚠️ 사내 추출 라이브러리를 연결할 자리.

    반환: (yield_records, step_records) — 위 '입력 계약' 형태.
    step_records 는 커도 되므로 리스트 대신 제너레이터를 반환해도 된다.
    """
    raise NotImplementedError(
        "사내 추출 라이브러리를 연결하세요. "
        "yield_records / step_records 를 입력 계약 형태로 반환하면 됩니다."
    )


def main():
    ap = argparse.ArgumentParser(description="사내 실데이터 → yield + step_history 적재")
    # help 문구는 argparse 가 직접 찍는다 — `_say` 가 못 덮으므로 cp949 밖 글자를 쓰면
    # `--help` 자체가 UnicodeEncodeError 로 죽는다 (em-dash·⚠️ 금지)
    ap.add_argument("--db", default=str(config.DB_PATH),
                    help=f"적재 대상 DB (기본 {config.DB_PATH}: 더미와 동일, 덮어씀 주의)")
    ap.add_argument("--force", action="store_true",
                    help="치명적 정합성 오류가 있어도 기존 DB 를 교체한다")
    args = ap.parse_args()

    db = Path(args.db)
    if db == Path(config.DB_PATH):
        _say(f"[주의] {db} 는 더미 DB 와 같은 경로입니다. 기존 내용이 대체됩니다.")

    yield_records, step_records = _extract()
    report = load(yield_records, step_records, db, force=args.force)
    raise SystemExit(0 if report["swapped"] else 1)


if __name__ == "__main__":
    main()