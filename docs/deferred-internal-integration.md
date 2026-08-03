# 사내 연동 시 처리할 미룸 항목

2026-07-11 리뷰(Claude + codex 교차 검증)에서 확인했으나, 실행 경로가 사내 연동
(`LLM_MODE=openai` / `EDS_MODE=http`) 전에는 없어 의도적으로 미룬 항목들.
**사내 연동 착수 시 이 문서를 작업 목록으로 사용한다.** 착수 전 각 항목의 완료 여부를
git log·코드로 먼저 확인한다 (1·2·3번은 이미 구현 완료 — 아래 참조).

## 1. ~~tool 호출 오류를 복구 가능한 ToolMessage 로 변환~~ (2026-07-18 구현 완료, 커밋 dd27cae)

- 구현: `graph/nodes.py` `tools_node` 가 `TOOLS_BY_NAME.get(name)` 으로 조회해 없는 tool 은
  안내 메시지를, `.invoke()` 는 try/except 로 감싸 실패 시 오류 내용을 ToolMessage 로 반환한다.
  LLM 이 다음 analyze 에서 스스로 교정하는 tool-calling 루프 표준 패턴.

## 2. ~~finalize confidence 비숫자 방어~~ (2026-07-18 구현 완료, 커밋 dd27cae)

- 구현: `graph/nodes.py` `_finalize_gate` 가 `float(raw)` 를 try/except 로 감싸 변환 실패 시
  0.0 으로 취급하고, 반려 메시지에 "confidence 는 0~1 사이 숫자로 다시 제출하라"를 덧붙인다.

## 3. ~~게이트에 결정론적 증거 조건 추가~~ (2026-07-13 구현 완료)

- 구현: `_finalize_gate` 가 findings 에서 판별 통과 후보의 토큰을 모아, 가설이 그것을
  포함해야 승인 — 이었다. (2026-07-13 당시에는 `compare_process_logs` 의 suspect_equipment 를
  봤고, Stage 0 에서 레지스트리 결과의 `candidates` 로, Stage 5 에서 그 도구 자체가 삭제됐다.
  이 substring 매칭은 2026-08-01 "게이트 강화(EvidenceBundle)" 에서 없어졌다 — 현재는
  LLM 이 지목한 `claim_id` 로 `EvidenceBundle` 을 조회해 판정하고, 그 근거 투영(findings →
  Claim 사전)은 `graph/evidence.py` 의 `build_bundle` 이 한다.)
  MAX_LOOPS 강제 종료는 `finalize_status="inconclusive"` 로 구분 기록되고
  리포트 결론도 "미확정(루프 한계 도달)" 톤으로 분기. 테스트: `tests/test_graph_nodes.py`

## 4. TLS 검증 기본값을 켜짐으로 (codex 4번)

- 위치: `ya_config.py` `EDS_HTTP_VERIFY = False`
- 문제: http 모드를 켜는 것만으로 인증서 검증 없이 사내 데이터 전송
- 처방: 사내 루트 인증서(.pem) 확보 → `EDS_HTTP_VERIFY = "인증서경로"` 를 기본값으로, 우회는 개발 환경에서만 명시적으로

## 5. ~~finalize 승인 후 같은 메시지의 후속 tool 실행 중단~~ (2026-07-29 구현 완료, 커밋 d5a33f5)

- 구현: `tools_node` 가 `stopped` 플래그로 승인/한계 판정 즉시 루프를 중단하고, 잔여 call 에는
  "분석 종료로 생략" ToolMessage 를 채워 응답한다(LangChain 은 모든 tool_call_id 에 응답을 요구).
  **반려는 종료가 아니므로 뒤따르는 tool 은 그대로 실행한다** — 그 절반도 테스트로 고정했다
  (`test_rejected_finalize_does_not_stop_following_calls`).

## 6. HTTP EDS 응답 스키마 실측 검증

- 위치: `tools/eds_search.py` `HttpEDSSearcher` — 필드명(`wafer_id`/`score`)이 추정값
- 처방: 사내 `/search` 실제 응답으로 매핑 확정 + 오류 응답(4xx/5xx, 타임아웃) 처리 방침 결정
- 여기서 **9번의 `eds_lookup_failed` 라벨 세분화도 같이 결정한다** — 지금은 인덱스 미등재와
  서비스 장애가 한 상태로 뭉쳐 있고, 실측 없이는 둘을 가를 수 없다

## 7. 실패 경로 테스트 확충 (codex 7번)

- 현재 테스트는 mock 정상 경로 중심. 연동 시 추가할 것: 알 수 없는 tool 이름 복구(1번),
  비숫자 confidence(2번), tool 실행 실패, MAX_LOOPS 강제 종료 시 리포트 내용, HTTP 오류 응답
- 실제 LLM 을 붙인 통합 테스트(별도 마커로 분리) 1본 이상

## 8. 기타 경미 (여유 있을 때)

- `ya_config.py` 상수의 환경변수 오버라이드 (`os.getenv`) — 코드 수정 없는 모드 전환
- `tools/yield_tools.py` `find_low_yield_lots` 기본 인자가 import 시점 바인딩 — 런타임 threshold 변경이 기본값에 반영 안 됨 → 2026-07-19 status 입력 재설계에서 해소
- ~~`graph/nodes.py` 모듈 레벨 `_llm = get_llm()` — import 시점에 구현 고정, 지연 획득으로 전환하면 테스트·모드 전환 유연~~ — **2026-07-31 완료.** `_llm_lazy()` 로 전환. `tests/test_graph_nodes.py::test_importing_nodes_does_not_acquire_the_llm` 이 별도 프로세스에서 "import 만으로는 안 잡힌다" 를 고정한다
- `llm/client.py` 리포트 결론 fallback "원인 미확정"이 원인(수율 이상 lot 없음 vs 루프 한계 도달)을 구분하지 않음 — 이상 없음 경로는 "이상 없음" 문구로 분기하고, 한계 도달은 3번 항목의 "미확정(한계 도달)" 구분 기록과 함께 처리
- ~~`README.md` 아키텍처 다이어그램에 status→(대상 없음)→report 분기 미표기 (graph/build.py docstring 다이어그램과 불일치) — 동기화~~ — **2026-07-31 완료.** 다이어그램에 조기 출구 엣지를 넣고, 사유 5종(`no_anomaly`·`unknown_target`·`eds_lookup_failed`·`isolated`·`control_insufficient`)과 "사람이 할 일" 을 표로 추가했다 (README "조기 출구" 절)
- `tools/eds_search.py` k+1 조회 버퍼는 필터로 제외되는 후보가 많으면 유효 후보가 더 있어도 k 미만을 반환할 수 있음 (Local 도 동일, 계약상 허용) — 6번 실측 검증 때 함께 확인
- 빈 대조 그룹(`control_group=[]`) lot 에서는 `ScriptedMockLLMClient._groups` 정규식이 매칭 실패해 ValueError — 현재 시드 데이터에서는 도달 불가 경로라 미룸. 사내 실데이터 연동 시 seed 라인 파싱/그룹 부재 처리 필요. → 2026-07-19 status 입력 재설계에서 해소 (GROUPS_JSON 라인으로 대체)

## 9. ~~yield DB 에는 있으나 EDS 인덱스에 없는 wafer 입력 시 크래시~~ (2026-07-29 구현 완료, 커밋 21955b3)

- 구현: `normalize_target` 이 검색을 감싸 실패를 `eds_error` **사실로만 보고**하고(흐름 판단은
  `status_node`), 전용 조기 출구 `eds_lookup_failed` 로 끝낸다.
- ⚠️ **원래 처방(`unknown_target` 계열 재사용)은 의도적으로 뒤집었다** — 'wafer 가 없다'와
  'EDS 조회가 실패했다'는 사람이 할 조치가 다르다. 근거는 spec `2026-07-29-post-stage4-small-fixes-design.md` §2.
  되돌리지 말 것.
- 남은 것: 예외를 넓게 잡으므로 **인덱스 미등재·서비스 장애·인덱스 손상이 한 상태로 뭉쳐 있다.**
  라벨 세분화는 6번(HTTP 오류 응답 실측)과 함께 결정한다. 그때까지 결론 문구는 사유를 단정하지
  않고 구체 오류는 `[현황]` 에 싣는다.

## 10. ~~get_searcher 캐시를 grouping/agent_tools 간 통합~~ (2026-07-31 완료)

- 위치: `tools/grouping.py` `_searcher_lazy` 와 `tools/agent_tools.py` `_searcher_lazy` — 각자 별도 lazy-singleton
- 문제: hnswlib 인덱스를 두 번 로드(메모리·기동시간 낭비), 각 전역이 스레드 비안전(Task 3 리뷰 Minor 와 동일 뿌리)
- 처방: 검색기 획득을 한 모듈(예: `eds_search.get_searcher` 자체 캐시)로 단일화하고 양쪽이 공유
- **구현**: 처방대로 캐시를 `eds_search._searcher` 하나로 모으고 양쪽 lazy-singleton 을 삭제했다.
  `tests/test_eds_search.py::test_both_call_paths_share_one_searcher` 가 "두 경로가 돌아도 로드 1회"
  를 고정한다. **스레드 안전은 손대지 않았다** — 락을 걸지 않았으므로 동시 최초 호출이 겹치면
  검색기가 두 번 만들어질 수 있다(둘 다 정상 동작하고 하나는 버려진다). 그래프가 단일 스레드라
  실행 경로가 없어서 미뤘고, 멀티스레드로 돌릴 일이 생기면 그때 락을 건다.

## 11. SIBLING_SEARCH_K=50 이 실제 인덱스 규모에서 형제를 잘라내지 않는지 검증

- 위치: `ya_config.py` `SIBLING_SEARCH_K = 50`, 사용처 `tools/grouping.py` `normalize_target`
- 문제: 한 사건의 형제 수가 50 을 넘으면 knn 조회 폭에서 잘려 형제 묶기가 불완전해짐 (더미 데이터에선 여유)
- 처방: 사내 양산 규모 인덱스에서 최대 형제 군집 크기를 실측해 K 를 조정하거나, 컷오프 기반 조회로 전환 검토
