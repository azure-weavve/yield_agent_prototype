"""사내 실데이터 적재 — yield + step_history (선적재분).

역할 경계:
  [사내 lib 로 추출]  →  (이 스크립트) 변환 + 적재  →  [yield.db]
  추출부는 사내 lib 소관이라 여기 없다. `_extract()` 안에서 연결한다.

범위: **yield 와 step_history 만.**
  sensor_log 는 2단(센서 비교)이 지목된 스텝에 대해서만 온디맨드로 당기며,
  별도 캐시 DB(sensor_cache.db) + SensorStore 계층으로 따로 붙인다. 여기서 다루지 않는다.

────────────────────────────────────────────────────────────────────────
입력 계약 — `_extract()` 가 반환할 형태 (원천 컬럼명 그대로 통과시켜도 된다)

  yield_records : [{root_lot_id, wafer_id, lot_id, lot_type, yield, date,
                    defect_type(optional)}, ...]                     # wafer 1장당 1행
  step_records  : [{root_lot_id, wafer_id, step_seq, eqp_id,
                    area(optional), ch_id(optional), ppid(optional),
                    timestamp}, ...]                                 # wafer×스텝당 1행

  ⚠️ `step_seq` 는 **문자 2자리(제품군) + 숫자 6자리(스텝 순서)** 다 ("CC001000").
      스텝의 **공정명이 아니다** — 공정명은 원천의 별개 컬럼 `area` 에 있고, 그 스텝이
      무슨 공정인지 확인할 때 그쪽을 본다. 분석은 step_seq 를 축으로 돈다.
      뒤에 **`EC` 가 붙는 값이 있다**("AA110000EC"). **비정규 스텝** 표시이고 정상적으로
      실려 오는 값이다. 원천 값을 그대로 싣는다 — 접미를 떼지 않는다.

  ⚠️ ppid 는 **그 wafer 가 그 스텝을 돌 때 쓴 PPID** — wafer×스텝 단위다.
      lot 단위나 recipe 마스터 단위로 넣으면 에러 없이 틀린 집계가 나온다.
      hyp_ppid_commonality(2차 legend)가 이 컬럼 위에서 돈다.
      **적재된 테이블만으로는 이걸 검증할 수 없다.** lot×스텝 마스터에서 조인한 값과
      제대로 실린 값은 이 테이블 안에서 완전히 같은 모양이다(둘 다 스텝마다 갈리고
      lot 안에서는 대개 안 갈린다 — 후자는 도메인상 정상이다). 그래서 조인 단위는
      **사람이 원천 추출 쿼리에서 확인**해야 한다. 점검표 1장 참조.

  ⚠️ **이름 겹침 주의 (이 스크립트에서 가장 헷갈리는 지점)**
      원천의 `wafer_id`  = 두 자리 **순번** ("01", "13", "25")
      타깃의 `wafer_id`  = **합성 조인 키** ("A45Z5_01")
      → 이 스크립트가 root_lot_id + "_" + zero-pad(순번,2) 로 합성해 넣는다.
        yield · step_history · EDS 3곳이 바이트 단위로 일치해야 조인이 성립한다.
        (순번 키를 `wafer_no` 로 넘겨도 받는다 — _wafer_no() 참조)

      원천의 `lot_type`  = 사내 **두 자리 코드** ("PP" 양산 · "ES" 평가 등)
      타깃의 `lot_type`  = **"prod" / "eval"**
      → classify_lot_type() 이 변환해 넣는다. 원천 코드를 그대로 실으면 commonality
        meta 집계가 사내 코드로 나와 해석이 어긋난다.
────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

# 스크립트 경로(`python data/load_internal.py`)로 실행하면 sys.path[0] 이 data/ 라
# 저장소 루트가 빠진다. generate_dummy.py 와 같은 방어다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ya_config                       # noqa: E402
from ya_console import say as _say     # noqa: E402  cp949 콘솔에서 리포트가 통째로 사라지는 것을 막는다

BATCH = 20_000          # step_history 는 wafer 당 ~1000행이라 배치로 넣는다

# 결측이 이 비율을 넘으면 '경고'가 아니라 '교체 차단'. 소수의 결측은 흔하지만
# 대부분이 결측이면 조인 키가 어긋난 것이고, 그 DB 로는 commonality 가 못 돈다.
ORPHAN_FATAL_RATE = 0.5
NO_HISTORY_FATAL_RATE = 0.5

# --------------------------------------------------------------------------- #
# lot_type 판정 — 격리 함수 (원천 두 자리 코드 → prod/eval)
# --------------------------------------------------------------------------- #
# 판정 규칙이 바뀌면 **이 함수 하나만** 고치면 된다.
# 주의: lot_type 은 대조군 '필터'가 아니다. 평가랏에는 설비 작업 후 검증랏이 섞여 있어
#      배제하면 오히려 단서를 버린다. commonality 는 이 값을 meta(해석 재료)로만 쓴다.
PROD = "prod"
EVAL = "eval"


def classify_lot_type(code: str) -> str:
    """원천 lot_type 두 자리 코드의 첫 글자가 P 면 양산, 아니면 평가.

    형식이 어긋나면 eval 로 떨어뜨리지 않고 적재를 멈춘다 — 조용히 넘기면 양산랏이
    통째로 평가랏으로 둔갑해도 리포트의 lot_type 집계가 그럴듯해 보인다.
    """
    if not code or len(code) != 2:
        raise ValueError(f"lot_type 코드가 두 자리가 아님: {code!r}")
    return PROD if code[0].upper() == "P" else EVAL


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
            "step_seq": None,
            "date": str(r["date"]),
            "root_lot_id": root,
            "lot_type": classify_lot_type(r["lot_type"]),
        }


def transform_steps(records):
    for r in records:
        yield {
            "wafer_id": build_wafer_id(r["root_lot_id"], _wafer_no(r)),
            # 증분 적재가 lot 단위로 지우고 다시 넣을 때 쓰는 키. wafer_id 접두와 같은
            # 값이지만 문자열을 쪼개 쓰면 인덱스를 못 타므로 컬럼으로 둔다.
            "root_lot_id": r["root_lot_id"],
            # 필수 필드도 공백을 턴다. 원천이 고정폭 CHAR 이면 "CC002000 " 이 섞여 들어와
            # commonality 가 같은 스텝(같은 설비)을 두 군으로 쪼갠다 — 에러 없이 신호만 반토막.
            "step_seq": str(r["step_seq"]).strip(),
            # area = 그 스텝의 공정명. 분석 축은 step_seq 이고 area 는 사람이 "이 스텝이
            # 무슨 공정인가" 를 확인할 때만 본다. 원천이 아직 안 실어 줘도 되게 NULL 허용.
            "area": _text(r.get("area")),
            "eqp_id": str(r["eqp_id"]).strip(),
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
    step_seq     TEXT,               -- 항상 NULL (정답 누출 방지, 컬럼만 호환 유지)
    date         TEXT NOT NULL,
    root_lot_id  TEXT NOT NULL,
    lot_type     TEXT NOT NULL       -- 필터가 아니라 해석용 컨텍스트
);

CREATE TABLE step_history (
    wafer_id     TEXT NOT NULL,      -- 합성 조인 키
    root_lot_id  TEXT NOT NULL,      -- lot 단위 증분 삭제의 키 (wafer_id 접두와 같은 값)
    step_seq     TEXT NOT NULL,      -- 제품군 2자리 + 순서 6자리 (+ 비정규 스텝이면 "EC")
    area         TEXT,               -- 그 스텝의 공정명 (NULL 허용, 해석용)
    eqp_id       TEXT NOT NULL,
    ch_id        TEXT,               -- NULL 허용
    ppid         TEXT,               -- NULL 허용 (2차 legend: hyp_ppid_commonality)
    timestamp    TEXT
);
"""

# 인덱스는 적재 **후에** 만든다 (적재 중 인덱스 유지 비용 회피)
INDEXES = """
CREATE INDEX idx_step_wafer ON step_history(wafer_id);
CREATE INDEX idx_step_step  ON step_history(step_seq);
CREATE INDEX idx_step_root  ON step_history(root_lot_id);
CREATE INDEX idx_yield_root ON yield(root_lot_id);
"""


# 적재 SQL — rebuild 와 증분이 같은 문을 쓴다 (한쪽만 고치면 컬럼이 조용히 갈린다)
YIELD_INSERT = """
    INSERT INTO yield (wafer_id, lot_id, yield, defect_type, step_seq,
                       date, root_lot_id, lot_type)
    VALUES (:wafer_id, :lot_id, :yield, :defect_type, :step_seq,
            :date, :root_lot_id, :lot_type)"""

STEP_INSERT = """
    INSERT INTO step_history (wafer_id, root_lot_id, step_seq, area, eqp_id,
                              ch_id, ppid, timestamp)
    VALUES (:wafer_id, :root_lot_id, :step_seq, :area, :eqp_id,
            :ch_id, :ppid, :timestamp)"""


def _chunked(seq, size: int):
    """리스트를 size 개씩 자른다. 마지막 조각은 짧을 수 있다.

    lot 목록을 이 단위로 잘라 `_extract()` 를 여러 번 부른다. 청크가 끝나면 그
    DataFrame 과 dict 리스트가 참조를 잃고 해제되므로 메모리가 청크 하나 크기로
    유계가 된다.
    """
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


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


def rebuild(batches, db_path: Path, verbose: bool = True, force: bool = False) -> dict:
    """전체 재적재. 임시 파일에 만들고 검증 통과 시에만 원자적 교체.

    batches: `(yield_records, step_records)` 튜플의 반복자. 호출부가 lot 청크마다
             하나씩 흘려보내면 전량을 메모리에 들지 않는다.

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
        conn.execute("PRAGMA synchronous=OFF")       # (증분 경로에서는 쓰면 안 된다)
        conn.executescript(DDL)

        n_y = n_s = 0
        for yield_records, step_records in batches:
            n_y += _insert_batched(conn, YIELD_INSERT, transform_yield(yield_records))
            n_s += _insert_batched(conn, STEP_INSERT, transform_steps(step_records))

        conn.executescript(INDEXES)                  # 인덱스는 적재 후에 만든다
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


def load(yield_records, step_records, db_path: Path,
         verbose: bool = True, force: bool = False) -> dict:
    """배치 1개짜리 rebuild. 기존 호출부와 테스트가 쓰는 계약을 그대로 둔다."""
    return rebuild([(yield_records, step_records)], db_path,
                   verbose=verbose, force=force)


def load_incremental(chunks, db_path: Path, verbose: bool = True,
                     force: bool = False) -> dict:
    """살아 있는 DB 에 lot 단위로 삭제 후 삽입. 실행 전체가 트랜잭션 하나다.

    chunks: `(root_lots, yield_records, step_records)` 튜플의 반복자.
            청크마다 그 lot 들을 지우고 다시 넣으므로 몇 번을 돌려도 결과가 같다.

    ⚠️ 여기서는 journal_mode 를 끄지 않는다. 끄면 롤백 자체가 불가능해져서
       "실패하면 되돌아간다" 는 전제가 조용히 깨진다. rebuild 의 PRAGMA 두 줄은
       tmp 파일에 새로 만드는 경우 전용이다.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path)
    conn.isolation_level = None          # 트랜잭션 경계를 이 함수가 직접 잡는다
    lots, n_y, n_s, del_y, del_s = [], 0, 0, 0, 0
    try:
        conn.execute("BEGIN")
        for root_lots, yield_records, step_records in chunks:
            root_lots = list(root_lots)
            ph = ",".join("?" * len(root_lots))
            del_s += conn.execute(
                f"DELETE FROM step_history WHERE root_lot_id IN ({ph})",
                root_lots).rowcount
            del_y += conn.execute(
                f"DELETE FROM yield WHERE root_lot_id IN ({ph})",
                root_lots).rowcount
            n_y += _insert_batched(conn, YIELD_INSERT, transform_yield(yield_records))
            n_s += _insert_batched(conn, STEP_INSERT, transform_steps(step_records))
            lots.extend(root_lots)
        report = validate(conn, n_y, n_s, root_lots=lots)
    except BaseException:
        conn.execute("ROLLBACK")         # 추출 실패·중단·스키마 위반 전부 여기로
        conn.close()
        raise

    committed = force or not report["fatal"]
    conn.execute("COMMIT" if committed else "ROLLBACK")
    conn.close()

    report.update(committed=committed, db_path=str(db_path), n_lots=len(lots),
                  n_deleted_yield=del_y, n_deleted_steps=del_s)
    if verbose:
        _print(report)
    return report


# --------------------------------------------------------------------------- #
# 적재 후 정합성 검사
# --------------------------------------------------------------------------- #
_WID = re.compile(r"^.+_\d{2}$")
# 제품군 2자리 + 스텝 순서 6자리. 사내에 문자3+숫자5 체계도 있으나 이 팀은 안 쓴다 —
# 그 체계를 쓰는 데이터를 받게 되면 이 정규식부터 넓힐 것.
# 접미 `EC` 는 **비정규 스텝** 표시다("AA110000EC"). 정상적으로 실려 오는 값이므로
# 형식 위반이 아니다. 접미가 붙은 값은 commonality 에서 **별개 스텝 키**가 된다.
_STEP_SEQ = re.compile(r"^[A-Z]{2}\d{6}(EC)?$")


def _in_scope(alias: str = "") -> str:
    """검사 범위 조건절. alias 는 조인 질의에서 테이블 별칭("s"/"y")."""
    p = f"{alias}." if alias else ""
    return f"{p}root_lot_id IN (SELECT root_lot_id FROM _scope)"


def validate(conn: sqlite3.Connection, n_yield: int, n_steps: int,
             root_lots=None) -> dict:
    """적재 후 정합성 검사.

    root_lots 를 주면 그 lot 으로 모든 검사를 좁힌다(증분). None 이면 전역(rebuild).

    범위를 좁히는 이유는 성능만이 아니다. 고아 비율을 전역으로 재면 이번에 들어온
    lot 이 통째로 깨져 있어도 기존 2,800만 행이 희석해 비율이 0.001 로 나온다.
    안전장치가 있는데 아무것도 못 막는다.
    """
    conn.row_factory = sqlite3.Row
    q = lambda sql, *a: conn.execute(sql, a).fetchall()
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]

    # 검사 범위. 전역일 때는 yield 와 step_history 양쪽의 root_lot 을 다 넣는다 -
    # yield 에 아예 없는 lot 의 고아 행을 범위 밖으로 밀어내면 안 되기 때문이다.
    conn.execute("DROP TABLE IF EXISTS temp._scope")
    conn.execute("CREATE TEMP TABLE _scope (root_lot_id TEXT PRIMARY KEY)")
    if root_lots is None:
        conn.execute("INSERT INTO _scope SELECT root_lot_id FROM yield "
                     "UNION SELECT root_lot_id FROM step_history")
    else:
        conn.executemany("INSERT OR IGNORE INTO _scope VALUES (?)",
                         [(x,) for x in root_lots])

    # fatal = 교체 차단 (이 상태로 갈아끼우면 기존 DB 보다 나쁘다)
    # warn  = 교체는 하되 사람이 봐야 하는 것
    fatal, issues = [], []

    # 0. 빈 추출 — 그대로 교체하면 멀쩡한 DB 를 빈 DB 로 덮어쓴다
    if n_yield == 0:
        fatal.append("yield 0행: 추출 결과가 비었다 (교체 중단)")

    # 1. 조인 키 형식 (…_NN)
    bad = [r["wafer_id"] for r in
           q(f"SELECT wafer_id FROM yield WHERE {_in_scope()}")
           if not _WID.match(r["wafer_id"])]
    if bad:
        fatal.append(f"wafer_id 형식 위반 {len(bad)}건 (예: {bad[:3]})")

    # 2. wafer_id 접두 == root_lot_id 교차검증
    mism = q(f"""SELECT wafer_id FROM yield
                 WHERE wafer_id <> root_lot_id || '_' || substr(wafer_id, -2)
                   AND {_in_scope()}""")
    if mism:
        fatal.append(f"root_lot_id 불일치 {len(mism)}건 "
                     f"(예: {[r['wafer_id'] for r in mism[:3]]})")

    # 2-1. step_seq 형식 — 원천에서 step_seq 와 area 가 뒤바뀌어 실려도 적재는 통과하고,
    #      공정명("Etch")으로 묶인 후보가 그럴듯하게 나온다. 그 사고를 잡는다.
    #      자릿수 관행이 제품군마다 다를 수 있으므로 경고에 그친다 (교체는 막지 않는다).
    bad_seq = [r["step_seq"] for r in
               q(f"SELECT DISTINCT step_seq FROM step_history WHERE {_in_scope()}")
               if not _STEP_SEQ.match(r["step_seq"])]
    if bad_seq:
        issues.append(f"step_seq 형식 위반 {len(bad_seq)}종 (예: {bad_seq[:3]}): "
                      f"기대 형식은 제품군 2자리 + 순번 6자리('CC001000') 이고 "
                      f"비정규 스텝이면 뒤에 'EC' 가 붙는다('AA110000EC'). "
                      f"area 컬럼과 뒤바뀌지 않았는지 확인")

    # 3. step_history 고아 (이력엔 있으나 yield 에 없는 wafer) — 조인 키 불일치의 주 증상
    # 소수면 경고지만, 대부분이 고아면 조인 키 자체가 어긋난 것이므로 교체를 막는다
    n_hist_wafers = one(f"SELECT COUNT(DISTINCT wafer_id) FROM step_history "
                        f"WHERE {_in_scope()}")
    orphan = q(f"""SELECT DISTINCT s.wafer_id FROM step_history s
                   LEFT JOIN yield y ON y.wafer_id = s.wafer_id
                   WHERE y.wafer_id IS NULL AND {_in_scope('s')}""")
    if orphan:
        msg = (f"step_history 고아 wafer {len(orphan)}/{n_hist_wafers}건 "
               f"(예: {[r['wafer_id'] for r in orphan[:3]]}): 조인 키 불일치 의심")
        (fatal if len(orphan) > n_hist_wafers * ORPHAN_FATAL_RATE else issues).append(msg)

    # 4. 이력 없는 wafer — commonality 가 분모에서 제외하므로 표본이 조용히 줄어든다.
    #    대부분이 이력 없으면 1단이 아예 못 돌므로 교체를 막는다.
    no_hist = q(f"""SELECT y.wafer_id FROM yield y
                    LEFT JOIN step_history s ON s.wafer_id = y.wafer_id
                    WHERE s.wafer_id IS NULL AND {_in_scope('y')}""")
    if no_hist:
        msg = (f"step_history 없는 wafer {len(no_hist)}/{n_yield}건 "
               f"(예: {[r['wafer_id'] for r in no_hist[:3]]}): commonality 분모에서 빠짐")
        (fatal if len(no_hist) > n_yield * NO_HISTORY_FATAL_RATE else issues).append(msg)

    # 5. yield 범위
    oor = one(f"SELECT COUNT(*) FROM yield "
              f"WHERE (yield < 0 OR yield > 100) AND {_in_scope()}")
    if oor:
        issues.append(f"yield 범위(0~100) 이탈 {oor}건")

    # 6. 중복 이력 (같은 wafer×스텝이 여러 번) — 정상일 수도(재작업), 확인 필요
    dup = one(f"""SELECT COUNT(*) FROM (SELECT wafer_id, step_seq
                  FROM step_history WHERE {_in_scope()}
                  GROUP BY 1,2 HAVING COUNT(*) > 1)""")
    if dup:
        issues.append(f"wafer×스텝 중복 이력 {dup}건: 재작업(rework)인지 확인 필요")

    # 7번(ppid grain 진단)은 2026-08-03 에 **삭제**했다. 다시 만들지 말 것.
    #    "설비·챔버는 wafer 마다 갈리는데 ppid 는 한 번도 안 갈린다" 를 lot×스텝 군에서
    #    세는 검사였는데, 판별력이 없다 — lot 안에서 ppid 가 안 갈리는 것은 도메인상
    #    **정상**이기 때문이다(같은 root_lot 을 PPID 시험용으로 나눌 때만 갈린다).
    #    lot 마스터 조인이든 lot×스텝 마스터 조인이든 정상이든 세 경우가 이 지표에서
    #    같은 모양이라, 실데이터에서 사람을 틀린 판단으로 이끌었다(2026-08-03).
    #    조인 단위는 원천 추출 쿼리를 사람이 보는 수밖에 없다 — 점검표 1장이 그 항목을
    #    사람 확인 사항으로 들고 있다.

    lot_types = {r["lot_type"]: r["c"] for r in
                 q(f"SELECT lot_type, COUNT(*) c FROM yield "
                   f"WHERE {_in_scope()} GROUP BY 1")}
    if lot_types.get(PROD, 0) == 0:
        issues.append(f"양산({PROD}) lot 0건: classify_lot_type 규칙 확인 필요")

    steps = q(f"""SELECT MIN(c) lo, MAX(c) hi, AVG(c) avg FROM
                  (SELECT COUNT(*) c FROM step_history WHERE {_in_scope()}
                   GROUP BY wafer_id)""")
    s = steps[0] if steps and steps[0]["lo"] is not None else None

    return {
        "n_yield": n_yield, "n_steps": n_steps,
        "n_wafers_with_history": n_hist_wafers,
        "n_root_lots": one(f"SELECT COUNT(DISTINCT root_lot_id) FROM yield "
                           f"WHERE {_in_scope()}"),
        # 전역 규모 - 검사 대상이 아니라 사람이 "지금 DB 가 얼마나 큰가" 를 보는 값
        "n_total_yield": one("SELECT COUNT(*) FROM yield"),
        "n_total_steps": one("SELECT COUNT(*) FROM step_history"),
        "n_total_root_lots": one("SELECT COUNT(DISTINCT root_lot_id) FROM yield"),
        "lot_types": lot_types,
        "defect_labeled": one(f"SELECT COUNT(*) FROM yield "
                              f"WHERE defect_type IS NOT NULL AND {_in_scope()}"),
        "steps_per_wafer": ({"min": s["lo"], "max": s["hi"], "avg": round(s["avg"], 1)}
                            if s else None),
        # area 결측률 — step_seq 는 순번 코드라 그 자체로는 무슨 공정인지 안 보인다.
        # 주의: **리포트는 area 를 싣지 않는다** (읽는 코드가 아직 없다 — commonality 의
        # SELECT 에도 legend 에도 없다). 그래서 이 값이 0.0 이어도 리포트의 스텝은
        # `CC002000` 뿐이다. area 는 사람이 DB 를 직접 조회할 때 쓴다.
        "area_null_rate": round(
            one(f"SELECT COUNT(*) FROM step_history "
                f"WHERE area IS NULL AND {_in_scope()}") / max(n_steps, 1), 3),
        # ch_id 결측률 — 높으면 commonality 가 챔버 레벨을 거의 못 쓴다(설비 레벨만 남음)
        "ch_id_null_rate": round(
            one(f"SELECT COUNT(*) FROM step_history "
                f"WHERE ch_id IS NULL AND {_in_scope()}") / max(n_steps, 1), 3),
        # ppid 결측률 — 전부 NULL 이면 hyp_ppid_commonality 가 **에러 없이 후보 0** 으로
        # 끝난다. 이 값이 없으면 "PPID 로도 안 갈린다" 와 "PPID 가 안 실렸다" 를 구분 못 한다.
        "ppid_null_rate": round(
            one(f"SELECT COUNT(*) FROM step_history "
                f"WHERE ppid IS NULL AND {_in_scope()}") / max(n_steps, 1), 3),
        "fatal": fatal,
        "issues": issues,
    }


def _print(r: dict) -> None:
    _say(f"[적재] yield {r['n_yield']}행 / step_history {r['n_steps']}행")
    if "n_lots" in r:                       # 증분에서만
        _say(f"[증분] 대상 lot {r['n_lots']}개 · 삭제 yield {r['n_deleted_yield']}행"
             f" / step_history {r['n_deleted_steps']}행")
        _say(f"[전체] yield {r['n_total_yield']}행 / step_history "
             f"{r['n_total_steps']}행 · root_lot {r['n_total_root_lots']}개")
    _say(f"[구성] root_lot {r['n_root_lots']}개 · 이력 보유 wafer {r['n_wafers_with_history']}장 "
         f"· lot_type {r['lot_types']}")
    _say(f"[이력] wafer 당 스텝 {r['steps_per_wafer']} · ch_id 결측률 {r['ch_id_null_rate']}"
         f" · ppid 결측률 {r['ppid_null_rate']} · area 결측률 {r['area_null_rate']}")
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
    if "n_lots" in r:
        _say(f"[커밋] {r['db_path']} 갱신 완료" if r.get("committed")
             else f"[되돌림] {r['db_path']} 는 기존 상태 유지 (--force 로 무시 가능)")
    elif r.get("swapped"):
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
    ap.add_argument("--db", default=str(ya_config.DB_PATH),
                    help=f"적재 대상 DB (기본 {ya_config.DB_PATH}: 더미와 동일, 덮어씀 주의)")
    ap.add_argument("--force", action="store_true",
                    help="치명적 정합성 오류가 있어도 기존 DB 를 교체한다")
    args = ap.parse_args()

    db = Path(args.db)
    if db == Path(ya_config.DB_PATH):
        _say(f"[주의] {db} 는 더미 DB 와 같은 경로입니다. 기존 내용이 대체됩니다.")

    yield_records, step_records = _extract()
    report = load(yield_records, step_records, db, force=args.force)
    raise SystemExit(0 if report["swapped"] else 1)


if __name__ == "__main__":
    main()