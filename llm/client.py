"""LLM 클라이언트 인터페이스 + 구현(mock / 사내 OpenAI 호환).

설계의 두 LLM 호출 지점을 단일 인터페이스로 추상화한다:
  - classify_intent : 질문 -> 라우팅 레이블 (의도 파악 노드)
  - generate_answer : 도구 결과(context) -> 자연어 답변 (답변 생성 노드)

수치 계산은 도구 계층이 담당하고, LLM 은 의도 해석·표현만 맡는다.
"""

from abc import ABC, abstractmethod

import config

# 라우팅 레이블 (그래프와 공유)
ROUTE_YIELD = "yield_query"        # 단순 조회/집계 (시나리오 1)
ROUTE_SIMILAR = "similar_search"   # 유사 패턴 탐색 (시나리오 2)
ROUTE_CAUSE = "defect_cause"       # 유사 사례 원인 추정 (시나리오 3, 확장)
ROUTES = (ROUTE_YIELD, ROUTE_SIMILAR, ROUTE_CAUSE)


class LLMClient(ABC):
    @abstractmethod
    def classify_intent(self, question: str) -> str:
        """질문을 ROUTES 중 하나로 분류."""
        ...

    @abstractmethod
    def generate_answer(self, question: str, context: str) -> str:
        """도구 결과 문자열(context)을 자연어 답변으로 변환."""
        ...


class MockLLMClient(LLMClient):
    """사내망 밖 데모용. 키워드 규칙으로 분류, context 를 그대로 표현."""

    def classify_intent(self, question: str) -> str:
        q = question
        if any(k in q for k in ("비슷", "유사", "패턴", "사례")):
            return ROUTE_SIMILAR
        if any(k in q for k in ("원인", "왜", "이유")):
            return ROUTE_CAUSE
        return ROUTE_YIELD

    def generate_answer(self, question: str, context: str) -> str:
        return context


class OpenAILLMClient(LLMClient):
    """운영용. 사내 OpenAI 호환 서빙에 base_url 만 지정해 연결."""

    def __init__(self):
        from langchain_openai import ChatOpenAI

        self.llm = ChatOpenAI(
            base_url=config.LLM_BASE_URL,
            api_key=config.LLM_API_KEY,
            model=config.LLM_MODEL,
            temperature=0,
        )

    def classify_intent(self, question: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        sys = (
            "너는 반도체 수율 분석 질문을 분류한다. 다음 중 하나의 레이블만 출력:\n"
            f"- {ROUTE_YIELD}: 수율/lot/배치 조회·집계\n"
            f"- {ROUTE_SIMILAR}: 불량 맵이 과거 어떤 사례와 비슷한지 (유사 패턴 탐색)\n"
            f"- {ROUTE_CAUSE}: 유사 사례들의 원인/불량 유형\n"
            "레이블 외 다른 말은 출력하지 마라."
        )
        resp = self.llm.invoke([SystemMessage(content=sys), HumanMessage(content=question)])
        label = resp.content.strip()
        return label if label in ROUTES else ROUTE_YIELD

    def generate_answer(self, question: str, context: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        sys = (
            "현장 반도체 엔지니어에게 한국어 높임말로 간결히 답한다. "
            "도구 결과의 수치는 절대 임의로 바꾸지 말고 그대로 사용하라."
        )
        user = f"질문: {question}\n\n도구 결과:\n{context}"
        resp = self.llm.invoke([SystemMessage(content=sys), HumanMessage(content=user)])
        return resp.content.strip()


def get_llm() -> LLMClient:
    if config.LLM_MODE == "mock":
        return MockLLMClient()
    if config.LLM_MODE == "openai":
        return OpenAILLMClient()
    raise ValueError(f"알 수 없는 LLM_MODE: {config.LLM_MODE}")
