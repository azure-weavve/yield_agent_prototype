# 사내 연동 시 처리할 미룸 항목

2026-07-11 리뷰(Claude + codex 교차 검증)에서 확인했으나, 실행 경로가 사내 연동
(`LLM_MODE=openai` / `EDS_MODE=http`) 전에는 없어 의도적으로 미룬 항목들.
**사내 연동 착수 시 이 문서를 작업 목록으로 사용한다.** 1~2번은 연동 첫날 필수.

## 1. tool 호출 오류를 복구 가능한 ToolMessage 로 변환 (필수)

- 위치: `graph/nodes.py` `tools_node` — `TOOLS_BY_NAME[call["name"]]` 직접 인덱싱, `.invoke()` 무방비
- 문제: 실제 LLM 이 없는 tool 이름을 내거나 인자 스키마를 벗어나면 KeyError/ValidationError 로 그래프 전체가 예외 종료
- 처방: 예외를 잡아 오류 내용을 ToolMessage 로 반환 → LLM 이 다음 analyze 에서 스스로 교정 (tool-calling 루프 표준 패턴)

## 2. finalize confidence 비숫자 방어 (필수)

- 위치: `graph/nodes.py` `_finalize_gate` — `float(args.get("confidence", 0.0))`
- 문제: LLM 이 `"high"` 같은 비숫자를 주면 ValueError 크래시
- 처방: 변환 실패 시 0.0 취급 + 반려 메시지에 "confidence 는 0~1 숫자" 명시

## 3. 게이트에 결정론적 증거 조건 추가 (codex 3번, 설계 개선)

- 위치: `graph/nodes.py` `_finalize_gate`
- 문제: 승인 기준이 LLM 자기 신고 confidence 뿐 — MAX_LOOPS 도달 시엔 근거 품질 무관 승인
- 처방: findings 에서 결정론적 증거(공정 로그 in_spec=False 행 존재, 유사 사례 수 등)를 게이트 조건에 포함. "수치는 결정론, LLM 은 판단" 철학과 일치
- 참고: MAX_LOOPS 강제 종료 시 "승인"이 아니라 "미확정(한계 도달)"으로 구분 기록하는 것도 함께 검토

## 4. TLS 검증 기본값을 켜짐으로 (codex 4번)

- 위치: `config.py` `EDS_HTTP_VERIFY = False`
- 문제: http 모드를 켜는 것만으로 인증서 검증 없이 사내 데이터 전송
- 처방: 사내 루트 인증서(.pem) 확보 → `EDS_HTTP_VERIFY = "인증서경로"` 를 기본값으로, 우회는 개발 환경에서만 명시적으로

## 5. finalize 승인 후 같은 메시지의 후속 tool 실행 중단 (codex 6번)

- 위치: `graph/nodes.py` `tools_node` 의 for 루프
- 문제: 한 AIMessage 에 finalize + 다른 tool 이 오면 승인 후에도 나머지가 실행되고, finalize 2개면 뒤가 앞을 덮어씀
- 처방: 승인 즉시 루프 중단(잔여 call 은 "종료로 생략" ToolMessage 처리) 또는 finalize 는 단독 호출만 허용하도록 사전 검증

## 6. HTTP EDS 응답 스키마 실측 검증

- 위치: `tools/eds_search.py` `HttpEDSSearcher` — 필드명(`wafer_id`/`score`)이 추정값
- 처방: 사내 `/search` 실제 응답으로 매핑 확정 + 오류 응답(4xx/5xx, 타임아웃) 처리 방침 결정

## 7. 실패 경로 테스트 확충 (codex 7번)

- 현재 테스트는 mock 정상 경로 중심. 연동 시 추가할 것: 알 수 없는 tool 이름 복구(1번),
  비숫자 confidence(2번), tool 실행 실패, MAX_LOOPS 강제 종료 시 리포트 내용, HTTP 오류 응답
- 실제 LLM 을 붙인 통합 테스트(별도 마커로 분리) 1본 이상

## 8. 기타 경미 (여유 있을 때)

- `config.py` 상수의 환경변수 오버라이드 (`os.getenv`) — 코드 수정 없는 모드 전환
- `tools/yield_tools.py` `find_low_yield_lots` 기본 인자가 import 시점 바인딩 — 런타임 threshold 변경이 기본값에 반영 안 됨
- `graph/nodes.py` 모듈 레벨 `_llm = get_llm()` — import 시점에 구현 고정, 지연 획득으로 전환하면 테스트·모드 전환 유연
- `llm/client.py` 리포트 결론 fallback "원인 미확정"이 원인(수율 이상 lot 없음 vs 루프 한계 도달)을 구분하지 않음 — 이상 없음 경로는 "이상 없음" 문구로 분기하고, 한계 도달은 3번 항목의 "미확정(한계 도달)" 구분 기록과 함께 처리
- `README.md` 아키텍처 다이어그램에 status→(대상 없음)→report 분기 미표기 (graph/build.py docstring 다이어그램과 불일치) — 동기화
- `tools/eds_search.py` k+1 조회 버퍼는 필터로 제외되는 후보가 많으면 유효 후보가 더 있어도 k 미만을 반환할 수 있음 (Local 도 동일, 계약상 허용) — 6번 실측 검증 때 함께 확인
