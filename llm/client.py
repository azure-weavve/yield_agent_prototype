"""LLM 클라이언트 인터페이스 + 구현(스크립트형 mock / 사내 OpenAI 호환).

분석 루프의 두 LLM 호출 지점을 단일 인터페이스로 추상화한다:
  - analyze_step     : 누적 messages -> tool call 또는 finalize 를 담은 AIMessage
  - generate_report  : 감사 기록(findings) -> 원인 리포트 (수치는 tool 결과 그대로)

수치 계산은 도구 계층이 담당하고, LLM 은 "어떤 분석을 할지 판단"과 표현만 맡는다.
"""

import json
import re
from abc import ABC, abstractmethod

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import config


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
    ) -> str:
        """감사 기록을 근거로 원인 리포트 생성.

        finalize_status 가 "inconclusive"(루프 한계 도달)면 결론을 확정 톤이 아니라
        "미확정 + 유력 가설(후보)" 톤으로 서술해야 한다.
        """
        ...


class ScriptedMockLLMClient(LLMClient):
    """사내망 밖 데모용. 그룹 대조 시나리오를 따라가는 결정론적 스크립트.

    finalize(0.6, 게이트가 반려) → hyp_eqp_ch_commonality(1단: 어느 챔버)
    → compare_sensor_distribution(2단: 왜) → finalize(0.9, 승인) 순서로 진행하며,
    각 단계 인자는 seed 메시지의 GROUPS_JSON 과 직전 ToolMessage(json) 를 파싱해 이어받는다.

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
                {"hypothesis": f"불량 그룹 {len(target)}장이 한 사건으로 묶였다 — "
                               f"공통 원인 존재 추정",
                 "confidence": 0.6},
                "그룹은 묶였지만 공정 근거가 아직 없다. 이 정도로 종료를 제안해 본다.")

        if "hyp_eqp_ch_commonality" not in done:
            return self._call(
                "hyp_eqp_ch_commonality", {"group_ids": target, "control_ids": control},
                "종료 제안이 반려됐다. 챔버 편중 가설로 두 그룹을 대조한다.")

        res = self._result(tool_msgs, "hyp_eqp_ch_commonality")
        passing = [c for c in res.get("candidates", []) if c["passes"]]
        if not passing:
            # 분리되는 후보가 없다 — **원인 없음이 아니라 lot 내부 대조로는 안 보인다**는 뜻.
            # 억지로 후보를 집으면 허위 확정이므로 낮은 확신도로 물러선다(게이트가 반려하고,
            # 루프 한계에 닿아 '미확정' 리포트로 끝난다).
            return self._call(
                "finalize",
                {"hypothesis": "lot 내부 대조로는 타깃만 거친 설비/챔버가 없다 — "
                               "원인이 root_lot 전체에 걸렸을 수 있어 lot 밖 대조군이 필요하다",
                 "confidence": 0.2},
                "대조 결과에 분리되는 후보가 없다. 확정할 근거가 없으므로 물러선다.")
        top = passing[0]

        if "compare_sensor_distribution" not in done:
            return self._call(
                "compare_sensor_distribution",
                {"step_seq": top["step_seq"],
                 "group_ids": target, "control_ids": control},
                "챔버까지 좁혔다. 그 스텝의 센서 분포로 '왜' 를 본다.")

        sensor = self._result(tool_msgs, "compare_sensor_distribution")
        val = top["value"][-1]
        hyp = (f"{top['value'][0]} 공정 {val} 편중(분리 점수 {top.get('score')}, "
               f"불량군 {top['target_pass']}장 전용)이 원인")
        if sensor.get("status") != "ok":
            # 2단이 갈리지 않았거나(no_signal) 아예 못 돌았다(fetch_failed/insufficient_sample).
            # 1단 근거는 그대로 남기되 확신도를 낮춰 물러선다 — 센서 결과를 안 보고 0.9 를
            # 내면 없는 근거를 있다고 말하는 꼴이라, 이 Stage 가 없앤 조용한 오확증이 된다.
            return self._call(
                "finalize",
                {"hypothesis": hyp + " — 다만 2단 센서 근거는 확보하지 못했다",
                 "confidence": 0.5},
                f"1단은 갈렸지만 2단이 근거를 못 냈다(status={sensor.get('status')}). "
                f"'왜' 없이 확정하지 않는다.")
        c = sensor["candidates"][0]
        hyp += f" — {c['sensor_name']} 효과크기 {c['effect_size']}"
        return self._call(
            "finalize", {"hypothesis": hyp, "confidence": 0.9},
            "챔버 편중에 센서 근거까지 붙었다. 근거 충분.")

    # -------------------------------------------------- report
    def generate_report(self, target_wafers, target_source, target_group, status_summary,
                        findings, hypothesis, confidence, finalize_status=None) -> str:
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
            conclusion = f"미확정 (루프 한계 도달) — 유력 가설: {hypothesis or '없음'}"
        elif finalize_status == "no_anomaly":
            conclusion = "이상 없음 — 수율 임계 미만 lot 이 없다."
        elif finalize_status == "unknown_target":
            conclusion = "분석 미수행 — 입력 wafer 를 데이터에서 찾을 수 없다. 입력을 확인하라."
        elif finalize_status == "eds_lookup_failed":
            conclusion = ("분석 미수행 — EDS 유사맵 조회 실패 (wafer 는 yield DB 에 존재). "
                          "인덱스↔yield DB 동기화 또는 EDS 서비스 상태를 확인하라 "
                          "— 구체 사유는 [현황] 참조.")
        elif finalize_status == "isolated":
            conclusion = ("분석 미수행 — 고립 패턴: 유사 형제 wafer 가 없어 그룹 대조가 "
                          "불가능하다. 추후 분석 필요.")
        elif finalize_status == "control_insufficient":
            conclusion = ("분석 미수행 — 대조군 부족 (lot 내 대조 한계). "
                          "root_lot 확장은 ETL(lot_type) 이후 활성화. 추후 분석 필요.")
        else:
            conclusion = hypothesis or "원인 미확정"
        conf = f" (확신도 {confidence})" if confidence is not None else ""
        lines += ["", f"[결론] {conclusion}{conf}"]
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

        self.llm = ChatOpenAI(
            base_url=config.LLM_BASE_URL,
            api_key=config.LLM_API_KEY,
            model=config.LLM_MODEL,
            temperature=0,
        )
        self.analyzer = self.llm.bind_tools(ALL_TOOLS, parallel_tool_calls=False)

    def analyze_step(self, messages: list) -> AIMessage:
        return self.analyzer.invoke(messages)

    def generate_report(self, target_wafers, target_source, target_group, status_summary,
                        findings, hypothesis, confidence, finalize_status=None) -> str:
        sys = (
            "현장 반도체 엔지니어에게 한국어 높임말로 원인 분석 리포트를 쓴다. "
            "분석 과정(findings)의 수치는 절대 임의로 바꾸지 말고 그대로 인용하라. "
            "구성: 분석 대상/현황 → 분석 과정 요약 → 결론(원인 가설과 근거). "
            "판정이 inconclusive 면 결론을 확정하지 말고 '미확정(루프 한계 도달)'과 "
            "유력 후보·추가 조사 필요 항목으로 서술하라. "
            "판정이 no_anomaly 면 '이상 없음'으로 서술하라. "
            "판정이 isolated/control_insufficient/unknown_target/eds_lookup_failed 이면 "
            "'분석 미수행'과 그 사유를 명시하고 확정 결론을 쓰지 마라."
        )
        user = (
            f"분석 대상 입력 ({target_source}): {', '.join(target_wafers)}\n"
            f"불량 그룹: {', '.join(target_group)}\n현황: {status_summary}\n\n"
            f"분석 기록(JSON):\n{json.dumps(findings, ensure_ascii=False, default=str)}\n\n"
            f"결론 가설: {hypothesis or '미확정'} / 확신도: {confidence} / "
            f"판정: {finalize_status or '미상'}"
        )
        resp = self.llm.invoke([SystemMessage(content=sys), HumanMessage(content=user)])
        return resp.content.strip()


def get_llm() -> LLMClient:
    if config.LLM_MODE == "mock":
        return ScriptedMockLLMClient()
    if config.LLM_MODE == "openai":
        return OpenAILLMClient()
    raise ValueError(f"알 수 없는 LLM_MODE: {config.LLM_MODE}")
