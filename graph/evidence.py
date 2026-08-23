"""도구 결과를 게이트가 읽는 구조화된 증거로 투영한다 (EvidenceBundle).

게이트가 findings 를 덕타이핑으로 훑던 것을 대체한다. **판별자는 `hypothesis_id`
키의 유무**다 — `domain/engine.py` 의 결과에는 있고 `tools/sensor_compare.py` 의
결과에는 없다. 예전 판별자였던 `"candidates" in result` 는 센서 결과에도 걸린다.

여기는 판정하지 않는다. 사실만 모으고, 판정은 `graph/nodes.py` 의 게이트가 한다.
상태를 저장하지 않는 순수 함수이므로 감사 기록(findings)이 유일한 출처로 남는다.
"""

from dataclasses import asdict, dataclass, field


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
    # 축마다 있고 없는 값들(coverage_*, metro 의 item·split_value·split_direction 등).
    # 예전에는 엔진이 실어도 여기서 통째로 잘려 **코드 게이트가 못 보는** 상태였다.
    # 축이 늘 때마다 이 dataclass 를 고치지 않으려고 한 자리에 모아 둔다.
    # frozen 이지만 dict 자체는 바뀔 수 있다 - 읽기 전용으로만 쓴다.
    extra: dict = field(default_factory=dict)


# Claim 이 1급 필드로 갖는 것들. build_bundle 이 나머지를 extra 로 몰아 넣을 때 쓴다.
_FIRST_CLASS_FIELDS = frozenset({
    "claim_id", "hypothesis_id", "step_seq", "key", "level", "passes",
    "reject_reason", "score", "target_pass", "target_total",
    "control_pass", "control_total", "p_permutation", "p_min_possible",
    "target_wafers", "control_wafers",
})


@dataclass(frozen=True)
class ClaimGroup:
    """**같은 wafer 집합**을 가리키는 claim 들을 하나로 접은 묶음.

    두 축이 각각 후보를 내면 그것이 독립 근거 둘인지 한 사실의 두 이름인지가
    갈린다. 더미 LOT2406 에서 챔버 `ETCH9_B` 와 레시피 `PPID_X` 는 정확히 같은
    3장을 가리킨다 - 근거가 둘이 아니라 하나이고, 둘을 따로 세면 확신도가 부풀고
    리포트가 길기만 한 거짓이 된다.

    반대로 **부분 겹침은 접지 않는다.** 겹치지 않는 그 wafer 들이 두 가설을 가르는
    유일한 정보이기 때문이다. 그래서 접기 기준은 임의 임계가 아니라 **집합 동일**이다.
    """
    claims: tuple[Claim, ...]      # rank key 로 정렬됨. [0] 이 대표

    @property
    def lead(self) -> Claim:
        return self.claims[0]

    @property
    def confounded(self) -> bool:
        """같은 wafer 를 두 가지 이상의 이름으로 설명하고 있다."""
        return len(self.claims) > 1

    @property
    def rank_key(self) -> tuple:
        """**우열을 가르는 값.** 이게 같으면 동점이고, 동점은 우열이 없다는 뜻이다."""
        return _rank_key(self.lead)

    @property
    def sort_key(self) -> tuple:
        """표시 순서를 고정하는 값. 우열 비교에 쓰면 안 된다."""
        return _sort_key(self.lead)


def _rank_key(claim: Claim) -> tuple:
    """순위 기준: 순열 p 가 먼저, 동점이면 분리 점수. **여기까지가 우열이다.**

    **원시 점수를 1순위로 쓰지 않는다.** 점수는 탐색 폭에 따라 부풀고(계측 축은
    무신호에서도 후보의 48.7%가 판별선을 넘는다), 축마다 그 부풀림 정도가 다르다.
    p 는 그 탐색까지 포함해 잰 값이라 축을 가로질러 비교할 수 있는 유일한 자다.
    p 가 없으면(순열을 껐으면) 최하위로 민다 - 없는 것을 좋은 것으로 읽으면 안 된다.
    """
    p = claim.p_permutation
    return (1.0 if p is None else p, -claim.score)


def _sort_key(claim: Claim) -> tuple:
    """정렬용. 우열(`_rank_key`)에 **표시 순서 고정용 tie-break** 만 덧붙인다.

    둘을 한 튜플로 겸하게 두었더니 게이트는 claim_id 까지 넣어 비교하고 등수 계산은
    빼고 비교해서, **동점이라고 보고해 놓고 게이트는 반려하는** 상태가 됐다.
    claim_id 는 우열이 아니므로 우열을 묻는 자리에서는 절대 보이면 안 된다.
    """
    return (*_rank_key(claim), claim.claim_id)


@dataclass(frozen=True)
class Bundle:
    claims: dict[str, Claim]      # claim_id -> Claim (미통과 후보도 담는다)
    statuses: dict[str, str]      # tool 이름 -> 마지막 실행의 status
    ran: set[str]                 # 유효한 결과를 낸 hyp_* 도구 이름

    def passing(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.passes]

    def ranked_groups(self) -> list[ClaimGroup]:
        """통과 후보를 wafer 집합으로 접고 순위를 매긴다 — **코드가 하는 판단.**

        예전에는 게이트가 "도구 안 최고 점수" 하나만 승인해서, 축이 여럿일 때 나머지
        근거가 리포트에 도달하지 못했다. 축을 가로질러 줄을 세우는 것이 이 함수다.

        wafer 목록이 없는 claim 은 접지 않는다 - 빈 집합끼리 같다고 묶으면 서로
        무관한 후보가 한 덩어리가 된다. 그런 claim 은 각자 홀로 선다.
        """
        buckets: dict = {}
        for claim in self.passing():
            # 목록이 없으면 claim_id 로 스스로만의 버킷을 만든다 (접기 대상 아님)
            if not claim.target_wafers:
                key = ("__unfoldable__", claim.claim_id)
            else:
                # **대조군까지 같아야 접는다.** 타깃만 보면 "타깃 3장 · 반례 0건" 과
                # "타깃 3장 · 반례 3건" 이 한 근거로 접히고, 그러면 리포트가
                # "구분되지 않는다" 고 말하면서 바로 옆에 구분되는 수치를 찍는다.
                # 반례가 있고 없고는 2x2 가 실제로 가르는 것이라, 그 차이가 남아
                # 있으면 두 후보는 같은 사실이 아니다.
                key = (frozenset(claim.target_wafers), frozenset(claim.control_wafers))
            buckets.setdefault(key, []).append(claim)

        groups = [ClaimGroup(claims=tuple(sorted(cs, key=_sort_key)))
                  for cs in buckets.values()]
        return sorted(groups, key=lambda g: g.sort_key)


def find_group(groups: list[ClaimGroup], claim_id: str) -> ClaimGroup | None:
    """이미 만들어 둔 순위 목록에서 그 claim 이 속한 묶음을 찾는다.

    Bundle 의 메서드로 두지 않는 이유: 그러면 호출할 때마다 `ranked_groups()` 를
    다시 돌게 되고, **매번 다른 객체가 나와** 호출부가 `is` 로 대조하면 조용히
    어긋난다(실제로 그렇게 틀렸다). 목록을 한 번 만들고 그것을 넘겨 쓴다.
    """
    for group in groups:
        if any(c.claim_id == claim_id for c in group.claims):
            return group
    return None


def group_to_dict(group: ClaimGroup, picked: bool = False) -> dict:
    """묶음을 상태·리포트가 들고 다닐 사전으로. 대표 + 같은 사실의 다른 이름들.

    `picked` 는 LLM 이 서술의 축으로 삼은 묶음인가다. 순위는 코드가 매기고 LLM 은
    그중 하나를 골라 이야기를 쓴다 - 둘을 구분해 두지 않으면 나중에 리포트만 보고
    "이 순서를 누가 정했나" 를 되짚을 수 없다.
    """
    lead = asdict(group.lead)
    lead["picked_by_llm"] = picked
    # 접힌 쪽도 **자기 수치를 그대로 들고 간다.** 이름만 남기면 접기가 곧 정보
    # 손실이 된다 - 같은 wafer 를 가리켜도 분모(target_total)와 p 는 다를 수 있고,
    # 그 차이가 "어느 이름으로 의뢰할 것인가" 를 정하는 재료다. 예를 들어 계측
    # 후보는 분모가 계측된 몇 장뿐이라 같은 wafer 를 가리켜도 근거의 무게가 다르다.
    lead["confounded_with"] = [
        {"claim_id": c.claim_id, "hypothesis_id": c.hypothesis_id,
         "level": c.level, "key": c.key, "step_seq": c.step_seq,
         "score": c.score, "p_permutation": c.p_permutation,
         "target_pass": c.target_pass, "target_total": c.target_total,
         "control_pass": c.control_pass, "control_total": c.control_total}
        for c in group.claims[1:]
    ]
    return lead


def groups_to_dicts(groups: list[ClaimGroup], picked: ClaimGroup | None = None) -> list[dict]:
    """순위 목록을 상태가 들고 다닐 사전 목록으로. **동점에 같은 등수를 준다.**

    번호만 매기면 `[근거 1]` 과 `[근거 2]` 가 강약으로 읽힌다. 그런데 p 도 점수도
    같으면 우열을 가릴 근거가 실제로 없다 - 그 "못 가린다" 를 표현하지 못하는 것이
    바로 이 프로젝트가 고치려는 결함이다(무엇을 모르는지 알아야 다음에 무엇을 볼지
    추천할 수 있다). 표시 순서를 고정하는 claim_id 는 `sort_key` 에만 있고 `rank_key`
    에는 없다 - 우열을 묻는 자리에 그것이 섞이면 안 된다.
    """
    out: list[dict] = []
    rank, prev = 0, None
    for i, group in enumerate(groups):
        key = group.rank_key              # 우열만. claim_id 는 여기 없다
        if key != prev:
            rank, prev = i + 1, key
        item = group_to_dict(group, picked=(group is picked))
        item["rank"] = rank
        out.append(item)

    counts: dict[int, int] = {}
    for item in out:
        counts[item["rank"]] = counts.get(item["rank"], 0) + 1
    for item in out:
        item["tied"] = counts[item["rank"]] > 1
    return out


def format_group_line(group: dict) -> str:
    """묶음 하나를 사람이 읽는 근거 줄로. 교락·동점이면 그 사실을 함께 적는다."""
    line = format_evidence_line(group)
    wafers = group.get("target_wafers") or ()
    if wafers:
        line += f" · 대상 {', '.join(wafers)}"
    others = group.get("confounded_with") or []
    if others:
        # 여기가 이 기능의 요점이다. 같은 wafer 를 두 이름으로 부르는 것을 근거 둘로
        # 세면 확신도가 부풀고, 하나를 버리면 의뢰 대상을 못 정한다. 둘 다 적되
        # **하나의 사실**임을 밝히고, 무엇을 더 봐야 갈리는지를 남긴다.
        #
        # 분모까지 적는 이유: 같은 wafer 를 가리켜도 그 wafer 가 **몇 장 중 몇 장인지**
        # 는 축마다 다르다(계측 축은 잰 wafer 만 분모다). 이름만 적으면 접힌 쪽이
        # 대표와 같은 무게인 것처럼 읽힌다.
        for o in others:
            detail = ""
            if o.get("target_total") is not None:
                detail = (f" · 타깃 {o['target_pass']}/{o['target_total']}"
                          f" · 대조군 {o['control_pass']}/{o['control_total']}")
                if o.get("p_permutation") is not None:
                    detail += f" · 순열 p {o['p_permutation']}"
            line += (f"\n        같은 wafer 를 {o['key']}({o['level']}) 로도 설명할 수 "
                     f"있다 (교락){detail} - 현재 증거로는 구분되지 않는다")
    if group.get("tied"):
        # 번호만 보면 앞선 것이 더 강해 보인다. 실제로는 순열 p 도 분리 점수도 같아
        # 우열을 가릴 근거가 없다 - 그 사실이 다음에 무엇을 볼지 정하는 입력이다.
        line += ("\n        같은 등수의 근거가 더 있다 - 순열 p 와 분리 점수가 같아 "
                 "어느 쪽이 유력한지 현재 증거로는 정할 수 없다")
    return line


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
                # 1급이 아닌 것은 버리지 않고 여기 모은다. 예전에는 coverage_* 와
                # metro 의 split_value 가 이 경계에서 조용히 사라져, LLM 은 보는데
                # **코드 게이트는 못 보는** 값이 됐다.
                extra={k: v for k, v in c.items()
                       if k not in _FIRST_CLASS_FIELDS and k != "value"},
            )
    return Bundle(claims=claims, statuses=statuses, ran=ran)
