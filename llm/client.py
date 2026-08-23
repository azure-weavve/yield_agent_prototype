"""LLM 클라이언트 인터페이스 + 구현(스크립트형 mock / 사내 OpenAI 호환).

분석 루프의 두 LLM 호출 지점을 단일 인터페이스로 추상화한다:
  - analyze_step     : 누적 messages -> tool call 또는 finalize 를 담은 AIMessage
  - generate_report  : 감사 기록(findings) -> 원인 리포트 (수치는 tool 결과 그대로)

수치 계산은 도구 계층이 담당하고, LLM 은 "어떤 분석을 할지 판단"과 표현만 맡는다.
"""

import json
import re
import uuid
from abc import ABC, abstractmethod

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import ya_config
from tools.agent_tools import TOOLS_BY_NAME


class LLMClient(ABC):
    @abstractmethod
    def analyze_step(self, messages: list) -> AIMessage:
        """누적 대화를 보고 다음 행동(tool call / finalize)을 결정."""
        ...

    @abstractmethod
    def generate_report(
        self,
        target_wafers: list[str],
        target_source: str,
        target_group: list[str],
        status_summary: str,
        findings: list[dict],
        hypothesis: str | None,
        confidence: float | None,
        finalize_status: str | None = None,
        claims: list[dict] | None = None,
    ) -> str:
        """감사 기록을 근거로 원인 리포트 생성.

        finalize_status 가 "inconclusive"(루프 한계 도달)면 결론을 확정 톤이 아니라
        "미확정 + 유력 가설(후보)" 톤으로 서술해야 한다.
        claims 는 게이트가 접고 줄 세운 근거 **목록**이다 - 수치를 그대로 인용하고
        바꾸지 않는다. 하나만 고르지 마라: 순위는 코드가 매긴 것이고, `picked_by_llm`
        이 붙은 것은 서술의 축일 뿐 나머지가 덜 중요하다는 뜻이 아니다.
        `confounded_with` 가 있는 항목은 **같은 wafer 를 다른 이름으로도 설명할 수
        있다**는 뜻이니, 둘 중 하나로 단정하지 말고 구분이 안 된다는 사실을 적어라.
        """
        ...


# EQP_CH 가 갈렸어도 **반드시 함께 보는** 축. 챔버와 레시피는 같은 스텝의 같은 wafer 를
# 두 이름으로 부르는 일이 흔하다(더미 RECENT_LOT 에서 ETCH9_B 와 PPID_X 가 정확히 같은
# 3장을 가리킨다). 챔버가 갈렸다고 여기서 멈추면 그 교락이 아예 관측되지 않아, 게이트가
# 접을 것도 없고 리포트는 근거 하나만 든 채 확신에 찬 문장을 쓴다 — 다축 집계가 잡으려는
# 상황 자체가 데모에서 한 번도 안 나타난다.
_ALWAYS_WITH_CHAMBER = (
    "hyp_ppid_commonality",
    "챔버가 갈렸지만 레시피도 함께 본다 - 같은 wafer 를 두 이름으로 설명하는 "
    "교락인지 확인해야 의뢰 대상을 정할 수 있다.")

# 경로 축이 전부 조용할 때 순서대로 써 보는 나머지 등록 가설 (이름, 고른 이유).
# **hypotheses.yaml 에 가설을 추가하면 여기(또는 위)에도 추가해야 한다** — 게이트는
# 등록 가설을 전부 돌린 뒤에만 no_signal 을 선언하므로, 빠뜨리면 데모가 루프 한계까지
# 가서 inconclusive 로 끝난다(사유가 틀린 보고가 된다).
_FALLBACK_HYPOTHESES = [
    ("hyp_step_passage_commonality",
     "설비·PPID 로도 안 갈렸다. 스텝 통과 여부(비정규 스텝 포함)로 대조한다."),
    ("hyp_metro_commonality",
     "경로 축으로는 안 갈렸다. 계측값 구간(두께·CD)으로 대조한다."),
]


class ScriptedMockLLMClient(LLMClient):
    """사내망 밖 데모용. 그룹 대조 시나리오를 따라가는 결정론적 스크립트.

    finalize(claim_id="", confidence=0.6, 게이트가 반려) → hyp_eqp_ch_commonality(1단: 어느 챔버)
    → (EQP_CH 에 통과 후보가 없으면 hyp_ppid_commonality 로 폴백, 2차 legend)
    → compare_sensor_distribution(2단: 왜) → finalize(claim_id=<통과 후보>, confidence=0.9, 승인)
    순서로 진행하며, 각 단계 인자는 seed 메시지의 GROUPS_JSON 과 직전 ToolMessage(json) 를
    파싱해 이어받는다. 등록 가설(EQP_CH → `_FALLBACK_HYPOTHESES` 순)을 다 돌렸는데도
    분리되는 후보가 없으면 claim_id 를 비운 채 confidence=0.2 로 물러선다
    (게이트가 no_signal 로 판정).

    라벨(defect_type)을 쓰지 않는다 — 실데이터에 없기 때문이다.
    """

    def __init__(self):
        self._seq = 0

    # -------------------------------------------------- analyze
    def analyze_step(self, messages: list) -> AIMessage:
        target, control = self._groups(messages)
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        done = [m.name for m in tool_msgs]

        if "finalize" not in done:
            return self._call(
                "finalize",
                {"claim_id": "",
                 "hypothesis": f"불량 그룹 {len(target)}장이 한 사건으로 묶였다 - "
                               f"공통 원인 존재 추정",
                 "confidence": 0.6},
                "그룹은 묶였지만 공정 근거가 아직 없다. 이 정도로 종료를 제안해 본다.")

        if "hyp_eqp_ch_commonality" not in done:
            return self._call(
                "hyp_eqp_ch_commonality", {"group_ids": target, "control_ids": control},
                "종료 제안이 반려됐다. 챔버 편중 가설로 두 그룹을 대조한다.")

        res = self._result(tool_msgs, "hyp_eqp_ch_commonality")
        passing = [c for c in res.get("candidates", []) if c["passes"]]

        # 통과 여부와 무관하게 레시피 축을 함께 돌린다 (교락 확인 - 위 상수 참조).
        ppid_name, ppid_why = _ALWAYS_WITH_CHAMBER
        if ppid_name not in done:
            return self._call(ppid_name,
                              {"group_ids": target, "control_ids": control}, ppid_why)
        passing += [c for c in self._result(tool_msgs, ppid_name).get("candidates", [])
                    if c["passes"]]

        for name, why in _FALLBACK_HYPOTHESES:
            # EQP_CH 로 안 갈렸다. 남은 등록 가설을 순서대로 써 본다 - 첫 no_signal 로
            # 물러서면 안 써 본 가설을 남긴 채 포기하는 셈이고, 게이트도 no_signal 을
            # 선언하지 않는다(등록 가설을 전부 돌린 뒤에만 판정한다).
            if passing:
                break
            if name not in done:
                return self._call(name, {"group_ids": target, "control_ids": control}, why)
            res = self._result(tool_msgs, name)
            passing = [c for c in res.get("candidates", []) if c["passes"]]

        if not passing:
            # 등록 가설을 다 돌렸는데 분리되는 후보가 없다 - **원인 없음이 아니라 lot
            # 내부 대조로는 안 보인다**는 뜻. 억지로 후보를 집으면 허위 확정이므로
            # 지목 없이 물러선다(게이트가 no_signal 로 판정한다).
            return self._call(
                "finalize",
                {"claim_id": "",
                 "hypothesis": "lot 내부 대조로는 타깃만 거친 설비/챔버/PPID 가 없다 - "
                               "원인이 root_lot 전체에 걸렸을 수 있어 lot 밖 대조군이 필요하다",
                 "confidence": 0.2},
                "등록 가설을 다 돌렸으나 분리되는 후보가 없다. 확정할 근거가 없으므로 물러선다.")
        # **지목은 게이트와 같은 순위 함수로 고른다.** 도구는 후보를 점수순으로
        # 돌려주는데 게이트는 순열 p 로 줄을 세운다 - 둘이 어긋나면 반려가 오고,
        # 이 스크립트에는 그 반려에 반응할 분기가 없어 같은 finalize 를 루프 한계까지
        # 되풀이한다(확정될 분석이 inconclusive 로 끝난다). 순위를 여기서 다시
        # 구현하지 않고 게이트가 쓰는 것을 그대로 부르면 어긋날 자리가 없어진다.
        top = self._top_ranked(tool_msgs)
        if top is None:                      # 방어: 위에서 passing 을 확인했으므로 정상 경로는 아니다
            return self._call(
                "finalize",
                {"claim_id": "", "hypothesis": "통과 후보를 순위로 정렬하지 못했다",
                 "confidence": 0.2},
                "후보는 있으나 순위를 매길 수 없다. 지목 없이 물러선다.")

        if top.level == "step_passage":
            # 이 축은 키가 스텝 자체다 - "무엇을 썼는가" 가 아니라 "거쳤는가" 가 결론이다
            hyp = (f"불량군만 {top.step_seq} 스텝을 거쳤다(분리 점수 {top.score}, "
                   f"불량군 {top.target_pass}장 전용)")
        else:
            hyp = (f"{top.step_seq} 공정 {top.key} 편중(분리 점수 {top.score}, "
                   f"불량군 {top.target_pass}장 전용)이 원인")

        if "compare_sensor_distribution" not in TOOLS_BY_NAME:
            # 2단이 **아예 없는 구성**(SENSOR_MODE=off)이다. 아래 "근거를 못 냈다" 와
            # 구분해야 한다 - 거기서는 기다리면 언젠가 근거가 나오지만 여기서는 안
            # 나온다. 2단을 기다리며 물러서면 이 구성에서는 무엇도 확정되지 못하고
            # 매번 루프 소진으로 끝난다. 1단 근거는 게이트의 승인 조건(claim_id·최고
            # 점수)을 이미 충족하므로 그것으로 판단하되, 무엇이 없는지 문장에 남긴다.
            return self._call(
                "finalize",
                {"claim_id": top.claim_id,
                 "hypothesis": hyp + " - 2단 센서가 연결되지 않은 구성이라 1단 경로 근거만으로 판단",
                 "confidence": 0.85},
                "센서 도구가 없는 구성이다. 1단 경로 근거로 판단한다.")

        if "compare_sensor_distribution" not in done:
            return self._call(
                "compare_sensor_distribution",
                {"step_seq": top.step_seq,
                 "group_ids": target, "control_ids": control},
                "챔버까지 좁혔다. 그 스텝의 센서 분포로 '왜' 를 본다.")

        sensor = self._result(tool_msgs, "compare_sensor_distribution")
        if sensor.get("status") != "ok":
            # 2단이 갈리지 않았거나(no_signal) 아예 못 돌았다(fetch_failed/insufficient_sample).
            # 1단 근거는 그대로 남기되 확신도를 낮춰 물러선다 — 센서 결과를 안 보고 0.9 를
            # 내면 없는 근거를 있다고 말하는 꼴이라, 이 Stage 가 없앤 조용한 오확증이 된다.
            return self._call(
                "finalize",
                {"claim_id": top.claim_id,
                 "hypothesis": hyp + " - 다만 2단 센서 근거는 확보하지 못했다",
                 "confidence": 0.5},
                f"1단은 갈렸지만 2단이 근거를 못 냈다(status={sensor.get('status')}). "
                f"'왜' 없이 확정하지 않는다.")
        c = sensor["candidates"][0]
        hyp += f" - {c['sensor_name']} 효과크기 {c['effect_size']}"
        return self._call(
            "finalize",
            {"claim_id": top.claim_id, "hypothesis": hyp, "confidence": 0.9},
            "챔버 편중에 센서 근거까지 붙었다. 근거 충분.")

    # -------------------------------------------------- report
    def generate_report(self, target_wafers, target_source, target_group, status_summary,
                        findings, hypothesis, confidence, finalize_status=None,
                        claims=None) -> str:
        lines = [
            f"[분석 대상 입력] ({target_source}) {', '.join(target_wafers) or '없음'}",
            f"[불량 그룹] {', '.join(target_group) or '없음'}",
            f"[현황] {status_summary}",
            "",
            "[분석 과정]",
        ]
        for f in findings:
            lines.append(f"  {f['loop']}. {f['tool']}({f['args']})")
            if f.get("thought"):
                lines.append(f"     - 판단: {f['thought']}")
            if f["tool"] == "finalize":
                lines.append(f"     - 게이트: {f['result']}")
        if finalize_status == "inconclusive":
            conclusion = f"미확정 (루프 한계 도달) - 유력 가설: {hypothesis or '없음'}"
        elif finalize_status == "no_signal":
            conclusion = ("신호 없음 - lot 내부 대조로는 타깃만 거친 설비/챔버/PPID 가 없다. "
                          "원인 없음이 아니라 원인이 root_lot 전체에 걸렸을 수 있다는 뜻이며, "
                          "lot 밖 대조군이 필요하다.")
        elif finalize_status == "llm_call_failed":
            conclusion = ("분석 미수행 - LLM 분석 호출이 실패해 루프를 돌지 못했다. "
                          "원인을 못 찾은 것이 아니라 분석 자체가 안 돌았다는 뜻이며, "
                          "LLM 서빙 상태를 확인하고 재실행해야 한다.")
        elif finalize_status == "no_comparable_data":
            conclusion = ("분석 미수행 - 비교 가능한 데이터가 없다. 타깃과 같은 root_lot 의 "
                          "대조군이 없거나 그 wafer 들의 설비 이력이 없어 계산이 성립하지 "
                          "않았다. 근거를 못 찾은 것이 아니라 볼 것이 없었다는 뜻이며, "
                          "적재 범위와 추출 조건을 확인해야 한다.")
        elif finalize_status == "no_anomaly":
            conclusion = "이상 없음 - 수율 임계 미만 lot 이 없다."
        elif finalize_status == "unknown_target":
            conclusion = "분석 미수행 - 입력 wafer 를 데이터에서 찾을 수 없다. 입력을 확인하라."
        elif finalize_status == "eds_lookup_failed":
            conclusion = ("분석 미수행 - EDS 유사맵 조회 실패 (wafer 는 yield DB 에 존재). "
                          "인덱스↔yield DB 동기화 또는 EDS 서비스 상태를 확인하라 "
                          "- 구체 사유는 [현황] 참조.")
        elif finalize_status == "isolated":
            conclusion = ("분석 미수행 - 고립 패턴: 유사 형제 wafer 가 없어 그룹 대조가 "
                          "불가능하다. 추후 분석 필요.")
        elif finalize_status == "control_insufficient":
            conclusion = ("분석 미수행 - 대조군 부족 (lot 내 대조 한계). "
                          "root_lot 확장은 ETL(lot_type) 이후 활성화. 추후 분석 필요.")
        else:
            conclusion = hypothesis or "원인 미확정"
        conf = f" (확신도 {confidence})" if confidence is not None else ""
        lines += ["", f"[결론] {conclusion}{conf}"]
        # [근거] 줄은 여기서 붙이지 않는다 - report_node 가 코드로 붙인다(운영 클라이언트도
        # 동일하게 보장하려고 두 클라이언트 밖으로 뺐다). 여기서 또 붙이면 줄이 두 번 나온다.
        return "\n".join(lines)

    # -------------------------------------------------- 내부
    @staticmethod
    def _groups(messages) -> tuple[list[str], list[str]]:
        text = "\n".join(getattr(m, "content", "") or "" for m in messages
                         if isinstance(m, HumanMessage))
        m = re.search(r"GROUPS_JSON=(\{.*\})", text)
        if not m:
            raise ValueError("messages 에서 GROUPS_JSON 라인을 찾지 못했다")
        groups = json.loads(m.group(1))
        return groups["target"], groups["control"]

    @staticmethod
    def _top_ranked(tool_msgs):
        """지금까지 본 도구 결과 전부에서 게이트 기준 1등 claim.

        **게이트가 쓰는 함수를 그대로 부른다.** 여기서 순위를 다시 구현하면 규칙이
        바뀔 때 한쪽만 고쳐져 조용히 어긋나고, 그 어긋남은 "반려 - 다시 제출 - 반려"
        왕복으로만 드러난다(루프 한계까지 가서 inconclusive 로 끝난다).

        지연 import 는 순환을 피하려는 것이 아니라(순환은 없다) 데모 전용 경로 때문에
        운영 import 그래프를 넓히지 않으려는 것이다.
        """
        from graph import evidence

        findings = []
        for msg in tool_msgs:
            try:
                findings.append({"tool": msg.name, "result": json.loads(msg.content)})
            except (TypeError, ValueError):
                continue          # 도구 오류는 문자열로 온다 - 증거가 아니다
        groups = evidence.build_bundle(findings).ranked_groups()
        return groups[0].lead if groups else None

    @staticmethod
    def _result(tool_msgs, name):
        msg = next(m for m in reversed(tool_msgs) if m.name == name)
        res = json.loads(msg.content)
        # tools 노드는 실행 실패 시 오류 '문자열' 을 담는다 (dict 가정이 깨지는 유일한 경로).
        # 각본이 죽는 대신 '결과 없음' 으로 취급해 낮은 확신도 후퇴 분기를 타게 한다.
        return res if isinstance(res, dict) else {}

    def _call(self, name, args, thought) -> AIMessage:
        self._seq += 1
        return AIMessage(
            content=thought,
            tool_calls=[{"name": name, "args": args, "id": f"call_{self._seq}"}],
        )


class OpenAILLMClient(LLMClient):
    """운영용. 사내 OpenAI 호환 서빙에 base_url 만 지정해 연결."""

    def __init__(self):
        from langchain_openai import ChatOpenAI

        from tools.agent_tools import ALL_TOOLS

        # 헤더 값이 None 이면 인증 실패(401)가 아니라 httpx 의 TypeError 로 죽는다 —
        # 메시지에 USER_NAME 이 안 나와서 원인이 안 읽힌다. 여기서 먼저 멈춘다.
        if not ya_config.USER_NAME:
            raise ValueError(
                "USER_NAME 이 비어 있습니다. .env 에 사내 AD ID 를 넣으세요 "
                "(사내 LLM 게이트웨이가 User-Id 헤더로 요구합니다)."
            )

        self.llm = ChatOpenAI(
            base_url=ya_config.LLM_BASE_URL,
            # 인증은 아래 x-dep-ticket 이 하지만, 이 인자를 빼면 ChatOpenAI 가
            # 생성 시점에 OPENAI_API_KEY 환경변수를 찾다가 "Missing credentials" 로
            # 죽는다 (langchain_openai 1.3.3 확인). 인증과 무관한 메시지라 넣어 둔다.
            api_key=ya_config.LLM_API_KEY,
            model=ya_config.LLM_MODEL,
            temperature=0,
            timeout=ya_config.LLM_TIMEOUT,
            max_retries=ya_config.LLM_MAX_RETRIES,
            # 사내 게이트웨이 규약. 값과 이름은 사내 예시를 그대로 따른다.
            # Msg-Id 두 개는 클라이언트 1개당 한 번만 생성되므로 한 번 실행하는 동안
            # 모든 요청이 같은 값을 단다. 게이트웨이가 이 값을 어떻게 쓰는지 아직
            # 모르며, 추적·중복제거에 쓰인다면 호출마다 새로 만들어야 한다.
            default_headers={
                "x-dep-ticket": ya_config.LLM_API_KEY,
                "Send-System-Name": "test_api_1",
                "User-Id": ya_config.USER_NAME,
                "User-Type": "AD_ID",
                "Prompt-Msg-Id": str(uuid.uuid4()),
                "Completion-Msg-Id": str(uuid.uuid4()),
            },
        )
        self.analyzer = self.llm.bind_tools(ALL_TOOLS, parallel_tool_calls=False)

    def analyze_step(self, messages: list) -> AIMessage:
        return self.analyzer.invoke(messages)

    def generate_report(self, target_wafers, target_source, target_group, status_summary,
                        findings, hypothesis, confidence, finalize_status=None,
                        claims=None) -> str:
        sys = (
            "현장 반도체 엔지니어에게 한국어 높임말로 원인 분석 리포트를 쓴다. "
            "분석 과정(findings)의 수치는 절대 임의로 바꾸지 말고 그대로 인용하라. "
            "구성: 분석 대상/현황 → 분석 과정 요약 → 결론(원인 가설과 근거). "
            "판정이 inconclusive 면 결론을 확정하지 말고 '미확정(루프 한계 도달)'과 "
            "유력 후보·추가 조사 필요 항목으로 서술하라. "
            "판정이 no_signal 이면 '신호 없음'으로 서술하라 - 원인 없음이 아니라 "
            "lot 내부 대조로는 보이지 않는다는 뜻이며 lot 밖 대조군이 필요하다는 "
            "후속 조치를 명시하고, 확정 결론을 쓰지 마라. "
            "판정이 no_comparable_data 면 '분석 미수행 - 비교 가능한 데이터 없음'으로 "
            "서술하라 - 근거를 못 찾은 것이 아니라 대조에 쓸 짝이 없어 계산이 성립하지 "
            "않은 것이며, 적재 범위와 추출 조건 확인이 후속 조치다. 확정 결론을 쓰지 마라. "
            "판정이 llm_call_failed 면 '분석 미수행 - LLM 분석 호출 실패'로 서술하라 - "
            "분석 루프가 아예 안 돌았으니 확정 결론을 쓰지 말고 재실행을 권하라. "
            "판정이 no_anomaly 면 '이상 없음'으로 서술하라. "
            "판정이 isolated/control_insufficient/unknown_target/eds_lookup_failed 이면 "
            "'분석 미수행'과 그 사유를 명시하고 확정 결론을 쓰지 마라. "
            "근거가 여러 건이면 **전부** 서술하라 - 하나로 줄이지 마라. 순위는 코드가 "
            "매긴 것이며, 같은 wafer 를 두 이름으로 설명할 수 있는 항목(confounded_with)은 "
            "'현재 증거로는 구분되지 않는다'고 밝히고 무엇을 더 봐야 갈리는지 적어라."
        )
        user = (
            f"분석 대상 입력 ({target_source}): {', '.join(target_wafers)}\n"
            f"불량 그룹: {', '.join(target_group)}\n현황: {status_summary}\n\n"
            f"분석 기록(JSON):\n{json.dumps(findings, ensure_ascii=False, default=str)}\n\n"
            f"결론 가설: {hypothesis or '미확정'} / 확신도: {confidence} / "
            f"판정: {finalize_status or '미상'}"
        )
        if claims:
            user += (f"\n게이트가 확인한 근거 {len(claims)}건 "
                     f"(순위는 코드가 매겼다. 수치를 그대로 인용하고, 하나만 고르지 말고 "
                     f"전부 서술하라. rank 가 같은 항목은 우열을 가릴 수 없다는 뜻이고, "
                     f"confounded_with 가 있으면 같은 wafer 를 다른 이름으로도 설명할 수 "
                     f"있다는 뜻이니 둘 중 하나로 단정하지 마라): "
                     f"{json.dumps(claims, ensure_ascii=False)}")
        resp = self.llm.invoke([SystemMessage(content=sys), HumanMessage(content=user)])
        return resp.content.strip()


def get_llm() -> LLMClient:
    if ya_config.LLM_MODE == "mock":
        return ScriptedMockLLMClient()
    if ya_config.LLM_MODE == "openai":
        return OpenAILLMClient()
    raise ValueError(f"알 수 없는 LLM_MODE: {ya_config.LLM_MODE}")
