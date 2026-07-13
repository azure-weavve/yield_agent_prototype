# 근거 기반 수율 분석 고도화 로드맵

## 목적

이 문서는 현재 Yield Agent가 제공하는 "불량군 탐지 → 정상군 비교 → 공정 로그 조사 → 원인 가설 → 리포트" 흐름을, 현업 의사결정에 사용할 수 있는 근거 기반 분석 체계로 발전시키기 위한 설계안이다.

핵심 방향은 Tool의 개수를 늘리는 것 자체가 아니다. 각 결론이 다음 질문에 명확히 답하도록 만드는 것이다.

- 어떤 데이터가 이 결론을 지지하는가?
- 우연한 차이 또는 데이터 오류일 가능성은 얼마나 되는가?
- 정상 wafer에도 같은 현상이 존재하는가?
- 다른 lot 또는 시간대에서도 재현되는가?
- 현장 엔지니어가 다음에 취해야 할 조치는 무엇인가?

현재 구현에서는 LLM이 `finalize(hypothesis, confidence)`를 호출하고, 코드가 `CONFIDENCE_THRESHOLD` 이상인지를 확인한다. 앞으로는 LLM의 confidence를 최종 근거로 사용하지 않는다. 계산 가능한 증거를 코드로 산출하고, LLM은 그 증거의 해석·추가 조사 선택·리포트 작성에 사용한다.

## 현재 구조와 한계

현재 분석 그래프는 다음 구조를 가진다.

```text
status → analyze ⇄ tools → report
```

- `status`: 저수율 lot과 불량군/정상군을 결정한다.
- `analyze`: LLM이 다음 Tool 호출을 선택한다.
- `tools`: 조회·비교 Tool을 실행하고 `findings`에 감사 기록을 남긴다.
- `report`: 수집한 결과를 최종 리포트로 만든다.

현재 제공되는 주요 Tool은 wafer 조회, 유사 wafer 검색, 결함 집계, 개별 공정 로그 조회, 불량군/정상군 공정 로그 비교다. 이는 조사 시작점으로 적절하지만, 현재의 `compare_process_logs`는 공통 장비와 스펙 이탈 여부 중심이다. 다음 정보가 부족하다.

- 파라미터 차이가 얼마나 큰지와 우연일 가능성
- 불량군을 얼마나 잘 설명하는지와 정상군에서의 발생률
- 다른 lot·시간대에서 동일 현상이 다시 나타났는지
- 원천 데이터가 결론에 사용할 만큼 완전하고 신뢰할 수 있는지
- 가설에 반하는 사례와 그 영향

## 목표 원칙

### 1. 결론과 근거를 분리한다

분석 결과는 자연어 가설만이 아니라 기계가 검증 가능한 `EvidenceBundle`로 저장한다. 최종 리포트는 이 Bundle을 인용해야 하며, Bundle에 없는 수치·사실을 만들어서는 안 된다.

### 2. LLM은 판단 보조자, 코드와 데이터는 사실의 원천이다

LLM은 어떤 Tool을 추가 호출할지, 상충하는 근거를 어떻게 설명할지, 현장용 문장을 어떻게 쓸지를 담당한다. 그룹 간 수치 비교, 통계 검정, 데이터 품질 판정, 승인 게이트는 결정론적인 코드가 담당한다.

### 3. 원인과 상관관계를 구분한다

특정 장비 또는 파라미터가 불량군에서 많이 발견되었다는 사실만으로 원인이라고 단정하지 않는다. 원인 후보는 최소한 정상군 대비 차이, 반례, 시간적 선후관계, 재현성, 혼란 변수 여부를 함께 평가한다.

### 4. 불확실성은 숨기지 않는다

표본 수 부족, 결측 로그, 상반된 증거, 검증되지 않은 가설은 리포트에 명시한다. 이 경우에는 "원인 확정" 대신 "우선 조사 후보"와 "추가 확인 방법"을 제시한다.

## EvidenceBundle 설계

각 원인 후보는 아래와 유사한 구조로 표현한다. 실제 필드는 데이터 가용성에 맞추어 단계적으로 도입한다.

```json
{
  "hypothesis_id": "etch-9-rf-power-high",
  "hypothesis": "ETCH-9의 rf_power 상한 이탈이 center_spot 불량의 원인 후보이다.",
  "scope": {
    "target_wafer_ids": ["W2406_02", "W2406_04", "W2406_06"],
    "control_wafer_ids": ["W2406_01", "W2406_03", "W2406_05"],
    "analysis_period": {"start": "2026-07-01", "end": "2026-07-12"}
  },
  "evidence": {
    "target_count": 3,
    "control_count": 3,
    "target_match_rate": 1.0,
    "control_match_rate": 0.0,
    "effect_size": 2.1,
    "p_value": 0.01,
    "spec_violation_rate_target": 1.0,
    "spec_violation_rate_control": 0.0,
    "replicated_lots": 3,
    "counterexamples": []
  },
  "data_quality": {
    "status": "good",
    "missing_log_rate": 0.0,
    "timestamp_alignment_ok": true,
    "warnings": []
  },
  "scores": {
    "association": 0.95,
    "specificity": 1.0,
    "reproducibility": 0.8,
    "data_quality": 1.0,
    "counterexample_penalty": 0.0,
    "evidence_score": 0.87
  },
  "verdict": "confirmed_candidate",
  "recommended_next_step": "ETCH-9의 최근 유지보수·레시피 변경과 다음 생산 lot의 rf_power를 확인한다."
}
```

`effect_size`와 `p_value`는 표본 특성과 분포에 따라 적절한 검정법으로 계산한다. 작은 표본만 있는 초기 단계에서는 p-value를 과신하지 않고, 표본 수·효과 크기·재현성·반례를 함께 사용한다.

## 근거 점수와 최종 게이트

### 점수 구성

초기 버전에서는 0~1 범위의 점수로 정규화해 아래처럼 계산할 수 있다.

```text
evidence_score =
  0.30 × association
+ 0.25 × specificity
+ 0.20 × reproducibility
+ 0.15 × data_quality
+ 0.10 × temporal_consistency
- counterexample_penalty
```

- `association`: 대상군과 정상군 사이 파라미터·장비 사용의 차이 크기
- `specificity`: 대상군에서의 발생률은 높고 정상군에서는 낮은 정도
- `reproducibility`: 별도 lot·기간에서 같은 패턴이 재현되는 정도
- `data_quality`: 분석에 필요한 로그의 완전성 및 신뢰성
- `temporal_consistency`: 공정 이상이 수율 하락보다 앞서 발생했는지
- `counterexample_penalty`: 가설과 맞지 않는 정상/불량 사례의 비율과 심각도

가중치는 고정값으로 시작하되, 과거 사건 평가셋이 쌓이면 실제 정확도와 비용을 기준으로 조정한다.

### 판정 등급

| 등급 | 조건 예시 | 시스템 동작 |
| --- | --- | --- |
| `confirmed_candidate` | 점수 0.80 이상, 최소 표본 충족, 치명적 반례 없음 | 원인 후보로 보고하고 현장 확인 조치를 권고 |
| `investigate` | 점수 0.50~0.79 또는 재현성 부족 | 원인으로 단정하지 않고 필요한 추가 Tool/검증을 제안 |
| `insufficient_evidence` | 표본 부족·결측 과다·근거 상충 | 데이터 보강 요청과 분석 보류 사유를 보고 |
| `rejected` | 정상군에서도 동일하게 발생하거나 반례가 강함 | 후보에서 제외하되 반증 근거를 기록 |

### `finalize` 변경 방향

기존의 `finalize(hypothesis, confidence)`는 다음 중 하나로 바꾼다.

1. LLM이 `propose_hypothesis`로 후보만 제안한다.
2. 코드가 후보별 `EvidenceBundle`과 `evidence_score`를 계산한다.
3. `finalize`는 `hypothesis_id`만 받아 저장된 증거와 게이트를 확인한다.
4. 게이트를 통과하지 못하면 이유와 다음 검증 Tool을 `ToolMessage`로 반환한다.

이렇게 하면 "LLM이 0.9라고 말했기 때문"이 아니라 "대상군 일치율 100%, 정상군 일치율 0%, 재현 3 lot, 데이터 품질 양호"라는 설명 가능한 근거로 승인된다.

## 추가 Tool 우선순위

### 1단계: 신뢰 가능한 비교를 위한 Tool

#### `validate_data_completeness`

입력 wafer·분석 기간에 대해 yield, 공정 로그, 장비 식별자, recipe 버전, 타임스탬프의 누락·중복·비정상값을 검사한다.

- 반환: 필드별 결측률, 중복 건수, 제외 wafer, 차단/경고 상태
- 용도: 분석 전제 확인, EvidenceBundle의 `data_quality` 생성
- 우선순위가 높은 이유: 잘못된 데이터에서 나온 정교한 분석은 신뢰할 수 없다.

#### `compare_parameter_distribution`

불량군과 정상군의 동일 공정/장비/파라미터를 비교한다.

- 입력: `group_ids`, `control_ids`, 선택적 `process_step`, `equipment_id`, `param_name`
- 반환: 각 군의 표본 수·평균·중앙값·표준편차·분위수, 효과 크기, 검정 결과, 스펙 이탈률
- 용도: `compare_process_logs`가 찾은 후보를 정량 검증

#### `find_counterexamples`

가설과 상반되는 사례를 명시적으로 찾는다.

- 예: ETCH-9 rf_power 이탈이 있었지만 정상인 wafer, 이탈 없이도 동일 결함이 난 wafer
- 반환: 사례 목록, 발생률, 반례의 공통 조건
- 용도: 확증 편향 방지 및 원인 후보의 특이성 측정

### 2단계: 시간과 설비 문맥을 위한 Tool

#### `analyze_yield_trend`

lot, 날짜, shift, product, process step, equipment 기준으로 수율 추세·변화점·이상 구간을 찾는다.

#### `get_equipment_history`

장비의 유지보수, 부품 교체, 알람, calibration, 다운타임, recipe 배포 이력을 조회한다.

#### `get_recipe_version`

wafer가 통과한 recipe와 버전, 파라미터 변경 이력, 변경 승인 정보를 조회한다.

이 단계는 "이상값이 있었다"에서 "언제 어떤 변경 뒤에 이상이 시작됐는가"로 분석을 확장한다.

### 3단계: 재현성·의사결정 지원 Tool

#### `search_incident_cases`

과거 분석 리포트, 조치 결과, 유사 defect/장비/recipe 조합을 검색한다. 검색 결과에는 실제 해결 여부와 효과를 포함해야 한다.

#### `select_holdout_validation_set`

현재 결론 산출에 사용하지 않은 lot 또는 기간을 골라 가설이 독립 데이터에서도 유지되는지 검증한다.

#### `recommend_containment_action`

확정 원인을 자동으로 실행하지 않고, 증거 수준에 맞는 조치를 제안한다. 예: lot hold, 장비 점검, calibration 확인, recipe rollback 검토, 추가 샘플링.

#### `create_investigation_ticket`

사람의 승인 후 조사 티켓을 만들고, EvidenceBundle과 필요한 확인 항목을 연결한다. 외부 시스템 연동은 권한·승인·감사 요건을 만족한 뒤 도입한다.

## 권장 분석 흐름

```text
1. status
   └─ 저수율 lot, 대상군, 정상군 선정
2. validate_data_completeness
   └─ 차단 수준 품질 문제면 분석 보류
3. candidate discovery
   └─ 공정 로그 비교, 유사 사례, 시간·설비 이력으로 후보 발굴
4. evidence validation
   └─ 분포 비교, 효과 크기, 스펙 이탈률, 반례, holdout 재현성 계산
5. evidence gate
   ├─ confirmed_candidate: 조치 권고 포함 리포트
   ├─ investigate: 다음 확인 Tool 및 현장 점검 항목 제안
   └─ insufficient_evidence: 보류 사유와 데이터 보강 요청
6. human review 및 조치 결과 수집
   └─ 실제 결과를 사례 DB와 평가셋에 반영
```

LLM의 자유로운 Tool 선택은 3단계와 일부 4단계에 유지할 수 있다. 단, 품질 검사와 최종 게이트는 반드시 고정 노드 또는 코드 기반 Tool로 실행한다.

## 데이터 모델 확장

현 데이터의 `yield`, `process_log` 외에 다음 데이터가 있으면 분석 품질이 크게 높아진다.

- `equipment_event`: 장비 알람, 다운타임, 상태 변화, calibration
- `maintenance_history`: 유지보수, 부품 교체, 작업자, 완료 시각
- `recipe_history`: recipe 버전, 파라미터 변경 전후값, 승인자, 적용 범위
- `wafer_context`: product, layer, chamber, shift, operator, material batch
- `investigation_case`: 가설, EvidenceBundle, 엔지니어 판정, 실제 원인, 조치, 효과

모든 레코드에는 가능한 한 원천 시스템 ID, 수집 시각, 이벤트 시각, 버전 정보를 둔다. 리포트는 이 메타데이터를 바탕으로 분석 범위와 데이터 버전을 표시해야 한다.

## 운영 및 사람 검토

분석 결과의 권한을 다음처럼 구분한다.

- Agent: 조회, 분석, 가설 제안, 조치 초안 작성
- 코드 게이트: 증거 점수, 품질 기준, 최소 표본, 감사 로그 판정
- 엔지니어: 원인 승인, lot hold·recipe 변경·장비 조치 승인
- 운영 시스템: 승인된 작업만 티켓/알림/조치 시스템에 전달

리포트에는 결론 외에 반드시 다음을 포함한다.

- 분석 대상·기간·대상군/정상군 수
- 지지 근거와 반증 근거
- 데이터 품질 경고와 제외한 데이터
- 판정 등급 및 근거 점수 구성
- 권장 조치, 담당 역할, 확인 완료 기준

## 평가 지표와 검증 체계

Tool이나 프롬프트를 추가할 때는 과거 사례 또는 합성 시나리오로 회귀 평가한다. 최소 측정 항목은 다음과 같다.

| 범주 | 지표 | 의미 |
| --- | --- | --- |
| 원인 분석 | Top-1 / Top-3 원인 적중률 | 실제 원인이 후보 상위에 있는 비율 |
| 안전성 | 허위 원인 확정률 | 근거 부족한 후보를 확정으로 보고한 비율 |
| 근거성 | 필수 근거 충족률 | 표본·대조군·반례·품질 정보가 갖춰진 비율 |
| 재현성 | 독립 lot 검증 통과율 | holdout 데이터에서도 결론이 유지되는 비율 |
| 효율 | 평균 분석 시간·Tool 호출 수 | 운영 비용과 응답성 |
| 운영 효과 | 조치 후 수율 개선·재발률 | 실제 현장 가치 |

평가셋에는 정상 사례, 단일 원인 사례, 복합 원인 사례, 결측 데이터 사례, 강한 반례 사례를 모두 포함한다. 특히 "모른다" 또는 "추가 조사가 필요하다"고 올바르게 답하는 능력도 평가해야 한다.

## 단계별 구현 계획

### Phase 1 — 정량 근거의 최소 기반

1. `EvidenceBundle` 데이터 구조와 `findings` 연결
2. `validate_data_completeness` 구현
3. `compare_parameter_distribution` 구현
4. `find_counterexamples` 구현
5. `finalize`를 evidence score 기반 게이트로 변경
6. 리포트에 지지/반증 근거와 불확실성 표시

완료 기준: 각 확정 후보는 대상/정상군 표본 수, 비교 수치, 데이터 품질 상태, 반례 여부를 리포트에서 확인할 수 있다.

### Phase 2 — 시간·설비 문맥

1. 장비 이벤트·유지보수·recipe 이력 데이터 인터페이스 정의
2. 추세·변화점 분석 Tool 추가
3. 공정 변경과 수율 하락의 시간적 관계를 EvidenceBundle에 반영

완료 기준: 리포트가 특정 파라미터 이상뿐 아니라, 관련 변경/알람/유지보수 이력을 함께 제시한다.

### Phase 3 — 검증과 운영 폐루프

1. holdout lot 검증과 과거 사례 검색
2. 엔지니어 검토 화면 또는 승인 인터페이스
3. 조사 티켓과 조치 결과 수집
4. 평가셋·대시보드·회귀 테스트 운영

완료 기준: 분석 결과가 승인된 조치와 이후 수율 결과까지 추적되며, 실제 원인 판정이 다음 분석 개선에 사용된다.

## 구현 시 주의사항

- 작은 표본에서 통계적 유의성 하나만으로 결론을 내리지 않는다.
- 동일 lot의 wafer는 완전히 독립 표본이 아닐 수 있으므로 lot·chamber·시간대 단위의 군집 효과를 고려한다.
- 여러 파라미터를 동시에 탐색하면 우연히 유의해 보이는 후보가 늘어난다. 후보 탐색과 검증 데이터를 분리하거나 다중 비교 보정을 적용한다.
- Tool 출력 스키마는 버전 관리하고, 숫자의 단위·정밀도·결측 표현을 통일한다.
- 데이터 품질 경고가 있는 경우 높은 evidence score가 나오더라도 자동 확정하지 않는다.
- 외부 조치 Tool은 읽기 전용 분석 Tool과 분리하고, 사람 승인·권한 관리·감사 로그를 요구한다.

## 첫 구현 권장 순서

가장 높은 효과 대비 구현 난이도를 기준으로 아래 순서를 권장한다.

1. `validate_data_completeness`
2. `compare_parameter_distribution`
3. `find_counterexamples`
4. EvidenceBundle 및 evidence score 기반 `finalize` 게이트
5. `get_equipment_history`
6. `analyze_yield_trend`
7. holdout 검증과 과거 사례 검색

이 순서는 현재 SQLite 기반 구조와 `tools/yield_tools.py`, `tools/agent_tools.py`, `graph/nodes.py`의 역할 분리에 자연스럽게 맞는다. 먼저 결정론적 분석 Tool과 게이트를 추가하고, 이후 외부 설비·유지보수 시스템 연동은 현재의 EDS/LLM 인터페이스 분리 방식처럼 별도 어댑터로 확장한다.
