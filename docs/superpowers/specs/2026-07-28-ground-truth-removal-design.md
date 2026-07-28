# Stage 4 — 더미에서 정답지 컬럼 걷어내기

작성일: 2026-07-28
선행: `docs/2026-07-24-domain-corrections.md` A-2·A-3, `docs/stages.md` (Stage 4)

---

## 0. 문제

### 0.1 원래 Stage 4 는 이미 끝나 있다

Stage 표의 Stage 4 는 "`defect_type` 그룹핑 → EDS top-k, status_node 재설계" 였다.
A-3 이 지정한 코드 영향 3건을 실제 코드와 대조하면 전부 완료 상태다 — **Stage 2 가
흡수해 갔다.**

| A-3 이 요구한 것 | 현재 |
|---|---|
| `status_node` 의 `defect_type` 완전일치 그룹핑 폐기 | 완료 — `grouping.normalize_target` 이 EDS top-k 로 묶는다 |
| `find_normal_wafers` → root_lot 기반 재작성 | 완료 — 함수가 사라지고 `select_control` 로 대체 |
| 07-18 의 열린 질문 "형제 그룹핑 방법" | 완료 — EDS 로 확정·종결 |

간판 항목이던 `SIBLING_MIN_SIMILARITY` 컷오프 검증은 이미 Stage 5.5 로 이월 결정됐다.

### 0.2 진짜 남은 문제 — 더미가 정답지를 들고 있다

`yield` 테이블에 **실데이터에는 없는 컬럼 두 개가 값을 갖고 있다.**

| 컬럼 | 적재기(`load_internal.py`) | 더미(`generate_dummy.py`) |
|---|---|---|
| `defect_type` | nullable, 사내 라벨 거의 없음 (A-3) | `center_spot`·`edge_ring` … 전부 채움 |
| `process_step` | `:118` 이 강제로 `None`, `:153` 주석 "항상 NULL (정답 누출 방지)" | `"Etch"`·`"Normal"` 채워 넣음 |

**적재기와 더미가 같은 컬럼을 두고 반대로 행동한다.** "어느 스텝이 원인인가" 는 시스템이
추론해야 할 **결론**인데(A-2), 더미는 그것을 입력 테이블에 적어 두고 있다.

Stage A 가 적대적 더미로 메우려던 「더미가 너무 착해서 안 드러난다」 문제의 남은 절반이
이것이다. 라벨이 있으면 그룹핑이 라벨로도 되고 EDS 로도 되므로, **EDS 경로가 실제로
성립하는지를 더미가 증명해 주지 못한다.**

### 0.3 이 Stage 의 성격

**방어 코드를 덧대는 것이 아니라 목발을 뺏는다.** "라벨이 NULL 일 때도 돌게 만든다" 가
아니라 "라벨을 없애고 무너지는 것을 고친다" 이다. 전자는 새 분기를 늘리고, 후자는 의존을
없앤다.

---

## 1. 결정

| # | 결정 | 근거 |
|---|---|---|
| 1 | `defect_type`·`process_step` 을 더미에서 **전원 NULL** | §0.2 — 적재기와 동작을 일치시킨다 |
| 2 | 컬럼 자체는 **남긴다** | A-3 의 "nullable 메타데이터". 스키마 계약도 안 깨진다 |
| 3 | 생성기의 정답지는 **`_truth_*` 키로 분리** | §2.1 |
| 4 | `aggregate_defects` **삭제** | §3.1 |
| 5 | `LEGACY_TOOLS_ENABLED` 기본값 **`1` → `0`** | §3.2 — 조용한 오확증을 막는다 |
| 6 | mock 각본 재작성, **데모 출력 변경을 감수** | §4 |

---

## 2. 더미 — 정답지 분리

### 2.1 `_truth_*` 키

생성기는 "이 wafer 의 이상을 Etch 에 심는다" 를 알아야 `process_log`·`step_history` 를
만들 수 있다. 그 정보를 지금은 `yield` 행 dict 에 담아 **그대로 DB 에 쓴다.**

행의 `process_step`·`defect_type` 을 **`_truth_step`·`_truth_defect`** 로 개명한다.

```python
rows.append({
    "wafer_id": wid,
    "yield": ...,
    "_truth_defect": FEATURED_DEFECT,   # DB 에 안 들어감
    "_truth_step": FEATURED_PROCESS,    # DB 에 안 들어감
})
```

DB 컬럼과 이름이 달라 섞일 수 없고, `_write_sqlite` 가 실수로 쓸 경로가 사라진다.
"쓰기 직전에 NULL 로 치환" 방식보다 이쪽을 택한 이유는, 행을 읽는 사람이 "DB 에도 값이
있겠구나" 로 오해할 여지를 남기지 않기 위해서다.

### 2.2 영향 범위

- 행 리터럴 8군데 (정상·불량군·대조군·패턴 그룹·구멍 케이스·적대적 lot·분할 lot)
- 읽는 곳 1군데 — `_make_process_logs` 의 `if r["process_step"] == step`
- `_write_sqlite` 의 `INSERT INTO yield` — 두 컬럼에 `None`

`_augment_yield`·`_make_step_history`·`_make_sensor_log` 는 이 두 컬럼을 안 쓰므로 무영향.

### 2.3 `_report()`

`_report` 가 `defect={r['defect_type']}` 을 출력한다. `_truth_defect` 로 바꾼다 — 생성기
자신의 진단 출력이므로 정답지를 보여도 된다. **DB 에 없는 값임이 드러나게** 라벨을 붙인다.

---

## 3. 라벨 의존 제거

### 3.1 `aggregate_defects` 삭제

라벨이 전원 NULL 이면 `[{"defect_type": None, "count": 6}]` 한 줄만 반환한다. LLM 에 노출된
base 도구라 남겨두면 루프 예산만 태운다. `2026-07-25-dummy-first-stage-reorder.md:372` 가
이미 "Stage 4 소관" 으로 지정해 둔 항목이다.

tool 래퍼(`agent_tools.py`)와 구현(`yield_tools.py`) 양쪽에서 지운다.

함께 사라지는 것:
- `grouping.normalize_target` 의 `label_counts`
- `nodes.py` 의 `label` (LLM 프롬프트의 `불량 그룹 ({label})`)
- `_summarize_target` 의 `defect 라벨 (참고): …` 줄

### 3.2 `LEGACY_TOOLS_ENABLED` 기본값 끄기

`find_counterexamples` 는 `defect_type == 'none'` 으로 "정상 wafer" 를, `defect_type = ?` 로
"같은 불량" 을 센다. 라벨이 NULL 이면 **두 목록이 모두 비고**, docstring 대로면 그것은
「가설의 특이성이 전수 데이터에서 확인됨」으로 읽힌다.

**데이터가 없어서 빈 것을 "반례가 없다" 로 보고하는 것** — `'none'` 채우기를 금지한 이유
(A-3: 라벨 없는 wafer 가 정상으로 둔갑)와 같은 실패다. 조용히 틀리느니 안 도는 게 낫다.

`config.py:43` 의 주석이 이미 "실데이터(step_history)에서는 못 도니 끈다" 라고 적어 두었다.
더미가 실데이터를 닮는 순간 그 논리가 더미에도 적용된다.

**끄는 것과 지우는 것은 다르다.** 삭제는 Stage 5 그대로이며, Stage 5 의 전제(대체 매핑
확인)도 그대로 남는다.

---

## 4. mock 각본 재작성

현재 각본의 1수가 `aggregate_defects` 라 반드시 바뀐다. 그리고 현재 데모는 Stage 3 에서
만든 2단을 **한 번도 부르지 않는다.**

```
finalize(0.6)                    → 게이트 반려 (근거 부족)
hyp_eqp_ch_commonality           → 챔버 지목 (1단)
compare_sensor_distribution      → 왜 그런지 (2단)
finalize(0.9)                    → 승인
```

게이트 반려 시연이 유지되고, 2단이 데모에 처음 나온다.

**데모 출력은 바뀐다.** Stage 2·3 은 "출력 불변" 을 검증 항목으로 썼지만 이번엔 불가능하다 —
각본이 라벨에 의존하고 있으므로 각본도 같이 고쳐야 한다. 대신 **수렴 결론(`ETCH9_B`)이
유지되는지**를 검증 항목으로 삼는다.

---

## 5. 테스트

라벨·스텝을 단언하던 테스트를 **"NULL 인지" 단언으로 뒤집는다.** 이것이 이 Stage 의 회귀
방어선이다 — 나중에 누가 더미에 라벨을 다시 채우면 즉시 깨져야 한다.

| 파일 | 현재 | 변경 후 |
|---|---|---|
| `test_dummy_data.py` | `defect_type == 'center_spot'`, `== 'none'` 등 6건 | 두 컬럼이 전원 NULL 인지 |
| `test_yield_tools.py:19` | `bad[0]["process_step"] == "Etch"` | `is None` |
| `test_agent_tools.py:28` | `aggregate_defects` 도구 테스트 | 삭제, 도구 목록에서도 제거 |
| `test_mock_llm.py` | 각본 순서 | 새 4수 순서 |
| `test_graph_nodes.py:102` | `label_counts` 스텁 | 제거 |

`test_commonality.py`·`test_engine.py` 의 인라인 DDL 은 자체 fixture 라 영향 없다.

### 5.1 `find_counterexamples` 테스트 5건 — 자체 fixture 로 이전

`test_yield_tools.py` 4건 + `test_agent_tools.py:52` 1건이 `center_spot`·`'none'` 을
인자로 넘긴다. **`LEGACY_TOOLS_ENABLED` 를 꺼도 이들은 `yt.find_counterexamples` 를 직접
호출하므로 라벨이 사라지면 그대로 깨진다.**

함수를 Stage 5 까지 살려 두기로 한 이상(대체 매핑 확인이 삭제의 전제다) 테스트도 살아
있어야 한다. **라벨을 가진 작은 fixture DB 를 만들어 그 위에서 검증한다.** 이 함수의 입력
계약이 "라벨이 있다" 이므로, 라벨 있는 DB 로 시험하는 것이 정직하다.

`test_yield_tools.py:258`(`test_find_counterexamples_null_spec_in_spec_none`)이 이미
`tmp_path`+`monkeypatch` 로 같은 일을 하고 있다 — 그 패턴을 헬퍼로 뽑아 5건이 공유한다.

이 방식의 뜻: **더미(=실데이터 모사)에는 라벨이 없고, 라벨을 요구하는 함수는 자기 fixture
안에서만 산다.** 둘이 섞이지 않는 것이 핵심이다.

**신규 회귀 테스트 (핵심):**

```sql
SELECT COUNT(*) FROM yield WHERE defect_type IS NOT NULL OR process_step IS NOT NULL
```
= **0** 이어야 한다.

---

## 6. 완료 기준

1. 위 SQL 이 0 을 반환한다.
2. 라벨 없이 1단→2단 깔때기가 끝까지 돈다 (E2E).
3. `python main.py` 의 수렴 결론이 여전히 `ETCH9_B` 다. **출력 문구는 바뀐다.**
4. `LEGACY_TOOLS_ENABLED=0` 이 기본. 레거시 도구는 코드에 그대로 있고, `find_counterexamples`
   는 자체 fixture 위에서 계속 테스트된다 (§5.1). 삭제는 Stage 5.
5. 전체 회귀 green.

---

## 7. 비목표

- **`SIBLING_MIN_SIMILARITY` 컷오프 검증** — 실데이터 분포가 필요하다 (Stage 5.5).
  컷오프를 못 정한 채 구조만 두는 것을 계속 감수한다.
- **레거시 도구·`process_log` 삭제** — Stage 5. 이 문서는 노출만 끈다.
- **라벨이 일부만 있는 경우** — 사내에 라벨이 조금이라도 생기면 그때 다룬다. 지금
  중간 상태를 설계하면 검증할 수 없는 분기가 는다.
