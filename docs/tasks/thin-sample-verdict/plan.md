# thin-sample-verdict — 표본 미달 판정 `(2c)` 신설 계획

작성: 2026-09-16 · 설계자 Claude · 구현 Codex Sol · 검증 Codex Astra

## 목표와 요구사항

게이트가 **"갈릴 수도 있는 후보가 있는데 타깃 표본이 얇아 물어볼 수 없다"** 는 상태를
제 이름으로 내보내게 한다. 지금 이 상태는 `(2a)`·`(2b)` 어디에도 안 걸려
사실과 다른 사유로 나간다(아래 "현재 동작" 의 실측 근거 참조).

요구사항:

1. 새 판정 `finalize_status = "thin_sample"` 을 게이트 분기 `(2c)` 로 신설한다.
2. 얇은 후보를 리포트 근거로 싣고 `[표본 미달]` 로 찍는다 — 어느 스텝·어느 항목의
   표본을 채워야 하는지 엔지니어가 알 수 있어야 한다. 이 판정의 조치가 그것이다.
3. `(2a) weak_signal` 로 나가는 경로에서도 얇은 후보가 소각되지 않는다.
4. 이 변경으로 **거짓이 되는 기존 문장을 같이 고친다**(D7).

## 작업 범위 및 제외 범위

### 범위

- `graph/evidence.py` — `Bundle.thin_sample()` · 얇음 술어 1개 · `group_to_dict` 플래그
- `graph/nodes.py` — `(2c)` 분기 · `_evidence_groups` 확장 · `_residual_evidence_note`
  좁히기 + 얇은 쪽 문구 · `_drop_reason` 갈래 추가 · `_no_candidate_action` 의
  `opens_thin` · `report_node` 라벨과 괄호 접두어
- `graph/state.py` — `finalize_status` 어휘 주석
- `llm/client.py` — 결론 문장 분기 · sys 프롬프트 규칙 · 근거 JSON 설명 문장 한정
- `README.md` — 판정 표에 행 추가
- `tests/` — 신규 테스트 + 기존 단언 갱신

### 제외 범위

- `residuals()` 의 정의 변경 — **금지.** 얇은 후보를 잔차에 흡수시키는 것은 설계
  단계에서 기각했다(사용자 결정). `_fold_key`·근거 적재·`(4)` 백스톱까지 파급된다.
- `(2a)`·`(2b)`·`(2)` 의 **하한 변경** — 금지. `(2c)` 는 추가만 한다.
- `_passes`(`domain/engine.py`)의 판별 규칙, `COMMONALITY_PASS_MIN_TARGET` 기본값,
  도구의 후보 절단 규칙 — 금지. 이 작업은 **판정**이지 판별선 조정이 아니다.
- git 조작(커밋·브랜치·푸시·태그·리베이스) — 금지. origin 미푸시 17커밋은 그대로 둔다.
- 워킹 트리의 미추적 파일(아래 "미커밋 변경사항") 정리·되돌림 — 금지.

## 기준 브랜치와 커밋

- 기준: `main` @ `eeb2eb5`
  (`docs(tests): 재리뷰 I-A - (2) 하한 셋 중 하나만 옮겨 "만 본다" 로 못박은 문장을 고친다`)
- **브랜치·커밋은 만들지 않는다.** 인계 스크립트의 요청문이 커밋·푸시를 금지하므로
  구현은 `main` @ `eeb2eb5` 의 **워킹 트리에서** 진행한다. 브랜치를 딸지, 언제 커밋할지는
  사용자 결정으로 남긴다(작업이 끝난 뒤 판단한다).
- 테스트 기준선: **583 passed**.
  ⚠️ 실행값은 **595** 로 나온다 — 다른 도구가 같은 워킹 트리에 만든 미추적
  `tests/test_workflow.py`(12건)가 더해진 값이다. 이 저장소의 기준선은 583이며,
  그 12건은 이 작업의 범위도 책임도 아니다.

## 계획 시점에 존재하는 관련 미커밋 변경사항

`git status` 기준. **전부 이 작업과 무관하며 손대지 않는다.**

- 수정: `.gitignore`
- 미추적: `AGENTS.md`, `CLAUDE.md`, `workflow.py`, `workflow-config.json`,
  `tests/test_workflow.py`, `docs/codex-handoff.md`, `docs/tasks/`,
  `docs/2026-08-22-agent-direction-review.md`,
  `docs/2026-08-31-finalize-계약-영향범위.md`, `docs/2026-09-12-F-준비.md`

제품 코드(`graph/`·`llm/`·`tools/`·`domain/`)에는 미커밋 변경이 없다 — 이 작업이
건드릴 파일은 전부 `eeb2eb5` 상태 그대로다.

## 현재 코드 구조와 관련 파일

### 틈새의 원인 (✅ 코드에서 확인)

`tools/commonality.py::_score_map` 은 점수 절단(`MIN_SCORE`)만 걸고 **타깃 표본 수를
안 본다**(`MIN_TARGET` 은 `find_commonality` 진입부에서 타깃 *전체* 장수만 본다).
그래서 `target_pass = 1` 짜리 후보가 정상적으로 나온다. 그 후보는:

| 자리 | 결과 |
|---|---|
| `domain/engine.py::_passes` | `타깃 표본 1 < 2` 로 **미통과** |
| `evidence.Bundle.residuals()` | `target_pass >= COMMONALITY_PASS_MIN_TARGET` 요구 → **제외** → `(2a)` 안 열림 |
| `nodes._no_separation_state` | 비센서 점수가 **전부** `RESIDUAL_MIN_SCORE` 미만일 것을 요구 → 이 후보는 아랫선 이상이라 **`(2b)` 안 열림** |
| `_evidence_groups` / `ranked_groups()` | 둘 다 `passing()` + `residuals()` 만 본다 → **리포트에 한 줄도 안 닿는다** |

`_no_separation_state` 의 독스트링이 이 후보의 존재를 이미 명시한다("표본이 얇아
반려된 완전 분리 후보(예: score 1.0 인데 target_pass 1 < 2)"). 그 사실을 `(2b)` 의
점수 조건을 정당화하는 데만 쓰고, **그 후보 자체의 출구는 안 만들었다.**

⚠️ 메모리·조사 문서의 라벨 "판별선 미달 + 표본이 얇은 후보" 는 느슨하다.
**점수가 판별선을 넘어도 이 틈새에 빠진다** — `nt=2, a=1, c=0` 이면 score 0.5 로
판별선(기본 0.5) 이상인데 표본 미달로 반려된다. 이 상태의 성질은 "약하다" 가 아니라
**"물어볼 수 없다"** 이고, 그것이 이름과 문구를 가르는 근거다.

### 현재 동작 (2026-09-14 실측, 조사 문서 2.2절 각주)

- 빈손 제출 + 다른 축 침묵 → `(2)` 가 받아 **"신호 없음 … 분리되는 후보 없음"**.
  후보가 있고 점수도 센데 없다고 말하는 **거짓 판정문**이다.
- 얇은 후보를 지목했거나 다른 축에 통과 후보가 있으면 → `(2)` 하한(`not claim_id` ·
  `not statistical_passing()`)에 막혀 **반려 → 루프 한계 `inconclusive`**.
  M4 가 닫기 전에 보이던 것과 같은 증상(사유가 실제와 다르다).

### 관련 파일과 심볼

- `graph/evidence.py` — `Claim`(`passes`·`score`·`target_pass`·`kind`),
  `Bundle.residuals()`/`passing()`/`statistical_passing()`/`ranked_groups()`,
  `group_to_dict`, `format_group_line`
- `graph/nodes.py` — `_gate_verdict`(분기 `(1)`~`(5)`), `_evidence_groups`,
  `_record_evidence`, `_residual_evidence_note`, `_honest_pick`, `_approvable_pick`,
  `_drop_reason`, `_drop_unapprovable_pick`, `_no_separation_state`,
  `_no_candidate_action`, `_gateless_finalize`, `report_node`
- `llm/client.py` — 결론 문장 분기(`finalize_status` 별), 리포트 sys 프롬프트 규칙,
  근거 JSON 설명 문장("passes 가 false 인 항목은 …")
- `graph/state.py` — `finalize_status` 어휘 주석
- `tests/test_graph_nodes.py`(게이트 판정), `tests/test_evidence.py`(번들),
  `tests/test_mock_llm.py`(프롬프트·결론 문장)

## 설계 결정과 이유

### D1. 새 판정을 만든다 (사용자 결정)

대안 둘을 기각했다. **`residuals()` 확장**은 "약한 신호" 가 거짓 서술이 되고
(점수는 셀 수 있다) `_fold_key`·적재·백스톱까지 파급이 오히려 크다.
**판정문 문구만 한정**하는 안은 지목한 경로가 여전히 루프 한계로 새고
`finalize_status` 가 `no_signal` 이라 리포트 소비자가 구분하지 못한다.

### D2. 이름은 `thin_sample`, 리포트 표기는 "표본 미달"

`insufficient_sample` 은 **이미 2단 센서 도구의 status** 다
(`tools/sensor_compare.py`, `llm/client.py` 의 센서 설명 문장). 같은 프롬프트 안에서
두 어휘가 나란히 나가므로 같은 이름을 쓰면 "센서 표본 부족" 과 "게이트 판정" 이
섞인다. 이 저장소는 한 이름이 두 뜻을 갖는 사고(`no_paired_stratum` 이 축 무관·축
고유를 같은 이름으로 부른 것)를 이미 겪었다.

### D3. 판별 조건 — `residuals()` 와 서로소로 정의한다

```
not c.passes
and c.kind != "sensor"                                       # 센서는 자기 판별선을 쓴다
and statuses[c.tool] == "ok"                                 # "볼 것이 없었다" 는 얇은 것이 아니다
and c.target_pass <  ya_config.COMMONALITY_PASS_MIN_TARGET   # residuals() 는 >= 를 요구한다
and c.score      >= ya_config.RESIDUAL_MIN_SCORE             # 아랫선 미만은 (2b) 영역이다
```

- `target_pass` 부등호가 `residuals()` 와 반대라 **정의상 한 claim 이 양쪽에 못 든다.**
  `_evidence_groups` 가 두 목록을 이어 붙여도 중복이 안 생긴다.
- 아랫선을 공유하므로 `(2b)` 와도 배타적이다(`(2b)` 는 비센서 점수가 전부 아랫선
  미만일 것을 요구한다). 점수가 아랫선 미만이면서 표본도 얇은 후보는 `(2b)` 를
  막지 않고 그대로 "안 갈렸다" 영역에 남는다 — 그 후보에 대해서는 `(2b)` 의 서술이 참이다.

### D4. 분기 위치와 `(2a)` 와의 순서 (사용자 결정)

순서는 `(1) → (2a) → (2b) → (2c) → (2) → (3) → (3b) → (4) → (5)`.

- **`(2)` 보다 앞이다.** 뒤에 두면 빈손 제출만 `(2)` 로 새어나가 **같은 증거가 제출
  형태에 따라 다른 판정**을 받는다 — `(2a)`·`(2b)` 를 `(2)` 앞에 둔 것과 같은 원칙.
- **`(2a)` 가 이긴다.** 잔차는 게이트 계약(표본)을 다 채우고 점수로만 떨어진 후보라
  정보가 더 많고, "타깃/대조군을 넓히면 갈릴 수 있다" 는 조치가 얇은 후보의 조치를
  포함한다. 대신 **얇은 후보를 그 경로에서 소각하지 않는다**(D5).
- 이 우선순위는 **문면 순서로만** 정한다. `(2c)` 조건에 `not residuals()` 를 또 적지
  않는다 — 같은 규칙을 두 자리에 적으면 한쪽만 고치는 것이 이 저장소의 반복 결함이고,
  `(2a)` 가 `(2)` 를 이기는 방식이 이미 문면 순서다.

### D5. 증거 적재는 `_evidence_groups` 한 자리에서 넓힌다 (사용자 결정)

```python
weak = bundle.residuals() + bundle.thin_sample()
if bundle.statistical_passing() or not weak:
    return passing_groups
return bundle.ranked_groups(bundle.passing() + weak)
```

- 하한(`not statistical_passing()`)은 **그대로 둔다.** 이것이 접기 계약의 전제이고,
  얇은 후보도 `passes=False` 라 "합집합의 비센서가 전부 미통과" 가 유지된다 —
  `_fold_key` 가 통과 claim 과 미통과를 한 묶음에 섞지 않는다(B 설계 4절 · C 계약).
- 한 자리를 고치면 네 소비자(`(2a)`·`(2b)`·`(4)`·백스톱)가 함께 갱신된다. 그 함수의
  독스트링이 이미 "규칙을 네 번 적으면 한 자리를 빠뜨린다" 고 경고한다.
- `(2b)` 경로에서는 얇은 후보가 정의상 존재할 수 없어(D3) 동작이 안 바뀐다.

### D6. 리포트 라벨은 조치로 가르고, 괄호는 도구가 낸 사유를 그대로 옮긴다

- 라벨: `passes` 면 `근거`, 얇으면 `표본 미달`, 나머지 미통과는 `잔차`.
- 판정 재료는 문자열이 아니라 `group_to_dict` 가 싣는 **구조적 플래그**다.
  `reject_reason` 파싱은 금지되어 있다(`residuals()` 독스트링).
- 괄호 접두어: 잔차 줄은 `(판별선 미달: …)` 그대로 — 잔차는 표본 조건을 이미
  채웠으므로 점수로만 떨어진 것이 **참**이다. 얇은 줄은 `(미통과: …)` 로 쓴다 —
  얇은 후보는 점수와 표본 **둘 다** 떨어졌을 수 있어(예: score 0.3 · 타깃 1) 한쪽
  이름을 접두어로 붙이면 거짓이 된다. 사유 문자열 자체는 `_passes` 가 만든 것을
  그대로 옮기므로 두 이유가 다 적힌다.

### D7. 함께 고쳐야 참이 되는 자리

이 변경이 **기존 문장을 거짓으로 만드는 자리**다. 구현에서 빠뜨리면 초록 스위트로도
안 잡힌다 — 각각 단언을 함께 넣는다.

1. ⚠️ **`_residual_evidence_note`** — `final_claims` 의 `not passes` 를 세므로 얇은
   후보가 실리는 순간 `(2a)` 의 *"아랫선을 넘은 잔차 N건"* 이 **부풀어 거짓**이 된다.
   잔차만 세도록 좁히고(얇음 플래그로 제외), 얇은 쪽 건수를 말하는 문구를 따로 낸다.
   두 문구 모두 **절단 후 실제로 실린 수**를 센다(상한이 다 밀어낼 수 있다).
2. **`_drop_reason`** — 미통과 지목을 전부 *"판별선을 넘지 못해"* 라 부른다. 점수가
   판별선을 넘은 얇은 후보에는 거짓이다. 갈래를 넷 → 다섯으로 늘린다
   (`_approvable_pick` 과 **같은 술어**를 쓴다 — 그 함수 주석이 이미 경고하는 함정이다).
3. **`_no_candidate_action`** — `opens_thin = bool(bundle.thin_sample())` 을
   `step_back` 조건에 더한다. 안 넣으면 물러설 문이 열렸는데 안내가 없어 루프 한계까지
   왕복한다(`(3)` 이 겪은 라이브락, `_no_separation_state` 독스트링의 경고).
4. **`llm/client.py` 근거 JSON 설명** — *"passes 가 false 인 항목은 판별선을 넘지 못한
   잔차다"* 가 얇은 줄에 거짓이 된다. 얇은 항목을 따로 부르는 한정절을 넣는다.
5. **`graph/state.py`** 의 `finalize_status` 어휘 주석, **`README.md`** 판정 표.

## 인터페이스 및 데이터 구조 변경과 호환성 조건

| 대상 | 변경 | 호환성 |
|---|---|---|
| `Bundle.thin_sample()` | 신설(메서드 추가) | 기존 호출부 없음 |
| `group_to_dict` 결과 | 얇음 플래그 키 1개 추가 | 추가 전용. 옛 상태에서 실려 온 dict 는 키가 없고 `.get()` 기본값이 "얇지 않음" 이라 옛 동작과 같다 |
| `final_claims` 내용 | 얇은 후보가 실릴 수 있다(`passes=False`) | `passes` 기반 소비자는 이미 미통과를 다룬다. **단 D7-1·D7-4 를 안 고치면 문장이 거짓이 된다** |
| `finalize_status` | 값 `thin_sample` 추가 | `state.py` 주석·프롬프트 분기·README 표를 함께 갱신. 모르는 값은 기존대로 일반 분기로 떨어진다 |
| 게이트 판정문 | 새 머리말 "표본 미달 (…)" | findings 를 타고 리포트 LLM 까지 간다. 프롬프트가 "그대로 인용하라" 이므로 문구 자체가 계약이다 |

`domain/hypotheses.yaml` 은 이 판정 어휘를 싣지 않는다(✅ grep 확인) — 손대지 않는다.

## 단계별 구현 순서

각 단계는 테스트를 함께 넣고 통과시킨 뒤 다음으로 간다. 3단계의 두 항목은
**같은 커밋**이어야 한다(넓히고 안 좁히면 그 사이 커밋이 거짓 문구를 낸다).

1. **`graph/evidence.py` — 얇음의 정의**
   - 얇음 술어 1개(모듈 수준 헬퍼)와 `Bundle.thin_sample()` 을 `residuals()` 옆에 둔다.
   - `group_to_dict` 의 `lead` 에 같은 술어로 얇음 플래그를 싣는다.
     술어가 두 곳에서 쓰이지만 **함수는 하나**다.
   - 검증: 서로소 단언(같은 번들에서 `residuals()` 와 `thin_sample()` 의 교집합이 공집합),
     아랫선 미만 + 얇음은 `thin_sample()` 에 **안** 들어옴, 센서 제외, status != ok 제외.

2. **리포트 표기**(`graph/nodes.py::report_node`)
   - 라벨 3갈래와 괄호 접두어 2갈래(D6).
   - 검증: 얇은 후보가 실린 상태에서 `[표본 미달 N]` 이 찍히고 `[잔차` 가 안 찍힌다.
     잔차만 있는 기존 상태는 문자열이 그대로다(회귀 단언).

3. **적재 확장 + 문구 좁히기**(`_evidence_groups` · `_residual_evidence_note` + 얇은 쪽 문구)
   - D5 와 D7-1 을 **함께**.
   - 검증: 잔차 1건 + 얇은 후보 1건인 `weak_signal` 상태에서 ①둘 다 `final_claims` 에
     있고 ②판정문의 잔차 건수가 **1** 이며 ③얇은 건수를 말하는 문장이 따로 있다.

4. **게이트 분기**(`(2c)` · `_drop_reason` · `_no_candidate_action`)
   - `(2c)` 를 `(2b)` 와 `(2)` 사이에 넣는다. 하한은
     `not statistical_passing()` + `thin_sample()` + `_honest_pick(...)`.
   - 판정문: 커버리지 문구 + 지목 문구(형제와 같은 4갈래: 빈손 / 대체 / 센서 / 얇은 후보)
     + 실린 건수 + 최고 점수와 타깃 카운트 + **조치**("타깃 표본을 채워 재확인하라")
     + "리포팅으로 진행한다".
   - D7-2·D7-3 을 같이.
   - 검증: 아래 "잠글 것" 표.

5. **LLM 계약과 문서**(`llm/client.py` 결론 분기·sys 프롬프트·근거 JSON 설명 한정,
   `graph/state.py` 어휘, `README.md` 판정 표)
   - 프롬프트를 고치면 **단언도 같이 넣는다.** 이 저장소는 "프롬프트만 고치고 단언을
     안 넣으면 안 잠긴다" 를 두 번 실측했다(마지막은 `gate_lines[-1]` → `[0]` 훼손이
     582개 전부 통과한 것).

6. **훼손 실험과 전체 스위트** — 아래 훼손 표를 전부 돌린다.

## 예외 상황과 실패 시 기대 동작

| 상황 | 기대 동작 |
|---|---|
| 얇은 후보 + **환각 지목** | `_honest_pick` 이 막아 `(5) 반려`. 루프 한계에서 `_drop_unapprovable_pick` 이 지목을 버려 `(2c)` 가 열린다 — 형제 판정과 같은 대칭 |
| 얇은 후보 + **얇은 후보 자신을 지목** | `_honest_pick` 을 통과하므로 **한계 전에** `(2c)`. 판정문이 그 이름을 부르고 "원인으로 확정하지 않았다" 를 말한다 |
| 얇은 후보 + 다른 축에 **통과 후보** | `(2c)` 안 열림(하한 `not statistical_passing()`). `(1)` 승인이나 반려로 간다 — 통과 후보가 있는데 "표본 미달" 로 끝내면 거짓이다 |
| 얇은 후보 + **잔차** 동시 존재 | `(2a) weak_signal`. 얇은 후보는 근거로 함께 실리고 잔차 건수 문구는 잔차만 센다 |
| 상한(`REPORT_MAX_EVIDENCE`)이 얇은 후보를 다 밀어냄 | 판정문은 **실린 수**로 말한다. 0건이면 "있었으나 상한을 채워 리포트에는 실리지 않는다" 로 적는다(`_residual_evidence_note` 와 같은 처리) |
| 게이트 미경유 종료(백스톱·텍스트 이탈) | `_gateless_finalize` 가 빈손 제출로 `_finalize_gate` 를 부르므로 **자동으로 `thin_sample` 이 나간다.** 별도 분기를 만들지 않는다 |
| 축 status 가 `ok` 가 아닌데 후보가 있음 | `thin_sample()` 에서 제외. "볼 것이 없었다" 는 얇은 것과 다른 사실이다(`residuals()` 와 같은 이유) |

## 테스트 방법과 검증 가능한 완료 기준

실행: `python -m pytest -q` (기준선 583 passed. 실행값 595 는 "기준 브랜치" 절의 주석 참조).

### 잠글 것

| # | 상태 | 기대 |
|---|---|---|
| T1 | 얇은 후보 1건 + 다른 축 침묵 + 빈손 제출, loop 2 | `thin_sample` (지금은 `no_signal`) |
| T2 | 같은 상태에서 그 후보를 **지목** | `thin_sample`, 판정문이 그 `claim_id` 를 부른다 |
| T3 | 같은 상태 + **환각 지목**, loop 2 / loop 7 | loop 2 = 반려 · loop 7 = `thin_sample` |
| T4 | 얇은 후보 + 잔차 동시 | `weak_signal` · 둘 다 `final_claims` · **잔차 건수 = 1** |
| T5 | 비센서 점수가 전부 아랫선 미만 + 그중 일부가 얇음 | `no_separation`(`(2b)` 가 그대로 열린다) |
| T6 | 얇은 후보 + 통과 후보 | `(2c)` 안 열림 |
| T7 | 리포트 문자열 | `[표본 미달 N]` · `(미통과: …)` · 잔차 줄은 `[잔차 N]` · `(판별선 미달: …)` 유지 |
| T8 | `_drop_reason` | 판별선을 넘은 얇은 지목에 "판별선을 넘지 못해" 가 **안** 나온다 |
| T9 | `_no_candidate_action` | 얇은 후보만 있는 상태에서 "claim_id 를 비우고 finalize 하라" 가 붙는다 |
| T10 | `thin_sample()` ∩ `residuals()` | 공집합(임의 조합 픽스처) |

### 훼손 실험 (전부 CAUGHT 여야 한다)

훼손 복원은 `git checkout` 이 아니라 **`finally` 복원**으로 한다(커밋 안 된 작업을
날린 전례가 있다). 루프가 도구 타임아웃에 죽을 수 있으니 끝나면 `git diff` 로 확인한다.

| # | 훼손 | 잡는 단언 |
|---|---|---|
| M1 | `thin_sample()` 의 `target_pass <` → `<=` | T10(서로소) |
| M2 | `thin_sample()` 의 `score >=` 조건 삭제 | T5(`(2b)` 가 안 열림) |
| M3 | `thin_sample()` 의 `kind != "sensor"` 삭제 | 센서 단언 |
| M4 | `thin_sample()` 의 status 조건 삭제 | status != ok 단언 |
| M5 | `(2c)` 를 `(2)` **뒤로** 이동 | T1 |
| M6 | `(2c)` 를 `(2a)` **앞으로** 이동 | T4 |
| M7 | `(2c)` 하한에서 `_honest_pick` 삭제 | T3(loop 2 가 반려여야 한다) |
| M8 | `(2c)` 하한에서 `not statistical_passing()` 삭제 | T6 |
| M9 | `_evidence_groups` 에서 `thin_sample()` 삭제 | T4·T7 |
| M10 | `_residual_evidence_note` 를 옛 술어(`not passes`)로 되돌림 | T4 의 잔차 건수 |
| M11 | 라벨 3갈래를 2갈래로(얇음을 `잔차` 로) | T7 |
| M12 | 괄호 접두어를 얇은 줄에도 `판별선 미달:` 로 | T7 |
| M13 | `opens_thin` 삭제 | T9 |
| M14 | `_drop_reason` 새 갈래 삭제 | T8 |
| M15 | sys 프롬프트의 `thin_sample` 규칙 삭제 | 프롬프트 단언(5단계) |

### 완료 기준

1. 전체 스위트가 기준선 + 신규만큼 초록(583 + 신규, 미추적 12건 제외 기준).
2. T1~T10 이 전부 있고, M1~M15 가 전부 CAUGHT.
3. `README.md` 판정 표에 `thin_sample` 행이 있고 `state.py` 어휘 주석에 값이 있다.
4. 저장소 전체에서 **옛 규칙의 술어**로 grep 해 남은 자리가 없다 —
   "판별선을 넘지 못한 잔차" · "아랫선을 넘은 잔차" · `not c.get("passes"` 형태의
   미통과 판정. (키워드가 아니라 **술어**로 grep 한다. 키워드로 돌려 세 자리를
   놓친 전례가 있다.)

## 구현자가 자율적으로 결정할 세부 사항

- 얇음 술어와 플래그 키의 **이름**, 헬퍼의 배치(모듈 함수 / `Claim` 프로퍼티).
- 판정문·결론 문장의 **정확한 한국어 문면**(아래 내용을 담는 한).
  내용: 지목 사실 → 얇은 후보가 있다는 사실과 건수 → 최고 점수와 타깃 카운트 →
  조치(표본을 채워 재확인) → 리포팅 진행.
- 테스트 픽스처 구성과 파일 배치(`test_graph_nodes.py` / `test_evidence.py` /
  `test_mock_llm.py` 중 어디에 둘지).
- 얇은 건수 문구를 새 함수로 뺄지 `_residual_evidence_note` 를 인자화할지.
  (단 **두 문구가 같은 수를 세면 안 된다** — D7-1.)

## 설계 재검토가 필요한 사항 (구현자가 임의로 바꾸지 않는다)

- `(2c)` 의 **하한 3개**와 **분기 위치**(D3·D4).
- `_evidence_groups` 의 **하한**(`not statistical_passing()`) — 접기 계약의 전제다(D5).
- `residuals()` 의 정의, `(2a)`·`(2b)`·`(2)` 의 하한.
- 얇음을 `reject_reason` **문자열 파싱**으로 판정하는 것 — 금지된 방식이다.
- 위 범위를 벗어나야 통과하는 테스트가 나오면 그것은 구현 문제가 아니라 설계 문제다.
  `needs_design_revision` 으로 보고한다.

## 미해결 질문과 가정

### ✅ 코드에서 확인한 사실

- `_score_map` 이 표본 수를 안 봐 `target_pass=1` 후보가 나온다.
- `residuals()` 는 `target_pass >= COMMONALITY_PASS_MIN_TARGET` 을 요구한다.
- `_no_separation_state` 는 비센서 점수가 전부 아랫선 미만일 것을 요구한다.
- 리포트 라벨은 `passes` 로만 갈린다(`report_node`).
- `_residual_evidence_note` 는 `final_claims` 의 `not passes` 를 센다.
- `_drop_reason` 은 미통과 지목을 전부 "판별선을 넘지 못해" 로 부른다.
- `hypotheses.yaml` 에는 `min_target`/`min_score` override 도 판정 어휘도 없다.
- `metro` 축은 `a >= MIN_TARGET` 로 조각을 미리 걸러 이 후보를 안 낸다 —
  **틈새는 현재 `step_history` 축 고유**다.

### ⚠️ 설계상의 가정

- 게이트는 `ya_config.COMMONALITY_PASS_MIN_TARGET` 상수를 본다. `hypotheses.yaml` 의
  spec 이 `min_target` 을 override 하면 `_passes` 와 어긋날 수 있다.
  **`residuals()` 가 이미 같은 가정 위에 서 있어** 새로 생기는 위험이 아니고,
  현재 yaml 에 override 가 없어 도달 불가다. 이번 작업에서 해결하지 않는다.
- `COMMONALITY_MIN_TARGET`(탐색) ≤ `COMMONALITY_PASS_MIN_TARGET`(판별) 이 아닌 설정에서는
  metro 축도 얇은 후보를 낼 수 있다. 판정은 축을 안 가리므로 그때도 동작은 옳다.
- 얇은 후보의 실데이터 빈도는 모른다. 더미 데이터에서 재현 가능한 것만 확인했다.
- `REPORT_MAX_EVIDENCE >= 1` 을 전제한다(`_residual_evidence_note` 와 같은 전제).

---

# 잔여 작업 — 2차 인계 (2026-09-16, 설계자 확인)

1차 실행(run `15397151`)은 **사용자 중단**으로 `blocked` 로 끝났다. 기술적 차단이 아니다.
현재 워킹 트리 상태를 설계자가 직접 확인했다: **612 passed**, `(2c)`·`thin_sample()`·
`_evidence_groups`·라벨·`_unconfirmed_pick_note`·`_residual_evidence_note` 가
D3~D7 대로 들어가 있다. **R1~R4 는 해결됐고 재작업 대상이 아니다.**

남은 것은 Astra 가 마지막에 낸 **R5 하나**와 그 최종 재검증이다.

## R5 — 분석 프롬프트가 이제 수락되는 지목을 "반려된다" 고 가르친다

설계자가 코드로 재확인한 실재 결함이다.

### 자리 1 — `graph/nodes.py::ANALYZE_SYSTEM_PROMPT` (규칙 "판별선을 넘지 못한 후보만 있으면 지목하지 마라")

거짓이 된 절은 이것이다.

> 잔차마저 없는 상태에서 지목하면 반려되고 같은 반려를 되풀이하면 루프 예산만 태운다

`(2c)` 가 생긴 뒤로는 **잔차가 없어도** 표본 미달 후보가 있고 그 이름을 정직하게
지목하면 **루프 한계 전에 수락된다**(T2 가 그것을 잠근다). 운영 LLM 에게 실제
게이트와 **반대 계약**을 알려주는 문장이다.

고칠 때 지켜야 할 것:

- ⚠️ **넓혀 적으면 반대 방향으로 거짓이 된다.** 이 저장소는 같은 문단이 세 라운드
  연속 거짓이 된 전례가 있다(한 항만 옮기고 "…일 때만" 으로 못박았다).
  **수락 조건을 함께 적는다** — 잔차가 있으면 `(2a)`, 전축 대조 + 점수가 전부
  아랫선 미만이면 `(2b)`, 표본 미달 후보가 있으면 `(2c)`. 세 갈래 모두 **정직한
  제출**(도구 결과에서 실제로 받은 이름이거나 빈손)이 하한이다.
- 표본 미달 갈래에는 **조치**를 함께 적는다: 타깃 표본을 채워 재확인해야 한다는 것.
- 반려가 실제로 일어나는 자리를 뭉개지 말 것 — 지어낸 이름(환각), 통과 후보가 있는데
  센서·미통과를 지목한 경우 등은 그대로 반려다.

### 자리 2 — `llm/client.py` 의 `generate_report` 추상 독스트링

> 일부 판정(weak_signal·inconclusive)에서는 `passes: false` 인 항목(잔차 - 판별선을
> 못 넘은 후보)이 섞여 온다

`thin_sample` 판정에서도 섞여 오고, 그 항목은 **잔차가 아니다**(점수가 판별선을
넘었을 수 있다). 판정 목록에 `thin_sample` 을 더하고, 두 종류를 **구조 플래그
`thin_sample` 로 가른다**는 사실을 적는다. 이미 고쳐 둔 운영 프롬프트(user 메시지의
근거 JSON 설명)와 같은 계약이어야 한다.

## 이번 인계에서 하지 않을 것

- R1~R4 재작업, 이미 통과한 테스트의 재작성.
- **제품 동작 변경 금지** — 분기 순서·하한·`thin_sample()` 조건·라벨·판정문 문구를
  건드리지 않는다. 이번 작업은 **프롬프트와 독스트링, 그리고 그것을 잠그는 단언**뿐이다.
- git 조작(커밋·브랜치·푸시) — 1차와 동일하게 금지.

## 완료 기준 (2차)

1. ⚠️ **프롬프트를 고치면 단언도 같이 넣는다.** 이 저장소는 "프롬프트만 고치고 단언을
   안 넣으면 안 잠긴다" 를 두 번 실측했다. `ANALYZE_SYSTEM_PROMPT` 에 대한 단언을
   추가한다 — 옛 절이 사라졌다는 것과, 세 수락 갈래(`weak_signal`·`no_separation`·
   `thin_sample`)가 프롬프트에 적혀 있다는 것을 함께 본다.
2. `generate_report` 독스트링 단언(기존 계약 테스트 관행을 따른다).
3. 전체 스위트가 **612 + 신규**로 초록(현재 트리 기준. 583 은 미추적
   `tests/test_workflow.py` 12건과 이번 신규를 뺀 값이다).
4. `git diff --check` 오류 없음.
5. Astra 최종 재검증에서 R5 해결 확인, 새 지적이 있으면 Sol 수정 후 재검증.
