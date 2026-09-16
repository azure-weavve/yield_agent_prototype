# thin-sample-verdict 구현 인계

## 사용자 요청에 따른 중단 (2026-09-16)

- 사용자가 중단을 요청하여 Sol의 R5 수정 작업을 중지했다. 현재 변경사항은 보존하며 완료로 판정하지 않는다.
- 마지막 독립 검증: 전체 612 passed. Astra가 R1~R4 해결을 확인했으나 R5가 남아 최종 판정은 수정 필요다.
- 남은 작업: graph/nodes.py의 ANALYZE_SYSTEM_PROMPT에서 표본 미달 후보 지목의 수락 조건과 표본 보충 조치 반영, llm/client.py의 generate_report 독스트링 분류 정정, 관련 프롬프트 테스트 추가, 필요한 테스트 실행, Astra 최종 재검증.
- 아래 이전 기록의 grep '출력 0건' 주장은 정정한다. not passes 술어는 남아 있지만 thin_sample 제외 조건으로 좁혀진 곳은 올바르다. 문자열 부재가 아니라 잘못된 포괄 분류의 부재를 확인해야 한다.
- 아래 '알려진 남은 제품 문제는 없다' 및 '필수 검증은 없다'는 R5 발견 이전 기록이다. 최신 상태는 이 중단 메모와 review.md의 R5를 따른다.
- M1~M15 모두 CAUGHT는 Sol 실행 보고이며 Astra가 변이를 독립 재실행한 것은 아니다.

- 실행 ID: `15397151-bd9f-4cfa-80a8-44bad6f8bb45`
- 구현 모델: `gpt-5.6-sol` (모델명은 실행 에이전트의 자기 보고이며 독립 로그 증명은 아님)
- 기준 커밋: `eeb2eb58c6eee71f8358726fbf7a8af7fe592c0a`
- 리뷰 기준: 위 기준 커밋 대비 아래 제품·테스트·문서 변경(커밋하지 않음)

## 변경 내용

- `graph/evidence.py`: `Bundle.thin_sample()`과 구조 플래그 `thin_sample`을 추가했다. 조건은 미통과·비센서·status `ok`·`target_pass < COMMONALITY_PASS_MIN_TARGET`·`score >= RESIDUAL_MIN_SCORE`다. `residuals()` 정의는 바꾸지 않았다.
- `graph/nodes.py`: `(2a) -> (2b) -> (2c) -> (2)` 순서로 `thin_sample` 판정을 추가했다. 정직한 지목 하한과 통과 후보 부재 하한을 유지하고, 표본 미달 후보를 증거 목록에 함께 싣는다. 약한 신호와 함께 있으면 `weak_signal`이 이기되 잔차 건수에는 표본 미달 후보를 세지 않는다.
- `graph/nodes.py`: 리포트 라벨을 `[근거]`/`[표본 미달]`/`[잔차]`로 나누고, 표본 미달 줄은 `(미통과: reject_reason)`으로 표시한다. `_drop_reason`과 `_no_candidate_action`도 새 상태를 안다.
- `llm/client.py`: mock 결론과 운영 system/user 프롬프트에 `thin_sample`의 뜻, 확정 금지, 타깃 표본 보충 조치를 추가했다. `passes: false`를 모두 잔차로 부르던 문장을 구조 플래그에 따라 구분하도록 고쳤다.
- `graph/state.py`, `README.md`: `finalize_status = thin_sample` 계약과 사용자 조치를 문서화했다.
- `tests/test_evidence.py`, `tests/test_graph_nodes.py`, `tests/test_mock_llm.py`: 계획의 T1~T10과 M1~M15를 잠그는 단언을 추가했다.

## 완료 기준별 근거

1. 전체 스위트: Astra R1~R4 수정 및 변이 원복 후 최종 `python -m pytest -q` -> `612 passed in 14.95s`.
2. T1~T10 및 리뷰 회귀: `python -m pytest -q tests/test_evidence.py tests/test_graph_nodes.py tests/test_mock_llm.py` -> `338 passed in 1.98s`; 이후 전체 스위트에 모두 포함되어 최종 612개 통과.
3. M1~M15: R1~R4 최종 수정본에서 임시 변이 실행기를 다시 만들고 각 변이를 한 번씩 주입했다. 각 실행은 `finally`에서 원본 바이트를 복원했으며 실행기를 삭제했다. 결과는 전부 `CAUGHT`:
   - M1~M4: `test_thin_sample_and_residuals_partition_nonpassing_candidates`
   - M5: `test_thin_sample_verdict_for_empty_and_named_submissions`
   - M6, M9, M10: `test_weak_signal_precedes_thin_sample_and_carries_both`
   - M7: `test_thin_sample_hallucination_rejects_before_limit_and_recovers_at_limit`
   - M8: `test_thin_sample_does_not_override_a_passing_candidate`
   - M11~M14: `test_thin_sample_report_label_drop_reason_and_step_back`
   - M15: `test_mock_report_and_operational_prompt_explain_thin_sample`
4. 문서: README 판정 표와 `graph/state.py` 주석에 `thin_sample`이 있다.
5. 옛 분류 문구 검사: `rg -n 'passes 가 false 인 항목은 판별선을 넘지 못한 잔차|not c\.get\("passes"' . --glob '!docs/tasks/thin-sample-verdict/plan.md'` -> 출력 0건.
6. 공백 오류 검사: `git diff --check` -> 오류 없음(Windows CRLF 안내만 출력).

## 계획과의 차이

- 계획의 M2 표에는 T5가 점수 하한 제거를 잡는다고 적혀 있으나 `(2b)`와 `(2c)`의 점수 조건상 간접 경로만으로는 독립 검출이 불명확하다. `test_thin_sample_and_residuals_partition_nonpassing_candidates`가 점수 하한을 직접 단언해 M2를 확실히 잡도록 했다. 제품 동작이나 요구사항은 바꾸지 않았다.
- 테스트 개수는 계획 작성 당시 저장소 기준 583개에 새 테스트만 더한 값이 아니다. 기존 미추적 `tests/test_workflow.py` 12개와 현재 작업 트리의 전체 수를 포함해 최종 612개다.

## Astra 리뷰 지적과 해결

- R1: 혼합 `weak_signal` 판정문에 절단 뒤 실제 표시된 표본 미달 건수 문장을 추가했다. 1건 표시와 0건 표시를 각각 단언한다.
- R2: 잔차 0건 문구를 특정 원인으로 단정하지 않는 "표시 상한에 밀려"로 고쳤다. mock의 잔차 판별도 `not passes and not thin_sample`로 좁혔다. 상한 1에서 표본 미달만 남는 경우와 센서만 남아 두 미통과 종류가 모두 0건인 경우를 검증한다.
- R3: 공용 `_unconfirmed_pick_note`가 실제 지목 후보를 보고 센서·대체·표본 미달·그 밖의 미통과 사유를 구분한다. `weak_signal`에서 표본 미달 후보를 지목한 경우와 `thin_sample`에서 표본 충분·낮은 점수 후보를 지목한 경우를 모두 단언한다.
- R4: `thin_sample` 판정문에 최고 점수 후보의 실제 `target_pass`와 하한을 함께 표시하며 `1건 < 2건` 재현을 잠갔다.

## 실행하지 못한 검증과 남은 문제

- 실행하지 못한 필수 검증은 없다.
- 알려진 남은 제품 문제는 없다. 별도 Astra 독립 리뷰와 최종 재검증은 메인 에이전트가 이어서 수행한다.

## 변경 범위와 기존 사용자 변경 구분

- 이번 작업 제품/문서 변경: `README.md`, `graph/evidence.py`, `graph/nodes.py`, `graph/state.py`, `llm/client.py`.
- 이번 작업 테스트 변경: `tests/test_evidence.py`, `tests/test_graph_nodes.py`, `tests/test_mock_llm.py`.
- 이번 작업 산출물: `docs/tasks/thin-sample-verdict/handoff.md`.
- 기존 사용자 변경으로 보존: 수정된 `.gitignore`; 미추적 `AGENTS.md`, `CLAUDE.md`, `workflow.py`, `workflow-config.json`, `tests/test_workflow.py`, 기존 `docs/` 및 workflow 관련 파일 전부. 이 작업은 해당 파일을 수정·삭제하지 않았다.
- 커밋, 브랜치 생성, push, deploy, workflow claim/finish는 수행하지 않았다.


## R5 — Claude 직접 처리 (2026-09-16)

사용자가 **"인계하지 말고 직접 진행해"** 로 역할을 바꿔(CLAUDE.md 의 역할 분담 예외)
설계자가 R5 를 직접 고쳤다. 2차 인계(run `ba89bdc4`)는 `abandon` 으로 표시했다 -
⚠️ 그 명령은 앱 큐의 메시지를 취소하지 못하므로, 앱 대화가 이미 집었다면 거기서
중단해야 한다.

### 고친 것

1. `graph/nodes.py::ANALYZE_SYSTEM_PROMPT` - "잔차마저 없는 상태에서 지목하면
   반려되고" 를 뺐다. 잔차가 없어도 **표본 미달 후보**가 있고 실제로 받은 이름을
   지목하면 `(2c)` 가 한계 전에 받는다는 사실과, **상한이 남는 한** 그 후보를 근거로
   싣는다는 한정, 타깃 표본을 채워 재확인하라는 조치를 적었다. 반려 조건은 **연언**
   ("잔차도 표본 미달 후보도 없는 상태에서")으로 적어 한쪽만 옮겨 반대 방향으로
   거짓이 되는 것을 막았다. 뒤따르는 `(2b)` 한정절("다만 …")은 그대로 뒀다.
2. `llm/client.py::LLMClient.generate_report` 독스트링(추상 계약) - `passes: false`
   항목을 전부 잔차로 부르던 분류를 고쳤다. 판정 목록에 `thin_sample` 을 더하고,
   두 종류를 가르는 것은 **구조 플래그 `thin_sample`** 이며 `reject_reason` 파싱으로
   추측하지 말 것과 두 조치의 차이를 적었다.
3. `tests/test_graph_nodes.py::test_analyze_prompt_tells_the_llm_the_two_outcomes_of_naming_a_weak_candidate`
   - **이 단언 자체가 옛(거짓이 된) 계약을 붙잡고 있었다.** 꼬리 절을 새 계약으로
   고치고 docstring 에 "꼬리 절의 항 수를 세라" 는 이유를 남겼다.

### 새 단언

- `tests/test_mock_llm.py::test_analyze_prompt_knows_a_thin_sample_pick_is_received_not_rejected`
  - 옛 절의 **부재**까지 본다(덧붙이고 안 지우면 프롬프트가 자기모순인 채 초록이 된다).
- `tests/test_mock_llm.py::test_report_contract_docstring_splits_thin_sample_from_residual`
  - 줄바꿈은 계약이 아니므로 공백을 접어 문장으로 본다.

### 검증

- `python -m pytest -q` -> **614 passed** (직전 612 + 신규 2). 설계자가 직접 실행.
- 훼손 실험 4건 전부 **CAUGHT**(복원은 `finally`, 복원 뒤 재실행으로 확인):
  MR5-1 프롬프트 전체 되돌림 · MR5-2 반려 절만 되돌림 · MR5-3 독스트링 판정 목록
  되돌림 · MR5-4 독스트링 판별 규칙 문장 훼손.
- 옛 술어 grep: 제품·테스트 코드에 남은 자리 없음. `not c.get("passes", True)` 는
  `and not c.get("thin_sample")` 로 좁혀진 두 자리와, 미통과 부재를 단언하는
  테스트 두 자리만 남는다(둘 다 올바른 용법).

### 남은 한계

- **독립 검증(Astra)이 없다.** 이 R5 수정은 설계자가 직접 쓰고 직접 검증했다.
  1차 실행의 R1~R4 는 Astra 재검증을 받았으나 R5 수정본은 못 받았다.
- 과거 작업 문서(`.superpowers/2026-09-09-잔차-소각-종료/*`,
  `docs/superpowers/plans|specs/2026-09-09-*`)가 옛 프롬프트 문장을 인용하고 있다.
  완료된 작업의 날짜 있는 기록이라 고쳐 쓰지 않았다.
- 커밋·브랜치·푸시는 하지 않았다. 워킹 트리 미커밋 상태 그대로다.
