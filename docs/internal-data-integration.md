# 사내 실데이터 연동 — 작업 정리 (2026-07-14)

사내 데이터로 프로토타입을 동작시키기 위한 논의 정리.
기존 미룸 항목은 [deferred-internal-integration.md](deferred-internal-integration.md) 참고 —
이 문서는 그 위에 **데이터 매핑 지식과 신규 발견 수정 항목**을 얹은 작업 계획이다.

## 1. 사내 ID 체계 (ETL 매핑의 전제)

​```
root_lot A45Z5 (물리 묶음, 거의 항상 25매)
 ├── lot_id A45Z5.1   (양산랏 — 대부분 ".1")
 │    ├── 조인 키 A45Z5_01   ← root_lot_id + "_" + zero-pad(wafer_no, 2)
 │    └── ... A45Z5_20
 └── lot_id A45Z5.U2  (평가랏 — ".1" 외 전부)
      └── A45Z5_21 ... A45Z5_25
​```

**용어 (이름 겹침 주의):**
- `wafer_no` = **두 자리 순번 그 자체**(예 `01`). 사내 원천에선 이 값이 `wafer_id`
  라는 컬럼명으로 올 수 있으나, root_lot/lot 정보를 담지 않는다.
- **조인 키** = `root_lot_id` + `_` + `zero-pad(wafer_no, 2)` = 예 `A45Z5_01`.
  전 시스템 공통 키 — 타깃 DB 의 `wafer_id` 컬럼, process_log, EDS 인덱스 모두 이 형태.
- 결론: **타깃 `wafer_id` 컬럼 = 합성 조인 키**, **원천 `wafer_id` = 두 자리 순번**.
  이름이 겹치니 ETL 에서 반드시 구분해 합성한다.

- **wafer_no(순번)만으로는 양산/평가 소속을 알 수 없다** (root_lot 기준 순번).
  → wafer → lot_id 매핑은 원천 데이터에서 별도 확보 **필수**.
- **lot_type 판정은 휴리스틱** (`.1` = 양산, 그 외 = 평가. 예외 있음).
  더 정확한 사내 구분 방법이 있으나 보안상 이 저장소에 두지 않는다 —
  **판정은 ETL 의 함수 하나로 격리**해 사내에서만 교체.
- 25매 완전성 검사는 실무 요구사항 아님 (wafer 단위로 봄).
- 현재 코드는 ID 를 파싱하지 않고 합성 키를 문자열로 그대로 사용 →
  ID 형식은 코드 수정 없이 수용. 단 **조인 키 합성(패딩 포함)은 ETL 책임**.

## 2. ETL 적재 규칙 (`data/load_internal.py` 신규 — 미작성)

목표 스키마: `yield`·`process_log` 2테이블 (generate_dummy.py 의 CREATE TABLE 참조) + 확장.

| 컬럼 | 규칙 |
|------|------|
| `wafer_id` | **원천 그대로 아님** — `root_lot_id + "_" + f"{int(wafer_no):02d}"` 로 합성한 조인 키. 원천 `wafer_id`(두 자리 순번)와 이름이 겹치므로 ETL 에서 구분. yield·process_log·EDS 3곳 바이트 일치 필수 |
| `lot_id` | 원천의 분할 lot ID (파생 불가, 매핑 필수) |
| `root_lot_id` (신규) | lot_id 의 `.` 앞 — wafer_id 의 `_` 앞과 교차 검증 (품질 체크) |
| `lot_type` (신규) | `.1` → 양산, 그 외 → 평가. 격리 함수로 구현 |
| `yield` | 0~100 스케일 확인 (YIELD_THRESHOLD=90.0 과 정합) |
| `defect_type` | NOT NULL — 정상 wafer 는 `"none"` |
| `spec_low`/`spec_high` | **NULL 허용으로 완화** (스펙 없는 아이템 존재) |

- generate_dummy.py 는 더미 전용으로 그대로 둔다 (실행 시 DB 삭제·재생성 주의).
- EDS `/search` 응답의 wafer 식별자도 `{root_lot_id}_{wafer_no}` 체계인지 확인
  (다르면 HttpEDSSearcher 매핑에서 조립 — 미룸 문서 6번과 함께).

## 3. 코드 수정 항목 (2026-07-14 신규 발견)

### 3-1. ~~spec NULL 크래시 3건~~ (2026-07-19 구현 완료, 커밋 b45e61b)

세 함수 모두 NULL-safe 로 수정됨 + 편측 spec 테스트 5개(`tests/test_yield_tools.py`
199~258행)로 검증됨. **재작업 불필요.**

- **`compare_parameter_distribution`** (`_stats`): spec None 행은 이탈 집계에서 제외,
  이탈률 분모는 spec 있는 행 수로. (`is not None` 가드)
- **`find_counterexamples`** (`_in_spec`): spec 없으면 `in_spec: None` 반환.
- **`compare_process_logs`** (violations SQL): `spec_low IS NOT NULL` / `spec_high IS NOT NULL`
  명시 조건으로 편측 spec 도 의도대로 동작.

남은 것: `data/generate_dummy.py` 의 `CREATE TABLE` 은 여전히 `spec_low/high REAL NOT NULL`.
함수는 NULL 을 받아도 안전하지만, 실제 NULL 값은 ETL 적재 스크립트(2절)가 nullable
스키마로 넣어야 나온다 — 즉 스키마 완화는 ETL 쪽 작업.

참고: finalize 게이트는 통과 이력 기반 suspect 라 spec 과 무관하게 동작 — 당장 수정 불요.
spec 없는 파라미터가 원인일 땐 group_spec_violations 가 비므로,
compare_parameter_distribution 의 효과 크기가 보완 근거.

### 3-2. 평가랏 오탐 방지 — ETL 과 함께 (lot_type 컬럼 생긴 뒤)

- **`find_low_yield_lots` 에 lot_type 필터**: 평가랏은 의도적 저수율이 정상이라
  이상 lot 오탐의 주 원인. 양산랏만 대상 또는 별도 임계.

### 3-3. 보류 (실데이터 보고 결정)

- **대조 그룹 root_lot 확장**: 분할 lot 이 작을 때(예: 평가랏 5매) 같은 root_lot 의
  양산랏을 대조군에 포함할지. 평가랏은 공정 조건이 달라 대조군 오염 위험 —
  넓히더라도 양산랏끼리만. 분할 lot 크기 분포 보고 결정.
- **lot 간 대조**: 배치(batch) 장비 공정은 lot 내 wafer 간 차이가 없어 현재의
  lot 내 대조로 못 잡음. 공정 이력이 wafer 단위 장비 기록인지 lot 단위인지 실측 후 결정.

## 4. 확보할 사내 리소스

1. 사내 LLM 서빙: `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY` + **OpenAI 호환 tool-calling 지원 여부**
2. 사내 EDS `/search`: URL + 루트 인증서(.pem) + 실제 응답 스키마 (미룸 4·6번)
3. 수율·공정 이력 추출: 위 2절 스키마로 변환 가능한 형태 (spec 상·하한 포함 여부 확인)

## 5. 진행 순서 (크리티컬 패스)

1. ~~spec NULL 수정 3건 + 테스트~~ (3-1절) — ✅ 완료 (b45e61b)
2. ~~미룸 문서 1~2번~~ (tool 오류 복구, confidence 방어) — ✅ 완료 (dd27cae)
3. **ETL 적재 스크립트** (2절 규칙) → 정합성 검사 (validate_data_completeness 스모크,
   find_low_yield_lots 직접 호출로 상식 검증)
4. **lot_type 필터** (3-2절)
5. **tool 단위 검증** (LLM 없이 실데이터 위에서 직접 호출)
6. **`LLM_MODE=openai` E2E** — mock LLM 은 더미 시나리오 스크립트라 실데이터에서 동작 안 함
7. **임계값 튜닝** (YIELD_THRESHOLD, EDS_MIN_SIMILARITY, MAX_LOOPS)
8. 나머지 미룸 항목 (TLS 기본값, finalize 후속 tool 중단, 실패 경로 테스트 등)
