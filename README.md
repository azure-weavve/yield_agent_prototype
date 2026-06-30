# yield_agent — 반도체 수율 분석 AI Agent 프로토타입

LangGraph 기반 AI Agent가 자연어 질문을 받아 **의도 파악 → 도구 실행 → 답변 생성**으로
이어지는 reasoning loop를 더미 데이터 위에서 End-to-End로 시연하는 프로토타입입니다.

운영 중인 사내 EDS 유사맵 시스템(Flask `/search`)과 사내 LLM 서빙에 붙는 구조를 설계하고,
사내망 접근 없이도 동일 그래프가 돌도록 외부 의존성을 **인터페이스 뒤로 추상화**했습니다.

## 보여주는 것 (세 키워드)

- **Agentic AI** — Agent가 질문 의도를 스스로 분류해 적절한 도구로 라우팅한다.
- **Legacy 연계** — 사내 EDS/LLM에 붙는 구조를 단일 인터페이스로 설계 (mock ↔ 사내 교체).
- **End-to-End** — 두 질문이 같은 `wafer_id`로 이어지며 한 대화 안에서 끊김 없이 흐른다.

## 데모

```
$ python main.py

[질문] 이번 배치에서 수율 떨어진 lot 있어?
[의도] yield_query
[답변]
수율 임계 미만 lot (낮은 순):
- LOT2406: 평균 수율 84.8 (4장), 최저 wafer W2406_cen0 (수율 84.1, 불량 center_spot)

[질문] 그 wafer 불량 맵 패턴이 과거 어떤 사례랑 비슷해?
[의도] similar_search
[답변]
W2406_cen0 와 유사한 과거 wafer (유사도 순):
- W2411_cen2 (유사도 0.925)
- W2412_cen3 (유사도 0.922)
  ...
```

1번 답변의 worst wafer(`W2406_cen0`)가 상태에 저장되어, 2번 질문의 "그 wafer"로 자동 이어집니다.
이 멀티턴 연결이 End-to-End의 핵심입니다.

## 빠른 시작

요구사항: Python 3.11

```bash
pip install -r requirements.txt

# 더미 데이터 생성 (yield.db + 512차원 임베딩 인덱스) — 최초 1회
python data/generate_dummy.py

# 데모 대화 실행 (시나리오 1 → 2)
python main.py

# 단일 질문도 가능
python main.py "이번 배치에서 수율 떨어진 lot 있어?"
```

> Windows 콘솔에서 한글이 깨지면 `set PYTHONUTF8=1` 후 실행하세요.

## 아키텍처

```
[ 자연어 질문 ]
       │
   intent (LLM)  ── 의도 분류 → 라우팅 레이블
       │
   ┌───┴─────────────┐  (conditional edge)
   ▼                 ▼
yield_tool      similar_tool      ← 결정론적 도구 (정확한 수치)
 (SQLite)        (hnswlib HNSW)
   └───┬─────────────┘
       ▼
   answer (LLM)  ── 도구 결과 → 자연어 답변
       │
      END
```

- **수치 계산은 결정론적 함수**(SQLite 쿼리 / HNSW 검색)가 전담합니다.
- **LLM은 의도 해석과 표현만** 담당합니다 → 환각으로 인한 수치 오류를 구조적으로 차단.

## 디렉토리 구조

```
prototype/
├── config.py              설정 (데이터 경로, EDS/LLM 모드 토글, 임계값)
├── main.py                실행 진입점 (시나리오 1→2 연속 대화)
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
    ├── state.py           LangGraph 상태 (멀티턴 last_wafer_id)
    ├── nodes.py           의도 파악 / 도구 실행 / 답변 생성 노드
    └── build.py           그래프 조립 + 체크포인터(MemorySaver)
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
최근 1장 + 과거 4~5장으로 날짜가 분포합니다. 최근 1장이 시나리오 1에서 검출되고,
그 wafer로 유사 검색하면 같은 그룹의 과거 wafer들이 반환됩니다.

> 512차원에서는 noise를 `1/√DIM`로 스케일해야 그룹 응집(코사인 유사도 ~0.92)이 성립합니다.
> 안 그러면 noise 노름이 중심 벡터를 압도해 그룹이 흩어집니다.

## 한계와 다음 단계

- 사내 EDS는 자체 발급 인증서라 프로토타입은 `verify=False`로 우회합니다.
  운영 전환 시 사내 루트 인증서(`.pem`)를 확보해 `verify="인증서경로"`로 바꿉니다.
- 시나리오 3(유사 사례 원인 추정)은 상태·도구(`aggregate_defects`)가 준비되어 있으며 확장 예정입니다.
