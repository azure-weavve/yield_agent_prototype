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
        target_wafer: str,
        status_summary: str,
        findings: list[dict],
        hypothesis: str | None,
        confidence: float | None,
    ) -> str:
        """감사 기록을 근거로 원인 리포트 생성."""
        ...


class ScriptedMockLLMClient(LLMClient):
    """사내망 밖 데모용. 시나리오를 따라가는 결정론적 스크립트.

    search_similar → aggregate_defects → finalize(0.6, 게이트가 반려)
    → get_process_log → finalize(0.9, 승인) 순서로 진행하며,
    각 단계 인자는 직전 ToolMessage(json) 를 파싱해 이어받는다.
    """

    def __init__(self):
        self._seq = 0

    # -------------------------------------------------- analyze
    def analyze_step(self, messages: list) -> AIMessage:
        target = self._target(messages)
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        done = [m.name for m in tool_msgs]

        if "search_similar" not in done:
            return self._call(
                "search_similar", {"wafer_id": target},
                f"{target} 의 불량 맵과 유사한 과거 사례부터 확인한다.")

        if "aggregate_defects" not in done:
            sims = [r["wafer_id"] for r in self._result(tool_msgs, "search_similar")]
            return self._call(
                "aggregate_defects", {"wafer_ids": [target] + sims},
                "유사 wafer 들이 같은 불량 유형을 공유하는지 집계한다.")

        if "finalize" not in done:
            top = self._result(tool_msgs, "aggregate_defects")[0]["defect_type"]
            return self._call(
                "finalize",
                {"hypothesis": f"유사 사례가 모두 {top} — 공통 원인 존재 추정",
                 "confidence": 0.6},
                "불량 유형은 좁혔지만 공정 근거가 아직 없다. 이 정도로 종료를 제안해 본다.")

        if "get_process_log" not in done:
            return self._call(
                "get_process_log", {"wafer_id": target},
                "종료 제안이 반려됐다. 원인 공정을 좁히기 위해 공정 로그를 확인한다.")

        logs = self._result(tool_msgs, "get_process_log")
        bad = next(r for r in logs if not r["in_spec"])
        hyp = (f"{bad['process_step']} 공정 {bad['equipment_id']} 장비의 "
               f"{bad['param_name']} 스펙 이탈({bad['param_value']}, "
               f"스펙 {bad['spec_low']}~{bad['spec_high']})이 원인")
        return self._call(
            "finalize", {"hypothesis": hyp, "confidence": 0.9},
            "공정 로그에서 스펙 이탈 장비를 특정했다. 근거가 충분하다.")

    # -------------------------------------------------- report
    def generate_report(self, question, target_wafer, status_summary,
                        findings, hypothesis, confidence) -> str:
        lines = [
            f"[분석 대상] {target_wafer}",
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
    def _target(messages) -> str:
        for m in messages:
            found = re.search(r"대상 wafer: (\S+)", getattr(m, "content", "") or "")
            if found:
                return found.group(1)
        raise ValueError("messages 에서 '대상 wafer:' 라인을 찾지 못했다")

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

    def generate_report(self, question, target_wafer, status_summary,
                        findings, hypothesis, confidence) -> str:
        sys = (
            "현장 반도체 엔지니어에게 한국어 높임말로 원인 분석 리포트를 쓴다. "
            "분석 과정(findings)의 수치는 절대 임의로 바꾸지 말고 그대로 인용하라. "
            "구성: 분석 대상/현황 → 분석 과정 요약 → 결론(원인 가설과 근거)."
        )
        user = (
            f"질문: {question}\n대상 wafer: {target_wafer}\n현황: {status_summary}\n\n"
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
