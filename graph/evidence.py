"""도구 결과를 게이트가 읽는 구조화된 증거로 투영한다 (EvidenceBundle).

게이트가 findings 를 덕타이핑으로 훑던 것을 대체한다. 도구 결과는 **두 갈래**로
받는다 — 1단 가설(`domain/engine.py`)은 `hypothesis_id` 키로, 2단 센서
(`tools/sensor_compare.py`)는 `kind == "sensor"` 로 가른다(`_is_sensor_result`).
둘 다 `"candidates" in result` 라 예전 판별자로는 구분되지 않는다. 센서도 Claim 이
되지만 `kind` 가 다르고, 근거로는 실리되 승인 지목 대상이 아니다
(`statistical_passing`).

여기는 판정하지 않는다. 사실만 모으고, 판정은 `graph/nodes.py` 의 게이트가 한다.
상태를 저장하지 않는 순수 함수이므로 감사 기록(findings)이 유일한 출처로 남는다.
"""

from dataclasses import asdict, dataclass, field

import ya_config


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
    # 이 후보가 어떤 종류의 증거인가. **게이트 승인 하한이 읽는 자리다.**
    # `_is_statistical` 로 대신하면 안 된다 - 그 함수는 "순열 참조 회차가 0이라 바닥이
    # 1.0" 인 1단 후보에도 False 를 주므로, 그것으로 승인을 막으면 이번 변경이 1단의
    # 승인 가능 범위까지 조용히 좁혀 2026-09-01 에 확정한 순위 계약이 흔들린다.
    kind: str = "statistical"
    p_permutation: float | None = None
    p_min_possible: float | None = None    # 이 표본이 낼 수 있는 최소 p (바닥값)
    # p 가 그 바닥에 닿았는가. **도구가 센 사실이다** - p 와 바닥은 4자리로 반올림돼
    # 오므로 여기서 두 숫자를 == 로 비교하면 참조 회차가 13,333 이상일 때 귀무가
    # 넘은 후보까지 바닥으로 읽힌다 (`tools/commonality.py::_null_distribution`).
    p_at_floor: bool | None = None
    # 이 후보가 가리키는 실제 wafer. 카운트만 담으면 두 후보가 **같은 3장**을 말하는지
    # **다른 3장**을 말하는지 게이트가 구분할 수 없다 - 축이 여럿일 때 한 사실의 두
    # 이름(교락)과 독립 근거 둘이 똑같아 보인다. 축 무관 필드라 1급으로 둔다
    # (metro 의 split_value 처럼 축마다 있고 없는 것과 다르다).
    target_wafers: tuple[str, ...] = ()
    control_wafers: tuple[str, ...] = ()
    # 이 후보를 정의한 legend 컬럼값 (설비 = {eqp_id}, 챔버 = {eqp_id, ch_id}).
    # 접힌 두 이름이 **한 설명의 두 해상도**인지 **다른 두 설명**인지를 코드가 가르는
    # 재료다. wafer 목록과 같은 이유로 1급이다 - 축 무관이고, 게이트가 읽는다.
    level_columns: dict = field(default_factory=dict)
    # 축마다 있고 없는 값들(coverage_*, metro 의 item·split_value·split_direction 등).
    # 예전에는 엔진이 실어도 여기서 통째로 잘려 **코드 게이트가 못 보는** 상태였다.
    # 축이 늘 때마다 이 dataclass 를 고치지 않으려고 한 자리에 모아 둔다.
    # frozen 이지만 dict 자체는 바뀔 수 있다 - 읽기 전용으로만 쓴다.
    extra: dict = field(default_factory=dict)


# Claim 이 1급 필드로 갖는 것들. build_bundle 이 나머지를 extra 로 몰아 넣을 때 쓴다.
_FIRST_CLASS_FIELDS = frozenset({
    "claim_id", "hypothesis_id", "step_seq", "key", "level", "passes",
    "reject_reason", "score", "target_pass", "target_total",
    "control_pass", "control_total", "kind", "p_permutation", "p_min_possible",
    "p_at_floor",
    "target_wafers", "control_wafers", "level_columns",
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
        """같은 wafer 를 두 가지 이상의 이름으로 설명하고 있다.

        **접혔다는 사실만 말한다.** 그것이 다른 두 설명(교락)인지 한 설명의 두
        해상도(설비 ⊃ 챔버)인지는 `_is_roll_up_of` 가 가른다 - 리포트와 LLM 에는
        두 갈래가 다른 문장으로 나간다.
        """
        return len(self.claims) > 1

    @property
    def sort_key(self) -> tuple:
        """표시 순서를 고정하는 값. 우열 비교에 쓰면 안 된다."""
        return _sort_key(self.lead)


def _order_key(claim: Claim) -> tuple:
    """**표시 순서와 대표 선정에만 쓰는 전순서 키.** 우열은 `dominates` 가 가른다.

    예전에는 이 키가 우열까지 겸했는데, 순열 p 의 바닥이 후보마다 달라지면서
    (2026-08-29) 그 비교가 **신호 세기가 아니라 참조집합 크기**를 재게 됐다.
    우열 판정은 `dominates` 로 옮겼다. 여기 남은 일은 "같은 등수 안에서 매번 같은
    순서로 보여 주는 것" 뿐인데 그것도 필요하다 - 리포트를 실행마다 비교해야 한다.
    """
    p = claim.p_permutation
    return (1.0 if p is None else p, -claim.score)


def _is_statistical(claim: Claim) -> bool:
    """이 후보에게 통계적 근거가 있는가. **없으면 순위에서 별도 등급으로 내린다.**

    바닥이 1.0 이라는 것은 참조 회차가 0 이라는 뜻이고, 그것은 "우연이다" 가 아니라
    **"비교할 귀무 표본이 하나도 없었다"** 다
    (`tools/commonality.py::_null_distribution`). 분리 점수가 1.0 이어도 통계적
    근거는 없으므로, p 를 아예 안 내는 증거(2단 센서·잔차)와 같은 등급이다.

    바닥만 없고 p 는 있는 조합은 도구가 둘을 같이 싣기 때문에 실경로에서는 안
    생긴다(`domain/engine.py::evaluate`). 생기면 보수적으로 비통계로 떨어뜨린다.
    """
    if claim.p_permutation is None:
        return False
    floor = claim.p_min_possible if claim.p_min_possible is not None else 1.0
    return floor < 1.0


def dominates(a: ClaimGroup, b: ClaimGroup) -> bool:
    """a 가 b 를 **확실히** 이기는가. 아니면 둘은 갈리지 않는 것이다.

    비교는 두 후보가 **둘 다 표현할 수 있는 해상도**에서만 한다. 순열 p 의 바닥은
    1/(참조회차+1) 이고 참조 회차는 후보마다 다르므로(참조집합을 표본 크기가 같은
    회차로 좁힌 2026-08-29 변경), 거친 쪽 바닥 아래로는 두 후보 모두 말할 수 있는
    것이 없다. 그 아래를 비교하면 순위가 **신호 세기가 아니라 참조집합 크기**를
    따라간다 - 참조 8회의 완전 분리 후보가 참조 300회의 약한 후보에게 진다.

    비통계 쌍은 p 계산을 **건너뛴다.** 없는 값을 1.0 으로 채워 넣으면 "참조 0회라
    p 가 1.0" 인 후보와 "p 를 아예 안 낸" 후보가 같은 값이 되어, 나중에 등급 판정을
    고칠 때 한쪽이 조용히 따라 움직인다.
    """
    x, y = a.lead, b.lead
    sx, sy = _is_statistical(x), _is_statistical(y)
    if sx != sy:
        return sx                      # 통계 등급이 비통계 등급을 이긴다
    if sx:
        floor = max(x.p_min_possible, y.p_min_possible)   # 공통 해상도
        px, py = max(x.p_permutation, floor), max(y.p_permutation, floor)
        if px != py:
            return px < py
    # 센서는 점수로 안 가른다. `tools/sensor_compare.py` 가 결과 note 에 스스로
    # 적는다 - "연동된 센서는 함께 움직이므로 순위만으로 원인을 가릴 수 없다." 센서
    # 효과크기(d)를 우열로 쓰면 그 경고가 투영 경계에서 정확히 뒤집힌다: 상관된
    # 센서 top-K 가 1등부터 꼴찌까지 엄격한 서열로 리포트에 나간다. 스텝을 넘으면
    # 더 나쁘다 - 센서 수가 스텝마다 달라(수백 개 vs 수십 개) 최대 d 의 분포 자체가
    # 탐색 폭을 타므로, 방금 위에서 p 비교를 축 안으로 가둔 것과 같은 이유로 축을
    # 넘는 d 비교도 막아야 한다. hypothesis_id 로는 못 막는다 - 센서는 전부 ""
    # 이므로 이 줄만으로는 "모든 센서가 같은 축" 이 되어 버린다.
    if x.kind == "sensor" or y.kind == "sensor":
        return False
    # p 로는 안 갈렸다. 점수는 탐색 폭에 따라 부풀고 그 정도가 축마다 다르므로
    # **같은 축 안에서만** 쓴다 - 축을 넘으면 탐색이 넓은 축이 늘 이긴다.
    return x.hypothesis_id == y.hypothesis_id and x.score > y.score


def layer_ranks(groups: list[ClaimGroup]) -> list[int]:
    """각 묶음의 등수. **지배당하지 않은 것 전부가 1등**이고, 걷어내고 반복한다.

    정렬로 못 하는 이유: **비교 불가는 이행적이지 않다.** 바닥 0.111 인 X 와 p
    0.05 인 Y 는 동점인데(공통 해상도 0.111 에서 둘 다 그 이하) Y 는 p 0.002 인
    Z 에게 진다 - X~Y, X~Z 인데 Z>Y 다. 비교자로 정렬하면 입력 순서에 따라 답이
    달라진다.

    지배 관계 자체는 이행적이라 순환이 없지만(설계 문서 §2.1) 안전판을 둔다 -
    증명이 닿지 않는 자리에서 순환이 한 번 나면 무한 루프이고, 그건 분석 전체가
    멎는다는 뜻이다.

    **끝나는 것과 맞는 것을 따로 보장한다.** 층은 묶음 수를 넘을 수 없으므로 루프를
    그 수로 묶는다 - 안전판이 하는 일은 순환일 때 등수를 **맞게** 매기는 것이고,
    안 끝나는 것을 막는 것은 루프 경계다. 둘을 한 곳에 걸면 안전판이 사라졌을 때
    실패 모드가 행(hang)이 되어 스위트가 통째로 멎는다(2026-08-28 사고).
    """
    ranks = [0] * len(groups)
    remaining = list(range(len(groups)))
    for layer in range(1, len(groups) + 1):
        if not remaining:
            break
        front = [i for i in remaining
                 if not any(dominates(groups[j], groups[i])
                            for j in remaining if j != i)]
        if not front:                       # 안전판: 순환이면 남은 전부를 한 층으로
            front = list(remaining)
        for i in front:
            ranks[i] = layer
        taken = set(front)
        remaining = [i for i in remaining if i not in taken]
    return ranks


def _is_roll_up_of(coarse: Claim, fine: Claim) -> bool:
    """coarse 가 fine 을 **굵은 해상도로 부른 같은 설명**인가.

    설비 `PHOT7` 과 챔버 `PHOT7_B` 는 한 설명의 두 해상도이고, 챔버와 레시피는 다른 두
    설명이다. 앞의 것을 "현재 증거로는 구분되지 않는다" 로 내보내면 엔지니어에게는
    당연한 소리이고, 그 문장이 진짜 미해결과 섞이면 어느 쪽이 조사할 거리인지 흐려진다.

    **같은 가설이어야 한다.** 컬럼만 보면 metro `{step_seq, item}` 이 스텝 통과
    `{step_seq}` 를 포함하지만, '그 스텝을 지났다' 와 '그 스텝의 계측값이 높다' 는
    해상도 차이가 아니라 서로 다른 두 설명이다. 한 legend 안의 레벨들만이 같은 사실을
    굵게/가늘게 부르기로 선언된 것이다.

    **같은 스텝이어야 한다.** 그 선언은 한 스텝 안에서만 참이다 - `level_columns` 에는
    legend 컬럼만 있고 step_seq 는 없는데(eqp_ch 의 컬럼은 eqp_id·ch_id 뿐이다) 후보
    키는 (level, step, key) 라 같은 설비가 스텝마다 별개 후보로 나온다. 스텝을 안 보면
    'CC001000 의 PHOT7' 과 'CC003000 의 PHOT7_B' 가 같은 설명이 돼 진짜 교락이 리포트에서
    사라진다. 같은 설비를 여러 레이어에서 쓰거나 재작업 스텝에서 다시 타면 바로 이 모양이다.
    """
    if coarse.hypothesis_id != fine.hypothesis_id or coarse.step_seq != fine.step_seq:
        return False
    a, b = coarse.level_columns, fine.level_columns
    if not a or not b or not a.keys() < b.keys():   # 진부분집합만 (동률은 같은 레벨)
        return False
    return all(b.get(col) == val for col, val in a.items())


def _fold_key(claim: Claim) -> tuple:
    """묶음 **안에서** 대표를 고르는 순서. 우열이 같으면 더 세밀한 쪽이 대표다.

    대표는 리포트가 지목하는 이름이고 곧 의뢰 대상이다. 설비와 챔버가 접혔을 때 굵은
    쪽을 지목하면 조사 범위를 쓸데없이 넓힌다. 지금까지 챔버가 앞선 것은 claim_id
    문자열에서 'c' < 'e' 였기 때문일 뿐이라 이름이 바뀌면 뒤집힌다.

    ⚠️ **이 키는 `passes` 를 안 본다.** 안전한 이유는 현재 어떤 호출부도 통과
    claim 과 미통과(통계) claim 을 한 목록에 섞지 않기 때문이다 - (2a)는
    `not statistical_passing()` 이 하한이라 `passing() + residuals` 안의 비센서
    claim 은 전부 `passes=False` 이고, 센서는 `build_bundle` 이 `target_wafers` 를
    안 실어(위 `__unfoldable__` 분기) 항상 자기 혼자만의 묶음에 남는다 - 통과
    claim 과 미통과(통계) claim 이 지금은 같은 버킷에 들어올 길이 없다. 이 전제가
    깨지는 순간(통계적 claim 이 통과할 수 있는 목록으로 `ranked_groups(passing() +
    residuals)` 류를 부르는 새 호출부가 생기면) 잔차가 대표(`_fold_key` 가 더
    작은 p 를 우선하므로)가 되고 통과 claim 은 `confounded_with`/`rolled_up_as`
    로 밀려나는데, 그 자리는 `passes` 키 자체가 없어(`group_to_dict::folded`)
    묶음 전체가 `[잔차]` 로 찍힌다 - 통과 근거가 있는데도.
    """
    return (*_order_key(claim), -len(claim.level_columns), claim.claim_id)


def _sort_key(claim: Claim) -> tuple:
    """정렬용. 표시 순서(`_order_key`)에 **표시 순서 고정용 tie-break** 만 덧붙인다.

    둘을 한 튜플로 겸하게 두었더니 게이트는 claim_id 까지 넣어 비교하고 등수 계산은
    빼고 비교해서, **동점이라고 보고해 놓고 게이트는 반려하는** 상태가 됐다.
    claim_id 는 우열이 아니므로 우열을 묻는 자리에서는 절대 보이면 안 된다.
    """
    return (*_order_key(claim), claim.claim_id)


@dataclass(frozen=True)
class Bundle:
    claims: dict[str, Claim]      # claim_id -> Claim (미통과 후보도 담는다)
    statuses: dict[str, str]      # tool 이름 -> 마지막 실행의 status
    ran: set[str]                 # 유효한 결과를 낸 hyp_* 도구 이름
    # **실행 중 터진 도구 이름** (`ran` 과 배타적이다 - 어느 시점에든 유효한 결과를
    # 낸 축은 여기 없다. 집합 연산이라 순서를 안 본다: 성공 뒤 재실행에서 터진 축도
    # 빠지는데, 그 축의 결과는 실제로 손에 있으므로 옳다).
    # `ran` 에서 빼는 것만으로는 '안 돌린 축' 과 구분되지 않아, 게이트가 방금 터진
    # 도구를 다시 부르라고 이름을 대고 리포트는 시도조차 안 한 것처럼 적었다.
    # 조치가 다르다: 인프라 확인 vs 축을 더 보기. 판정은 여기서 안 한다.
    #
    # 표시는 `tools_node` 가 붙인다(`failed: True`). 오류 문자열의 **모양으로 넘겨짚지
    # 않는 이유**는 dict 가 아닌 결과가 실패만이 아니기 때문이다 - "분석 종료로 생략"
    # 도 문자열이고, 그것을 실패로 세면 없는 장애를 보고한다.
    failed: frozenset[str] = frozenset()
    # 뒤 실행에 밀려 claims 에서 **실제로 후보가 빠진** findings 의 위치. 폐기 사실을
    # 밖으로 내보내는 자리다 - 폐기는 여기서만 일어나는데 findings 는 그대로 리포트
    # LLM 에 넘어가고 운영 프롬프트가 그 수치를 "그대로 인용하라" 고 지시하므로,
    # 말해 주지 않으면 게이트가 버린 후보를 리포트가 근거로 인용한다.
    #
    # **후보를 안 낸 실행은 안 담는다.** 버릴 것이 없으므로 대체가 아니고, 담으면
    # 리포트에 "그 실행의 후보는 근거가 아니다" 라는 없는 후보에 대한 문장이 붙는다.
    superseded: frozenset[int] = frozenset()
    # 대체된 claim_id -> 그것을 낸 도구. **위치가 아니라 이름으로 답하는 자리**다.
    # LLM 은 재실행 뒤에도 앞 실행의 claim_id 를 대화 문맥에서 그대로 보고 있어
    # (tools_node 가 도구 결과를 ToolMessage 로 싣는다) 그것을 제출한다. 게이트가
    # "도구 결과에 없다" 고 답하면 거짓이고, 그 문구는 '지어낸 claim_id' 분기라
    # LLM 은 자기가 환각을 낸 줄 알고 같은 문맥을 다시 읽는다.
    dropped_claims: dict[str, str] = field(default_factory=dict)

    def passing(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.passes]

    def statistical_passing(self) -> list[Claim]:
        """**지목 가능한** 통과 후보. `passing()` 은 근거로 실을 것 전부다.

        둘을 가르는 이유: 센서는 근거로 인용되지만 원인 확정의 지목 대상이 아니다
        (다중비교 보정을 일부러 안 한 도구다). 이 구분이 없으면 센서만 통과한 상태에서
        게이트가 승인도 물러섬도 못 하고 루프 한계까지 왕복한다.
        """
        return [c for c in self.passing() if c.kind != "sensor"]

    def residuals(self) -> list[Claim]:
        """판별선 아래의 1단 후보 중 '약한 신호' 라고 부를 수 있는 것.

        `passing()` 을 넓히지 않고 문을 따로 내는 이유: `statistical_passing()`
        (지목 가능한 것)과 `ranked_groups()`(1등 층 = 게이트 승인 조건)가 둘 다
        `passing()` 을 타므로, 넓히는 순간 **잔차로 confirmed 가 나간다.**

        status 를 `statuses[c.tool]` 로 보는 이유: status 는 후보가 아니라 그 실행의
        성질이고, `reject_reason` 문자열을 파싱하는 것은 claim_id 에서 금지한 짓이다.
        """
        return [c for c in self.claims.values()
                if not c.passes
                # 센서는 자기 판별선(0.8)을 갖고 이미 근거 전용이다
                and c.kind != "sensor"
                # "볼 것이 없었다"(no_paired_stratum 등)는 약한 신호가 아니다
                and self.statuses.get(c.tool) == "ok"
                and c.target_pass >= ya_config.COMMONALITY_PASS_MIN_TARGET
                and c.score >= ya_config.RESIDUAL_MIN_SCORE]

    def ranked_groups(self, claims: list[Claim] | None = None) -> list[ClaimGroup]:
        """통과 후보를 wafer 집합으로 접고 순위를 매긴다 — **코드가 하는 판단.**

        예전에는 게이트가 "도구 안 최고 점수" 하나만 승인해서, 축이 여럿일 때 나머지
        근거가 리포트에 도달하지 못했다. 축을 가로질러 줄을 세우는 것이 이 함수다.

        wafer 목록이 없는 claim 은 접지 않는다 - 빈 집합끼리 같다고 묶으면 서로
        무관한 후보가 한 덩어리가 된다. 그런 claim 은 각자 홀로 선다.

        `claims` 를 주면 그 목록을 대신 줄 세운다 - 잔차 경로가 **같은 접기·순위
        규칙**을 타게 하려는 것이다. 기본값은 통과 후보(`passing()`)이며, 기본값을
        바꾸면 확정 경로가 조용히 달라진다.
        """
        buckets: dict = {}
        for claim in (self.passing() if claims is None else claims):
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

        groups = [ClaimGroup(claims=tuple(sorted(cs, key=_fold_key)))
                  for cs in buckets.values()]
        groups.sort(key=lambda g: g.sort_key)          # 같은 등수 안의 표시 순서
        # **등수를 먼저 본다.** 표시 순서(전순서 키)와 등수가 어긋나면 리포트에서
        # `[근거 2]` 가 `[근거 1]` 위에 찍힌다 - 바닥에 걸린 후보는 p 가 커서
        # 전순서로는 뒤인데 등수는 1등일 수 있다. 파이썬 정렬은 안정적이라 같은
        # 등수 안에서는 위에서 잡은 표시 순서가 그대로 유지된다.
        ranks = layer_ranks(groups)
        return [g for _, g in sorted(zip(ranks, groups), key=lambda pair: pair[0])]


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
    if group.lead.kind == "sensor":
        # **가짜 2x2 를 여기서 막는다.** 아래 `folded()` 의 센서 분기는 실제로는
        # 안 닿는다 - 센서는 wafer 목록이 없어 늘 홀로 서므로 `group.claims[1:]` 가
        # 비어 있다. 나가는 길은 이 대표 dict 이고, `llm/client.py` 가 그것을 JSON
        # 으로 덤프해 "수치를 그대로 인용하라" 와 함께 리포트 LLM 에 넘긴다.
        # 투영이 채워 둔 통과 카운트 0 이 분모(n_target=12)와 나란히 실리면 "타깃
        # 0/12 · 대조군 0/40" 이라는 **일어나지도 않은 대조 실패**가 산문에 찍힌다.
        # 분모는 남긴다 - 효과크기는 표본 수와 함께 읽어야 하고 근거 줄이 그 값을 쓴다.
        del lead["target_pass"], lead["control_pass"]
    lead["picked_by_llm"] = picked
    # 접힌 쪽도 **자기 수치를 그대로 들고 간다.** 이름만 남기면 접기가 곧 정보
    # 손실이 된다 - 같은 wafer 를 가리켜도 분모(target_total)와 p 는 다를 수 있고,
    # 그 차이가 "어느 이름으로 의뢰할 것인가" 를 정하는 재료다. 예를 들어 계측
    # 후보는 분모가 계측된 몇 장뿐이라 같은 wafer 를 가리켜도 근거의 무게가 다르다.
    def folded(c: Claim) -> dict:
        base = {"claim_id": c.claim_id, "hypothesis_id": c.hypothesis_id,
                "level": c.level, "key": c.key, "step_seq": c.step_seq,
                "score": c.score, "kind": c.kind}
        if c.kind == "sensor":
            # 2x2 키를 아예 안 싣는다. target_total 자리에는 n_target(예: 12) 이
            # 온다 - 0 을 그대로 실으면 "타깃 0/0" 이 아니라 "타깃 0/12" 같은
            # 그럴듯한 가짜 2x2 가 찍힌다. `_folded_detail` 은 target_total 유무로만
            # 분기하므로 여기서 아예 안 실어야 막힌다.
            return base
        return {**base, "p_permutation": c.p_permutation,
                "target_pass": c.target_pass, "target_total": c.target_total,
                "control_pass": c.control_pass, "control_total": c.control_total}

    # **접힌 이유를 두 갈래로 나눈다.** 굵은 해상도로 부른 같은 설명(설비 ⊃ 챔버)과
    # 다른 두 설명(챔버 vs 레시피)은 엔지니어에게 완전히 다른 정보다 - 앞의 것은 조사할
    # 거리가 아니고 뒤의 것만이 "다음에 무엇을 볼까" 의 입력이다. 한 목록에 담고 항목마다
    # 구분을 붙이는 대신 키를 나누는 이유: LLM 프롬프트가 목록 단위로 지시하므로,
    # 한 목록이면 두 문장을 다르게 쓰라는 지시를 걸 자리가 없다.
    others, resolutions = [], []
    for c in group.claims[1:]:
        rel = _resolution_of(c, group)
        (resolutions if rel else others).append({**folded(c), **(rel or {})})
    lead["confounded_with"] = others
    lead["rolled_up_as"] = resolutions
    return lead


def _resolution_of(claim: Claim, group: ClaimGroup) -> dict | None:
    """이 후보가 묶음 안에서 **같은 설명의 다른 해상도**인가. 아니면 None.

    대표하고만 대보면 안 된다. 분리 점수는 분모를 타므로(챔버 분모는 ch_id 결측 wafer 를
    뺀다) 굵은 쪽이 대표가 될 수 있고, 제3의 가설이 1등이면 설비·챔버가 둘 다 대표와
    무관해진다. 그 두 경우에 판정이 통째로 꺼져 "구분되지 않는다" 가 돌아왔다.

    상대를 함께 돌려주는 이유: 문장이 "대조군에 'PHOT7 통과 · PHOT7_B 미통과' 인 wafer 가
    없다" 라고 **두 이름을 대고** 주장하는데, 상대가 늘 대표인 것은 아니다.

    **세밀한 쪽은 대표와의 관계에서만 접는다.** 굵은 이름은 언제나 다른 후보를 되풀이한
    것이라 근거로 셀 수 없지만, 세밀한 이름은 대표와 경합하는 진짜 후보일 수 있다
    (레시피가 1등이면 챔버는 레시피의 경쟁 설명이다 - 설비의 세부라는 이유로 접으면
    경합 관계가 사라진다).
    """
    lead = group.lead
    if _is_roll_up_of(claim, lead):
        return {"resolution": "coarser", "of": lead.key}
    if _is_roll_up_of(lead, claim):
        return {"resolution": "finer", "of": lead.key}
    for other in group.claims[1:]:
        if other is not claim and _is_roll_up_of(claim, other):
            return {"resolution": "coarser", "of": other.key}
    return None


def _tie_reason(group: ClaimGroup, peers: list[ClaimGroup]) -> str:
    """**왜** 갈리지 않는가. 사유마다 엔지니어가 할 일이 다르다.

    - `resolution`: 어느 한쪽의 p 가 **공통 해상도에 걸려 있다**. 걸린 값은 "그
      이하" 라는 뜻이라 진짜 우열을 알 수 없다. **표본을 늘리면 갈릴 수 있다** -
      참조 회차가 늘면 바닥이 내려간다.
    - `cross_axis`: p 는 둘 다 실측값인데 같고, 축이 달라 분리 점수를 안 쓴다.
      표본을 더 모아도 **이 규칙으로는 영원히 안 갈린다** - 두 축을 직접 가르는
      대조를 찾아야 한다.
    - `identical`: 축과 무관하게 p 도 점수도 같다. 같은 축이었어도 안 갈렸다.
      두 후보가 같은 wafer 를 다르게 부르는 것은 아닌지(교락) 부터 본다.
    - `no_statistics`: 어느 쪽도 귀무 표본이 없다. 순위 이전의 문제다 - **표본을
      늘리면 풀릴 수 있다**(참조 회차가 늘면 통계적 근거가 생긴다).
    - `sensor_correlated`: 층이 **전부** 센서다. `dominates` 의 센서
      하한(`if x.kind == "sensor" or y.kind == "sensor": return False`)은
      의도된 거부라 표본을 아무리 늘려도 **영원히** 안 갈린다 - 도구 자신의
      note 그대로 "연동된 센서는 함께 움직이므로 효과크기 순위만으로는 원인을
      가릴 수 없다." `no_statistics` 와 헷갈리면 안 된다 - 그건 "아직 근거가
      없다"(모으면 풀린다)로 읽히는데, 이건 "이 규칙으로는 원천적으로 비교하지
      않는다"다.

    하나로 뭉뚱그리면 안 되는 이유가 이것이다. "해상도에서 갈리지 않는다" 만 적으면
    `cross_axis` 인 엔지니어가 wafer 를 더 모으고, 그래도 안 갈린다. 거꾸로도 같다 -
    바닥에 걸린 것을 `cross_axis` 로 부르면 갈릴 수 있는 것을 포기시킨다.

    같은 등수 안에서는 통계/비통계 등급이 섞이지 않는다 - `dominates` 가 통계
    등급을 비통계 등급보다 위로 올리므로 둘이 같은 층에 설 수 없다(`resolution`
    이하 세 갈래는 그래서 대표 하나의 등급만 봐도 된다). 다만 **비통계 등급 안에서는
    kind 가 섞일 수 있다** - 센서와 참조 회차 0인 1단 후보는 둘 다 `_is_statistical`
    이 False 라 센서 하한으로 갈리지 않고 같은 층에 묶인다. 그래서 `sensor_correlated`
    판정만은 대표 하나가 아니라 **층 전체**(peers 까지)를 보는데, 조건은 "하나라도"
    가 아니라 **"전부"** 다: 그 섞인 층은 표본을 모으면 갈린다(1단 후보가 통계 등급이
    되는 순간 `sx != sy` 가 센서 하한보다 먼저 걸려 1단이 이긴다). 하나라도로 물으면
    갈릴 수 있는 것에 "영원히 안 갈린다" 를 붙여 조사를 포기시킨다 - 이 docstring 이
    바로 위에서 경고하는 오안내를 센서 갈래로 되풀이하는 것이다.
    """
    lead = group.lead
    leads = [lead, *(p.lead for p in peers)]
    if all(c.kind == "sensor" for c in leads):
        return "sensor_correlated"
    if not _is_statistical(lead):
        return "no_statistics"
    # **clamp 가 우열을 덮었는지**를 묻는다. "원 p 가 다른가" 로 물으면 놓치는 경우가
    # 있다 - 두 후보의 p 가 우연히 같아도 한쪽이 자기 바닥에 걸려 있으면 그 값은
    # "그 이하" 이므로, 참조 회차를 늘리면 실제로 갈린다. 그때 축 탓을 하면
    # "더 모아도 소용없다" 는 정반대 안내가 나간다.
    floor = max(c.p_min_possible for c in leads)
    if any(c.p_permutation <= floor for c in leads):
        return "resolution"
    # 축이 다른 것만으로는 부족하다. **점수까지 같으면** 같은 축이었어도 갈리지
    # 않았을 것이므로, 축 탓을 하면 "점수가 갈랐을 텐데" 로 잘못 읽힌다.
    if any(c.hypothesis_id != lead.hypothesis_id and c.score != lead.score
           for c in leads):
        return "cross_axis"
    return "identical"


def groups_to_dicts(groups: list[ClaimGroup], picked: ClaimGroup | None = None) -> list[dict]:
    """순위 목록을 상태가 들고 다닐 사전 목록으로. **동점에 같은 등수를 준다.**

    번호만 매기면 `[근거 1]` 과 `[근거 2]` 가 강약으로 읽힌다. 그런데 두 후보가
    **함께 표현할 수 있는 해상도**에서 갈리지 않으면 우열을 가릴 근거가 실제로 없다
    - 그 "못 가린다" 를 표현하지 못하는 것이 바로 이 프로젝트가 고치려는 결함이다
    (무엇을 모르는지 알아야 다음에 무엇을 볼지 추천할 수 있다). 등수는 `layer_ranks`
    가 지배 관계로 매긴다 - 표시 순서를 고정하는 `sort_key` 는 우열을 묻는 자리에
    절대 들어가면 안 된다.

    동점이면 **사유까지** 싣는다(`_tie_reason`). 사유마다 다음 행동이 다르다.
    """
    out: list[dict] = []
    for group, rank in zip(groups, layer_ranks(groups)):
        item = group_to_dict(group, picked=(group is picked))
        item["rank"] = rank
        out.append(item)

    by_rank: dict[int, list[ClaimGroup]] = {}
    for group, item in zip(groups, out):
        by_rank.setdefault(item["rank"], []).append(group)
    for group, item in zip(groups, out):
        peers = [g for g in by_rank[item["rank"]] if g is not group]
        item["tied"] = bool(peers)
        if peers:
            item["tie_reason"] = _tie_reason(group, peers)
    return out


_TIE_REASONS = {
    "resolution": "이 표본들이 낼 수 있는 해상도에서는 갈리지 않아",
    "cross_axis": "순열 p 가 같고 축이 달라 분리 점수로는 가르지 않아",
    "identical": "순열 p 도 분리 점수도 같아",
    "no_statistics": "어느 쪽도 통계적 근거가 없어",
    "sensor_correlated": "연동된 센서는 함께 움직여 효과크기 순위만으로는 가릴 수 없어",
}


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
            line += (f"\n        같은 wafer 를 {o['key']}({o['level']}) 로도 설명할 수 "
                     f"있다 (교락){_folded_detail(o)} - 현재 증거로는 구분되지 않는다")
    # 포함관계는 **다른 문장으로 적는다.** 접기 기준이 대조군 집합까지 같을 것이므로,
    # 대조군 중 그 설비를 지났으면서 이 챔버는 아닌 wafer 가 하나라도 있으면 두 후보는
    # 애초에 안 접힌다 - 즉 접혔다는 사실 자체가 "그 대조가 없다" 의 증명이다. 그래서
    # "구분되지 않는다" 로 끝내지 않고 무엇을 보면 갈리는지를 적는다. 조치도 다르다:
    # 교락은 다른 축을 더 보는 것이고, 이건 대조군 범위를 넓히는 것이다.
    for o in group.get("rolled_up_as") or []:
        # 방향과 상대를 문장이 그대로 말한다. 상대가 늘 대표인 것은 아니다 - 제3의
        # 가설이 1등이면 설비가 대는 상대는 대표가 아니라 챔버다.
        coarse = o.get("resolution") != "finer"
        wide, narrow = (o["key"], o["of"]) if coarse else (o["of"], o["key"])
        line += (f"\n        {'굵은' if coarse else '세밀한'} 해상도로는 "
                 f"{o['key']}({o['level']}) 다{_folded_detail(o)} - 대조군에 "
                 f"'{wide} 통과 · {narrow} 미통과' 인 wafer 가 없어 둘을 가를 대조가 없다")
    if group.get("tied"):
        # 번호만 보면 앞선 것이 더 강해 보인다. 실제로는 갈리지 않는데, **왜 못
        # 가리는지에 따라 다음에 할 일이 다르다** - 표본을 늘리면 갈리는 경우와
        # 늘려도 안 갈리는 경우를 한 문장으로 뭉개면 엔지니어가 헛수고를 한다.
        # 사유가 없는 사전(옛 상태에서 실려 온 것)이면 이유를 지어내지 않는다.
        #
        # "근거" 가 아니라 "항목" 이다 - 이 줄은 이 함수를 부르는 `group_to_dict`
        # 가 만든 아무 묶음에나 붙는데, weak_signal 경로에서는 그 묶음이 잔차일
        # 수 있다(잔차끼리도 동점일 수 있다). 브랜치 이전에는 통과 claim 만
        # 리포트에 닿아 "근거" 가 맞았지만, 지금은 `[잔차]` 줄 위에도 이 문장이
        # 찍힌다 - 판별선을 못 넘은 후보를 근거로 단정하는 다른 자리들과 같은
        # 이유로 중립어를 쓴다.
        why = _TIE_REASONS.get(group.get("tie_reason"), "우열을 가릴 근거가 없어")
        line += (f"\n        같은 등수의 항목이 더 있다 - {why} 어느 쪽이 유력한지 "
                 f"현재 증거로는 정할 수 없다")
    return line


def _folded_detail(o: dict) -> str:
    """접힌 후보의 수치. 이름만 적으면 대표와 같은 무게인 것처럼 읽힌다.

    같은 wafer 를 가리켜도 **몇 장 중 몇 장인지**는 이름마다 다르다 - 챔버 분모는
    ch_id 가 결측인 wafer 를 빼므로 설비 분모와 같지 않을 수 있다.
    """
    if o.get("target_total") is None:
        return ""
    detail = (f" · 타깃 {o['target_pass']}/{o['target_total']}"
              f" · 대조군 {o['control_pass']}/{o['control_total']}")
    if o.get("p_permutation") is not None:
        detail += f" · 순열 p {o['p_permutation']}"
    return detail


def format_evidence_line(claim: dict) -> str:
    """Claim 사전(`asdict(Claim)` 결과)을 사람이 읽는 근거 한 줄로 렌더링한다.

    게이트 승인 verdict(`graph/nodes.py`)와 리포트 `[근거]` 줄(`report_node`)이
    같은 본문을 문자 그대로 복제하던 것을 여기 하나로 모았다.
    """
    if claim.get("kind") == "sensor":
        # 2x2 도 순열 p 도 없다. 있는 것은 효과크기와 두 분포뿐이고, 그 둘을 표본 수와
        # 함께 읽어야 한다 - 표본이 작으면 효과크기가 커지므로 n 을 떼면 거짓말이 된다.
        # `ex[...]` 다 - `.get` 이 아니다. 통계 분기 아래의 `claim['target_pass']`
        # 와 같은 실패 모드를 쓴다: target_mean 이 사라지면 조용히 "평균 None" 을
        # 찍는 대신 KeyError 로 죽어야 한다 - 이 함수의 취지가 "숫자가 없는 게
        # 아니라 틀린 숫자가 나가는 것" 을 막는 것이다.
        ex = claim["extra"]
        return (f"{claim['claim_id']} · 효과크기 {claim['score']} · "
                f"타깃 n={claim['target_total']} 평균 {ex['target_mean']} · "
                f"대조군 n={claim['control_total']} 평균 {ex['control_mean']}")
    line = (f"{claim['claim_id']} · 분리 점수 {claim['score']} · "
            f"타깃 {claim['target_pass']}/{claim['target_total']} 통과 · "
            f"대조군 {claim['control_pass']}/{claim['control_total']} 통과")
    p = claim.get("p_permutation")
    if p is not None:
        line += f" · 순열 p {p}"
        floor = claim.get("p_min_possible")
        # 바닥이 1.0 이면 **비교할 귀무 표본이 하나도 없었다**는 뜻이다 (참조집합이
        # 표본 크기로 좁혀지므로 0회가 될 수 있다). 아래 딱지를 그대로 붙이면
        # "이 표본이 낼 수 있는 최강" 이라는 **정반대 뜻**이 되고, 분리 점수 1.0 과
        # 나란히 나가면 엔지니어가 그것을 근거로 설비를 세운다.
        if floor == 1.0:
            line += " (비교 가능한 귀무 표본이 없어 판단 불가)"
        # 바닥값에 닿았으면 "약한 신호" 가 아니라 "이 표본이 낼 수 있는 최강" 이다.
        # 소표본에서 p 는 1/(참조 회차+1) 밑으로 못 내려간다 - 표시가 없으면
        # 같은 숫자가 정반대 뜻으로 읽힌다.
        #
        # **판정은 도구가 센 사실로 한다.** 여기서 `floor == p` 로 물으면 두 값이
        # 4자리로 반올림돼 있어 참조 회차가 13,333 이상일 때 1/13334 과 2/13334 이
        # 같은 숫자가 되고, 귀무가 넘은 후보에 정반대 딱지가 붙는다.
        elif claim.get("p_at_floor"):
            line += " (이 표본의 최소값)"
    return line


def _is_hypothesis_result(result) -> bool:
    return (isinstance(result, dict)
            and "hypothesis_id" in result and "candidates" in result)


def _is_sensor_result(result) -> bool:
    """2단 센서 결과인가. **판별자는 `kind` 다.**

    `candidates` 유무로 가르면 가설 결과와 섞이고, `sensor_name` 같은 후보 내부 키로
    가르면 후보가 0건인 경로(no_signal·insufficient_sample)를 못 알아본다.
    """
    return (isinstance(result, dict)
            and result.get("kind") == "sensor" and "candidates" in result)


def build_bundle(findings: list[dict]) -> Bundle:
    """감사 기록에서 가설 도구의 결과만 골라 Claim 사전으로 투영한다.

    `ran` 은 "호출됐다" 가 아니라 **"유효한 결과를 냈다"** 다. 인자 오류로 실패한
    도구는 결과가 dict 가 아니라 오류 문자열이므로 들어오지 않는다.

    실패한 도구는 대신 `failed` 로 모은다. 예전에는 그냥 빠져서 '아직 안 돌린 축' 과
    한 덩어리였고, 그 결과 게이트가 **방금 터진 도구를 다시 부르라고** 이름을 댔다.
    """
    claims: dict[str, Claim] = {}
    statuses: dict[str, str] = {}
    ran: set[str] = set()
    crashed: set[str] = set()
    # 위치 -> 그 실행이 내놨다가 재실행에 밀려 나간 claim_id 들. **끝까지 살아남지
    # 못한 것이 있을 때만** 대체로 친다(아래에서 거른다). claim_id 는 그룹 인자와
    # 무관하게 만들어지므로(`domain/engine.py`) 인자가 같은 재실행은 같은 claim_id 를
    # 그대로 되살린다 - 잃은 것이 없는데 대체로 표시하면 리포트가 자기모순을 낸다:
    # `[근거]` 로 실린 바로 그 claim 을 sys 프롬프트가 "인용하지 마라" 로 막는다.
    lost_at: dict[int, set[str]] = {}
    dropped_claims: dict[str, str] = {}
    # tool -> 지금 claims 에 들어 있는 후보를 낸 실행의 위치. **후보를 낸 실행만**
    # 담는다(빈손 실행은 버릴 것이 없어 대체의 주체도 대상도 아니다).
    claims_from: dict[str, int] = {}

    for i, f in enumerate(findings):
        result = f.get("result")
        if _is_sensor_result(result):
            # **ran / statuses / 폐기 장부에 넣지 않는다.** 그 셋은 '등록 축 커버리지'
            # 전용 어휘라, 센서 status 가 섞이면 게이트 (3) 의 `uncomputable` 이 영영
            # False 가 되고 센서의 no_signal 이 1단의 것으로 둔갑한다.
            # 폐기도 안 건다: claim_id 에 step_seq 가 들어가 같은 스텝 재호출은 같은
            # 키로 덮어써지고, 다른 스텝 호출은 대체가 아니라 다른 질문이다.
            tool = f.get("tool", "")
            for c in result["candidates"]:
                claim_id = c.get("claim_id")
                if not claim_id:
                    continue
                claims[claim_id] = Claim(
                    claim_id=claim_id, tool=tool, kind="sensor",
                    # 등록 가설이 아니다. hypothesis_id="" 가 실제로 읽히는 자리는
                    # `_is_roll_up_of`(coarse.hypothesis_id != fine.hypothesis_id
                    # 줄 - 다만 level_columns 가 비어 있어 이미 False 로 떨어진다)와
                    # `_tie_reason`(다만 그 줄은 lead 가 통계적일 때만 닿는데 센서는
                    # 늘 비통계라 역시 안 닿는다) 뿐이다. `dominates` 에서는 아무
                    # 일도 안 한다 - 센서가 낀 쌍은 통계 등급 분기(sx != sy)나 센서
                    # 하한(`if x.kind == "sensor" or y.kind == "sensor": return
                    # False`)에서 먼저 걸려 hypothesis_id 를 비교하는 줄까지 가지
                    # 못한다.
                    hypothesis_id="",
                    # 센서 후보 dict 에는 step_seq 키가 없다 (claim_id 문자열 안에만
                    # 있는데, 그것을 파싱하지 않기로 했다). 대신 감사 기록의 도구
                    # 인자(`f["args"]["step_seq"]`, tools_node 가 주입)에서 읽는다.
                    step_seq=str(c.get("step_seq") or f.get("args", {}).get("step_seq") or ""),
                    key=c.get("sensor_name", ""), level="sensor",
                    passes=bool(c.get("passes")),
                    reject_reason=c.get("reject_reason"),
                    score=float(c.get("effect_size") or 0.0),
                    # 2x2 가 아니다. 분모(n)만 참이고 pass 카운트는 없는 값이라
                    # 0 으로 두되 렌더러가 kind 로 막는다.
                    target_pass=0, target_total=int(c.get("n_target") or 0),
                    control_pass=0, control_total=int(c.get("n_control") or 0),
                    # wafer 목록을 안 싣는다: 한 호출의 top-K 는 전부 같은 집합이라
                    # 실으면 서로 다른 센서 열 개가 한 덩어리로 접힌다.
                    # extra 에서 1급으로 옮겨 간 키를 다시 뺀다 - 안 빼면 같은 사실이
                    # 두 이름(score/effect_size, target_total/n_target, control_total/
                    # n_control)으로 겹쳐 실려, 나중에 렌더러가 어느 쪽을 읽을지 정해야
                    # 하고 한쪽만 고치면 조용히 어긋난다. target_mean·control_mean·
                    # target_std·control_std 는 1급 자리가 없으므로 그대로 남긴다 -
                    # 근거 줄이 그 넷을 읽는다.
                    extra={k: v for k, v in c.items()
                           if k not in _FIRST_CLASS_FIELDS
                           and k not in ("sensor_name", "effect_size",
                                         "n_target", "n_control")},
                )
            continue
        if not _is_hypothesis_result(result):
            if f.get("failed"):
                crashed.add(f.get("tool", ""))
            continue
        tool = f.get("tool", "")
        ran.add(tool)
        statuses[tool] = result.get("status", "")
        # 재실행이면 앞 결과를 버린다 — 그룹이 바뀐 재실행에서 옛 후보는 거짓이다
        # (group_ids/control_ids 중 하나만 바뀌어도 분모가 달라진다). 인자가 같으면
        # 도구가 결정적이라 같은 후보가 다시 만들어져 손실이 없다.
        if tool in claims_from:
            gone = {k for k, v in claims.items() if v.tool == tool}
            lost_at[claims_from.pop(tool)] = gone
            dropped_claims.update({k: tool for k in gone})
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
                p_at_floor=c.get("p_at_floor"),
                # frozen dataclass 라 tuple 로 받는다. 도구가 아직 안 싣는 경우
                # (센서 등 다른 형태의 결과)에도 빈 튜플로 안전하게 떨어진다.
                target_wafers=tuple(c.get("target_wafers") or ()),
                control_wafers=tuple(c.get("control_wafers") or ()),
                level_columns=dict(c.get("level_columns") or {}),
                # 1급이 아닌 것은 버리지 않고 여기 모은다. 예전에는 coverage_* 와
                # metro 의 split_value 가 이 경계에서 조용히 사라져, LLM 은 보는데
                # **코드 게이트는 못 보는** 값이 됐다.
                extra={k: v for k, v in c.items()
                       if k not in _FIRST_CLASS_FIELDS and k != "value"},
            )
            # 후보를 하나라도 실었을 때만 "이 실행이 지금 claims 의 주인" 이 된다.
            claims_from[tool] = i
    # **끝까지 살아남지 못한 claim 이 있는 실행만** 대체로 친다. 되살아난 claim 은
    # 잃은 것이 아니므로, 그 실행만 밀려났다고 표시하면 리포트가 [근거] 로 싣는
    # claim 을 동시에 "인용하지 마라" 로 막는 상반된 지시가 나간다.
    surviving = set(claims)
    superseded = frozenset(i for i, lost in lost_at.items() if lost - surviving)
    return Bundle(claims=claims, statuses=statuses, ran=ran,
                  # 어느 시점에든 결과를 낸 축은 실패가 아니다 - 그 축은 봤다.
                  failed=frozenset(crashed - ran),
                  superseded=superseded,
                  dropped_claims={k: v for k, v in dropped_claims.items()
                                  if k not in surviving})
