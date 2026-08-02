# 게이트 강화 (EvidenceBundle) — 설계

작성: 2026-08-01 · 브랜치 `feat/evidence-bundle-gate`

> **실행 후 정정 (2026-08-02, Task 8):**
> 1. **`claim_id` 형식에 `level` 이 추가됐다.** 초안(§3) 형식은 `{spec['id']}:{step_seq}:{key}`
>    였다. 챔버 키가 `eqp_id` 와 `ch_id` 를 언더스코어로 이어 만들기 때문에
>    (`tools/commonality.py`), 설비 하나가 `ETCH9_B` 라는 이름을 갖고 다른 wafer 가
>    `eqp_id=ETCH9, ch_id=B` 이면 설비 후보와 챔버 후보의 id 가 충돌한다. commonality 의
>    후보 정체성이 `(level, step_seq, key)` 이므로 id 도 그 셋을 다 담는다. Task 1 검토에서
>    잡혀 §2·§3·§6 본문은 이미 반영돼 있다 (커밋 `3cdaa06`).
> 2. **`[근거]` 줄 예시(§6)의 데모 수치가 낡았다.** (지시받은 위치는 "§8 성공 기준
>    표" 였으나 실제로 `대조군 0/6` 이 적힌 곳은 §6 의 `[근거]` 줄 예시 코드 블록이다 —
>    §8 표에는 애초에 대조군 통과 수 breakdown 이 없다.) `대조군 0/6 통과` 로 적었던
>    자리는 실제 실행값 **`대조군 0/4 통과`** 다 (`python -X utf8 main.py W2406_02` 로
>    재확인, 2026-08-02). 아래 §6 예시를 실측값으로 정정했다.
> 3. **알려진 한계는 이미 §12 에 있다** — "모든 가설이 `status=ok` 인데 통과 후보가
>    0" 인 경우는 `no_signal` 이 아니라 루프 한계로 끝난다는 서술. 신규 추가 없음.

미룸 항목 "4번(no_signal 이 게이트에 안 들린다)" 과 "5번 (a) (승인이 자유 텍스트
substring 매칭)" 을 한 건으로 묶은 것이다. 별건처럼 보이지만 **뿌리가 하나**다.

---

## 0. 뿌리와 두 증상

게이트가 도구 결과를 구조화된 증거로 받지 않고 `findings` 를 덕타이핑으로 훑는다.

```python
# graph/nodes.py:250  _collect_evidence
if not isinstance(result, dict) or "candidates" not in result:
    continue
```

여기서 두 증상이 갈라진다.

**증상 1 — `no_signal` 이 게이트에 안 들린다.** `tools/commonality.py:272` 가
`status="no_signal"` 을 정확히 낸다. 그런데 게이트는 `candidates` 키만 보고 `status` 를
안 봐서, 적대적 케이스 4가 E2E 에서 `inconclusive` 로 끝난다
(`tests/test_adversarial_dummy.py:107` 이 그 상태를 단언 중). "신호 없다고 판정" 과
"루프 6회 다 써서 못 정함" 이 같은 문자열로 보고된다 — 엔지니어가 할 조치는 전자가
"대조군을 lot 밖으로 넓혀라", 후자가 "에이전트가 헤맸다" 로 서로 다른데도.
게다가 도구가 1회차에 아는 사실인데 MAX_LOOPS 를 다 돌고 끝난다.

**증상 2 — 승인이 자유 텍스트 substring 매칭이다.**

```python
# graph/nodes.py:218
if conf >= config.CONFIDENCE_THRESHOLD and any(eq in hypothesis for eq in suspects):
```

LLM 이 `"ETCH9_B 는 원인이 아니다"` 라고 써도 토큰이 들어 있으니 승인된다. 로드맵
목적절은 "LLM confidence 를 최종 근거로 쓰지 않는다" 인데 실제 게이트는 LLM 이 쓴
문장을 문자열로 뒤진다.

**덕타이핑은 생각보다 더 아슬아슬하다.** `sensor_compare` 결과에도 `candidates` 키가
있어서 위 루프에 **들어온다**. 센서 후보에 `passes` 키가 없어서 우연히 아무것도
수집되지 않을 뿐이다. 센서 결과에 `passes` 를 붙이는 날 조용히 오염된다.

---

## 1. 결정 요약

| # | 결정 | 대안 대비 이유 |
|---|---|---|
| 1 | `no_signal` 은 **등록 가설 소진 후**에 최종 판정 | `ppid_commonality` 의 YAML 설명이 "EQP_CH 로 안 갈릴 때 쓰는 2차 legend" 다. 첫 no_signal 로 끊으면 등록된 가설 하나를 안 써보고 포기한다 |
| 2 | 지목은 **`claim_id` 문자열 한 개** | 구조화 3필드는 LLM 이 틀릴 지점이 3배. 순번 지목은 순서 의존이라 감사 기록에서 사람이 못 읽는다 |
| 3 | 근접 미끼는 **최고 점수 규칙**으로 거른다 (동점 허용) | 2단 센서 필수화는 센서 없는 스텝을 원리상 영구 미확정으로 만들고 새 등급이 필요해진다 |
| 4 | 번들은 **`findings` 를 투영하는 순수 함수** | 도구 계약을 dataclass 로 바꾸면 ToolMessage JSON 왕복이 생긴다. state 누적은 같은 사실을 두 곳에 저장한다 |

---

## 2. EvidenceBundle

새 파일 `graph/evidence.py`. 상태를 갖지 않는다.

```python
@dataclass(frozen=True)
class Claim:
    claim_id: str          # "eqp_ch_commonality:chamber:CC002000:ETCH9_B"
    tool: str              # "hyp_eqp_ch_commonality"  (findings 의 tool 이름)
    hypothesis_id: str
    step_seq: str
    key: str
    level: str
    passes: bool
    reject_reason: str | None
    score: float
    target_pass: int
    target_total: int
    control_pass: int
    control_total: int


@dataclass(frozen=True)
class Bundle:
    claims: dict[str, Claim]    # claim_id -> Claim
    statuses: dict[str, str]    # tool 이름 -> 마지막 실행의 status
    ran: set[str]               # 유효 결과를 낸 hyp_* 도구 이름


def build_bundle(findings: list[dict]) -> Bundle: ...
```

**판별자는 `hypothesis_id` 키의 유무다.** `engine.evaluate` 결과에는 있고
`sensor_compare` 결과에는 없다. 덕타이핑을 명시적 계약으로 바꾸는 것이 이 설계의 핵심이고,
센서 결과가 증거 수집에 딸려 들어오던 경로가 구조적으로 막힌다.

**`ran` 은 "호출됐다" 가 아니라 "유효한 결과를 냈다" 다.** 인자 오류로 실패한 도구는
결과가 dict 가 아니라 오류 문자열이므로 `ran` 에 들어가지 않는다. 게이트는 그 도구를
계속 요구하고, 무한 재시도는 루프 한계가 잡는다. "불렀다" 와 "근거를 냈다" 를 구분하는
것은 이 저장소가 리뷰에서 반복해 걸린 실패 유형 1번이다.

**같은 도구가 두 번 실행되면 나중 결과가 앞 결과를 덮는다.** 그룹이 바뀐 재실행이면
최신이 맞고, 같은 그룹 재실행이면 값이 같다.

---

## 3. claim_id

`domain/engine.py` 의 `evaluate()` 가 후보마다 발급해 **도구 결과에 실어 보낸다.**
LLM 이 결과에서 그대로 읽어 옮겨야 하므로 도구 출력에 있어야 한다.

```python
claim_id = f"{spec['id']}:{cand['level']}:{cand['step_seq']}:{cand['key']}"
```

**게이트는 이 문자열을 파싱하지 않는다.** 사전 조회 키로만 쓴다. 구분자가 값에 섞여도
조회는 안전하다. 콜론 형식을 쓰는 유일한 이유는 감사 기록에서 사람이 읽을 수 있다는 것이다.

**id 는 commonality 의 후보 정체성 `(level, step_seq, key)` 를 전부 담아야 한다**
(`tools/commonality.py` 의 `agg` 키와 같은 조합). 초안은 `level` 을 뺐다가 Task 1 검토에서
잡혔다 — 챔버 키는 `eqp_id` 와 `ch_id` 를 언더스코어로 이어 만들기 때문에
(`commonality.py:108`), 설비 하나가 `ETCH9_B` 라는 이름을 갖고 다른 wafer 가
`eqp_id=ETCH9, ch_id=B` 이면 설비 후보와 챔버 후보의 id 가 같아진다. 사전 조회에서
통과 후보가 미통과 후보에 덮이면 게이트가 조용히 반대 판정을 낸다.

`hypothesis_id` 접두는 legend 가 다른 두 도구가 같은 `(level, step_seq, key)` 를 내는
경우를 막는다.

---

## 4. 게이트 판정표

`finalize(claim_id, hypothesis, confidence)` 로 인자가 하나 는다. `claim_id` 는
**기본값 `""`** 를 준다 — 필수로 만들면 LLM 이 빠뜨렸을 때 스키마 오류로 죽어, 게이트가
안내 문구를 돌려줄 기회를 잃는다. `hypothesis` 는 리포트 서술용으로만 남고 판정
권한이 없다.

판정은 위에서부터 처음 걸리는 줄로 결정된다.

| # | 조건 | 결과 |
|---|---|---|
| 1 | claim_id 가 번들에 있고 · `passes` 이고 · **같은 도구의 통과 후보 중 최고 점수(동점 허용)** 이고 · `confidence >= CONFIDENCE_THRESHOLD` | `confirmed` (종료) |
| 2 | 통과 claim 0 · 등록 `hyp_*` 전부 `ran` · `statuses` 에 `no_signal` 하나 이상 | `no_signal` (종료, 확정 아님) |
| 3 | `loop >= MAX_LOOPS` | `inconclusive` (종료) |
| 4 | 그 외 | 반려 |

**2번이 3번보다 위에 있어야 한다.** 순서가 뒤집히면 루프 한계에 먼저 걸려 케이스 4가
지금과 똑같이 `inconclusive` 로 끝난다. 변이 테스트 4번이 이 순서를 지킨다.

4번의 반려 문구는 번들 상태를 그대로 되돌려 준다.

| 상황 | 문구 |
|---|---|
| claim_id 미제출/미존재 | 유효 claim_id 목록. 하나도 없으면 "hyp_* 로 두 그룹을 먼저 대조하라" |
| `passes=False` | `reject_reason` 을 그대로 (`"분리 점수 0.3 < 0.5"`) |
| 통과했으나 최고 점수 아님 | 최고 점수 claim_id 와 두 점수를 나란히 |
| confidence 미달 | 현행 문구 유지 (비숫자 입력 안내 포함) |
| 통과 후보 0 · 안 돌린 가설 있음 | `"hyp_ppid_commonality 를 아직 안 돌렸다"` |

**confidence 임계는 1번(confirmed) 경로에만 건다.** 2번은 물러섬 선언이라 확신도를
요구하면 모순이다. 지금 mock 이 `no_signal` 에서 0.2 로 물러서는 것이 정상 동작이 된다.
confidence 는 이제 **필요조건일 뿐 근거가 아니다.** 승인 실권은 claim_id 조회 결과에 있다.

**최고 점수 비교는 같은 도구 안에서만 한다.** legend 가 다른 두 도구의 점수는 비교
대상이 아니다. 동점을 허용하는 이유는, 타깃 전원이 거친 설비를 대조군이 아무도 안
거치면 설비 롤업과 챔버가 둘 다 1.0 이 되고 정렬은 문자열순이라 **덜 구체적인 설비
롤업이 앞서기 때문**이다. 동점을 막으면 더 구체적인 챔버 지목이 반려된다.

게이트가 "등록 가설 전부" 를 아는 방법은 `TOOLS_BY_NAME` 에서 `hyp_` 접두 이름을 뽑는
것이다. `nodes.py` 가 이미 import 하고 있어 새 의존이 생기지 않는다.

---

## 5. `no_signal` 상태 어휘

`finalize_status` 에 `no_signal` 하나만 추가한다. `no_paired_stratum`·
`insufficient_group` 같은 다른 비-ok 상태에는 종료 상태를 따로 만들지 않는다 —
현재 파이프라인에서는 `status_node` 의 `isolated`·`control_insufficient` 조기 출구가
앞서 걸러 사실상 도달하지 않는 경로다. 도달하더라도 가설별 실제 status 는 번들과
리포트 본문에 그대로 남는다. 대조군을 lot 밖으로 확장하면 도달 가능해지므로 그때 다시 볼 자리.

리포트 결론 문구:

> 신호 없음 — lot 내부 대조로는 타깃만 거친 설비/챔버/PPID 가 없다. 원인 없음이 아니라
> 원인이 root_lot 전체에 걸렸을 수 있다는 뜻이며, lot 밖 대조군이 필요하다.

`finalize_accepted` 는 `no_signal` 에서도 True 다. 이 플래그는 승인 신호가 아니라
'리포트로 진행' 라우팅 플래그라는 기존 주석 그대로다.

---

## 6. 리포트에 코드가 만드는 `[근거]` 줄

`confirmed` 일 때 승인된 Claim 을 `report_node` 가 `generate_report(claim=...)` 로
넘기고, 코드가 `claim_id`·score·2x2 카운트를 직접 쓴다.

```
[근거] eqp_ch_commonality:chamber:CC002000:ETCH9_B · 분리 점수 1.0 ·
       타깃 3/3 통과 · 대조군 0/4 통과
```

지금은 근거 수치가 LLM 문장 안에만 있다. mock 은 각본이 수치를 넣어 주지만 운영
LLM 이 흐리면 리포트에서 사라진다. 게이트가 "설명 가능한 근거로 승인한다" 를
표방하는 이상 그 근거가 리포트에 남아야 한다.

`claim` 파라미터는 **기본값 `None`** 으로 추가한다 — 기존 호출부와 테스트가 그대로 동작한다.

---

## 7. 파급 파일

| 파일 | 변경 |
|---|---|
| `graph/evidence.py` | **신규** — `Claim`·`Bundle`·`build_bundle` |
| `domain/engine.py` | 후보마다 `claim_id` 발급 |
| `graph/nodes.py` | `_collect_evidence` 삭제 · `_finalize_gate` 재작성 · `ANALYZE_SYSTEM_PROMPT` 에 claim_id 규칙 · `report_node` 가 승인 claim 전달 |
| `tools/agent_tools.py` | `finalize(claim_id, hypothesis, confidence)` 시그니처와 docstring |
| `llm/client.py` | mock 각본 ppid 폴백 분기 + claim_id 사용 · `no_signal` 결론 문구 · `[근거]` 줄 · **운영 시스템 프롬프트에 같은 규칙** |
| `graph/build.py` | 모듈 docstring 의 "종료는 finalize 게이트(확신도)" 문구 — 확신도는 더 이상 승인 근거가 아니다 (라우팅 코드는 그대로) |
| `README.md` | `finalize_status` 어휘에 `no_signal` |
| `docs/stages.md` | 게이트 강화 반영 |

**운영 프롬프트 반영을 빼먹지 않는다.** mock 만 고치면 정직성 보장이 데모에만 걸린다 —
이 저장소가 리뷰에서 반복해 걸린 실패 유형 5번이다.

mock 각본 변경은 한 분기다. `hyp_eqp_ch_commonality` 에 통과 후보가 없을 때만
`hyp_ppid_commonality` 를 돌리고, 그것도 비면 물러선다. 케이스 1~3 은 EQP_CH 에서 바로
후보가 나와 경로가 그대로다.

---

## 8. 성공 기준

적대적 케이스 4종 + 데모. 1단 실측은 2026-08-01 측정값이다.

| 케이스 | 1단 실측 | 기대 판정 | 무엇을 재는가 |
|---|---|---|---|
| 1 반례 `LOT2414` | `ETCH1_B` 0.8 단독 통과 | `confirmed` | 반례가 있어도 판별선을 넘으면 승인 — 과하게 조여지지 않았음 |
| 2 미끼 `LOT2415` | `ETCH2_B` 1.0 · `PHOT2_X` 0.75 둘 다 통과 | `ETCH2_B` → `confirmed` / `PHOT2_X` 지목 → 반려 | 최고 점수 규칙 (지금은 둘 다 승인) |
| 3 결측 `LOT2416` | `ETCH3_B` 1.0 단독 통과 | `confirmed` | 결측이 분모에서 빠져도 판정이 흔들리지 않음 |
| 4 무신호 `LOT2417` | EQP_CH·PPID **둘 다 no_signal** | `no_signal`, 루프 한계 전 종료 | 이번 작업의 본체 (지금은 `inconclusive`) |
| 데모 `W2406_02` | `ETCH9_B` 1.0 단독 통과 | `confirmed` 유지 | 게이트를 조여도 데모가 반려로 바뀌지 않음 |

여기에 게이트 단위 테스트를 더한다. **claim_id 없이 `hypothesis` 문자열만으로는 절대
승인되지 않는다** 가 substring 매칭으로 되돌아가지 못하게 막는 테스트다.

---

## 9. 변이 테스트

구현을 일부러 틀리게 바꿔 **해당 테스트가 단독으로 죽는지** 확인한다. 통과하는 잘못된
구현이 나오면 테스트가 공허한 것이다. 변이가 통과하면 테스트를 의심하기 전에 **변이가
진짜 그 버그인지** 먼저 확인한다.

| # | 변이 | 죽어야 할 테스트 |
|---|---|---|
| 1 | 최고 점수 비교 제거 | 케이스 2 미끼 반려 |
| 2 | `passes` 검사 제거 | 미통과 claim 승인 금지 |
| 3 | 2번 규칙의 "전부 `ran`" 조건 제거 | ppid 유도 반려 |
| 4 | 2번 규칙을 3번(루프 한계) 뒤로 이동 | 케이스 4 E2E |
| 5 | claim_id 조회를 substring 매칭으로 되돌림 | 문자열 단독 승인 금지 |

---

## 10. 바뀌는 기존 테스트

| 테스트 | 변경 |
|---|---|
| `test_adversarial_dummy.py:107` | `inconclusive` → `no_signal` |
| `test_case2_gate_alone_does_not_reject_the_decoy` | 이름과 의미가 뒤집힌다. engine 은 여전히 `passes=True` 를 주지만 **이제 게이트가 거른다** — engine 단언은 유지하고 게이트 단언을 추가한다 |
| `test_graph_nodes.py` 게이트 픽스처 | `EVIDENCE_FINDING`·`EVIDENCE_FINDING_NEW` 후보에 `claim_id` 추가, finalize 호출에 claim_id 인자 |

`test_sensor_failure_is_not_reported_as_confirmed` 는 **손대지 않는다.** 2단이 죽으면
mock 이 확신도 0.5 로 물러서고, 새 게이트에서도 1번 규칙의 confidence 조건에 걸려
반려된 뒤 루프 한계에서 `inconclusive` 로 끝난다. 단언(`finalize_status != "confirmed"`,
`final_confidence < 임계`)이 그대로 성립한다.

---

## 11. 범위 밖 (이번에 하지 않는 것)

- **2단 센서 근거를 confirmed 필수 조건으로** — 센서 없는 스텝이 원리상 영구 미확정이
  되고 "1단만 갖춘" 새 등급이 필요해진다. 지금은 mock 이 자발적으로 물러서는 것에
  기대고 있고, 그 자발성을 게이트로 옮기는 것은 별건이다.
- **로드맵의 `evidence_score` 가중합** — 5개 성분 중 `reproducibility`·
  `temporal_consistency` 는 원천 데이터가 없어 계산 자체가 불가능하다. 못 세는 성분에
  가중치를 주면 숫자만 그럴듯해진다.
- 시간축 · 사람 검토 폐루프 · 다인성 — 전부 이 건 뒤 또는 사내 리소스 대기.

---

## 12. 알려진 한계

**모든 가설이 `status="ok"` 인데 통과 후보가 하나도 없는 경우**(후보는 있으나 전부
판별선 미달)는 2번 규칙에 걸리지 않아 지금처럼 루프 한계까지 가서 `inconclusive` 로
끝난다. `no_signal`(계산했으나 분리 없음)과 "약한 후보만 있음" 은 사람이 할 조치가
다르므로 같은 상태로 뭉개지 않는다. 현행 대비 퇴보는 아니지만 루프를 태우는 경로가
하나 남는다는 뜻이다. 실데이터에서 이 경우가 흔하면 그때 전용 상태를 판다.

**미끼 규칙은 순위를 신뢰한다.** 진짜 원인이 2등이면 게이트가 거부하고, 사람이 개입해야
한다. 게이트에는 어느 쪽이 진짜인지 가릴 도메인 지식이 없으므로, 약한 근거로 확정하는
쪽보다 거부하는 쪽을 택했다.

**`hypothesis` 자유 텍스트는 여전히 LLM 이 쓴다.** 게이트가 판정에 쓰지 않을 뿐,
리포트에는 그대로 실린다. 코드가 만드는 `[근거]` 줄이 그 옆에 붙어 대조 가능하게 하는
것이 이번 건의 대응이고, 문장 자체의 사실성 검증은 범위 밖이다.
