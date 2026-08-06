# step_history 증분 적재 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매일 root_lot 단위로 증분 적재해서, 지금 수십 분 + 메모리 32GB 를 쓰는 전체 재적재를 일상 경로에서 걷어낸다.

**Architecture:** `data/load_internal.py` 에 적재 함수를 두 개로 나눈다. `rebuild()` 는 지금처럼 tmp DB 를 만들어 원자적으로 교체하고, `load_incremental()` 은 살아 있는 DB 에 lot 단위로 삭제 후 삽입하며 전체를 트랜잭션 하나로 묶는다. 둘 다 배치(청크)를 반복자로 받아서 호출부가 2,800만 행을 한꺼번에 메모리에 들지 않게 한다. 검증은 이번 배치의 lot 으로 범위를 좁힌다.

**Tech Stack:** Python 3, sqlite3(표준 라이브러리), argparse, pytest. 새 의존성 없음.

## Global Constraints

- **설계 원본은 `docs/superpowers/specs/2026-08-06-incremental-load-design.md`.** 판단이 갈리면 그 문서가 기준이다.
- **회귀 기준선은 201 passed.** 각 Task 끝에서 `python -m pytest -q` 가 이 수 이상으로 통과해야 한다. (`pytest` 가 PATH 에 없을 수 있으므로 반드시 `python -m pytest` 로 부른다.)
- **출력 리터럴에 em-dash(U+2014)를 쓰지 않는다.** 콘솔이 cp949 라 `?` 로 깨진다. argparse 의 `help`/`description` 은 `say()` 가 못 덮으므로 cp949 밖 글자를 넣으면 `--help` 자체가 죽는다.
- **사용자 출력은 `ya_console.say`(`_say`)로 한다.** `print` 직접 호출 금지.
- **주석과 문구는 한국어.** 기존 파일의 서술 밀도와 어조를 따른다.
- **더미 DB(`data/yield.db`)는 gitignore 대상이다.** 스키마를 바꾸면 `python data/generate_dummy.py` 로 재생성해야 `test_schema_contract.py` 가 통과한다(그 테스트는 소스가 아니라 **DB 파일**을 읽는다).
- **변이 확인을 필수로 한다.** 각 Task 의 마지막 단계에 명시된 변이를 실제로 넣어보고 지정된 테스트가 **단독으로** 죽는지 확인한 뒤 되돌린다.
- **시작 전 워킹 트리를 정리한다.** `llm/client.py`·`ya_config.py` 에 사내 LLM 헤더 인증 관련 커밋 안 된 변경이 있다. 이 작업이 `ya_config.py` 를 건드리므로, 먼저 그 변경을 커밋하거나 `git stash` 로 치워두고 시작한다.

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `data/load_internal.py` | 사내 추출 결과의 변환·적재·검증 (전체 재적재 + 증분) | 대부분 |
| `data/generate_dummy.py` | 더미 DB 생성 | `_write_sqlite` 만 |
| `ya_config.py` | 설정 | 2줄 추가 |
| `tests/test_load_internal.py` | 적재 왕복·증분 동작 | 테스트 추가 |
| `docs/사내-투입-점검표.md` | 사내 실행 절차 | 3-1 갱신 + 매일 적재 절 추가 |
| `README.md` | 적재 예시 | 명령 갱신 |
| `docs/사내-데이터-변환시-할일.md` | 사내 연결 항목 | `_extract` 계약 갱신 |

새 파일은 만들지 않는다. `load_internal.py` 가 465줄에서 600줄 안팎으로 늘지만 책임은 하나(적재)이고, 이 저장소는 적재 경로를 한 모듈에 두는 방식을 유지해 왔다.

---

### Task 1: `step_history` 에 `root_lot_id` 추가

lot 단위 삭제의 키다. 이게 없으면 `wafer_id LIKE 'A45Z5\_%'` 로 긁어야 하는데 2,800만 행에서 인덱스를 못 타고, `yield` 를 거쳐 지우면 lot 의 wafer 구성이 바뀌었을 때 지워지지 않은 행이 남는다.

**Files:**
- Modify: `data/load_internal.py` (DDL, INDEXES, `transform_steps`, step INSERT)
- Modify: `data/generate_dummy.py:538-551` (`_write_sqlite` 의 step_history DDL·INSERT)
- Test: `tests/test_load_internal.py`

**Interfaces:**
- Consumes: 없음 (첫 Task)
- Produces: `step_history.root_lot_id` 컬럼과 `idx_step_root` 인덱스. Task 3·4 의 lot 단위 삭제와 검증 범위 좁히기가 이걸 쓴다. `transform_steps(records)` 가 내는 dict 에 `"root_lot_id"` 키가 추가된다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_load_internal.py` 의 `test_step_columns_survive_the_write_path` 바로 아래에 추가한다.

```python
def test_root_lot_id_survives_the_write_path(tmp_path):
    """lot 단위 삭제의 키다. DDL 에만 있고 INSERT 에서 빠지면 NOT NULL 위반으로
    적재가 죽거나(운이 좋으면), 조용히 틀린 lot 이 실린다."""
    db, _ = _load(tmp_path)
    conn = sqlite3.connect(db)
    rows = conn.execute("""SELECT DISTINCT wafer_id, root_lot_id FROM step_history
                           ORDER BY wafer_id""").fetchall()
    conn.close()
    assert rows == [("A45Z5_01", "A45Z5"), ("A45Z5_02", "A45Z5")]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_load_internal.py::test_root_lot_id_survives_the_write_path -v`
Expected: FAIL - `sqlite3.OperationalError: no such column: root_lot_id`

- [ ] **Step 3: 사내 적재 스키마에 컬럼을 넣는다**

`data/load_internal.py` 의 `DDL` 상수에서 `step_history` 정의를 바꾼다.

```python
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
```

`INDEXES` 상수에 한 줄 추가한다.

```python
INDEXES = """
CREATE INDEX idx_step_wafer ON step_history(wafer_id);
CREATE INDEX idx_step_step  ON step_history(step_seq);
CREATE INDEX idx_step_root  ON step_history(root_lot_id);
CREATE INDEX idx_yield_root ON yield(root_lot_id);
"""
```

`transform_steps` 의 반환 dict 첫 줄 다음에 추가한다.

```python
def transform_steps(records):
    for r in records:
        yield {
            "wafer_id": build_wafer_id(r["root_lot_id"], _wafer_no(r)),
            # 증분 적재가 lot 단위로 지우고 다시 넣을 때 쓰는 키. wafer_id 접두와 같은
            # 값이지만 문자열을 쪼개 쓰면 인덱스를 못 타므로 컬럼으로 둔다.
            "root_lot_id": r["root_lot_id"],
            "step_seq": str(r["step_seq"]).strip(),
            # (이하 기존과 동일)
```

- [ ] **Step 4: INSERT 문을 모듈 상수로 뽑고 컬럼을 추가한다**

Task 2·3 이 같은 INSERT 를 쓰므로 지금 상수로 뽑아둔다. `_insert_batched` 정의 바로 위에 넣는다.

```python
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
```

그리고 `load()` 안의 두 `_insert_batched` 호출을 이 상수로 바꾼다.

```python
        n_y = _insert_batched(conn, YIELD_INSERT, transform_yield(yield_records))
        n_s = _insert_batched(conn, STEP_INSERT, transform_steps(step_records))
```

- [ ] **Step 5: 더미 스키마도 맞춘다**

`data/generate_dummy.py` 의 `_write_sqlite` 에서 step_history 부분을 바꾼다. 스텝 생성기 4개는 건드리지 않는다 (난수열이 흔들리면 기존 케이스가 전부 바뀐다). 대신 `yield` 행에서 매핑을 만들어 채운다.

```python
    conn.execute("""
        CREATE TABLE step_history (
            wafer_id     TEXT NOT NULL,
            root_lot_id  TEXT NOT NULL,
            step_seq     TEXT NOT NULL,
            area         TEXT,
            eqp_id       TEXT NOT NULL,
            ch_id        TEXT,
            ppid         TEXT,
            timestamp    TEXT
        )
    """)
    # 스텝 생성기들은 wafer_id 만 만든다. root_lot 은 yield 행이 이미 알고 있으므로
    # 여기서 매핑한다 - 생성기 4개를 고치면 난수열이 흔들려 기존 케이스가 바뀐다.
    # yield 에 없는 wafer 의 이력이 있으면 KeyError 로 즉시 드러난다 (조용한 NULL 금지).
    root_of = {r["wafer_id"]: r["root_lot_id"] for r in rows}
    for s in steps:
        s["root_lot_id"] = root_of[s["wafer_id"]]
    conn.executemany(
        """INSERT INTO step_history VALUES
           (:wafer_id, :root_lot_id, :step_seq, :area, :eqp_id, :ch_id, :ppid,
            :timestamp)""", steps)
```

- [ ] **Step 6: 더미 DB 를 재생성한다**

Run: `python data/generate_dummy.py`
Expected: 정상 종료. `test_schema_contract.py` 는 소스가 아니라 이 DB 파일을 읽으므로, 재생성하지 않으면 계약 테스트가 계속 실패한다.

- [ ] **Step 7: 전체 테스트**

Run: `python -m pytest -q`
Expected: 202 passed (기존 201 + 신규 1)

- [ ] **Step 8: 변이 확인**

`transform_steps` 에서 `"root_lot_id": r["root_lot_id"],` 줄을 지운다.
Run: `python -m pytest tests/test_load_internal.py -q`
Expected: 새 테스트가 죽는다 (NOT NULL 위반). 확인 후 되돌린다.

- [ ] **Step 9: 커밋**

```bash
git add data/load_internal.py data/generate_dummy.py tests/test_load_internal.py
git commit -m "feat(load): step_history 에 root_lot_id 를 싣는다 (lot 단위 증분의 키)"
```

---

### Task 2: 배치를 나눠 받는 `rebuild()`

전체 재적재도 청크로 돌게 만든다. 지금은 호출부가 `to_dict()` 로 2,800만 개 dict 를 만들어 통째로 넘기고, 그 리스트가 적재 내내 살아 있어 메모리가 32GB 까지 오른다.

**Files:**
- Modify: `data/load_internal.py:209-276` (`_insert_batched` 아래 ~ `load` 끝)
- Test: `tests/test_load_internal.py`

**Interfaces:**
- Consumes: Task 1 의 `YIELD_INSERT` / `STEP_INSERT` 상수
- Produces:
  - `_chunked(seq: list, size: int) -> Iterator[list]`
  - `rebuild(batches, db_path, verbose=True, force=False) -> dict` — `batches` 는 `(yield_records, step_records)` 튜플의 반복자. 반환 dict 는 지금 `load()` 가 내던 것과 같다(`swapped`·`db_path` 포함).
  - `load(yield_records, step_records, db_path, verbose=True, force=False) -> dict` — 기존 시그니처 유지. 배치 1개짜리 `rebuild` 호출로 바뀐다. Task 3·4 의 테스트가 이걸로 DB 를 준비한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_load_internal.py` 맨 아래에 추가한다.

```python
def test_rebuild_takes_batches_so_the_caller_need_not_hold_everything(tmp_path):
    """전체 재적재도 청크로 받는다. 호출부가 2,800만 행을 한 리스트로 들면
    적재 내내 그 리스트가 살아 있어 메모리가 32GB 까지 오른다(사내 실측)."""
    b1 = ([YIELDS[0]], [STEPS[0]])
    b2 = ([YIELDS[1]], [STEPS[1], STEPS[2]])
    report = li.rebuild([b1, b2], tmp_path / "t.db", verbose=False)

    assert report["n_yield"] == 2 and report["n_steps"] == 3
    assert report["swapped"] and not report["fatal"]


def test_chunked_splits_a_lot_list_into_fixed_size_pieces():
    assert [len(c) for c in li._chunked(list(range(45)), 20)] == [20, 20, 5]
    assert list(li._chunked([], 20)) == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_load_internal.py -k "rebuild_takes_batches or chunked_splits" -v`
Expected: FAIL - `AttributeError: module 'data.load_internal' has no attribute 'rebuild'`

- [ ] **Step 3: `_chunked` 를 만든다**

`data/load_internal.py` 의 `_insert_batched` 위에 넣는다.

```python
def _chunked(seq, size: int):
    """리스트를 size 개씩 자른다. 마지막 조각은 짧을 수 있다.

    lot 목록을 이 단위로 잘라 `_extract()` 를 여러 번 부른다. 청크가 끝나면 그
    DataFrame 과 dict 리스트가 참조를 잃고 해제되므로 메모리가 청크 하나 크기로
    유계가 된다.
    """
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
```

- [ ] **Step 4: `load()` 를 `rebuild()` 로 바꾸고 얇은 래퍼를 남긴다**

기존 `load()` 본문 전체를 `rebuild()` 로 옮기고, 삽입 부분만 배치 순회로 바꾼다. 나머지(tmp 경로, PRAGMA, DDL, 인덱스, 검증, os.replace, `_print`)는 그대로 둔다.

```python
def rebuild(batches, db_path, verbose: bool = True, force: bool = False) -> dict:
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
        conn.execute("PRAGMA journal_mode=OFF")      # 초기 벌크 적재 - 복구 필요 없음
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


def load(yield_records, step_records, db_path, verbose: bool = True,
         force: bool = False) -> dict:
    """배치 1개짜리 rebuild. 기존 호출부와 테스트가 쓰는 계약을 그대로 둔다."""
    return rebuild([(yield_records, step_records)], db_path,
                   verbose=verbose, force=force)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/test_load_internal.py -v`
Expected: 전부 PASS. 기존 왕복 테스트 8개가 `load()` 를 그대로 부르므로 여기서 계약 유지가 확인된다.

- [ ] **Step 6: 전체 테스트**

Run: `python -m pytest -q`
Expected: 204 passed

- [ ] **Step 7: 커밋**

```bash
git add data/load_internal.py tests/test_load_internal.py
git commit -m "refactor(load): 전체 재적재를 배치 반복자로 받게 한다 (메모리 유계)"
```

---

### Task 3: 멱등 증분 적재와 롤백

lot 단위로 지우고 다시 넣는다. 재작업 이력이 뒤달려 붙으므로, 같은 lot 을 다시 넣어도 결과가 같아야 한다. 그냥 INSERT 하면 이력이 두 벌로 쌓이고 commonality 는 에러 없이 분모가 두 배가 된 채 계산한다.

**Files:**
- Modify: `data/load_internal.py` (`rebuild` 아래에 추가)
- Test: `tests/test_load_internal.py`

**Interfaces:**
- Consumes: Task 1 의 `root_lot_id` 컬럼, Task 2 의 `YIELD_INSERT`/`STEP_INSERT`/`load()`
- Produces: `load_incremental(chunks, db_path, verbose=True, force=False) -> dict`
  - `chunks`: `(root_lots: list[str], yield_records, step_records)` 튜플의 반복자
  - 반환 dict: `validate()` 의 키에 더해 `committed: bool`, `db_path: str`, `n_lots: int`, `n_deleted_yield: int`, `n_deleted_steps: int`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_load_internal.py` 맨 아래에 추가한다.

```python
def _counts(db):
    conn = sqlite3.connect(db)
    try:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("yield", "step_history"))
    finally:
        conn.close()


def _seed(tmp_path):
    """A45Z5 lot 이 이미 적재된 DB."""
    db = tmp_path / "t.db"
    li.load(YIELDS, STEPS, db, verbose=False)
    return db


def test_reloading_the_same_lot_does_not_duplicate_rows(tmp_path):
    """멱등성. 그냥 INSERT 하면 이력이 두 벌이 되고 commonality 는 에러 없이
    분모가 두 배가 된 채 계산한다 - 재작업 행과 구분이 안 돼 눈에도 안 띈다."""
    db = _seed(tmp_path)
    before = _counts(db)

    report = li.load_incremental([(["A45Z5"], YIELDS, STEPS)], db, verbose=False)

    assert _counts(db) == before
    assert report["committed"] and not report["fatal"]


def test_rework_history_replaces_the_old_rows(tmp_path):
    """재작업으로 이력이 늘면 새 내용으로 통째로 대체된다."""
    db = _seed(tmp_path)
    reworked = STEPS + [{"root_lot_id": "A45Z5", "wafer_id": "01",
                         "step_seq": "CC002000", "area": "Etch", "eqp_id": "ETCH9",
                         "ch_id": "C", "ppid": "PPID_R", "timestamp": "t2"}]

    li.load_incremental([(["A45Z5"], YIELDS, reworked)], db, verbose=False)

    assert _counts(db) == (2, 4)          # 옛 3행이 남으면 7


def test_a_failure_mid_load_leaves_the_db_untouched(tmp_path):
    """추출이 중간에 죽어도 어제 상태로 돌아가야 한다.

    전체 재적재는 tmp 파일 + os.replace 가 이걸 보장했다. 증분은 살아 있는 DB 를
    고치므로 그 보장을 트랜잭션이 대신한다.
    """
    db = _seed(tmp_path)
    before = _counts(db)

    def dying_chunks():
        yield (["A45Z5"], YIELDS, STEPS)      # 한 청크는 적용된 뒤
        raise RuntimeError("추출 중단")

    try:
        li.load_incremental(dying_chunks(), db, verbose=False)
    except RuntimeError:
        pass
    else:
        raise AssertionError("예외가 전파되지 않았다")

    assert _counts(db) == before
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_load_internal.py -k "reloading_the_same_lot or rework_history or failure_mid_load" -v`
Expected: FAIL - `AttributeError: module 'data.load_internal' has no attribute 'load_incremental'`

- [ ] **Step 3: `load_incremental` 을 구현한다**

`rebuild()` 와 `load()` 아래에 넣는다.

```python
def load_incremental(chunks, db_path, verbose: bool = True,
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
        report = validate(conn, n_y, n_s)
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_load_internal.py -v`
Expected: 전부 PASS

- [ ] **Step 5: 전체 테스트**

Run: `python -m pytest -q`
Expected: 207 passed

- [ ] **Step 6: 변이 확인 (2개)**

1. 두 `DELETE` 를 지운다 → `test_reloading_the_same_lot_does_not_duplicate_rows` 와 `test_rework_history_replaces_the_old_rows` 가 죽어야 한다. 되돌린다.
2. `except BaseException` 의 `conn.execute("ROLLBACK")` 를 `conn.execute("COMMIT")` 으로 바꾼다 → `test_a_failure_mid_load_leaves_the_db_untouched` 가 죽어야 한다. 되돌린다.

- [ ] **Step 7: 커밋**

```bash
git add data/load_internal.py tests/test_load_internal.py
git commit -m "feat(load): lot 단위 멱등 증분 적재 (단일 트랜잭션, 실패 시 롤백)"
```

---

### Task 4: 검증 범위를 이번 배치로 좁힌다

성능 때문만이 아니다. 고아 비율을 전역으로 재면 이번에 들어온 lot 23개가 통째로 깨져 있어도 기존 2,800만 행이 희석해 비율이 0.001 로 나온다. 안전장치가 있는데 아무것도 못 막는다.

**Files:**
- Modify: `data/load_internal.py:290-403` (`validate`)
- Modify: `data/load_internal.py` (`_print` 에 전체 규모 줄 추가)
- Test: `tests/test_load_internal.py`

**Interfaces:**
- Consumes: Task 3 의 `load_incremental`
- Produces: `validate(conn, n_yield, n_steps, root_lots=None) -> dict`
  - `root_lots=None` 이면 전역(rebuild 용, 지금 동작 그대로)
  - 리스트를 주면 그 lot 들로 모든 검사를 좁힌다
  - 반환 dict 에 `n_total_yield`·`n_total_steps`·`n_total_root_lots`(전역 규모, 보고용) 추가

- [ ] **Step 1: 실패하는 테스트를 쓴다**

양방향으로 잠근다. 한쪽만 쓰면 "항상 통과" 나 "항상 차단" 구현이 통과해 버린다.

```python
B_YIELDS = [{"root_lot_id": "B77B7", "wafer_id": "01", "lot_id": "B77B7.1",
             "lot_type": "PP", "yield": 88.0, "date": "2026-08-01"}]
B_STEPS = [{"root_lot_id": "B77B7", "wafer_id": "01", "step_seq": "CC002000",
            "eqp_id": "ETCH9", "timestamp": "t"}]


def test_a_broken_batch_is_blocked_even_though_the_db_is_mostly_clean(tmp_path):
    """이번 배치의 고아를 전역 비율로 재면 기존 데이터가 희석해 못 잡는다.

    아래 배치는 wafer 3장 중 2장이 고아(yield 없음)라 그 자체로는 0.67 이지만,
    DB 전체로 세면 5장 중 2장(0.4)이라 임계 0.5 를 안 넘는다.
    """
    db = _seed(tmp_path)                       # A45Z5 wafer 2장, 고아 없음
    orphans = B_STEPS + [
        {"root_lot_id": "B77B7", "wafer_id": "09", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"},
        {"root_lot_id": "B77B7", "wafer_id": "10", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"}]

    report = li.load_incremental([(["B77B7"], B_YIELDS, orphans)], db, verbose=False)

    assert report["fatal"] and not report["committed"]
    assert _counts(db) == (2, 3)               # 원래 상태 그대로


def test_old_orphans_do_not_block_a_clean_batch(tmp_path):
    """반대 방향. 기존 데이터에 고아가 있어도 이번 배치가 깨끗하면 통과한다."""
    db = tmp_path / "t.db"
    dirty = STEPS + [{"root_lot_id": "A45Z5", "wafer_id": "77",
                      "step_seq": "CC002000", "eqp_id": "ETCH9", "timestamp": "t"}]
    li.load(YIELDS, dirty, db, verbose=False)  # 고아 1장이 이미 들어 있는 DB

    report = li.load_incremental([(["B77B7"], B_YIELDS, B_STEPS)], db, verbose=False)

    assert report["committed"] and not report["fatal"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_load_internal.py -k "broken_batch_is_blocked or old_orphans_do_not_block" -v`
Expected: `test_a_broken_batch_is_blocked_even_though_the_db_is_mostly_clean` 이 FAIL (전역 비율 0.4 라 fatal 이 안 잡힌다). 다른 하나는 통과할 수 있다 - 정상이다.

- [ ] **Step 3: 검증 범위를 임시 테이블로 잡는다**

`validate()` 시그니처와 앞부분을 바꾼다. 조건절을 문자열로 붙이는 대신 임시 테이블을 쓰면, 전역과 증분이 **같은 SQL** 을 타서 한쪽만 고치는 사고가 안 생기고 SQLite 의 인자 개수 한계(999)도 안 걸린다.

```python
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
```

바로 아래에 범위 조건 헬퍼를 모듈 수준 함수로 둔다 (`validate` 위에 정의).

```python
def _in_scope(alias: str = "") -> str:
    """검사 범위 조건절. alias 는 조인 질의에서 테이블 별칭("s"/"y")."""
    p = f"{alias}." if alias else ""
    return f"{p}root_lot_id IN (SELECT root_lot_id FROM _scope)"
```

- [ ] **Step 4: 검사 질의 8개에 범위를 건다**

`validate()` 본문의 질의를 아래처럼 바꾼다. 검사 번호와 주석은 그대로 둔다.

```python
    # 1. 조인 키 형식 (…_NN)
    bad = [r["wafer_id"] for r in
           q(f"SELECT wafer_id FROM yield WHERE {_in_scope()}")
           if not _WID.match(r["wafer_id"])]

    # 2. wafer_id 접두 == root_lot_id 교차검증
    mism = q(f"""SELECT wafer_id FROM yield
                 WHERE wafer_id <> root_lot_id || '_' || substr(wafer_id, -2)
                   AND {_in_scope()}""")

    # 2-1. step_seq 형식
    bad_seq = [r["step_seq"] for r in
               q(f"SELECT DISTINCT step_seq FROM step_history WHERE {_in_scope()}")
               if not _STEP_SEQ.match(r["step_seq"])]

    # 3. step_history 고아
    n_hist_wafers = one(f"SELECT COUNT(DISTINCT wafer_id) FROM step_history "
                        f"WHERE {_in_scope()}")
    orphan = q(f"""SELECT DISTINCT s.wafer_id FROM step_history s
                   LEFT JOIN yield y ON y.wafer_id = s.wafer_id
                   WHERE y.wafer_id IS NULL AND {_in_scope('s')}""")

    # 4. 이력 없는 wafer
    no_hist = q(f"""SELECT y.wafer_id FROM yield y
                    LEFT JOIN step_history s ON s.wafer_id = y.wafer_id
                    WHERE s.wafer_id IS NULL AND {_in_scope('y')}""")

    # 5. yield 범위
    oor = one(f"SELECT COUNT(*) FROM yield "
              f"WHERE (yield < 0 OR yield > 100) AND {_in_scope()}")

    # 6. 중복 이력
    dup = one(f"""SELECT COUNT(*) FROM (SELECT wafer_id, step_seq
                  FROM step_history WHERE {_in_scope()}
                  GROUP BY 1,2 HAVING COUNT(*) > 1)""")
```

반환 dict 의 집계 질의도 같이 좁히고, 전역 규모를 새 키로 더한다.

```python
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
        "area_null_rate": round(
            one(f"SELECT COUNT(*) FROM step_history "
                f"WHERE area IS NULL AND {_in_scope()}") / max(n_steps, 1), 3),
        "ch_id_null_rate": round(
            one(f"SELECT COUNT(*) FROM step_history "
                f"WHERE ch_id IS NULL AND {_in_scope()}") / max(n_steps, 1), 3),
        "ppid_null_rate": round(
            one(f"SELECT COUNT(*) FROM step_history "
                f"WHERE ppid IS NULL AND {_in_scope()}") / max(n_steps, 1), 3),
        "fatal": fatal,
        "issues": issues,
    }
```

- [ ] **Step 5: `load_incremental` 이 범위를 넘기게 한다**

Task 3 에서 넣은 `report = validate(conn, n_y, n_s)` 를 바꾼다.

```python
        report = validate(conn, n_y, n_s, root_lots=lots)
```

- [ ] **Step 6: `_print` 에 전체 규모와 증분 정보를 싣는다**

`_print` 의 첫 줄 다음에 넣는다. 증분이 아닐 때(`n_lots` 키가 없을 때)는 안 찍는다.

```python
def _print(r: dict) -> None:
    _say(f"[적재] yield {r['n_yield']}행 / step_history {r['n_steps']}행")
    if "n_lots" in r:                       # 증분에서만
        _say(f"[증분] 대상 lot {r['n_lots']}개 · 삭제 yield {r['n_deleted_yield']}행"
             f" / step_history {r['n_deleted_steps']}행")
        _say(f"[전체] yield {r['n_total_yield']}행 / step_history "
             f"{r['n_total_steps']}행 · root_lot {r['n_total_root_lots']}개")
    _say(f"[구성] root_lot {r['n_root_lots']}개 · 이력 보유 wafer "
         f"{r['n_wafers_with_history']}장 · lot_type {r['lot_types']}")
    # (이하 기존과 동일)
```

`_print` 끝의 교체 안내도 두 모드를 구분한다.

```python
    if "n_lots" in r:
        _say(f"[커밋] {r['db_path']} 갱신 완료" if r.get("committed")
             else f"[되돌림] {r['db_path']} 는 기존 상태 유지 (--force 로 무시 가능)")
    elif r.get("swapped"):
        _say(f"[교체] {r['db_path']} 갱신 완료")
    else:
        _say(f"[교체 안 함] {r['db_path']} 는 기존 상태 유지 (--force 로 무시 가능)")
```

- [ ] **Step 7: 테스트 통과 확인**

Run: `python -m pytest tests/test_load_internal.py -v`
Expected: 전부 PASS. 특히 `test_null_rates_reflect_actual_gaps` 와 `test_report_prints_on_a_console_that_cannot_encode_every_character` 가 계속 통과해야 한다(전역 경로가 안 깨졌다는 뜻).

- [ ] **Step 8: 전체 테스트**

Run: `python -m pytest -q`
Expected: 209 passed

- [ ] **Step 9: 변이 확인**

`load_incremental` 의 `validate(conn, n_y, n_s, root_lots=lots)` 를 `validate(conn, n_y, n_s)` 로 되돌린다(= 전역 검증).
Run: `python -m pytest tests/test_load_internal.py -q`
Expected: `test_a_broken_batch_is_blocked_even_though_the_db_is_mostly_clean` 이 죽는다. 확인 후 되돌린다.

- [ ] **Step 10: 커밋**

```bash
git add data/load_internal.py tests/test_load_internal.py
git commit -m "fix(load): 증분 검증을 이번 배치의 lot 으로 좁힌다 (전역 비율은 희석돼 못 막는다)"
```

---

### Task 5: 실행 모드와 추출 계약

`--rebuild` / `--since` / `--lots` 를 붙이고, 사내 추출 함수를 둘로 나눈다. 모드를 필수로 두는 이유는, 지금 인자 없이 실행하면 전체 재적재라서 매일 도는 스크립트에서 인자가 빠지면 수십 분짜리가 조용히 돌기 때문이다.

**Files:**
- Modify: `ya_config.py` (설정 2줄)
- Modify: `data/load_internal.py:433-465` (`_extract`, `main`)
- Test: `tests/test_load_internal.py`

**Interfaces:**
- Consumes: Task 2 의 `_chunked`·`rebuild`, Task 3 의 `load_incremental`
- Produces:
  - `ya_config.LOAD_LOT_CHUNK: int` (기본 20), `ya_config.LOAD_SINCE_DAYS: int` (기본 7)
  - `_extract_lot_ids(since_date: str | None) -> list[str]` — 사내가 채울 자리
  - `_extract(root_lots: list[str]) -> tuple[Iterable[dict], Iterable[dict]]` — 사내가 채울 자리 (시그니처 변경)
  - `_run_incremental(lot_ids, db_path, force, verbose=True) -> dict` — 청크 순회 드라이버

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_extraction_runs_once_per_chunk(tmp_path, monkeypatch):
    """전량을 한 번에 안 받는다. 이것이 메모리 유계의 실질 보증이다 -
    한 번만 부르면 사내 lib 가 2,800만 행을 통째로 만들어 32GB 를 쓴다."""
    import ya_config
    db = _seed(tmp_path)
    seen = []

    def fake_extract(chunk):
        seen.append(list(chunk))
        return [], []

    monkeypatch.setattr(li, "_extract", fake_extract)
    monkeypatch.setattr(ya_config, "LOAD_LOT_CHUNK", 20)

    lots = [f"L{i:03d}" for i in range(45)]
    # force=True: 이 가짜 추출은 yield 0행이라 정상적으로 fatal 이 난다.
    # 여기서 보는 것은 적재 결과가 아니라 호출 분할이다.
    li._run_incremental(lots, db, force=True, verbose=False)

    assert [len(c) for c in seen] == [20, 20, 5]
    assert seen[0] == lots[:20]


def test_an_empty_lot_list_ends_normally_without_touching_the_db(tmp_path, monkeypatch):
    """주말·비가동으로 대상이 0개인 것은 정상이다.

    이 분기가 없으면 검사 0번("yield 0행: 추출 결과가 비었다")이 매주 치명적
    오류로 뜨고, 사람이 그 경보를 무시하기 시작하면 진짜 추출 장애도 같이 묻힌다.
    """
    db = _seed(tmp_path)
    before = _counts(db)
    monkeypatch.setattr(li, "_extract_lot_ids", lambda since: [])
    monkeypatch.setattr(sys, "argv",
                        ["load_internal", "--since", "7", "--db", str(db)])

    try:
        li.main()
    except SystemExit as e:
        assert e.code == 0
    else:
        raise AssertionError("SystemExit 가 나지 않았다")

    assert _counts(db) == before


def test_a_mode_must_be_given_explicitly():
    """인자 없이 실행하면 전체 재적재가 조용히 도는 것을 막는다."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run([sys.executable, "-m", "data.load_internal"],
                          capture_output=True, cwd=root)
    assert proc.returncode != 0
    assert b"--rebuild" in proc.stderr or b"--since" in proc.stderr
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_load_internal.py -k "runs_once_per_chunk or empty_lot_list or mode_must_be_given" -v`
Expected: FAIL - `_run_incremental` 없음 / `main()` 에 `--since` 인자가 없음 / 인자 없는 실행이 `NotImplementedError` 로 죽어 returncode 는 0 이 아니지만 stderr 에 `--rebuild` 가 없다

- [ ] **Step 3: 설정을 추가한다**

`ya_config.py` 의 `DB_PATH` 정의 아래에 넣는다.

```python
# 사내 적재 - lot 청크 크기. `_extract()` 를 이 단위로 나눠 부른다. 청크가 끝나면
# 그 DataFrame 과 dict 가 해제되므로 메모리가 청크 하나 크기로 유계가 된다.
LOAD_LOT_CHUNK = int(os.getenv("LOAD_LOT_CHUNK", "20"))
# `--since` 의 기본 일수. 재작업이 며칠 안에 끝나는지에 맞춰 실측 후 조정한다.
LOAD_SINCE_DAYS = int(os.getenv("LOAD_SINCE_DAYS", "7"))
```

- [ ] **Step 4: 추출 계약을 둘로 나눈다**

`data/load_internal.py` 의 `_extract()` 를 통째로 교체한다.

```python
def _extract_lot_ids(since_date):
    """⚠️ 사내 추출 라이브러리를 연결할 자리 (1/2).

    반환: 적재 대상 root_lot_id 목록.

    since_date 가 None 이면 전체(rebuild 용). 날짜 문자열("2026-07-30")이면
    **두 축의 합집합**으로 뽑는다:

        검사일이 since_date 이후인 lot  UNION  스텝 처리시각이 since_date 이후인 lot

    검사일만 보면 안 된다. 재작업 이력이 붙어도 yield 의 검사일은 그대로일 수 있어서,
    그 lot 이 재확인 창에 안 걸리고 **이력은 늘었는데 DB 에는 영영 안 들어온다.**
    """
    raise NotImplementedError(
        "사내 추출 라이브러리를 연결하세요. "
        "적재 대상 root_lot_id 목록을 반환하면 됩니다."
    )


def _extract(root_lots: list[str]):
    """⚠️ 사내 추출 라이브러리를 연결할 자리 (2/2).

    입력: root_lot_id 목록 (LOAD_LOT_CHUNK 개 이하)
    반환: (yield_records, step_records) — 위 '입력 계약' 형태

    **lot 전체를 한 번에 받지 말 것.** 호출부가 청크로 나눠 여러 번 부르므로,
    이 함수는 받은 lot 만 뽑아 돌려주면 된다. DataFrame 을 dict 로 바꾸는 것은
    그대로 두어도 되고, 리스트 대신 제너레이터를 반환해도 된다.
    """
    raise NotImplementedError(
        "사내 추출 라이브러리를 연결하세요. "
        "yield_records / step_records 를 입력 계약 형태로 반환하면 됩니다."
    )
```

- [ ] **Step 5: 청크 드라이버와 CLI 를 만든다**

`main()` 위에 드라이버를 두고, `main()` 을 교체한다. `datetime` import 를 파일 상단 표준 라이브러리 묶음에 추가한다 (`from datetime import date, timedelta`).

```python
def _run_incremental(lot_ids, db_path, force: bool, verbose: bool = True) -> dict:
    """lot 목록을 청크로 잘라 추출하고 증분 적재한다."""
    chunks = ((c, *_extract(c)) for c in _chunked(lot_ids, ya_config.LOAD_LOT_CHUNK))
    return load_incremental(chunks, db_path, verbose=verbose, force=force)


def main():
    ap = argparse.ArgumentParser(description="사내 실데이터 -> yield + step_history 적재")
    # help 문구는 argparse 가 직접 찍는다 - `_say` 가 못 덮으므로 cp949 밖 글자를 쓰면
    # `--help` 자체가 UnicodeEncodeError 로 죽는다 (em-dash 금지)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rebuild", action="store_true",
                     help="전체 재적재. 임시 DB 를 만들어 검증 통과 시 교체한다")
    mode.add_argument("--since", nargs="?", type=int, const=ya_config.LOAD_SINCE_DAYS,
                     metavar="N",
                     help=f"최근 N일 안에 검사되거나 처리된 lot 을 다시 적재 "
                          f"(기본 {ya_config.LOAD_SINCE_DAYS}일). 매일 이것을 쓴다")
    mode.add_argument("--lots", metavar="A45Z5,B12X3",
                     help="쉼표로 구분한 root_lot 목록만 적재 (수동 교정용)")
    ap.add_argument("--db", default=str(ya_config.DB_PATH),
                    help=f"적재 대상 DB (기본 {ya_config.DB_PATH}: 더미와 동일, 덮어씀 주의)")
    ap.add_argument("--force", action="store_true",
                    help="치명적 정합성 오류가 있어도 확정한다")
    args = ap.parse_args()

    db = Path(args.db)
    if db == Path(ya_config.DB_PATH):
        _say(f"[주의] {db} 는 더미 DB 와 같은 경로입니다. 기존 내용이 대체됩니다.")

    if args.rebuild:
        lot_ids = _extract_lot_ids(None)
        batches = (_extract(c) for c in _chunked(lot_ids, ya_config.LOAD_LOT_CHUNK))
        report = rebuild(batches, db, force=args.force)
        raise SystemExit(0 if report["swapped"] else 1)

    if args.lots is not None:
        lot_ids = [s.strip() for s in args.lots.split(",") if s.strip()]
    else:
        since = (date.today() - timedelta(days=args.since)).isoformat()
        lot_ids = _extract_lot_ids(since)

    # 주말·비가동으로 대상이 0개인 것은 정상이다. 여기서 걸러야 "추출이 비었다" 는
    # 치명적 판정(검사 0번)이 매주 오경보로 뜨는 것을 막는다.
    if not lot_ids:
        _say("[증분] 대상 lot 0개. 적재할 것이 없습니다.")
        raise SystemExit(0)

    report = _run_incremental(lot_ids, db, force=args.force)
    raise SystemExit(0 if report["committed"] else 1)
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest tests/test_load_internal.py -v`
Expected: 전부 PASS. `test_help_text_survives_a_cp949_console` 과 `test_script_path_execution_finds_the_repo_root` 가 계속 통과하는지 특히 볼 것 - 새 help 문구에 cp949 밖 글자가 들어가면 여기서 죽는다.

- [ ] **Step 7: 전체 테스트**

Run: `python -m pytest -q`
Expected: 212 passed

- [ ] **Step 8: 변이 확인**

`_run_incremental` 의 `_chunked(lot_ids, ya_config.LOAD_LOT_CHUNK)` 를 `[lot_ids]` 로 바꾼다(= 통째로 한 번에).
Run: `python -m pytest tests/test_load_internal.py -q`
Expected: `test_extraction_runs_once_per_chunk` 가 죽는다. 확인 후 되돌린다.

- [ ] **Step 9: 커밋**

```bash
git add ya_config.py data/load_internal.py tests/test_load_internal.py
git commit -m "feat(load): --rebuild/--since/--lots 실행 모드와 lot 청크 추출 계약"
```

---

### Task 6: 문서와 사내 연결 안내

사내에서 `_extract_lot_ids` / `_extract` 를 직접 채우실 수 있게 필요한 형태를 정확히 적는다.

**Files:**
- Modify: `data/load_internal.py:11-46` (모듈 docstring 의 입력 계약)
- Modify: `docs/사내-투입-점검표.md` (3-1 명령 + 매일 적재 절)
- Modify: `README.md` (적재 명령 예시)
- Modify: `docs/사내-데이터-변환시-할일.md` (`_extract` 계약)

**Interfaces:**
- Consumes: Task 5 의 `_extract_lot_ids`·`_extract` 시그니처
- Produces: 없음 (문서)

- [ ] **Step 1: 모듈 docstring 의 입력 계약을 갱신한다**

`data/load_internal.py` 상단 docstring 의 "입력 계약" 블록 앞에 추출 함수 두 개를 명시한다. 기존 레코드 형태 서술과 세 개의 ⚠️ 블록은 그대로 둔다.

```
────────────────────────────────────────────────────────────────────────
사내가 채울 함수 2개

  _extract_lot_ids(since_date) -> ["A45Z5", "B12X3", ...]
      since_date=None      : 전체 root_lot (--rebuild 용)
      since_date="2026-07-30": 검사일이 그 날 이후인 lot
                               UNION 스텝 처리시각이 그 날 이후인 lot

      ⚠️ 검사일만 보면 안 된다. 재작업 이력이 붙어도 yield 의 검사일은 그대로일
         수 있어서, 그 lot 이 재확인 창에 안 걸리고 이력이 영영 안 들어온다.

  _extract(root_lots) -> (yield_records, step_records)
      root_lots 는 LOAD_LOT_CHUNK(기본 20) 개 이하. 호출부가 나눠 부른다.

      ⚠️ 전량을 한 번에 만들지 말 것. dict 2,800만 개는 10GB 를 넘고, 적재가
         끝날 때까지 그 리스트가 살아 있어 메모리가 32GB 까지 오른다(사내 실측).
────────────────────────────────────────────────────────────────────────
```

- [ ] **Step 2: 점검표 3-1 을 갱신하고 매일 적재 절을 추가한다**

`docs/사내-투입-점검표.md` 의 3-1 실행 명령을 바꾸고, 그 아래에 절을 하나 더한다.

```markdown
### 3-1. 첫 적재 (전체)

python -X utf8 -m data.load_internal --rebuild

`--rebuild` 를 빼면 오류로 멈춘다. 모드를 반드시 지정해야 매일 도는 스크립트에서
인자가 빠졌을 때 전체 재적재가 조용히 도는 일이 없다.

### 3-2. 매일 적재 (증분)

python -X utf8 -m data.load_internal --since 7

최근 7일 안에 검사되거나 처리된 root_lot 을 다시 적재한다. lot 단위로 지우고
다시 넣으므로 몇 번을 돌려도 결과가 같고, 재작업으로 늘어난 이력이 반영된다.

판독:
  [증분] 대상 lot 0개        주말·비가동이면 정상이다 (종료 코드 0)
  삭제 행수가 0 이 아니다     재작업으로 다시 실린 lot 이 있다는 뜻
  [되돌림] 이 찍혔다          정합성 문제로 커밋을 안 했다. 경고 내용을 볼 것

특정 lot 만 다시 넣으려면:

python -X utf8 -m data.load_internal --lots A45Z5,B12X3

### 3-3. 사내에서 채울 함수 2개

`data/load_internal.py` 아래쪽 `_extract_lot_ids` / `_extract` 두 곳이다.
형태는 이렇다 (원천 테이블·컬럼명은 사내 것으로).

```python
def _extract_lot_ids(since_date):
    if since_date is None:
        df = <사내lib>.query("SELECT DISTINCT root_lot_id FROM <수율원천>")
    else:
        df = <사내lib>.query(f"""
            SELECT DISTINCT root_lot_id FROM <수율원천> WHERE 검사일 >= '{since_date}'
            UNION
            SELECT DISTINCT root_lot_id FROM <이력원천> WHERE 처리시각 >= '{since_date}'
        """)
    return [str(x) for x in df["root_lot_id"]]


def _extract(root_lots):
    ph = ",".join(f"'{lot}'" for lot in root_lots)
    y = <사내lib>.query(f"SELECT ... FROM <수율원천>  WHERE root_lot_id IN ({ph})")
    s = <사내lib>.query(f"SELECT ... FROM <이력원천> WHERE root_lot_id IN ({ph})")
    return y.to_dict("records"), s.to_dict("records")
```

`_extract` 는 받은 lot 만 뽑는다. 전체를 한 번에 만들면 메모리가 32GB 까지 오른다.
```

- [ ] **Step 3: README 의 파일 설명을 갱신한다**

`README.md:168` 한 줄이다. 실행 명령 예시는 README 에 없고 파일 트리 설명만 있다.

```
│   ├── load_internal.py   사내 실데이터 적재 ETL (전체 --rebuild / 증분 --since,
│   │                      추출은 사내 lib - _extract_lot_ids()·_extract() 에 연결)
```

- [ ] **Step 4: 변환시-할일 문서의 `_extract` 계약을 갱신한다**

`docs/사내-데이터-변환시-할일.md:66` 의 `→ _extract() 가 yield 레코드에 lot_type 코드를 실어 줘야 한다.` 는 그대로 두고(여전히 맞다), §2 절의 체크리스트에 항목을 하나 더한다.

```markdown
- [ ] **추출 함수 2개 연결** (2026-08-06 신규) — `_extract()` 가 `root_lots` 를 인자로
  받게 바뀌었고, lot 목록을 뽑는 `_extract_lot_ids(since_date)` 가 새로 생겼다.
  `--since` 로 매일 증분 적재를 돌리려면 둘 다 채워야 한다. 형태는 점검표 3-3 참조.
  ⚠️ `_extract()` 는 **받은 lot 만** 뽑는다. 전체를 한 번에 dict 로 만들면 메모리가
  32GB 까지 오르고 적재가 수십 분이 된다 (2026-08-06 사내 실측).
```

- [ ] **Step 5: 문서 전체 확인**

Run: `python -m pytest -q`
Expected: 212 passed (문서 변경이 테스트를 깨지 않는지 확인)

Run: `python -X utf8 -m data.load_internal --help`
Expected: 정상 출력. 새 `--since`·`--lots`·`--rebuild` 설명이 보인다.

- [ ] **Step 6: 커밋**

```bash
git add data/load_internal.py docs/사내-투입-점검표.md README.md docs/사내-데이터-변환시-할일.md
git commit -m "docs: 증분 적재 실행 절차와 사내 추출 함수 2개의 형태를 싣는다"
```

---

## 완료 기준

- `python -m pytest -q` 가 **212 passed**
- `python -X utf8 -m data.load_internal` (인자 없음) 이 오류로 멈춘다
- `--help` 가 cp949 콘솔에서 죽지 않는다
- Task 1·3·4·5 의 변이 확인이 모두 "해당 테스트가 단독으로 죽는다" 로 나왔다
- 사내에서 `_extract_lot_ids` / `_extract` 두 함수만 채우면 `--since 7` 이 돈다

## 이 계획이 다루지 않는 것

- 센서 추출 방식 전환 (사내 라이브러리) - 별도 설계 예정
- 보존 기간 정리 (`--purge-before`) - 지금 아픈 문제가 아니라 뺐다
- 전컬럼 완전 동일 행 16만건 조사 (`docs/2026-08-03-사내투입-진단정리.md` §5)
