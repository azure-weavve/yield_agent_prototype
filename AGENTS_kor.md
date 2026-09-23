# Claude에서 인계받은 작업

## 개발 역할 분담

- Claude 메인: 설계, 구현계획, Claude/Codex 작업 분할
- Claude Sonnet 5: `owner: claude` 범위 구현 및 수정
- Claude Opus 5.5 (`high effort`): Claude 담당 구현 리뷰
- Codex GPT-6 Terra: `owner: codex` 범위 구현, 테스트, 수정
- Codex GPT-6 Sol (`high effort`): Codex 담당 구현 리뷰
- Codex GPT-6 Astra (`low effort`): Claude와 Codex 전체 변경사항의 최종 통합 리뷰
- 사용자가 명시적으로 역할을 변경하면 해당 지시를 우선한다.

이 문서는 모델을 자동 전환하지 않는다.
현재 작업의 출처와 역할에 따라 아래 규칙을 적용한다.
지정 모델이나 effort를 사용할 수 없으면 임의 대체하지 않고 blocked로 보고한다.

## 앱 대화로 인계된 작업

`workflow.py`가 전달한 요청은 이 앱 대화의 메인 Codex가 관리한다.
요청 문서에 지정된 claim 명령으로 실행 ID의 유효성을 확인한 뒤 시작한다.
일시적인 상태 잠금 충돌은 잠시 후 재시도한다.
활성 실행 ID가 아니거나 이미 수락된 요청이면 구현을 시작하지 않는다.

인계된 작업에서는 다음 모델 분담을 사용한다.

1. `gpt-6-terra`가 Codex 담당 범위를 구현·테스트·수정한다.
2. 별도 컨텍스트의 `gpt-6-sol`이 `high effort`로 Codex 담당 구현을 리뷰한다.
3. Sol 지적이 있으면 Terra가 수정하고 Sol이 수정본을 다시 리뷰한다.
4. Codex 담당 구현 리뷰가 끝난 뒤 별도 컨텍스트의 `gpt-6-astra`가 `low effort`로 이번 작업의 전체 변경사항을 최종 리뷰한다.
5. Astra는 Claude가 이미 구현하고 Opus가 리뷰한 범위까지 포함해 전체 통합 상태를 확인한다.

- 이 모델 지정과 서브에이전트 사용을 명시적으로 허용한다.
- 자식 에이전트는 추가 위임 없이 맡은 역할을 수행한다.
- 메인은 인계·변경 범위·완료 기준·리뷰 루프를 관리하며 사용자에게 진행을 알린다.
- 리뷰 에이전트는 대상 제품 코드를 직접 수정하지 않는다.
- 모델명과 effort는 실제 사용에 대한 보고이며 로그로 독립 증명된 값이라고 표현하지 않는다.

## 인계 범위 확인

`docs/tasks/<작업명>/plan.md`의 각 구현 단계에 표시된 owner를 기준으로 한다.

- `owner: claude`: 이미 Claude 쪽에서 구현·리뷰된 범위다. Codex가 중복 구현하지 않는다.
- `owner: codex`: Codex가 구현해야 하는 범위다.
- owner가 없거나 서로 충돌하면 임의로 범위를 정하지 않고 `needs_design_revision`으로 돌린다.

Claude 담당 변경사항도 최종 Astra 리뷰 대상에는 포함한다.
다만 Astra가 Claude 담당 범위의 제품 코드 수정을 요구하면 Codex가 임의로 수정하지 않는다.
해당 결함의 위치, 발생 조건, 영향, 근거를 `review.md`에 남기고 `needs_design_revision`으로 종료해 Claude 재작업으로 돌린다.

Astra가 Codex 담당 범위의 결함을 찾으면 다음 순서를 따른다.

`Terra 수정 → Sol(high) 재리뷰 → Astra(low) 전체 재리뷰`

## 상태 및 실행 규칙

`handoff.md`와 `review.md`를 이번 실행에 맞게 작성한 뒤 요청 문서의 finish 명령으로
최종 상태를 기록한다. 문서 확인과 필수 검증이 끝나기 전 complete로 기록하지 않는다.
설계 변경 또는 Claude 담당 범위 재작업이 필요하면 `needs_design_revision`,
검증이나 실행 불가는 `blocked`로 기록한다.
실행 ID가 일치하지 않으면 다른 작업 상태를 덮어쓰지 않는다.
상태 파일을 직접 편집하지 않고 `workflow.py`의 claim/finish 명령을 사용한다.
Claude나 `workflow.py run`을 재귀 호출하지 않는다.
지침 및 인계 스크립트 자체 수정에는 별도 기능 계획을 요구하지 않는다.

## 공통 규칙

- `docs/tasks/<작업명>/plan.md`를 작업 기준으로 사용한다.
- 저장소 지침과 기존 변경사항을 먼저 확인한다.
- 기존 사용자 변경사항과 Claude가 완료한 변경사항을 보존한다.
- 계획의 주장도 실제 코드와 대조한다.
- 요구사항을 유지하는 세부 구현 선택은 자율적으로 진행한다.
- 요구사항, 공개 인터페이스 또는 주요 데이터 구조의 변경이 필요하면 근거와 대안을 기록하고 Claude의 설계 재검토로 넘긴다.
- 실행하지 않은 검증을 통과했다고 기록하지 않는다.
- 서로 다른 리뷰 단계의 목적을 섞지 않는다. Sol은 Codex 구현 범위를 깊게 보고, Astra는 전체 통합 상태를 마지막에 확인한다.

## Codex 구현 작업 — GPT-6 Terra

1. plan.md와 실제 코드의 일치 여부를 확인한다.
2. `owner: codex`로 지정된 범위만 구현한다.
3. 필요한 테스트를 실행한다.
4. `docs/tasks/<작업명>/handoff.md`를 작성하거나 갱신한다.

handoff.md에 포함할 내용:

- Codex가 변경한 내용
- Claude에서 이미 존재하던 이번 작업 관련 변경과의 구분
- 완료 기준별 충족 여부와 근거
- 실행한 검증 명령과 결과
- 실행하지 못한 검증과 이유
- 계획과 달라진 사항과 그 이유
- 남은 문제
- 리뷰 기준 커밋과 대상 변경 범위
- 관련 미커밋 변경 및 기존 사용자 변경과의 구분

Sol 또는 Astra의 Codex 범위 지적을 받으면 타당성을 확인하고 수정한다.
지적에 동의하지 않으면 코드나 검증 근거를 기록한다.
수정 후 관련 검증과 handoff.md를 갱신한다.

## Codex 범위 리뷰 — GPT-6 Sol (high effort)

Terra 구현과 분리된 컨텍스트에서 `high effort`로 리뷰한다.
제품 코드를 직접 수정하지 않고 코드 검사와 필요한 검증을 수행한다.

검토 범위는 기본적으로 `owner: codex` 변경사항이다.
plan.md, 실제 변경사항, 관련 호출부와 데이터 흐름을 대조하고 handoff.md의 주장을 독립적으로 확인한다.

우선 검토 대상:

- Codex 담당 요구사항 누락
- 실제 동작 오류와 회귀
- 데이터 무결성 및 예외 처리
- 인터페이스 계약 위반
- 중요한 테스트 공백

지적이 있으면 Terra가 수정한다.
수정 후에는 Sol이 수정본을 다시 리뷰한다.
완료를 막는 Sol 지적이 남아 있는 동안 Astra 최종 리뷰로 넘어가지 않는다.

Sol 리뷰 결과는 `docs/tasks/<작업명>/review.md`의
`Codex scoped review — Sol (high effort)` 섹션에 기록한다.

## 전체 최종 리뷰 — GPT-6 Astra (low effort)

Sol 리뷰가 끝난 최종 수정본을 대상으로, 구현 컨텍스트와 분리된 새 컨텍스트에서
`low effort`로 전체 리뷰한다.

Astra의 범위는 이번 작업의 전체 변경사항이다.

- Claude Sonnet 5가 구현하고 Opus 5가 리뷰한 변경
- Codex Terra가 구현하고 Sol이 리뷰한 변경
- 두 범위 사이의 인터페이스, 호출 관계, 데이터 흐름
- plan.md의 전체 완료 기준

Astra는 제품 코드를 직접 수정하지 않는다.
세부 구현을 다시 처음부터 깊게 재리뷰하는 것보다, 전체 작업의 누락·통합 문제·회귀·계약 불일치를 우선 확인한다.

우선 검토 대상:

- Claude/Codex 경계에서의 통합 오류
- 전체 요구사항 누락
- 범위 간 인터페이스 또는 데이터 구조 불일치
- 최종 동작 회귀
- 완료 기준과 실제 결과의 불일치
- 각 로컬 리뷰에서 놓친 명백한 결함

Astra 결과는 `docs/tasks/<작업명>/review.md`의
`Integrated final review — Astra (low effort)` 섹션에 기록한다.

review.md에는 최종적으로 다음이 포함되어야 한다.

- 검토한 코드 버전과 전체 변경 범위
- Sol의 Codex 범위 리뷰 결과
- Astra의 전체 통합 리뷰 결과
- 결함별 심각도, 파일·위치, 발생 조건, 영향, 근거
- 확인된 결함과 추가 확인이 필요한 의심 사항의 구분
- 완료 기준별 검증 결과
- 검증하지 못한 사항과 이유
- 최종 판정: 통과 / 수정 필요 / 검증 미완료

## 완료 기준

- 계획의 완료 기준이 충족되어야 한다.
- Claude 담당 범위가 존재하면 Claude 측 구현과 Opus 5 (`high effort`) 리뷰가 끝난 상태여야 한다.
- Codex 담당 범위가 존재하면 Terra 구현과 Sol (`high effort`) 리뷰가 끝나야 한다.
- 필요한 검증이 통과해야 한다.
- 완료를 막는 리뷰 지적이 해결되어야 한다.
- 최종 수정본 전체에 대한 Astra (`low effort`) 재검증이 완료되어야 한다.
- 필수 검증을 실행하지 못한 경우 검증 미완료로 표시한다.


# Agent Workflow (코덱스 단독 작업 시)

You are the primary architect and coordinator.

## Primary model responsibilities

Use the primary agent for:
- requirements analysis
- architecture
- design decisions
- implementation planning
- reviewing implementation
- debugging strategy
- deciding the next task

## Implementation delegation

When the task requires substantial code implementation or modification:

1. Do not implement the code yourself unless the change is trivial.
2. Delegate the implementation to the coding subagent.
3. Give the coding agent:
   - the implementation plan
   - relevant files
   - constraints
   - acceptance criteria
4. Let the coding agent implement and test the change.
5. Review the returned implementation.
6. If corrections are needed, delegate them again.
7. Continue the main task after implementation succeeds.

## Delegate when

Delegate to the coding agent for:
- creating new modules
- implementing functions/classes
- modifying multiple files
- refactoring
- writing tests
- fixing implementation bugs

Do not delegate for:
- architecture discussion
- planning
- requirement clarification
- small one-line changes
- documentation-only changes
