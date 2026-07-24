"""legend 어댑터 — commonality 후보를 게이트 계약(passes/value)으로 매핑한다.

commonality 는 판정하지 않는다(후보≠결론). 판별(passes)은 게이트가 suspect 를
모으기 위한 최소 신뢰선일 뿐이며, 반례 판별은 commonality 의 2×2(대조군 카운트)에
이미 내장돼 있다(c = 원인 거쳤는데 정상). 임계는 config 상수(실데이터 보며 조정).
"""

import config
from tools import commonality as cm


def _passes(cand, min_score, min_target):
    reasons = []
    if cand["score"] < min_score:
        reasons.append(f"분리 점수 {cand['score']} < {min_score}")
    if cand["target_pass"] < min_target:
        reasons.append(f"타깃 표본 {cand['target_pass']} < {min_target}")
    return (not reasons), ("; ".join(reasons) or None)


def evaluate(spec: dict, group_ids: list[str], control_ids: list[str]) -> dict:
    """spec['legend'] 로 commonality 실행 후 각 후보를 게이트 계약으로 매핑."""
    min_score = spec.get("min_score", config.COMMONALITY_PASS_MIN_SCORE)
    min_target = spec.get("min_target", config.COMMONALITY_PASS_MIN_TARGET)
    res = cm.find_commonality(group_ids, control_ids, legend=spec["legend"])

    candidates = []
    for cand in res.get("candidates", []):
        passes, reject = _passes(cand, min_score, min_target)
        candidates.append({
            "value": [cand["process_step"], cand["key"]],
            "passes": passes,
            "reject_reason": reject,
            "level": cand["level"],
            "key": cand["key"],
            "process_step": cand["process_step"],
            "score": cand["score"],
            "target_pass": cand["target_pass"], "target_total": cand["target_total"],
            "control_pass": cand["control_pass"], "control_total": cand["control_total"],
            "coverage_target": cand["coverage_target"],
            "coverage_control": cand["coverage_control"],
        })
    return {
        "hypothesis_id": spec["id"],
        "legend": spec["legend"],
        "status": res.get("status"),
        "candidates": candidates,
        "meta": res.get("meta"),
        "note": res.get("note"),
    }
