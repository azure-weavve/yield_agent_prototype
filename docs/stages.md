# Stage 표 — 실데이터에서 돌게 만들기까지

**이 문서가 Stage 순서의 단일 출처입니다.** 이전 판은 Stage 0 설계 문서
(`superpowers/specs/2026-07-24-registry-commonality-realignment-design.md` §12)의 참고 절에
얹혀 있었고, 2026-07-25 재배열이 반영되어 있지 않습니다.

갱신: 2026-07-28

---

## 현재 위치

```
Stage 0    ✅ 완료 (2026-07-24) — 레지스트리를 commonality(step_history) 위에 재정렬
Stage 1    ⏸  Stage 5.5 로 이동 (실데이터 · 사내 _extract() 작업 대기)
Stage A    ✅ 완료 (2026-07-25) — 안전장치 + 계약 동결 + 적대적 더미
Stage 2    ✅ 완료 (2026-07-25) — 대조군을 같은 root_lot 의 비타깃 전원으로
Stage 3    ✅ 완료 (2026-07-28) — sensor_log + SensorStore + 2단 센서 비교
Stage 4    ✅ 완료 (2026-07-28) — 더미에서 정답지 컬럼(defect_type·process_step) 제거
Stage 5    ✅ 완료 (2026-07-29) — process_log · 레거시 도구 삭제 = 단일 스키마 완성
Stage 5.5  ⬜ 구 Stage 1 — 실데이터 적재 · 검증 · 임계 튜닝
```

**Stage A 세부** (`2026-07-25-dummy-first-stage-reorder.md`): Task 0~6 전부 완료.
전체 테스트 133 passed. **다음은 Stage 2(대조군) — 별도 spec/plan 부터.**

Stage A 가 남긴 것: `test_schema_contract.py`(스키마 계약 동결)·`test_load_internal.py`
(적재 왕복)·`test_adversarial_dummy.py`(적대적 케이스)·`LEGACY_TOOLS_ENABLED`(Stage 5 에서
삭제)·`docs/stages.md`.

---

## 왜 Stage 1 을 뒤로 미뤘나

2026-07-25 결정. 두 가지가 착수 직전에 드러났습니다.

1. **Stage 1 은 Stage 2 없이 완주할 수 없다.** commonality 는 `(target, control)` 을 받는데,
   대조군을 만드는 `find_normal_wafers` 가 `defect_type = 'none'` 에 의존합니다. 사내
   `defect_type` 은 nullable 이라 실데이터에서 대조군이 비고 `no_paired_stratum` 으로 끝납니다.
   대조군 재작성이 곧 Stage 2 입니다.
2. **Stage 1 에 합격 기준이 없었다.** "실데이터로 commonality 1회 검증" 에서 무엇을 보면
   통과인지가 정의되지 않았습니다. 실데이터에는 정답지가 없어 후보가 나와도 맞는지 알 수 없습니다.

Stage 2~5 는 대부분 배선·계약·구조 문제이고, 수치 임계는 이미 `config` 상수 + "실데이터 보고
조정" 으로 분리하는 관행이 있습니다. 구조를 먼저 짜고 상수를 나중에 맞추는 것이 원래 설계 의도입니다.

**이 순서가 만드는 대가:** 더미는 정답을 심어둔 데이터라 green 이 실력인지 데이터가 착한
건지 구분이 안 됩니다. Stage A Task 4(적대적 더미)가 그 절반을 메웁니다.

---

## 각 Stage 진입 전 확인 사항

각 Stage 는 별도 spec/plan 을 씁니다. 착수 시 아래를 먼저 확인합니다.

### Stage 2 — 대조군 ✅ 완료

spec `superpowers/specs/2026-07-25-root-lot-control-group-design.md`,
플랜 `superpowers/plans/2026-07-25-root-lot-control-group.md`.

**대조군 = 타깃과 같은 root_lot 의 비타깃 wafer 전원** (수율·라벨·`lot_type` 조건 없음).
라벨 없이는 "정상"을 판정할 수 없으므로 판정을 없앴고, 저수율 혼입은 막는 대신
`yield_summary`(중앙값·임계 미만 장수)로 리포트까지 보인다. `lot_id` → `root_lot_id` 로
넓혀 분할 lot 이 갈려 있어도 대조군을 찾는다. 1/2단계 확장 개념(`stage` 키)은 폐기했다.

07-18 §7 에서 살아남은 것은 3단계(정직 보고 = `control_insufficient`)와 출처 명시뿐이다.
더미에 분할 lot `R2418`(`.1`/`.2`/`.3`)을 심어 root_lot 기준의 효과를 테스트로 고정했다.

### Stage 3 — 센서 (완료)

spec `superpowers/specs/2026-07-25-sensor-comparison-design.md` (2026-07-25),
플랜 `superpowers/plans/2026-07-25-sensor-comparison.md`.

**구현 완료 (2026-07-28, 158 passed).** `data/generate_dummy.py` 의 `sensor_log`
(케이스 4종) → `tools/sensor_store.py`(EDS 와 같은 local↔http 교체) →
`tools/sensor_compare.py`(효과크기 랭킹·top-K 절단·재-fetch 키) →
`compare_sensor_distribution` tool 등록. 캐시 DB 는 만들지 않았습니다.

더미 센서의 `spread` 는 임의 값이 아닙니다: 효과크기가 `이동폭/spread` 라
이 값이 곧 센서 순위를 정합니다. `std` 계열 spread 를 작게 잡으면 '분산만 이동'
케이스가 진짜 원인을 앞질러 1등이 되므로 avg 1.5 / std 1.2 로 맞췄습니다.

**남은 것 = 시간 대조.** 원인이 전 구간에 걸리는 경우(PM·부품 교체)는 그룹 대조로
잡히지 않습니다. 아래 결정 항목 4번이 그대로 남아 있으며, 실데이터를 보고 정합니다.

**⚠ 이전에 적어둔 "서브시스템 신설" 경고는 철회합니다.** 그 판단은 센서 데이터가
**트레이스**라는 가정 위에 있었는데, 실제로는 **wafer 1장의 구간 통계값**(구간·통계가 센서
이름에 포함된 형태)입니다. 분석당 수천~수만 행이라 `sensor_cache.db` 를 지금 만들 근거가
사라졌고, 규모는 **파일 두 개 + 더미 테이블**로 줄었습니다.

기준선은 **그룹 대조만**입니다. 시간 대조는 별도 Stage — 그것이 메우려는 사각지대에는
corrections B-3 의 "lot 밖 대조군 확장" 이 이미 후보로 있어, 실데이터 없이 한쪽을 못 박지
않습니다. 계약 3건·재-fetch 키·더미 케이스 4종은 spec 을 보십시오.

이로써 2단 깔때기가 붙어, 시스템이 "어느 챔버가 의심된다" 다음에 "그 스텝의 어느 센서가
갈렸다" 까지 말합니다. 다만 후보일 뿐 결론이 아니라는 것은 계약 3번 그대로입니다.

**계약 (어기면 분석이 성립하지 않습니다):**

1. **fetch 단위는 (지목된 스텝 × 타깃+대조군 전원).** 챔버 단위로 당기면 안 됩니다 — 1단이 그
   챔버를 지목한 근거가 "대조군은 안 거쳤다"(score=1.0 이면 control_pass=0)이므로, 지목된
   챔버만 뽑으면 대조군 표본이 0 이라 비교 자체가 성립하지 않습니다.
2. **tool 반환은 집계값만** (표본 수·평균·표준편차·효과크기). wafer 별 원본값은 ToolMessage 에
   싣지 않습니다. 분석당 수만 행이라 한 번만 어겨도 컨텍스트가 터집니다. 반환은 효과크기
   top-K 로 절단해 fetch 량과 무관하게 유계로 만듭니다.
3. **2단 출력은 후보이지 결론이 아닙니다.** p-value 컷이 아니라 효과크기 랭킹. 스텝당 센서
   수백 개라 α=0.05 면 우연히 수십 개가 유의합니다. tool 결과 `note` 에 명시합니다.

**결정 항목:**

4. **기준선을 그룹 대조로 할지 시간 대조로 할지.** 그룹 대조 = 같은 스텝의 다른 챔버,
   시간 대조 = 그 챔버의 과거 정상 구간. 둘은 다른 원인에 반응합니다 — PM·부품 교체는 시간
   대조로만 잡힙니다. `parameter_drift 부활` 이 후자를 암시하나 명시된 적이 없습니다.
   둘 다 하면 규모가 다시 늡니다.
5. ~~캐시 무효화 정책·`sensor_cache.db` 수명 주기~~ — **해소.** 캐시를 만들지 않기로 해
   무효화·수명 문제 자체가 사라졌습니다. 감사 추적은 반환의 `refetch_key`(스텝·타깃/대조군
   wafer 목록·`store_mode`)가 맡고, 이 키만으로 같은 집계값이 재현되는지를 테스트로
   고정했습니다. fetch 실패는 `status="fetch_failed"` 로 '결과 없음'과 구분합니다.

### Stage 4 — 정답지 제거 (완료)

spec `superpowers/specs/2026-07-28-ground-truth-removal-design.md`,
플랜 `superpowers/plans/2026-07-28-ground-truth-removal.md`.

**원래 Stage 4(`defect_type` 그룹핑 → EDS)는 Stage 2 가 흡수해 이미 끝나 있었다.**
A-3 이 지정한 코드 영향 3건(status_node 그룹핑 폐기·find_normal_wafers 재작성·형제
그룹핑 방법 확정)이 전부 완료 상태였다.

진짜 남은 문제는 **더미가 실데이터에 없는 정답지 두 컬럼을 값으로 들고 있다**는
것이었다. 적재기는 `yield.process_step` 에 NULL 을 강제하는데 더미는 `"Etch"` 를
채워 넣어, 같은 컬럼을 두고 둘이 반대로 행동했다. 라벨이 있으면 그룹핑이 라벨로도
되고 EDS 로도 되므로, EDS 경로가 실제로 성립하는지를 더미가 증명해 주지 못했다.

**한 것:** 생성기 정답지를 `_truth_*` 로 분리하고 두 컬럼을 NULL 로,
`aggregate_defects` 와 `label_counts` 삭제, 레거시 도구 기본 OFF(조용한 오확증 차단),
mock 각본을 라벨 없이 재작성하며 2단을 데모에 넣었다.

**`SIBLING_MIN_SIMILARITY` 컷오프는 여전히 미검증** — 실데이터 분포가 필요하다
(Stage 5.5). 컷오프를 못 정한 채 구조만 두는 것을 계속 감수한다.

### Stage 5 — 삭제 (완료)

spec `superpowers/specs/2026-07-29-stage5-legacy-removal-design.md`,
플랜 `superpowers/plans/2026-07-29-stage5-legacy-removal.md`.

**구현 완료 (2026-07-29, 139 passed).** 스키마가 `yield`·`step_history`·`sensor_log`
3개로 확정됐습니다.

**대체 매핑을 먼저 확인했고, 기능 유실은 없었습니다.** 품질 검사는 `load_internal.validate()`
(적재 시점)와 commonality 의 `missing_history`·`no_paired_stratum`(분석 시점)이, 반례는
commonality 2×2 의 `control_pass` 가, 파라미터 비교는 2단 센서가 이미 흡수하고 있었습니다.
`compare_process_logs`·`compare_parameter_distribution` 은 tool 로 등록된 적도 없는 죽은
코드였습니다. **결정적 근거: `load_internal.py` 는 `yield`·`step_history` 만 만듭니다 —
`process_log` 테이블 자체가 실데이터에 없습니다.**

한 곳은 등가가 아니라 **범위 축소**입니다: 옛 `find_counterexamples` 는 전수 데이터에서
해당 장비를 거친 wafer 를 모두 훑었지만, `control_pass` 는 **선택된 같은 root_lot 대조군
안**만 셉니다. 다른 root_lot 의 반례는 안 보입니다. 이는 Stage 2 의 층화 결정에서 나온
의도된 축소이고, 라벨이 전 행 NULL 이라 옛 도구는 어차피 무력했으므로 실질 손실은 없습니다.

**불변식 재작성이 이 Stage 의 유일한 실질 판단이었습니다.** 더미의 "심은 이상은 심은 곳에만"
이 `process_log` 의 스펙 이탈로만 표현돼 있었는데, `_make_step_history` 는 **과거 패턴
wafer 에 신호를 심지 않습니다**(데모가 타깃 7장 중 "불량군 3장 전용"이라고 말하는 이유).
과거 wafer 에 신호를 심으면 `target_pass` 가 3→7 로 바뀌어 데모가 깨지므로, 손실을 받아들이고
**챔버 배타성**(`ETCH9_B` 를 거친 wafer 는 `GROUP_WAFERS` 뿐)과 **"같은 설비 다른 챔버"**
전수 단언으로 좁혀 다시 썼습니다. 구멍 케이스 (가)의 "스펙 안으로 통과"는 측정값이 사라져
후속이 없습니다 — 그 wafer 가 지금 하는 일(저수율 무라벨이 대조군에 섞임)은
`test_grouping`·`test_e2e` 가 고정합니다.

**`yield` DDL 계약 동결을 함께 넣었습니다.** Stage 4 에서 더미의 `yield` 는
`defect_type TEXT NOT NULL` 인데 로더만 NULL 허용이라 NULL 기록이 한동안 실패했습니다.
이제 `step_history` 와 같은 방식으로 `yield` 도 얼리고, 더미 테이블이 정확히 3개임을
고정해 `process_log` 부활을 막습니다. **`sensor_log` 는 얼리지 않습니다** —
`load_internal.py` 에 대응물이 없어(사내는 FDC HTTP) 비교 대상이 성립하지 않습니다.

**남은 것:** '스펙 이탈' 개념이 프로토타입에서 사라졌습니다. 사내 `step_history` 에는
파라미터가 없고 값 비교는 센서가 맡으므로 정합하지만, 사내 원천에 파라미터 이력이 따로
있다면 그때 다시 볼 축입니다.

### Stage 5.5 — 구 Stage 1 (실데이터)

**합격 기준을 착수 전에 정의합니다.** 최소:

1. `load_internal.validate()` 리포트에 fatal 없음
2. 적대적 케이스 5종(Stage A Task 4)의 판정이 실데이터에서도 유지
3. **과거에 원인이 확정된 사례 3~5건에서 Top-3 안에 정답이 들어오는지** ← 이것이 진짜 검증.
   사내 사례 확보가 전제입니다.
4. 임계(`COMMONALITY_PASS_MIN_SCORE`·`MIN_TARGET`·`SIBLING_MIN_SIMILARITY`·`YIELD_THRESHOLD`)를
   실분포로 조정

3번이 확보되지 않으면 Stage 5.5 는 "에러 없이 돈다" 수준의 스모크임을 문서에 정직하게 남깁니다.
**사내 사례 확보는 코드 작업이 아니라 조직 작업이므로 지금부터 병행 요청해 두는 편이 좋습니다.**

---

## 이 축이 다루지 않는 것

Stage 축은 **"실데이터에서 돌게 만든다"** 이고, `evidence_based_analysis_roadmap.md` 의 Phase
축은 **"믿을 만하게 만든다"** 입니다. 서로를 참조하지 않습니다.

**Stage 5 를 다 끝내도 결론 정확도를 측정할 수단은 없습니다.** Stage A Task 4 의 적대적
케이스가 Phase 축으로 넘어가는 첫 다리입니다.

Phase 축 소관(여기서 안 다룸): EvidenceBundle 게이트 강화(게이트가 여전히 문자열 매칭),
시간축(장비 이벤트·PM·recipe 이력), 사람 검토 폐루프, 다인성(독립 원인 2개가 타깃을 절반씩 설명).

---

## 관련 문서

| 문서 | 내용 |
|---|---|
| `2026-07-24-domain-corrections.md` | 사내 데이터로 뒤집힌 설계 결정 (A/B/C/D/E/F 절). Stage 표의 A-3·B-3·§E 라벨이 가리키는 곳 |
| `2026-07-25-dummy-first-stage-reorder.md` | Stage A 실행 플랜 (Task 0~6) |
| `superpowers/specs/2026-07-24-registry-commonality-realignment-design.md` | Stage 0 설계 (§12 에 구판 Stage 표) |
| `2026-07-18-status-node-review-and-redesign.md` | 대조군 3단계 규칙 (Stage 2 전제) |
| `evidence_based_analysis_roadmap.md` | Phase 축 — 신뢰도 로드맵 |
| `도메인지식-주입-틀-공백분석.md` | 왜 레지스트리가 1순위였는지 |
