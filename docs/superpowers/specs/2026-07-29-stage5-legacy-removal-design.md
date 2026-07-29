# Stage 5 — `process_log`·레거시 도구 삭제 (단일 스키마 완성) 설계

작성: 2026-07-29 · 브랜치 `stage-5-legacy-removal`
Stage 순서의 단일 출처: `docs/stages.md` (이 문서는 그 Stage 5 항목의 설계)

---

## 왜 지금 지우는가

**실데이터에 `process_log` 테이블이 없습니다.** `data/load_internal.py` 는 `yield` 와
`step_history` 만 만듭니다(`DDL`). `process_log` 에 묶인 도구·함수·더미 테이블은 사내
데이터에서는 **호출 즉시 빈 결과이거나 SQL 오류**입니다. Stage 4 에서 노출만 껐고
(`LEGACY_TOOLS_ENABLED` 기본 OFF), 삭제는 여기로 미뤄 뒀습니다.

파라미터·스펙 개념은 Stage 3 에서 **센서(`sensor_log`)가 가져갔습니다.** 사내
`step_history` 는 (wafer, step, eqp, ch, ppid, timestamp) 뿐이라 파라미터가 없고,
값 비교는 `compare_sensor_distribution` 이 합니다. 따라서 `process_log` 는 대체된 것이지
잘려 나가는 것이 아닙니다.

## 대체 매핑 확인 (`docs/stages.md:142-146` 이 요구한 삭제 전제)

**결론: 기능 유실 없음.** 코드로 확인했습니다.

| 지금 레거시가 하는 일 | 대체 | 확인 위치 |
|---|---|---|
| `validate_data_completeness` → `missing_yield_rows` | `normalize_target` 의 `unknown_wafers` 조기 출구 | `tools/grouping.py` |
| → `missing_log_steps` | commonality 의 `missing_history` · `no_paired_stratum` | `tools/commonality.py:221,284` |
| → `duplicate_logs` | `load_internal.validate()` 의 중복 검사 (적재 시점) | `data/load_internal.py:306` |
| `find_counterexamples` | commonality 2×2 의 `control_pass` (= 원인 거쳤는데 정상) | `domain/engine.py:4-5` 가 이미 명시 |
| `compare_parameter_distribution` | `compare_sensor_distribution` (효과크기 랭킹·top-K) | `tools/sensor_compare.py` |
| `compare_process_logs` | 레지스트리 가설 도구(`hyp_*`) + commonality | `domain/engine.py` |

`compare_process_logs` 와 `compare_parameter_distribution` 은 **이미 죽은 코드**입니다 —
tool 로 등록돼 있지 않고 테스트만 호출합니다.

---

## 삭제 목록

**코드**

- `tools/yield_tools.py` — `get_process_log` · `compare_process_logs` ·
  `validate_data_completeness` · `compare_parameter_distribution` · `find_counterexamples`.
  381줄 → 약 100줄. 남는 것은 `find_low_yield_lots` · `get_wafer` · `get_wafers` ·
  `find_control_candidates` 4개다. `statistics` import 도 쓰는 곳이 없어져 함께 지운다.
- `tools/agent_tools.py` — 레거시 tool 래퍼 3개와 `_LEGACY_TOOLS` 목록. `ANALYSIS_TOOLS` 는
  `_BASE_TOOLS + _HYPOTHESIS_TOOLS` 로 단순해진다.
- `config.py` — `LEGACY_TOOLS_ENABLED` 상수와 그 위의 설명 주석.
- `data/generate_dummy.py` — `PROCESS_FLOW` · `_make_process_logs` · 챔버 상수 3개
  (`DECOY_CHAMBER`·`REAL_CHAMBER`·`CONTROL_ETCH_CHAMBER`) · `process_log` DDL 과 INSERT ·
  `_write_sqlite` 의 `logs` 인자.

**테스트** (지우는 것이 정상이다 — 지워지는 코드를 검증하던 테스트다)

- `tests/test_yield_tools.py` — 26개 중 21개. 남는 5개는 `get_wafers` ·
  `find_control_candidates` 3종 · `find_low_yield_lots` 런타임 임계.
- `tests/test_dummy_data.py` — 7개(아래 "불변식 재작성" 참조).
- `tests/test_agent_tools.py` — 4개 (`get_process_log`·`validate_data_completeness` 실행,
  플래그 ON/OFF 2종). `test_tool_names` 는 이미 정확한 집합을 단언하므로 그대로 둔다.

**문서** — '스펙 이탈'(`spec_low`/`spec_high`/`param_value`/`in_spec`) 서술 정리.
`README.md` · `docs/stages.md`(Stage 5 완료 표기) · `docs/internal-data-integration.md` ·
`docs/사내-데이터-변환시-할일.md` · `docs/deferred-internal-integration.md`.

---

## 불변식 재작성 — 이 Stage 의 유일한 실질적 판단

세 테스트가 더미의 "심어둔 이상은 심은 곳에만 있다" 를 **`process_log` 의 스펙 이탈로만**
표현하고 있습니다. 그중 `test_only_planted_pattern_wafers_have_anomalies` 는 Stage 4 가
라벨을 없애면서 그 자리에 넣은 대체 단언입니다.

**그대로 옮길 수 없습니다.** `_make_step_history`(`data/generate_dummy.py:383-391`)는
**과거 패턴 wafer(`W2410_cen1` 등)에 아무 신호도 심지 않습니다** — `else` 분기로 랜덤
ETCH 챔버를 받습니다. 데모가 타깃 7장 중 "불량군 **3장** 전용"이라고 말하는 이유가 이것입니다.
저 불변식이 다루는 20장 중 step_history 에 신호가 있는 것은 3장뿐입니다.

과거 wafer 에도 신호를 심으면 `target_pass` 가 3→7 로 바뀌어 **README 데모 숫자와 여러
테스트가 깨집니다.** 그렇게 하지 않습니다.

**결정: 손실을 받아들이고, step_history 로 표현 가능한 범위로 좁혀 재작성한다.**

| 지우는 테스트 | 후속 |
|---|---|
| `test_process_log_table_exists_with_4_rows_per_wafer` | `test_every_wafer_has_the_full_step_path_except_the_planted_gap` (아래 신규 3) |
| `test_pattern_wafer_has_single_anomaly_at_its_step` | 아래 신규 1 |
| `test_anomaly_equipment_is_always_the_shared_minus9` | 아래 신규 1 |
| `test_only_planted_pattern_wafers_have_anomalies` | 아래 신규 1 (대상이 3장으로 좁아진다) |
| `test_process_log_has_eq_chamber` | `test_step_history_planted_eqp_ch_and_ppid_separation` (기존) |
| `test_control_shares_equipment_not_chamber` | 아래 신규 2 |
| `test_hole_case_unlabeled_low_yield_wafer_passed_etch9_in_spec` | 없음 — 아래 참조 |

**신규 1 — 심은 챔버는 심은 wafer 에만 있다 (전수 SQL).**
`GROUP_WAFERS` 3장만 Etch 에서 `ETCH9_B` 를 거치고, **더미 전체에서 그 밖의 어떤 wafer 도
거치지 않는다.** 기존 `test_step_history_planted_eqp_ch_and_ppid_separation` 은 commonality
결과만 보므로 이 전수 성질을 보지 않는다 — 새로 필요하다.

단언이 성립하는 근거를 생성기에서 확인했다: 챔버 `B` 를 쓰는 다른 케이스들은 전부 **설비가
다르다** — 적대적 lot 은 `ETCH1`·`ETCH2`·`ETCH3`, 분할 lot 은 `ETCH5`(`_make_split_lot_steps`).
대조군은 같은 `ETCH9` 지만 챔버가 `"1"`~`"8"` 이고, 나머지 wafer 는 `else` 분기로 챔버 `"A"` 를
받는다. 따라서 `(eqp_id='ETCH9' AND ch_id='B')` 인 wafer 집합은 정확히 `GROUP_WAFERS` 다.

**신규 3 — 모든 wafer 가 전 공정 경로를 갖는다 (결측은 심어둔 1장뿐).**

> **⚠️ 2026-07-29 리뷰 반영.** 처음에는 `test_process_log_table_exists_with_4_rows_per_wafer`
> 의 후속을 "없음(테이블이 사라진다)" 으로 판정했는데, 이는 범주 오류였다. 그 테스트가
> 지키던 성질은 *테이블의 존재*가 아니라 **경로 완전성**이고, 그것은 `step_history` 로
> 그대로 표현된다. 이력이 조용히 빠지면 commonality 의 분모가 줄어 점수가 부풀지만 다른
> 테스트는 초록이다 — 실데이터 쪽은 `load_internal.validate()` 검사 #4 가 같은 것을 막는데
> **더미에는 가드가 없어진다.** `test_adversarial_dummy.py` 는 `ADV_MISSING_WAFER` 가
> `missing_history` 에 든다는 것만 보고 "그 밖에 결측이 없다" 는 반대 방향을 보지 않는다.

**신규 2 — 대조군은 같은 설비, 다른 챔버.**
`CONTROL_WAFERS` 는 Etch 에서 `eqp_id == "ETCH9"` 이되 `ch_id != "B"` 다. 설비 레벨 롤업이
눌리고 챔버 레벨만 분리되는 것이 이 시나리오의 핵심이고, 그것은 step_history 로 그대로
표현된다.

**구멍 케이스 (가) `W2406_07` 은 후속을 만들지 않는다.**
원래 성질은 "이상 장비를 거쳤지만 측정값은 스펙 내" 였는데, 측정값이 없어지면 남는 것이
없다. step_history 에서 이 wafer 는 이미 랜덤 ETCH 챔버를 받는 평범한 wafer 다. 이 wafer 가
지금 실제로 하는 일 — **저수율 무라벨이 대조군에 섞이는 것** — 은 `tests/test_grouping.py`
(`test_control_reports_yield_distribution_instead_of_filtering`)와 `tests/test_e2e.py`
가 이미 고정하고 있다. 생성기 주석에서 스펙 관련 서술만 걷어낸다.

---

## 계약 동결 보강 (`docs/stages.md:148-151` 이 Stage 5 로 지정)

`tests/test_schema_contract.py` 는 지금 `step_history` 만 얼립니다. Stage 4 에서 더미의
`yield` 는 `defect_type TEXT NOT NULL` 인데 로더만 nullable 이라 NULL 기록이 한동안 실패한
일이 실제로 있었습니다. **`yield` 테이블도 같은 방식으로 얼립니다** — 더미 DDL 과
`load_internal.DDL` 의 `yield` 컬럼 집합이 갈리면 실패하게 합니다.

`sensor_log` 는 얼리지 않습니다. `load_internal.py` 에 대응물이 없어(사내는 FDC HTTP)
비교 대상이 성립하지 않습니다 — 이 사실을 문서에 남기고 미룹니다.

---

## Task 순서 (매 커밋 green 유지)

1. **레거시 노출 제거** — `agent_tools` 래퍼 3개 · `config.LEGACY_TOOLS_ENABLED` ·
   `test_agent_tools` 4개. 이 시점에 LLM 이 볼 수 있는 도구 집합이 확정된다.
2. **`yield_tools` 5함수 삭제** — 해당 테스트 21개 함께. 1번이 끝나야 호출부가 없다.
3. **더미 `process_log` 삭제 + 불변식 재작성** — 생성기와 `test_dummy_data`.
   DB 를 재생성하므로 여기서 전체 스위트가 한 번 크게 움직인다.
4. **`yield` DDL 계약 동결 추가.**
5. **문서 정리** — 스펙 이탈 서술 · `docs/stages.md` Stage 5 완료 표기.

**순서 근거:** 도구 노출 → 함수 → 데이터 → 계약 → 문서. 반대로 가면(데이터 먼저) 중간
커밋에서 살아 있는 함수가 없는 테이블을 조회해 스위트가 빨개진다.

## 성공 기준

1. 매 Task 끝에 전체 스위트 green. **테스트 수는 줄어드는 것이 정상**이다(166 → 약 138).
   각 Task 의 예상 증감과 실제가 다르면 이유를 확인하고 진행한다.
2. `python main.py` 출력이 `README.md` 데모 블록과 일치 — **데모 경로는 한 글자도 바뀌지
   않는다.** `process_log` 는 현재 분석 경로가 쓰지 않으므로 이것이 성립해야 한다.
3. 더미 DB 재생성 후에도 `step_history`·`sensor_log`·`yield` 의 기존 값이 불변
   (기존 wafer·난수열을 건드리지 않는다).
4. 저장소 전체에서 `process_log`·`spec_low`·`spec_high`·`param_value` 검색 결과가
   **과거 문서(plans/specs)와 사내 스키마 설명에만** 남는다.
