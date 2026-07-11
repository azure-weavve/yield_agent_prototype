# yield_agent — 반도체 수율 분석 AI Agent 프로토타입

LangGraph 기반 AI Agent가 자연어 질문을 받아 **현황 파악 → 분석 루프(tool 자율 호출) → 리포트**로
이어지는 하이브리드 reasoning loop를 더미 데이터 위에서 End-to-End로 시연하는 프로토타입입니다.

운영 중인 사내 EDS 유사맵 시스템(Flask `/search`)과 사내 LLM 서빙에 붙는 구조를 설계하고,
사내망 접근 없이도 동일 그래프가 돌도록 외부 의존성을 **인터페이스 뒤로 추상화**했습니다.

## 보여주는 것 (세 키워드)

- **Agentic AI** — Agent가 스스로 tool 을 골라 호출하며 근거를 좁히고, 확신도가 찰 때까지 루프를 돈다.
- **Legacy 연계** — 사내 EDS/LLM에 붙는 구조를 단일 인터페이스로 설계 (mock ↔ 사내 교체).
- **End-to-End** — 현황 파악부터 원인 규명 리포트까지, 감사 기록(findings)이 남는 한 흐름으로 이어진다.

## 데모

```
$ PYTHONUTF8=1 python main.py

[질문] 이번 배치에서 수율 이상 wafer 의 불량 원인을 분석해줘

[현황 파악 — 고정 골격]
- LOT2406: 평균 수율 84.8 (4장), 최저 wafer W2406_cen0 (수율 84.1, 불량 center_spot)

[분석 대상] W2406_cen0

[분석 루프 — 감사 기록]
  1. search_similar  args={'wafer_id': 'W2406_cen0'}
     판단: W2406_cen0 의 불량 맵과 유사한 과거 사례부터 확인한다.
  2. aggregate_defects  args={...}
     판단: 유사 wafer 들이 같은 불량 유형을 공유하는지 집계한다.
  3. finalize  args={'confidence': 0.6, ...}
     게이트: 반려: 확신도 0.60 < 0.8. 근거를 좁힐 tool 을 더 호출하라.
  4. get_process_log  args={'wafer_id': 'W2406_cen0'}
     판단: 종료 제안이 반려됐다. 원인 공정을 좁히기 위해 공정 로그를 확인한다.
  5. finalize  args={'confidence': 0.9, ...}
     게이트: 승인 (확신도 충족): 리포팅으로 진행한다.

[리포트 — 고정 골격]
...
[결론] Etch 공정 ETCH-9 장비의 rf_power 스펙 이탈(570.0, 스펙 450.0~550.0)이 원인 (확신도 0.9)
```

현황 파악이 지목한 wafer(`W2406_cen0`)를 대상으로 Agent 가 tool 을 자율적으로 호출하며 근거를
쌓다가, 확신도 낮은 finalize 시도는 게이트가 반려하고 더 조사하게 만듭니다. 근거가 충분해지면
게이트가 승인해 리포트로 넘어갑니다. 이 반려→재시도→승인 순환이 End-to-End의 핵심입니다.

## 빠른 시작

요구사항: Python 3.11

```bash
pip install -r requirements.txt

# 더미 데이터 생성 (yield.db + 512차원 임베딩 인덱스 + 공정 로그) — 최초 1회
python data/generate_dummy.py

# 테스트 전체 실행
pytest

# 데모 실행 (분석 루프 End-to-End)
PYTHONUTF8=1 python main.py

# 단일 질문도 가능
python main.py "이번 배치에서 수율 이상 wafer 의 불량 원인을 분석해줘"
```

> Windows 콘솔에서 한글이 깨지면 `set PYTHONUTF8=1` 후 실행하세요.

## 아키텍처

```
status ──▶ analyze ──(tool call)──▶ tools ──(반려/계속)──▶ analyze   ← 순환
 (고정)        │                      │
               └─(호출 없음)           └─(finalize 승인/한계 도달)
                      ▼                      ▼
                    report ◀────────────────┘
                     (고정)
```

- **status → report 골격은 고정 엣지**입니다: 반드시 현황 파악으로 시작해 리포팅으로 끝납니다.
- **analyze ⇄ tools 만 LLM 자율 순환**입니다: 어떤 tool 을 언제 호출할지는 Agent(LLM)가 결정합니다.
- **수치 계산은 결정론적 tool**(SQLite 쿼리 / HNSW 검색 / 공정 로그 조회)이 전담합니다.
- **LLM은 판단과 표현만** 담당합니다 → 환각으로 인한 수치 오류를 구조적으로 차단.

## 분석 루프

`analyze` 노드에서 Agent 는 `search_similar`, `aggregate_defects`, `get_process_log`,
`finalize` 등의 tool 을 자율적으로 호출합니다. 매 호출은 `findings` 에 감사 기록
(`loop`, `tool`, `args`, `result`, `thought`)으로 남습니다.

- **finalize 게이트**: Agent 가 결론을 제안(`finalize`)하면, 확신도(`confidence`)가 임계값
  (기본 0.8) 이상이어야 승인됩니다. 미달이면 반려되어 `analyze` 로 되돌아가 근거를 더 쌓습니다.
- **가드레일(MAX_LOOPS)**: 루프가 한계(기본 6회)에 도달하면 확신도와 무관하게 강제로 리포팅으로
  진행합니다 — 무한 루프를 원천 차단합니다.

## 디렉토리 구조

```
prototype/
├── config.py              설정 (데이터 경로, EDS/LLM 모드 토글, 임계값)
├── main.py                실행 진입점 (하이브리드 분석 루프 데모)
├── data/
│   ├── generate_dummy.py  더미 생성 (yield + 임베딩, 유사 그룹 심기)
│   ├── yield.db           (생성물) SQLite — gitignore
│   └── embeddings/        (생성물) hnswlib 인덱스 — gitignore
├── tools/
│   ├── yield_tools.py     수율 조회·집계 (결정론 SQLite)
│   └── eds_search.py      EDS 유사맵 도구 (인터페이스 + 로컬/HTTP 구현)
├── llm/
│   └── client.py          LLM 클라이언트 (인터페이스 + mock/사내 OpenAI 구현)
└── graph/
    ├── state.py           LangGraph 상태 (findings 감사 기록, loop_count 등 누적형)
    ├── nodes.py           현황 파악 / 분석(tool-calling) / tool 실행+게이트 / 리포트 노드
    └── build.py           그래프 조립 (status → analyze ⇄ tools → report)
```

## 인터페이스 ↔ 구현 교체 (mock ↔ 사내)

외부 의존성은 추상 인터페이스 뒤에 두고, `config.py`의 모드 한 줄로 구현을 바꿔 끼웁니다.
사내망 밖에서는 기본값(local/mock)으로 동일 그래프가 그대로 동작합니다.

| 설정 | 데모(기본) | 운영(사내) |
|------|-----------|-----------|
| `LLM_MODE`  | `mock` — 규칙 기반 분류·표현 | `openai` — 사내 OpenAI 호환 서빙 (`base_url` 지정) |
| `EDS_MODE`  | `local` — 로컬 hnswlib (실제 HNSW 로직 재사용) | `http` — 사내 Flask `/search` HTTP 호출 |

LLM만 사내로 전환(`LLM_MODE=openai` + `EDS_MODE=local`)해도 더미 데이터 그대로 시연됩니다.
LLM은 데이터를 만들지 않고 도구 결과를 표현만 하므로, 식별자를 사내 것에 맞출 필요가 없습니다.

## 더미 데이터 설계

`generate_dummy.py`는 "정상 다수 + 패턴 그룹 몇 개"를 생성합니다. 각 패턴 그룹은
임베딩 공간에서 서로 가깝고(중심 벡터 + 작은 noise), 같은 `defect_type`을 공유하며,
최근 1장 + 과거 4~5장으로 날짜가 분포합니다. 최근 1장이 현황 파악에서 검출되고,
그 wafer로 유사 검색하면 같은 그룹의 과거 wafer들이 반환됩니다.

> 512차원에서는 noise를 `1/√DIM`로 스케일해야 그룹 응집(코사인 유사도 ~0.92)이 성립합니다.
> 안 그러면 noise 노름이 중심 벡터를 압도해 그룹이 흩어집니다.

## 한계와 다음 단계

- 사내 EDS는 자체 발급 인증서라 프로토타입은 `verify=False`로 우회합니다.
  운영 전환 시 사내 루트 인증서(`.pem`)를 확보해 `verify="인증서경로"`로 바꿉니다.
- 분석 루프의 tool 목록(`search_similar`, `aggregate_defects`, `get_process_log`)은 데모 흐름
  기준이며, 실제 원인 계열이 늘어나면 tool 도 함께 확장될 여지가 있습니다.
