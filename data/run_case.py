"""사례 DB 에 등록 가설을 LLM·EDS·센서 없이 직접 돌린다 (P1-4).

파이프라인이 쓰는 함수를 그대로 재사용한다 - 대조군은 `tools/grouping.py::select_control`,
축 평가는 `domain/engine.py::evaluate`, 접기·순위·문장은 `graph/evidence.py` 의
build_bundle/ranked_groups/groups_to_dicts/format_group_line. 스크립트가 새로
판단하는 것은 (i) 없는 DB (ii) 없는 타깃 (iii) 없는 테이블 (iv) 도구 예외 네
가지 입력 처리뿐이다(docs/tasks/case-run-prep/plan.md D1).

사례 DB 에는 EDS 인덱스가 없으므로 `tools/grouping.py::normalize_target` 은 쓰지
않는다 - 타깃은 명시 목록 그대로 쓴다(요구사항 2).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

# 스크립트 경로(`python data/run_case.py`)로 실행하면 sys.path[0] 이 data/ 라
# 저장소 루트가 빠진다. load_internal.py 와 같은 방어다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ya_config                       # noqa: E402
from ya_console import say as _say     # noqa: E402  cp949 콘솔 방어
from domain import engine, registry    # noqa: E402
from graph import evidence             # noqa: E402
from tools import grouping             # noqa: E402
from tools import yield_tools as yt    # noqa: E402

SETTINGS_KEYS = (
    "COMMONALITY_PASS_MIN_SCORE", "COMMONALITY_PASS_MIN_TARGET",
    "COMMONALITY_PERMUTATIONS", "COMMONALITY_TOP_K",
    "CONTROL_MIN_SIZE", "RESIDUAL_MIN_SCORE",
)

# 축 상태 중 evaluate() 의 note 를 함께 붙일 것들 - "볼 것이 없었다" 류.
_NOTE_STATUSES = ("no_signal", "no_paired_stratum", "insufficient_group")


def _table_exists(db_path: Path, table: str) -> bool:
    """가설이 읽는 테이블이 이 DB 에 있는가. 사례 DB 에는 metro 테이블이 없다
    (`data/load_internal.py` DDL 이 yield·step_history 만 만든다)."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _dedup(items: list[str]) -> list[str]:
    """입력 순서를 유지한 채 중복만 뺀다."""
    seen: set[str] = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def run_case(db_path, targets: list[str]) -> dict:
    db_path = Path(db_path)
    # is_file() 로 묶는다 - 디렉터리를 --db 로 주면 sqlite3.connect 가 그 자리에서
    # 바로 안 터지고(자물쇠 파일만 만들다 실패) 뒤늦게 알 수 없는 오류로 번진다.
    # "없는 DB" 와 같은 자리에서 같은 오류로 막는다(m4).
    if not db_path.is_file():
        raise FileNotFoundError(f"DB 없음: {db_path}")

    targets = _dedup(targets)
    if not targets:
        raise ValueError("타깃 목록이 비었다")

    original_db_path = ya_config.DB_PATH
    ya_config.DB_PATH = db_path
    try:
        target_rows = yt.get_wafers(targets)
        known = {r["wafer_id"] for r in target_rows}
        unknown = [w for w in targets if w not in known]

        result: dict = {
            "db": str(db_path.resolve()),
            "targets": targets,
            "unknown_targets": unknown,
            "target_root_lots": {},
            "control": None,
            "stopped": None,
            "axes": [],
            "groups": [],
            "settings": {k: getattr(ya_config, k) for k in SETTINGS_KEYS},
        }
        if unknown:
            result["stopped"] = "unknown_targets"
            return result

        root_lots: dict[str, int] = {}
        for r in target_rows:
            root_lots[r["root_lot_id"]] = root_lots.get(r["root_lot_id"], 0) + 1
        result["target_root_lots"] = root_lots

        control = grouping.select_control(targets)
        result["control"] = control
        if control["insufficient"]:
            result["stopped"] = "control_insufficient"
            return result

        specs = registry.load_hypotheses()
        findings = []
        for spec in specs:
            tool_key = spec.get("tool", "step_history")
            table = engine.TOOL_TABLES[tool_key]
            tool_name = f"hyp_{spec['id']}"
            axis = {"hypothesis_id": spec["id"], "tool": tool_name,
                    "outcome": None, "result": None, "error": None}

            if not _table_exists(db_path, table):
                axis["outcome"] = "no_table"
                axis["error"] = table
                result["axes"].append(axis)
                continue

            try:
                res = engine.evaluate(spec, targets, control["control_group"])
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                axis["outcome"] = "failed"
                axis["error"] = err
                result["axes"].append(axis)
                findings.append({"tool": tool_name, "result": err, "failed": True})
                continue

            axis["outcome"] = "ran"
            axis["result"] = res
            result["axes"].append(axis)
            findings.append({"tool": tool_name, "result": res})

        bundle = evidence.build_bundle(findings)
        groups = bundle.ranked_groups()
        group_dicts = evidence.groups_to_dicts(groups)
        for g in group_dicts:
            g["line"] = evidence.format_group_line(g)
        result["groups"] = group_dicts
        return result
    finally:
        ya_config.DB_PATH = original_db_path


def _render_control(control: dict) -> str:
    c_group = control["control_group"]
    sources = " · ".join(f"{rl} {len(ws)}" for rl, ws in sorted(control["sources"].items()))
    ys = control.get("yield_summary")
    y_str = ""
    if ys:
        y_str = (f" · 수율 중앙값 {ys['median']} · 임계 {ys['threshold']} 미만 "
                 f"{ys['n_below_threshold']}장")
    insuff = " (부족 - 파이프라인은 여기서 멈춘다)" if control["insufficient"] else ""
    return f"[대조군] {len(c_group)}장 (root_lot 별: {sources}){y_str}{insuff}"


def _render_axis(axis: dict) -> str:
    tool = axis["tool"]
    if axis["outcome"] == "no_table":
        return f"[축] {tool}  미적재(테이블 없음: {axis['error']})"
    if axis["outcome"] == "failed":
        return f"[축] {tool}  도구 실패: {axis['error']}"

    res = axis["result"]
    candidates = res.get("candidates", [])
    n_pass = sum(1 for c in candidates if c["passes"])
    status = res.get("status")
    note = ""
    if status in _NOTE_STATUSES and res.get("note"):
        note = f" · {res['note']}"
    pf, pf_floor = res.get("p_family_wise"), res.get("p_family_wise_min_possible")
    pf_str = f" · p_family_wise {pf} (바닥 {pf_floor})" if pf is not None else ""
    lines = [f"[축] {tool}  status={status}{note}  후보 {len(candidates)} "
             f"(통과 {n_pass}){pf_str}"]
    if candidates:
        # "#" 는 이 도구가 낸 순서(대개 score 내림차순)일 뿐 게이트 등수가
        # 아니다 - 등수는 아래 [순위 묶음] 절의 rank 뿐이다(m5, 혼동 방지).
        lines.append("  # | level | step | key | score | p (바닥, 바닥도달) | "
                      "타깃 | 대조 | 통과 | 제외 사유  (# = 도구 내 순서 - 게이트 등수가 아니다)")
        for i, c in enumerate(candidates, 1):
            p = c.get("p_permutation")
            p_str = (f"{p} ({c.get('p_min_possible')}, {c.get('p_at_floor')})"
                      if p is not None else "-")
            lines.append(
                f"  {i} | {c['level']} | {c['step_seq']} | {c['key']} | {c['score']} | "
                f"{p_str} | {c['target_pass']}/{c['target_total']} | "
                f"{c['control_pass']}/{c['control_total']} | {c['passes']} | "
                f"{c.get('reject_reason') or '-'}"
            )
    return "\n".join(lines)


def render(result: dict) -> str:
    """사람이 읽는 요약 - 사례 기록 양식 2·3절 순서(plan.md 출력 형식)."""
    lines = [f"[DB] {result['db']}"]

    if result["unknown_targets"]:
        lines.append(f"[타깃] 입력 {len(result['targets'])}장 중 DB 에 없음 "
                      f"{len(result['unknown_targets'])}장: "
                      f"{', '.join(result['unknown_targets'])}")
        return "\n".join(lines)

    targets = result["targets"]
    rl_str = " · ".join(f"{rl} {n}" for rl, n in sorted(result["target_root_lots"].items()))
    lines.append(f"[타깃] {len(targets)}장: {', '.join(targets)}            "
                 f"root_lot 별 타깃 수: {rl_str}")

    lines.append(_render_control(result["control"]))
    if result["stopped"] == "control_insufficient":
        return "\n".join(lines)

    s = result["settings"]
    lines.append(
        f"[설정] PASS_MIN_SCORE {s['COMMONALITY_PASS_MIN_SCORE']} · "
        f"PASS_MIN_TARGET {s['COMMONALITY_PASS_MIN_TARGET']} · "
        f"PERMUTATIONS {s['COMMONALITY_PERMUTATIONS']} · "
        f"TOP_K {s['COMMONALITY_TOP_K']} · CONTROL_MIN_SIZE {s['CONTROL_MIN_SIZE']}"
    )

    for axis in result["axes"]:
        lines.append(_render_axis(axis))

    lines.append("[순위 묶음] (게이트와 같은 접기·순위, 통과 후보만)")
    if not result["groups"]:
        lines.append("  (통과 후보 없음)")
    else:
        for g in result["groups"]:
            lines.append(f"  [{g['rank']}] {g['line']}")

    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="사례 DB 에 등록 가설을 LLM 없이 직접 돌린다 (P1-4)")
    ap.add_argument("--db", required=True, help="사례 DB 경로")
    ap.add_argument("--targets", required=True, metavar="W1,W2,...",
                    help="쉼표로 구분한 타깃 wafer_id 목록")
    ap.add_argument("--out", help="원시 결과를 JSON 으로 저장할 경로 (선택)")
    args = ap.parse_args(argv)

    # --out 검사는 아무것도 돌리기 전에 끝낸다(m4) - 뒤늦게 걸리면 이미 도구를
    # 다 돌린 뒤 저장 직전에 실패해 시간만 버린다.
    if args.out:
        out_path, db_path = Path(args.out), Path(args.db)
        # resolve() 비교만으로는 하드링크를 못 본다 - 파일이 둘 다 있으면 samefile 로도 본다.
        if out_path.resolve() == db_path.resolve() or (
                out_path.exists() and db_path.exists()
                and os.path.samefile(out_path, db_path)):
            _say(f"[오류] --out 이 --db 와 같은 파일이다: {out_path}")
            return 2
        if out_path.is_dir():
            _say(f"[오류] --out 이 폴더다: {out_path}")
            return 2
        if not out_path.parent.exists():
            _say(f"[오류] --out 의 상위 폴더가 없다: {out_path.parent}")
            return 2

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    if not targets:
        _say(f"[오류] --targets 에 유효한 wafer_id 가 없다: {args.targets!r}")
        return 2

    try:
        result = run_case(args.db, targets)
    except FileNotFoundError as e:
        _say(f"[오류] {e}")
        return 2
    except ValueError as e:
        _say(f"[오류] {e}")
        return 2
    except sqlite3.DatabaseError as e:
        # 0바이트 파일 등 "파일은 있는데 sqlite DB 가 아니다" 는 존재 검사로는
        # 안 걸린다 - 실제 쿼리에서만 터진다(m4).
        _say(f"[오류] DB 를 읽을 수 없다 (손상, sqlite 아님, 스키마 불일치): "
             f"{args.db} ({e})")
        return 2

    _say(render(result))

    if args.out:
        Path(args.out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        _say(f"[저장] {args.out}")

    return 2 if result["stopped"] == "unknown_targets" else 0


if __name__ == "__main__":
    raise SystemExit(main())
