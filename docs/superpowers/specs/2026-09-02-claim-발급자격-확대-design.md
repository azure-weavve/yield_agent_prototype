# Claim 발급 자격 확대 — 2단 센서가 claim_id 를 받는다

- 작성일: 2026-09-02 / 기준 커밋: `7bfc946` (441 passed)
- 근거 문서: `docs/2026-08-31-finalize-계약-영향범위.md` §2-A, §4 권고 2번
- 확정 순서에서 **A**. 선행인 **C(축 간 공통 척도)는 2026-09-01 완료**(`7bfc946`).

---

## 0. 한 줄 계약

> 2단 센서 후보도 `claim_id` 를 받아 번들에 들어간다. 순위·`final_claims`·리포트
> `[근거]` 에 실리고 LLM 이 인용할 수 있지만, **게이트 승인(confirmed)의 지목
> 대상은 아니다.**

## 1. 무엇이 문제였나

지금 계약에서 리포트의 근거가 될 수 있는 것은 `hypotheses.yaml` 에 등록된 가설이
발급한 후보뿐이다. 판별자는 `graph/evidence.py:_is_hypothesis_result()` 이고,
그 형태를 만드는 곳은 `domain/engine.py::evaluate()` 하나다.

결과로 **2단 센서(`compare_sensor_distribution`)는 후보를 내도 Claim 이 되지
못한다.** claim_id 자체가 없으므로 `finalize` 로 지목할 수도 없고, 순위·접기·
`final_claims`·`[근거]` 어디에도 못 들어간다.

게이트는 `_no_candidate_action` 에서 "2단 센서로 근거를 더 좁혀라" 라고 안내하면서
그 결과를 받아 주지 않는다. **안내와 계약이 어긋나 있다.**

## 2. 왜 승인 대상에서는 빼는가

`tools/sensor_compare.py` 모듈 docstring 이 설계 원칙으로 못박은 문장이다.

> **p-value 를 쓰지 않는다.** 스텝당 센서가 수백 개라 α=0.05 면 우연히 수십 개가
> 유의하다.

다중비교 보정을 **일부러 안 한** 도구다. 이것을 단독 승인 근거로 열어 주면 1단이
빈손일 때 효과크기 하나로 `confirmed` 가 나가는 거짓 양성 기계가 된다. 센서는
"어느 챔버인가" 를 지목하는 도구가 아니라 지목된 뒤 "왜" 를 좁히는 2단이다.

그래서 센서 claim 은 **인용 가능하되 지목 불가**다.

## 3. 데이터 흐름

```
compare_sensor_distribution()          ← 게이트 계약을 여기서 붙인다
  {kind:"sensor", status, candidates:[{claim_id, passes, reject_reason, ...}]}
        |
        v
build_bundle()  ← _is_hypothesis_result 옆에 _is_sensor_result 분기
        |  ★ claims 에만 넣는다. ran / statuses / 폐기 장부에는 안 넣는다 (§5)
        v
  Claim(kind="sensor", score=effect_size, target_total=n_target, ...)
        |
        v
passing() -> ranked_groups() -> _is_statistical False -> 통계 등급에 지배당해 2등
        |
        v
final_claims -> format_group_line (kind 로 분기) -> 리포트 [근거]

게이트 (1) 승인      : ★  kind == "statistical" 하한 추가
게이트 (2) 물러섬     : ★★ no_signal 하한을 passing() -> statistical_passing() 으로 (§6)
게이트 반려 문구      : ★  센서 지목 분기 신설 (§6b)
```

## 4. Claim 의 모양 — `kind` 판별 필드

`Claim` 에 `kind: str = "statistical"` 을 더한다. 센서는 `kind="sensor"`.

| Claim 필드 | 센서에서의 값 |
|---|---|
| `claim_id` | `sensor:{step_seq}:{sensor_name}` |
| `tool` | `compare_sensor_distribution` |
| `hypothesis_id` | `""` (등록 가설이 아니다) |
| `step_seq` | 호출된 스텝 |
| `key` | `sensor_name` |
| `level` | `"sensor"` |
| `score` | `effect_size` (Cohen's d) |
| `target_total` / `control_total` | `n_target` / `n_control` |
| `target_pass` / `control_pass` | **쓰지 않는다** (2×2 가 아니다). 0 으로 두고 렌더러가 kind 로 막는다 |
| `p_permutation` / `p_min_possible` | `None` — 설계상 p 를 안 낸다 |
| `target_wafers` / `control_wafers` | 빈 튜플 (§7) |
| `level_columns` | 빈 사전 |
| `extra` | `target_mean`·`control_mean`·`target_std`·`control_std` 등 |

**`_is_statistical` 로 승인 하한을 걸지 않는 이유.** 그 함수는 "순열 참조 회차가
0이라 바닥이 1.0" 인 **1단 후보**에도 False 를 준다. 그것으로 승인을 막으면 이번
변경이 1단의 승인 가능 범위까지 조용히 좁혀, 2026-09-01 에 확정한 순위·게이트
계약이 흔들린다. 하한은 `kind` 로 명시적으로 건다.

**`hypothesis_id` 가 `""` 라서 안전한 것들.**
- `_is_roll_up_of` — `level_columns` 가 비어 `not a` 로 False. 포함관계 오판 없음.
- `dominates` 의 점수 비교 — `x.hypothesis_id == y.hypothesis_id` 조건이라 센서끼리만
  효과크기로 비교된다. 축을 넘는 오비교가 생기지 않는다.

## 5. `ran` / `statuses` / 폐기 장부에는 넣지 않는다

센서 결과를 그냥 번들에 흘리면 조용히 깨지는 것들이다. 조사 문서가 경고한
"그 후보가 예전 버킷에 있었기에 켜지던 조건" 이 정확히 여기다.

| 자리 | 센서 status 가 섞이면 |
|---|---|
| 게이트 (3) `uncomputable = ran_statuses <= NO_DATA_STATUSES` | 센서의 `ok`·`insufficient_sample`·`fetch_failed` 는 그 집합에 없다 → **`no_comparable_data` 가 영영 안 열린다** |
| 게이트 (2) `"no_signal" in statuses.values()` | 센서의 `no_signal` 이 1단의 것으로 둔갑 → 축을 하나도 안 돌리고 센서만 부른 뒤 "대조한 축에서는 원인을 좁힐 수 없다" 로 종료 |
| `_coverage.no_data` | 등록 축이 아닌 도구가 커버리지 분모에 섞인다 |
| `_no_candidate_action` 의 `if not bundle.ran` | "부를 축이 없다" 판정이 센서 호출로 뒤집힌다 |

**`ran`·`statuses` 는 "등록 축 커버리지" 전용 어휘다. 센서는 축이 아니다.**

### 폐기(supersede) 규칙도 적용하지 않는다

`build_bundle` 은 같은 tool 이 다시 돌면 앞 후보를 전부 버린다. 근거는 "그룹이
바뀌면 분모가 달라 옛 후보가 거짓" 이다. 센서는 group/control 이 주입이라 **항상
같고**, 다른 것은 `step_seq` 하나뿐이다. 스텝 A 와 스텝 B 는 서로를 대체하는
재실행이 아니라 **다른 질문**이다. tool 키로 묶으면 스텝 B 호출이 스텝 A 근거를
조용히 지운다.

claim_id 에 `step_seq` 가 들어가므로 같은 스텝 재호출은 같은 키로 덮어써진다.
폐기 장부가 필요 없다.

## 6. 라이브락 — 이번 변경의 가장 큰 함정

센서만 통과하면 `bundle.passing()` 이 비지 않는다. 그러면

- (1) 승인 — `kind` 하한에 막힌다
- (2) 물러섬 — `not bundle.passing()` 이 False 라 **`no_signal` 이 닫힌다**
  ((3)(3b)는 `passing()` 을 안 보지만, 그 둘은 "등록 축을 다 돌렸고 전부 계산 불가"
  라는 훨씬 좁은 조건이라 일반적인 물러섬 경로가 아니다)
- → `MAX_LOOPS` 까지 왕복하다 `inconclusive`

즉 근거를 살리려던 변경이 종료 경로를 막는다. 이것을 막는 것이 아래 이동이며,
**선택이 아니라 이 설계의 필수 구성요소**다.

`Bundle` 에 `statistical_passing()` 을 더하고, `passing()` 호출부 다섯 자리를
하나씩 판정한다.

| 자리 | 지금 | 바뀐 뒤 | 왜 |
|---|---|---|---|
| `nodes.py:417` 게이트 (2) `no_signal` 하한 | `not bundle.passing()` | `not bundle.statistical_passing()` | **라이브락의 진원지.** 센서가 통과했다고 물러설 길을 닫으면 안 된다 |
| `nodes.py:607` 없는/대체된 claim_id 안내의 `valid` | `bundle.passing()` | `bundle.statistical_passing()` | 지목 불가한 센서를 "통과 후보" 로 안내하면 왕복이 생긴다 |
| `nodes.py:620` "통과 후보가 하나도 없으면" 판정 | 〃 | 〃 | 센서만 통과한 상태에서 물러설 안내가 꺼진다 |
| `nodes.py:646` claim_id 미제출 시 `valid` | 〃 | 〃 | 위 607 과 같은 이유 |
| `evidence.py:272` `ranked_groups()` | `passing()` | **그대로** | 센서를 근거 목록에 싣는 것이 이번 변경의 목적이다 |

게이트 (3)·(3b)는 `passing()` 을 쓰지 않는다(`not claim_id` 와 `uncomputable` 로
판정한다). §5 로 센서 status 가 `statuses` 에 안 들어오므로 두 자리는 손대지 않는다.

`_no_candidate_action` 도 `passing()` 을 직접 부르지 않는다 — `step_back` 은
`ran_statuses`·`unrun`·`failed` 로만 판정하고 그 셋은 §5 때문에 센서에 영향받지
않는다. **호출 조건이 위 세 자리에 달려 있을 뿐이므로 함수 자체는 안 고친다.**

## 6b. `_gate_rejection` 에 센서 지목 분기를 신설한다

LLM 이 센서 claim_id 를 지목했을 때 지금 코드가 어디로 가는지 따라가면 두 자리가
**거짓말을 한다.**

| 센서를 지목했을 때 | 지금 도달하는 문구 | 무엇이 거짓인가 |
|---|---|---|
| 1단 통과 후보가 있다 (센서는 2등) | `"... p None, 점수 2.31 ... p 는 자기 바닥과 함께 읽어야 한다"` | 센서는 p 를 애초에 안 낸다. 바닥을 읽으라는 지시가 실행 불가능하다 |
| 1단 통과 후보가 없다 (센서가 1등) | `"반려: 확신도 0.90 < 0.7"` | 확신도가 임계를 넘었는데도 그렇게 적는다. **수치가 그 자리에서 자기모순** |

> ⚠️ **표 2행은 이제 조건부다.** 후속 `2026-09-06-잔차-지목-종료-design.md` 가 `(2a)`
> 하한을 "정직한 제출" 로 넓혀, **1단 통과 후보가 없고 아랫선을 넘은 잔차가 남아
> 있으면** 센서를 지목한 제출은 `(2a) weak_signal` 로 먼저 받아져 이 반려 분기에
> 도달조차 하지 않는다. 아래 신설 분기가 실제로 도는 것은 그 문이 닫힌 상태 —
> **1단 통과 후보가 있거나(= 표 1행) 아랫선을 넘은 잔차가 하나도 없을 때**다.
> 분기 자체는 그대로 필요하다: 표 **1행**의 거짓말(`"p None"`)은 잔차가 있어도
> 통과 후보만 있으면 그대로 나가고, 2행의 거짓말은 잔차가 없을 때 나간다.

그래서 `claim.passes` 검사 **뒤, 순위 비교 앞**에 분기를 하나 넣는다.

> 반려: `{claim_id}` 는 2단 센서 후보다. 센서 근거는 리포트에 함께 실리지만
> **원인 확정의 지목 대상이 아니다** — 스텝당 센서가 수백 개라 효과크기 순위만으로는
> 우연한 분리를 가릴 수 없다. 가설 도구(hyp_*)가 발급한 claim_id 를 지목하라.

지목할 통계 후보가 하나도 없으면 목록 대신 `_no_candidate_action` 을 붙인다 —
607·620 자리와 같은 이유다(실행 불가능한 지시를 남기면 루프 한계까지 왕복한다).

## 7. 접기(fold) — 센서는 빈 wafer 목록으로 홀로 선다

`ranked_groups()` 는 `target_wafers` 가 비면 `("__unfoldable__", claim_id)` 로
각자 홀로 세운다. 센서 claim 은 이 경로를 탄다.

**wafer 목록을 싣지 않는 이유.** 센서 도구는 주입된 group/control 전체를 받으므로,
한 번의 호출이 낸 top-K 후보 10개가 **전부 같은 wafer 집합**을 갖는다. 그대로
실으면 서로 다른 센서 10개가 한 덩어리로 접혀 "같은 사실의 열 가지 이름" 이 된다.
그것은 거짓이다 — 온도와 파티클은 다른 설명이다.

`build_bundle` 은 이미 이 경우를 예상하고 있다(`target_wafers` 주석: "도구가 아직
안 싣는 경우(센서 등 다른 형태의 결과)에도 빈 튜플로 안전하게 떨어진다").

## 8. 판별선 — `SENSOR_PASS_MIN_EFFECT`

센서 도구는 지금 `d > 0` 이면 전부 top-K 에 싣는다. **효과크기 임계가 없다.**
그대로 근거로 태우면 `d=0.05` 짜리가 리포트 `[근거]` 에 올라간다.

`ya_config.SENSOR_PASS_MIN_EFFECT = 0.8` 을 신설한다(Cohen 의 large 관례).
`COMMONALITY_PASS_MIN_SCORE` 와 같은 자리에 같은 성격으로 놓인다.

- `d >= 임계` → `passes=True`
- 미달 → `passes=False` + `reject_reason` (1단 미통과 후보와 같은 취급: 번들에는
  남아 게이트가 조회할 수 있고, `passing()` 은 못 넘는다)

기존 `SENSOR_MIN_SAMPLE`(그룹 표본 하한)과 후보별 `len >= 2` 검사는 그대로 둔다 —
그 둘은 계산 성립 조건이지 판별선이 아니다.

## 9. 렌더링

`format_evidence_line` 은 지금 2×2 를 하드코딩한다. 센서 claim 을 그대로 태우면
`분리 점수 2.31 · 타깃 0/0 통과 · 대조군 0/0 통과` 가 찍힌다 — 숫자가 없는 것이
아니라 **틀린 숫자**가 나간다.

`kind` 로 분기한다.

```
sensor:CC003000:TEMP_1 · 효과크기 2.31 · 타깃 n=12 평균 812.4 · 대조군 n=40 평균 799.1
```

- `분리 점수`·2×2 카운트·순열 p 는 찍지 않는다.
- `group_to_dict` 의 `folded()` 도 같은 이유로 분기한다. 센서는 §7 때문에 접히지
  않지만, 빈 wafer 목록 규칙이 바뀌면 바로 새는 자리다.

## 10. LLM 계약 (`hypotheses.yaml` · 운영 프롬프트)

> ⚠️ `hypotheses.yaml` 은 코드가 아니라 **LLM 이 읽는 계약 문서**다. 지난 순열 p
> 교정 때 리뷰 Important 4건 중 2건이 이 계약 구멍이었다.

담을 문장은 하나다.

> 센서 후보의 `claim_id` 는 **리포트에서 인용하기 위한 것이며 `finalize` 의 지목
> 대상이 아니다.** 원인을 확정하려면 가설 도구(hyp_*)가 발급한 claim_id 를 지목하라.

- `domain/hypotheses.yaml` — 통계 해석 문단이 4가설에 복붙돼 있으므로 **4곳 동기 수정**
- `llm/client.py` 운영 sys 프롬프트 — 같은 문구
- `tools/agent_tools.py::finalize` docstring — claim_id 설명에 한 줄

## 11. 파일별 변경

| 파일 | 변경 |
|---|---|
| `ya_config.py` | `SENSOR_PASS_MIN_EFFECT = 0.8` 신설 |
| `tools/sensor_compare.py` | 결과에 `kind:"sensor"`, 후보에 `claim_id`·`passes`·`reject_reason` |
| `graph/evidence.py` | `Claim.kind` · `_is_sensor_result` · `build_bundle` 분기 · `Bundle.statistical_passing()` · `format_evidence_line`/`folded` kind 분기 |
| `graph/nodes.py` | 게이트 (1) `kind` 하한 · (2)와 `_gate_rejection` 3자리의 `passing()` 기준 이동 · `_gate_rejection` 센서 지목 분기 신설 |
| `domain/hypotheses.yaml` | LLM 계약 4곳 |
| `llm/client.py` | 운영 sys 프롬프트 |
| `tools/agent_tools.py` | `finalize` docstring |
| `tests/` | 아래 §12 |

## 12. 검증

기준선 **441 passed** 를 유지한다.

새로 잠글 것 (각각 훼손 실험으로 확인한다):

1. 센서 후보가 `claim_id` 를 받고 번들 `claims` 에 들어온다
2. `d < SENSOR_PASS_MIN_EFFECT` 인 센서는 `passes=False` + `reject_reason`
3. 센서 claim 을 지목한 `finalize` 는 **승인되지 않는다** (`kind` 하한)
4. 1단 통과 후보가 있으면 센서는 순위 2등 이하다 (C 계약)
5. **센서만 통과한 상태에서 물러서면 `no_signal` 이 열린다** (§6 라이브락)
6. 센서 status 는 `bundle.statuses`·`ran` 에 들어오지 않는다 (§5 회귀 3건)
7. 다른 스텝의 두 번째 센서 호출이 첫 호출의 claim 을 지우지 않는다 (§5 폐기)
8. 센서 claim 의 `[근거]` 줄에 2×2 카운트가 찍히지 않는다 (§9)
9. 센서 후보 10개가 한 묶음으로 접히지 않는다 (§7)
10. 센서를 지목한 반려 문구가 **순열 p 나 확신도를 근거로 대지 않는다** (§6b 거짓말 2건).
    후속 `2026-09-06-잔차-지목-종료-design.md` 이후로는 **조건부다** — 1단 통과 후보가
    없고 잔차가 남아 있으면 센서 지목이 `(2a) weak_signal` 로 흡수돼 반려 문구가 아예
    안 나간다. 이 기준을 확인하려면 그 문이 닫힌 상태로 조립해야 한다: §6b 표
    **1행**(통과 후보 있음)은 **잔차가 있어도** 그대로 확인되고, **2행**(통과 후보
    없음)만 **잔차가 없는 상태**를 요구한다.

> **훼손 실험 필수.** 지난 5회 리뷰에서 매번 실재 결함이 나왔고 그 절반이 "고치다
> 만든 회귀" 였다. 특히 §5·§6 의 하한 이동은 훼손해도 테스트가 안 잡히면 잠근 것이
> 없는 것이다. 훼손은 "고친 코드" 가 아니라 **"안 넣어 본 상태"** 에서 뽑는다.

## 13. 이번에 하지 않는 것

- 미통과 **1단** 후보를 잔차로 싣기 → 조사 권고의 **B**
- `no_signal` 재정의 / "구분 불가" 판정 신설 → **D**
- `final_hypothesis`·`final_confidence` 복수화 → **E**
- `domain/registry.py` — 조사 결과 이 계약과 무관하다(문서 §5 정정 참조)
