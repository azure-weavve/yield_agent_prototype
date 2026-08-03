"""사내 적재 왕복 — transform → INSERT 경로가 실제로 도는지.

계약 테스트(test_schema_contract.py)는 **DDL 만** 동결한다. 그래서 DDL 에 컬럼이
있어도 transform_steps 나 INSERT 에서 빠뜨리면 계약은 green 인데 적재된 값은
전부 NULL 이 된다 — hyp_ppid_commonality 가 에러 없이 후보 0 으로 끝나는,
계약 테스트가 막으려던 것과 똑같은 모양의 조용한 실패다. 그 구멍을 메운다.
"""

import io
import os
import sqlite3
import subprocess
import sys

from data import load_internal as li

YIELDS = [{"root_lot_id": "A45Z5", "wafer_id": "01", "lot_id": "A45Z5.1",
           "lot_type": "PP", "yield": 91.2, "date": "2026-07-01"},
          {"root_lot_id": "A45Z5", "wafer_id": "02", "lot_id": "A45Z5.1",
           "lot_type": "PP", "yield": 62.0, "date": "2026-07-01"}]

STEPS = [{"root_lot_id": "A45Z5", "wafer_id": "01", "step_seq": "CC002000",
          "area": "Etch", "eqp_id": "ETCH9", "ch_id": "A", "ppid": "PPID_Y",
          "timestamp": "t"},
         {"root_lot_id": "A45Z5", "wafer_id": "02", "step_seq": "CC002000",
          "area": "Etch", "eqp_id": "ETCH9", "ch_id": "B", "ppid": "PPID_X",
          "timestamp": "t"},
         # area·ch_id·ppid 없는 원천 (공정명 미제공·단일 챔버 설비·PPID 개념 없는 스텝)
         {"root_lot_id": "A45Z5", "wafer_id": "02", "step_seq": "CC004000",
          "eqp_id": "CMP1", "timestamp": "t"}]


def _load(tmp_path):
    db = tmp_path / "t.db"
    report = li.load(YIELDS, STEPS, db, verbose=False)
    return db, report


def test_step_columns_survive_the_write_path(tmp_path):
    """DDL 에만 있고 INSERT 에서 빠지는 일이 없어야 한다."""
    db, _ = _load(tmp_path)
    conn = sqlite3.connect(db)
    rows = conn.execute("""SELECT wafer_id, area, eqp_id, ch_id, ppid FROM step_history
                           ORDER BY wafer_id, step_seq""").fetchall()
    conn.close()
    assert rows == [("A45Z5_01", "Etch", "ETCH9", "A", "PPID_Y"),
                    ("A45Z5_02", "Etch", "ETCH9", "B", "PPID_X"),
                    ("A45Z5_02", None, "CMP1", None, None)]   # 결측은 NULL 로


def test_null_rates_reflect_actual_gaps(tmp_path):
    """결측률이 실제 결측을 반영해야 한다 — 0.0 으로 굳으면 '안 실렸다'를 못 본다."""
    _, report = _load(tmp_path)
    assert report["ch_id_null_rate"] == round(1 / 3, 3)
    assert report["ppid_null_rate"] == round(1 / 3, 3)
    assert report["area_null_rate"] == round(1 / 3, 3)
    assert not report["fatal"]


def test_lot_type_comes_from_the_source_code_not_from_the_lot_id(tmp_path):
    """판정 재료는 원천의 두 자리 코드다 — lot_id 접미는 아무것도 결정하지 않는다.

    한동안 `lot_id` 의 '.1' 접미를 보는 휴리스틱이었다. 되돌아가면 여기서 잡힌다:
    아래 두 행은 접미와 코드가 서로 반대라 옛 규칙이면 값이 뒤집힌다.
    """
    ys = [{"root_lot_id": "Z99Z9", "wafer_id": "01", "lot_id": "Z99Z9.1",
           "lot_type": "ES", "yield": 80.0, "date": "d"},
          {"root_lot_id": "Z99Z9", "wafer_id": "02", "lot_id": "Z99Z9.2",
           "lot_type": "PP", "yield": 80.0, "date": "d"}]
    st = [{"root_lot_id": "Z99Z9", "wafer_id": f"{i:02d}", "step_seq": "CC002000",
           "eqp_id": "E9", "timestamp": "t"} for i in (1, 2)]
    report = li.load(ys, st, tmp_path / "t.db", verbose=False)

    assert report["lot_types"] == {"eval": 1, "prod": 1}


def test_a_malformed_lot_type_code_stops_the_load(tmp_path):
    """코드 형식이 어긋나면 조용히 eval 로 떨어뜨리지 말고 멈춰야 한다.

    eval 로 흘리면 양산랏이 통째로 평가랏이 되어도 리포트의 lot_type 집계가
    그럴듯해 보인다 — 사람이 볼 수 있는 증상이 없다.
    """
    ys = [dict(YIELDS[0], lot_type="PROD")]
    db = tmp_path / "t.db"
    try:
        li.load(ys, [], db, verbose=False)
    except ValueError as e:
        assert "두 자리" in str(e)
    else:
        raise AssertionError("형식 위반 코드가 통과했다")
    # 실패한 적재가 기존 DB 자리에 잔해를 남기면 안 된다
    assert not db.exists() and not db.with_name(db.name + ".tmp").exists()


def test_a_process_name_in_step_seq_is_flagged(tmp_path):
    """step_seq 자리에 공정명이 들어오면 경고해야 한다 — area 와 뒤바뀐 원천의 서명.

    이 사고는 에러를 내지 않는다. 공정명으로 묶인 후보가 그럴듯하게 나오고, 사내에서
    그 스텝 번호를 못 찾아서야 뒤늦게 드러난다. 다만 교체는 막지 않는다 — 자릿수
    관행이 제품군마다 다를 수 있어 오경보가 가능하다.
    """
    st = [dict(s, step_seq="Etch") for s in STEPS]
    report = li.load(YIELDS, st, tmp_path / "t.db", verbose=False)

    assert any("step_seq 형식 위반" in i for i in report["issues"])
    assert not report["fatal"] and report["swapped"]


def test_padded_step_seq_does_not_split_one_step_into_two(tmp_path):
    """고정폭 원천의 앞뒤 공백이 같은 스텝을 두 군으로 쪼개면 안 된다.

    `"CC002000"` 과 `"CC002000 "` 이 섞이면 commonality 가 같은 설비를 두 군으로 나눠
    분리 점수가 반토막 나는데, 에러는 나지 않는다.
    """
    st = [dict(STEPS[0]), dict(STEPS[1])]
    st[1]["step_seq"] = " CC002000 "          # 고정폭 CHAR 원천의 흔한 모양
    db = tmp_path / "t.db"
    li.load(YIELDS, st, db, verbose=False)

    conn = sqlite3.connect(db)
    seqs = [r[0] for r in conn.execute("SELECT DISTINCT step_seq FROM step_history")]
    conn.close()
    assert seqs == ["CC002000"]


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
                     "lot_type": "PP", "yield": 88.0, "date": "2026-07-02"},
                    {"root_lot_id": "B77Q2", "wafer_id": "02", "lot_id": "B77Q2.1",
                     "lot_type": "PP", "yield": 55.0, "date": "2026-07-02"}]

# lot 마스터 조인의 서명: 같은 lot×스텝의 두 wafer 가 챔버는 갈리는데 ppid 는 같다
LOT_GRAIN_STEPS = [{"root_lot_id": "B77Q2", "wafer_id": "01", "step_seq": "CC002000",
                    "eqp_id": "ETCH9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"},
                   {"root_lot_id": "B77Q2", "wafer_id": "02", "step_seq": "CC002000",
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
    """군 안에 설비·챔버가 갈리는 wafer 짝이 없으면 판정 대상이 아니다.

    여기서는 lot×스텝마다 wafer 가 1장씩이라 그렇다. 단일 wafer 를 위한 별도 가드가
    있는 게 아니라 `COUNT(DISTINCT tool) > 1` 하나가 두 경우를 함께 처리한다.
    """
    yields = [{"root_lot_id": "C31K8", "wafer_id": "01", "lot_id": "C31K8.1",
               "lot_type": "PP", "yield": 90.0, "date": "2026-07-03"},
              {"root_lot_id": "C31K8", "wafer_id": "02", "lot_id": "C31K8.2",
               "lot_type": "ES", "yield": 70.0, "date": "2026-07-03"}]
    steps = [{"root_lot_id": "C31K8", "wafer_id": "01", "step_seq": "CC002000",
              "eqp_id": "ETCH9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"},
             {"root_lot_id": "C31K8", "wafer_id": "02", "step_seq": "CC002000",
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


def test_uniform_equipment_means_the_source_never_proved_wafer_granularity(tmp_path):
    """한 lot 이 한 챔버·한 PPID 로 돈 것은 정상이다 — 여기서 경고하면 오경보다.

    판정 대상은 **설비·챔버가 wafer 마다 갈리는 군**으로 좁힌다. 그런 군에서는 원천이
    그 스텝에서 wafer 단위 세부를 실제로 주고 있음이 증명되므로, "챔버는 갈리는데
    ppid 는 한 번도 안 갈린다" 가 비로소 의심스러운 조건이 된다. 설비·챔버도 안 갈리는
    군에서는 원천이 wafer 단위를 주는지 자체가 안 보이므로 할 말이 없다.
    """
    ys = [{"root_lot_id": "G44D4", "wafer_id": f"{i:02d}", "lot_id": "G44D4.1",
           "lot_type": "PP", "yield": 80.0, "date": "d"} for i in (1, 2, 3)]
    # lot 전원이 같은 설비·챔버·PPID (정상 운영에서 흔하다)
    st = [{"root_lot_id": "G44D4", "wafer_id": f"{i:02d}", "step_seq": "CC002000",
           "eqp_id": "E9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"}
          for i in (1, 2, 3)]
    report = li.load(ys, st, tmp_path / "t.db", verbose=False)

    assert report["ppid_grain"] == {"checkable": 0, "varying": 0}
    assert not any("마스터 단위 조인 의심" in i for i in report["issues"])


def test_equipment_alone_can_prove_wafer_granularity_without_any_chamber(tmp_path):
    """설비만 갈리고 `ch_id` 가 아예 없는 스텝도 판정 대상이다.

    `ch_id` 는 nullable 이고(단일 챔버 설비·챔버 개념 없는 스텝) 결측률이 높을 수 있어
    리포트가 `ch_id_null_rate` 를 따로 싣는다. `tool` 을 `ch_id` 만으로 잡거나
    `IFNULL` 을 빼면 그런 스텝 전부에서 검사가 조용히 꺼진다.
    """
    ys = [{"root_lot_id": "P11A1", "wafer_id": f"{i:02d}", "lot_id": "P11A1.1",
           "lot_type": "PP", "yield": 80.0, "date": "d"} for i in (1, 2, 3)]
    # 설비는 wafer 마다 갈리고 ch_id 는 원천에 없음. ppid 는 전원 동일(lot 마스터 grain)
    st = [{"root_lot_id": "P11A1", "wafer_id": f"{i:02d}", "step_seq": "CC002000",
           "eqp_id": f"E{i}", "ppid": "PPID_L", "timestamp": "t"} for i in (1, 2, 3)]
    report = li.load(ys, st, tmp_path / "t.db", verbose=False)

    assert report["ch_id_null_rate"] == 1.0        # 챔버 정보가 전혀 없는 상태
    assert report["ppid_grain"] == {"checkable": 1, "varying": 0}
    assert any("마스터 단위 조인 의심" in i for i in report["issues"])


def test_equipment_and_chamber_are_joined_with_a_separator(tmp_path):
    """설비·챔버를 이어붙일 때 구분자가 없으면 서로 다른 장비가 같은 값이 된다.

    `E1`+`2A` 와 `E12`+`A` 는 구분자가 없으면 둘 다 `E12A` 로 뭉쳐 판정 대상에서
    빠진다(항상 침묵 방향이라 오경보는 안 나지만, 검사가 조용히 꺼진다).
    """
    ys = [{"root_lot_id": "R33C3", "wafer_id": f"{i:02d}", "lot_id": "R33C3.1",
           "lot_type": "PP", "yield": 80.0, "date": "d"} for i in (1, 2)]
    st = [{"root_lot_id": "R33C3", "wafer_id": "01", "step_seq": "CC002000",
           "eqp_id": "E1", "ch_id": "2A", "ppid": "PPID_L", "timestamp": "t"},
          {"root_lot_id": "R33C3", "wafer_id": "02", "step_seq": "CC002000",
           "eqp_id": "E12", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"}]
    report = li.load(ys, st, tmp_path / "t.db", verbose=False)

    assert report["ppid_grain"] == {"checkable": 1, "varying": 0}
    assert any("마스터 단위 조인 의심" in i for i in report["issues"])


def test_grain_is_judged_per_step_not_per_lot(tmp_path, monkeypatch):
    """군은 (lot, 스텝) 이다 — 스텝 축을 빼면 실데이터에서 검사가 통째로 침묵한다.

    바깥 GROUP BY 에서 스텝을 빼면 한 lot 의 여러 스텝이 한 군으로 뭉친다. 스텝마다
    PPID 가 다른 건 당연하므로 `varying > 0` 이 항상 성립하고, 판정이 전역이라 전체가
    침묵한다 — 그런데 `[grain]` 줄은 0 아닌 숫자를 찍어 사람을 안심시킨다.
    """
    ys = [{"root_lot_id": "Q22B2", "wafer_id": f"{i:02d}", "lot_id": "Q22B2.1",
           "lot_type": "PP", "yield": 80.0, "date": "d"} for i in (1, 2)]
    # 2개 스텝, 둘 다 lot 마스터 grain (스텝끼리는 ppid 가 다르다 — 정상)
    st = [{"root_lot_id": "Q22B2", "wafer_id": f"{i:02d}", "step_seq": step,
           "eqp_id": "E9", "ch_id": ch, "ppid": f"PPID_{step}", "timestamp": "t"}
          for step in ("CC002000", "CC004000") for i, ch in zip((1, 2), "AB")]

    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", buf)
    report = li.load(ys, st, tmp_path / "t.db", verbose=True)
    buf.flush()
    out = buf.buffer.getvalue().decode("cp949")

    assert report["ppid_grain"] == {"checkable": 2, "varying": 0}
    assert any("마스터 단위 조인 의심" in i for i in report["issues"])
    # 비율의 **순서**까지 고정한다 — 체크리스트가 사람에게 이 줄에서 `0/N군` 을 읽으라고
    # 지시하므로, 뒤집히면(2/0) 판단을 정반대로 오도한다
    assert "0/2군" in out


def test_rework_rows_are_not_mistaken_for_wafer_level_variation(tmp_path):
    """재작업 행 1건이 검사를 꺼뜨리면 안 된다.

    판정이 전역(반례 1건이면 침묵)이라, 행 단위로 ppid 를 세면 **전 데이터에 이런 행이
    하나만 있어도** 검사가 통째로 무력화된다. 수백만 행 실데이터에서 중복 이력은
    예상되는 상태다(검사 #6 이 "재작업인지 확인" 이라고 말하는 이유).
    """
    ys = [{"root_lot_id": "D11A1", "wafer_id": f"{i:02d}", "lot_id": "D11A1.1",
           "lot_type": "PP", "yield": 80.0, "date": "d"} for i in (1, 2, 3)]
    # 챔버는 wafer 마다 갈리고(= 판정 대상) ppid 만 전원 동일 = lot 마스터 grain(틀림)
    st = [{"root_lot_id": "D11A1", "wafer_id": f"{i:02d}", "step_seq": "CC002000",
           "eqp_id": "E9", "ch_id": ch, "ppid": "PPID_L", "timestamp": "t"}
          for i, ch in zip((1, 2, 3), "ABC")]
    rework = dict(st[0])
    rework["ppid"] = "PPID_M"                 # 같은 wafer×스텝·같은 챔버, 다른 ppid
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
            "lot_type": "PP", "yield": 80.0, "date": "d"} for i in (1, 2)] +
          [{"root_lot_id": "E22B2", "wafer_id": f"{i:02d}", "lot_id": "E22B2.2",
            "lot_type": "ES", "yield": 80.0, "date": "d"} for i in (3, 4)])
    # 두 lot 모두 챔버는 갈린다(= 둘 다 판정 대상). ppid 는 lot .2 에서만 갈린다.
    st = ([{"root_lot_id": "E22B2", "wafer_id": "01", "step_seq": "CC002000",
            "eqp_id": "E9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"},
           {"root_lot_id": "E22B2", "wafer_id": "02", "step_seq": "CC002000",
            "eqp_id": "E9", "ch_id": "B", "ppid": "PPID_L", "timestamp": "t"},
           {"root_lot_id": "E22B2", "wafer_id": "03", "step_seq": "CC002000",
            "eqp_id": "E9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"},
           {"root_lot_id": "E22B2", "wafer_id": "04", "step_seq": "CC002000",
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
           "lot_type": "PP", "yield": 80.0, "date": "d"} for i in (1, 2, 3)]
    # 챔버는 갈린다 — 그래서 checkable 이 0 인 유일한 이유가 ppid 결측이 된다
    # (챔버까지 같으면 이 테스트는 NULL 필터 삭제를 못 잡는다)
    st = [{"root_lot_id": "F33C3", "wafer_id": f"{i:02d}", "step_seq": "CC002000",
           "eqp_id": "E9", "ch_id": ch, "timestamp": "t"}
          for i, ch in zip((1, 2, 3), "ABC")]
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


def test_help_text_survives_a_cp949_console():
    """`--help` 는 argparse 가 직접 찍으므로 `_say` 가 못 덮는다.

    help·description 문구에 cp949 밖 글자(em-dash·⚠️)를 하나 넣으면 `--help` 자체가
    UnicodeEncodeError 로 죽는다. 코드에는 그러지 말라는 주석이 있지만 주석은 강제력이
    없어서, 이 저장소에서 `_say` 가 구조적으로 보호할 수 없는 유일한 경로를 여기서 고정한다.
    """
    env = {**os.environ, "PYTHONIOENCODING": "cp949"}
    proc = subprocess.run([sys.executable, "-m", "data.load_internal", "--help"],
                          capture_output=True, env=env,
                          cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")


def test_script_path_execution_finds_the_repo_root():
    """`python data/load_internal.py` (스크립트 경로) 로도 돌아야 한다.

    스크립트 경로로 실행하면 `sys.path[0]` 은 **`data/`** 이고 CWD 는 들어가지 않는다.
    그래서 모듈 상단의 `sys.path.insert` 가 없으면 `import ya_config` 가 죽는다.
    사내에서 실제로 이 형태로 실행해 `ModuleNotFoundError` 를 봤고(2026-08-03),
    방어를 넣었지만 그 세 줄을 지워도 나머지 테스트는 전부 통과한다 — 여기서 잠근다.

    `PYTHONPATH` 를 지우고 돌린다. 안 그러면 상위 프로세스가 저장소 루트를 넘겨줘
    방어가 없어도 통과하는 공허한 테스트가 된다.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run([sys.executable, os.path.join("data", "load_internal.py"), "--help"],
                          capture_output=True, env=env, cwd=root)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
