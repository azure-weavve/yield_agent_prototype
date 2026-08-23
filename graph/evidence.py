"""도구 결과를 게이트가 읽는 구조화된 증거로 투영한다 (EvidenceBundle).

게이트가 findings 를 덕타이핑으로 훑던 것을 대체한다. **판별자는 `hypothesis_id`
키의 유무**다 — `domain/engine.py` 의 결과에는 있고 `tools/sensor_compare.py` 의
결과에는 없다. 예전 판별자였던 `"candidates" in result` 는 센서 결과에도 걸린다.

여기는 판정하지 않는다. 사실만 모으고, 판정은 `graph/nodes.py` 의 게이트가 한다.
상태를 저장하지 않는 순수 함수이므로 감사 기록(findings)이 유일한 출처로 남는다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Claim:
    """도구가 발급한 후보 하나. LLM 이 만들어낼 수 없는 값들이다."""
    claim_id: str
    tool: str                 # findings 의 tool 이름 (hyp_eqp_ch_commonality)
    hypothesis_id: str
    step_seq: str
    key: str
    level: str
    passes: bool
    reject_reason: str | None
    score: float
    target_pass: int
    target_total: int
    control_pass: int
    control_total: int
    p_permutation: float | None = None
    p_min_possible: float | None = None    # 이 표본이 낼 수 있는 최소 p (바닥값)
    # 이 후보가 가리키는 실제 wafer. 카운트만 담으면 두 후보가 **같은 3장**을 말하는지
    # **다른 3장**을 말하는지 게이트가 구분할 수 없다 - 축이 여럿일 때 한 사실의 두
    # 이름(교락)과 독립 근거 둘이 똑같아 보인다. 축 무관 필드라 1급으로 둔다
    # (metro 의 split_value 처럼 축마다 있고 없는 것과 다르다).
    target_wafers: tuple[str, ...] = ()
    control_wafers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Bundle:
    claims: dict[str, Claim]      # claim_id -> Claim (미통과 후보도 담는다)
    statuses: dict[str, str]      # tool 이름 -> 마지막 실행의 status
    ran: set[str]                 # 유효한 결과를 낸 hyp_* 도구 이름

    def passing(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.passes]

    def top_score(self, tool: str) -> float | None:
        """그 도구 안에서 통과 후보의 최고 점수. legend 가 다르면 비교 대상이 아니다."""
        scores = [c.score for c in self.claims.values() if c.tool == tool and c.passes]
        return max(scores) if scores else None


def format_evidence_line(claim: dict) -> str:
    """Claim 사전(`asdict(Claim)` 결과)을 사람이 읽는 근거 한 줄로 렌더링한다.

    게이트 승인 verdict(`graph/nodes.py`)와 리포트 `[근거]` 줄(`report_node`)이
    같은 본문을 문자 그대로 복제하던 것을 여기 하나로 모았다.
    """
    line = (f"{claim['claim_id']} · 분리 점수 {claim['score']} · "
            f"타깃 {claim['target_pass']}/{claim['target_total']} 통과 · "
            f"대조군 {claim['control_pass']}/{claim['control_total']} 통과")
    p = claim.get("p_permutation")
    if p is not None:
        line += f" · 순열 p {p}"
        # 바닥값에 닿았으면 "약한 신호" 가 아니라 "이 표본이 낼 수 있는 최강" 이다.
        # 소표본에서 p 는 1/(섞는 경우의 수+1) 밑으로 못 내려간다 - 표시가 없으면
        # 같은 숫자가 정반대 뜻으로 읽힌다.
        if claim.get("p_min_possible") == p:
            line += " (이 표본의 최소값)"
    return line


def _is_hypothesis_result(result) -> bool:
    return (isinstance(result, dict)
            and "hypothesis_id" in result and "candidates" in result)


def build_bundle(findings: list[dict]) -> Bundle:
    """감사 기록에서 가설 도구의 결과만 골라 Claim 사전으로 투영한다.

    `ran` 은 "호출됐다" 가 아니라 **"유효한 결과를 냈다"** 다. 인자 오류로 실패한
    도구는 결과가 dict 가 아니라 오류 문자열이므로 들어오지 않는다 — 게이트는
    그 도구를 계속 요구하고, 무한 재시도는 루프 한계가 잡는다.
    """
    claims: dict[str, Claim] = {}
    statuses: dict[str, str] = {}
    ran: set[str] = set()

    for f in findings:
        result = f.get("result")
        if not _is_hypothesis_result(result):
            continue
        tool = f.get("tool", "")
        ran.add(tool)
        statuses[tool] = result.get("status", "")
        # 재실행이면 앞 결과를 버린다 — 그룹이 바뀐 재실행에서 옛 후보는 거짓이다
        claims = {k: v for k, v in claims.items() if v.tool != tool}
        for c in result["candidates"]:
            claim_id = c.get("claim_id")
            if not claim_id:                       # claim_id 없는 후보는 지목 불가
                continue
            claims[claim_id] = Claim(
                claim_id=claim_id,
                tool=tool,
                hypothesis_id=result["hypothesis_id"],
                step_seq=c.get("step_seq", ""),
                key=c.get("key", ""),
                level=c.get("level", ""),
                passes=bool(c.get("passes")),
                reject_reason=c.get("reject_reason"),
                score=float(c.get("score") or 0.0),
                target_pass=int(c.get("target_pass") or 0),
                target_total=int(c.get("target_total") or 0),
                control_pass=int(c.get("control_pass") or 0),
                control_total=int(c.get("control_total") or 0),
                p_permutation=c.get("p_permutation"),
                p_min_possible=c.get("p_min_possible"),
                # frozen dataclass 라 tuple 로 받는다. 도구가 아직 안 싣는 경우
                # (센서 등 다른 형태의 결과)에도 빈 튜플로 안전하게 떨어진다.
                target_wafers=tuple(c.get("target_wafers") or ()),
                control_wafers=tuple(c.get("control_wafers") or ()),
            )
    return Bundle(claims=claims, statuses=statuses, ran=ran)
