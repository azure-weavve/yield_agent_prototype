# 분석 루프 설계 — 하이브리드 Agent (현황 파악 → 원인 분석 → 리포팅)

> 현재 프로토타입(고정 경로)에서 **하이브리드 자율 분석 Agent**로 진화하기 위한 설계 메모.
> 나중에 이어서 구현하기 위한 참고 문서입니다. 아직 코드로는 미구현.

## 1. 목표

Agent가 다음을 스스로 수행하게 만든다:

```
현황 파악 → 분석이 필요한 wafer 발견 → 그 wafer를 여러 각도로 분석
→ 현재까지 결과를 보고 더 볼지 판단(반복) → 원인을 좁힘 → 리포팅
```

핵심은 **분석 단계 수를 미리 알 수 없다**는 점. wafer마다 1번이면 끝날 수도, 5번을 파고들어야 할 수도 있다.
직전 분석 결과를 보고 다음 분석을 결정해야 하므로, 고정 경로로는 담을 수 없고 **LLM 주도 반복 루프**가 필요하다.

## 2. 왜 하이브리드인가

| 방식 | 경로 결정 | 적합성 |
|------|----------|--------|
| A. 경로 강제 (현재 프로토타입) | 개발자가 엣지로 못박음 | 흐름 고정된 데모용. 동적 분석 불가 |
| B. 완전 자율 (ReAct 루프) | LLM이 매 스텝 판단 | 유연하지만 통제·신뢰성 약함 |
| **C. 하이브리드 (채택)** | **골격은 강제, 분석만 위임** | **신뢰성 중요한 분석 자동화에 적합** |

- **일의 순서(골격)는 고정**: 반드시 "현황 파악 먼저 → 마지막에 리포팅". 개발자가 못박는다.
- **방법(중간 분석)은 위임**: "어떤 분석 tool을 몇 번 쓸지"는 LLM이 판단한다.

```
[고정] 현황파악 ──▶ [자유 루프] ──────────────────▶ [고정] 리포팅
                    ┌────────────────────────┐
                    │  analyze(LLM) ⇄ tools   │  ← 이 구간만 LLM 자율 순환
                    └────────────────────────┘
```

이 프로젝트의 핵심 철학("LLM은 숫자를 만들지 않는다, 도구가 계산한다")을 루프에서도 유지한다:
LLM은 **어떤 분석을 할지 판단**만 하고, 수치는 여전히 결정론적 tool이 만든다.

## 3. 분석 루프를 구성하는 4개 부품

### 부품 1: 순환 엣지 (루프의 몸통)

`tools → analyze`로 **되돌아가는 엣지**가 순환 고리를 만든다.
(현재 프로토타입은 `yield_tool → answer` 한 방향뿐이라 루프가 없다. 되돌아가는 엣지 하나가 핵심.)

```python
def _should_continue(state):
    last = state["messages"][-1]
    if last.tool_calls:      # LLM이 "이 tool 불러줘"라고 했으면
        return "tools"       # → 루프 계속
    return "report"          # → tool 안 불렀으면 = 다 봤다는 신호 → 탈출

g.add_conditional_edges("analyze", _should_continue, ["tools", "report"])
g.add_edge("tools", "analyze")   # ← 순환 고리
```

### 부품 2: 행동 = 신호 (계속 vs 멈춤)

LLM은 "계속/멈춤"을 말로 하지 않는다. **tool을 부르는 행동 자체가 신호**다.
- 분석 더 필요 → tool call을 뱉음 → 조건부 엣지가 `tools`로 → 순환
- 원인 충분히 좁혀짐 → tool call 없이 결론을 냄 → 탈출

매 순환마다 LLM이 "지금까지 결과로 충분한가?"를 스스로 평가해 둘 중 하나를 고른다.

### 부품 3: 상태 누적 (reducer)

LLM이 "현재까지 결과를 보고" 판단하려면, 매 순환마다 그동안 알아낸 걸 **전부** 보여줘야 한다.
현재 프로토타입은 "덮어쓰기" 모델이지만, 루프에서는 **누적**이 필요하다.

```python
from typing import Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # 덮어쓰기 대신 계속 쌓음(reducer)
    target_wafer: str
    findings: list                           # 확정된 분석 결과 누적
```

누적하지 않으면 매 순환마다 맥락을 잃고 같은 tool을 반복 호출한다.

### 부품 4: 종료 통제 (프롬프트 + 코드 가드레일)

LLM 자율 판단만 믿으면 "근거 없이 멈추거나" "무한 루프"가 난다. 두 겹으로 통제한다.

**(a) 프롬프트에 목표와 멈춤 기준 명시**
```
목표: 이 wafer의 불량 원인을 특정 공정 단계까지 좁혀라.
규칙:
- 매 단계, 지금까지 결과로 원인을 확신할 수 있는지 스스로 평가하라.
- 확신이 부족하면 근거를 좁힐 tool을 하나 더 호출하라.
- 원인을 특정 공정으로 좁혔고 근거가 충분하면, tool 호출을 멈추고 결론을 내라.
```

**(b) 구조화된 출력 + 코드 가드레일**
매 순환마다 자유 텍스트가 아니라 구조를 뱉게 하고, 종료는 코드가 최종 통제한다.

```python
class AnalysisStep(BaseModel):
    hypothesis: str        # 현재 원인 가설
    confidence: float      # 0~1 확신도
    need_more: bool        # 더 봐야 하나?
    next_tool: str | None  # 다음에 부를 tool

def _should_continue(state):
    step = state["last_step"]
    if step.confidence >= 0.8:     # 확신도 임계 → 종료 강제
        return "report"
    if state["loop_count"] >= 6:   # 가드레일: 최대 6회 → 무한루프 차단
        return "report"
    return "tools"
```

## 4. 전체 그림

```
[고정] 현황파악 ──▶ [자유 루프] ──────────────────────▶ [고정] 리포팅
                    ┌──────────────────────────┐
                    │ analyze(LLM)             │
                    │   ↑ 누적된 findings 보고   │  ← 부품3: 상태 누적
                    │   → 확신? 부족하면 tool    │  ← 부품4-a: 목표 프롬프트
                    │ tools 실행 → analyze 로     │  ← 부품1: 순환 엣지
                    │ [종료: 확신≥0.8 or 6회]     │  ← 부품4-b: 코드 가드레일
                    └──────────────────────────┘
```

## 5. 현재 프로토타입 대비 바뀌는 것

| 항목 | 현재 | 분석 루프 도입 후 |
|------|------|------------------|
| 흐름 | intent → tool → answer (한 방향) | 현황 → **분석 루프(순환)** → 리포팅 |
| tool 선택 | `_route` if문이 강제 | 루프 안에서 **LLM이 골라 호출** |
| 상태 | 덮어쓰기 (`total=False`) | **누적** (`add_messages` reducer + findings) |
| 종료 | answer 후 무조건 END | **확신도/최대횟수로 판단** |
| tool 수 | 2개 (yield, similar) | 확장 (아래 6절) |

## 6. 다음 단계 체크리스트

- [ ] 분석에 필요한 tool 목록 확정 (예: `get_wafer`, `search_similar`, `aggregate_defects`,
      `get_process_log`, 공정 파라미터 조회 등). 이미 있는 `aggregate_defects`는 재활용.
- [ ] 상태를 누적형으로 전환 (`messages` + reducer, `findings`, `loop_count`).
- [ ] 분석 루프 서브그래프 구성 (`analyze` ⇄ `tools` 순환 + 조건부 종료).
- [ ] LLM을 tool-calling 모드로 (langchain의 `bind_tools` 또는 `create_react_agent`).
- [ ] 종료 판단: 구조화 출력(`AnalysisStep`) + 확신도 임계 + 최대 횟수 가드레일.
- [ ] 리포팅 노드: 누적된 findings를 근거로 원인 리포트 생성 (수치는 tool 결과 그대로 인용).
- [ ] 골격(현황파악/리포팅)은 고정 엣지로 못박아 순서 보장.

## 7. 참고

- LangGraph 자율 루프 표준 패턴: `create_react_agent`, 또는 `ToolNode` + 조건부 순환 엣지.
- 관련 기존 문서: `yield_agent_design_plan_v2.md`
- 현재 구현: `graph/build.py`(고정 경로), `graph/nodes.py`, `graph/state.py`(덮어쓰기 상태)
