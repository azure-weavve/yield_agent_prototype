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
        question: str,
        target_group: list[str],
        status_summary: str,
        findings: list[dict],
        hypothesis: str | None,
        confidence: float | None,
    ) -> str:
        """감사 기록을 근거로 원인 리포트 생성."""
        ...


class ScriptedMockLLMClient(LLMClient):
    """사내망 밖 데모용. 그룹 대조 시나리오를 따라가는 결정론적 스크립트.

    aggregate_defects(불량 그룹) → finalize(0.6, 게이트가 반려)
    → compare_process_logs(불량 vs 대조) → finalize(0.9, 승인) 순서로 진행하며,
    각 단계 인자는 seed 메시지의 그룹 라인과 직전 ToolMessage(json) 를 파싱해 이어받는다.
    """

    def __init__(self):
        self._seq = 0

    # -------------------------------------------------- analyze
    def analyze_step(self, messages: list) -> AIMessage:
        target, control = self._groups(messages)
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        done = [m.name for m in tool_msgs]

        if "aggregate_defects" not in done:
            return self._call(
                "aggregate_defects", {"wafer_ids": target},
                "불량 그룹이 같은 불량 유형을 공유하는지 먼저 집계한다.")

        if "finalize" not in done:
            top = self._result(tool_msgs, "aggregate_defects")[0]["defect_type"]
            return self._call(
                "finalize",
                {"hypothesis": f"불량 그룹 {len(target)}장이 모두 {top} — 공통 원인 존재 추정",
                 "confidence": 0.6},
                "불량 유형은 좁혔지만 공정 근거가 아직 없다. 이 정도로 종료를 제안해 본다.")

        if "compare_process_logs" not in done:
            return self._call(
                "compare_process_logs", {"group_ids": target, "control_ids": control},
                "종료 제안이 반려됐다. 그룹 대조로 원인 공정/장비를 좁힌다.")

        cmp = self._result(tool_msgs, "compare_process_logs")
        bad = cmp["group_spec_violations"][0]
        hyp = (f"{bad['process_step']} 공정 {bad['equipment_id']} 장비의 "
               f"{bad['param_name']} 스펙 이탈(불량 그룹 {len(cmp['group_spec_violations'])}장 공통, "
               f"스펙 {bad['spec_low']}~{bad['spec_high']}, 측정 {bad['param_value']})이 원인")
        return self._call(
            "finalize", {"hypothesis": hyp, "confidence": 0.9},
            "그룹 대조에서 불량 그룹만 공유하는 스펙 이탈 장비를 특정했다. 근거가 충분하다.")

    # -------------------------------------------------- report
    def generate_report(self, question, target_group, status_summary,
                        findings, hypothesis, confidence) -> str:
        lines = [
            f"[분석 대상] 불량 그룹: {', '.join(target_group) or '없음'}",
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
        conclusion = hypothesis or "원인 미확정"
        conf = f" (확신도 {confidence})" if confidence is not None else ""
        lines += ["", f"[결론] {conclusion}{conf}"]
        return "\n".join(lines)

    # -------------------------------------------------- 내부
    @staticmethod
    def _groups(messages) -> tuple[list[str], list[str]]:
        text = "\n".join(getattr(m, "content", "") or "" for m in messages
                         if isinstance(m, HumanMessage))
        t = re.search(r"불량 그룹 \([^)]*\): (.+)", text)
        c = re.search(r"대조 그룹 \(정상\): (.+)", text)
        if not (t and c):
            raise ValueError("messages 에서 불량/대조 그룹 라인을 찾지 못했다")
        return ([w.strip() for w in t.group(1).split(",")],
                [w.strip() for w in c.group(1).split(",")])

    @staticmethod
    def _result(tool_msgs, name):
        msg = next(m for m in reversed(tool_msgs) if m.name == name)
        return json.loads(msg.content)

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
        self.analyzer = self.llm.bind_tools(ALL_TOOLS)

    def analyze_step(self, messages: list) -> AIMessage:
        return self.analyzer.invoke(messages)

    def generate_report(self, question, target_group, status_summary,
                        findings, hypothesis, confidence) -> str:
        sys = (
            "현장 반도체 엔지니어에게 한국어 높임말로 원인 분석 리포트를 쓴다. "
            "분석 과정(findings)의 수치는 절대 임의로 바꾸지 말고 그대로 인용하라. "
            "구성: 분석 대상/현황 → 분석 과정 요약 → 결론(원인 가설과 근거)."
        )
        user = (
            f"질문: {question}\n불량 그룹: {', '.join(target_group)}\n현황: {status_summary}\n\n"
            f"분석 기록(JSON):\n{json.dumps(findings, ensure_ascii=False, default=str)}\n\n"
            f"결론 가설: {hypothesis or '미확정'} / 확신도: {confidence}"
        )
        resp = self.llm.invoke([SystemMessage(content=sys), HumanMessage(content=user)])
        return resp.content.strip()


def get_llm() -> LLMClient:
    if config.LLM_MODE == "mock":
        return ScriptedMockLLMClient()
    if config.LLM_MODE == "openai":
        return OpenAILLMClient()
    raise ValueError(f"알 수 없는 LLM_MODE: {config.LLM_MODE}")
