# docs 색인 — 어느 문서가 살아 있는 지침인가

이 색인을 빼고 문서가 31개(약 13,600줄)라 **무엇을 믿고 무엇을 기록으로만 읽어야
하는지**가 헷갈린다. 이 파일이 그 판정만 한다. 내용 요약이 아니다.

> **원칙: 과거 문서의 본문은 고치지 않는다.** 그때의 판단 기록이 사라지면 "왜 그렇게
> 결정했는지" 를 잃는다. 대신 낡은 문서 상단에 **상태 블록**(`⚠️ 이 문서의 상태`)을 붙여
> 무엇이 유효하고 무엇이 사라졌는지 적는다. 상태 블록이 있으면 그것을 먼저 읽을 것.

**현재 상태의 정본은 항상 코드다.** 문서와 코드가 어긋나면 코드가 맞다.

---

## 1. 현재 지침 — 읽고 따를 것

| 문서 | 무엇 |
|---|---|
| [`stages.md`](stages.md) | **Stage 순서의 단일 출처.** "다음에 뭐 하지" 는 여기부터. Stage 0~5 완료, 5.5(실데이터)는 사내 리소스 대기 |
| [`../README.md`](../README.md) | 시스템 구조·실행법·더미 설계의 정본 |
| [`사내-데이터-변환시-할일.md`](사내-데이터-변환시-할일.md) | 사내 실데이터 전환 체크리스트. **무엇을 바꿔야 하는가** |
| [`사내-투입-점검표.md`](사내-투입-점검표.md) | 사내망에서 처음 돌릴 때의 **확인 절차와 판독법.** 적재 검증 → tool 단위 → E2E 순. 4장(조용히 틀리는 것들)이 핵심 |
| [`internal-data-integration.md`](internal-data-integration.md) | ETL 적재 규칙·ID 체계·조인 키 합성. §2·§3-1 에 Stage 5 갱신 블록 있음 |
| [`deferred-internal-integration.md`](deferred-internal-integration.md) | 사내 연동(`LLM_MODE=openai`/`EDS_MODE=http`) 전에는 실행 경로가 없어 미룬 항목. **착수 시 작업 목록**. `codex.md` 항목들의 처리 상태도 여기서 추적 |
| [`2026-07-24-domain-corrections.md`](2026-07-24-domain-corrections.md) | 도메인 지식으로 **뒤집힌** 설계 결정들. 되돌리지 않으려면 읽어야 함 |
| [`2026-08-03-사내투입-진단정리.md`](2026-08-03-사내투입-진단정리.md) | **실데이터 첫 적재(2,800만 행)의 진단 결과와 후속 목록.** §4-A(문서)·§4-B(grain)·§4-C(회귀 테스트)는 **2026-08-03 처리 완료** — 남은 것은 §4-D 보류 3건과 §5 조사 스크립트다. §1 의 "조치 완료" 는 사내 머신 기준이었고 저장소 반영은 `3c45aba` |

## 2. 방향은 유효하나 세부가 낡음 — 상태 블록을 먼저 읽을 것

| 문서 | 상태 |
|---|---|
| [`evidence_based_analysis_roadmap.md`](evidence_based_analysis_roadmap.md) | **Phase 축("믿을 만하게 만든다") = 지정된 다음 축**이고 `stages.md:198` 이 여기를 가리킨다. 다만 본문이 만들라고 처방하는 도구 3개는 만들어졌다가 Stage 5 에서 **삭제**됐고 스키마 서술도 낡았다. 상태 블록에 대체 매핑 표가 있다 |
| [`analysis_loop_design.md`](analysis_loop_design.md) | 원문의 "아직 미구현" 은 **사실이 아니다** — 루프는 구현돼 있다(`graph/`). 착수 전 설계 메모의 기록 |
| [`도메인지식-주입-틀-공백분석.md`](도메인지식-주입-틀-공백분석.md) | "도메인 전문가가 지식을 넣을 자리" 관점의 진단. 1순위(레지스트리)는 반영 완료, 2순위는 `defect_type` 전 행 NULL(Stage 4)이라 단절 |

## 3. 과거 기록 — 고치지 않는다

그때 무엇을 왜 결정했는지의 기록. **작업 지시로 읽지 말 것.**

| 문서 | 무엇 |
|---|---|
| [`사내LLM연동_변경분_정리.md`](사내LLM연동_변경분_정리.md) | 2026-07-16 에 **끝난** 사내 LLM 연동 재현 기록. 기준선 63 passed(현재 200) |
| [`2026-07-18-status-node-review-and-redesign.md`](2026-07-18-status-node-review-and-redesign.md) | status_node 재설계 논의. 후속 구현은 `plans/2026-07-19-status-input-redesign.md` |
| [`2026-07-25-dummy-first-stage-reorder.md`](2026-07-25-dummy-first-stage-reorder.md) | 더미 우선 Stage 재배열 계획. **완료** — 체크박스와 "이 플랜을 구현하라" 지시가 남아 있지만 실행하지 말 것. 결과는 `stages.md` |
| [`codex.md`](codex.md) | 2026-07-13 codex 리뷰 **원문**(헤더 없음). 1번은 수정됨(`tools/target_selection.py:13`), 4번(TLS 기본값)·5번은 `deferred-internal-integration.md` 가 추적 중 |

## 4. `superpowers/` — spec·plan 스냅샷 (21개)

`superpowers/specs/<날짜>-<주제>-design.md` = 설계, `superpowers/plans/<날짜>-<주제>.md` = 구현 플랜.
**파일명에 날짜가 박혀 있어 구조상 과거 기록이고**, 그 날짜의 작업이 끝나면 동결된다.
plan 13개 · spec 8개인데 **이름이 정확히 짝을 이루는 건 7쌍뿐**이다 — 초기 6개 plan
(`2026-07-10`~`2026-07-19`, 그리고 `2026-07-24-causal-hypothesis-registry`)은 같은 이름의
spec 이 없다(그 spec 은 하루 앞선 `2026-07-23-...-design.md`).
어떤 Stage 가 어느 spec/plan 을 썼는지는 `stages.md` 가 짚어준다.

가장 최근 것부터: `2026-08-01-evidence-bundle-gate`(게이트 강화, EvidenceBundle) ·
`2026-07-29-stage5-legacy-removal`(Stage 5 삭제) ·
`2026-07-29-post-stage4-small-fixes`(조기 출구 3건) · `2026-07-28-ground-truth-removal`(Stage 4) ·
`2026-07-25-sensor-comparison`(Stage 3, 2단) · `2026-07-25-root-lot-control-group`(Stage 2) ·
`2026-07-24-registry-commonality-realignment` · `2026-07-24-causal-hypothesis-registry` ·
`2026-07-19-status-input-redesign` · `2026-07-13-evidence-tools` ·
`2026-07-12-group-comparison-analysis` · `2026-07-11-urgent-fixes` · `2026-07-10-hybrid-analysis-loop`

---

## 이 저장소에서 반복되는 함정

**해결된 항목의 낡은 처방이 남아 다음 작업자를 되돌린다.** 실제로 여러 번 걸렸다.
그래서 위 3개 문서에 상태 블록을 붙였다. 문서를 고칠 때는 **삭제된 것을 지우기보다
"삭제됐다" 고 적는 편**이 안전하다 — 지우면 다음 사람이 같은 것을 다시 만든다.

삭제된 주요 심볼(문서에서 보이면 낡은 서술이다): `process_log` 테이블 ·
`spec_low`/`spec_high` · `LEGACY_TOOLS_ENABLED` · `aggregate_defects` · `label_counts` ·
`find_counterexamples` · `validate_data_completeness` · `compare_process_logs` ·
`compare_parameter_distribution`. 현재 스키마는 **`yield`·`step_history`·`sensor_log` 3개**다.

**삭제된 진단**: `validate()` 의 `ppid_grain` 과 리포트 `[grain]` 줄 (2026-08-03).
lot 안에서 ppid 가 안 갈리는 것을 조인 오류의 신호로 읽었는데 그게 도메인상 **정상**이라
판별력이 없었고, 실데이터에서 사람을 틀린 판단으로 이끌었다. 대체물은 코드가 아니라
**사람의 원천 쿼리 확인**이다 — `사내-투입-점검표.md` 4-2 가 경위와 절차를 들고 있다.

**개명된 심볼**: `process_step` → **`step_seq`** (2026-07-31, 사내 원천 이름에 맞춤 —
세 테이블·후보 dict 키·도구 파라미터·FDC 요청 키 전부). 문서에서 `process_step` 이
보이면 낡은 서술이다. 값도 공정명(`"Etch"`)이 아니라 **순번 코드**(`"CC002000"` =
제품군 2자리 + 스텝 순서 6자리)로 바뀌었고, 공정명은 신규 컬럼 **`area`** 에 있다.

**개명된 모듈**: `config.py` → **`ya_config.py`** · `console.py` → **`ya_console.py`**
(2026-08-03). 사내에서 돌리니 `import config` 가 저장소 밖의 다른 패키지로 잡혔다.
과거 문서·플랜의 `import config` / `config.py:NN` 은 그대로 두었으니 읽을 때 치환할 것.
