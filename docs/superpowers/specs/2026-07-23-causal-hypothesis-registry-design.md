# 인과 가설 레지스트리 — 설계 (spec)

> 작성일 2026-07-23. 트랙 A(도메인 지식 주입 틀)의 **1순위** 항목.
> 배경: `docs/도메인지식-주입-틀-공백분석.md` 의 "1순위 — 인과 가설 공간이 닫혀 있음".

## 0. 문제 (왜 이걸 만드는가)

지금 이 시스템이 내릴 수 있는 결론은 사실상 **하나**다: "불량 그룹만 거친 **장비** + 스펙 이탈". 원인은 게이트(`graph/nodes.py:_collect_suspects`)가 **오직 `compare_process_logs` 의 결과만** 증거로 인정하기 때문. 도구가 8개여도 인과 계열은 하나로 수렴한다.

실제 전문가는 훨씬 많은 가설을 안다(챔버 매칭, PM 타이밍, 소재 lot, 레시피 이력, 온도 드리프트…). 그러나 지금 구조에서 새 가설을 추가하려면 **개발자가 매번 새 도구를 짜고 게이트에 배선**해야 한다. 전문가가 "이런 것도 확인해봐"를 **데이터로 등록**할 자리가 없다.

**이 스펙의 목표:** 전문가가 코딩 없이 인과 가설을 **선언**하면, 시스템이 그걸 실행하고 **판별 시험을 통과한 가설만** 결론으로 승인하는 레지스트리를 만든다.

## 1. 확정된 설계 결정 (브레인스토밍 합의)

1. **LLM은 코드를 짜지 않는다.** 전문가는 "명세"를 쓰고, 개발자가 만든 범용 엔진이 결정론적으로 실행한다. 이 프로젝트의 원칙("수치는 tool 결과를 그대로 인용, 절대 임의 생성 금지" / "LLM은 제안, 코드가 결정")을 그대로 지킨다.
2. **통합 방식 = 가설 하나 = 도구 하나** (동적 생성). 전문가가 쓴 설명이 도구의 docstring이 되고 LLM이 읽고 필요할 때 호출한다. 기존 tool-calling 구조에 그대로 맞고, 공백분석 문서가 짚은 "docstring = 가장 깨끗한 주입점"을 실현한다.
3. **증명 수준 = 성과 증명(수준 2).** 더미 데이터에 컬럼 1개(`eq_chamber`, 설비ID+챔버ID 결합)를 추가해, 옛 시스템이 **절대 도달 못하던 새 인과 계열(챔버 편중)**을 YAML 등록만으로 여는 것까지 보여준다.
4. **핵심은 "진짜 인과 판별"이다.** 심어둔 신호를 되찾는 게 아니라, **여러 후보 중 진짜를 가려내는 것**이 목표. 가설 발화는 후보일 뿐이고, 판별 시험(특이성·반례·효과크기)을 통과해야 결론이 된다. 더미에 **미끼(decoy)**를 함께 심어 이 판별을 시험대에 올린다.
5. **사내 데이터도 같은 컬럼 계약을 따른다.** 더미의 `eq_chamber`는 사내 실데이터의 설비·챔버 결합 컬럼(엔지니어가 이미 `ETCH9_B` 로 보는 그 자리)과 같은 자리. 실컬럼(PM일자·소재lot 등)이 들어오면 YAML만 늘리면 확장된다(트랙 B와 접합).

## 2. 구조 (신규 `domain/` 패키지)

```
domain/
  hypotheses.yaml   ← 전문가 저작 영역 (코딩 아님)
  registry.py       ← YAML 로드 + 스키마 검증 + LangChain 도구 생성
  engine.py         ← 비교타입 3종 + 판별 계층 (결정론적, 개발자 영역)
```

이 패키지의 존재 이유는 **전문가/개발자 경계선**을 코드로 긋는 것이다: `hypotheses.yaml` = 전문가가 손대는 데이터, `engine.py`/`registry.py` = 개발자가 손대는 뼈대.

## 3. 레지스트리 스키마 (`hypotheses.yaml`)

각 항목:

```yaml
- id: <str>                 # 고유 식별자 (도구 이름의 근간)
  name: <str>               # 사람용 한글 이름
  description: <str>        # LLM이 읽는 docstring: "언제 이 가설을 보나"
  comparison: <str>         # 비교타입 3종 중 하나 (4절)
  column: <str>             # 참조할 데이터 컬럼
  # 판별 임계 (선택 — 없으면 engine 기본값)
  min_specificity: <float>  # 0~1
  min_effect_size: <float>  # 수치형에만 의미
```

초기 항목 3개:

```yaml
- id: equipment_commonality        # 기존 "장비 공통성"도 이제 한 항목
  name: 장비 공통성
  description: |
    불량 그룹 전원이 거쳤고 대조군은 안 거친 (공정,장비)를 찾는다.
    특정 장비가 원인으로 의심될 때 사용.
  comparison: group_only_categorical
  column: equipment_id

- id: chamber_concentration        # 신규 인과 계열 (옛 시스템 도달 불가)
  name: 챔버 편중
  description: 불량 그룹이 특정 설비·챔버 조합(예: ETCH9_B)에 몰려 있는지 확인한다. 챔버 매칭 불량 의심 시 사용.
  comparison: categorical_concentration
  column: eq_chamber               # 설비ID+챔버ID 결합 단위(엔지니어 관행). 챔버 없는 배치/원라인 설비는 빈 값→제외
  min_specificity: 0.9

- id: parameter_drift              # 스펙 안이어도 그룹간 값 차이
  name: 파라미터 드리프트
  description: 스펙 내라도 불량군의 파라미터 값이 대조군과 체계적으로 다른지 본다.
  comparison: numeric_distribution_shift
  column: param_value
```

새 가설 추가 = YAML 몇 줄. 개발자 호출 불필요.

## 4. 비교타입 3종 (`engine.py`)

개발자가 짜는 범용 primitive. 세 함수 모두 같은 계약:
`run(group_ids, control_ids, column, params) -> HypothesisResult`.

| 비교타입 | 계산 | 출처 |
|---|---|---|
| `group_only_categorical` | 불량군 전원 통과 & 대조군 0 인 값 | 기존 `compare_process_logs` 일반화 |
| `numeric_distribution_shift` | 평균차·Cohen's d·스펙 이탈률 | 기존 `compare_parameter_distribution` 일반화 |
| `categorical_concentration` | 불량군 내 특정 범주값 비율 vs 대조군 (편중) | **신규** |

범주형 비교(`group_only_categorical`, `categorical_concentration`)는 **공정 단계(`process_step`) 스코프 안에서** 평가한다 — 후보 `value` 는 (공정, 값) 쌍이다(예: `('Etch','ETCH-9')`, `('Etch','ETCH9_B')`). 챔버 단위는 **설비ID+챔버ID를 결합한 값**(`eq_chamber`, 엔지니어 관행)을 쓴다 — `ETCH1_B` 와 `ETCH2_B` 는 서로 다른 물리 챔버라 결합해야 구분되고, 설비/챔버를 따로 세면 게이트에서 중첩(같은 원인 이중 보고)이 생기므로 처음부터 하나로 본다. 챔버가 없는 배치/원라인 설비(CMP 등)는 이 값이 비어 있어 후보에서 조용히 제외된다. 같은 조합이라도 다른 공정에서는 별개 후보다. 수치형(`numeric_distribution_shift`)은 (공정, 파라미터) 단위(기존 `compare_parameter_distribution` 관행).

`HypothesisResult` (반환 형태):

```python
{
  "hypothesis_id": str,
  "comparison": str,
  "column": str,
  "candidates": [
     {
       "value": <suspect 값>,       # 예: 'ETCH9_B', ('Etch','ETCH-9'), 파라미터명
       "specificity": float | None, # 범주형만: 0~1 몰림/그룹전용 정도. 수치형은 None
       "counterexamples": {...},    # passed_but_normal / defect_without_cause
       "effect_size": float | None, # 수치형만
       "n_group": int, "n_control": int,
       "passes": bool,              # 판별 통과 여부
       "reject_reason": str | None, # 탈락 시 이유 (미끼 판별 근거)
     }, ...
  ],
}
```

## 5. 판별 계층 ("진짜 인과 찾기"의 심장)

가설이 발화해도 **후보일 뿐**이다. 각 후보는 세 시험을 거쳐 `passes` 판정을 받는다:

- **특이성(specificity)**: 불량군에만 몰렸나 (그룹전용 비율 / 편중 비율). `min_specificity` 미만이면 탈락.
- **반례(counterexamples)**: 그 원인인데 정상인 wafer 있나 / 그 원인 없이 불량 났나. 기존 `find_counterexamples` 를 임의 컬럼으로 일반화. 반례율이 높으면 탈락.
- **효과크기·표본수**: 수치형 한정. `min_effect_size` 미만이면 탈락.

**`passes` 는 비교타입별로 어울리는 잣대만 본다:** 범주형(`group_only_categorical`/`categorical_concentration`)은 특이성+반례로, 수치형(`numeric_distribution_shift`)은 효과크기+분포겹침(반례)으로 판정한다. **특이성은 범주형 전용 개념**이라 수치형 후보에선 `None` 이고 판정에 쓰지 않는다(타입이 다른 잣대를 하나의 숫자로 뭉개지 않는다 — 임의 수치 금지).

**미끼(decoy)는 발화하되 특이성/반례에서 탈락**한다. 판별 임계는 engine 기본값을 두되 YAML에서 가설별 override.

## 6. 게이트 일반화 (`graph/nodes.py`)

- `_collect_suspects`(오직 `compare_process_logs`) → **`_collect_evidence`**: 등록된 **모든** 가설 도구의 findings에서 `passes=True` 후보를 수집.
- `_finalize_gate` 승인 조건: confidence 충족 **AND** 가설 문장이 **판별 통과한 어떤 후보든** 지목. 장비뿐 아니라 챔버·파라미터도 결론 가능.
- **순위는 같은 비교타입 안에서만** 매긴다(특이성끼리·효과크기끼리 — 단위가 같아 비교가 정당). 타입이 다른 후보는 **하나의 점수로 뭉개지 않고 병렬 원인으로 함께 보고**한다(다인성 인정, 임의 수치 금지). 미끼는 진짜 챔버와 **같은 타입**이라 타입 내 순위에서 걸러진다. 반려 메시지·리포트에 **"왜 미끼가 아니라 이것인지"** 기록.
- 루프 한계 강제 종료(`inconclusive`)·confidence 비숫자 방어 등 기존 분기는 유지.

기존 도구 정리(targeted improvement): `compare_process_logs`/`compare_parameter_distribution` 의 인과 계산 로직은 engine 비교타입으로 이관하고, 이 두 도구는 레지스트리 항목으로 흡수한다. base 데이터 조회 도구(`get_wafer`, `search_similar`, `aggregate_defects`, `get_process_log`, `validate_data_completeness`)는 그대로 둔다.

**이관 순서(동작 보존 우선):**
1. `group_only_categorical` 을 engine 에 구현 → 기존 `compare_process_logs` 의 `suspect_equipment` 와 **동일 출력**임을 characterization 테스트로 고정.
2. `_collect_suspects`(도구 이름 하드코딩) 를 `_collect_evidence` 로 일반화하되 **기존 e2e/게이트 테스트 green 유지**.
3. `eq_chamber` 컬럼·`categorical_concentration`·챔버 가설 추가 — **여기서 새 능력이 처음 열림**.
4. 파라미터 도구를 `numeric_distribution_shift` 로 이관.

1·2 는 동작 불변 리팩터링(리스크는 테스트가 붙잡음), 새 능력은 3 부터.

**스펙 이탈 경로 흡수(확정):** 현재 `_collect_suspects` 는 `group_spec_violations` 의 **장비**도 용의자에 넣는다(스펙 밖 값이 찍힌 장비를 지목). 이 귀속은 부정확하므로(스펙 이탈은 장비가 아니라 **파라미터**에 대한 사실) `numeric_distribution_shift` 로 흡수한다:
- 수치형 결과에 **스펙 이탈률 필드**를 둔다(같은 `param_value`·`spec_low/high` 행에서 계산, 새 데이터 불필요).
- `_collect_evidence` 는 이 경로에서 **장비가 아니라 (공정, 파라미터) 후보**를 수집한다. 장비 지목은 공통성 경로(`group_only_categorical`)에만 맡긴다.
- 부수 효과: 대조군도 동일하게 스펙 밖인 경우 기존엔 무조건 장비를 지목했으나(오탐), 반례 검사로 걸러진다.

## 7. 데이터 (`generate_dummy.py`)

- `process_log` 에 `eq_chamber` 컬럼 추가(설비ID+챔버ID 결합, 예 `ETCH9_B`). 챔버 없는 설비 행은 빈 값.
- **진짜 원인**: 불량군 3장(`W2406_02/04/06`) 전부 Etch에서 **`ETCH9_B`**. 대조군은 **ETCH-9 를 쓰되 다른 챔버**(`ETCH9_C` 등)로 배치 → 설비 공통성(`equipment_commonality`)은 대조군도 ETCH-9 를 써서 **발화 안 하고**, 챔버 편중(`chamber_concentration`)만 `ETCH9_B` 를 특이적으로 집는다(설비→챔버로 좁혀짐, 이중보고 없음). 반례 없음.
- **미끼(decoy)**: 두 그룹이 **공유하는** `eq_chamber` 조합 하나 → 챔버 가설(`categorical_concentration`)에서 후보로 **발화하지만 특이성이 낮아 탈락**. 진짜(`ETCH9_B`, 특이성 높음)와 **같은 비교타입 안에서 특이성으로 갈린다**(§6 타입 내 순위). 편중 조사라야 미끼가 후보로 떠올라 판별 대상이 됨(완전공통 방식이면 공유 값은 애초에 안 떠오름). (기존 구멍 케이스 `UNLABELED_LOW_WAFER` 와 충돌 없게 배치.)
- 검증 포인트: 시스템이 **`ETCH9_B` 를 집고 미끼를 버리는가.**
- 난수열 보존: 신규 컬럼·신호는 기존 난수 소비 순서를 깨지 않도록 배치(기존 관행 유지, 파일 주석 참조).

## 8. 데이터 흐름

```
status(고정) → analyze(LLM) ⇄ tools(실행+게이트) → report(고정)
                              │
        base 데이터 도구(조회/검색) ─┤   ← 기존 유지
        registry 도구(YAML 생성) ───┘   ← 신규, engine 호출
```

골격 순서·안전장치(원자적 DB 교체, "수치는 코드만", "LLM은 제안·코드가 결정")는 그대로.

생성된 registry 도구의 시그니처는 기존 비교 도구와 동일: `(group_ids: list[str], control_ids: list[str], reason: str = "")`. column/params는 스펙이 고정(클로저)한다.

## 9. 에러 처리

- YAML 스키마 위반 → 로드 시 즉시 실패, 어느 가설·어느 필드인지 명시.
- 미지의 비교타입 → 로드 시 실패.
- 참조 컬럼이 데이터에 없음 → 생성된 도구가 "컬럼 X 없음(scope Y)" 을 명확히 반환. 기존 tool 오류복구 방식(크래시 대신 LLM에 재시도 안내)과 일관.

## 10. 테스트

- **비교타입 단위**: 진짜 원인 발화+통과 / 미끼 발화+탈락 (3종 각각, 픽스처 기반).
- **판별 계층 단위**: 특이성·반례·효과크기 임계 경계값.
- **레지스트리 로더**: 정상/불량 YAML, 없는 컬럼, 미지 비교타입.
- **게이트**: 비장비 가설(챔버) 승인 / 미끼 반려 / 경합 시 순위.
- **e2e**: 전체 그래프가 `ETCH9_B` 로 결론, 미끼 배제, 리포트가 근거를 인용하는지.
- 기존 e2e/게이트 테스트가 이관 후에도 green 유지(회귀 방어).

## 11. 이번 범위 밖 (YAGNI)

- 비교타입은 3종만. 시간 드리프트·PM 타이밍 등은 컬럼/타입이 갖춰지면 이후.
- 트랙 A의 나머지: 온톨로지(2순위)·피드백 루프(3순위)·임계값 저작 UI(4순위) 제외. **이번은 레지스트리만.**
- YAML은 수동 편집 (편집 UI 없음).
- 챔버는 결합 단위(`eq_chamber`)로 봐 설비/챔버 중첩을 애초에 없앤다. 다만 설비 단위 가설(`equipment_commonality`)과 챔버 가설이 **동시 발화하는 일반 케이스의 포함관계 정리**는 이번 범위 밖(데모는 데이터 설계로 회피). 필요 시 이후 게이트에서 다룬다.
- 사내 실데이터 연동(트랙 B)은 별개 — 단, 컬럼 계약을 맞춰 접합만 준비.

## 12. 성공 기준 (한 줄)

전문가가 `hypotheses.yaml` 에 **챔버 편중 가설을 한 줄 추가**하면, 시스템이 `ETCH9_B` 를 원인으로 찾아내되 **미끼는 판별로 걸러내고**, 그 판단 근거가 리포트에 결정론적으로 남는다 — 개발자가 코드를 짜지 않고.
