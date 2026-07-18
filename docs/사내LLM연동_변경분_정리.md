# 사내 LLM 연동 — 변경분 전체 정리 (2026-07-16)

> **목적:** 회사에서 진행한 `LLM_MODE=openai` 연동 작업을 집에서 손으로 재현하기 위한 작업 목록.
> **범위:** 사내 LLM + 더미 데이터로 End-to-End 정상 동작 확인까지. EDS 는 `local` 유지, 실데이터 연동은 미착수.
> **결과:** 테스트 58 → 63 passed (0.89s, mock 기본값). `main.py` 실제 사내 LLM 완주 + 수치 검증 통과.

---

## 변경 파일 요약

| 파일 | 변경 내용 |
|------|----------|
| `config.py` | LLM 설정 환경변수화 (기본값 `mock`) |
| `requirements.txt` | `python-dotenv` 추가 |
| `.env` | 접속 정보만 (LLM_MODE 넣지 말 것) |
| `.gitignore` | `.env` 확인 |
| `llm/client.py` | `parallel_tool_calls=False` |
| `graph/nodes.py` | tool 오류 경계, confidence 방어, thought fallback, 프롬프트 |
| `tools/agent_tools.py` | 분석 tool 8개에 `reason` 인자 |
| `tests/test_graph_nodes.py` | 테스트 4개 추가 |
| `tests/test_agent_tools.py` | 테스트 1개 추가 |

---

## 1. `config.py` — LLM 설정 환경변수화

`.env` + `load_dotenv()` 는 이미 쓰고 있었으므로, **`os.getenv` 로 감싸는 것**이 실제 변경분.
핵심은 `LLM_MODE` 의 기본값을 `mock` 으로 두는 것 — 그래야 `pytest` 가 사내 서빙을 안 탄다.

```python
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()   # 반드시 os.getenv 호출들보다 위에

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "yield.db"
EMB_DIR = BASE_DIR / "data" / "embeddings"

# ... (YIELD_THRESHOLD, EDS_* 등은 변경 없음) ...

# LLM: "mock" = 규칙 기반(사내망 밖 데모), "openai" = 사내 OpenAI 호환 서빙
LLM_MODE = os.getenv("LLM_MODE", "mock")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://<사내-llm-호스트>/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "dummy")
LLM_MODEL = os.getenv("LLM_MODEL", "<사내-모델명>")
```

**주의:** 기본값에 실제 사내 호스트를 박지 말 것. `.env` 가 없으면 mock 으로 안전하게 떨어져야 한다.

### 우선순위 동작
`load_dotenv()` 는 기본이 `override=False` → **이미 `os.environ` 에 있는 값은 `.env` 가 덮어쓰지 않는다.**
따라서 셸에서 준 값이 `.env` 보다 우선한다. 의도한 동작.

---

## 2. `.env` — LLM_MODE 를 넣지 말 것 ⚠️

```bash
# .env — 접속 정보(비밀)만
LLM_BASE_URL=https://실제-사내-호스트/v1
LLM_API_KEY=실제키
LLM_MODEL=실제-모델명
# LLM_MODE 는 여기 넣지 않는다 — 기본 mock 유지
```

`.env` 에 `LLM_MODE=openai` 가 있으면 `pytest` 도 사내 LLM 을 타서
`test_e2e.py::test_full_loop_reaches_report_with_audit_trail` 이 깨진다 (실제로 겪음).

**역할 분리:** 모드는 셸에서, 접속 정보는 `.env` 에서.

---

## 3. `requirements.txt` — python-dotenv 추가

```
langgraph==1.2.6
langchain-openai==1.3.3
hnswlib==0.8.0
numpy==1.26.3
pytest==8.3.4
python-dotenv==1.0.1     # ← 추가
```

집에서 확인: `python -m pip install -r requirements.txt`

---

## 4. `.gitignore` — `.env` 추적 여부 확인

```powershell
git check-ignore -v .env
```
출력이 없으면 추적 대상 → **API 키 커밋 위험.** `.gitignore` 에 `.env` 추가.
`.env.example` 을 키 없이 만들어 두면 다른 사람이 뭘 채울지 알 수 있다.

---

## 5. `llm/client.py` — `parallel_tool_calls=False`

`OpenAILLMClient.__init__` 의 `bind_tools` 한 줄만 수정:

```python
        self.analyzer = self.llm.bind_tools(ALL_TOOLS, parallel_tool_calls=False)
```

미룸 항목 5번(한 AIMessage 에 finalize + 다른 tool 이 섞이는 문제)이 사실상 닫힌다.
서빙이 이 파라미터를 모르면 400 → 그때는 `bind_tools(ALL_TOOLS)` 로 되돌린다.
(사내 서빙에서는 정상 동작 확인됨)

---

## 6. `graph/nodes.py` — 4곳 수정

### 6-1. `tools_node` 의 `else` 분기 — tool 오류 경계 (미룸 1번)

**문제:** `TOOLS_BY_NAME[call["name"]]` 직접 인덱싱 + `.invoke()` 무방비
→ 실제 LLM 이 없는 tool 이름/잘못된 인자를 내면 KeyError/ValidationError 로 그래프 전체가 예외 종료.

**교체 (else 분기 전체):**

```python
        else:
            tool = TOOLS_BY_NAME.get(call["name"])
            if tool is None:
                result = (f"오류: '{call['name']}' 는 존재하지 않는 tool 이다. "
                          f"사용 가능한 tool: {', '.join(TOOLS_BY_NAME)}. "
                          f"이 중에서 다시 선택해 호출하라.")
            else:
                try:
                    result = tool.invoke(call["args"])
                except Exception as e:  # 인자 스키마 위반·조회 실패 등
                    result = (f"오류: {call['name']} 실행 실패 "
                              f"({type(e).__name__}: {e}). 인자를 확인하고 다시 호출하라.")
            out_msgs.append(ToolMessage(
                json.dumps(result, ensure_ascii=False),
                tool_call_id=call["id"], name=call["name"],
            ))
            findings.append({
                "loop": loop, "tool": call["name"], "args": call["args"],
                "result": result, "thought": ai.content or call["args"].get("reason", ""),
            })
```

- 예외를 삼키지 않고 **ToolMessage 로 LLM 에게 되돌려준다** → 다음 analyze 에서 스스로 교정 (tool-calling 루프 표준 패턴)
- `except Exception` 통짜는 의도적 — LLM 이 저지를 실수 종류를 미리 열거할 수 없다

### 6-2. `thought` fallback (위 코드에 이미 포함)

```python
"thought": ai.content or call["args"].get("reason", ""),
```

**`ai.content` 를 먼저 보는 순서가 중요.** mock 은 `content` 에 판단을 넣고 `reason` 은 안 주므로,
이 순서라야 mock 동작이 그대로 유지된다.

### 6-3. `_finalize_gate` — confidence 비숫자 방어 (미룸 2번)

**문제:** LLM 이 `"high"` 같은 비숫자를 주면 `float()` 에서 ValueError 크래시.

기존 첫 줄 `conf = float(args.get("confidence", 0.0))` 를 교체:

```python
    raw = args.get("confidence", 0.0)
    try:
        conf = float(raw)
    except (TypeError, ValueError):
        conf = 0.0
        conf_note = (f" (confidence 로 받은 '{raw}' 은 숫자가 아니다 — "
                     f"0~1 사이 숫자로 다시 제출하라)")
    else:
        conf_note = ""
```

그리고 **확신도 미달 반려 메시지에만** `conf_note` 를 붙인다
(반려 return 이 두 군데 — 확신도 미달 / 가설 불일치. 전자에만):

```python
    if conf < config.CONFIDENCE_THRESHOLD:
        return (f"반려: 확신도 {conf:.2f} < {config.CONFIDENCE_THRESHOLD}."
                f"{conf_note} 근거를 좁힐 tool 을 더 호출하라.")
```

### 6-4. `ANALYZE_SYSTEM_PROMPT` — reason 규칙으로 교체

기존의 "tool 호출 시 … 이유를 한두 문장으로 함께 서술하라" 는 **꼬리에 붙어 있던 지시**였고,
실제 LLM 은 tool call 시 `content` 를 비우므로 무력했다. `reason` 인자 규칙으로 대체:

```python
ANALYZE_SYSTEM_PROMPT = """너는 반도체 수율 분석 전문가다. 불량 그룹(유사 불량 wafer 들)과 대조 그룹(같은 lot 의 정상 wafer 들)을 비교해, 불량 그룹만의 공통 원인을 특정 공정 단계(가능하면 장비)까지 좁혀라.

규칙:
- 매 단계, 지금까지의 tool 결과로 원인을 확신할 수 있는지 스스로 평가하라.
- 확신이 부족하면 근거를 좁힐 tool 을 하나 더 호출하라. 그룹 간 차이(장비·파라미터)가 핵심 근거다 — compare_process_logs 로 두 그룹을 대조하라.
- tool 을 호출할 때는 reason 인자에 현재 가설과 그 tool 을 고른 이유를 한 문장으로 반드시 담아라 — 이 서술이 그대로 분석 감사 기록에 남는다.
- 원인을 좁혔고 근거가 충분하면 finalize(hypothesis, confidence) 로 종료를 제안하라. 확신도가 낮으면 반려된다.
- 수치는 tool 결과를 그대로 인용하고 절대 임의로 만들지 마라."""
```

---

## 7. `tools/agent_tools.py` — 분석 tool 8개에 `reason` 인자

**왜:** 실제 LLM 은 tool call 시 `content` 를 비운다 → 감사 기록의 `판단:` 줄이 전부 빈다.
프롬프트로 부탁했지만 지켜지지 않았다(첫 턴만 됨). **스키마로 강제**하는 것이 확실.

**패턴:** 마지막 인자로 `reason: str = ""`, docstring 끝에 한 줄.
**기본값 `""` 은 필수** — 없으면 기존 테스트(`invoke({"wafer_id": ...})`)가 스키마 위반으로 깨진다.
**`finalize` 는 제외** — `hypothesis` 가 이미 그 역할.

```python
@tool
def get_wafer(wafer_id: str, reason: str = "") -> dict | None:
    """wafer 1장의 수율·defect_type·공정·날짜를 조회한다.
    대상 wafer 의 기본 정보가 필요할 때 사용.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.get_wafer(wafer_id)


@tool
def search_similar(wafer_id: str, k: int = 5, reason: str = "") -> list[dict]:
    """불량 맵 패턴이 유사한 과거 wafer 를 찾는다.
    과거 사례와 비교해 원인 단서를 얻으려면 가장 먼저 사용.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return _searcher_lazy().search(wafer_id, k=k)


@tool
def aggregate_defects(wafer_ids: list[str], reason: str = "") -> list[dict]:
    """여러 wafer 의 defect_type 분포를 집계한다.
    유사 wafer 들이 같은 불량 유형을 공유하는지 확인할 때 사용.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.aggregate_defects(wafer_ids)


@tool
def get_process_log(wafer_id: str, reason: str = "") -> list[dict]:
    """wafer 의 공정 단계별 장비·파라미터 로그를 조회한다.
    in_spec=False 인 행이 스펙 이탈. 원인을 특정 공정/장비까지 좁히려면 반드시 확인.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.get_process_log(wafer_id)


@tool
def compare_process_logs(group_ids: list[str], control_ids: list[str],
                         reason: str = "") -> dict:
    """불량 그룹과 대조 그룹(정상 wafer)의 공정 로그를 대조해, 불량 그룹만
    공통으로 거친 장비(suspect_equipment)와 불량 그룹의 스펙 이탈
    (group_spec_violations)을 찾는다. 그룹 간 차이로 원인 공정/장비를 좁힐 때 사용.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.compare_process_logs(group_ids, control_ids)


@tool
def validate_data_completeness(wafer_ids: list[str], reason: str = "") -> dict:
    """분석 대상 wafer 들의 수율 행 누락·공정 로그 단계 누락·중복 로그를 검사한다.
    그룹 대조(compare_process_logs) 전에 호출해 데이터가 결론에 쓸 만큼 완전한지 확인.
    status=blocked 면 비교 결과를 신뢰하지 말고 리포트에 품질 경고를 남겨야 한다.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.validate_data_completeness(wafer_ids)


@tool
def compare_parameter_distribution(group_ids: list[str], control_ids: list[str],
                                   process_step: str | None = None,
                                   param_name: str | None = None,
                                   reason: str = "") -> list[dict]:
    """불량 그룹과 대조 그룹의 공정 파라미터 분포(표본 수·평균·표준편차·효과 크기·
    스펙 이탈률)를 (공정, 파라미터) 단위로 비교한다. compare_process_logs 가 지목한
    후보의 정량 검증, 또는 스펙 이탈이 없어도 그룹 간 차이를 찾을 때 사용.
    process_step/param_name 으로 범위를 좁힐 수 있다.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.compare_parameter_distribution(group_ids, control_ids,
                                             process_step, param_name)


@tool
def find_counterexamples(equipment_id: str, process_step: str,
                         defect_type: str, reason: str = "") -> dict:
    """가설 '(공정, 장비)가 defect 의 원인'에 반하는 사례를 전수 데이터에서 찾는다:
    해당 장비를 거쳤지만 정상인 wafer, 장비 없이 같은 defect 가 난 wafer.
    finalize 전에 호출해 가설의 특이성(반례 유무)을 확인하고 리포트에 인용.
    reason: 이 tool 을 호출하는 판단 이유를 한 문장으로 기술한다 (감사 기록에 남는다)."""
    return yt.find_counterexamples(equipment_id, process_step, defect_type)
```

`reason` 은 함수 본문에서 사용하지 않는다 (감사 기록용). 의도된 설계.
`ANALYSIS_TOOLS` / `ALL_TOOLS` / `TOOLS_BY_NAME` 정의는 **변경 없음.**

---

## 8. `tests/test_graph_nodes.py` — 테스트 4개 추가

파일 맨 아래에 추가. 상단 import 에 `AIMessage`, `nodes` 는 이미 있음.

```python
def test_tools_node_recovers_from_unknown_tool_name():
    ai = AIMessage(content="", tool_calls=[
        {"name": "functions.get_wafer", "args": {"wafer_id": "W2406_02"}, "id": "c1"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    assert "오류" in out["messages"][0].content
    assert "get_wafer" in out["messages"][0].content


def test_tools_node_recovers_from_bad_args():
    ai = AIMessage(content="", tool_calls=[
        {"name": "aggregate_defects", "args": {"wafer_ids": "W2406_02"}, "id": "c1"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    assert "오류" in out["messages"][0].content


def test_finalize_gate_handles_non_numeric_confidence():
    ai = AIMessage(content="종료 제안", tool_calls=[
        {"name": "finalize", "args": {"hypothesis": "Etch ETCH-9 원인",
                                      "confidence": "high"}, "id": "cf"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": []})
    assert "finalize_accepted" not in out
    assert "숫자" in out["messages"][0].content


def test_tools_node_falls_back_to_reason_when_content_empty():
    # 실제 LLM 은 tool call 시 content 를 비우므로 reason 인자가 감사 기록을 채운다
    ai = AIMessage(content="", tool_calls=[
        {"name": "get_process_log",
         "args": {"wafer_id": "W2406_02", "reason": "스펙 이탈 확인"}, "id": "c1"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    assert out["findings"][0]["thought"] == "스펙 이탈 확인"
```

---

## 9. `tests/test_agent_tools.py` — 테스트 1개 추가

```python
def test_reason_is_optional_and_ignored():
    # reason 은 감사 기록용 — 있어도 없어도 결과는 같다
    args = {"wafer_ids": ["W2406_02"]}
    assert (at.TOOLS_BY_NAME["aggregate_defects"].invoke(args)
            == at.TOOLS_BY_NAME["aggregate_defects"].invoke({**args, "reason": "테스트"}))
```

---

## 10. 임시 파일 — 커밋 금지

연동 확인용으로 만든 스모크 스크립트. **집에서 재현할 필요 없음. 있으면 삭제.**

- `smoke_a.py` — 연결 확인 (`ChatOpenAI(...).invoke("안녕")`)
- `smoke_b.py` — tool calling 확인 (`bind_tools(ALL_TOOLS).invoke(...)`)

---

## 검증 절차 (집에서 적용 후)

```powershell
# 1) 의존성
python -m pip install -r requirements.txt

# 2) 더미 데이터 (최초 1회)
python data/generate_dummy.py

# 3) mock 회귀 — 63 passed 기대 (약 1초, 네트워크 안 탐)
python -m pytest -v

# 4) 사내 LLM 실행 (사내망에서만)
$env:LLM_MODE="openai"; $env:PYTHONUTF8="1"; python main.py

# 되돌리기
Remove-Item Env:LLM_MODE
```

**주의:** `pytest` 명령이 PATH 에 없을 수 있음 → `python -m pytest` 를 쓸 것.

### 통과 기준
- `python -m pytest` → **63 passed**, 1초 내외 (오래 걸리면 `.env` 에 `LLM_MODE` 가 들어간 것)
- `main.py` → 감사 기록 1~4번 모두 `판단:` 줄이 채워짐
- 리포트 수치가 tool 결과와 일치 (`ETCH-9`, `rf_power 570.0`, `스펙 450.0~550.0`, `7장`)

---

## 커밋 제안 (집에서)

```bash
git add config.py requirements.txt .gitignore
git commit -m "feat: LLM 설정 환경변수화 (.env + os.getenv, 기본값 mock)"

git add graph/nodes.py llm/client.py tests/test_graph_nodes.py
git commit -m "fix: 사내 LLM 연동 안정화 - tool 오류 복구, confidence 방어, 단일 tool call"

git add tools/agent_tools.py graph/nodes.py tests/
git commit -m "feat: tool reason 인자로 감사 기록 확보 (실제 LLM 은 content 를 비운다)"
```

---

## 아직 안 한 것 (다음 작업)

### 문서 갱신 (권장)
- **`docs/deferred-internal-integration.md`**
  - 1번(tool 오류 → ToolMessage) → 완료 표시
  - 2번(confidence 비숫자 방어) → 완료 표시
  - 5번(finalize 후속 tool) → `parallel_tool_calls=False` 로 닫힘
  - 8번 첫 항목(환경변수 오버라이드) → 완료
  - 7번(실패 경로 테스트) → 일부 완료 (알 수 없는 tool 이름, 비숫자 confidence). 실제 LLM 통합 테스트는 미착수
- **`README.md`**
  - "빠른 시작" 이 `config.py` 를 손으로 고치는 전제로 쓰여 있음 → 환경변수 실행법 + `.env` 설정 반영
  - `pytest` → `python -m pytest` 표기

### 미룸 항목 중 남은 것
- **4번 TLS 검증** — EDS `http` 전환 시 필수 (`EDS_HTTP_VERIFY=False` 가 기본값)
- **6번 HTTP EDS 응답 스키마 실측**
- **7번 실제 LLM 통합 테스트** — `@pytest.mark.integration` 마커로 분리.
  단언은 "반려가 있었다"가 아니라 "리포트 도달 + findings 에 compare_process_logs 존재" 수준으로 느슨하게

### 사내 적용 전체(7단계) 관점 진행도
- 1단계 연동: **LLM ✅ / EDS `http` ❌**
- 2단계 안정화: **필수 항목 ✅ / TLS ❌**
- 3~7단계(실데이터, EvidenceBundle 게이트, 권한·사람 검토, 평가셋, 배포): 미착수

---

## 이번에 확인된 사실 (기록용)

1. **사내 서빙 tool calling 정상** — tool 이름 정확 일치(접두사 없음), args 가 dict + 리스트 인자 정상, 단일 호출, `parallel_tool_calls=False` 수용
2. **실제 LLM 은 tool call 시 `content` 를 비운다** — 감사 기록은 프롬프트 부탁이 아니라 **스키마(`reason`)로 받아야 한다.** 이번에 실증
3. **LLM 이 수치를 지어내지 않았다** — 리포트의 `7장` 이 `find_counterexamples` 의 `equipment_wafers: 7` 과 일치. "LLM 은 판단과 표현만, 수치는 tool 에서만" 이라는 프로젝트 핵심 주장이 실제 사내 모델에서 검증됨
4. **실제 모델의 분석 경로가 mock 각본보다 낫다** — mock: `aggregate_defects` → finalize(0.6) 반려 → `compare_process_logs` → finalize(0.9).
   실제: `aggregate_defects` → `validate_data_completeness` → `compare_process_logs` → `find_counterexamples` → finalize.
   로드맵의 권장 흐름(품질 검사 → 후보 발굴 → 근거 검증 → 게이트)과 거의 일치. 반려가 없는 건 근거를 먼저 쌓기 때문이라 정상
5. **모델이 `confidence: 1.0` 을 자기 신고** — 3장 대 3장 비교로 "인과관계 검증", "직접적인 원인" 은 과한 주장.
   로드맵이 경고한 "원인과 상관관계 혼동" 의 실제 사례. EvidenceBundle 게이트(Phase 1)가 필요한 이유의 실증
6. **반례가 양방향 0인 건 더미 데이터 설계 때문** — `generate_dummy.py` 가 center_spot ↔ ETCH-9 를 1:1 로 심어서 반례가 나올 수 없다.
   **시연 시 "더미 데이터가 깨끗해서 나온 결과이고 실데이터에서는 이렇게 안 나온다"고 먼저 설명할 것.**
   역으로, 평가셋에 반례가 강한 사례를 넣으면 에이전트가 제대로 물러설 줄 아는지 알 수 있다

### 시연 시 유의
README 는 "반려→재시도→승인 순환이 End-to-End 의 핵심" 이라고 내세우는데,
**실제 사내 LLM 에서는 이 순환이 안 보인다** (근거를 먼저 확보하고 finalize 하므로).
시연에서 그 순환이 핵심 볼거리라면 별도 논의 필요.
