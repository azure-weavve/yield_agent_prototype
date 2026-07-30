"""사내 적재 왕복 — transform → INSERT 경로가 실제로 도는지.

계약 테스트(test_schema_contract.py)는 **DDL 만** 동결한다. 그래서 DDL 에 컬럼이
있어도 transform_steps 나 INSERT 에서 빠뜨리면 계약은 green 인데 적재된 값은
전부 NULL 이 된다 — hyp_ppid_commonality 가 에러 없이 후보 0 으로 끝나는,
계약 테스트가 막으려던 것과 똑같은 모양의 조용한 실패다. 그 구멍을 메운다.
"""

import io
import sqlite3
import sys

from data import load_internal as li

YIELDS = [{"root_lot_id": "A45Z5", "wafer_id": "01", "lot_id": "A45Z5.1",
           "yield": 91.2, "date": "2026-07-01"},
          {"root_lot_id": "A45Z5", "wafer_id": "02", "lot_id": "A45Z5.1",
           "yield": 62.0, "date": "2026-07-01"}]

STEPS = [{"root_lot_id": "A45Z5", "wafer_id": "01", "process_step": "Etch",
          "eqp_id": "ETCH9", "ch_id": "A", "ppid": "PPID_Y", "timestamp": "t"},
         {"root_lot_id": "A45Z5", "wafer_id": "02", "process_step": "Etch",
          "eqp_id": "ETCH9", "ch_id": "B", "ppid": "PPID_X", "timestamp": "t"},
         # ch_id·ppid 없는 원천 (단일 챔버 설비·PPID 개념 없는 스텝)
         {"root_lot_id": "A45Z5", "wafer_id": "02", "process_step": "CMP",
          "eqp_id": "CMP1", "timestamp": "t"}]


def _load(tmp_path):
    db = tmp_path / "t.db"
    report = li.load(YIELDS, STEPS, db, verbose=False)
    return db, report


def test_step_columns_survive_the_write_path(tmp_path):
    """DDL 에만 있고 INSERT 에서 빠지는 일이 없어야 한다."""
    db, _ = _load(tmp_path)
    conn = sqlite3.connect(db)
    rows = conn.execute("""SELECT wafer_id, eqp_id, ch_id, ppid FROM step_history
                           ORDER BY wafer_id, process_step""").fetchall()
    conn.close()
    assert rows == [("A45Z5_01", "ETCH9", "A", "PPID_Y"),
                    ("A45Z5_02", "CMP1", None, None),      # 결측은 NULL 로
                    ("A45Z5_02", "ETCH9", "B", "PPID_X")]


def test_null_rates_reflect_actual_gaps(tmp_path):
    """결측률이 실제 결측을 반영해야 한다 — 0.0 으로 굳으면 '안 실렸다'를 못 본다."""
    _, report = _load(tmp_path)
    assert report["ch_id_null_rate"] == round(1 / 3, 3)
    assert report["ppid_null_rate"] == round(1 / 3, 3)
    assert not report["fatal"]


# --------------------------------------------------------------------------- #
# ppid grain — 결측률이 못 보는 실패
#
# ppid 는 wafer×스텝 단위(그 wafer 가 그 스텝에서 쓴 PPID)다. 원천에서 lot/recipe
# 마스터에 조인해 오면 결측률은 0.0(초록)인데 lot 전원이 같은 ppid 를 갖게 되어
# hyp_ppid_commonality 가 **에러 없이 틀린 집계**를 낸다. 결측률로는 안 보인다.
#
# 판정은 전역 조건으로만 한다 — 한 lot 이 한 PPID 로 도는 건 정상인 스텝도 많아서
# lot 개별 판정은 오경보가 잦다. 반례(한 군에서 ppid 2값) 1건이면 wafer 단위가
# 증명되므로, "전 데이터에 반례 0건" 일 때만 의심한다.
# --------------------------------------------------------------------------- #
LOT_GRAIN_YIELDS = [{"root_lot_id": "B77Q2", "wafer_id": "01", "lot_id": "B77Q2.1",
                     "yield": 88.0, "date": "2026-07-02"},
                    {"root_lot_id": "B77Q2", "wafer_id": "02", "lot_id": "B77Q2.1",
                     "yield": 55.0, "date": "2026-07-02"}]

# lot 마스터 조인의 서명: 같은 lot×스텝의 두 wafer 가 챔버는 갈리는데 ppid 는 같다
LOT_GRAIN_STEPS = [{"root_lot_id": "B77Q2", "wafer_id": "01", "process_step": "Etch",
                    "eqp_id": "ETCH9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"},
                   {"root_lot_id": "B77Q2", "wafer_id": "02", "process_step": "Etch",
                    "eqp_id": "ETCH9", "ch_id": "B", "ppid": "PPID_L", "timestamp": "t"}]


def test_ppid_that_never_varies_within_lot_and_step_is_flagged(tmp_path):
    """결측률 0.0 이어도 grain 이 틀렸으면 경고가 떠야 한다."""
    report = li.load(LOT_GRAIN_YIELDS, LOT_GRAIN_STEPS, tmp_path / "t.db",
                     verbose=False)
    assert report["ppid_null_rate"] == 0.0            # 결측률은 못 보는 실패다
    assert report["ppid_grain"] == {"checkable": 1, "varying": 0}
    assert any("마스터 단위 조인 의심" in i for i in report["issues"])
    assert not report["fatal"]                        # 교체는 막지 않는다 (사람이 볼 것)


def test_ppid_grain_is_silent_when_variation_is_structurally_impossible(tmp_path):
    """lot×스텝마다 wafer 가 1장뿐이면 갈릴 수가 없다 — 경고하면 100% 오경보다."""
    yields = [{"root_lot_id": "C31K8", "wafer_id": "01", "lot_id": "C31K8.1",
               "yield": 90.0, "date": "2026-07-03"},
              {"root_lot_id": "C31K8", "wafer_id": "02", "lot_id": "C31K8.2",
               "yield": 70.0, "date": "2026-07-03"}]
    steps = [{"root_lot_id": "C31K8", "wafer_id": "01", "process_step": "Etch",
              "eqp_id": "ETCH9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"},
             {"root_lot_id": "C31K8", "wafer_id": "02", "process_step": "Etch",
              "eqp_id": "ETCH9", "ch_id": "B", "ppid": "PPID_L", "timestamp": "t"}]
    report = li.load(yields, steps, tmp_path / "t.db", verbose=False)
    assert report["ppid_grain"] == {"checkable": 0, "varying": 0}
    assert not any("마스터 단위 조인 의심" in i for i in report["issues"])


def test_ppid_grain_accepts_a_single_counterexample_as_proof(tmp_path):
    """한 군에서 ppid 가 갈리면 wafer 단위가 증명된다 — 더미가 이 모양이다.

    이 테스트는 검사에서 DISTINCT 판정이 빠져 무조건 경고하게 되면 실패한다.
    """
    _, report = _load(tmp_path)
    assert report["ppid_grain"] == {"checkable": 1, "varying": 1}
    assert not any("마스터 단위 조인 의심" in i for i in report["issues"])


def test_rework_rows_are_not_mistaken_for_wafer_level_variation(tmp_path):
    """재작업 행 1건이 검사를 꺼뜨리면 안 된다.

    판정이 전역(반례 1건이면 침묵)이라, 행 단위로 ppid 를 세면 **전 데이터에 이런 행이
    하나만 있어도** 검사가 통째로 무력화된다. 수백만 행 실데이터에서 중복 이력은
    예상되는 상태다(검사 #6 이 "재작업인지 확인" 이라고 말하는 이유).
    """
    ys = [{"root_lot_id": "D11A1", "wafer_id": f"{i:02d}", "lot_id": "D11A1.1",
           "yield": 80.0, "date": "d"} for i in (1, 2, 3)]
    # 전 데이터가 lot 마스터 grain(틀림)
    st = [{"root_lot_id": "D11A1", "wafer_id": f"{i:02d}", "process_step": "Etch",
           "eqp_id": "E9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"}
          for i in (1, 2, 3)]
    rework = dict(st[0])
    rework["ppid"] = "PPID_M"                 # 같은 wafer×스텝, 다른 ppid
    report = li.load(ys, st + [rework], tmp_path / "t.db", verbose=False)

    # wafer 간 변이는 0 이다 — 한 wafer 안의 재작업 차이는 반례가 아니다
    assert report["ppid_grain"] == {"checkable": 1, "varying": 0}
    assert any("마스터 단위 조인 의심" in i for i in report["issues"])


def test_ppid_grain_needs_a_counterexample_somewhere_not_in_every_lot(tmp_path):
    """반례가 한 lot 에만 있어도 전역 침묵이어야 한다.

    lot 개별 판정(`varying < checkable`)으로 바꾸면 이 테스트가 실패한다. 한 lot 이 한
    PPID 로 도는 건 정상인 스텝도 많아 개별 판정은 오경보이므로, 금지된 설계다.
    """
    ys = ([{"root_lot_id": "E22B2", "wafer_id": f"{i:02d}", "lot_id": "E22B2.1",
            "yield": 80.0, "date": "d"} for i in (1, 2)] +
          [{"root_lot_id": "E22B2", "wafer_id": f"{i:02d}", "lot_id": "E22B2.2",
            "yield": 80.0, "date": "d"} for i in (3, 4)])
    st = ([{"root_lot_id": "E22B2", "wafer_id": f"{i:02d}", "process_step": "Etch",
            "eqp_id": "E9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"}
           for i in (1, 2)] +                  # lot .1 — 안 갈린다
          [{"root_lot_id": "E22B2", "wafer_id": "03", "process_step": "Etch",
            "eqp_id": "E9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"},
           {"root_lot_id": "E22B2", "wafer_id": "04", "process_step": "Etch",
            "eqp_id": "E9", "ch_id": "B", "ppid": "PPID_M", "timestamp": "t"}])
    report = li.load(ys, st, tmp_path / "t.db", verbose=False)                # lot .2 — 갈린다

    assert report["ppid_grain"] == {"checkable": 2, "varying": 1}
    assert not any("마스터 단위 조인 의심" in i for i in report["issues"])


def test_ppid_grain_ignores_wafers_whose_ppid_is_missing(tmp_path):
    """ppid 있는 wafer 가 1장뿐인 군은 판정 대상이 아니다.

    `WHERE h.ppid IS NOT NULL` 을 빼면 checkable 이 1 로 올라가 오경보가 난다.
    ppid 부분 결측은 실데이터 1차 추출의 전형적 상태다(DDL 이 nullable 인 이유).
    """
    ys = [{"root_lot_id": "F33C3", "wafer_id": f"{i:02d}", "lot_id": "F33C3.1",
           "yield": 80.0, "date": "d"} for i in (1, 2, 3)]
    st = [{"root_lot_id": "F33C3", "wafer_id": f"{i:02d}", "process_step": "Etch",
           "eqp_id": "E9", "ch_id": "A", "timestamp": "t"} for i in (1, 2, 3)]
    st[0]["ppid"] = "PPID_L"                  # 3장 중 1장만 ppid 보유
    report = li.load(ys, st, tmp_path / "t.db", verbose=False)

    assert report["ppid_grain"] == {"checkable": 0, "varying": 0}
    assert not any("마스터 단위 조인 의심" in i for i in report["issues"])


def test_report_prints_on_a_console_that_cannot_encode_every_character(tmp_path,
                                                                      monkeypatch):
    """cp949 콘솔에서 리포트가 죽으면 안 된다.

    `_print` 는 os.replace **뒤에** 불린다. 한 줄이 UnicodeEncodeError 로 죽으면 DB 는
    교체된 채 traceback 만 남고 **사람이 봐야 할 경고 문구가 사라진다** — 리포트가
    가장 필요한 순간이 정확히 이 경로다.

    이 저장소가 직접 쓰는 문구는 전부 cp949 안으로 맞췄으므로(그래야 '?' 로도 안 깨진다),
    남은 위험은 **데이터에서 오는 문자열**이다. 리포트는 DB 경로·wafer_id 예시 같은
    외부 값을 그대로 싣는데 그 안에 무엇이 들어올지는 이 저장소가 통제하지 못한다.
    여기서는 경로에 em-dash(U+2014, 한국어 코드페이지에 없다)를 넣어 그 경우를 만든다.
    """
    steps = STEPS + [dict(STEPS[0])]          # wafer×스텝 중복 → 경고 1건 발생
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", buf)
    li.load(YIELDS, steps, tmp_path / "t—.db", verbose=True)   # 경로에 cp949 밖 글자
    buf.flush()
    out = buf.buffer.getvalue().decode("cp949")

    assert "재작업" in out                     # 경고 내용이 남아야 한다
    assert "[교체]" in out                     # 경고 뒤 줄까지 끝까지 찍혀야 한다
    assert "[grain]" in out                    # grain 진단 줄이 사라지면 안 된다
