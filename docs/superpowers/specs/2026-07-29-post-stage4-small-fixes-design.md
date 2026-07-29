# Stage 4 이후 소품 3건 — 설계

작성: 2026-07-29 · 브랜치 `post-stage4-small-fixes`

Stage 5(삭제) 착수 전에, Stage 축과 무관하게 독립적으로 고칠 수 있는 것만 묶었다.
전부 **크래시·오염 방지**이고 새 기능이 아니다.

**Stage 5 가 지울 코드는 여기서 건드리지 않는다.** `find_counterexamples` 라벨 가드,
`.env` 로 무력화되는 `LEGACY_TOOLS_ENABLED` 기본값 테스트, reload 보일러플레이트
3중복은 전부 Stage 5 삭제 대상이라 지금 고치면 버릴 코드를 고치는 셈이다.

---

## 1. finalize 승인 후 후속 tool 실행 중단 (미룸 5번)

**지금:** `graph/nodes.py` `tools_node` 의 for 루프가 한 AIMessage 안의 tool_call 을
끝까지 전부 실행한다. 그래서

- finalize 가 승인된 뒤에도 같은 메시지의 나머지 tool 이 실행되어 findings 에 남는다.
  종료 판정 **뒤에 생긴 증거**가 감사 기록에 섞인다.
- 한 메시지에 finalize 가 2개면 뒤가 앞의 `update`(`final_hypothesis`·`final_confidence`)를
  덮어쓴다. 승인된 가설이 조용히 바뀐다.

mock 은 항상 tool_call 을 1개만 내므로 현재 데모 경로에서는 드러나지 않는다.
실제 LLM(`LLM_MODE=openai`)은 그렇지 않다 — `parallel_tool_calls=False` 로 억제하고
있으나 모델·서빙 구현에 기대는 방어이고, 계약으로 못 박혀 있지 않다.

**처방:** 게이트가 `finalize_accepted` 를 찍는 즉시 루프를 중단한다. 남은 tool_call 은
실행하지 않되 **`"분석 종료로 생략"` ToolMessage 를 채워 응답한다** — LangChain 은
모든 `tool_call_id` 에 대응하는 ToolMessage 를 요구하므로, 빼먹으면 다음 LLM 호출이
스키마 오류로 죽는다. 생략된 call 은 findings 에도 같은 문구로 남겨 감사 추적을 끊지 않는다.

**반려는 종료가 아니다** — 반려된 finalize 뒤의 tool 은 그대로 실행한다.
`finalize_accepted` 는 승인(`confirmed`)과 루프 한계(`inconclusive`) 양쪽에서 찍히는데,
둘 다 그래프가 report 로 가는 종료 상태이므로 구분 없이 중단한다.

**테스트:** finalize + `get_wafer` 를 한 AIMessage 에 담아 tools_node 를 직접 호출 →
`get_wafer` 가 findings 에 실행 결과로 남지 않고, ToolMessage 는 tool_call 수만큼
반환되는지. finalize 2개(승인+승인)를 담아 뒤엣것이 `final_hypothesis` 를 덮지 않는지.

---

## 2. EDS 인덱스에 없는 wafer 크래시 (미룸 9번)

**지금:** `tools/grouping.py:32` 의 `_searcher_lazy().search(...)` 가 무방비다.
yield DB 에는 실재해 `unknown_wafers` 판정을 통과했지만 EDS 인덱스에는 없는 wafer 를
한 장 입력하면 `LocalEDSSearcher` 는 `KeyError`, `HttpEDSSearcher` 는 requests 예외로
**그래프 전체가 예외 종료**한다. 리포트도 감사 기록도 남지 않는다.

역방향(EDS 엔 있으나 yield DB 엔 없는 형제)은 이미 `unmatched_siblings` 로 해소돼 있다.
이쪽만 뚫려 있다.

**처방:** 검색을 감싸 예외를 잡고 조기 출구로 유도한다. 상태 이름은
**`unknown_target` 재사용이 아니라 전용 `eds_lookup_failed`** 를 쓴다.

- "wafer 가 데이터에 없다"와 "wafer 는 있는데 EDS 인덱스에 안 실렸다"는 사람이 할
  조치가 다르다. 후자는 입력 실수가 아니라 **인덱스와 yield DB 의 동기화 문제**다.
- 이 저장소는 조기 출구를 뭉개지 않는 관례를 이미 테스트로 고정해 두었다
  (`test_generate_report_distinguishes_early_exits`).

`normalize_target` 은 실패를 dict 로 보고하고(`eds_error` 키), 판단은 `status_node` 가
한다 — 정규화 계층은 결정론적 계산만 하고 그래프 흐름을 모른다는 기존 분담을 지킨다.

`generate_report` 에 분기 한 줄을 추가한다: "분석 미수행 — EDS 유사맵 조회 실패."

**⚠️ 2026-07-29 리뷰 반영:** 처음에는 상태 이름을 `eds_index_missing` 으로, 결론 문구를
"인덱스에 없다" 로 단정했다. 그러나 `except Exception` 은 인덱스 미등재뿐 아니라 서비스 장애·
인덱스 손상까지 함께 잡는다 — 네트워크가 끊겼을 때 "이 wafer 는 인덱스에 없습니다" 라고
말하는 것은 사실이 아니고 조치 방향도 틀리게 유도한다. 이름을 `eds_lookup_failed` 로 바꾸고
결론은 관찰 서술로 두었다. 구체 오류(`type(e).__name__: e`)는 `[현황]` 에 그대로 싣는다.
라벨 세분화는 미룸 6번(HTTP 오류 응답 실측)과 함께 결정한다.

**테스트:** `_searcher_lazy` 를 인덱스에 없는 wafer 에서 `KeyError` 를 던지는 스텁으로
바꿔치기하고 그래프를 돌려, 예외 없이 `finalize_status == "eds_index_missing"` 리포트로
끝나는지. 정상 경로가 그대로인지는 기존 E2E 가 지킨다.

---

## 3. mock 이 tool 실패 문자열에 죽는 문제 (리뷰 Minor)

**지금:** `graph/nodes.py:147-149` 는 tool 실행이 실패하면 결과를 **문자열**
(`"오류: ... 인자를 확인하고 다시 호출하라."`)로 ToolMessage 에 담는다. 반면
`llm/client.py` 의 `_result` 는 `json.loads` 결과가 dict 라고 가정하고,
호출부는 `res["candidates"]`(78행)·`sensor.get(...)`(102행)로 바로 파고든다.
그래서 1단이나 2단 도구가 실패하면 mock 이 `TypeError`/`AttributeError` 로 죽는다.

tool 오류 복구는 이 시스템이 이미 갖춘 기능인데(미룸 1번, 커밋 `dd27cae`), mock 이
그 복구 경로를 못 타고 죽는다.

**처방:** `_result` 가 dict 가 아니면 `{}` 를 반환하고, 1단 소비부를
`res.get("candidates", [])` 로 바꾼다. 그러면 도구 실패는 "분리되는 후보가 없다"와
같은 경로를 타 **확신도 0.2 로 물러선다** — 이미 있는 정직한 후퇴 분기다.
2단은 `sensor.get("status") != "ok"` 분기가 `{}` 를 그대로 흡수한다.

**테스트:** 1단 도구 결과 자리에 오류 문자열 ToolMessage 를 물린 뒤
`analyze_step` 이 죽지 않고 낮은 확신도 finalize 를 내는지.

---

## 4. `tools/agent_tools.py` 파일 끝 개행 (리뷰 Minor)

파일이 개행 없이 끝난다. 1바이트.

---

## 이 문서가 다루지 않는 것

**`no_signal` 전용 `finalize_status` 는 미룸을 유지한다.** commonality 가
`status="no_signal"`(갈리는 후보 없음)을 내면 mock 이 낮은 확신도로 물러서고,
루프 한계에 닿아 `inconclusive`("미확정 — 루프 한계 도달")로 보고된다. 사유가
부정확하다 — 진짜 사유는 "lot 내부 대조로는 신호가 없다"이다.

고치려면 **종료 사유를 누가 소유하는지**부터 정해야 한다. 신호 없음을 아는 것은
도구인데 `finalize_status` 를 찍는 것은 게이트다. 게이트가 가설 문자열을 파싱하게
만들면 지금 게이트의 알려진 약점(문자열 매칭)을 키운다. 소품으로 처리할 크기가 아니다.

## 성공 기준

1. 기존 159 passed 유지 + 신규 테스트 전원 통과
2. 세 항목 모두 **먼저 실패하는 테스트**로 재현한 뒤 고친다
3. 정상 데모 경로(`README` 의 출력)는 한 글자도 바뀌지 않는다 — 전부 실패 경로 방어다
