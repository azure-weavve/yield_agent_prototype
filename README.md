# yield_agent — 반도체 수율 분석 AI Agent 프로토타입

LangGraph 기반 AI Agent가 자연어 질문을 받아 **현황 파악 → 분석 루프(tool 자율 호출) → 리포트**로
이어지는 하이브리드 reasoning loop를 더미 데이터 위에서 End-to-End로 시연하는 프로토타입입니다.

운영 중인 사내 EDS 유사맵 시스템(Flask `/search`)과 사내 LLM 서빙에 붙는 구조를 설계하고,
사내망 접근 없이도 동일 그래프가 돌도록 외부 의존성을 **인터페이스 뒤로 추상화**했습니다.

## 보여주는 것 (세 키워드)

- **Agentic AI** — Agent가 스스로 tool 을 골라 호출하며 근거를 좁히고, 게이트가 그 근거를 확인해 주면 루프를 끝낸다.
- **Legacy 연계** — 사내 EDS/LLM에 붙는 구조를 단일 인터페이스로 설계 (mock ↔ 사내 교체).
- **End-to-End** — 현황 파악부터 원인 규명 리포트까지, 감사 기록(findings)이 남는 한 흐름으로 이어진다.

## 데모

```
$ PYTHONUTF8=1 python main.py

[분석 대상 입력] (auto) W2406_06

[현황 파악 — 고정 골격]
분석 대상 입력 (auto): W2406_06
형제 묶기 (EDS, 컷오프 0.8): 7장 — 입력 + W2406_02(0.93), W2413_cen4(0.923), W2411_cen2(0.922), W2410_cen1(0.92), W2412_cen3(0.918), W2406_04(0.915)
대조군 (같은 root_lot 비타깃): 78장 — LOT2402 18장, LOT2403 18장, LOT2404 19장, LOT2405 19장, LOT2406 4장 · 수율 중앙값 95.3, 임계 90.0 미만 10장

[분석 루프 — 감사 기록]
  1. finalize  args={'claim_id': '', 'hypothesis': '불량 그룹 7장이 한 사건으로 묶였다 - 공통 원인 존재 추정', 'confidence': 0.6}
     판단: 그룹은 묶였지만 공정 근거가 아직 없다. 이 정도로 종료를 제안해 본다.
     게이트: 반려: 통과한 후보가 없다. 아직 실행하지 않은 가설 도구가 있다: hyp_eqp_ch_commonality, hyp_ppid_commonality, hyp_step_passage_commonality. 먼저 호출하라.
  2. hyp_eqp_ch_commonality  args={'group_ids': ['W2406_06', 'W2406_02', 'W2413_cen4', ...], 'control_ids': ['W2401_001', ...]}
     판단: 종료 제안이 반려됐다. 챔버 편중 가설로 두 그룹을 대조한다.
  3. compare_sensor_distribution  args={'step_seq': 'CC002000', 'group_ids': ['W2406_06', 'W2406_02', 'W2413_cen4', ...], 'control_ids': ['W2401_001', ...]}
     판단: 챔버까지 좁혔다. 그 스텝의 센서 분포로 '왜' 를 본다.
  4. finalize  args={'claim_id': 'eqp_ch_commonality:chamber:CC002000:ETCH9_B', 'hypothesis': 'CC002000 공정 ETCH9_B 편중(분리 점수 1.0, 불량군 3장 전용)이 원인 - rf_power_steady_avg 효과크기 2.573', 'confidence': 0.9}
     판단: 챔버 편중에 센서 근거까지 붙었다. 근거 충분.
     게이트: 승인 (근거 확인): eqp_ch_commonality:chamber:CC002000:ETCH9_B · 분리 점수 1.0 · 타깃 3/3 통과 · 대조군 0/4 통과. 리포팅으로 진행한다.

[리포트 — 고정 골격]
...
[결론] CC002000 공정 ETCH9_B 편중(분리 점수 1.0, 불량군 3장 전용)이 원인 - rf_power_steady_avg 효과크기 2.573 (확신도 0.9)
[근거] eqp_ch_commonality:chamber:CC002000:ETCH9_B · 분리 점수 1.0 · 타깃 3/3 통과 · 대조군 0/4 통과
```

> 실제 실행 출력입니다. wafer 목록과 `control_ids`(78장)만 `...` 로 줄였습니다.

현황 파악이 지목한 wafer(`W2406_06`) 를 EDS 유사맵으로 형제 묶기(컷오프 0.8)한 불량 그룹 7장과,
형제 lot 들의 대조군을 대상으로 Agent 가 tool 을 자율적으로 호출하며 근거를 쌓습니다.
**게이트는 근거 없는 결론을 반려합니다** — 위 1번처럼 도구가 발급한 `claim_id` 없이 낸 finalize 는
`analyze` 로 되돌려 보내집니다. 확신도는 넘어야 할 필요조건일 뿐, 승인 근거는 그 claim 입니다.

> 다만 위 반려→재시도 순환은 **mock LLM 각본에서 보이는 모습**입니다. 실제 사내 LLM 은 대개
> 근거를 먼저 쌓고 finalize 하므로 반려가 나타나지 않습니다 — 정상 동작이며, 볼거리는
> 순환 자체가 아니라 **승인 실권이 LLM 자기 신고가 아니라 findings 의 결정론적 증거에 있다는 점**입니다.

## 빠른 시작

요구사항: Python 3.11

```bash
pip install -r requirements.txt

# 더미 데이터 생성 (yield.db + 512차원 임베딩 인덱스 + 공정 로그) — 최초 1회
python data/generate_dummy.py

# 테스트 전체 실행
python -m pytest

# 데모 실행 (자동 모드 — 최악 lot 의 최저 wafer 를 대상으로 선정)
PYTHONUTF8=1 python main.py

# 수동 모드 (대상 wafer 지정, lot_wafer 결합 형태)
python main.py W2406_02
python main.py W2407_01 W2407_02
```

수동 모드는 wafer 를 1장 넘기면 EDS 유사맵으로 형제를 묶고, 여러 장을 넘기면 그 그룹을 그대로
분석합니다. 형제 lot 대조군이 3장 미만이면 "대조군 부족"으로 조기 종료합니다.

> Windows 콘솔에서 한글이 깨지면 `set PYTHONUTF8=1` 후 실행하세요.

## 아키텍처

```
status ──(대상 있음)──▶ analyze ──(tool call)──▶ tools ──(반려/계속)──▶ analyze   ← 순환
 (고정)     │               │                      │
            │               └─(호출 없음)           └─(finalize 승인/한계 도달)
            └─(조기 출구)          ▼                      ▼
                   ▼             report ◀────────────────┘
                   └──────────────▶ (고정)
```

- **status → report 골격은 고정 엣지**입니다: 반드시 현황 파악으로 시작해 리포팅으로 끝납니다.
- **analyze ⇄ tools 만 LLM 자율 순환**입니다: 어떤 tool 을 언제 호출할지는 Agent(LLM)가 결정합니다.
- **수치 계산은 결정론적 tool**(SQLite 쿼리 / HNSW 검색 / 공정 로그 조회)이 전담합니다.
- **LLM은 판단과 표현만** 담당합니다. 수치는 tool 결과에서만 나오며 — mock 리포트는
  템플릿 렌더링이라 수치 변형이 구조적으로 불가능하고, openai 리포트는 프롬프트로 인용을
  강제하되 감사 기록(findings) 원본이 함께 남아 수치를 대조·검증할 수 있습니다.

## 분석 루프

`analyze` 노드에서 Agent 는 `get_wafer`, `search_similar`,
`hyp_*` 가설 도구, `finalize` 를 자율적으로 호출합니다.
매 호출은 `findings` 에 감사 기록(`loop`, `tool`, `args`, `result`, `thought`)으로 남습니다.

- **hyp_eqp_ch_commonality** (1차): 타깃 전원이 거쳤고 대조군은 안 거친 (공정 스텝, 설비/챔버)를
  찾습니다. 설비 롤업과 챔버 세부를 함께 냅니다 — 엔지니어가 가장 먼저 돌리는 주 분석입니다.
- **hyp_ppid_commonality** (2차): 설비/챔버로 두 그룹이 안 갈릴 때 PPID 축으로 다시 봅니다.
- **hyp_step_passage_commonality**: "그 스텝을 **거쳤는가**" 자체를 후보로 냅니다. 비정규 스텝
  (`step_seq` 접미 `EC`)처럼 지나는 lot 과 안 지나는 lot 이 갈리는 축을 잡습니다. 위 두 가설은
  "그 스텝 안에서 무엇을 썼는가" 만 보므로, 타깃이 같은 비정규 스텝을 제각각 다른 설비로
  거치면 후보가 쪼개져 신호가 사라집니다. 전원이 거치는 정상 스텝은 분리 점수가 0 이라
  자동으로 탈락합니다.
- **compare_sensor_distribution** (2단): 1단이 지목한 스텝에서 두 그룹의 센서 통계값
  분포를 비교해 효과크기 top-K 를 냅니다. 1단이 "어느 챔버" 라면 2단은 "왜" 입니다.
  센서 값은 트레이스가 아니라 wafer 1장의 구간 통계값이며, 구간·통계 종류가 센서
  이름에 들어 있습니다(`rf_power_steady_avg`).

이 `hyp_*` 도구는 손으로 짠 것이 아니라 **`domain/hypotheses.yaml` 의 선언에서 생성**됩니다.
각 가설은 "어느 축(legend)으로 공통성을 돌릴지"만 선언하고, 계산은 공용 commonality 엔진이
합니다. 새 인과 가설을 추가할 때 tool 코드를 새로 짤 필요 없이 YAML 에 항목을 추가하면 됩니다.

- **finalize 게이트**: Agent 가 결론을 제안(`finalize`)할 때 판정 근거는 LLM 이 쓴 자유 텍스트
  `hypothesis` 가 아니라 **도구가 발급한 `claim_id`** 입니다. 게이트는 그 claim_id 로
  EvidenceBundle 을 조회해 통과 여부·같은 도구 안 최고 점수 여부·확신도를 확인합니다 —
  승인 실권은 LLM 자기 신고가 아니라 findings 의 결정론적 증거에 있습니다. 반려되면
  claim_id 미제출·미통과·최고 점수 아님·확신도 미달·미실행 가설 도구 존재 중 무엇이
  걸렸는지를 그대로 돌려받아 `analyze` 로 되돌아가 근거를 더 쌓습니다.

- **가드레일(MAX_LOOPS)**: 루프가 한계(기본 6회)에 도달하면 확신도와 무관하게 강제로 리포팅으로
  진행합니다 — 무한 루프를 원천 차단합니다. 이때의 finalize 는 승인이 아니라
  **미확정(루프 한계 도달)** 으로 구분 기록되고, 리포트 결론도 확정이 아닌 유력 가설 제시로 나갑니다.

## 조기 출구 (분석 루프를 아예 돌지 않는 경로)

`status` 노드가 **분석의 전제**를 확인하고, 전제가 안 서면 LLM 을 부르지 않고 바로
리포팅으로 보냅니다. 전제가 없는데 루프를 돌리면 근거 없는 결론이 나오기 때문입니다.
사유는 `finalize_status` 에 남고 리포트 결론 문장도 사유별로 갈립니다 — **사람이 할 조치가
사유마다 다르기 때문에** 하나로 뭉뚱그리지 않습니다.

| `finalize_status` | 언제 | 사람이 할 일 |
|---|---|---|
| `no_anomaly` | 수율 임계 미만 lot 이 없다 (자동 선정이 빈손) | 없음 — 정상 |
| `unknown_target` | 입력한 wafer 가 yield DB 에 없다 | 입력 오타 또는 적재 누락 확인 |
| `eds_lookup_failed` | wafer 는 DB 에 있는데 EDS 유사맵 조회가 실패했다 | EDS 인덱스↔DB 동기화·서비스 상태 확인 (사유를 단정하지 않고 예외 원문을 싣습니다) |
| `isolated` | 형제가 없다 (컷오프 미만) | 고립 패턴 — 자동 분석 범위 밖, 수동 판단 |
| `control_insufficient` | 같은 root_lot 의 비타깃 wafer 가 `CONTROL_MIN_SIZE` 미만 | 대조군을 만들 수 없음 — 대조 없이 결론 내지 않습니다 |

루프를 돈 뒤의 종료 사유는 다섯입니다.

| `finalize_status` | 언제 | 사람이 할 일 |
|---|---|---|
| `confirmed` | 게이트가 claim_id 를 조회해 근거를 확인했다 (통과 후보 + 그 도구 안 최고 점수 + 확신도 충족) | 리포트의 `[근거]` 줄을 보고 현장 확인 |
| `no_signal` | 등록 가설을 전부 대조했으나 타깃만 거친 후보가 없다 (계산 결과가 `no_signal` 인 가설이 하나 이상일 때) | 원인 없음이 아니라 lot 내부 대조의 한계 — 대조군을 lot 밖으로 넓혀야 합니다 |
| `no_comparable_data` | 돌아간 가설이 전부 계산 자체를 못 했다 (`no_paired_stratum`·`insufficient_group`) | **근거를 못 찾은 게 아니라 볼 것이 없었습니다** — 적재 범위와 추출 조건을 확인합니다. legend 와 무관한 그룹 수준 사실이라 남은 가설을 기다리지 않고 첫 판정에서 끝냅니다 |
| `inconclusive` | 루프 한계까지 근거를 좁히지 못했다 | 분석 기록을 보고 사람이 이어받습니다 |
| `llm_call_failed` | 분석 LLM 호출이 실패해 루프를 못 돌렸다 | LLM 서빙 상태를 확인하고 재실행합니다. 분석이 **안 돌았다**는 뜻이라 `inconclusive` 와 다릅니다 |

## 디렉토리 구조

```
prototype/
├── ya_config.py           설정 (데이터 경로, EDS/LLM 모드 토글, 임계값, 도구 플래그)
├── ya_console.py          콘솔 출력 래퍼 (cp949 에서 인코딩 오류로 산출물을 잃지 않게)
├── main.py                실행 진입점 (하이브리드 분석 루프 데모)
├── data/
│   ├── generate_dummy.py  더미 생성 (yield + step_history + 임베딩, 유사 그룹 심기)
│   ├── load_internal.py   사내 실데이터 적재 ETL (추출은 사내 lib — _extract() 에 연결)
│   ├── yield.db           (생성물) SQLite — gitignore
│   └── embeddings/        (생성물) hnswlib 인덱스 — gitignore
├── domain/                도메인 전문가가 손대는 자리
│   ├── hypotheses.yaml    인과 가설 선언 (어느 축으로 공통성을 돌릴지)
│   ├── registry.py        YAML 로드·검증 → hyp_* tool 동적 생성
│   └── engine.py          가설 선언 → commonality 호출로 잇는 어댑터
├── tools/
│   ├── agent_tools.py     @tool 래퍼 + LLM 노출 목록 (레거시 게이팅)
│   ├── commonality.py     공통성 계산 엔진 (legend = 임의의 축)
│   ├── yield_tools.py     수율 조회·집계 (결정론 SQLite)
│   ├── grouping.py        EDS 형제 묶기 / 대조군 선정
│   ├── target_selection.py 분석 대상 자동 선정
│   └── eds_search.py      EDS 유사맵 도구 (인터페이스 + 로컬/HTTP 구현)
├── llm/
│   └── client.py          LLM 클라이언트 (인터페이스 + mock/사내 OpenAI 구현)
└── graph/
    ├── state.py           LangGraph 상태 (findings 감사 기록, loop_count 등 누적형)
    ├── nodes.py           현황 파악 / 분석(tool-calling) / tool 실행+게이트 / 리포트 노드
    └── build.py           그래프 조립 (status → analyze ⇄ tools → report)
```

## 인터페이스 ↔ 구현 교체 (mock ↔ 사내)

외부 의존성은 추상 인터페이스 뒤에 두고, 모드 하나로 구현을 바꿔 끼웁니다.
사내망 밖에서는 기본값(local/mock)으로 동일 그래프가 그대로 동작합니다.

설정은 두 갈래입니다 (`ya_config.py` 가 `load_dotenv()` 를 호출합니다):

- **환경변수 / `.env` 로 덮어쓸 수 있는 것** — 외부 연동 3종은 **전부** 여기 있습니다.
  `LLM_MODE`·`LLM_BASE_URL`·`LLM_API_KEY`·`LLM_MODEL`·`LLM_TIMEOUT`·`LLM_MAX_RETRIES`·`USER_NAME`,
  `EDS_MODE`·`EDS_URL`·`EDS_HTTP_VERIFY`,
  `SENSOR_MODE`·`SENSOR_HTTP_URL`·`SENSOR_TOP_K`·`SENSOR_MIN_SAMPLE`, 그리고 임계값
  `COMMONALITY_PASS_MIN_SCORE`·`COMMONALITY_PASS_MIN_TARGET`·`SIBLING_MIN_SIMILARITY`·`CONTROL_MIN_SIZE`
- **아직 `ya_config.py` 파일 상수인 것** — `EDS_MIN_SIMILARITY`·`SIBLING_SEARCH_K`·
  `YIELD_THRESHOLD`·`MAX_LOOPS`·`CONFIDENCE_THRESHOLD`

> `SENSOR_MODE` 를 빼먹으면 2단 센서가 조용히 죽습니다 — 기본값 `local` 이 읽는
> `sensor_log` 는 사내 적재 DB 에 없습니다 (`사내-투입-점검표.md` 4-5).

| 설정 | 데모(기본) | 운영(사내) |
|------|-----------|-----------|
| `LLM_MODE`  | `mock` — 규칙 기반 분류·표현 | `openai` — 사내 OpenAI 호환 서빙 (`base_url` 지정) |
| `EDS_MODE`  | `local` — 로컬 hnswlib (실제 HNSW 로직 재사용) | `http` — 사내 Flask `/search` HTTP 호출 |

LLM만 사내로 전환(`LLM_MODE=openai` + `EDS_MODE=local`)해도 더미 데이터 그대로 시연됩니다.
LLM은 데이터를 만들지 않고 도구 결과를 표현만 하므로, 식별자를 사내 것에 맞출 필요가 없습니다.

## 더미 데이터 설계

`generate_dummy.py`는 LOT2406에 불량 3장(W2406_02/04/06, 수율 76~82)과
대조 3장(W2406_01/03/05, 수율 93~97)을 심습니다. 어느 쪽이 불량인지는 데이터에
적혀 있지 않고(라벨 컬럼은 전 행 NULL), 수율과 아래 원인 신호로만 드러납니다. 원인 신호는
두 층에 있습니다 — `step_history` 에는 불량군 전용 챔버 `ETCH9_B`(+`PPID_X`)가 "어느
챔버인가"로, `sensor_log` 에는 그 스텝의 `rf_power_steady_avg` 이동이 "왜"로 들어 있습니다.
1단이 전자, 2단이 후자를 씁니다. 이와 별도로 4개의 패턴 그룹은 전부
과거 wafer로 구성되어, `search_similar`가 참조하는 유사 사례 풀 역할을 합니다(각 그룹은
임베딩 공간에서 서로 가깝고 생성기 내부 정답지 `_truth_defect`가 같습니다 — DB 컬럼
`yield.defect_type`은 모든 행이 NULL입니다). 불량 그룹은 `center_spot` 패턴 그룹과
임베딩 중심을 공유해, 유사 검색 시 관련 과거 사례가 반환됩니다.

> 512차원에서는 noise를 `1/√DIM`로 스케일해야 그룹 응집(코사인 유사도 ~0.92)이 성립합니다.
> 안 그러면 noise 노름이 중심 벡터를 압도해 그룹이 흩어집니다.

대조군은 **타깃과 같은 root_lot 의 비타깃 wafer 전원**입니다 — 수율·라벨 조건이 없습니다.
사내 `defect_type` 이 대부분 비어 있어 "정상"을 판정할 방법이 없기 때문입니다. 저수율 wafer 가
대조군에 섞이면 진짜 신호가 희석될 수 있는데, 이를 막는 대신 대조군의 수율 분포를 리포트에
함께 실어 판단 재료로 넘깁니다 — 걸러내면 그 정보 자체가 사라지고, 수율 임계로 거르면 임의
수치가 계산에 들어갑니다.

`root_lot` 하나가 여러 `lot` 으로 갈리는 사내 구조도 더미에 있습니다(`R2418` → `.1`/`.2`/`.3`).
타깃이 한 분할 lot 에 몰려 있어도 같은 root_lot 의 다른 lot 에서 대조군을 찾습니다.

## 한계와 다음 단계

- 사내 EDS는 자체 발급 인증서라 프로토타입은 `verify=False`로 우회합니다.
  운영 전환 시 사내 루트 인증서(`.pem`)를 확보해 `verify="인증서경로"`로 바꿉니다.
- 2단 센서 비교는 **그룹 대조**(같은 스텝의 타깃 vs 대조군)만 합니다. 원인이 전 구간에
  걸리는 경우(PM·부품 교체)는 시간 대조가 필요하며 아직 없습니다.
- 파라미터의 **스펙 이탈** 개념은 프로토타입에 없습니다. 사내 `step_history` 에는 파라미터가
  없고(설비·챔버·PPID 뿐), 값 비교는 2단 센서가 맡습니다. 옛 `process_log` 계열 도구는
  삭제했습니다(Stage 5).
- 사내 연동 시점으로 미룬 항목(오류 복구, 게이트 증거 조건, TLS 검증 등)은
  [docs/deferred-internal-integration.md](docs/deferred-internal-integration.md) 참고.
- 실데이터로 가기까지의 작업 순서와 각 단계 진입 조건은 [docs/stages.md](docs/stages.md) 가
  단일 출처입니다.
- `docs/` 에 문서가 31개 있는데 **일부는 과거 기록이라 그대로 따르면 안 됩니다.**
  어느 것이 살아 있는 지침인지는 [docs/README.md](docs/README.md) 색인이 판정해 줍니다.
