"""진입점이 cp949 콘솔에서 출력을 통째로 잃지 않는지.

이슈 `.scratch/yield-agent-console-encoding/issues/01-cp949-crash-in-demo-entrypoints.md`.
`main.py` 는 그래프를 **다 돌린 뒤** 찍으므로, 출력 한 줄이 UnicodeEncodeError 로 죽으면
분석 결과 100% 를 잃는다(실측 기록은 이슈 파일에).

⚠️ 이 테스트가 공허해지는 함정 (`fix/ppid-grain-check` 에서 실제로 겪었다):
   이 저장소의 **authored 리터럴**로만 찌르면, 나중에 누가 그 리터럴에서 em-dash 를
   지우는 순간 방어를 통째로 제거해도 통과하게 된다. 그래서 여기서는 **데이터에서 오는
   문자열**(그래프 상태값·생성기 row)로 찌른다 — 그 안에 무엇이 들어올지는 이 저장소가
   통제하지 못한다(LLM 산출물·wafer_id·DB 경로).
"""

import io
import os
import subprocess
import sys

import main
from ya_console import say

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# cp949 에 없는 글자들. 데이터를 흉내 내는 값에만 넣는다.
DASH = "—"          # em-dash — LLM 산출물·기존 문구에 흔하다
WARN = "⚠"          # ⚠ — 도구 note 에 실려 올 수 있다


def _cp949_stdout(monkeypatch):
    """stdout 을 cp949 로 갈아끼우고, 나중에 읽을 버퍼를 돌려준다."""
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", buf)
    return buf


def _read(buf) -> str:
    buf.flush()
    return buf.buffer.getvalue().decode("cp949")


def test_say_keeps_the_line_when_the_console_cannot_encode_it(monkeypatch):
    """콘솔이 못 싣는 글자는 버리되 줄 자체는 남긴다."""
    buf = _cp949_stdout(monkeypatch)
    say(f"앞{DASH}뒤")
    out = _read(buf)

    assert "앞" in out and "뒤" in out          # 줄이 사라지면 안 된다
    assert DASH not in out                      # 못 싣는 글자만 빠진다


class _StubApp:
    """그래프 대신 고정 상태를 돌려준다 — 여기서 검증할 것은 출력 경로뿐이다."""

    def __init__(self, state):
        self._state = state

    def invoke(self, _inputs):
        return self._state


def _state_with_unencodable_content():
    """LLM·도구에서 흘러온 값에 cp949 밖 글자가 섞인 상태.

    실제로 `llm/client.py` 의 가설 문구가 지금 이 모양이다("...이 원인 — 효과크기 ...").
    다만 그 리터럴이 언제 바뀔지 모르므로 여기서는 상태값에 직접 넣는다.
    """
    return {
        "status_summary": f"대조군 78장 {DASH} 수율 중앙값 95.3",
        "target_group": ["W2406_06"],
        "control_group": ["W2406_01"],
        "finalize_status": None,
        "findings": [
            {"loop": 0, "tool": "normalize_target", "args": {}},
            {"loop": 1, "tool": "hyp_eqp_ch_commonality",
             "args": {"note": f"{WARN} 표본 부족"}, "thought": f"챔버 편중 {DASH} 대조"},
            {"loop": 2, "tool": "finalize",
             "args": {"hypothesis": f"CC002000 공정 ETCH9_B 편중이 원인 {DASH} rf_power"},
             "thought": "근거 충분", "result": "승인"},
        ],
        "report": f"[결론] CC002000 공정 ETCH9_B 편중이 원인 {DASH} 확신도 0.9",
    }


def test_main_prints_the_whole_report_when_content_has_unencodable_characters(monkeypatch):
    """내용에 cp949 밖 글자가 있어도 **마지막 줄까지** 나와야 한다.

    방어를 지우면 첫 위반 줄에서 죽고 그 뒤가 전부 사라진다 — 이 단언들이 그것을 잡는다.
    """
    state = _state_with_unencodable_content()
    monkeypatch.setattr(main, "build_graph", lambda: _StubApp(state))
    buf = _cp949_stdout(monkeypatch)

    main.run(["W2406_06"], "manual")
    out = _read(buf)

    assert "[현황 파악" in out                   # 죽던 첫 줄
    assert "[분석 루프" in out
    assert "hyp_eqp_ch_commonality" in out       # 도구 args 안의 글자로도 안 죽는다
    assert "[리포트" in out                      # 마지막 줄까지 도달
    assert "확신도 0.9" in out                   # 결론 본문이 남아야 한다


def test_dummy_generator_report_survives_a_cp949_console(monkeypatch):
    """생성기 리포트도 같은 모양이다 — DB·임베딩을 다 쓴 뒤에 찍는다.

    row 값(lot_id·정답지 라벨)은 생성기가 만드는 데이터라, 시나리오를 늘리면
    무엇이 들어올지 이 테스트가 통제하지 못한다. 그 경우를 여기서 만든다.
    """
    from data import generate_dummy as gd

    rows = [{"wafer_id": "W2406_02", "lot_id": gd.RECENT_LOT, "yield": 79.6,
             "_truth_defect": f"center_spot{DASH}A"}]
    buf = _cp949_stdout(monkeypatch)

    gd._report(rows, [[0.0]], ["W2406_02"])
    out = _read(buf)

    assert "총 wafer: 1" in out
    assert gd.RECENT_LOT in out                  # 마지막 절까지 도달
    assert "W2406_02" in out


def test_demo_entrypoint_exits_zero_on_a_cp949_console():
    """실제 데모 실행이 cp949 에서 끝까지 도는지 (이슈에 기록된 재현 그대로).

    위 테스트들은 stdout 만 갈아끼우므로, 프로세스 전체 경로에서 새는 출력은 못 본다.
    """
    env = {**os.environ, "PYTHONIOENCODING": "cp949"}
    proc = subprocess.run([sys.executable, "main.py"],
                          capture_output=True, env=env, cwd=ROOT)

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert b"[\xb8\xae\xc6\xf7\xc6\xae" in proc.stdout    # cp949 로 인코딩한 "[리포트"
