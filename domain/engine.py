"""legend 어댑터 — commonality 후보를 게이트 계약(passes/value)으로 매핑한다.

commonality 는 판정하지 않는다(후보≠결론). 판별(passes)은 게이트가 suspect 를
모으기 위한 최소 신뢰선일 뿐이며, 반례 판별은 commonality 의 2×2(대조군 카운트)에
이미 내장돼 있다(c = 원인 거쳤는데 정상). 임계는 config 상수(실데이터 보며 조정).
"""

import ya_config
from tools import commonality as cm
from tools import metro_commonality as mcm

# 가설의 `tool` 필드 -> (실행 함수, 그 도구가 읽는 테이블). 기본은 step_history 축이다.
# metro 를 별도 도구로 둔 이유는 `tools/metro_commonality.py` 상단에 있다 — 요약하면
# 게이트가 "같은 도구 안 최고 점수" 를 비교하기 때문에 후보를 섞으면 서로를 누른다.
#
# 함수를 직접 담지 않고 람다로 감싸는 이유: 여기서 바인딩하면 모듈 속성을 갈아끼우는
# 테스트(monkeypatch)가 안 먹는다. 호출 시점에 이름을 다시 찾게 둔다.
TOOLS = {
    "step_history": lambda *a, **kw: cm.find_commonality(*a, **kw),
    "metro": lambda *a, **kw: mcm.find_metro_commonality(*a, **kw),
}
TOOL_TABLES = {"step_history": "step_history", "metro": "metro"}


def _passes(cand, min_score, min_target, status, ok):
    reasons = []
    if not ok:
        reasons.append(f"상태 {status} - ok 아님")
    if cand["score"] < min_score:
        reasons.append(f"분리 점수 {cand['score']} < {min_score}")
    if cand["target_pass"] < min_target:
        reasons.append(f"타깃 표본 {cand['target_pass']} < {min_target}")
    return (not reasons), ("; ".join(reasons) or None)


def evaluate(spec: dict, group_ids: list[str], control_ids: list[str]) -> dict:
    """spec['legend'] 로 commonality 실행 후 각 후보를 게이트 계약으로 매핑."""
    min_score = spec.get("min_score", ya_config.COMMONALITY_PASS_MIN_SCORE)
    min_target = spec.get("min_target", ya_config.COMMONALITY_PASS_MIN_TARGET)
    find = TOOLS[spec.get("tool", "step_history")]
    res = find(group_ids, control_ids, legend=spec["legend"])
    status = res.get("status")
    ok = status == "ok"

    candidates = []
    for cand in res.get("candidates", []):
        passes, reject = _passes(cand, min_score, min_target, status, ok)
        candidates.append({
            # 게이트가 조회할 유일한 키. 게이트는 이 문자열을 **파싱하지 않는다** —
            # 사전 조회에만 쓰므로 구분자가 값에 섞여도 안전하다. 콜론 형식을 쓰는
            # 이유는 감사 기록에서 사람이 읽을 수 있다는 것뿐이다.
            # level 을 빼면 안 된다 — 챔버 키가 eqp_id + "_" + ch_id 라서,
            # 이름이 "ETCH9_B" 인 설비와 (ETCH9, B) 챔버의 id 가 같아진다.
            "claim_id": f"{spec['id']}:{cand['level']}:{cand['step_seq']}:{cand['key']}",
            "value": [cand["step_seq"], cand["key"]],
            "passes": passes,
            "reject_reason": reject,
            "level": cand["level"],
            "key": cand["key"],
            "step_seq": cand["step_seq"],
            "score": cand["score"],
            "target_pass": cand["target_pass"], "target_total": cand["target_total"],
            "control_pass": cand["control_pass"], "control_total": cand["control_total"],
            "coverage_target": cand["coverage_target"],
            "coverage_control": cand["coverage_control"],
            # 이 후보가 가리키는 실제 wafer. 카운트만으로는 두 후보가 같은 wafer 를
            # 말하는지(교락) 다른 wafer 를 말하는지(독립 근거) 구분할 수 없다 —
            # 축이 여럿일 때 그 둘이 게이트에게 똑같아 보이는 것이 문제였다.
            "target_wafers": cand["target_wafers"],
            "control_wafers": cand["control_wafers"],
            # 게이트는 이 값을 **판정에 쓰지 않는다**(_passes 참조). 리포트와 감사
            # 기록에 흐르게 하는 것이 목적이다 - 자동 차단은 실데이터를 본 뒤에 얹는다.
            "p_permutation": cand.get("p_permutation"),
            # p 만 실으면 바닥값과 약한 신호가 같은 숫자로 보인다. 소표본에서는
            # p 가 1/(경우의 수) 밑으로 못 내려가므로 그 바닥값을 함께 보낸다 —
            # hypotheses.yaml 이 LLM 에게 이 필드를 읽으라고 지시한다.
            "p_min_possible": cand.get("p_min_possible"),
            "n_permutations_total": cand.get("n_permutations_total"),
        })
        # metro 후보만 갖는 것들. 이게 없으면 LLM 은 "THK >= 129.0" 이라는 key
        # 문자열을 다시 파싱해야 하고, 그러다 129.0 을 놓치거나 방향을 뒤집는다.
        for extra in ("item", "split_value", "split_direction"):
            if extra in cand:
                candidates[-1][extra] = cand[extra]
    return {
        "hypothesis_id": spec["id"],
        "legend": spec["legend"],
        "status": res.get("status"),
        "candidates": candidates,
        # 최상위 통계 — 후보별 p 는 "이 후보 하나" 를, 이 둘은 "목록 전체" 를 말한다.
        # yaml 이 LLM 에게 결과 최상위에서 읽으라고 지시하는 자리다.
        "fdr_table": res.get("fdr_table", []),
        "p_family_wise": res.get("p_family_wise"),
        "p_family_wise_min_possible": res.get("p_family_wise_min_possible"),
        "meta": res.get("meta"),
        "note": res.get("note"),
    }
