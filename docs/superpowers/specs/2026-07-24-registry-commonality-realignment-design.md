# 레지스트리 ↔ commonality 재정렬 설계 (Stage 0, 좁게)

작성일: 2026-07-24
선행: `docs/superpowers/specs/2026-07-23-causal-hypothesis-registry-design.md`,
`docs/2026-07-24-domain-corrections.md`

## 1. 문제

인과가설 레지스트리(`domain/`)는 구현·main 병합까지 끝났으나, 데이터 접근층이
**옛 더미 스키마(`process_log`)에 묶여 사내 확정 스키마(`step_history`)와 충돌**한다.

- `domain/engine.py` 가 읽는 것: `process_log` / `equipment_id` / `eq_chamber`(합성) /
  `param_value`·`spec_low/high`, 그리고 `yield.defect_type` 조인.
- 사내 확정(corrections A-4/A-5): `step_history`(선적재, `eqp_id`+`ch_id` 분리) +
  `sensor_log`(온디맨드, **미구현**). `defect_type` 는 nullable, 그룹핑은 EDS(A-3).

그 결과 레지스트리는 더미 위에선 돌지만 **사내 데이터 위에선 못 돈다.**

## 2. 도메인 재발견 (설계를 바꾼 핵심)

브레인스토밍에서 현업 워크플로가 드러났다:

```
0. 이 랏이 (설비)평가랏인가?           → lot_type 은 낮은 가중치 컨텍스트 (DBKM 평가는 제외)
1. 타깃 vs 일반, EQP_CH PATH 가 나뉘나?  → commonality 가 하는 일 (1차·주 분석, legend=EQP_CH)
2. 안 갈리면 → "다른 부분" (보통 PPID 등, 불량 형태·엔지니어마다 다름)
```

핵심 통찰: **commonality 는 하나의 알고리즘이 아니라 "legend(축)를 바꿔가며 돌리는
패턴"이다.** EQP_CH 가 1차 legend 일 뿐이고, PPID 등 2차 legend 는 불량 형태와 엔지니어
판단에 따라 달라진다. defect_type 라벨이 없으니 자동 선택은 불가 → 에이전트/엔지니어가
메뉴에서 골라 돌린다(= 가설 = 도구 구조 유지).

→ **레지스트리의 정체 확정: "어떤 legend 로 commonality 를 돌릴지"의 메뉴를 도메인
전문가가 YAML 로 저작하는 자리.** commonality 는 고정된 "2×2 coverage-diff + root_lot
층화" 엔진을 제공하고, 가설은 그 엔진을 어느 legend 컬럼에 걸지를 선언한다. 이전 설계의
"겹침"(레지스트리 범주형 비교타입 vs commonality)이 이렇게 해소된다 — 겹치던 범주형은
commonality 로 흡수되고, 레지스트리는 legend 저작 전담이 된다.

## 3. 목표와 범위

**Stage 0 (이 문서, 좁게/surgical):** 레지스트리를 commonality 위에 앉힌다. 딱 그만큼만.

- **In scope:** commonality 를 legend 로 일반화, engine 을 legend 어댑터로 재편,
  hypotheses.yaml 을 legend 스키마로, registry 검증 갱신, generate_dummy 에 step_history
  신설 + yield 스키마 정합, `find_commonality` 정식 배선, 관련 테스트 재작성.
- **Out of scope (별도 워크스트림, 손대지 않음):** find_normal_wafers 대조군 재작성(B-3),
  status_node 재설계·defect_type→EDS 그룹핑(A-3), sensor_log 2단(SensorStore),
  yield_tools 레거시 도구(`get_process_log`·`compare_process_logs`·
  `compare_parameter_distribution`·`find_counterexamples`·`validate_data_completeness`).
  이들은 dummy 에서 process_log 로 계속 동작하고, 실데이터에선 이미 알려진 대기 상태다.

**제약:** `data/load_internal.py` 는 수정 금지(source of truth). `tools/commonality.py` 는
**프리즈 해제하되 행동보존**(기존 test 14케이스 green 유지)한다 — 사용자 승인(이 세션).

## 4. 아키텍처 — 층 구조

```
① tools/commonality.py  [프리즈 해제, 행동보존 리팩터]
     범용 2×2 coverage-diff + root_lot 층화 엔진.
     find_commonality(target, control, legend=EQP_CH_기본, top_k=None)
     legend 만 바꾸면 임의 축(EQP_CH·PPID…)에 동일 계산.
     → 후보: {level, process_step, key, score, coverage, 원시카운트, status}
        (결론 아닌 후보 — 판정하지 않는다. p-value 없음.)
        │
② domain/engine.py  [비교타입 → legend 어댑터로 재편]
     evaluate(spec, target, control):
       commonality.find_commonality(target, control, legend=spec["legend"]) 호출
       각 후보 → 게이트 계약으로 매핑:
         value  = [process_step, key]              (토큰 = key, 예 "ETCH9_3")
         passes = score ≥ 임계 AND target_pass ≥ 최소표본   (config)
       반환: {hypothesis_id, legend, status, candidates:[{value, passes, ...원시카운트}]}
        │
③ domain/registry.py  [스키마만 legend 로 교체]
     YAML legend 선언 로드·검증 → hyp_* 도구 동적생성 (호출부 engine.evaluate 그대로)
        │
④ graph/nodes.py 게이트  [무수정]
     _collect_evidence 가 passes + value[-1] 로 suspect 수집 — 계약 유지
```

핵심: **commonality 는 판정하지 않고(철학 유지: 후보≠결론), 판별(passes)은 게이트
계약을 맞추는 어댑터로 engine 에 얹힌다.** 반례 판별은 commonality 의 2×2 에 이미
내장돼 있다(b = 원인 없이 불량, c = 원인 거쳤는데 정상)이므로 defect_type 기반
`_counterexamples` 는 폐기한다.

## 5. legend 추상화 (YAML 저작면)

legend = 순서 있는 "레벨(롤업)"들. 각 레벨은 컬럼 묶음이며, 레벨의 컬럼이 전부
non-null 일 때만 후보를 낸다(현재 `_keys` 의 "ch_id 없으면 챔버 스킵, 가짜 키 금지"의
자연스러운 일반화).

```yaml
- id: eqp_ch_commonality
  name: 설비/챔버 공통성
  description: 타깃만 거친 (스텝, 설비/챔버)를 찾는다. 1차 legend.
  legend:
    - {level: equipment, columns: [eqp_id]}          # 설비 롤업
    - {level: chamber,   columns: [eqp_id, ch_id]}    # 설비+챔버 (ch_id 있을 때만)

- id: ppid_commonality
  name: PPID 공통성
  description: EQP_CH 로 안 갈릴 때, 타깃만 거친 (스텝, PPID)를 찾는다.
  legend:
    - {level: ppid, columns: [ppid]}
```

- **키 문자열**: 레벨 컬럼값을 `_` 로 조인. equipment 레벨(eqp_id 만) → `"ETCH9"`,
  chamber 레벨(eqp_id+ch_id) → `"ETCH9_3"`.
- **새 legend 추가 = 가설 한 줄 + step_history 에 컬럼.** 이것이 "도메인 지식 주입 자리"의
  실체다.
- `parameter_drift`(수치, numeric_distribution_shift)는 legend 스키마에 맞지 않고
  sensor_log 미구현이라 **레지스트리에서 제외**한다(Stage 3 에서 센서 기반으로 부활).

## 6. commonality.py 일반화 (행동보존)

`find_commonality(target_wafers, control_wafers, legend=EQP_CH_DEFAULT, top_k=None)`.

- **EQP_CH_DEFAULT** = `[("equipment", ["eqp_id"]), ("chamber", ["eqp_id","ch_id"])]`.
  legend 인자를 안 주면 현재 동작과 **바이트 단위로 동일**해야 한다.
- `_history()`: legend 가 필요로 하는 컬럼의 합집합을 `step_history` 에서 SELECT.
  요청 컬럼이 테이블에 없으면 명시적 에러(현 engine `_assert_column` 정신).
- `_keys(row, legend)`: 각 레벨에 대해, 레벨 컬럼이 전부 non-null/non-empty 이면
  `(level_name, process_step, tuple(값들))` 후보 키를 낸다.
- 나머지(root_lot 층화·결측 분리·no_signal·score·절단·meta)는 **불변**.
- 후보 dict 의 `key` 는 레벨 컬럼값을 `_` 로 조인. `level` 필드로 레벨명 유지.

**검증:** `tests/test_commonality.py` 14케이스가 legend 인자 없이 호출되어 그대로 green.
legend 일반화용 신규 케이스(PPID 단일레벨, 다레벨 롤업)를 추가한다.

## 7. engine.py 재편

- **제거:** `group_only_categorical`, `categorical_concentration`, `numeric_distribution_shift`,
  `_counterexamples`, `_usage`, `_numeric_rows`, `_cohens_d`, `_spec_violation_rate`,
  `_assert_column`, `COMPARISONS`. (수치 코드는 git 에서 Stage 3 때 복구 가능.)
- **신규:** `evaluate(spec, group_ids, control_ids)`:
  1. `res = commonality.find_commonality(group_ids, control_ids, legend=spec["legend"])`
  2. 각 후보 → `{value: [process_step, key], passes: <판별>, level, key, score,
     target_pass, target_total, control_pass, control_total, coverage_target,
     coverage_control}`.
  3. 반환 `{hypothesis_id: spec["id"], legend: spec["legend"], status: res["status"],
     candidates: [...], meta: res.get("meta")}`.
- **판별(passes) 기준 (config, 실데이터 보며 조정):**
  `passes = (status == "ok") AND score ≥ COMMONALITY_PASS_MIN_SCORE
            AND target_pass ≥ COMMONALITY_PASS_MIN_TARGET`.
  기본값 예: `MIN_SCORE=0.5`, `MIN_TARGET=2`. commonality 의 "임의 수치 금지·후보≠결론"
  정신에 따라 config 상수로 빼고 못 박지 않는다.

## 8. registry.py 변경

- `REQUIRED_FIELDS = ("id", "name", "description", "legend")` (comparison/column 제거).
- `load_hypotheses` 검증: `legend` 가 리스트이고 각 원소가 `{level, columns(list)}` 형태인지.
  (컬럼 존재 검증은 런타임에 commonality 가 수행하므로 여기선 구조만.)
- `build_tools`: 현행 유지 — 각 도구가 `engine.evaluate(spec, group_ids, control_ids)` 호출.

## 9. generate_dummy.py 변경

- **yield 스키마 정합(commonality 필수):** `root_lot_id`, `lot_type` 컬럼 추가.
  `defect_type` 는 dummy 에선 채워둔다(기존 그룹핑 데모 유지 — out of scope 워크스트림).
- **step_history 신설:** `(wafer_id, process_step, eqp_id, ch_id, ppid, timestamp)`.
  타깃 그룹이 특정 (스텝, eqp_ch) 와 (스텝, ppid) 를 공유하고 대조군은 아니도록 이상을 심어,
  EQP_CH·PPID 두 legend 가 각각 검출되게 한다.
- **process_log 는 유지** — 2단 수치 미리보기용(out of scope). step_history 와 느슨하게
  공존(타이트한 상관은 요구하지 않음).

## 10. agent_tools.py 변경

- **매달려 있던 raw `find_commonality` 래퍼(및 `from tools import commonality as cm`
  import)를 제거한다.** 새 아키텍처에서 EQP_CH commonality 는 `hyp_eqp_ch_commonality`
  (게이트 계약 shaped: passes/value 보유)로 도달한다. raw 래퍼는 passes/value 가 없어
  게이트가 증거로 쓸 수 없는 중복 도구다 — commonality 접근을 legend 메뉴로 일원화한다.
  (이 래퍼는 아직 커밋 안 된 M 변경이라 되돌리는 것.)
- `_HYPOTHESIS_TOOLS = registry.build_tools(registry.load_hypotheses())` 는 그대로 —
  이제 legend 기반 hyp_* 도구(EQP_CH·PPID)를 생성한다.
- 레거시 도구(`get_process_log`·`find_counterexamples`·`validate_data_completeness`)는
  **손대지 않는다**(out of scope, dummy 에서 계속 동작).

## 11. 테스트 영향

| 파일 | 조치 |
|---|---|
| `test_commonality.py` | 유지 + legend 신규 케이스(PPID·다레벨) 추가 |
| `test_engine.py` | 재작성 — 비교타입 → `evaluate` legend 어댑터(passes/value 매핑) |
| `test_registry.py` | legend 스키마 검증으로 갱신 |
| `test_dummy_data.py` | step_history + ppid + yield 신컬럼 단언 추가(process_log 단언 유지) |
| `test_agent_tools.py` | raw `find_commonality` 제거·hyp_* legend 도구 반영 |
| `test_graph_nodes.py` | 게이트 계약(commonality 유래 passes/value) 확인 |
| `test_e2e.py`, `test_mock_llm.py` | 도구 흐름이 legend hyp_* 로 결론 나는지 반영 |
| `test_yield_tools.py` | **무손** (레거시 도구 out of scope) |

## 12. 좁게 → 넓게 수렴 경로 (참고)

이 재정렬(Stage 0)은 넓게(단일 스키마)의 부분집합이다. 이후 이미 계획된 사내 전환
워크스트림이 하나씩 process_log/defect_type 의존을 걷어내면 넓게로 자연 수렴한다.

```
Stage 0  이 문서 — 레지스트리를 commonality(step_history) 위에.
Stage 1  _extract() 연결 → 실데이터로 commonality 1회 검증 (corrections §E).
Stage 2  find_normal_wafers → root_lot 기반 대조군 (B-3). 대조군 defect_type 의존 제거.
Stage 3  sensor_log + SensorStore, compare_parameter_distribution 재설계. parameter_drift 부활.
Stage 4  defect_type 그룹핑 → EDS top-k, status_node 재설계 (A-3).
Stage 5  process_log·레거시 도구 삭제 = 죽은 코드 정리. 단일 스키마 완성 (= 넓게).
```

Stage 2·3·4 는 각자 독립 워크스트림([[next-steps-internal-data-integration]]·corrections)
이며, 순서대로 착수하면 Stage 5 는 대공사 없이 자동 도달한다.

## 13. 성공 기준

1. `pytest` 전체 green (재작성 포함).
2. dummy DB(step_history 포함)에서 `hyp_eqp_ch_commonality`·`hyp_ppid_commonality` 가
   심어둔 이상을 검출(후보에 해당 key, `passes=True`).
3. 게이트: 검출된 key 를 담은 finalize 가설이 승인되고, 담지 않으면 반려됨.
4. commonality 접근이 legend hyp_* 도구로 일원화됨(raw `find_commonality` 래퍼 제거).
5. legend 인자 없는 기존 commonality 호출 결과 불변(행동보존).
