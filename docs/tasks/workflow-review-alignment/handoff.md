# workflow.py 리뷰 절차 정합성 수정

## 요청과 범위

- 사용자 직접 요청: `AGENTS.md`에 맞춰 `workflow.py` 수정.
- 앱 인계 실행이 아닌 Codex 직접 작업이다. 실행 ID 및 실제 claim/finish는 해당하지 않는다.
- `AGENTS.md`에서 workflow/instruction 변경은 별도 기능 계획을 요구하지 않는다.
- 소유 범위: `owner: codex` — `workflow.py`, `tests/test_workflow.py`, `docs/codex-handoff.md`, 이 작업의 handoff/review 문서.
- Claude 소유 구현 변경은 없다. 제품 분석 로직은 변경하지 않는다.
- 기준 커밋: `2324f280bb8c1a5bef291c216cf896df5f87e26a`.
- 착수 시 작업 트리는 깨끗했고 활성 인계 마커는 없었다. 기존 실행 상태·로그는 수정하지 않는다.

## 적용 기준과 변경 내용

- `AGENTS.md`의 App-Handoff Tasks / Model flow에 명시된 `gpt-5.6-terra` 구현 → 별도 `gpt-5.6-sol` high 범위 리뷰 → 별도 `gpt-6-astra` low 통합 리뷰를 따른다.
- 상단 Roles의 GPT-6 표기와 App-Handoff Tasks의 GPT-5.6 표기는 서로 다르다. 이번에는 workflow 요청에 직접 적용되는 후자를 기준으로 하며 `AGENTS.md` 자체는 변경하지 않는다.
- 생성 요청에 소유 범위, Claude 범위 결함의 설계 재검토 반환, Codex 수정·리뷰 반복, 리뷰 문서 요건을 반영한다.
- 기존 `review_model`은 Astra 통합 리뷰 의미를 보존한다. Sol 범위 리뷰 모델·effort와 Astra effort 보고를 추가한다.
- `complete`는 세 모델과 두 effort의 올바른 보고 및 기존 결과 문서 갱신 검사를 요구한다.
- 새 필드가 없는 기존 비완료 보고와 과거 상태 조회는 지원한다. 누락된 리뷰를 완료한 것으로 간주하지 않는다.
- 인계 안내 문서를 동일한 절차로 갱신한다.

## 수용 기준 및 검증

- 생성 요청: Terra 구현, 별도 Sol high 범위 리뷰, 별도 Astra low 전체 리뷰, 수정 시 재검토 순서와 소유 범위별 반환 규칙 반영.
- 완료 보고: 세 모델과 두 effort가 일치해야 완료 가능. 보고 누락·잘못된 effort 시 실행은 running 상태와 활성 마커를 유지한다.
- 호환성: 과거 두 모델 필드만 있는 `blocked`/`needs_design_revision` 보고는 누락 필드를 빈 값으로 정규화한다. 과거 형식의 `complete`는 거부한다.
- CLI: 세 가지 새 옵션을 finish 파서와 결과 전달에 연결했다. 생성된 finish 명령은 PowerShell에서 실행할 수 있는 한 줄이다.
- 기존 큐 전송·실행 ID 상관 검사·중복 claim 방지·대기·완료와 전송 반환 간 경합 회귀 테스트를 유지했다.
- Terra 실행 보고: `pytest -q tests/test_workflow.py` → **27 passed**.
- 메인 독립 실행: `python -m pytest -q` → **691 passed in 16.18s**.
- 메인 실행: `git diff --check` → 공백 오류 없음(CRLF 변환 안내만 있음).
- 메인 실행: `python workflow.py finish --help` → 새 옵션 표시 확인, 종료 코드 0.
- 별도 Sol (`gpt-5.6-sol`, high) 범위 리뷰: **pass**, 지적 사항 없음. 독립 `python -m pytest -q tests/test_workflow.py` → **27 passed in 0.90s**.
- 별도 Astra (`gpt-6-astra`, low) 최종 통합 리뷰: **pass**, 확인되거나 의심되는 결함 없음. 요청 → CLI → 상태 저장 계약, 문서 정합성, 완료 검사와 기존 상태 호환성 확인.
- 최종 검토 내역은 `review.md`에 기록했다. 알려진 남은 문제나 미실행 필수 자동 검증은 없다.

## 한계

- 모델·effort는 요청한 실행 설정 및 에이전트 자기 보고이며 독립 서버 로그 증명이 아니다.
- finish는 보고 값과 문서 갱신을 검사한다. 실제 리뷰 순서·내용 및 수용 기준 충족은 메인이 근거를 확인해야 한다.
- 실제 앱 큐 전송이나 모델 가용성 탐지는 이번 변경의 자동 테스트 대상이 아니다. 테스트는 격리된 임시 저장소와 모의 큐 호출을 사용한다.
